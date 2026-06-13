"""lib/diff.py および scripts/diff_topology.py のテスト（TDD: RED先行）。

テスト構成:
  - ユニット: diff_topology の各セクション (devices/interfaces/links/segments/routing)
  - ユニット: format_diff_report の出力構造・件数サマリ・差分ゼロ時表示
  - 決定性: 同一入力→空 diff / format_diff_report 同一文字列
  - 統合(CLI): subprocess で diff_topology.py を呼び出し
"""
import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REBUILD_ROOT = Path(__file__).resolve().parents[2]
CLI = REBUILD_ROOT / "scripts" / "diff_topology.py"
GOLDEN = REBUILD_ROOT / "dev" / "examples" / "topology"

# ---------------------------------------------------------------------------
# テスト用最小 topology dict ファクトリ
# ---------------------------------------------------------------------------

def _base_topo():
    """最小限の topology dict を返す（テスト間で共有しない=毎回 deepcopy して使う）。"""
    return {
        "meta": {"schema_version": "1.0", "title": "Test", "generated_from": []},
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "juniper_junos", "as": 65002,
             "ospf_router_id": None, "bgp_router_id": None, "sections": []},
        ],
        "interfaces": [
            {"id": "r1::Gi0/0", "device": "r1", "name": "Gi0/0",
             "description": "to-R2", "shutdown": False, "mtu": 1500, "speed": None,
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
             "ospf": None},
            {"id": "r2::ge-0/0/0", "device": "r2", "name": "ge-0/0/0",
             "description": "to-R1", "shutdown": False, "mtu": 1500, "speed": None,
             "addresses": [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}],
             "ospf": None},
        ],
        "links": [
            {"a_device": "r1", "a_if": "Gi0/0", "b_device": "r2", "b_if": "ge-0/0/0",
             "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
        ],
        "segments": [
            {"id": "seg-192.168.1.0/24", "subnet": "192.168.1.0/24",
             "members": ["r1::Gi0/0"]},
        ],
        "routing": {
            "bgp": [
                {"device": "r1", "neighbor_ip": "10.0.0.2", "af": "v4",
                 "peer_as": 65002, "type": "ebgp", "local_ip": "10.0.0.1",
                 "update_source": None},
            ],
            "ospf": [
                {"device": "r1", "network": "192.168.1.0/24", "af": "v4",
                 "process": 1, "area": "0", "area_type": None},
            ],
            "static": [
                {"device": "r1", "prefix": "0.0.0.0/0", "af": "v4",
                 "next_hop": "10.0.0.2"},
            ],
        },
    }


def _import_diff():
    """lib.diff をインポート（sys.path 依存を避けるため遅延 import）。"""
    from lib import diff as diff_mod
    return diff_mod


# ===========================================================================
# 1. 同一入力 → 空 diff（決定性基礎テスト）
# ===========================================================================

@pytest.mark.unit
def test_identical_topology_produces_empty_diff():
    diff_mod = _import_diff()
    topo = _base_topo()
    diff = diff_mod.diff_topology(topo, copy.deepcopy(topo))
    for section in ("devices", "interfaces", "links", "segments",
                    "routing_bgp", "routing_ospf", "routing_static"):
        sec = diff[section]
        assert sec["added"] == [], f"{section}.added should be empty"
        assert sec["removed"] == [], f"{section}.removed should be empty"
        assert sec["changed"] == [], f"{section}.changed should be empty"


# ===========================================================================
# 2. devices セクション
# ===========================================================================

@pytest.mark.unit
def test_devices_added():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"].append({"id": "r3", "hostname": "R3", "vendor": "cisco_ios",
                            "as": 65003, "ospf_router_id": None, "bgp_router_id": None,
                            "sections": []})
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["devices"]["added"]) == 1
    assert diff["devices"]["added"][0]["id"] == "r3"
    assert diff["devices"]["removed"] == []
    assert diff["devices"]["changed"] == []


@pytest.mark.unit
def test_devices_removed():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"] = [d for d in new["devices"] if d["id"] != "r2"]
    # links/interfaces/segments/routing も整合させる（diff エンジン自体は cross-ref を見ない）
    new["interfaces"] = [i for i in new["interfaces"] if i["device"] != "r2"]
    new["links"] = []
    diff = diff_mod.diff_topology(old, new)
    removed_ids = [d["id"] for d in diff["devices"]["removed"]]
    assert "r2" in removed_ids
    assert diff["devices"]["added"] == []


