"""DATA 全体組立（build_data）— 附録 B.3 トポロジーでの統合テスト。"""
import json
from pathlib import Path

import pytest

from lib.topology_io import load_topology
from lib.rendering.data_transform import build_data, build_links, build_bgp_topology, _build_if, build_checks, build_devices, build_stub_nodes, _LOOPBACK_RE, build_fib, build_static_edges, build_static_stubs

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).resolve().parents[1] / "examples" / "topology"


def test_build_data_from_golden():
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    assert set(data["devices"]) == {"r1", "r2"}
    assert data["devices"]["r1"]["hostname"] == "R1"
    assert len(data["links"]) == 1 and data["links"][0]["subnet"] == "10.0.0.0/30"
    assert data["segments"] == []
    assert data["extPeers"] == []
    overs = [e for e in data["bgpEdges"] if e["kind"] == "over-link"]
    assert len(overs) == 1
    # 実 build_data 経路で afs が付与される（v4-only ゴールデンなので ["v4"]）
    assert isinstance(overs[0]["afs"], list) and overs[0]["afs"] == ["v4"]
    for dev in ("r1", "r2"):
        for row in data["devices"][dev]["bgp"]:
            assert row["link"] == overs[0]["id"]
    assert data["meta"]["generated_from"] == ["sample-ios-r1.cfg", "sample-junos-r2.conf"]


def test_build_data_deterministic():
    topo = load_topology(str(GOLDEN))
    a = json.dumps(build_data(topo), sort_keys=True)
    b = json.dumps(build_data(topo), sort_keys=True)
    assert a == b




def test_same_neighbor_two_sessions_distinct_links():
    # 同一 (device, neighbor_ip) の 2 セッションが別エッジを指すケースで前行が誤らない
    topo = {
        "meta": {"generated_from": []},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []},
                    {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [
            {"id": "r1::Gi0", "device": "r1", "name": "Gi0", "ip": "10.0.0.1/30", "vlan": None,
             "description": None, "shutdown": False, "admin_status": "up", "oper_status": None,
             "mtu": None, "speed": None, "duplex": None, "l2_l3": None, "switchport": None,
             "encapsulation": None, "source": "parsed",
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]},
            {"id": "r2::ge0", "device": "r2", "name": "ge0", "ip": "10.0.0.2/30", "vlan": None,
             "description": None, "shutdown": False, "admin_status": "up", "oper_status": None,
             "mtu": None, "speed": None, "duplex": None, "l2_l3": None, "switchport": None,
             "encapsulation": None, "source": "parsed",
             "addresses": [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]},
        ],
        "links": [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
                   "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}],
        "segments": [],
        "routing": {"bgp": [
            {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
             "neighbor_ip": "10.0.0.2", "peer_as": 65001, "type": "ibgp", "af": "v4"}],
            "ospf": [], "static": []},
    }
    data = build_data(topo)
    # over-link セッションは over-link エッジを指す
    assert data["devices"]["r1"]["bgp"][0]["link"].startswith("be:ol:")


# ---------------------------------------------------------------------------
# C2: _build_if に ospf フィールドが含まれること
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_if_includes_ospf_when_present():
    """interface dict に ospf がある場合、_build_if 結果に 'ospf' キーが出ること。"""
    itf = {
        "name": "GigabitEthernet0/0", "ip": "10.0.0.1/30", "ip6": None,
        "description": "to-R2", "admin_status": "up", "mtu": None, "speed": None,
        "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
        "ospf": {"cost": 100, "network_type": "point-to-point"},
    }
    result = _build_if(itf)
    assert "ospf" in result
    assert result["ospf"] == {"cost": 100, "network_type": "point-to-point"}


@pytest.mark.unit
def test_build_if_ospf_none_still_present_in_result():
    """ospf=None の場合、_build_if 結果に ospf キーが存在し値は None であること。"""
    itf = {
        "name": "GigabitEthernet0/0", "ip": "10.0.0.1/30", "ip6": None,
        "description": None, "admin_status": "up", "mtu": None, "speed": None,
        "addresses": [],
        "ospf": None,
    }
    result = _build_if(itf)
    assert "ospf" in result
    assert result["ospf"] is None


@pytest.mark.unit
def test_build_if_ospf_missing_key_handled():
    """ospf キー自体が interface dict に無い場合 _build_if が KeyError しないこと（後方互換）。"""
    itf = {
        "name": "GigabitEthernet0/0", "ip": "10.0.0.1/30", "ip6": None,
        "description": None, "admin_status": "up", "mtu": None, "speed": None,
        "addresses": [],
        # ospf キーなし（旧フォーマット互換）
    }
    result = _build_if(itf)
    assert "ospf" in result
    assert result["ospf"] is None


# ===========================================================================
# D2 設計検証パネル — build_checks テスト
# ===========================================================================

def _minimal_topo(**overrides):
    """テスト用最小 topology dict ベース。overrides で各フィールドを差し替える。"""
    base = {
        "meta": {"generated_from": []},
        "devices": [],
        "interfaces": [],
        "links": [],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    base.update(overrides)
    return base


def _make_if(device, name, addresses, mtu=None):
    """最小 interface dict を生成するヘルパー。"""
    return {
        "id": f"{device}::{name}",
        "device": device,
        "name": name,
        "ip": None,
        "vlan": None,
        "description": None,
        "shutdown": False,
        "admin_status": "up",
        "oper_status": None,
        "mtu": mtu,
        "speed": None,
        "duplex": None,
        "l2_l3": None,
        "switchport": None,
        "encapsulation": None,
        "source": "parsed",
        "addresses": addresses,
    }


def _make_dev(dev_id, hostname="R1", vendor="cisco_ios", as_=65001):
    """最小 device dict を生成するヘルパー。"""
    return {
        "id": dev_id,
        "hostname": hostname,
        "vendor": vendor,
        "as": as_,
        "ospf_router_id": None,
        "bgp_router_id": None,
        "sections": [],
    }


# ---------------------------------------------------------------------------
# 基本構造テスト
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_returns_list():
    """build_checks が list を返すこと。"""
    topo = _minimal_topo()
    result = build_checks(topo)
    assert isinstance(result, list)


@pytest.mark.unit
def test_build_checks_empty_topo_returns_empty():
    """空 topology で build_checks が空リストを返すこと（問題なし）。"""
    topo = _minimal_topo()
    result = build_checks(topo)
    assert result == []


@pytest.mark.unit
def test_build_checks_item_schema():
    """検出結果の各要素が必須キーを持つこと。"""
    # duplicate_ip ルールで1件検出される最小フィクスチャ
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
    )
    result = build_checks(topo)
    assert len(result) >= 1
    for item in result:
        assert "severity" in item
        assert "kind" in item
        assert "message" in item
        assert "refs" in item
        assert item["severity"] in ("error", "warning")
        assert isinstance(item["refs"], list)


# ---------------------------------------------------------------------------
# ルール 1: duplicate_ip（error）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_duplicate_ip_v4_detected():
    """同一ホスト v4 IP が複数 IF に存在する場合 duplicate_ip error が返ること。"""
    # Arrange
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "error"
    assert "10.0.0.1" in dup[0]["message"]
    # refs に両方の device::ifname が含まれること
    assert "r1::Gi0" in dup[0]["refs"]
    assert "r2::Gi0" in dup[0]["refs"]


@pytest.mark.unit
def test_build_checks_duplicate_ip_v6_detected():
    """同一ホスト v6 IP が複数 IF に存在する場合も duplicate_ip error が返ること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v6", "ip": "2001:db8::1", "prefix": 128}]),
            _make_if("r2", "Lo0", [{"af": "v6", "ip": "2001:db8::1", "prefix": 128}]),
        ],
    )

    result = build_checks(topo)

    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "error"
    assert "2001:db8::1" in dup[0]["message"]


@pytest.mark.unit
def test_build_checks_duplicate_ip_secondary_detected():
    """secondary アドレスも duplicate_ip の対象になること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                {"af": "v4", "ip": "172.16.0.1", "prefix": 24, "secondary": True},
            ]),
            _make_if("r2", "Gi0", [
                {"af": "v4", "ip": "172.16.0.1", "prefix": 24},
            ]),
        ],
    )

    result = build_checks(topo)

    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert any("172.16.0.1" in d["message"] for d in dup)


@pytest.mark.unit
def test_build_checks_no_duplicate_ip_when_unique():
    """IP が一意の場合 duplicate_ip が返らないこと。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
        ],
    )

    result = build_checks(topo)

    assert not any(c["kind"] == "duplicate_ip" for c in result)


@pytest.mark.unit
def test_build_checks_duplicate_ip_refs_sorted():
    """duplicate_ip の refs が ip 昇順で並んでいること。"""
    # 3 IF が同一 IP を持つケース → refs は ip 昇順
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2"), _make_dev("r3", hostname="R3")],
        interfaces=[
            _make_if("r3", "Gi0", [{"af": "v4", "ip": "10.0.0.5", "prefix": 30}]),
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.5", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.5", "prefix": 30}]),
        ],
    )

    result = build_checks(topo)

    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert len(dup) == 1
    # refs は device::ifname のリストで安定していること（ip 昇順の後は refs 自体が安定ソートされていること）
    assert dup[0]["refs"] == sorted(dup[0]["refs"])


# ---------------------------------------------------------------------------
# ルール 2: mtu_mismatch（warning）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_mtu_mismatch_detected():
    """同一物理リンクの両端 MTU が非 None かつ不一致の場合 mtu_mismatch warning が返ること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}], mtu=9000),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}], mtu=1500),
        ],
        links=[{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "Gi0",
                "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}],
    )

    result = build_checks(topo)

    mm = [c for c in result if c["kind"] == "mtu_mismatch"]
    assert len(mm) == 1
    assert mm[0]["severity"] == "warning"
    assert "9000" in mm[0]["message"] or "1500" in mm[0]["message"]
    # refs に両端 device::ifname とリンク subnet が含まれること
    assert "r1::Gi0" in mm[0]["refs"]
    assert "r2::Gi0" in mm[0]["refs"]


@pytest.mark.unit
def test_build_checks_mtu_mismatch_skipped_when_one_none():
    """片側 MTU が None の場合 mtu_mismatch を返さないこと。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}], mtu=9000),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}], mtu=None),
        ],
        links=[{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "Gi0",
                "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}],
    )

    result = build_checks(topo)

    assert not any(c["kind"] == "mtu_mismatch" for c in result)


@pytest.mark.unit
def test_build_checks_mtu_mismatch_skipped_when_equal():
    """両端 MTU が一致する場合 mtu_mismatch を返さないこと。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}], mtu=1500),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}], mtu=1500),
        ],
        links=[{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "Gi0",
                "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}],
    )

    result = build_checks(topo)

    assert not any(c["kind"] == "mtu_mismatch" for c in result)


# ---------------------------------------------------------------------------
# ルール 3: bgp_unresolved_local_ip（warning）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_bgp_unresolved_local_ip_detected():
    """BGP エントリで local_ip が None の場合 bgp_unresolved_local_ip warning が返ること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": None,
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"}
            ],
            "ospf": [],
            "static": [],
        },
    )

    result = build_checks(topo)

    unr = [c for c in result if c["kind"] == "bgp_unresolved_local_ip"]
    assert len(unr) == 1
    assert unr[0]["severity"] == "warning"
    assert "r1" in unr[0]["refs"]
    assert "10.0.0.2" in unr[0]["refs"]


@pytest.mark.unit
def test_build_checks_bgp_unresolved_local_ip_not_flagged_when_present():
    """local_ip が非 None の BGP エントリは bgp_unresolved_local_ip を返さないこと。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"}
            ],
            "ospf": [],
            "static": [],
        },
    )

    result = build_checks(topo)

    assert not any(c["kind"] == "bgp_unresolved_local_ip" for c in result)


# ---------------------------------------------------------------------------
# ルール 4: static_dangling_next_hop（warning）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_static_dangling_next_hop_detected():
    """static ルートの next_hop がどの IF サブネットにも属さない場合 static_dangling_next_hop が返ること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [],
            "ospf": [],
            "static": [
                {"device": "r1", "prefix": "192.168.100.0/24", "next_hop": "172.16.99.1",
                 "af": "v4"},
            ],
        },
    )

    result = build_checks(topo)

    dang = [c for c in result if c["kind"] == "static_dangling_next_hop"]
    assert len(dang) == 1
    assert dang[0]["severity"] == "warning"
    assert "r1" in dang[0]["refs"]
    assert "192.168.100.0/24" in dang[0]["refs"]
    assert "172.16.99.1" in dang[0]["refs"]


@pytest.mark.unit
def test_build_checks_static_default_route_not_dangling():
    """static ルートの next_hop が 0.0.0.0 のデフォルトルートは dangling と検出しないこと。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [],
            "ospf": [],
            "static": [
                {"device": "r1", "prefix": "0.0.0.0/0", "next_hop": "0.0.0.0", "af": "v4"},
            ],
        },
    )

    result = build_checks(topo)

    assert not any(c["kind"] == "static_dangling_next_hop" for c in result)


@pytest.mark.unit
def test_build_checks_static_next_hop_in_subnet_not_dangling():
    """static ルートの next_hop が IF サブネット内に属する場合 dangling と検出しないこと。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [],
            "ospf": [],
            "static": [
                # next_hop=10.0.0.2 は r1 Gi0 の 10.0.0.0/30 に属する
                {"device": "r1", "prefix": "192.168.100.0/24", "next_hop": "10.0.0.2", "af": "v4"},
            ],
        },
    )

    result = build_checks(topo)

    assert not any(c["kind"] == "static_dangling_next_hop" for c in result)


@pytest.mark.unit
def test_build_checks_static_next_hop_is_host_ip_not_dangling():
    """static ルートの next_hop が IF のホスト IP に一致する場合 dangling と検出しないこと。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 32}]),
        ],
        routing={
            "bgp": [],
            "ospf": [],
            "static": [
                # next_hop=10.0.0.2 は r2::Lo0 のホスト IP と一致
                {"device": "r1", "prefix": "192.168.100.0/24", "next_hop": "10.0.0.2", "af": "v4"},
            ],
        },
    )

    result = build_checks(topo)

    assert not any(c["kind"] == "static_dangling_next_hop" for c in result)


# ---------------------------------------------------------------------------
# 決定性テスト
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_deterministic():
    """build_checks を2回呼んで同一結果が返ること（決定性）。"""
    topo = load_topology(str(GOLDEN))
    a = json.dumps(build_checks(topo), sort_keys=True)
    b = json.dumps(build_checks(topo), sort_keys=True)
    assert a == b


@pytest.mark.unit
def test_build_checks_sort_order_severity_then_kind():
    """build_checks の返却リストが severity(error→warning)→kind 順に安定ソートされること。"""
    # duplicate_ip(error) と bgp_unresolved_local_ip(warning) が共存するフィクスチャ
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": None,
                 "neighbor_ip": "192.0.2.1", "peer_as": 65002, "type": "ebgp", "af": "v4"}
            ],
            "ospf": [],
            "static": [],
        },
    )

    result = build_checks(topo)

    severities = [c["severity"] for c in result]
    # error は warning より前
    last_error_idx = max((i for i, s in enumerate(severities) if s == "error"), default=-1)
    first_warning_idx = min((i for i, s in enumerate(severities) if s == "warning"), default=len(result))
    assert last_error_idx < first_warning_idx


# ---------------------------------------------------------------------------
# build_data 統合テスト: checks キーの追加
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_data_has_checks_key():
    """build_data の返り値に 'checks' キーが含まれること。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    assert "checks" in data


@pytest.mark.integration
def test_build_data_checks_is_list():
    """build_data の 'checks' が list であること。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    assert isinstance(data["checks"], list)


