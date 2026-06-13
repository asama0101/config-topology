"""DATA 全体組立（build_data）— 附録 B.3 トポロジーでの統合テスト。"""
import json
from pathlib import Path

import pytest

from lib.topology_io import load_topology
from lib.rendering.data_transform import build_data, build_stats, build_links, build_bgp_topology, _build_if, build_checks

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


# ---------------------------------------------------------------------------
# build_stats テスト（D1 統計ダッシュボード）
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_build_stats_returns_required_keys():
    """build_stats が必須キーをすべて返すこと。"""
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)
    required = {
        "devices", "interfaces", "links", "segments",
        "by_vendor", "by_as", "by_area",
        "link_kinds",
        "dualstack_ifs", "bgp_sessions", "ospf_networks", "static_routes",
    }
    assert set(stats.keys()) == required


@pytest.mark.unit
def test_build_stats_counts_from_golden():
    """golden (r1+r2) の各集計値が正しいこと。"""
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)
    # デバイス数・IF 数
    assert stats["devices"] == 2
    assert stats["interfaces"] == 6
    # リンク数（build_links で統合後）
    assert stats["links"] == 1
    assert stats["segments"] == 0
    # bgp_sessions = 重複排除済みセッション数（bgpEdges 本数）。golden: over-link 1本
    assert stats["bgp_sessions"] == 1
    assert stats["ospf_networks"] == 1
    assert stats["static_routes"] == 2
    # dual-stack: golden は全 IF が v4 only
    assert stats["dualstack_ifs"] == 0


@pytest.mark.unit
def test_build_stats_by_vendor_sorted():
    """by_vendor がキー昇順に固定されること。"""
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)
    assert stats["by_vendor"] == {"cisco_ios": 1, "juniper_junos": 1}
    assert list(stats["by_vendor"].keys()) == sorted(stats["by_vendor"].keys())


@pytest.mark.unit
def test_build_stats_by_as_sorted():
    """by_as が文字列キーで昇順になり None 機器は 'none' に集計されること。"""
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)
    # golden: r1=65001, r2=65002
    assert stats["by_as"]["65001"] == 1
    assert stats["by_as"]["65002"] == 1
    assert "none" not in stats["by_as"]
    # キー順は昇順
    assert list(stats["by_as"].keys()) == sorted(stats["by_as"].keys())


@pytest.mark.unit
def test_build_stats_by_as_none_bucket():
    """AS が None の機器は 'none' バケットに集計されること。"""
    topo = {
        "meta": {"generated_from": []},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [],
        "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    stats = build_stats(topo)
    assert stats["by_as"]["none"] == 1


@pytest.mark.unit
def test_build_stats_by_area_sorted():
    """by_area が OSPF ネットワークの area 別カウントでキー昇順になること。"""
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)
    # golden: ospf 1件 area '0'
    assert stats["by_area"] == {"0": 1}
    assert list(stats["by_area"].keys()) == sorted(stats["by_area"].keys())


@pytest.mark.unit
def test_build_stats_link_kinds():
    """link_kinds に 'link'/'segment'/'stub' キーが存在すること（int 値）。"""
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)
    assert isinstance(stats["link_kinds"]["link"], int)
    assert isinstance(stats["link_kinds"]["segment"], int)
    assert isinstance(stats["link_kinds"]["stub"], int)
    # golden: link=1, segment=0
    assert stats["link_kinds"]["link"] == 1
    assert stats["link_kinds"]["segment"] == 0