@pytest.mark.unit
def test_devices_changed_as():
    """AS 番号変更は changed に現れる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"][0]["as"] = 99999  # r1 の AS 変更
    diff = diff_mod.diff_topology(old, new)
    assert diff["devices"]["added"] == []
    assert diff["devices"]["removed"] == []
    assert len(diff["devices"]["changed"]) == 1
    ch = diff["devices"]["changed"][0]
    assert ch["id"] == "r1"
    assert "as" in ch["fields"]
    assert ch["fields"]["as"] == [65001, 99999]


@pytest.mark.unit
def test_devices_changed_hostname():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"][1]["hostname"] = "R2-NEW"
    diff = diff_mod.diff_topology(old, new)
    changed = diff["devices"]["changed"]
    assert len(changed) == 1
    assert changed[0]["id"] == "r2"
    assert "hostname" in changed[0]["fields"]
    assert changed[0]["fields"]["hostname"] == ["R2", "R2-NEW"]


@pytest.mark.unit
def test_devices_changed_vendor():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"][0]["vendor"] = "juniper_junos"
    diff = diff_mod.diff_topology(old, new)
    ch = diff["devices"]["changed"][0]
    assert ch["fields"]["vendor"] == ["cisco_ios", "juniper_junos"]


@pytest.mark.unit
def test_devices_changed_sorted_by_key():
    """changed リストは id 昇順でソートされること（決定性）。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    # r1 と r2 両方変更してキー昇順を検証
    new["devices"][0]["as"] = 11111
    new["devices"][1]["as"] = 22222
    diff = diff_mod.diff_topology(old, new)
    ids = [c["id"] for c in diff["devices"]["changed"]]
    assert ids == sorted(ids)


# ===========================================================================
# 3. interfaces セクション
# ===========================================================================

@pytest.mark.unit
def test_interfaces_added():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["interfaces"].append({
        "id": "r1::Lo0", "device": "r1", "name": "Lo0",
        "description": None, "shutdown": False, "mtu": None, "speed": None,
        "addresses": [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}],
        "ospf": None,
    })
    diff = diff_mod.diff_topology(old, new)
    added_ids = [i["id"] for i in diff["interfaces"]["added"]]
    assert "r1::Lo0" in added_ids


@pytest.mark.unit
def test_interfaces_removed():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["interfaces"] = [i for i in new["interfaces"] if i["id"] != "r2::ge-0/0/0"]
    new["links"] = []
    diff = diff_mod.diff_topology(old, new)
    removed_ids = [i["id"] for i in diff["interfaces"]["removed"]]
    assert "r2::ge-0/0/0" in removed_ids


@pytest.mark.unit
def test_interfaces_changed_mtu():
    """MTU 変更は changed に現れる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["interfaces"][0]["mtu"] = 9000
    diff = diff_mod.diff_topology(old, new)
    changed = diff["interfaces"]["changed"]
    assert len(changed) == 1
    assert changed[0]["id"] == "r1::Gi0/0"
    assert "mtu" in changed[0]["fields"]
    assert changed[0]["fields"]["mtu"] == [1500, 9000]


@pytest.mark.unit
def test_interfaces_changed_shutdown():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["interfaces"][0]["shutdown"] = True
    diff = diff_mod.diff_topology(old, new)
    ch = diff["interfaces"]["changed"][0]
    assert "shutdown" in ch["fields"]
    assert ch["fields"]["shutdown"] == [False, True]


@pytest.mark.unit
def test_interfaces_changed_description():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["interfaces"][0]["description"] = "updated-desc"
    diff = diff_mod.diff_topology(old, new)
    ch = diff["interfaces"]["changed"][0]
    assert "description" in ch["fields"]
    assert ch["fields"]["description"] == ["to-R2", "updated-desc"]


@pytest.mark.unit
def test_interfaces_changed_addresses():
    """addresses リストの変更（IP 変更）。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["interfaces"][0]["addresses"] = [{"af": "v4", "ip": "10.0.0.9", "prefix": 30}]
    diff = diff_mod.diff_topology(old, new)
    ch = diff["interfaces"]["changed"][0]
    assert "addresses" in ch["fields"]


@pytest.mark.unit
def test_interfaces_changed_ospf():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["interfaces"][0]["ospf"] = {"cost": 100, "network_type": "point-to-point", "passive": False}
    diff = diff_mod.diff_topology(old, new)
    ch = diff["interfaces"]["changed"][0]
    assert "ospf" in ch["fields"]
    assert ch["fields"]["ospf"][0] is None


@pytest.mark.unit
def test_interfaces_changed_sorted_by_key():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["interfaces"][0]["mtu"] = 9000
    new["interfaces"][1]["mtu"] = 9000
    diff = diff_mod.diff_topology(old, new)
    ids = [c["id"] for c in diff["interfaces"]["changed"]]
    assert ids == sorted(ids)