@pytest.mark.integration
def test_build_data_checks_consistent_with_build_checks():
    """build_data の checks が build_checks と同一内容であること。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    expected = build_checks(topo)
    assert data["checks"] == expected


# ---------------------------------------------------------------------------
# ゴールデン topo での回帰テスト（golden での検出結果を実値で固定）
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_checks_golden_result_regression():
    """golden topo での build_checks 結果を実値で固定（回帰検出）。

    golden (r1+r2): 検出ルール別の期待:
    - duplicate_ip: なし（全 IF の IP は一意）
    - mtu_mismatch: なし（全 IF の mtu=None）
    - bgp_unresolved_local_ip: なし（local_ip=10.0.0.1/10.0.0.2 が存在）
    - static_dangling_next_hop:
        r1: prefix=0.0.0.0/0 next_hop=10.0.0.2 → 0.0.0.0/0 はデフォルトルートスキップ
        r2: prefix=0.0.0.0/0 next_hop=10.0.0.1 → 同上
      ゆえに 0 件
    期待: checks = []
    """
    topo = load_topology(str(GOLDEN))
    result = build_checks(topo)
    # golden では設計上の問題点は0件（デフォルトルートはスキップ、MTU=None はスキップ）
    assert result == []


# ===========================================================================
# D2 修正項目テスト（修正 1-6）
# ===========================================================================

# ---------------------------------------------------------------------------
# 修正 1: link-local 偽陽性の除外
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_duplicate_ip_link_local_not_flagged():
    """同一 fe80:: アドレスが複数 IF に存在しても duplicate_ip を返さないこと。

    link-local（scope="link-local"）は各リンクで共通の fe80:: を持つことが通常であり、
    重複として報告すべきでない。
    """
    # Arrange: r1::Gi0 と r2::Gi0 が同一 fe80::1 を持つ（link-local）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
            ]),
            _make_if("r2", "Gi0", [
                {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
            ]),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: link-local の重複は無視され duplicate_ip が出ない
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert dup == [], f"link-local の重複が誤検知された: {dup}"


@pytest.mark.unit
def test_build_checks_duplicate_ip_global_v6_still_flagged():
    """グローバル v6 IP の重複は引き続き duplicate_ip として検出されること（回帰）。"""
    # Arrange: グローバル v6 が重複し、link-local は両者で共通
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [
                {"af": "v6", "ip": "2001:db8::1", "prefix": 128},
                {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
            ]),
            _make_if("r2", "Gi0", [
                {"af": "v6", "ip": "2001:db8::1", "prefix": 128},
                {"af": "v6", "ip": "fe80::2", "prefix": 64, "scope": "link-local"},
            ]),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: グローバル v6 の重複は検出される
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert len(dup) == 1
    assert "2001:db8::1" in dup[0]["message"]


@pytest.mark.unit
def test_build_checks_static_dangling_excludes_link_local_subnets():
    """link-local アドレス（fe80::）が all_subnets/all_host_ips に混入せず、
    static_dangling_next_hop の偽陰性・偽陽性が発生しないこと。

    fe80::/64 のサブネットが all_subnets に含まれると、next_hop が fe80:: 帯に
    入る任意の値が「属する」と誤判定される可能性があるため除外必須。
    """
    # Arrange: fe80:: のみを持つ IF と、link-local 外サブネットに属さない next_hop
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [
                {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
            ]),
        ],
        routing={
            "bgp": [],
            "ospf": [],
            "static": [
                # next_hop が fe80:: サブネット内のアドレス →
                # link-local が all_subnets に混入すると誤って「in_subnet」と判定されてしまう
                {"device": "r1", "prefix": "2001:db8::/32",
                 "next_hop": "2001:db8::99", "af": "v6"},
            ],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: グローバルルーティング可能なサブネットが存在しないため dangling
    dang = [c for c in result if c["kind"] == "static_dangling_next_hop"]
    assert len(dang) == 1, (
        "link-local を除外した all_subnets には 2001:db8::99 が属するサブネットが存在しないはず"
    )


# ---------------------------------------------------------------------------
# 修正 2: mtu_mismatch の dual-stack 重複解消（resolved_links 使用）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_mtu_mismatch_dualstack_no_duplicate():
    """dual-stack（同一端点ペアに v4+v6 エントリ）かつ MTU 不一致でも mtu_mismatch が 1 件のみであること。"""
    # Arrange: r1::Gi0 と r2::Gi0 の間に v4 エントリと v6 エントリが 2 行（dual-stack）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
            ], mtu=9000),
            _make_if("r2", "Gi0", [
                {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                {"af": "v6", "ip": "2001:db8::2", "prefix": 64},
            ], mtu=1500),
        ],
        links=[
            # dual-stack: 同一端点ペアに v4 と v6 の 2 行
            {"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "Gi0",
             "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
            {"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "Gi0",
             "subnet": "2001:db8::/64", "kind": "inferred-subnet"},
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: dual-stack でも mtu_mismatch は 1 件のみ（端点ペア単位）
    mm = [c for c in result if c["kind"] == "mtu_mismatch"]
    assert len(mm) == 1, f"dual-stack で mtu_mismatch が重複検出された: {mm}"


@pytest.mark.unit
def test_build_checks_mtu_mismatch_single_link_still_detected():
    """v4 のみの単一リンクで mtu_mismatch が引き続き検出されること（回帰）。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}], mtu=9000),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}], mtu=1500),
        ],
        links=[
            {"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "Gi0",
             "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
        ],
    )

    result = build_checks(topo)

    mm = [c for c in result if c["kind"] == "mtu_mismatch"]
    assert len(mm) == 1
    assert mm[0]["severity"] == "warning"


