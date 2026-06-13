"""DATA 全体組立（build_data）— 附録 B.3 トポロジーでの統合テスト。"""
import json
from pathlib import Path

import pytest

from lib.topology_io import load_topology
from lib.rendering.data_transform import build_data, build_stats, build_links, build_bgp_topology

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
# D1 修正項目テスト（TDD: 先に追加 → RED → 修正 → GREEN）
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