# ===========================================================================
# 4. links セクション
# ===========================================================================

@pytest.mark.unit
def test_links_added():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["links"].append({
        "a_device": "r1", "a_if": "Gi0/1",
        "b_device": "r2", "b_if": "ge-0/0/1",
        "subnet": "10.0.1.0/30", "kind": "inferred-subnet",
    })
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["links"]["added"]) == 1
    assert diff["links"]["removed"] == []
    # キー確認
    added = diff["links"]["added"][0]
    assert added["subnet"] == "10.0.1.0/30"


@pytest.mark.unit
def test_links_removed():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["links"] = []
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["links"]["removed"]) == 1
    assert diff["links"]["added"] == []
    assert diff["links"]["changed"] == []


@pytest.mark.unit
def test_links_no_changed_field():
    """links セクションは changed を持つが空のリスト（仕様: changed は扱わない）。"""
    diff_mod = _import_diff()
    topo = _base_topo()
    diff = diff_mod.diff_topology(topo, copy.deepcopy(topo))
    assert diff["links"]["changed"] == []


@pytest.mark.unit
def test_links_sorted_by_natural_key():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["links"] = []  # 既存削除
    diff = diff_mod.diff_topology(old, new)
    # removed は subnet,a_device,a_if,b_device,b_if の昇順
    removed = diff["links"]["removed"]
    assert removed == sorted(removed, key=lambda x: (
        x["subnet"], x["a_device"], x["a_if"], x["b_device"], x["b_if"]
    ))


# ===========================================================================
# 5. segments セクション
# ===========================================================================

@pytest.mark.unit
def test_segments_added():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["segments"].append({"id": "seg-192.168.2.0/24", "subnet": "192.168.2.0/24",
                             "members": ["r2::ge-0/0/0"]})
    diff = diff_mod.diff_topology(old, new)
    added_ids = [s["id"] for s in diff["segments"]["added"]]
    assert "seg-192.168.2.0/24" in added_ids


@pytest.mark.unit
def test_segments_removed():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["segments"] = []
    diff = diff_mod.diff_topology(old, new)
    removed_ids = [s["id"] for s in diff["segments"]["removed"]]
    assert "seg-192.168.1.0/24" in removed_ids