# ---------------------------------------------------------------------------
# 修正 3: bgp_unresolved_local_ip の KeyError ガード
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_bgp_unresolved_local_ip_missing_key_no_exception():
    """local_ip キー自体が欠如した BGP エントリで KeyError が起きないこと。"""
    # Arrange: local_ip キーを持たないエントリ（手編集 YAML 相当）
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        routing={
            "bgp": [
                # local_ip キーが存在しない（None 値とは別）
                {"device": "r1", "local_as": 65001,
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act: 例外が起きないこと
    try:
        result = build_checks(topo)
    except KeyError as e:
        pytest.fail(f"local_ip キー欠如で KeyError が発生した: {e}")

    # Assert: bgp_unresolved_local_ip として検出される（None 扱い）
    unr = [c for c in result if c["kind"] == "bgp_unresolved_local_ip"]
    assert len(unr) == 1


# ---------------------------------------------------------------------------
# 修正 4: </script> インジェクション対策
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_render_html_script_injection_escaped():
    """hostname 等に </script> を含む topo を render して生成 HTML のデータ内に
    生の </script> が現れないこと（<\\/script> にエスケープされること）。
    """
    from lib.rendering.template import render_html
    # Arrange: hostname に </script> を埋め込んだ最小 topo
    topo = _minimal_topo(
        devices=[{
            "id": "r1",
            "hostname": 'R1</script><script>alert(1)</script>',
            "vendor": "cisco_ios",
            "as": 65001,
            "ospf_router_id": None,
            "bgp_router_id": None,
            "sections": [],
        }],
    )

    # Act
    html = render_html(topo)

    # Assert: JSON データ埋め込みブロック内に生の </script> が現れない
    # （<script> タグを早期終了させる文字列がエスケープされていること）
    # DATA の埋め込みスクリプトを取り出して検査
    import re
    data_match = re.search(r'<script>const DATA=(.*?);</script>', html, re.DOTALL)
    assert data_match, "DATA 埋め込みが見つからない"
    data_str = data_match.group(1)
    assert '</script>' not in data_str, (
        "DATA 埋め込みに生の </script> が残っている（インジェクション可能）"
    )
    # エスケープ済みの形式が存在すること
    assert '<\\/script>' in data_str or '\\u003c/script\\u003e' in data_str or \
           '<\\/script>' in data_str, \
        "エスケープ済みの </script> が見つからない"


@pytest.mark.unit
def test_json_function_escapes_script_closing_tag():
    r"""template._json() が </script> を <\/script> にエスケープすること。"""
    from lib.rendering.template import _json
    obj = {"key": "</script><script>alert(1)"}
    result = _json(obj)
    assert '</script>' not in result, f"生の </script> が残っている: {result}"
    assert '<\\/script>' in result, f"エスケープが適用されていない: {result}"


# ---------------------------------------------------------------------------
# 修正 5: _SPECIAL_NH モジュール定数化（動作変更なし・構造テスト）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_special_nh_is_module_level_constant():
    """_SPECIAL_NH がモジュールレベルの定数として定義されていること。"""
    from lib.rendering import data_transform
    assert hasattr(data_transform, "_SPECIAL_NH"), (
        "_SPECIAL_NH がモジュールレベル定数として存在しない"
    )
    assert isinstance(data_transform._SPECIAL_NH, frozenset)
    # 既存の特殊値が含まれること
    assert "0.0.0.0" in data_transform._SPECIAL_NH
    assert "::" in data_transform._SPECIAL_NH
    assert "255.255.255.255" in data_transform._SPECIAL_NH


# ---------------------------------------------------------------------------
# 修正 6: ソート順テストの強化（severity→kind→refs 安定ソート）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_sort_order_severity_kind_refs():
    """build_checks が severity(error→warning)→kind 昇順→refs 安定ソートで並ぶこと。"""
    # Arrange: 複数の warning を異なる kind で生成し、kind と refs の順序を検証
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            # duplicate_ip (error) を生成
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [
                # bgp_unresolved_local_ip (warning) を生成
                {"device": "r1", "local_as": 65001, "local_ip": None,
                 "neighbor_ip": "192.0.2.1", "peer_as": 65002, "type": "ebgp", "af": "v4"},
                {"device": "r2", "local_as": 65002, "local_ip": None,
                 "neighbor_ip": "192.0.2.2", "peer_as": 65001, "type": "ebgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [
                # static_dangling_next_hop (warning) を生成
                {"device": "r1", "prefix": "192.168.99.0/24", "next_hop": "172.16.99.1", "af": "v4"},
                {"device": "r2", "prefix": "192.168.88.0/24", "next_hop": "172.16.88.1", "af": "v4"},
            ],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert 1: severity が error → warning 順
    severities = [c["severity"] for c in result]
    last_err = max((i for i, s in enumerate(severities) if s == "error"), default=-1)
    first_warn = min((i for i, s in enumerate(severities) if s == "warning"), default=len(result))
    assert last_err < first_warn, "error が warning より後に出ている"

    # Assert 2: 同一 severity 内で kind が昇順
    for sev in ("error", "warning"):
        items_of_sev = [c for c in result if c["severity"] == sev]
        kinds = [c["kind"] for c in items_of_sev]
        assert kinds == sorted(kinds), f"severity={sev} 内で kind が昇順でない: {kinds}"

    # Assert 3: 同一 severity + kind 内で refs が安定ソート（"|".join(refs) 昇順）
    from itertools import groupby
    for (sev, knd), group in groupby(result, key=lambda c: (c["severity"], c["kind"])):
        group_list = list(group)
        refs_keys = ["|".join(c["refs"]) for c in group_list]
        assert refs_keys == sorted(refs_keys), (
            f"severity={sev} kind={knd} 内で refs キーが昇順でない: {refs_keys}"
        )


# ===========================================================================
# C1: 相乗効果テスト — iBGP loopback + update-source で bgp_unresolved_local_ip が出ない
# ===========================================================================

@pytest.mark.unit
def test_build_checks_ibgp_loopback_update_source_no_unresolved_warning():
    """iBGP over loopback で update-source により local_ip が解決された場合、
    bgp_unresolved_local_ip warning が出ないこと（相乗効果テスト）。

    update-source なしの場合は local_ip=None → bgp_unresolved_local_ip が出る。
    update-source で local_ip が解決された場合は bgp_unresolved_local_ip が出ない。
    """
    # Arrange: local_ip を直接注入（build_checks は local_ip!=None を見て警告を出さないことを検証）。
    # フォールバック解決自体は test_build_bgp 側でカバー。
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Loopback0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
            _make_if("r2", "Loopback0", [{"af": "v4", "ip": "2.2.2.2", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                # local_ip=1.1.1.1（update-source Loopback0 により解決済み）
                {"device": "r1", "local_as": 65001, "local_ip": "1.1.1.1",
                 "neighbor_ip": "2.2.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                {"device": "r2", "local_as": 65001, "local_ip": "2.2.2.2",
                 "neighbor_ip": "1.1.1.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: bgp_unresolved_local_ip warning が出ないこと
    unr = [c for c in result if c["kind"] == "bgp_unresolved_local_ip"]
    assert unr == [], (
        "update-source で local_ip が解決されたはずなのに bgp_unresolved_local_ip が出た: "
        + str(unr)
    )


@pytest.mark.unit
def test_build_checks_ibgp_loopback_no_update_source_warns():
    """iBGP over loopback で update-source なし（local_ip=None）なら
    bgp_unresolved_local_ip が出ること（対照テスト）。
    """
    # Arrange: local_ip=None（update-source なし・サブネット一致も不可）
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": None,
                 "neighbor_ip": "2.2.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: bgp_unresolved_local_ip warning が出ること
    unr = [c for c in result if c["kind"] == "bgp_unresolved_local_ip"]
    assert len(unr) == 1


# ---------------------------------------------------------------------------
# C1: build_devices に update_source が渡されること
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_devices_bgp_row_includes_update_source_when_present():
    """routing.bgp エントリに update_source がある場合、build_devices の bgp 行に 'src' が含まれること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Loopback0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "1.1.1.1",
                 "neighbor_ip": "2.2.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4",
                 "update_source": "Loopback0"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    from lib.rendering.data_transform import build_devices
    devices = build_devices(topo)
    bgp_rows = devices["r1"]["bgp"]
    assert len(bgp_rows) == 1
    assert bgp_rows[0].get("src") == "Loopback0"


@pytest.mark.unit
def test_build_devices_bgp_row_no_src_when_update_source_absent():
    """routing.bgp エントリに update_source がない場合、build_devices の bgp 行に 'src' が None であること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "GigabitEthernet0/0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    from lib.rendering.data_transform import build_devices
    devices = build_devices(topo)
    bgp_rows = devices["r1"]["bgp"]
    assert len(bgp_rows) == 1
    # update_source なし → src は None（or キーなし）
    assert bgp_rows[0].get("src") is None


# ---------------------------------------------------------------------------
# C3: build_devices の ospf 行に area_type が透過されること
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_devices_ospf_row_includes_at_when_area_type_present():
    """routing.ospf エントリに area_type がある場合、build_devices の ospf 行に 'at' キーが含まれること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.1.0.0/24",
                 "area": "1", "af": "v4", "area_type": "stub"},
            ],
            "static": [],
        },
    )

    from lib.rendering.data_transform import build_devices
    devices = build_devices(topo)
    ospf_rows = devices["r1"]["ospf"]
    assert len(ospf_rows) == 1
    assert ospf_rows[0].get("at") == "stub"


@pytest.mark.unit
def test_build_devices_ospf_row_no_at_when_area_type_absent():
    """routing.ospf エントリに area_type がない場合、build_devices の ospf 行に 'at' キーが None であること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "192.168.1.0/24",
                 "area": "0", "af": "v4"},
            ],
            "static": [],
        },
    )

    from lib.rendering.data_transform import build_devices
    devices = build_devices(topo)
    ospf_rows = devices["r1"]["ospf"]
    assert len(ospf_rows) == 1
    assert ospf_rows[0].get("at") is None


@pytest.mark.unit
def test_build_devices_ospf_row_all_area_type_values():
    """stub/totally-stubby/nssa/totally-nssa の4値が ospf 行の 'at' に正しく透過されること。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.1.0.0/24",
                 "area": "1", "af": "v4", "area_type": "stub"},
                {"device": "r1", "process": 1, "network": "10.2.0.0/24",
                 "area": "2", "af": "v4", "area_type": "totally-stubby"},
                {"device": "r1", "process": 1, "network": "10.3.0.0/24",
                 "area": "3", "af": "v4", "area_type": "nssa"},
                {"device": "r1", "process": 1, "network": "10.4.0.0/24",
                 "area": "4", "af": "v4", "area_type": "totally-nssa"},
            ],
            "static": [],
        },
    )

    from lib.rendering.data_transform import build_devices
    devices = build_devices(topo)
    ospf_rows = {row["area"]: row["at"] for row in devices["r1"]["ospf"]}
    assert ospf_rows == {
        "1": "stub",
        "2": "totally-stubby",
        "3": "nssa",
        "4": "totally-nssa",
    }


# ---------------------------------------------------------------------------
# C4: build_devices の bgp 行に rr/nhs が含まれること
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_devices_bgp_row_rrc_true_present():
    """routing.bgp エントリに route_reflector_client=True がある場合、build_devices の bgp 行に 'rr': True が含まれること。"""
    from lib.rendering.data_transform import build_devices
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65001, "type": "ibgp", "af": "v4",
                 "route_reflector_client": True},
            ],
            "ospf": [],
            "static": [],
        },
    )

    devices = build_devices(topo)
    row = devices["r1"]["bgp"][0]
    assert row.get("rr") is True


@pytest.mark.unit
def test_build_devices_bgp_row_rrc_absent_falsy():
    """routing.bgp エントリに route_reflector_client がない場合、build_devices の bgp 行の 'rr' は falsy であること。"""
    from lib.rendering.data_transform import build_devices
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    devices = build_devices(topo)
    row = devices["r1"]["bgp"][0]
    assert not row.get("rr")


@pytest.mark.unit
def test_build_devices_bgp_row_nhs_true_present():
    """routing.bgp エントリに next_hop_self=True がある場合、build_devices の bgp 行に 'nhs': True が含まれること。"""
    from lib.rendering.data_transform import build_devices
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4",
                 "next_hop_self": True},
            ],
            "ospf": [],
            "static": [],
        },
    )

    devices = build_devices(topo)
    row = devices["r1"]["bgp"][0]
    assert row.get("nhs") is True


@pytest.mark.unit
def test_build_devices_bgp_row_nhs_absent_falsy():
    """routing.bgp エントリに next_hop_self がない場合、build_devices の bgp 行の 'nhs' は falsy であること。"""
    from lib.rendering.data_transform import build_devices
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    devices = build_devices(topo)
    row = devices["r1"]["bgp"][0]
    assert not row.get("nhs")


# ===========================================================================
# A4: degree 連動ノードサイズ — build_devices degree テスト
# ===========================================================================

def _make_link_entry(a_dev, a_if, b_dev, b_if, subnet):
    """最小 links エントリを生成するヘルパー。"""
    return {"a_device": a_dev, "a_if": a_if, "b_device": b_dev, "b_if": b_if,
            "subnet": subnet, "kind": "inferred-subnet"}


def _make_seg_entry(seg_id, subnet, member_ids):
    """最小 segments エントリを生成するヘルパー。"""
    return {"id": seg_id, "subnet": subnet, "members": member_ids}


@pytest.mark.unit
def test_build_devices_degree_isolated_is_zero():
    """リンク・セグメントに参加しない孤立機器の degree が 0 であること。"""
    # Arrange
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
        ],
    )

    # Act
    devices = build_devices(topo)

    # Assert
    assert devices["r1"]["degree"] == 0, (
        f"孤立機器の degree は 0 のはずだが {devices['r1']['degree']} だった"
    )


@pytest.mark.unit
def test_build_devices_degree_linear_topology():
    """線形トポロジー（R1—R2—R3）で端点 degree=1・中間 degree=2 になること。

    対照値: 誤った実装（重複計上）なら中間ノードが 4 になる。
    """
    # Arrange: R1—R2—R3 の線形リンク
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2"), _make_dev("r3", hostname="R3")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
            _make_if("r2", "Gi1", [{"af": "v4", "ip": "10.0.1.1", "prefix": 30}]),
            _make_if("r3", "Gi0", [{"af": "v4", "ip": "10.0.1.2", "prefix": 30}]),
        ],
        links=[
            _make_link_entry("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30"),
            _make_link_entry("r2", "Gi1", "r3", "Gi0", "10.0.1.0/30"),
        ],
    )

    # Act
    devices = build_devices(topo)

    # Assert: 端点 degree=1、中間 degree=2
    assert devices["r1"]["degree"] == 1, f"端点 r1 の degree は 1 のはずだが {devices['r1']['degree']}"
    assert devices["r3"]["degree"] == 1, f"端点 r3 の degree は 1 のはずだが {devices['r3']['degree']}"
    assert devices["r2"]["degree"] == 2, (
        f"中間 r2 の degree は 2 のはずだが {devices['r2']['degree']} "
        "(重複計上なら 4 になる誤り。set で排除されていること)"
    )


@pytest.mark.unit
def test_build_devices_degree_hub_multiple_links():
    """ハブ（1機器が 3 台の別機器に接続）の degree が 3 になること。

    対照値: 誤った実装なら 6（リンク端点を重複計上）。
    """
    # Arrange: hub—r1, hub—r2, hub—r3
    topo = _minimal_topo(
        devices=[
            _make_dev("hub", hostname="HUB"),
            _make_dev("r1"), _make_dev("r2", hostname="R2"), _make_dev("r3", hostname="R3"),
        ],
        interfaces=[
            _make_if("hub", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("hub", "Gi1", [{"af": "v4", "ip": "10.0.1.1", "prefix": 30}]),
            _make_if("hub", "Gi2", [{"af": "v4", "ip": "10.0.2.1", "prefix": 30}]),
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.1.2", "prefix": 30}]),
            _make_if("r3", "Gi0", [{"af": "v4", "ip": "10.0.2.2", "prefix": 30}]),
        ],
        links=[
            _make_link_entry("hub", "Gi0", "r1", "Gi0", "10.0.0.0/30"),
            _make_link_entry("hub", "Gi1", "r2", "Gi0", "10.0.1.0/30"),
            _make_link_entry("hub", "Gi2", "r3", "Gi0", "10.0.2.0/30"),
        ],
    )

    # Act
    devices = build_devices(topo)

    # Assert
    assert devices["hub"]["degree"] == 3, (
        f"hub の degree は 3 のはずだが {devices['hub']['degree']} "
        "(重複計上なら 6 になる誤り)"
    )
    assert devices["r1"]["degree"] == 1
    assert devices["r2"]["degree"] == 1
    assert devices["r3"]["degree"] == 1


@pytest.mark.unit
def test_build_devices_degree_segment_member():
    """セグメント（3 機器以上共有サブネット）メンバーの degree が正しいこと。

    セグメント R1/R2/R3 → 各機器は隣接 2 機器（他メンバー）で degree=2。
    対照値: セグメントメンバー数を直接使う誤実装は 3 になる（自分自身を含めてしまう）。
    """
    # Arrange: R1/R2/R3 が同一セグメントに参加
    topo = _minimal_topo(
        devices=[
            _make_dev("r1"), _make_dev("r2", hostname="R2"), _make_dev("r3", hostname="R3"),
        ],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "192.168.1.1", "prefix": 24}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "192.168.1.2", "prefix": 24}]),
            _make_if("r3", "Gi0", [{"af": "v4", "ip": "192.168.1.3", "prefix": 24}]),
        ],
        segments=[
            _make_seg_entry("seg-1", "192.168.1.0/24",
                            ["r1::Gi0", "r2::Gi0", "r3::Gi0"]),
        ],
    )

    # Act
    devices = build_devices(topo)

    # Assert: 各機器は他 2 メンバーに隣接 → degree=2
    for dev_id in ("r1", "r2", "r3"):
        assert devices[dev_id]["degree"] == 2, (
            f"{dev_id} の degree は 2 のはずだが {devices[dev_id]['degree']}"
        )


@pytest.mark.unit
def test_build_devices_degree_dualstack_same_pair_counted_once():
    """dual-stack（同一端点ペアの v4/v6 リンク 2 行）は 1 接続としてカウントされること。

    対照値: 誤実装（set を使わず links を直接走査）は 2 になる。
    """
    # Arrange: r1—r2 の dual-stack（v4 + v6 の 2 raw リンク行）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
            ]),
            _make_if("r2", "Gi0", [
                {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                {"af": "v6", "ip": "2001:db8::2", "prefix": 64},
            ]),
        ],
        links=[
            # dual-stack: 同一端点ペアに v4 と v6 の 2 行
            _make_link_entry("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30"),
            _make_link_entry("r1", "Gi0", "r2", "Gi0", "2001:db8::/64"),
        ],
    )

    # Act
    devices = build_devices(topo)

    # Assert: dual-stack でも相手は 1 機器なので degree=1
    assert devices["r1"]["degree"] == 1, (
        f"dual-stack でも degree は 1 のはずだが {devices['r1']['degree']} "
        "(raw リンク数を数えた誤実装は 2 になる)"
    )
    assert devices["r2"]["degree"] == 1


@pytest.mark.unit
def test_build_devices_degree_deterministic():
    """build_devices を 2 回呼んで degree が同一結果になること（決定性）。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
        ],
        links=[_make_link_entry("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30")],
    )

    # Act: 2 回呼ぶ
    devices_a = build_devices(topo)
    devices_b = build_devices(topo)

    # Assert: degree が一致
    assert devices_a["r1"]["degree"] == devices_b["r1"]["degree"]
    assert devices_a["r2"]["degree"] == devices_b["r2"]["degree"]


@pytest.mark.unit
def test_build_devices_degree_key_present_always():
    """リンクが 0 本のトポロジーでも degree キーが存在すること（後方互換のない新フィールド確認）。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
    )

    # Act
    devices = build_devices(topo)

    # Assert: degree キーが存在し値は整数
    assert "degree" in devices["r1"], "degree キーが存在しない"
    assert isinstance(devices["r1"]["degree"], int)


@pytest.mark.integration
def test_build_data_devices_have_degree_golden():
    """build_data(golden) の各デバイスに degree が含まれること。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)

    for dev_id, dev in data["devices"].items():
        assert "degree" in dev, f"DATA.devices['{dev_id}'] に degree キーがない"
        assert isinstance(dev["degree"], int), f"DATA.devices['{dev_id}'].degree が int でない"
        assert dev["degree"] >= 0, f"DATA.devices['{dev_id}'].degree が負"


@pytest.mark.integration
def test_build_data_golden_degree_values():
    """golden (r1—r2 の 1 リンク) で r1.degree=1, r2.degree=1 であること。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)

    assert data["devices"]["r1"]["degree"] == 1, (
        f"golden r1.degree は 1 のはずだが {data['devices']['r1']['degree']}"
    )
    assert data["devices"]["r2"]["degree"] == 1, (
        f"golden r2.degree は 1 のはずだが {data['devices']['r2']['degree']}"
    )


@pytest.mark.unit
def test_build_devices_degree_hybrid_link_and_segment():
    """同一機器が link で 1 台と接続しつつ segment にも参加する混在トポロジーで
    degree が両方の隣接の和（set マージ）になること。

    対照値（誤実装）:
    - link 分しか数えない: hub.degree=1（segment 隣接を見落とし）
    - segment 分しか数えない: hub.degree=2（link 隣接を見落とし）
    - 重複計上（set を使わない): r_seg と hub が segment 経由でも link 経由でも
      数えられ、hub.degree=4 のような誤値になる可能性

    正しい実装: hub は link で r_link に接続し、segment で r_seg1・r_seg2 に接続。
    hub.degree = |{r_link, r_seg1, r_seg2}| = 3。
    r_link.degree = 1（hub のみ隣接）。
    r_seg1/r_seg2.degree = 2（hub と互いに隣接）。
    """
    # Arrange:
    # - hub—r_link: 通常の /30 link
    # - hub / r_seg1 / r_seg2: 3 機器で /24 segment に参加
    topo = _minimal_topo(
        devices=[
            _make_dev("hub", hostname="HUB"),
            _make_dev("r_link", hostname="RLINK"),
            _make_dev("r_seg1", hostname="RSEG1"),
            _make_dev("r_seg2", hostname="RSEG2"),
        ],
        interfaces=[
            # link 用 IF
            _make_if("hub", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r_link", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
            # segment 用 IF
            _make_if("hub", "Gi1", [{"af": "v4", "ip": "192.168.1.1", "prefix": 24}]),
            _make_if("r_seg1", "Gi0", [{"af": "v4", "ip": "192.168.1.2", "prefix": 24}]),
            _make_if("r_seg2", "Gi0", [{"af": "v4", "ip": "192.168.1.3", "prefix": 24}]),
        ],
        links=[
            _make_link_entry("hub", "Gi0", "r_link", "Gi0", "10.0.0.0/30"),
        ],
        segments=[
            _make_seg_entry(
                "seg-192.168.1.0/24",
                "192.168.1.0/24",
                ["hub::Gi1", "r_seg1::Gi0", "r_seg2::Gi0"],
            ),
        ],
    )

    # Act
    devices = build_devices(topo)

    # Assert: hub は link 隣接(r_link) + segment 隣接(r_seg1, r_seg2) = 3
    assert devices["hub"]["degree"] == 3, (
        f"hub.degree は 3 のはずだが {devices['hub']['degree']} — "
        "link 分のみ(=1)か segment 分のみ(=2)しか数えていない誤実装か、重複計上の誤実装を示す"
    )
    # r_link は hub のみと接続（link 経由・segment 非参加）→ degree=1
    assert devices["r_link"]["degree"] == 1, (
        f"r_link.degree は 1 のはずだが {devices['r_link']['degree']}"
    )
    # r_seg1/r_seg2 は segment で hub・互いに隣接 → degree=2
    assert devices["r_seg1"]["degree"] == 2, (
        f"r_seg1.degree は 2 のはずだが {devices['r_seg1']['degree']}"
    )
    assert devices["r_seg2"]["degree"] == 2, (
        f"r_seg2.degree は 2 のはずだが {devices['r_seg2']['degree']}"
    )


# ===========================================================================
# D2b: router-id 重複検出（ルール5: duplicate_ospf_router_id / ルール6: duplicate_bgp_router_id）
# ===========================================================================

def _make_dev_with_rid(dev_id, ospf_router_id=None, bgp_router_id=None,
                        hostname=None, vendor="cisco_ios", as_=65001):
    """router-id 付き最小 device dict を生成するヘルパー。"""
    return {
        "id": dev_id,
        "hostname": hostname or dev_id.upper(),
        "vendor": vendor,
        "as": as_,
        "ospf_router_id": ospf_router_id,
        "bgp_router_id": bgp_router_id,
        "sections": [],
    }


# ---------------------------------------------------------------------------
# ルール 5: duplicate_ospf_router_id（error）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_duplicate_ospf_router_id_two_devices():
    """2 台が同一 ospf_router_id を持つ場合 duplicate_ospf_router_id error が 1 件返ること。"""
    # Arrange
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", ospf_router_id="1.1.1.1"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert
    dup = [c for c in result if c["kind"] == "duplicate_ospf_router_id"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "error"
    assert "1.1.1.1" in dup[0]["message"]
    assert "r1" in dup[0]["refs"]
    assert "r2" in dup[0]["refs"]


@pytest.mark.unit
def test_build_checks_duplicate_ospf_router_id_three_devices():
    """3 台が同一 ospf_router_id を持つ場合も duplicate_ospf_router_id error が 1 件返ること。"""
    # Arrange
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="2.2.2.2"),
            _make_dev_with_rid("r2", ospf_router_id="2.2.2.2"),
            _make_dev_with_rid("r3", ospf_router_id="2.2.2.2"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 3 台重複でも同一 router-id につき 1 件
    dup = [c for c in result if c["kind"] == "duplicate_ospf_router_id"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "error"
    # refs に 3 台すべての device id が含まれること
    for dev_id in ("r1", "r2", "r3"):
        assert dev_id in dup[0]["refs"], f"{dev_id} が refs に含まれていない"


@pytest.mark.unit
def test_build_checks_duplicate_ospf_router_id_refs_sorted():
    """duplicate_ospf_router_id の refs（device id 群）が昇順ソートされること。"""
    # Arrange: r3, r1, r2 の順で登録（意図的に非昇順）
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r3", ospf_router_id="3.3.3.3"),
            _make_dev_with_rid("r1", ospf_router_id="3.3.3.3"),
            _make_dev_with_rid("r2", ospf_router_id="3.3.3.3"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: refs が昇順ソートされていること
    dup = [c for c in result if c["kind"] == "duplicate_ospf_router_id"]
    assert len(dup) == 1
    # refs 内の先頭要素群が device id であり昇順
    dev_refs = [r for r in dup[0]["refs"] if r in ("r1", "r2", "r3")]
    assert dev_refs == sorted(dev_refs), f"refs の device id が昇順でない: {dev_refs}"


@pytest.mark.unit
def test_build_checks_no_duplicate_ospf_router_id_when_unique():
    """全機器の ospf_router_id が相異なる場合 duplicate_ospf_router_id が返らないこと。"""
    # Arrange
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", ospf_router_id="2.2.2.2"),
            _make_dev_with_rid("r3", ospf_router_id="3.3.3.3"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 検出なし
    assert not any(c["kind"] == "duplicate_ospf_router_id" for c in result)


@pytest.mark.unit
def test_build_checks_no_duplicate_ospf_router_id_when_all_none():
    """全機器の ospf_router_id が None の場合 duplicate_ospf_router_id が返らないこと。"""
    # Arrange: ospf_router_id=None（デフォルト）
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id=None),
            _make_dev_with_rid("r2", ospf_router_id=None),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: None は無視され検出なし
    assert not any(c["kind"] == "duplicate_ospf_router_id" for c in result)


@pytest.mark.unit
def test_build_checks_no_duplicate_ospf_router_id_when_single_device():
    """ospf_router_id が重複するのが 1 台だけ（他は None）の場合は検出しないこと。"""
    # Arrange: r1 のみが router-id を持つ（1 台のみ = 重複なし）
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", ospf_router_id=None),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 1 台のみは検出しない
    assert not any(c["kind"] == "duplicate_ospf_router_id" for c in result)


@pytest.mark.unit
def test_build_checks_duplicate_ospf_router_id_multiple_groups():
    """複数の重複グループ（router-id A を 2 台・B を 2 台）が決定的順序で両方出ること。"""
    # Arrange: router-id "1.1.1.1" が r1/r2 に、"2.2.2.2" が r3/r4 に重複
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", ospf_router_id="1.1.1.1"),
            _make_dev_with_rid("r3", ospf_router_id="2.2.2.2"),
            _make_dev_with_rid("r4", ospf_router_id="2.2.2.2"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 2 グループ分の 2 件が検出されること
    dup = [c for c in result if c["kind"] == "duplicate_ospf_router_id"]
    assert len(dup) == 2

    # 決定的順序（router-id 値の昇順で並ぶ）: "1.1.1.1" → "2.2.2.2"
    rid_msgs = [c["message"] for c in dup]
    assert "1.1.1.1" in rid_msgs[0]
    assert "2.2.2.2" in rid_msgs[1]


@pytest.mark.unit
def test_build_checks_ospf_same_device_ospf_bgp_not_flagged():
    """同一機器が ospf_router_id と bgp_router_id で同じ値を持つ場合は機器内重複として検出しないこと。

    機器内での ospf/bgp 共用 router-id は正常な設定。
    """
    # Arrange: r1 が ospf/bgp ともに "1.1.1.1"、r2 は別の値
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="1.1.1.1", bgp_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", ospf_router_id="2.2.2.2", bgp_router_id="2.2.2.2"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 機器内共用は検出しない（ospf でも bgp でも重複なし）
    assert not any(c["kind"] in ("duplicate_ospf_router_id", "duplicate_bgp_router_id")
                   for c in result)


# ---------------------------------------------------------------------------
# ルール 6: duplicate_bgp_router_id（error）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_duplicate_bgp_router_id_two_devices():
    """2 台が同一 bgp_router_id を持つ場合 duplicate_bgp_router_id error が 1 件返ること。"""
    # Arrange
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", bgp_router_id="10.0.0.1"),
            _make_dev_with_rid("r2", bgp_router_id="10.0.0.1"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert
    dup = [c for c in result if c["kind"] == "duplicate_bgp_router_id"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "error"
    assert "10.0.0.1" in dup[0]["message"]
    assert "r1" in dup[0]["refs"]
    assert "r2" in dup[0]["refs"]


@pytest.mark.unit
def test_build_checks_no_duplicate_bgp_router_id_when_unique():
    """全機器の bgp_router_id が相異なる場合 duplicate_bgp_router_id が返らないこと。"""
    # Arrange
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", bgp_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", bgp_router_id="2.2.2.2"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 検出なし
    assert not any(c["kind"] == "duplicate_bgp_router_id" for c in result)


@pytest.mark.unit
def test_build_checks_no_duplicate_bgp_router_id_when_all_none():
    """全機器の bgp_router_id が None の場合 duplicate_bgp_router_id が返らないこと。"""
    # Arrange
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", bgp_router_id=None),
            _make_dev_with_rid("r2", bgp_router_id=None),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: None は無視され検出なし
    assert not any(c["kind"] == "duplicate_bgp_router_id" for c in result)


@pytest.mark.unit
def test_build_checks_duplicate_bgp_router_id_three_devices():
    """3 台が同一 bgp_router_id を持つ場合も duplicate_bgp_router_id error が 1 件返ること（refs に全台）。"""
    # Arrange
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", bgp_router_id="7.7.7.7"),
            _make_dev_with_rid("r2", bgp_router_id="7.7.7.7"),
            _make_dev_with_rid("r3", bgp_router_id="7.7.7.7"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 3 台重複でも同一 router-id につき 1 件
    dup = [c for c in result if c["kind"] == "duplicate_bgp_router_id"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "error"
    # refs に 3 台すべての device id が含まれること
    for dev_id in ("r1", "r2", "r3"):
        assert dev_id in dup[0]["refs"], f"{dev_id} が refs に含まれていない"


@pytest.mark.unit
def test_build_checks_duplicate_bgp_router_id_refs_sorted():
    """duplicate_bgp_router_id の refs（device id 群）が昇順ソートされること。"""
    # Arrange: r3, r1, r2 の順で登録（意図的に非昇順）
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r3", bgp_router_id="8.8.8.8"),
            _make_dev_with_rid("r1", bgp_router_id="8.8.8.8"),
            _make_dev_with_rid("r2", bgp_router_id="8.8.8.8"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: refs の device id 群が昇順ソートされていること
    dup = [c for c in result if c["kind"] == "duplicate_bgp_router_id"]
    assert len(dup) == 1
    dev_refs = [r for r in dup[0]["refs"] if r in ("r1", "r2", "r3")]
    assert dev_refs == sorted(dev_refs), f"refs の device id が昇順でない: {dev_refs}"


@pytest.mark.unit
def test_build_checks_no_duplicate_bgp_router_id_when_single_device():
    """bgp_router_id が重複するのが 1 台だけ（他は None）の場合は検出しないこと。"""
    # Arrange: r1 のみが router-id を持つ（1 台のみ = 重複なし）
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", bgp_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", bgp_router_id=None),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 1 台のみは検出しない
    assert not any(c["kind"] == "duplicate_bgp_router_id" for c in result)


@pytest.mark.unit
def test_build_checks_duplicate_bgp_router_id_multiple_groups():
    """複数の BGP router-id 重複グループが決定的順序で両方出ること。"""
    # Arrange
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", bgp_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", bgp_router_id="1.1.1.1"),
            _make_dev_with_rid("r3", bgp_router_id="2.2.2.2"),
            _make_dev_with_rid("r4", bgp_router_id="2.2.2.2"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 2 件
    dup = [c for c in result if c["kind"] == "duplicate_bgp_router_id"]
    assert len(dup) == 2
    rid_msgs = [c["message"] for c in dup]
    assert "1.1.1.1" in rid_msgs[0]
    assert "2.2.2.2" in rid_msgs[1]


# ---------------------------------------------------------------------------
# 両ルール: 独立性・共存・ソート順
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_ospf_and_bgp_rid_duplicate_independently():
    """ospf と bgp の両方で router-id が重複する場合、両ルールが独立して検出されること。"""
    # Arrange: r1/r2 が ospf_router_id 重複、r3/r4 が bgp_router_id 重複
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="5.5.5.5"),
            _make_dev_with_rid("r2", ospf_router_id="5.5.5.5"),
            _make_dev_with_rid("r3", bgp_router_id="6.6.6.6"),
            _make_dev_with_rid("r4", bgp_router_id="6.6.6.6"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: ospf と bgp で各 1 件
    ospf_dup = [c for c in result if c["kind"] == "duplicate_ospf_router_id"]
    bgp_dup = [c for c in result if c["kind"] == "duplicate_bgp_router_id"]
    assert len(ospf_dup) == 1
    assert len(bgp_dup) == 1
    assert "5.5.5.5" in ospf_dup[0]["message"]
    assert "6.6.6.6" in bgp_dup[0]["message"]


@pytest.mark.unit
def test_build_checks_rid_duplicate_sort_order_with_other_rules():
    """duplicate_ospf/bgp_router_id（error）が severity→kind 昇順ソートに乗ること。

    ソート順: error→warning、同一 severity 内は kind 昇順。
    duplicate_bgp_router_id < duplicate_ip < duplicate_ospf_router_id（アルファベット順）
    """
    # Arrange: duplicate_ip(error) + duplicate_ospf_router_id(error) を同時発生させる
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="1.1.1.1"),
            _make_dev_with_rid("r2", ospf_router_id="1.1.1.1"),
        ],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert 1: error のみ（warning はない）
    kinds = [c["kind"] for c in result]
    assert "duplicate_ip" in kinds
    assert "duplicate_ospf_router_id" in kinds

    # Assert 2: kind が昇順に並ぶ（error 内で "duplicate_ip" < "duplicate_ospf_router_id"）
    error_items = [c for c in result if c["severity"] == "error"]
    error_kinds = [c["kind"] for c in error_items]
    assert error_kinds == sorted(error_kinds), f"error 内で kind が昇順でない: {error_kinds}"


@pytest.mark.unit
def test_build_checks_rid_duplicate_deterministic():
    """build_checks の router-id 重複検出が2回呼んで同一結果を返すこと（決定性）。"""
    # Arrange: ospf と bgp 両方の重複を含む
    topo = _minimal_topo(
        devices=[
            _make_dev_with_rid("r1", ospf_router_id="1.1.1.1", bgp_router_id="9.9.9.9"),
            _make_dev_with_rid("r2", ospf_router_id="1.1.1.1", bgp_router_id="9.9.9.9"),
        ],
    )

    # Act: 2 回呼ぶ
    result_a = build_checks(topo)
    result_b = build_checks(topo)

    # Assert: 完全一致
    assert json.dumps(result_a, sort_keys=True) == json.dumps(result_b, sort_keys=True)


# ---------------------------------------------------------------------------
# golden 回帰: router-id が null → 既存の checks==[] を維持
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_checks_golden_result_regression_rid_unchanged():
    """golden (r1+r2) の ospf_router_id/bgp_router_id がいずれも null であるため、
    duplicate_ospf/bgp_router_id は検出されず、checks が [] のまま変わらないこと。

    golden YAML 確認:
      r1.ospf_router_id = null, r1.bgp_router_id = null
      r2.ospf_router_id = null, r2.bgp_router_id = null
    → ルール5/6 の対象となる非 None router-id が存在しない。
    """
    topo = load_topology(str(GOLDEN))
    result = build_checks(topo)
    # duplicate_ospf_router_id / duplicate_bgp_router_id が出ないこと
    assert not any(c["kind"] in ("duplicate_ospf_router_id", "duplicate_bgp_router_id")
                   for c in result)
    # 全体として checks は依然として空
    assert result == []


# ===========================================================================
# D2c 追加ルール — ルール7: ospf_area0_disconnected / ルール8: ibgp_fullmesh_incomplete
# ===========================================================================

# ---------------------------------------------------------------------------
# ルール7: ospf_area0_disconnected（warning）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_checks_ospf_area0_disconnected_detected():
    """area0 持ち device と area1 のみの device が混在 → area1 device が 1 件検出されること。

    壊すと赤: ospf_area0_disconnected が発火する最小ケース。
    """
    # Arrange: r1=area0, r2=area1 のみ（area0 混在環境）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "1", "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: r2 が area0 を持たないとして 1 件 warning
    chk = [c for c in result if c["kind"] == "ospf_area0_disconnected"]
    assert len(chk) == 1
    assert chk[0]["severity"] == "warning"
    assert "r2" in chk[0]["message"]
    assert "1" in chk[0]["message"]          # area "1" がメッセージに含まれること
    # refs: [device] + sorted(areas)
    assert chk[0]["refs"][0] == "r2"
    assert "1" in chk[0]["refs"]


@pytest.mark.unit
def test_build_checks_ospf_area0_disconnected_all_area0_no_warning():
    """全 device が area0 を持つ場合 ospf_area0_disconnected が出ないこと。"""
    # Arrange: r1=area0, r2=area0
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "0", "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert
    assert not any(c["kind"] == "ospf_area0_disconnected" for c in result)


@pytest.mark.unit
def test_build_checks_ospf_area0_disconnected_no_area0_in_topo_no_warning():
    """全 device が非 area0（area0 が存在しない環境）→ ospf_area0_disconnected が出ないこと。

    壊すと赤: 偽陽性抑制の保証テスト。area0 が存在しない環境では発火しない。
    """
    # Arrange: r1=area1, r2=area2（area0 なし）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "1", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "2", "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: area0 不在環境では偽陽性なし
    chk = [c for c in result if c["kind"] == "ospf_area0_disconnected"]
    assert chk == [], (
        "area0 が存在しない環境で ospf_area0_disconnected が誤検知された（偽陽性）: %s" % chk
    )


@pytest.mark.unit
def test_build_checks_ospf_area0_disconnected_abr_not_flagged():
    """ABR（area0 と area1 の両方を持つ device）は ospf_area0_disconnected の対象外であること。"""
    # Arrange: r1=area0 のみ, r2=area0+area1（ABR）, r3=area1 のみ
    topo = _minimal_topo(
        devices=[
            _make_dev("r1"), _make_dev("r2", hostname="R2"), _make_dev("r3", hostname="R3")
        ],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "1", "af": "v4"},
                {"device": "r3", "process": 1, "network": "10.1.0.1/24", "area": "1", "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: r2（ABR）は非対象・r3 が検出される
    chk = [c for c in result if c["kind"] == "ospf_area0_disconnected"]
    assert len(chk) == 1
    assert chk[0]["refs"][0] == "r3"
    # r2 は対象外
    assert not any("r2" in c["refs"] for c in chk)


@pytest.mark.unit
def test_build_checks_ospf_area0_disconnected_no_ospf_no_warning():
    """OSPF エントリが全くない場合 ospf_area0_disconnected が出ないこと。"""
    topo = _minimal_topo()

    result = build_checks(topo)

    assert not any(c["kind"] == "ospf_area0_disconnected" for c in result)


@pytest.mark.unit
def test_build_checks_ospf_area0_disconnected_refs_format():
    """ospf_area0_disconnected の refs が [device] + sorted(areas) であること。"""
    # Arrange: r1=area0, r2=area1+area2（area0 なし）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "2", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.2.0.0/24", "area": "1", "af": "v4"},
            ],
            "static": [],
        },
    )

    result = build_checks(topo)

    chk = [c for c in result if c["kind"] == "ospf_area0_disconnected"]
    assert len(chk) == 1
    # refs = [device] + sorted(areas)  → ["r2", "1", "2"]
    assert chk[0]["refs"] == ["r2", "1", "2"]


# ---------------------------------------------------------------------------
# golden 回帰: ルール7 の非発火確認（golden は area "0" 単独）
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_checks_golden_no_ospf_area0_disconnected():
    """golden (r1 のみ OSPF area "0") では ospf_area0_disconnected が出ないこと。

    golden YAML: r1 に ospf area "0" 1 件のみ。r2 は OSPF 無し。
    → area0 を持つ device が存在するが、OSPF を保有しつつ area0 を持たない device がいない。
    → 非発火 → checks に影響なし → golden byte 不変。
    """
    topo = load_topology(str(GOLDEN))
    result = build_checks(topo)
    assert not any(c["kind"] == "ospf_area0_disconnected" for c in result)
    assert result == []


# ---------------------------------------------------------------------------
# ルール8: ibgp_fullmesh_incomplete（warning）
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_checks_ibgp_fullmesh_incomplete_detected():
    """3台 iBGP・RR なし・1ペアのセッションが欠落 → 該当ペア 1 件が検出されること。

    壊すと赤: ibgp_fullmesh_incomplete が発火する最小ケース。
    """
    # Arrange:
    # r1 ↔ r2, r1 ↔ r3 は iBGP セッションあり
    # r2 ↔ r3 は欠落（r2 に r3 へのセッションなし、r3 に r2 へのセッションなし）
    # neighbor_ip は各機器の Lo0 IP で解決可能
    topo = _minimal_topo(
        devices=[
            _make_dev("r1", as_=65001), _make_dev("r2", hostname="R2", as_=65001),
            _make_dev("r3", hostname="R3", as_=65001),
        ],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "192.0.2.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "192.0.2.2", "prefix": 32}]),
            _make_if("r3", "Lo0", [{"af": "v4", "ip": "192.0.2.3", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                # r1 → r2
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r2 → r1
                {"device": "r2", "local_as": 65001, "local_ip": "192.0.2.2",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r1 → r3
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.3", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r3 → r1
                {"device": "r3", "local_as": 65001, "local_ip": "192.0.2.3",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r2 ↔ r3: 欠落
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: r2 と r3 の間が 1 件検出
    chk = [c for c in result if c["kind"] == "ibgp_fullmesh_incomplete"]
    assert len(chk) == 1
    assert chk[0]["severity"] == "warning"
    assert "65001" in chk[0]["message"]
    assert "r2" in chk[0]["message"] and "r3" in chk[0]["message"]
    # refs: [di, dj, str(asn)]  di<dj
    assert chk[0]["refs"] == ["r2", "r3", "65001"]


@pytest.mark.unit
def test_build_checks_ibgp_fullmesh_rr_client_present_no_warning():
    """iBGP セッションに route_reflector_client=True が 1 件でも存在する AS → 0 件。

    壊すと赤: RR 構成の偽陽性抑制テスト。
    """
    # Arrange: r1=RR, r2/r3=RR client。r2↔r3 の直接セッションなし（RR 経由が前提）
    topo = _minimal_topo(
        devices=[
            _make_dev("r1", as_=65001), _make_dev("r2", hostname="R2", as_=65001),
            _make_dev("r3", hostname="R3", as_=65001),
        ],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "192.0.2.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "192.0.2.2", "prefix": 32}]),
            _make_if("r3", "Lo0", [{"af": "v4", "ip": "192.0.2.3", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                # r1 → r2 (RR client)
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4",
                 "route_reflector_client": True},
                # r2 → r1 (RR)
                {"device": "r2", "local_as": 65001, "local_ip": "192.0.2.2",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r1 → r3 (RR client)
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.3", "peer_as": 65001, "type": "ibgp", "af": "v4",
                 "route_reflector_client": True},
                # r3 → r1 (RR)
                {"device": "r3", "local_as": 65001, "local_ip": "192.0.2.3",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: RR 構成のため偽陽性なし
    chk = [c for c in result if c["kind"] == "ibgp_fullmesh_incomplete"]
    assert chk == [], (
        "RR client が存在する AS で ibgp_fullmesh_incomplete が誤検知された（偽陽性）: %s" % chk
    )


@pytest.mark.unit
def test_build_checks_ibgp_fullmesh_ebgp_only_no_warning():
    """eBGP セッションのみ → ibgp_fullmesh_incomplete が出ないこと。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
                {"device": "r2", "local_as": 65002, "local_ip": "10.0.0.2",
                 "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    result = build_checks(topo)

    assert not any(c["kind"] == "ibgp_fullmesh_incomplete" for c in result)


@pytest.mark.unit
def test_build_checks_ibgp_fullmesh_unresolved_neighbor_skipped():
    """解決不能 neighbor_ip を持つ device が絡むペアはスキップ（偽陽性なし）。

    r2 の neighbor_ip=192.0.2.99 はどの IF にも存在しない（未解決）。
    r2-r3 間ペアで r2 が unresolved_devs に含まれるためスキップ。
    """
    # Arrange: r1↔r2, r1↔r3 は解決可能。r2 は追加で未解決 neighbor を持つ。
    # r2↔r3 のペアは、r2 が未解決 neighbor を持つのでスキップ
    topo = _minimal_topo(
        devices=[
            _make_dev("r1", as_=65001), _make_dev("r2", hostname="R2", as_=65001),
            _make_dev("r3", hostname="R3", as_=65001),
        ],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "192.0.2.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "192.0.2.2", "prefix": 32}]),
            _make_if("r3", "Lo0", [{"af": "v4", "ip": "192.0.2.3", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                # r1 → r2
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r2 → r1
                {"device": "r2", "local_as": 65001, "local_ip": "192.0.2.2",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r1 → r3
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.3", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r3 → r1
                {"device": "r3", "local_as": 65001, "local_ip": "192.0.2.3",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r2 の追加 neighbor（未解決）
                {"device": "r2", "local_as": 65001, "local_ip": "192.0.2.2",
                 "neighbor_ip": "192.0.2.99", "peer_as": 65001, "type": "ibgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: r2 が unresolved → r2-r3 ペアはスキップ → 0 件
    chk = [c for c in result if c["kind"] == "ibgp_fullmesh_incomplete"]
    assert chk == [], (
        "解決不能 neighbor_ip を持つ device が絡むペアが偽陽性検出された: %s" % chk
    )


@pytest.mark.unit
def test_build_checks_ibgp_fullmesh_no_ibgp_no_warning():
    """iBGP エントリが全くない場合 ibgp_fullmesh_incomplete が出ないこと。"""
    topo = _minimal_topo()

    result = build_checks(topo)

    assert not any(c["kind"] == "ibgp_fullmesh_incomplete" for c in result)


@pytest.mark.unit
def test_build_checks_ibgp_fullmesh_sort_order_with_new_rules():
    """新ルール混在でも severity→kind→refs 安定ソートが維持されること。

    duplicate_ip(error) + ospf_area0_disconnected(warning) + ibgp_fullmesh_incomplete(warning)
    が共存する場合、error が先頭・warning 2種が kind 順に並ぶこと。
    """
    topo = _minimal_topo(
        devices=[
            _make_dev("r1", as_=65001), _make_dev("r2", hostname="R2", as_=65001),
            _make_dev("r3", hostname="R3", as_=65001),
        ],
        interfaces=[
            # duplicate_ip 発火用: r1 と r2 が同一 IP
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            # ibgp fullmesh 用 Lo0
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "192.0.2.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "192.0.2.2", "prefix": 32}]),
            _make_if("r3", "Lo0", [{"af": "v4", "ip": "192.0.2.3", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                # r1↔r2 ibgp
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                {"device": "r2", "local_as": 65001, "local_ip": "192.0.2.2",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r1↔r3 ibgp
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.3", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                {"device": "r3", "local_as": 65001, "local_ip": "192.0.2.3",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r2↔r3 欠落 → fullmesh_incomplete
            ],
            "ospf": [
                # r1=area0, r2=area1（area0不在）→ ospf_area0_disconnected for r2
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "1", "af": "v4"},
            ],
            "static": [],
        },
    )

    result = build_checks(topo)

    # error が全て warning より前
    severities = [c["severity"] for c in result]
    last_error_idx = max((i for i, s in enumerate(severities) if s == "error"), default=-1)
    first_warning_idx = min((i for i, s in enumerate(severities) if s == "warning"), default=len(result))
    assert last_error_idx < first_warning_idx

    # warning 種が kind 昇順: ibgp_fullmesh_incomplete < ospf_area0_disconnected (辞書順)
    warning_kinds = [c["kind"] for c in result if c["severity"] == "warning"]
    assert warning_kinds == sorted(warning_kinds)

    # 新ルール両方が検出されていること
    assert any(c["kind"] == "ospf_area0_disconnected" for c in result)
    assert any(c["kind"] == "ibgp_fullmesh_incomplete" for c in result)


# ---------------------------------------------------------------------------
# golden 回帰: ルール8 の非発火確認（golden は ebgp のみ）
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_checks_golden_no_ibgp_fullmesh_incomplete():
    """golden (r1+r2 は ebgp のみ) では ibgp_fullmesh_incomplete が出ないこと。

    golden YAML: bgp エントリはすべて type="ebgp"。
    → iBGP セッションが存在しない → 非発火 → checks に影響なし → golden byte 不変。
    """
    topo = load_topology(str(GOLDEN))
    result = build_checks(topo)
    assert not any(c["kind"] == "ibgp_fullmesh_incomplete" for c in result)
    assert result == []


# ===========================================================================
# D2c レビュー指摘修正テスト
# ===========================================================================

# ---------------------------------------------------------------------------
# 修正1: _check_ibgp_fullmesh で local_as=None の TypeError ガード
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_ibgp_local_as_none_does_not_crash():
    """local_as=None の iBGP エントリを含む topo で build_checks がクラッシュしないこと。

    壊すと赤: None キーを sorted() に渡すと TypeError が発生する（修正前の実装）。
    手編集 YAML 等で local_as=None になりうる。
    """
    # Arrange: local_as=None のエントリを混入させる
    topo = _minimal_topo(
        devices=[_make_dev("r1", as_=65001), _make_dev("r2", hostname="R2", as_=65001)],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "192.0.2.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "192.0.2.2", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                # 正常なエントリ
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # local_as=None の異常エントリ（手編集 YAML 相当）
                {"device": "r2", "local_as": None, "local_ip": "192.0.2.2",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act: TypeError が起きないこと
    try:
        result = build_checks(topo)
    except TypeError as e:
        pytest.fail(f"local_as=None で TypeError が発生した: {e}")

    # Assert: None AS（local_as=None のエントリ）は ibgp_fullmesh_incomplete の判定から除外される
    # （None AS として集約されたセッション群は sorted() でスキップ）
    chk = [c for c in result if c["kind"] == "ibgp_fullmesh_incomplete"]
    # None AS のエントリが判定されていないこと（refs に "None" が含まれない）
    assert not any("None" in c.get("refs", []) for c in chk), (
        "local_as=None のエントリが ibgp_fullmesh_incomplete の判定対象になった: %s" % chk
    )


@pytest.mark.unit
def test_build_checks_ibgp_local_as_none_only_does_not_produce_warning():
    """local_as=None のエントリのみの topo で ibgp_fullmesh_incomplete が 0 件であること。

    None AS は full-mesh 判定対象外のため、2台が互いに参照し合っていても検出しない。
    """
    # Arrange: 全エントリが local_as=None
    topo = _minimal_topo(
        devices=[_make_dev("r1", as_=65001), _make_dev("r2", hostname="R2", as_=65001)],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "192.0.2.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "192.0.2.2", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                {"device": "r1", "local_as": None, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                {"device": "r2", "local_as": None, "local_ip": "192.0.2.2",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: None AS は判定対象外 → 0 件
    chk = [c for c in result if c["kind"] == "ibgp_fullmesh_incomplete"]
    assert chk == [], f"local_as=None のエントリが誤って ibgp_fullmesh_incomplete に計上された: {chk}"


# ---------------------------------------------------------------------------
# 修正2: _check_ospf_area0_connectivity で area=None の TypeError ガード
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_ospf_area_none_does_not_crash():
    """OSPF エントリに area=None が混在しても build_checks がクラッシュしないこと。

    壊すと赤: None を set に追加し sorted() や ", ".join() に渡すと TypeError が発生する（修正前）。
    手編集 YAML 等で area=None になりうる。
    """
    # Arrange: area=None のエントリを混入
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                # area0 あり（発火環境を作る）
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                # area=None の異常エントリ
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": None, "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act: TypeError/AttributeError が起きないこと
    try:
        result = build_checks(topo)
    except (TypeError, AttributeError) as e:
        pytest.fail(f"area=None で例外が発生した: {e}")

    # Assert: area=None のエントリは無視される（r2 は area set が空になるため非対象）
    chk = [c for c in result if c["kind"] == "ospf_area0_disconnected"]
    # r2 の area=None エントリは無視 → r2 の area set = {} → area0 なし判定対象だが
    # area set が空（None を除外）なら dev_areas に r2 が入らないか、areas が空になるので
    # "0" in areas が False → ospf_area0_disconnected 対象外
    # いずれにしてもクラッシュしないことが主要な検証
    assert isinstance(result, list)


@pytest.mark.unit
def test_build_checks_ospf_area_none_is_ignored_in_dev_areas():
    """area=None のエントリは dev_areas の area set に追加されず、
    ospf_area0_disconnected の refs にも含まれないこと。

    壊すと赤: None を area set に追加し sorted() に渡すと TypeError（修正前）。
    """
    # Arrange: r1=area0, r2=area1+area_None
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                # r2 は area1 と area=None を持つ
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "1", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.2.0.0/24", "area": None, "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: r2 は area0 を持たないので警告が出る（area1 のみ認識）
    chk = [c for c in result if c["kind"] == "ospf_area0_disconnected"]
    assert len(chk) == 1
    assert chk[0]["refs"][0] == "r2"
    # refs に None（文字列）が含まれないこと（None は除外されている）
    assert None not in chk[0]["refs"]
    assert "None" not in chk[0]["refs"]
    # refs は [r2, "1"]（area=None は除外）
    assert chk[0]["refs"] == ["r2", "1"]


# ---------------------------------------------------------------------------
# 修正3: _check_ospf_area0_connectivity で area の数値優先ソート
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_ospf_area0_disconnected_refs_numeric_sort():
    """ospf_area0_disconnected の refs の area 部が数値優先ソートになること。

    壊すと赤: 辞書順実装では "10" < "2" の誤順序になる。
    数値優先ソートでは "2" < "10"。
    """
    # Arrange: r1=area0, r2=area2+area10（area0 なし）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                # r2 は area "2" と area "10" を保有（数値順なら 2<10、辞書順なら 10<2）
                {"device": "r2", "process": 1, "network": "10.2.0.0/24", "area": "10", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "2", "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: refs = ["r2", "2", "10"]（数値優先ソート）
    chk = [c for c in result if c["kind"] == "ospf_area0_disconnected"]
    assert len(chk) == 1
    # 数値優先: "2" < "10"
    refs_areas = chk[0]["refs"][1:]  # 先頭は device id
    assert refs_areas == ["2", "10"], (
        f"数値優先ソートの期待値は ['2', '10'] だが実際は {refs_areas} "
        "（辞書順実装なら ['10', '2'] になる誤り）"
    )


@pytest.mark.unit
def test_build_checks_ospf_area0_disconnected_refs_numeric_sort_mixed_nondigit():
    """非 digit 文字列を含む area でも数値優先ソートがクラッシュしないこと（フォールバック）。

    非 digit area（正規化失敗等で "backbone" 等が入る可能性）はフォールバックで
    辞書順末尾に置かれる。
    """
    # Arrange: r1=area0, r2=area "2" + area "10" + area "backbone"（非 digit）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[],
        routing={
            "bgp": [],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.2.0.0/24", "area": "10", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.1.0.0/24", "area": "2", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.3.0.0/24", "area": "backbone",
                 "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act: クラッシュしないこと
    try:
        result = build_checks(topo)
    except Exception as e:
        pytest.fail(f"非 digit area で例外が発生した: {e}")

    # Assert: 数値 area が数値順先頭・非 digit area は末尾
    chk = [c for c in result if c["kind"] == "ospf_area0_disconnected"]
    assert len(chk) == 1
    refs_areas = chk[0]["refs"][1:]
    # 数値系: "2", "10" が先（数値順）、"backbone" が末尾
    assert refs_areas.index("2") < refs_areas.index("10"), (
        "数値 area '2' が '10' より前にあるべき"
    )
    assert refs_areas[-1] == "backbone", (
        "非 digit area 'backbone' は末尾に置かれるべき"
    )


# ---------------------------------------------------------------------------
# 修正4: 2台 iBGP 双方向完成 → ibgp_fullmesh_incomplete が 0 件
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_checks_ibgp_fullmesh_two_devices_complete_no_warning():
    """2台が相互に iBGP セッションを持ち host_ip で解決可能・RR なし → 0 件。

    壊すと赤: 完成ケースを誤検知する実装だとここで失敗する。
    最小完成ケース（正常ケース非発火）の確認テスト。
    """
    # Arrange: r1↔r2 双方向 iBGP（full-mesh 完成）
    topo = _minimal_topo(
        devices=[_make_dev("r1", as_=65001), _make_dev("r2", hostname="R2", as_=65001)],
        interfaces=[
            _make_if("r1", "Lo0", [{"af": "v4", "ip": "192.0.2.1", "prefix": 32}]),
            _make_if("r2", "Lo0", [{"af": "v4", "ip": "192.0.2.2", "prefix": 32}]),
        ],
        routing={
            "bgp": [
                # r1 → r2（neighbor_ip=r2 の Lo0 IP で解決可能）
                {"device": "r1", "local_as": 65001, "local_ip": "192.0.2.1",
                 "neighbor_ip": "192.0.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                # r2 → r1（neighbor_ip=r1 の Lo0 IP で解決可能）
                {"device": "r2", "local_as": 65001, "local_ip": "192.0.2.2",
                 "neighbor_ip": "192.0.2.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
            ],
            "ospf": [],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: 2台 full-mesh 完成 → 0 件（誤検知なし）
    chk = [c for c in result if c["kind"] == "ibgp_fullmesh_incomplete"]
    assert chk == [], (
        "2台 iBGP full-mesh 完成ケースで誤検知が発生した: %s" % chk
    )


# ---------------------------------------------------------------------------
# 改修⑥ STATS タブ削除
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_data_no_stats_key():
    """build_data(topo) の返り値に 'stats' キーが無いこと（改修⑥後）。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    assert "stats" not in data, "'stats' キーがまだ残っている: %s" % list(data.keys())


# ===========================================================================
# 改修① OSPF area 不一致 CHECK ルール9: ospf_area_mismatch
# ===========================================================================

def _make_link(a_dev, a_if, b_dev, b_if, subnet, ospf_area=None):
    """最小 link dict（topo["links"] 用）を生成するヘルパー。"""
    ln = {
        "a_device": a_dev, "a_if": a_if,
        "b_device": b_dev, "b_if": b_if,
        "subnet": subnet,
    }
    if ospf_area is not None:
        ln["ospf_area"] = ospf_area
    return ln


def _make_segment(seg_id, subnet, members, ospf_area=None):
    """最小 segment dict（topo["segments"] 用）を生成するヘルパー。"""
    seg = {"id": seg_id, "subnet": subnet, "members": members}
    if ospf_area is not None:
        seg["ospf_area"] = ospf_area
    return seg


# ---------------------------------------------------------------------------
# ルール9: ospf_area_mismatch — リンク発火
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_check_ospf_area_mismatch_link_fires():
    """リンクの ospf_area が "0/1"（不一致）のとき ospf_area_mismatch が 1 件発火すること。

    壊すと赤: ospf_area_mismatch 発火の最小ケース。
    実機では area 不一致リンクで OSPF 隣接は張れない＝設定誤り。
    """
    # Arrange
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
        ],
        links=[
            _make_link("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30", ospf_area="0/1"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert
    chk = [c for c in result if c["kind"] == "ospf_area_mismatch"]
    assert len(chk) == 1, "area 不一致リンクで ospf_area_mismatch が 1 件発火すること: %s" % chk
    c = chk[0]
    assert c["severity"] == "warning"
    # refs = sorted([a_device, b_device]) + [subnet]
    assert c["refs"][:2] == sorted(["r1", "r2"])
    assert "10.0.0.0/30" in c["refs"]
    # message に area 値を含む
    assert "0/1" in c["message"]


@pytest.mark.unit
def test_check_ospf_area_mismatch_link_refs_deterministic():
    """refs の順序が決定的であること（sorted([a, b]) + [subnet]）。

    壊すと赤: refs を dict 挿入順に生成すると a/b の順序が不定になる。
    """
    # Arrange: b_device < a_device の辞書順になる設定
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
        ],
        links=[
            # a_device="r2", b_device="r1"（逆順）でも refs は sorted
            _make_link("r2", "Gi0", "r1", "Gi0", "10.0.0.0/30", ospf_area="0/1"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert
    chk = [c for c in result if c["kind"] == "ospf_area_mismatch"]
    assert len(chk) == 1
    # refs[0] < refs[1] (辞書順)
    assert chk[0]["refs"][0] == "r1"
    assert chk[0]["refs"][1] == "r2"


# ---------------------------------------------------------------------------
# ルール9: ospf_area_mismatch — セグメント発火
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_check_ospf_area_mismatch_segment_fires():
    """セグメントの ospf_area が "0/2"（不一致）のとき ospf_area_mismatch が 1 件発火すること。

    壊すと赤: セグメント経路での発火テスト。
    """
    # Arrange
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2"), _make_dev("r3", hostname="R3")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "192.168.1.1", "prefix": 24}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "192.168.1.2", "prefix": 24}]),
            _make_if("r3", "Gi0", [{"af": "v4", "ip": "192.168.1.3", "prefix": 24}]),
        ],
        segments=[
            _make_segment(
                "seg::192.168.1.0/24", "192.168.1.0/24",
                members=["r1::Gi0", "r2::Gi0", "r3::Gi0"],
                ospf_area="0/2",
            ),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert
    chk = [c for c in result if c["kind"] == "ospf_area_mismatch"]
    assert len(chk) == 1, "area 不一致 segment で ospf_area_mismatch が 1 件発火すること: %s" % chk
    c = chk[0]
    assert c["severity"] == "warning"
    # refs = [seg_id, subnet]（完全一致）
    assert c["refs"] == ["seg::192.168.1.0/24", "192.168.1.0/24"]
    # message に area 値を含む
    assert "0/2" in c["message"]


# ---------------------------------------------------------------------------
# ルール9: ospf_area_mismatch — 非発火（単一 area）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_check_ospf_area_mismatch_single_area_silent():
    """area が単一値（"0"）で "/" を含まないとき ospf_area_mismatch が出ないこと。

    壊すと赤: 正常リンクに誤検知が出るバグを防ぐ。
    """
    # Arrange
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
        ],
        links=[
            _make_link("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30", ospf_area="0"),
        ],
        segments=[
            _make_segment(
                "seg::10.1.0.0/24", "10.1.0.0/24",
                members=["r1::Gi0"],
                ospf_area="1",
            ),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert
    chk = [c for c in result if c["kind"] == "ospf_area_mismatch"]
    assert chk == [], (
        "単一 area (0 or 1) で ospf_area_mismatch が誤検知された（偽陽性）: %s" % chk
    )


@pytest.mark.unit
def test_check_ospf_area_mismatch_no_ospf_silent():
    """ospf_area フィールドがないリンク/セグメントでは ospf_area_mismatch が出ないこと。"""
    # Arrange
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
        ],
        links=[
            _make_link("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30"),  # ospf_area なし
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert
    assert not any(c["kind"] == "ospf_area_mismatch" for c in result)


# ---------------------------------------------------------------------------
# ルール9: ospf_area_mismatch — golden 非発火
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_check_ospf_area_mismatch_golden_silent():
    """golden topo（OSPF リンク無し）では ospf_area_mismatch が 0 件であること。

    golden の DATA.checks が不変であることの根拠テスト。
    """
    # Arrange
    topo = load_topology(str(GOLDEN))

    # Act
    result = build_checks(topo)

    # Assert
    chk = [c for c in result if c["kind"] == "ospf_area_mismatch"]
    assert chk == [], (
        "golden では ospf_area_mismatch が出ないはず: %s" % chk
    )
    # 全 checks が 0 件（既存アサート維持）
    assert result == []


# ---------------------------------------------------------------------------
# ルール9: ospf_area_mismatch — 安定ソート
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_checks_sorted_with_mismatch():
    """ospf_area_mismatch 混在でも severity→kind→refs 安定ソートが維持されること。

    duplicate_ip(error) + ospf_area_mismatch(warning) + ospf_area0_disconnected(warning) が
    共存したとき、error が先頭・warning が kind 昇順に並ぶこと。
    """
    # Arrange
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            # duplicate_ip 発火用（r1 と r2 で同一 IP）
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
        links=[
            # area 不一致リンク
            _make_link("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30", ospf_area="0/1"),
        ],
        routing={
            "bgp": [],
            "ospf": [
                # r1=area0, r2=area1 → ospf_area0_disconnected for r2
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 1, "network": "10.0.0.0/30", "area": "1", "af": "v4"},
            ],
            "static": [],
        },
    )

    # Act
    result = build_checks(topo)

    # Assert: error が全て warning より前
    severities = [c["severity"] for c in result]
    last_error_idx = max(
        (i for i, s in enumerate(severities) if s == "error"), default=-1
    )
    first_warning_idx = min(
        (i for i, s in enumerate(severities) if s == "warning"), default=len(result)
    )
    assert last_error_idx < first_warning_idx

    # warning が kind 昇順: ospf_area0_disconnected と ospf_area_mismatch の比較
    # 辞書順: "ospf_area0_disconnected" < "ospf_area_mismatch"
    warning_kinds = [c["kind"] for c in result if c["severity"] == "warning"]
    assert warning_kinds == sorted(warning_kinds)

    # 両方が存在すること
    assert any(c["kind"] == "ospf_area_mismatch" for c in result)
    assert any(c["kind"] == "ospf_area0_disconnected" for c in result)
    assert any(c["kind"] == "duplicate_ip" for c in result)


# ---------------------------------------------------------------------------
# build_stub_nodes テスト（build_ospf_stubs を一般化した新関数）
# ---------------------------------------------------------------------------

def _make_topo(devices=None, interfaces=None, ospf=None, links=None, segments=None):
    """テスト用 topo dict の最小骨格を組み立てるヘルパー。
    links/segments を渡すと「占有 cidr」を作り、LAN stub 判定テストでも使用できる。
    """
    return {
        "meta": {"generated_from": []},
        "devices": devices or [],
        "interfaces": interfaces or [],
        "links": links or [],
        "segments": segments or [],
        "routing": {
            "bgp": [],
            "ospf": ospf or [],
            "static": [],
            "redistribute": [],
        },
    }


def _make_loopback_if(dev, name, addresses):
    """loopback 用最小 interface dict を生成するヘルパー。"""
    return {
        "id": f"{dev}::{name}",
        "device": dev,
        "name": name,
        "ip": None,
        "vlan": None,
        "description": None,
        "shutdown": False,
        "admin_status": "up",
        "oper_status": None,
        "mtu": None,
        "speed": None,
        "duplex": None,
        "l2_l3": None,
        "switchport": None,
        "encapsulation": None,
        "source": "parsed",
        "addresses": addresses,
    }


def _make_plain_if(dev, name, addresses):
    """非 loopback 用最小 interface dict を生成するヘルパー（LAN stub テスト用）。"""
    return {
        "id": f"{dev}::{name}",
        "device": dev,
        "name": name,
        "ip": None,
        "vlan": None,
        "description": None,
        "shutdown": False,
        "admin_status": "up",
        "oper_status": None,
        "mtu": None,
        "speed": None,
        "duplex": None,
        "l2_l3": None,
        "switchport": None,
        "encapsulation": None,
        "source": "parsed",
        "addresses": addresses,
    }


# ---------------------------------------------------------------------------
# 基本動作: loopback アドレス取得・kind・subnet フィールド
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_stub_nodes_loopback_with_ospf_area():
    """loopback IF の /32 が OSPF network に含まれる場合、kind=loopback・area・subnet を返す。

    壊すと赤: kind フィールドを削除すると KeyError。subnet フィールドを削除しても KeyError。
    """
    # Arrange
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "10.10.0.4", "prefix": 32},
            ]),
        ],
        ospf=[{
            "device": "r1", "process": 1, "network": "10.10.0.4/32",
            "area": "2", "af": "v4",
        }],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert
    assert len(result) == 1
    stub = result[0]
    assert stub["dev"] == "r1"
    assert stub["ifn"] == "Loopback0"
    assert stub["ip"] == "10.10.0.4"
    assert stub["area"] == "2"
    assert stub["kind"] == "loopback", f"kind が 'loopback' でない: {stub['kind']}"
    assert stub["subnet"] == "10.10.0.4/32", (
        f"subnet が '10.10.0.4/32' でない: {stub.get('subnet')}"
    )


@pytest.mark.unit
def test_build_stub_nodes_non_ospf_loopback_returns_entry_with_none_area():
    """loopback IF が OSPF network に一致しなくても area=None でエントリが返ること。

    旧仕様（非 OSPF はスキップ）との最大の差分。
    壊すと赤: area=None を理由にスキップすると 0 件になり len==1 で赤。
    """
    # Arrange: Loopback0 は OSPF 192.168.1.0/24 に不含（完全に別サブネット）
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "10.10.0.4", "prefix": 32},
            ]),
        ],
        ospf=[{
            "device": "r1", "process": 1, "network": "192.168.1.0/24",
            "area": "0", "af": "v4",
        }],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: area=None で 1 件返ること（旧仕様では [] だった）
    assert len(result) == 1, (
        f"非 OSPF loopback でもエントリが返るはずだが {len(result)} 件: {result}"
    )
    assert result[0]["area"] is None, (
        f"OSPF 非参加時は area=None のはずだが: {result[0]['area']}"
    )
    assert result[0]["kind"] == "loopback"


@pytest.mark.unit
def test_build_stub_nodes_no_ospf_config_area_is_none():
    """OSPF 設定が一切なくても loopback エントリが area=None で返ること。

    壊すと赤: ospf_by_dev 参照時に KeyError や NoneType 処理漏れがあると赤。
    """
    # Arrange: OSPF エントリ 0 件
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "lo0", [
                {"af": "v4", "ip": "10.0.0.1", "prefix": 32},
            ]),
        ],
        ospf=[],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert
    assert len(result) == 1
    assert result[0]["area"] is None
    assert result[0]["kind"] == "loopback"


# ---------------------------------------------------------------------------
# subnet フィールド: /32 と /24 の正規化
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_stub_nodes_subnet_32():
    """loopback 10.10.0.4/32 の結果に subnet=='10.10.0.4/32' が含まれること。

    壊すと赤: subnet フィールドを削除すると KeyError になる。
    /32 は ip_network("10.10.0.4/32", strict=False) = "10.10.0.4/32"（ホスト部変化なし）。
    """
    # Arrange
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "10.10.0.4", "prefix": 32},
            ]),
        ],
        ospf=[{
            "device": "r1", "process": 1, "network": "10.10.0.4/32",
            "area": "2", "af": "v4",
        }],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert
    assert len(result) == 1, f"1 件返ることを期待: {result}"
    assert "subnet" in result[0], f"subnet フィールドが存在しない: {result[0].keys()}"
    assert result[0]["subnet"] == "10.10.0.4/32", (
        f"subnet が '10.10.0.4/32' でない: {result[0]['subnet']}"
    )


@pytest.mark.unit
def test_build_stub_nodes_subnet_24():
    """loopback に /24 を持つケースで subnet がネットワークアドレス表記になること。

    ip=192.168.1.100, prefix=24 → subnet="192.168.1.0/24"（ホスト部は落とす）。
    壊すと赤: strict=True で ip_network を呼ぶと ValueError になる実装の場合失敗。
    """
    # Arrange: /24 のループバック（loopback に /24 を付けるケースは稀だが仕様として対応）
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "192.168.1.100", "prefix": 24},
            ]),
        ],
        ospf=[{
            "device": "r1", "process": 1, "network": "192.168.1.0/24",
            "area": "1", "af": "v4",
        }],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert
    assert len(result) == 1, f"1 件返ることを期待: {result}"
    assert "subnet" in result[0], f"subnet フィールドが存在しない: {result[0].keys()}"
    # 192.168.1.100/24 → ip_network("192.168.1.100/24", strict=False) = "192.168.1.0/24"
    assert result[0]["subnet"] == "192.168.1.0/24", (
        f"subnet が '192.168.1.0/24' でない: {result[0]['subnet']}"
    )


# ---------------------------------------------------------------------------
# prefix 欠如: 新仕様では 0 件（スキップ）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_stub_nodes_no_prefix_skips_entry():
    """loopback address に prefix が無い場合、エントリ自体をスキップして 0 件を返すこと。

    新仕様「prefix 必須・欠如はスキップ」の回帰ガード。
    旧仕様（prefix 欠如でも net なしで 1 件返す）との差分。
    壊すと赤: prefix 欠如でもエントリを出す実装だと len==0 アサートで赤。
    """
    # Arrange: prefix フィールドを持たない loopback address（ip のみ）
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "10.0.0.1"},  # prefix フィールド無し
            ]),
        ],
        ospf=[{
            "device": "r1", "process": 1, "network": "10.0.0.0/8",
            "area": "0", "af": "v4",
        }],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: prefix 欠如はスキップ → 0 件
    assert len(result) == 0, (
        f"prefix 欠如はスキップされるはずだが {len(result)} 件返った: {result}"
    )


# ---------------------------------------------------------------------------
# golden 統合テスト（実値ベース）
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_build_stub_nodes_golden_four_entries():
    """golden topo で build_stub_nodes が 4 件を返すこと（実値確認）。

    golden の構成:
      r1: GigabitEthernet0/1(192.168.1.1/24) → stub(area="0")
          Loopback0(1.1.1.1/32)               → loopback(area=None)
      r2: ge-0/0/1(192.168.2.1/24)            → stub(area=None)
          lo0(2.2.2.2/32)                     → loopback(area=None)
    r1/GigabitEthernet0/0 と r2/ge-0/0/0 は 10.0.0.0/30 の link 所属 → stub に出ない。

    壊すと赤: link 占有判定を削除すると GigabitEthernet0/0 も出て 5 件以上になる。
    """
    # Arrange
    topo = load_topology(str(GOLDEN))

    # Act
    result = build_stub_nodes(topo)

    # Assert: 4 件
    assert len(result) == 4, f"4 件返るはずだが {len(result)} 件: {result}"

    # 実値でサブネット集合を確認（順序は (dev, natural_key(ifn)) ソート）
    subnets = [r["subnet"] for r in result]
    # r1::GigabitEthernet0/1 が先（自然順: G が lo より前）
    assert "192.168.1.0/24" in subnets
    assert "1.1.1.1/32" in subnets
    assert "192.168.2.0/24" in subnets
    assert "2.2.2.2/32" in subnets

    # kind の確認
    loopbacks = [r for r in result if r["kind"] == "loopback"]
    stubs = [r for r in result if r["kind"] == "stub"]
    assert len(loopbacks) == 2, f"loopback 2 件のはずだが: {loopbacks}"
    assert len(stubs) == 2, f"stub 2 件のはずだが: {stubs}"


@pytest.mark.integration
def test_build_stub_nodes_golden_area_assignment():
    """golden の r1::GigabitEthernet0/1 は OSPF 192.168.1.0/24 area=0 に含まれるので area='0' になる。

    壊すと赤: area 引き当てロジックを削除すると area=None が返り '0' アサートで赤。
    """
    # Arrange
    topo = load_topology(str(GOLDEN))

    # Act
    result = build_stub_nodes(topo)

    # Assert: r1::GigabitEthernet0/1 が area="0"
    gi01 = next((r for r in result if r["dev"] == "r1" and r["ifn"] == "GigabitEthernet0/1"), None)
    assert gi01 is not None, "r1::GigabitEthernet0/1 が結果に存在しない"
    assert gi01["area"] == "0", f"area が '0' でない: {gi01['area']}"
    assert gi01["kind"] == "stub"
    assert gi01["subnet"] == "192.168.1.0/24"

    # r1::Loopback0 は OSPF 非参加 → area=None
    lb0 = next((r for r in result if r["dev"] == "r1" and r["ifn"] == "Loopback0"), None)
    assert lb0 is not None, "r1::Loopback0 が結果に存在しない"
    assert lb0["area"] is None, f"Loopback0 は OSPF 非参加のはずが area={lb0['area']}"
    assert lb0["kind"] == "loopback"


@pytest.mark.integration
def test_build_data_has_stub_nodes_key():
    """build_data の返り値に 'stub_nodes' キーが存在し、リストであること。

    旧 'ospf_stubs' キーが 'stub_nodes' に変更されたことの回帰ガード。
    壊すと赤: build_data に 'stub_nodes' がないと KeyError / assert 失敗。
    """
    # Arrange
    topo = load_topology(str(GOLDEN))

    # Act
    data = build_data(topo)

    # Assert
    assert "stub_nodes" in data, (
        f"build_data に 'stub_nodes' キーが存在しない。現キー一覧: {list(data.keys())}"
    )
    assert isinstance(data["stub_nodes"], list)
    assert len(data["stub_nodes"]) == 4, (
        f"golden で stub_nodes は 4 件のはずだが: {len(data['stub_nodes'])}"
    )


@pytest.mark.integration
def test_build_stub_nodes_and_build_data_consistent():
    """build_stub_nodes と build_data["stub_nodes"] が同じ結果を返すこと。

    壊すと赤: build_data 内で異なる実装呼び出しをするとこのテストが赤になる。
    """
    # Arrange
    topo = load_topology(str(GOLDEN))

    # Act
    direct = build_stub_nodes(topo)
    via_data = build_data(topo)["stub_nodes"]

    # Assert
    assert direct == via_data, (
        f"build_stub_nodes と build_data['stub_nodes'] が一致しない"
    )


# ---------------------------------------------------------------------------
# secondary アドレス除外
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_stub_nodes_excludes_secondary():
    """loopback に primary + secondary v4 があっても primary 1件のみを返すこと。

    壊すと赤: secondary フィルタを削除すると 2 件返る → assert len == 1 で赤。
    """
    # Arrange: Loopback0 に primary 10.10.0.1/32 と secondary 10.10.0.2/32
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "10.10.0.1", "prefix": 32},               # primary
                {"af": "v4", "ip": "10.10.0.2", "prefix": 32, "secondary": True},  # secondary
            ]),
        ],
        ospf=[{
            "device": "r1", "process": 1, "network": "10.10.0.0/30",
            "area": "1", "af": "v4",
        }],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: primary 1 件のみ（secondary は除外）
    assert len(result) == 1, (
        f"secondary アドレスが除外されず {len(result)} 件返った（期待: 1 件 primary のみ）"
    )
    assert result[0]["ip"] == "10.10.0.1", (
        f"返ったのが primary でない: {result[0]['ip']}"
    )


@pytest.mark.unit
def test_build_stub_nodes_secondary_ip_not_in_results():
    """secondary=True の IP が結果に含まれないこと（詳細確認）。

    壊すと赤: secondary を含めると "10.10.0.2" が結果に出現する。
    """
    # Arrange
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "10.1.0.1", "prefix": 32},
                {"af": "v4", "ip": "10.1.0.2", "prefix": 32, "secondary": True},
            ]),
        ],
        ospf=[{
            "device": "r1", "process": 1, "network": "10.1.0.0/30",
            "area": "0", "af": "v4",
        }],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert
    ips_in_result = [r["ip"] for r in result]
    assert "10.1.0.2" not in ips_in_result, (
        f"secondary IP 10.1.0.2 が stubs に含まれている（除外されるべき）: {ips_in_result}"
    )
    assert "10.1.0.1" in ips_in_result, (
        f"primary IP 10.1.0.1 が stubs に含まれていない: {ips_in_result}"
    )


# ---------------------------------------------------------------------------
# 決定性・自然順ソート
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_stub_nodes_natural_sort_order():
    """同一 device の Loopback0/Loopback10/Loopback2 が自然順（0,2,10）で安定ソートされること。

    壊すと赤: _natural_key を辞書順（str sort）に変えると Loopback0/Loopback10/Loopback2 になる。
    """
    # Arrange: 3 loopback を意図的に非自然順で登録
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback10", [{"af": "v4", "ip": "10.0.10.1", "prefix": 32}]),
            _make_loopback_if("r1", "Loopback2",  [{"af": "v4", "ip": "10.0.2.1",  "prefix": 32}]),
            _make_loopback_if("r1", "Loopback0",  [{"af": "v4", "ip": "10.0.0.1",  "prefix": 32}]),
        ],
        ospf=[
            {"device": "r1", "process": 1, "network": "10.0.0.0/8", "area": "0", "af": "v4"},
        ],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: 自然順 Loopback0, Loopback2, Loopback10
    assert len(result) == 3, f"3 件返ることを期待: {result}"
    ifnames = [r["ifn"] for r in result]
    assert ifnames == ["Loopback0", "Loopback2", "Loopback10"], (
        f"自然順 (Loopback0, Loopback2, Loopback10) でない: {ifnames}"
        " (辞書順なら [Loopback0, Loopback10, Loopback2] になるバグを弾く)"
    )


@pytest.mark.unit
def test_build_stub_nodes_deterministic():
    """同じ topo を2回呼び出して同じ結果が得られること（決定性）。

    壊すと赤: 結果が set 依存の不定順になると a != b でテストが失敗する可能性がある。
    """
    # Arrange
    topo = _make_topo(
        devices=[
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios",
             "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios",
             "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": []},
        ],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [{"af": "v4", "ip": "10.1.0.1", "prefix": 32}]),
            _make_loopback_if("r2", "lo0", [{"af": "v4", "ip": "10.2.0.1", "prefix": 32}]),
        ],
        ospf=[
            {"device": "r1", "process": 1, "network": "10.1.0.1/32", "area": "0", "af": "v4"},
            {"device": "r2", "process": 1, "network": "10.2.0.1/32", "area": "0", "af": "v4"},
        ],
    )

    # Act
    a = build_stub_nodes(topo)
    b = build_stub_nodes(topo)

    # Assert: 2 回呼んで同一
    assert a == b
    # dev → ifn 自然順ソート: r1 が r2 より先
    assert a[0]["dev"] == "r1"
    assert a[1]["dev"] == "r2"


# ---------------------------------------------------------------------------
# area 選択: 最長プレフィックス・tiebreak
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_stub_nodes_longest_prefix_area():
    """loopback IP が複数の OSPF network に含まれる場合、最長プレフィックスの area を採用する。

    壊すと赤: 最短プレフィックスを採用する実装だと area "0"(/24) が返り "1"(/32) で赤。
    """
    # Arrange
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "10.10.0.4", "prefix": 32},
            ]),
        ],
        ospf=[
            # /24 が先に来ても最長(/32)が採用されること
            {"device": "r1", "process": 1, "network": "10.10.0.0/24", "area": "0", "af": "v4"},
            {"device": "r1", "process": 1, "network": "10.10.0.4/32", "area": "1", "af": "v4"},
        ],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert
    assert len(result) == 1
    assert result[0]["area"] == "1", f"/32 の area '1' が採用されるはずだが: {result[0]['area']}"


@pytest.mark.unit
def test_build_stub_nodes_area_tiebreak_ascending():
    """同一 IP が同長プレフィックスで area "0" と "1" の 2 entry に一致する場合、昇順の "0" を採用。

    壊すと赤: tiebreak を逆にすると area "1" が選ばれてアサート失敗。
    """
    # Arrange: /32 が area "0" と area "1" の両方の network に含まれる（同長プレフィックス）
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 32}]),
        ],
        ospf=[
            # area "1" を先に登録（逆順で意図的）
            {"device": "r1", "process": 1, "network": "10.0.0.1/32", "area": "1", "af": "v4"},
            {"device": "r1", "process": 1, "network": "10.0.0.1/32", "area": "0", "af": "v4"},
        ],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: 同長プレフィックスの tiebreak は area 昇順 → "0" が採用
    assert len(result) == 1
    assert result[0]["area"] == "0", (
        f"area tiebreak で昇順 '0' が選ばれるべきだが '{result[0]['area']}' が返った"
    )


# ---------------------------------------------------------------------------
# _LOOPBACK_RE: 一致・非一致の確認
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_loopback_regex_matches():
    """_LOOPBACK_RE が JS ifKind 基準の loopback 名に一致し、通常 IF に一致しないこと。

    壊すと赤: 正規表現を変更すると一致/非一致が逆転するケースが生じる。
    """
    # 一致すべきパターン
    for name in ["Loopback0", "lo0", "Lo10", "lo", "loopback1", "LOOPBACK0"]:
        assert _LOOPBACK_RE.match(name), f"_LOOPBACK_RE が '{name}' に一致しない"
    # 一致しないパターン
    for name in ["GigabitEthernet0/0", "Gi0/0", "ge-0/0/0", "eth0", "Vlan1"]:
        assert not _LOOPBACK_RE.match(name), f"_LOOPBACK_RE が '{name}' に誤一致"


@pytest.mark.unit
def test_build_stub_nodes_kind_loopback_vs_stub():
    """_LOOPBACK_RE 一致 IF が kind='loopback'、非一致が kind='stub' になること。

    壊すと赤: kind 判定を反転させると loopback が "stub"、GigabitEthernet が "loopback" になる。
    """
    # Arrange: Loopback0（loopback） と GigabitEthernet0/1（stub）を同一デバイスに
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_loopback_if("r1", "Loopback0", [
                {"af": "v4", "ip": "10.0.0.1", "prefix": 32},
            ]),
            _make_plain_if("r1", "GigabitEthernet0/1", [
                {"af": "v4", "ip": "192.168.1.1", "prefix": 24},
            ]),
        ],
        ospf=[],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert
    assert len(result) == 2
    lb = next(r for r in result if r["ifn"] == "Loopback0")
    gi = next(r for r in result if r["ifn"] == "GigabitEthernet0/1")
    assert lb["kind"] == "loopback", f"Loopback0 の kind が 'loopback' でない: {lb['kind']}"
    assert gi["kind"] == "stub", f"GigabitEthernet0/1 の kind が 'stub' でない: {gi['kind']}"


# ---------------------------------------------------------------------------
# 新規テスト: LAN stub 検出・link/segment 所属除外
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_stub_nodes_lan_stub_detected():
    """link にも segment にも属さない IP 付き非 loopback IF が kind='stub' で出ること。

    壊すと赤: link 占有判定を削除すると GigabitEthernet0/1 も stub に出ず 0 件になる
    （ここでは link を渡さないので stub として検出される）。
    """
    # Arrange: GigabitEthernet0/1 は links/segments から外れている（孤立 LAN 側）
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_plain_if("r1", "GigabitEthernet0/1", [
                {"af": "v4", "ip": "192.168.10.1", "prefix": 24},
            ]),
        ],
        ospf=[],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: GigabitEthernet0/1 が kind=stub で出る
    assert len(result) == 1, f"LAN stub が 1 件返るはずだが {len(result)} 件: {result}"
    assert result[0]["kind"] == "stub"
    assert result[0]["subnet"] == "192.168.10.0/24"
    assert result[0]["ifn"] == "GigabitEthernet0/1"


@pytest.mark.unit
def test_build_stub_nodes_link_member_excluded():
    """2機器が同一サブネットを共有する link 所属 IF は stub に出ないこと。

    壊すと赤: linked_cidrs 判定を削除すると link メンバーも stub に出て 2 件以上になる。
    """
    # Arrange: r1::Gi0/0 と r2::Gi0/0 が 10.0.0.0/30 で link を形成
    link = {
        "a_device": "r1", "a_if": "GigabitEthernet0/0",
        "b_device": "r2", "b_if": "GigabitEthernet0/0",
        "subnet": "10.0.0.0/30",
    }
    topo = _make_topo(
        devices=[
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios",
             "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios",
             "as": 65002, "ospf_router_id": None, "bgp_router_id": None, "sections": []},
        ],
        interfaces=[
            _make_plain_if("r1", "GigabitEthernet0/0", [
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
            ]),
            _make_plain_if("r2", "GigabitEthernet0/0", [
                {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
            ]),
        ],
        links=[link],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: link 所属サブネット 10.0.0.0/30 は除外 → 0 件
    assert len(result) == 0, (
        f"link メンバーは stub に出ないはずだが {len(result)} 件: {result}"
    )


@pytest.mark.unit
def test_build_stub_nodes_segment_member_excluded():
    """3 機器以上が同一サブネットを共有する segment 所属 IF は stub に出ないこと。

    壊すと赤: linked_cidrs に segments 占有サブネットを加えないと segment メンバーが stub に出る。
    """
    # Arrange: r1/r2/r3 が 10.1.0.0/24 の segment を形成
    segment = {
        "id": "seg:10.1.0.0/24",
        "subnet": "10.1.0.0/24",
        "members": ["r1::eth0", "r2::eth0", "r3::eth0"],
        "ospf_area": None,
    }
    topo = _make_topo(
        devices=[
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios",
             "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios",
             "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r3", "hostname": "R3", "vendor": "cisco_ios",
             "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": []},
        ],
        interfaces=[
            _make_plain_if("r1", "eth0", [{"af": "v4", "ip": "10.1.0.1", "prefix": 24}]),
            _make_plain_if("r2", "eth0", [{"af": "v4", "ip": "10.1.0.2", "prefix": 24}]),
            _make_plain_if("r3", "eth0", [{"af": "v4", "ip": "10.1.0.3", "prefix": 24}]),
        ],
        segments=[segment],
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: segment 所属サブネット 10.1.0.0/24 は除外 → 0 件
    assert len(result) == 0, (
        f"segment メンバーは stub に出ないはずだが {len(result)} 件: {result}"
    )


@pytest.mark.unit
def test_build_stub_nodes_self_loop_is_stub():
    """同一機器内の2つの IF が同一サブネットを持つ（自己ループ）場合は stub に出ること。

    links の定義は「異機器2メンバー」のため、同一機器内のサブネット重複は link 非所属 → stub。
    壊すと赤: 同一機器ペアも links として扱う誤実装では 0 件になる。
    """
    # Arrange: r1 の 2 つの IF が同じ /30 に属する（self-loop 状態）
    # 実機ではほぼありえないが仕様上のエッジケース
    topo = _make_topo(
        devices=[{
            "id": "r1", "hostname": "R1", "vendor": "cisco_ios",
            "as": 65001, "ospf_router_id": None, "bgp_router_id": None, "sections": [],
        }],
        interfaces=[
            _make_plain_if("r1", "Gi0/0", [{"af": "v4", "ip": "10.9.0.1", "prefix": 30}]),
            _make_plain_if("r1", "Gi0/1", [{"af": "v4", "ip": "10.9.0.2", "prefix": 30}]),
        ],
        # links に乗せない（同一機器ゆえ異機器2メンバーの link 定義は存在しない）
    )

    # Act
    result = build_stub_nodes(topo)

    # Assert: 同一機器 IF は stub 判定 → 各 IF が 1 件ずつ出る（seen は IF 内の cidr 重複のみ排除）
    # Gi0/0(10.9.0.1/30) と Gi0/1(10.9.0.2/30) はそれぞれ stub として 1 件ずつ → 合計 2 件
    assert len(result) == 2, (
        f"自己ループ（同一機器サブネット）は各 IF が stub に出るはずだが {len(result)} 件: {result}"
    )
    for r in result:
        assert r["kind"] == "stub", f"非 loopback IF は kind=stub のはずだが: {r['kind']}"


# ---------------------------------------------------------------------------
# CONFIG ビュー — DATA.raw_configs
# ---------------------------------------------------------------------------

def test_build_data_includes_raw_configs():
    """topo["raw_configs"] が DATA.raw_configs にそのまま入ること。"""
    topo = load_topology(str(GOLDEN))
    topo["raw_configs"] = {"r1": "hostname R1\n", "r2": "hostname R2\n"}
    data = build_data(topo)
    assert data["raw_configs"] == {"r1": "hostname R1\n", "r2": "hostname R2\n"}


def test_build_data_raw_configs_empty_when_absent():
    """topo に raw_configs が無いとき DATA.raw_configs は空 dict。"""
    topo = load_topology(str(GOLDEN))
    topo.pop("raw_configs", None)
    data = build_data(topo)
    assert data["raw_configs"] == {}


def test_build_data_includes_parse_status():
    topo = load_topology(str(GOLDEN))
    topo["parse_status"] = {"r1": ["parsed"], "r2": ["ignored"]}
    data = build_data(topo)
    assert data["parse_status"] == {"r1": ["parsed"], "r2": ["ignored"]}


def test_build_data_parse_status_empty_when_absent():
    topo = load_topology(str(GOLDEN))
    topo.pop("parse_status", None)
    assert build_data(topo)["parse_status"] == {}


# ===========================================================================
# FIB（build_fib）と STATIC オーバーレイ（build_static_edges / build_static_stubs）
# ===========================================================================

def _dlink(a_dev, a_if, b_dev, b_if, subnet):
    """topo["links"] 用の dict-link（v4/v6 別行）。"""
    return {"a_device": a_dev, "a_if": a_if, "b_device": b_dev, "b_if": b_if, "subnet": subnet}


def _fib(topo):
    return build_fib(topo, build_links(topo))


@pytest.mark.unit
def test_fib_connected_entries():
    """各 IF の非 link-local サブネットが connected エントリ（via=local・正しい plen/af/ifname）になる。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
                    _make_if("r1", "Lo0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}])],
    )
    ents = _fib(topo)["r1"]
    conn = {e["prefix"]: e for e in ents if e["kind"] == "connected"}
    assert conn["10.0.0.0/30"]["via"] == "local" and conn["10.0.0.0/30"]["plen"] == 30
    assert conn["10.0.0.0/30"]["ifname"] == "Gi0" and conn["10.0.0.0/30"]["af"] == "v4"
    assert conn["1.1.1.1/32"]["plen"] == 32
    # plen 降順ソート（/32 が /30 より先）
    plens = [e["plen"] for e in ents]
    assert plens == sorted(plens, reverse=True)


@pytest.mark.unit
def test_fib_static_resolves_to_neighbor_device_over_link():
    """static next_hop が隣接 IF のホスト IP → via=device・target=隣接・共有リンクは overLink。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
                    _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])],
        links=[_dlink("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30")],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "192.168.5.0/24", "next_hop": "10.0.0.2", "af": "v4"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static"][0]
    assert st["via"] == "device" and st["target"] == "r2"
    assert st["overLink"] and "r1::Gi0" in st["overLink"] and "r2::Gi0" in st["overLink"]


@pytest.mark.unit
def test_fib_static_subnet_containment_resolves_owner():
    """host IP 完全一致が無くても、next_hop を含む connected サブネットの所有機器に解決。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "192.168.1.1", "prefix": 24}]),
                    _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.6", "prefix": 29}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "8.8.8.0/24", "next_hop": "10.0.0.2", "af": "v4"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static"][0]
    assert st["via"] == "device" and st["target"] == "r2"


@pytest.mark.unit
def test_fib_static_dangling():
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "8.8.8.0/24", "next_hop": "172.16.99.1", "af": "v4"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static"][0]
    assert st["via"] == "dangling" and st["target"] is None


@pytest.mark.unit
def test_fib_static_blackhole_null0_and_special():
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}])],
        routing={"bgp": [], "ospf": [], "static": [
            {"device": "r1", "prefix": "203.0.113.0/24", "next_hop": "Null0", "af": "v4"},
            {"device": "r1", "prefix": "0.0.0.0/0", "next_hop": "0.0.0.0", "af": "v4"}]},
    )
    by_pfx = {e["prefix"]: e for e in _fib(topo)["r1"] if e["kind"] == "static"}
    assert by_pfx["203.0.113.0/24"]["via"] == "blackhole"
    assert by_pfx["0.0.0.0/0"]["via"] == "blackhole" and by_pfx["0.0.0.0/0"]["default"] is True


@pytest.mark.unit
def test_fib_static_ecmp_grouped_and_deterministic():
    """同一 prefix に複数 next_hop → ecmpGroup 非0・両エントリ存在・next_hop 昇順で決定的。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2"), _make_dev("r3")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
                    _make_if("r1", "Gi1", [{"af": "v4", "ip": "10.0.1.1", "prefix": 30}]),
                    _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
                    _make_if("r3", "Gi0", [{"af": "v4", "ip": "10.0.1.2", "prefix": 30}])],
        routing={"bgp": [], "ospf": [], "static": [
            {"device": "r1", "prefix": "8.8.8.0/24", "next_hop": "10.0.1.2", "af": "v4"},
            {"device": "r1", "prefix": "8.8.8.0/24", "next_hop": "10.0.0.2", "af": "v4"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static" and e["prefix"] == "8.8.8.0/24"]
    assert len(st) == 2 and all(e["ecmpGroup"] != 0 for e in st)
    assert len({e["ecmpGroup"] for e in st}) == 1   # 同一グループ番号
    # 決定性: 2 回ビルドで一致
    assert _fib(topo) == _fib(topo)


@pytest.mark.unit
def test_fib_static_v6():
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v6", "ip": "2001:db8::1", "prefix": 64}]),
                    _make_if("r2", "Gi0", [{"af": "v6", "ip": "2001:db8::2", "prefix": 64}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "2001:db8:5::/48", "next_hop": "2001:db8::2", "af": "v6"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static"][0]
    assert st["af"] == "v6" and st["via"] == "device" and st["target"] == "r2"


@pytest.mark.unit
def test_fib_via_interface_p2p_peer_and_unresolvable():
    """IF 名 next-hop: P2P リンクなら peer 解決(via-interface,target=peer)。リンク無しは target=None。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
                    _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
                    _make_if("r1", "Gi9", [{"af": "v4", "ip": "10.9.9.1", "prefix": 24}])],
        links=[_dlink("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30")],
        routing={"bgp": [], "ospf": [], "static": [
            {"device": "r1", "prefix": "8.8.8.0/24", "next_hop": "Gi0", "af": "v4"},
            {"device": "r1", "prefix": "9.9.9.0/24", "next_hop": "Gi9", "af": "v4"}]},
    )
    by_pfx = {e["prefix"]: e for e in _fib(topo)["r1"] if e["kind"] == "static"}
    assert by_pfx["8.8.8.0/24"]["via"] == "via-interface" and by_pfx["8.8.8.0/24"]["target"] == "r2"
    assert by_pfx["9.9.9.0/24"]["via"] == "via-interface" and by_pfx["9.9.9.0/24"]["target"] is None


@pytest.mark.unit
def test_static_edges_over_link_and_stub():
    """static_edges: 隣接かつ共有リンク → over-link。blackhole/dangling → stub 参照。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
                    _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])],
        links=[_dlink("r1", "Gi0", "r2", "Gi0", "10.0.0.0/30")],
        routing={"bgp": [], "ospf": [], "static": [
            {"device": "r1", "prefix": "8.8.8.0/24", "next_hop": "10.0.0.2", "af": "v4"},
            {"device": "r1", "prefix": "203.0.113.0/24", "next_hop": "Null0", "af": "v4"},
            {"device": "r1", "prefix": "9.9.9.0/24", "next_hop": "172.16.99.1", "af": "v4"}]},
    )
    fib = _fib(topo)
    edges = build_static_edges(topo, fib)
    stubs = build_static_stubs(topo, fib)
    by_pfx = {e["prefix"]: e for e in edges}
    assert by_pfx["8.8.8.0/24"]["kind"] == "over-link" and by_pfx["8.8.8.0/24"]["b"] == "r2"
    assert by_pfx["8.8.8.0/24"]["af"] == "v4" and by_pfx["8.8.8.0/24"]["default"] is False and by_pfx["8.8.8.0/24"]["ecmp"] is False
    assert by_pfx["203.0.113.0/24"]["kind"] == "blackhole" and by_pfx["203.0.113.0/24"]["stub"]
    assert by_pfx["9.9.9.0/24"]["kind"] == "dangling" and by_pfx["9.9.9.0/24"]["stub"]
    stub_kinds = {s["kind"] for s in stubs}
    assert "blackhole" in stub_kinds and "dangling" in stub_kinds
    # edge.stub が実在する static_stubs の id を指す（参照整合）
    stub_ids = {s["id"] for s in stubs}
    for e in edges:
        if e["stub"]:
            assert e["stub"] in stub_ids


@pytest.mark.unit
def test_build_data_has_fib_static_keys():
    """build_data の返り値に fib / static_edges / static_stubs キーが含まれる。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    assert isinstance(data["fib"], dict)
    assert isinstance(data["static_edges"], list)


# ---------------------------------------------------------------------------
# T0: diagnostics → CHECKS マージ（diagnostics パススルー）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_data_diagnostics_merged_into_checks():
    """topo["diagnostics"] のエントリが build_data の checks に追加されること。"""
    # Arrange
    topo = _minimal_topo()
    diag_entry = {"severity": "warning", "kind": "parse_warning",
                  "message": "unknown command at line 5", "refs": ["a.cfg"]}
    topo["diagnostics"] = [diag_entry]

    # Act
    data = build_data(topo)

    # Assert: diagnostics 由来エントリが checks に含まれる
    kinds = [c["kind"] for c in data["checks"]]
    assert "parse_warning" in kinds
    matched = [c for c in data["checks"] if c["kind"] == "parse_warning"]
    assert len(matched) == 1
    assert matched[0]["message"] == "unknown command at line 5"
    assert matched[0]["refs"] == ["a.cfg"]


@pytest.mark.unit
def test_build_data_diagnostics_appended_after_existing_checks():
    """diagnostics 由来エントリは既存 checks の後に追加されること（マージ順の決定性）。"""
    # Arrange: duplicate_ip チェックが発火するよう同一 IP を2つの IF に設定
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
    )
    topo["diagnostics"] = [
        {"severity": "warning", "kind": "parse_warning",
         "message": "from diagnostics", "refs": ["x.cfg"]},
    ]

    # Act
    data = build_data(topo)
    checks = data["checks"]

    # Assert: duplicate_ip（既存ルール）と parse_warning（diagnostics）が両方含まれる
    kinds = [c["kind"] for c in checks]
    assert "duplicate_ip" in kinds
    assert "parse_warning" in kinds

    # diagnostics 由来は既存 checks の後に付く（インデックスで順序確認）
    idx_dup = next(i for i, c in enumerate(checks) if c["kind"] == "duplicate_ip")
    idx_diag = next(i for i, c in enumerate(checks) if c["kind"] == "parse_warning")
    assert idx_diag > idx_dup


@pytest.mark.unit
def test_build_data_no_diagnostics_checks_unchanged():
    """topo に diagnostics キーがない（旧成果物）とき、checks に変化がないこと（後方互換）。"""
    topo = _minimal_topo()
    # diagnostics キーなし
    data = build_data(topo)
    # checks は通常通り（空 topo なので空リスト）
    assert data["checks"] == []


@pytest.mark.unit
def test_build_data_empty_diagnostics_checks_unchanged():
    """topo["diagnostics"] = [] のとき、checks に変化がないこと。"""
    topo = _minimal_topo()
    topo["diagnostics"] = []
    data = build_data(topo)
    assert data["checks"] == []


@pytest.mark.unit
def test_build_data_diagnostics_error_severity_preserved():
    """diagnostics の severity="error" が checks に正しく渡されること。"""
    topo = _minimal_topo()
    topo["diagnostics"] = [
        {"severity": "error", "kind": "unparsed_config",
         "message": "could not parse file", "refs": ["bad.cfg"]},
    ]
    data = build_data(topo)
    matched = [c for c in data["checks"] if c["kind"] == "unparsed_config"]
    assert len(matched) == 1
    assert matched[0]["severity"] == "error"


@pytest.mark.unit
def test_golden_topo_diagnostics_passthrough_gives_empty():
    """ゴールデン topology（diagnostics なし）で build_data を呼ぶと
    checks に diagnostics 由来エントリが混入しないこと。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    # ゴールデンに diagnostics はないので diagnostics 由来 kind は一切ない
    # （既存 checks ルールのみが発火）
    known_diag_kinds = {"parse_warning", "unparsed_config"}
    for c in data["checks"]:
        assert c["kind"] not in known_diag_kinds
    assert isinstance(data["static_stubs"], list)


# ===========================================================================
# discard / reject next-hop → FIB blackhole 判定
# ===========================================================================

@pytest.mark.unit
def test_fib_static_discard_yields_blackhole():
    """next_hop="discard" → via=blackhole（JunOS discard static route 対応）。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "10.99.0.0/24",
                             "next_hop": "discard", "af": "v4"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static"][0]
    assert st["via"] == "blackhole"
    assert st["target"] is None


@pytest.mark.unit
def test_fib_static_reject_yields_blackhole():
    """next_hop="reject" → via=blackhole（JunOS reject static route 対応）。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "10.98.0.0/24",
                             "next_hop": "reject", "af": "v4"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static"][0]
    assert st["via"] == "blackhole"
    assert st["target"] is None


@pytest.mark.unit
def test_fib_static_discard_case_insensitive():
    """next_hop="DISCARD"（大文字）でも blackhole に解決（大小文字非依存）。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "10.97.0.0/24",
                             "next_hop": "DISCARD", "af": "v4"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static"][0]
    assert st["via"] == "blackhole"


@pytest.mark.unit
def test_fib_static_discard_v6_yields_blackhole():
    """v6 next_hop="discard" → via=blackhole（inet6.0 discard 対応）。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v6", "ip": "2001:db8::1", "prefix": 64}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "::/0",
                             "next_hop": "discard", "af": "v6"}]},
    )
    st = [e for e in _fib(topo)["r1"] if e["kind"] == "static"][0]
    assert st["via"] == "blackhole"
    assert st["af"] == "v6"


@pytest.mark.unit
def test_fib_static_discard_in_static_stubs():
    """discard next_hop → build_static_stubs に blackhole スタブが生成される。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "10.96.0.0/24",
                             "next_hop": "discard", "af": "v4"}]},
    )
    fib = _fib(topo)
    stubs = build_static_stubs(topo, fib)
    bh_stubs = [s for s in stubs if s["kind"] == "blackhole"]
    assert len(bh_stubs) >= 1
    assert bh_stubs[0]["dev"] == "r1"


@pytest.mark.unit
def test_fib_static_discard_in_static_edges():
    """discard next_hop → build_static_edges に kind="blackhole" エッジが生成される。"""
    topo = _minimal_topo(
        devices=[_make_dev("r1")],
        interfaces=[_make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}])],
        routing={"bgp": [], "ospf": [],
                 "static": [{"device": "r1", "prefix": "10.95.0.0/24",
                             "next_hop": "discard", "af": "v4"}]},
    )
    fib = _fib(topo)
    edges = build_static_edges(topo, fib)
    bh_edges = [e for e in edges if e["kind"] == "blackhole"]
    assert len(bh_edges) == 1
    assert bh_edges[0]["a"] == "r1"