@pytest.mark.unit
def test_build_stats_dualstack_detection():
    """v4 と v6(非 link-local) 両方を持つ IF が dualstack_ifs に計上されること。"""
    topo = {
        "meta": {"generated_from": []},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [
            {"id": "r1::Gi0", "device": "r1", "name": "Gi0",
             "ip": "10.0.0.1/30", "vlan": None, "description": None,
             "shutdown": False, "admin_status": "up", "oper_status": None,
             "mtu": None, "speed": None, "duplex": None,
             "l2_l3": None, "switchport": None, "encapsulation": None,
             "source": "parsed",
             "addresses": [
                 {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                 {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
             ]},
            # link-local のみなら dual-stack ではない
            {"id": "r1::Gi1", "device": "r1", "name": "Gi1",
             "ip": None, "vlan": None, "description": None,
             "shutdown": False, "admin_status": "up", "oper_status": None,
             "mtu": None, "speed": None, "duplex": None,
             "l2_l3": None, "switchport": None, "encapsulation": None,
             "source": "parsed",
             "addresses": [
                 {"af": "v4", "ip": "10.0.0.5", "prefix": 30},
                 {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
             ]},
        ],
        "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    stats = build_stats(topo)
    assert stats["dualstack_ifs"] == 1  # Gi0 のみ dual-stack（Gi1 の v6 は link-local）


@pytest.mark.unit
def test_build_stats_deterministic():
    """build_stats を2回呼んで同一結果が返ること（決定性）。"""
    topo = load_topology(str(GOLDEN))
    a = json.dumps(build_stats(topo), sort_keys=True)
    b = json.dumps(build_stats(topo), sort_keys=True)
    assert a == b


@pytest.mark.integration
def test_build_data_has_stats_key():
    """build_data の返り値に 'stats' キーが含まれ、dict であること。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    assert "stats" in data
    assert isinstance(data["stats"], dict)


@pytest.mark.integration
def test_build_data_stats_consistent_with_build_stats():
    """build_data の stats が build_stats と同一内容であること。"""
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    expected = build_stats(topo)
    assert data["stats"] == expected


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


# ===========================================================================
# D1 修正項目テスト
# ===========================================================================

# --- 修正 1: by_as の数値ソート ---

@pytest.mark.unit
def test_build_stats_by_as_numeric_sort():
    """by_as キーが文字列ではなく数値昇順でソートされること（1桁・多桁混在）。"""
    # Arrange: AS 9, 65001, 100 の3台。文字列ソートなら ["100","65001","9"] だが数値順なら ["9","100","65001"]
    topo = {
        "meta": {"generated_from": []},
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 9,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65001,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r3", "hostname": "R3", "vendor": "cisco_ios", "as": 100,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
        ],
        "interfaces": [],
        "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }

    # Act
    stats = build_stats(topo)

    # Assert: 数値昇順（9 < 100 < 65001）
    assert list(stats["by_as"].keys()) == ["9", "100", "65001"]


@pytest.mark.unit
def test_build_stats_by_as_numeric_sort_with_none():
    """by_as: 数値キーが数値昇順に並び、'none' が末尾になること。"""
    # Arrange
    topo = {
        "meta": {"generated_from": []},
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 9,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 100,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r3", "hostname": "R3", "vendor": "cisco_ios", "as": None,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
        ],
        "interfaces": [],
        "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }

    # Act
    stats = build_stats(topo)

    # Assert: 数値昇順で 'none' は末尾
    assert list(stats["by_as"].keys()) == ["9", "100", "none"]


# --- 修正 2: by_area の数値ソート ---

@pytest.mark.unit
def test_build_stats_by_area_numeric_sort():
    """by_area キーが数値昇順でソートされること（文字列ソートで誤る "0","10","2" ケース）。"""
    # Arrange: area 0, 10, 2 を持つ OSPF エントリ
    topo = {
        "meta": {"generated_from": []},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [],
        "links": [], "segments": [],
        "routing": {
            "bgp": [], "static": [],
            "ospf": [
                {"device": "r1", "network": "10.0.0.0/24", "area": "10", "process": 1},
                {"device": "r1", "network": "10.0.1.0/24", "area": "2", "process": 1},
                {"device": "r1", "network": "10.0.2.0/24", "area": "0", "process": 1},
            ],
        },
    }

    # Act
    stats = build_stats(topo)

    # Assert: 数値昇順（0 < 2 < 10）
    assert list(stats["by_area"].keys()) == ["0", "2", "10"]


@pytest.mark.unit
def test_build_stats_by_area_none_at_end():
    """by_area: 数値キーが数値昇順に並び、'none' が末尾になること。"""
    topo = {
        "meta": {"generated_from": []},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [],
        "links": [], "segments": [],
        "routing": {
            "bgp": [], "static": [],
            "ospf": [
                {"device": "r1", "network": "10.0.0.0/24", "area": "2", "process": 1},
                {"device": "r1", "network": "10.0.1.0/24", "area": None, "process": 1},
                {"device": "r1", "network": "10.0.2.0/24", "area": "0", "process": 1},
            ],
        },
    }

    # Act
    stats = build_stats(topo)

    # Assert: 数値昇順で 'none' は末尾
    assert list(stats["by_area"].keys()) == ["0", "2", "none"]


# --- 修正 3: build_links 二重呼び出し解消 ---

@pytest.mark.unit
def test_build_stats_accepts_precomputed_links():
    """build_stats(topo, links=...) と build_stats(topo) が同一結果を返すこと。"""
    topo = load_topology(str(GOLDEN))

    # Act
    stats_no_arg = build_stats(topo)
    precomputed = build_links(topo)
    stats_with_arg = build_stats(topo, links=precomputed)

    # Assert: 結果が同一
    assert stats_no_arg == stats_with_arg


@pytest.mark.unit
def test_build_stats_standalone_still_works():
    """build_stats(topo) の引数なし呼び出しが壊れないこと（後方互換）。"""
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)
    assert stats["links"] == 1  # golden: 1リンク


# --- 修正 4: bgp_sessions = 重複排除済みセッション数 ---

@pytest.mark.unit
def test_build_stats_bgp_sessions_is_deduped_golden():
    """golden (r1↔r2 の eBGP 1セッション): bgp_sessions が 1 であること（旧値 2 ではない）。

    raw routing.bgp は r1→r2 と r2→r1 の 2 エントリだが、
    bgpEdges（重複排除済み）は over-link 1本なので bgp_sessions=1。
    """
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)
    # bgpEdges で重複排除後のセッション数
    bgp_topo = build_bgp_topology(topo)
    expected = len(bgp_topo["bgpEdges"])  # = 1
    assert stats["bgp_sessions"] == expected
    assert stats["bgp_sessions"] == 1


@pytest.mark.unit
def test_build_stats_bgp_sessions_accepts_precomputed_bgp_edges():
    """build_stats(topo, bgp_edges=...) 引数で渡した場合も同一結果になること。"""
    topo = load_topology(str(GOLDEN))
    bgp_topo = build_bgp_topology(topo)

    stats_no_arg = build_stats(topo)
    stats_with_arg = build_stats(topo, bgp_edges=bgp_topo["bgpEdges"])

    assert stats_no_arg == stats_with_arg


@pytest.mark.unit
def test_build_stats_bgp_sessions_ibgp_dedup():
    """iBGP 双方向エントリ（r1→r2, r2→r1）が 1 セッションとしてカウントされること。"""
    # Arrange: iBGP over loopback。r1 と r2 が互いに neighbor を張る
    topo = {
        "meta": {"generated_from": []},
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65001,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
        ],
        "interfaces": [
            {"id": "r1::Lo0", "device": "r1", "name": "Lo0", "ip": "1.1.1.1/32",
             "vlan": None, "description": None, "shutdown": False, "admin_status": "up",
             "oper_status": None, "mtu": None, "speed": None, "duplex": None,
             "l2_l3": None, "switchport": None, "encapsulation": None, "source": "parsed",
             "addresses": [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]},
            {"id": "r2::Lo0", "device": "r2", "name": "Lo0", "ip": "2.2.2.2/32",
             "vlan": None, "description": None, "shutdown": False, "admin_status": "up",
             "oper_status": None, "mtu": None, "speed": None, "duplex": None,
             "l2_l3": None, "switchport": None, "encapsulation": None, "source": "parsed",
             "addresses": [{"af": "v4", "ip": "2.2.2.2", "prefix": 32}]},
        ],
        "links": [], "segments": [],
        "routing": {
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "1.1.1.1",
                 "neighbor_ip": "2.2.2.2", "peer_as": 65001, "type": "ibgp", "af": "v4"},
                {"device": "r2", "local_as": 65001, "local_ip": "2.2.2.2",
                 "neighbor_ip": "1.1.1.1", "peer_as": 65001, "type": "ibgp", "af": "v4"},
            ],
            "ospf": [], "static": [],
        },
    }

    # Act
    stats = build_stats(topo)

    # Assert: 双方向エントリが 1 セッションに重複排除
    assert stats["bgp_sessions"] == 1


# --- 修正 5: link_kinds.stub 実値検証 + by_as/by_area 既存テスト更新 ---

@pytest.mark.unit
def test_build_stats_link_kinds_stub_golden_value():
    """golden での stub 実値が 4 であること。

    golden インターフェース 6本:
      リンク参加: r1::GigabitEthernet0/0, r2::ge-0/0/0 → 2本
      スタブ: r1::GigabitEthernet0/1, r1::Loopback0, r2::ge-0/0/1, r2::lo0 → 4本
    """
    topo = load_topology(str(GOLDEN))
    stats = build_stats(topo)

    # link と segment は既存テストで確認済み。ここで stub の実値を確定
    assert stats["link_kinds"]["stub"] == 4


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