@pytest.mark.unit
def test_segments_changed_members():
    """members 集合差は changed に現れる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["segments"][0]["members"] = ["r1::Gi0/0", "r2::ge-0/0/0"]
    diff = diff_mod.diff_topology(old, new)
    changed = diff["segments"]["changed"]
    assert len(changed) == 1
    ch = changed[0]
    assert ch["id"] == "seg-192.168.1.0/24"
    assert "members" in ch["fields"]
    old_members = set(ch["fields"]["members"][0])
    new_members = set(ch["fields"]["members"][1])
    assert "r1::Gi0/0" in old_members
    assert "r2::ge-0/0/0" in new_members


# ===========================================================================
# 6. routing.bgp セクション
# ===========================================================================

@pytest.mark.unit
def test_routing_bgp_added():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["bgp"].append({
        "device": "r2", "neighbor_ip": "10.0.0.1", "af": "v4",
        "peer_as": 65001, "type": "ebgp", "local_ip": "10.0.0.2",
        "update_source": None,
    })
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["routing_bgp"]["added"]) == 1
    assert diff["routing_bgp"]["removed"] == []


@pytest.mark.unit
def test_routing_bgp_removed():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["bgp"] = []
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["routing_bgp"]["removed"]) == 1
    assert diff["routing_bgp"]["added"] == []


@pytest.mark.unit
def test_routing_bgp_changed_peer_as():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["bgp"][0]["peer_as"] = 99999
    diff = diff_mod.diff_topology(old, new)
    changed = diff["routing_bgp"]["changed"]
    assert len(changed) == 1
    ch = changed[0]
    assert "peer_as" in ch["fields"]
    assert ch["fields"]["peer_as"] == [65002, 99999]


@pytest.mark.unit
def test_routing_bgp_changed_type():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["bgp"][0]["type"] = "ibgp"
    diff = diff_mod.diff_topology(old, new)
    ch = diff["routing_bgp"]["changed"][0]
    assert "type" in ch["fields"]
    assert ch["fields"]["type"] == ["ebgp", "ibgp"]


@pytest.mark.unit
def test_routing_bgp_changed_local_ip():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["bgp"][0]["local_ip"] = "192.168.100.1"
    diff = diff_mod.diff_topology(old, new)
    ch = diff["routing_bgp"]["changed"][0]
    assert "local_ip" in ch["fields"]


@pytest.mark.unit
def test_routing_bgp_changed_update_source():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["bgp"][0]["update_source"] = "Loopback0"
    diff = diff_mod.diff_topology(old, new)
    ch = diff["routing_bgp"]["changed"][0]
    assert "update_source" in ch["fields"]
    assert ch["fields"]["update_source"] == [None, "Loopback0"]


# ===========================================================================
# 7. routing.ospf セクション
# ===========================================================================

@pytest.mark.unit
def test_routing_ospf_added():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["ospf"].append({
        "device": "r2", "network": "10.0.0.0/30", "af": "v4",
        "process": 1, "area": "0", "area_type": None,
    })
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["routing_ospf"]["added"]) == 1


@pytest.mark.unit
def test_routing_ospf_removed():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["ospf"] = []
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["routing_ospf"]["removed"]) == 1


@pytest.mark.unit
def test_routing_ospf_changed_area_type():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["ospf"][0]["area_type"] = "stub"
    diff = diff_mod.diff_topology(old, new)
    changed = diff["routing_ospf"]["changed"]
    assert len(changed) == 1
    ch = changed[0]
    assert "area_type" in ch["fields"]
    assert ch["fields"]["area_type"] == [None, "stub"]


@pytest.mark.unit
def test_routing_ospf_changed_process():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["ospf"][0]["process"] = 2
    diff = diff_mod.diff_topology(old, new)
    ch = diff["routing_ospf"]["changed"][0]
    assert "process" in ch["fields"]
    assert ch["fields"]["process"] == [1, 2]


@pytest.mark.unit
def test_routing_ospf_changed_area():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["ospf"][0]["area"] = "1"
    diff = diff_mod.diff_topology(old, new)
    ch = diff["routing_ospf"]["changed"][0]
    assert "area" in ch["fields"]


# ===========================================================================
# 8. routing.static セクション
# ===========================================================================

@pytest.mark.unit
def test_routing_static_added():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["static"].append({
        "device": "r2", "prefix": "10.10.10.0/24", "af": "v4",
        "next_hop": "10.0.0.1",
    })
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["routing_static"]["added"]) == 1


@pytest.mark.unit
def test_routing_static_removed():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["static"] = []
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["routing_static"]["removed"]) == 1


@pytest.mark.unit
def test_routing_static_changed_next_hop():
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["static"][0]["next_hop"] = "10.0.0.254"
    diff = diff_mod.diff_topology(old, new)
    changed = diff["routing_static"]["changed"]
    assert len(changed) == 1
    ch = changed[0]
    assert "next_hop" in ch["fields"]
    assert ch["fields"]["next_hop"] == ["10.0.0.2", "10.0.0.254"]


# ===========================================================================
# 9. 決定性テスト
# ===========================================================================

@pytest.mark.unit
def test_diff_topology_is_deterministic():
    """diff_topology を同一入力で2回呼ぶと同一結果。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"][0]["as"] = 99999
    new["routing"]["bgp"][0]["peer_as"] = 99999

    result1 = diff_mod.diff_topology(old, copy.deepcopy(new))
    result2 = diff_mod.diff_topology(old, copy.deepcopy(new))
    assert result1 == result2


@pytest.mark.unit
def test_diff_topology_does_not_mutate_inputs():
    """diff_topology は old/new を変更しない。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    old_snapshot = copy.deepcopy(old)
    new_snapshot = copy.deepcopy(new)
    diff_mod.diff_topology(old, new)
    assert old == old_snapshot
    assert new == new_snapshot


# ===========================================================================
# 10. format_diff_report テスト
# ===========================================================================

@pytest.mark.unit
def test_format_diff_report_no_diff():
    """差分ゼロ → 「差分なし」を含む Markdown が返る。"""
    diff_mod = _import_diff()
    topo = _base_topo()
    diff = diff_mod.diff_topology(topo, copy.deepcopy(topo))
    report = diff_mod.format_diff_report(diff, "old-dir", "new-dir")
    assert isinstance(report, str)
    assert "差分なし" in report


@pytest.mark.unit
def test_format_diff_report_contains_labels():
    """ラベル（old_label / new_label）がレポートに含まれる。"""
    diff_mod = _import_diff()
    topo = _base_topo()
    diff = diff_mod.diff_topology(topo, copy.deepcopy(topo))
    report = diff_mod.format_diff_report(diff, "snapshot-2026-01", "snapshot-2026-02")
    assert "snapshot-2026-01" in report
    assert "snapshot-2026-02" in report


@pytest.mark.unit
def test_format_diff_report_is_deterministic():
    """format_diff_report を同一 diff で2回呼ぶと同一文字列（時刻非依存）。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"][0]["as"] = 99999
    diff = diff_mod.diff_topology(old, new)

    report1 = diff_mod.format_diff_report(diff, "A", "B")
    report2 = diff_mod.format_diff_report(diff, "A", "B")
    assert report1 == report2