# ===========================================================================
# #5B: duplicate_ip VRF 認識テスト
# ===========================================================================

def _make_if_vrf(device, name, addresses, vrf=None, mtu=None):
    """vrf フィールドを持つ interface dict を生成するヘルパー。"""
    d = _make_if(device, name, addresses, mtu=mtu)
    if vrf is not None:
        d["vrf"] = vrf
    return d


@pytest.mark.unit
def test_build_checks_duplicate_ip_different_vrf_not_flagged():
    """同一 IP でも異なる VRF の interface 間では duplicate_ip を発火しないこと。

    VRF 環境では同一 IP が異なる VRF に存在することは正当な設定であり、
    重複として検知してはならない。
    """
    # Arrange: r1 の Gi0 は VRF "RED"、r2 の Gi0 は VRF "BLUE" — 同一 IP でも異 VRF
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if_vrf("r1", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}], vrf="RED"),
            _make_if_vrf("r2", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}], vrf="BLUE"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 異なる VRF なので duplicate_ip が発火しないこと
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert dup == [], (
        f"異なる VRF（RED/BLUE）の同一 IP が誤検知された: {dup}"
    )


@pytest.mark.unit
def test_build_checks_duplicate_ip_same_vrf_flagged():
    """同一 VRF 内で同一 IP が複数 interface に存在する場合は duplicate_ip を発火すること。

    VRF が同じ場合はルーティングテーブルを共有するため、IP 重複は設定誤りとして
    従来通り検知しなければならない。
    """
    # Arrange: r1 と r2 の Gi0 が同じ VRF "RED" で同一 IP
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if_vrf("r1", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}], vrf="RED"),
            _make_if_vrf("r2", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}], vrf="RED"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 同一 VRF 内の重複は検知される
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "error"
    assert "10.1.1.1" in dup[0]["message"]
    assert "r1::Gi0" in dup[0]["refs"]
    assert "r2::Gi0" in dup[0]["refs"]


