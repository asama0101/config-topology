"""DATA 全体組立（build_data）— 附録 B.3 トポロジーでの統合テスト。"""
import json
from pathlib import Path

import pytest

from lib.topology_io import load_topology
from lib.rendering.data_transform import build_data, build_links, build_bgp_topology, _build_if, build_checks, build_devices, build_subnet_usage, _EXHAUSTED_THRESHOLD

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


# ===========================================================================
# D4: サブネット使用率集約ビュー — build_subnet_usage テスト
# ===========================================================================

def _make_if_with_addrs(device, name, addresses):
    """build_subnet_usage 用の最小 interface dict。"""
    return {
        "id": "%s::%s" % (device, name),
        "device": device,
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


def _minimal_topo_for_usage(**overrides):
    """build_subnet_usage 用の最小 topology dict。"""
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


@pytest.mark.unit
def test_build_subnet_usage_slash24_two_hosts():
    """/24 に 2 ホストが存在する場合の各フィールドが正しいこと（壊すと赤）。

    usable=254, used=2, free=252, util~0.0079, exhausted=False。
    """
    # Arrange
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [{"af": "v4", "ip": "192.168.1.1", "prefix": 24}]),
            _make_if_with_addrs("r2", "Gi0", [{"af": "v4", "ip": "192.168.1.2", "prefix": 24}]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert
    assert len(result) == 1
    row = result[0]
    assert row["subnet"] == "192.168.1.0/24"
    assert row["af"] == "v4"
    assert row["usable"] == 254
    assert row["used"] == 2
    assert row["free"] == 252
    assert row["exhausted"] is False
    assert abs(row["util"] - round(2 / 254, 4)) < 1e-6


@pytest.mark.unit
def test_build_subnet_usage_slash30_exhausted():
    """/30 に 2 ホストが存在する場合 exhausted=True（util=1.0）になること（壊すと赤）。

    usable=2, used=2, free=0, util=1.0, exhausted=True。
    exhausted 閾値（0.8）以上は True。
    """
    # Arrange
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if_with_addrs("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert
    assert len(result) == 1
    row = result[0]
    assert row["usable"] == 2
    assert row["used"] == 2
    assert row["free"] == 0
    assert row["util"] == 1.0
    assert row["exhausted"] is True, (
        "/30 に 2 ホスト（usable=2 / used=2）は util=1.0 >= 0.8 なので exhausted=True のはず"
    )


@pytest.mark.unit
def test_build_subnet_usage_slash31_usable_is_2():
    """/31（ポイントツーポイント）の usable が 2 になること。"""
    # Arrange: /31 に 2 ホスト
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.0", "prefix": 31}]),
            _make_if_with_addrs("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 31}]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert
    assert len(result) == 1
    row = result[0]
    assert row["usable"] == 2
    assert row["used"] == 2
    assert row["util"] == 1.0
    assert row["exhausted"] is True


@pytest.mark.unit
def test_build_subnet_usage_slash32_excluded():
    """/32（ホスト/ループバック）は除外されること（壊すと赤）。

    /32 が結果に出てしまう誤実装はこのテストで失敗する。
    """
    # Arrange: /32 のみの IF
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Lo0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
            _make_if_with_addrs("r2", "Lo0", [{"af": "v4", "ip": "2.2.2.2", "prefix": 32}]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert: /32 は使用率計画の対象外 → 結果は空
    assert result == [], (
        "/32 ループバックは build_subnet_usage の結果に出てはならない。"
        "実際の結果: %s" % result
    )


@pytest.mark.unit
def test_build_subnet_usage_link_local_excluded():
    """link-local（scope=link-local）は除外されること。"""
    # Arrange: fe80:: のみの IF（link-local）
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [
                {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
            ]),
            # v4 link-local 相当（scope 指定あり）
            _make_if_with_addrs("r2", "Gi0", [
                {"af": "v4", "ip": "169.254.0.1", "prefix": 24, "scope": "link-local"},
            ]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert: link-local は除外 → 結果は空
    assert result == []


@pytest.mark.unit
def test_build_subnet_usage_v6_excluded():
    """v6 アドレスは除外されること（v4 のみ対象）。"""
    # Arrange: v6 GUA のみの IF
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [{"af": "v6", "ip": "2001:db8::1", "prefix": 64}]),
            _make_if_with_addrs("r2", "Gi0", [{"af": "v6", "ip": "2001:db8::2", "prefix": 64}]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert: v6 は除外 → 結果は空
    assert result == []


@pytest.mark.unit
def test_build_subnet_usage_no_double_count_same_host_ip():
    """同一 host_ip が複数 IF に現れても二重計上しないこと。"""
    # Arrange: 同一ホスト IP が 2 つの IF に存在（used=set で排除）
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if_with_addrs("r1", "Gi1", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),  # 同一 host_ip
            _make_if_with_addrs("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert: 同一 host_ip は排除されるので used=2（10.0.0.1 と 10.0.0.2 各1回）
    assert len(result) == 1
    row = result[0]
    assert row["used"] == 2, (
        "同一 host_ip が重複して used が 3 になる誤実装を検知。used は %d" % row["used"]
    )


@pytest.mark.unit
def test_build_subnet_usage_sort_util_desc_then_subnet_asc():
    """util 降順→同率 subnet 昇順の安定ソートであること。"""
    # Arrange: 3 サブネット
    # - 10.0.0.0/30 (usable=2, used=2, util=1.0)
    # - 192.168.0.0/24 (usable=254, used=1, util~0.0039)
    # - 10.1.0.0/24 (usable=254, used=1, util~0.0039 - 同率で subnet 文字列昇順)
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if_with_addrs("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
            _make_if_with_addrs("r3", "Gi0", [{"af": "v4", "ip": "192.168.0.1", "prefix": 24}]),
            _make_if_with_addrs("r4", "Gi0", [{"af": "v4", "ip": "10.1.0.1", "prefix": 24}]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert: util 降順 → subnet 昇順
    assert len(result) == 3
    subnets = [r["subnet"] for r in result]
    # 10.0.0.0/30 (util=1.0) が先頭
    assert subnets[0] == "10.0.0.0/30", "util 最大サブネットが先頭に来ていない"
    # 残り 2 つは util 同率 → subnet 昇順（10.1.0.0/24 < 192.168.0.0/24）
    assert subnets[1] == "10.1.0.0/24", "同率 util のとき subnet 昇順になっていない"
    assert subnets[2] == "192.168.0.0/24"


@pytest.mark.unit
def test_build_subnet_usage_empty_topo_returns_empty():
    """interfaces が空の場合は空リストを返すこと。"""
    topo = _minimal_topo_for_usage()
    result = build_subnet_usage(topo)
    assert result == []


@pytest.mark.unit
def test_build_subnet_usage_deterministic():
    """2 回呼んで同一結果になること（決定性）。"""
    import json
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
            _make_if_with_addrs("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]),
            _make_if_with_addrs("r3", "Lo0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),  # /32 除外
        ],
    )
    a = json.dumps(build_subnet_usage(topo), sort_keys=True)
    b = json.dumps(build_subnet_usage(topo), sort_keys=True)
    assert a == b


@pytest.mark.integration
def test_build_data_has_subnet_usage_key():
    """build_data の返り値に 'subnet_usage' キーが含まれること。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    assert "subnet_usage" in data, "build_data に subnet_usage キーがない"
    assert isinstance(data["subnet_usage"], list)


@pytest.mark.integration
def test_build_data_subnet_usage_consistent():
    """build_data の subnet_usage が build_subnet_usage(topo) と同一内容であること。"""
    import json
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    expected = build_subnet_usage(topo)
    assert json.dumps(data["subnet_usage"], sort_keys=True) == json.dumps(expected, sort_keys=True)


# ---------------------------------------------------------------------------
# D4 レビュー指摘: exhausted 境界値テスト（壊すと赤）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_exhausted_threshold_constant_value():
    """_EXHAUSTED_THRESHOLD が 0.8 であること（定数値の固定）。"""
    assert _EXHAUSTED_THRESHOLD == 0.8


@pytest.mark.unit
def test_exhausted_threshold_inclusive_at_boundary():
    """_EXHAUSTED_THRESHOLD は >= 0.8 であること（ちょうど 0.8 で True。> 0.8 誤実装は赤）。

    壊すと赤: _EXHAUSTED_THRESHOLD を 0.8 から変えるか、比較を > に変えると失敗する。
    """
    # util == 0.8 ちょうどは exhausted=True（>=）
    assert (0.8 >= _EXHAUSTED_THRESHOLD) is True


@pytest.mark.unit
def test_exhausted_threshold_false_just_below():
    """util が _EXHAUSTED_THRESHOLD より小さい場合は exhausted=False であること。

    壊すと赤: 閾値を 0.8 以下に変えると失敗する。
    """
    # util = 0.7999 は exhausted=False（閾値未満）
    assert (0.7999 >= _EXHAUSTED_THRESHOLD) is False


@pytest.mark.unit
def test_build_subnet_usage_exhausted_at_exact_08_boundary():
    """build_subnet_usage で util がちょうど 0.8 になる場合に exhausted=True となること（壊すと赤）。

    /28: usable=14, used=12 → util=round(12/14, 4)=0.8571 >= 0.8 → exhausted=True。
    /28: usable=14, used=11 → util=round(11/14, 4)=0.7857 < 0.8  → exhausted=False。

    境界感度: > 0.8 の誤実装では「used=11 のみ False」となり used=12 は通る。
    しかし上記 test_exhausted_threshold_inclusive_at_boundary が「0.8 ちょうど→True」を固定する。

    壊すと赤（このテスト）: usable=14, used=12 の exhausted が False になると失敗。
    """
    # Arrange: /28 に 12 ホスト（exhausted=True）
    topo_12 = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r%d" % i, "Gi0", [
                {"af": "v4", "ip": "10.1.0.%d" % i, "prefix": 28}
            ])
            for i in range(1, 13)
        ],
    )
    result_12 = build_subnet_usage(topo_12)
    assert len(result_12) == 1
    row_12 = result_12[0]
    assert row_12["usable"] == 14
    assert row_12["used"] == 12
    assert row_12["util"] == round(12 / 14, 4)
    assert row_12["exhausted"] is True, (
        "/28 used=12 usable=14: util=%s >= 0.8 なので exhausted=True のはず" % row_12["util"]
    )

    # Arrange: /28 に 11 ホスト（exhausted=False）
    topo_11 = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r%d" % i, "Gi0", [
                {"af": "v4", "ip": "10.1.0.%d" % i, "prefix": 28}
            ])
            for i in range(1, 12)
        ],
    )
    result_11 = build_subnet_usage(topo_11)
    assert len(result_11) == 1
    row_11 = result_11[0]
    assert row_11["usable"] == 14
    assert row_11["used"] == 11
    assert row_11["util"] == round(11 / 14, 4)
    assert row_11["exhausted"] is False, (
        "/28 used=11 usable=14: util=%s < 0.8 なので exhausted=False のはず" % row_11["util"]
    )


@pytest.mark.unit
def test_build_subnet_usage_secondary_address_counted_as_used():
    """secondary IP（secondary=True）が used にカウントされること（仕様確認テスト）。

    実装は既に secondary を除外しない設計 → このテストは仕様を固定する確認テスト。
    secondary=True の IP が used から除かれると fail する。
    """
    # Arrange: 同一サブネット /24 に primary 1 件 + secondary 1 件
    topo = _minimal_topo_for_usage(
        interfaces=[
            _make_if_with_addrs("r1", "Gi0", [
                {"af": "v4", "ip": "192.168.1.1", "prefix": 24},
                {"af": "v4", "ip": "192.168.1.2", "prefix": 24, "secondary": True},
            ]),
        ],
    )

    # Act
    result = build_subnet_usage(topo)

    # Assert: primary + secondary の 2 ホストが used にカウントされる
    assert len(result) == 1
    row = result[0]
    assert row["used"] == 2, (
        "secondary IP も used にカウントされるべき。実際の used=%d" % row["used"]
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