@pytest.mark.unit
def test_format_diff_report_count_summary():
    """件数サマリ '+N -M ~K' が含まれる（追加 1 件の場合）。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"].append({"id": "r3", "hostname": "R3", "vendor": "cisco_ios",
                            "as": 65003, "ospf_router_id": None, "bgp_router_id": None,
                            "sections": []})
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    # devices セクションに +1 が含まれる
    assert "+1" in report


@pytest.mark.unit
def test_format_diff_report_removed_marker():
    """removed エントリは '-' プレフィックスで表示される。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"] = [d for d in new["devices"] if d["id"] != "r2"]
    new["interfaces"] = [i for i in new["interfaces"] if i["device"] != "r2"]
    new["links"] = []
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "- r2" in report


@pytest.mark.unit
def test_format_diff_report_added_marker():
    """added エントリは '+' プレフィックスで表示される。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"].append({"id": "r3", "hostname": "R3", "vendor": "cisco_ios",
                            "as": 65003, "ospf_router_id": None, "bgp_router_id": None,
                            "sections": []})
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "+ r3" in report


@pytest.mark.unit
def test_format_diff_report_no_timestamp():
    """レポートに時刻文字列（ISO 8601 / YYYY-MM-DD）が含まれないこと（決定性）。"""
    import re
    diff_mod = _import_diff()
    topo = _base_topo()
    diff = diff_mod.diff_topology(topo, copy.deepcopy(topo))
    report = diff_mod.format_diff_report(diff, "old", "new")
    # 日付パターン YYYY-MM-DD が入っていないこと
    assert not re.search(r"\d{4}-\d{2}-\d{2}", report), \
        f"レポートに日付が含まれている: {report}"


@pytest.mark.unit
def test_format_diff_report_is_markdown():
    """レポートは Markdown（見出し # を含む）。"""
    diff_mod = _import_diff()
    topo = _base_topo()
    diff = diff_mod.diff_topology(topo, copy.deepcopy(topo))
    report = diff_mod.format_diff_report(diff, "X", "Y")
    assert "#" in report


# ===========================================================================
# 11. 複合差分: 複数セクション同時変更
# ===========================================================================

@pytest.mark.unit
def test_multiple_sections_changed_simultaneously():
    """devices と routing_bgp が同時に変わった場合、両方の changed に現れる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["devices"][0]["as"] = 99999
    new["routing"]["bgp"][0]["peer_as"] = 77777
    new["routing"]["static"][0]["next_hop"] = "1.2.3.4"
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["devices"]["changed"]) >= 1
    assert len(diff["routing_bgp"]["changed"]) >= 1
    assert len(diff["routing_static"]["changed"]) >= 1


# ===========================================================================
# 12. エッジケース
# ===========================================================================

@pytest.mark.unit
def test_empty_topology_diff():
    """両方空の topology を比較すると全セクション空 diff。"""
    diff_mod = _import_diff()
    empty = {
        "meta": {}, "devices": [], "interfaces": [], "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    diff = diff_mod.diff_topology(empty, copy.deepcopy(empty))
    for section in ("devices", "interfaces", "links", "segments",
                    "routing_bgp", "routing_ospf", "routing_static"):
        sec = diff[section]
        assert sec["added"] == []
        assert sec["removed"] == []
        assert sec["changed"] == []


@pytest.mark.unit
def test_old_empty_new_has_devices():
    """old が空で new にデバイスがある → 全デバイスが added。"""
    diff_mod = _import_diff()
    old = {
        "meta": {}, "devices": [], "interfaces": [], "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    new = _base_topo()
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["devices"]["added"]) == 2
    assert diff["devices"]["removed"] == []


@pytest.mark.unit
def test_new_empty_old_has_devices():
    """new が空で old にデバイスがある → 全デバイスが removed。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = {
        "meta": {}, "devices": [], "interfaces": [], "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["devices"]["removed"]) == 2
    assert diff["devices"]["added"] == []


# ===========================================================================
# 13. CLI テスト（subprocess）
# ===========================================================================

def _run_cli(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(CLI)] + args,
        capture_output=True, text=True, cwd=cwd,
    )