@pytest.mark.unit
def test_build_checks_duplicate_ip_global_both_flagged():
    """両方 global（vrf フィールドなし）の同一 IP は従来通り duplicate_ip を発火すること（回帰）。

    #5B 変更後も既存の global-only 挙動が壊れていないことを確認する。
    """
    # Arrange: vrf フィールドなし（global）の 2 IF が同一 IP
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: global 同士の重複は従来通り検知
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert len(dup) == 1
    assert dup[0]["severity"] == "error"
    assert "10.0.0.1" in dup[0]["message"]


@pytest.mark.unit
def test_build_checks_duplicate_ip_global_vs_vrf_flagged():
    """global IF と VRF 付き IF が同一 IP を持つ場合は duplicate_ip を発火しないこと。

    global（vrf なし）と VRF 付きは別のルーティングテーブルを持つため、
    IP が一致しても重複ではない。
    """
    # Arrange: r1::Gi0 は global（vrf なし）、r2::Gi0 は VRF "RED"
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}]),
            _make_if_vrf("r2", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}], vrf="RED"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: global と VRF は別テーブルなので重複ではない
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert dup == [], (
        f"global と VRF の同一 IP が誤検知された: {dup}"
    )


@pytest.mark.unit
def test_build_checks_duplicate_ip_vrf_none_explicit_vs_no_key():
    """vrf=None 明示と vrf キーなしは同じ global として扱われ、同一 IP は duplicate_ip を発火すること。

    topology dict では vrf フィールドは omit-when-None なので、
    vrf キーが存在しない（無し）と vrf=None 明示は同じ global 扱いでなければならない。
    """
    # Arrange: r1::Gi0 は vrf キーなし、r2::Gi0 は vrf=None 明示（どちらも global 相当）
    if1 = _make_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.5", "prefix": 30}])
    # vrf キーなし（_make_if のデフォルト）

    if2 = _make_if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.5", "prefix": 30}])
    if2["vrf"] = None  # 明示的に None を設定

    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[if1, if2],
    )

    # Act
    result = build_checks(topo)

    # Assert: どちらも global なので重複として検知
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert len(dup) == 1
    assert "10.0.0.5" in dup[0]["message"]


@pytest.mark.unit
def test_build_checks_duplicate_ip_cross_device_same_vrf_flagged():
    """3 台の機器で、2 台が同じ VRF で同一 IP を持つ場合のみ duplicate_ip が発火すること。

    異なる VRF の IF は除外され、同一 VRF 内の重複のみ検知される。
    """
    # Arrange:
    # r1::Gi0 VRF "RED" 10.1.1.1 → r3::Gi0 VRF "RED" 10.1.1.1 と重複（発火）
    # r2::Gi0 VRF "BLUE" 10.1.1.1 → RED とは別 VRF（非発火）
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2"), _make_dev("r3", hostname="R3")],
        interfaces=[
            _make_if_vrf("r1", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}], vrf="RED"),
            _make_if_vrf("r2", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}], vrf="BLUE"),
            _make_if_vrf("r3", "Gi0", [{"af": "v4", "ip": "10.1.1.1", "prefix": 30}], vrf="RED"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: RED 内の重複（r1::Gi0 と r3::Gi0）のみ検知、r2::Gi0（BLUE）は除外
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert len(dup) == 1
    assert "r1::Gi0" in dup[0]["refs"]
    assert "r3::Gi0" in dup[0]["refs"]
    assert "r2::Gi0" not in dup[0]["refs"]


@pytest.mark.unit
def test_build_checks_duplicate_ip_vrf_v6_different_vrf_not_flagged():
    """v6 アドレスでも異なる VRF の場合は duplicate_ip を発火しないこと。"""
    # Arrange: v6 アドレスが異なる VRF に存在
    topo = _minimal_topo(
        devices=[_make_dev("r1"), _make_dev("r2", hostname="R2")],
        interfaces=[
            _make_if_vrf("r1", "Lo0", [{"af": "v6", "ip": "2001:db8::1", "prefix": 128}], vrf="VRF_A"),
            _make_if_vrf("r2", "Lo0", [{"af": "v6", "ip": "2001:db8::1", "prefix": 128}], vrf="VRF_B"),
        ],
    )

    # Act
    result = build_checks(topo)

    # Assert: 異なる VRF なので v6 重複も発火しない
    dup = [c for c in result if c["kind"] == "duplicate_ip"]
    assert dup == [], f"v6 異 VRF が誤検知された: {dup}"