@pytest.mark.integration
def test_cli_same_dir_no_diff_exit_0():
    """同一ディレクトリを old/new に指定 → 差分なし・終了コード 0。"""
    proc = _run_cli([str(GOLDEN), str(GOLDEN)])
    assert proc.returncode == 0, proc.stderr
    assert "差分なし" in proc.stdout


@pytest.mark.integration
def test_cli_diff_dir_shows_diff_exit_0(tmp_path):
    """golden を new に、1フィールド変えた tmp を old に渡すと差分が出る・終了コード 0。"""
    # golden をコピーして devices.yaml の AS を書き換え
    old_dir = tmp_path / "old"
    shutil.copytree(str(GOLDEN), str(old_dir))
    import yaml
    dev_yaml = old_dir / "devices.yaml"
    data = yaml.safe_load(dev_yaml.read_text(encoding="utf-8"))
    data["devices"][0]["as"] = 99999
    dev_yaml.write_text(
        yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True, indent=2),
        encoding="utf-8",
    )
    proc = _run_cli([str(old_dir), str(GOLDEN)])
    assert proc.returncode == 0, proc.stderr
    # 差分あり → 差分なし にならない
    assert "差分なし" not in proc.stdout
    # AS の差分が含まれる
    assert "as" in proc.stdout or "65001" in proc.stdout or "99999" in proc.stdout


@pytest.mark.integration
def test_cli_output_to_file(tmp_path):
    """-o オプションでファイルに出力できる。"""
    out_file = tmp_path / "diff_report.md"
    proc = _run_cli([str(GOLDEN), str(GOLDEN), "-o", str(out_file)])
    assert proc.returncode == 0, proc.stderr
    assert out_file.exists()
    assert "差分なし" in out_file.read_text(encoding="utf-8")
    # stdout は空（ファイル出力時）
    assert proc.stdout.strip() == ""


@pytest.mark.integration
def test_cli_invalid_dir_exits_nonzero(tmp_path):
    """存在しないディレクトリを指定 → 非ゼロ終了。"""
    proc = _run_cli([str(tmp_path / "nonexistent"), str(GOLDEN)])
    assert proc.returncode != 0
    assert "ERROR" in proc.stderr or "error" in proc.stderr.lower()


@pytest.mark.integration
def test_cli_stdout_when_no_output_option():
    """--output 省略時は stdout にレポートが出力される。"""
    proc = _run_cli([str(GOLDEN), str(GOLDEN)])
    assert proc.returncode == 0
    assert len(proc.stdout) > 0


# ===========================================================================
# 14. format_diff_report のラベル関数カバレッジ補完
#     （_entry_label / _changed_label の segments/routing 各ブランチを通す）
# ===========================================================================

@pytest.mark.unit
def test_format_diff_report_includes_segment_id():
    """segments の added エントリが segment id 表示でレポートに含まれる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["segments"].append({"id": "seg-10.9.9.0/24", "subnet": "10.9.9.0/24",
                             "members": ["r1::Gi0/0"]})
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "seg-10.9.9.0/24" in report


@pytest.mark.unit
def test_format_diff_report_includes_bgp_added_entry():
    """routing_bgp の added エントリが device->neighbor_ip 形式でレポートに含まれる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["bgp"].append({
        "device": "r2", "neighbor_ip": "10.0.0.1", "af": "v4",
        "peer_as": 65001, "type": "ebgp", "local_ip": "10.0.0.2",
        "update_source": None,
    })
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "r2" in report
    assert "10.0.0.1" in report


@pytest.mark.unit
def test_format_diff_report_includes_ospf_added_entry():
    """routing_ospf の added エントリが network= 形式でレポートに含まれる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["ospf"].append({
        "device": "r2", "network": "10.0.0.0/30", "af": "v4",
        "process": 1, "area": "0", "area_type": None,
    })
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "10.0.0.0/30" in report


@pytest.mark.unit
def test_format_diff_report_includes_static_added_entry():
    """routing_static の added エントリが prefix= 形式でレポートに含まれる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["static"].append({
        "device": "r2", "prefix": "10.10.10.0/24", "af": "v4",
        "next_hop": "10.0.0.1",
    })
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "10.10.10.0/24" in report


@pytest.mark.unit
def test_format_diff_report_includes_bgp_changed_entry():
    """routing_bgp の changed エントリが changed_label で表示される。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["bgp"][0]["peer_as"] = 99999
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    # r1 -> 10.0.0.2 (v4) が changed ラベルとして含まれるはず
    assert "r1" in report
    assert "10.0.0.2" in report


@pytest.mark.unit
def test_format_diff_report_includes_ospf_changed_entry():
    """routing_ospf の changed エントリが changed_label で表示される。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["ospf"][0]["area_type"] = "stub"
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "192.168.1.0/24" in report  # network=


@pytest.mark.unit
def test_format_diff_report_includes_static_changed_entry():
    """routing_static の changed エントリが changed_label で表示される。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["routing"]["static"][0]["next_hop"] = "1.2.3.4"
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "0.0.0.0/0" in report  # prefix=


@pytest.mark.unit
def test_format_diff_report_includes_segment_changed_entry():
    """segments の changed エントリが changed_label で表示される。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["segments"][0]["members"] = ["r1::Gi0/0", "r2::ge-0/0/0"]
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    assert "seg-192.168.1.0/24" in report


@pytest.mark.unit
def test_format_diff_report_includes_links_entry():
    """links の added/removed エントリが subnet と端点情報を含むラベルで表示される。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    new["links"] = []
    diff = diff_mod.diff_topology(old, new)
    report = diff_mod.format_diff_report(diff, "old", "new")
    # subnet と端点情報が含まれる
    assert "10.0.0.0/30" in report


# ===========================================================================
# 15. 修正項目1: CLI の YAMLError 捕捉
# ===========================================================================

@pytest.mark.integration
def test_cli_yaml_error_old_exits_nonzero(tmp_path):
    """破損 YAML を old ディレクトリに渡すと非ゼロ終了かつトレースが露出しない。"""
    # golden をコピーして _meta.yaml を破損させる
    old_dir = tmp_path / "old_broken"
    shutil.copytree(str(GOLDEN), str(old_dir))
    meta_yaml = old_dir / "_meta.yaml"
    meta_yaml.write_text("key: :\n  invalid: yaml: content: [\n", encoding="utf-8")
    proc = _run_cli([str(old_dir), str(GOLDEN)])
    assert proc.returncode != 0, "YAMLError で非ゼロ終了するはず"
    assert "ERROR" in proc.stderr
    assert "Traceback" not in proc.stderr, "スタックトレースが stderr に露出している"


@pytest.mark.integration
def test_cli_yaml_error_new_exits_nonzero(tmp_path):
    """破損 YAML を new ディレクトリに渡すと非ゼロ終了かつトレースが露出しない。"""
    new_dir = tmp_path / "new_broken"
    shutil.copytree(str(GOLDEN), str(new_dir))
    meta_yaml = new_dir / "_meta.yaml"
    meta_yaml.write_text("key: :\n  invalid: yaml: content: [\n", encoding="utf-8")
    proc = _run_cli([str(GOLDEN), str(new_dir)])
    assert proc.returncode != 0, "YAMLError で非ゼロ終了するはず"
    assert "ERROR" in proc.stderr
    assert "Traceback" not in proc.stderr, "スタックトレースが stderr に露出している"


# ===========================================================================
# 16. 修正項目3: addresses 順序 false-positive
# ===========================================================================

@pytest.mark.unit
def test_interfaces_addresses_order_no_false_positive():
    """同一内容で順序だけ異なる addresses は changed に出ない。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    # old の addresses: [v4, v6] → new で [v6, v4] に逆順
    old["interfaces"][0]["addresses"] = [
        {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
        {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
    ]
    new["interfaces"][0]["addresses"] = [
        {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
        {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
    ]
    diff = diff_mod.diff_topology(old, new)
    assert diff["interfaces"]["changed"] == [], \
        "順序だけ異なる addresses は changed に出てはいけない"


@pytest.mark.unit
def test_interfaces_addresses_content_diff_is_detected():
    """addresses の内容が異なる場合は changed に出る。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    old["interfaces"][0]["addresses"] = [
        {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
    ]
    new["interfaces"][0]["addresses"] = [
        {"af": "v4", "ip": "10.0.0.9", "prefix": 30},
    ]
    diff = diff_mod.diff_topology(old, new)
    assert len(diff["interfaces"]["changed"]) == 1
    assert "addresses" in diff["interfaces"]["changed"][0]["fields"]


# ===========================================================================
# 17. 修正項目4: 重複自然キーの決定化
# ===========================================================================

@pytest.mark.unit
def test_devices_duplicate_key_first_wins():
    """devices で同一 id が重複した場合、例外なく先勝ちで決定的な結果になる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    # r1 を old に重複追加（as が異なる）
    old["devices"].append({"id": "r1", "hostname": "R1-dup", "vendor": "cisco_ios",
                            "as": 11111, "ospf_router_id": None, "bgp_router_id": None,
                            "sections": []})
    result1 = diff_mod.diff_topology(old, copy.deepcopy(new))
    result2 = diff_mod.diff_topology(old, copy.deepcopy(new))
    # 例外なく完了し、結果が一致（決定的）
    assert result1 == result2


@pytest.mark.unit
def test_routing_bgp_duplicate_key_first_wins():
    """routing.bgp で同一キー重複した場合、例外なく先勝ちで決定的な結果になる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    # old に同一 (device, neighbor_ip, af) を重複追加（peer_as が異なる）
    old["routing"]["bgp"].append({
        "device": "r1", "neighbor_ip": "10.0.0.2", "af": "v4",
        "peer_as": 99999, "type": "ibgp", "local_ip": "10.0.0.1",
        "update_source": None,
    })
    result1 = diff_mod.diff_topology(old, copy.deepcopy(new))
    result2 = diff_mod.diff_topology(old, copy.deepcopy(new))
    assert result1 == result2


@pytest.mark.unit
def test_routing_ospf_duplicate_key_first_wins():
    """routing.ospf で同一キー重複した場合、例外なく先勝ちで決定的な結果になる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    old["routing"]["ospf"].append({
        "device": "r1", "network": "192.168.1.0/24", "af": "v4",
        "process": 99, "area": "1", "area_type": "stub",
    })
    result1 = diff_mod.diff_topology(old, copy.deepcopy(new))
    result2 = diff_mod.diff_topology(old, copy.deepcopy(new))
    assert result1 == result2


@pytest.mark.unit
def test_routing_static_duplicate_key_first_wins():
    """routing.static で同一キー重複した場合、例外なく先勝ちで決定的な結果になる。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    old["routing"]["static"].append({
        "device": "r1", "prefix": "0.0.0.0/0", "af": "v4",
        "next_hop": "1.2.3.4",
    })
    result1 = diff_mod.diff_topology(old, copy.deepcopy(new))
    result2 = diff_mod.diff_topology(old, copy.deepcopy(new))
    assert result1 == result2


# ===========================================================================
# 18. 修正項目5: ネガティブテスト（意図的スキップの明文化）
# ===========================================================================

@pytest.mark.unit
def test_links_kind_change_not_in_changed():
    """links の kind を変えても changed は空（仕様: added/removed のみ追跡）。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    # 同一 (subnet, 端点) で kind だけ変更
    new["links"][0]["kind"] = "manual"  # 元は "inferred-subnet"
    diff = diff_mod.diff_topology(old, new)
    assert diff["links"]["changed"] == [], \
        "links.kind の変更は changed に出てはいけない（added/removed のみ）"


@pytest.mark.unit
def test_segments_ospf_area_change_not_in_changed():
    """segments の ospf_area を変えても segments.changed は空（仕様: members のみ追跡）。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    old["segments"][0]["ospf_area"] = "0"
    new_seg = copy.deepcopy(old["segments"][0])
    new_seg["ospf_area"] = "1"  # ospf_area だけ変更
    new["segments"] = [new_seg]
    diff = diff_mod.diff_topology(old, new)
    assert diff["segments"]["changed"] == [], \
        "segments.ospf_area の変更は changed に出てはいけない（members のみ追跡）"


@pytest.mark.unit
def test_routing_bgp_local_as_change_not_in_changed():
    """bgp の local_as を変えても changed は空（仕様: local_as は非追跡）。"""
    diff_mod = _import_diff()
    old = _base_topo()
    new = copy.deepcopy(old)
    # local_as フィールドを追加・変更（COMPARE に含まれないので changed に出ない）
    old["routing"]["bgp"][0]["local_as"] = 65001
    new["routing"]["bgp"][0]["local_as"] = 99999
    diff = diff_mod.diff_topology(old, new)
    assert diff["routing_bgp"]["changed"] == [], \
        "bgp.local_as は COMPARE に含まれないため changed に出てはいけない"


# ===========================================================================
# 19. 修正項目7: 機密注意 WARN
# ===========================================================================

@pytest.mark.integration
def test_cli_warn_message_on_stdout(capsys):
    """CLI 実行時に機密注意 WARN が stderr に出力される（stdout または -o どちらでも）。"""
    proc = _run_cli([str(GOLDEN), str(GOLDEN)])
    assert proc.returncode == 0, proc.stderr
    assert "WARN" in proc.stderr, "機密注意 WARN が stderr に含まれるはず"


@pytest.mark.integration
def test_cli_warn_message_with_output_file(tmp_path):
    """-o 指定時も機密注意 WARN が stderr に出力される。"""
    out_file = tmp_path / "diff_report.md"
    proc = _run_cli([str(GOLDEN), str(GOLDEN), "-o", str(out_file)])
    assert proc.returncode == 0, proc.stderr
    assert "WARN" in proc.stderr, "機密注意 WARN が stderr に含まれるはず"
