"""§5.6 読込・参照整合検証のテスト（dangling 参照を ValueError で弾く）。"""
import pytest

from lib.topology_io import dump_topology, load_topology

pytestmark = pytest.mark.unit


def _topo():
    return {
        "meta": {"schema_version": "1.0", "title": "T", "generated_from": ["a.cfg"]},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [{"id": "r1::Gi0", "device": "r1", "name": "Gi0", "ip": None,
                        "vlan": None, "description": None, "shutdown": False,
                        "admin_status": "up", "oper_status": None, "mtu": None,
                        "speed": None, "duplex": None, "l2_l3": None, "switchport": None,
                        "encapsulation": None, "source": "parsed", "addresses": []}],
        "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }


def test_roundtrip(tmp_path):
    dump_topology(_topo(), str(tmp_path))
    loaded = load_topology(str(tmp_path))
    assert loaded["devices"][0]["id"] == "r1"
    assert loaded["interfaces"][0]["device"] == "r1"
    assert loaded["routing"]["bgp"] == []


def test_dangling_interface_device(tmp_path):
    topo = _topo()
    topo["interfaces"][0]["device"] = "rX"
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    msg = str(ei.value)
    assert "devices.yaml" in msg and "device" in msg and "rX" in msg


def test_dangling_link_endpoint(tmp_path):
    topo = _topo()
    topo["links"] = [{"a_device": "r1", "a_if": "Gi0", "b_device": "rZ", "b_if": "Gi9",
                      "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "physical.yaml" in str(ei.value) and "rZ" in str(ei.value)


def test_dangling_link_if_name(tmp_path):
    topo = _topo()
    topo["links"] = [{"a_device": "r1", "a_if": "Gi9", "b_device": "r1", "b_if": "Gi0",
                      "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "a_if" in str(ei.value) and "Gi9" in str(ei.value)


def test_dangling_segment_member(tmp_path):
    topo = _topo()
    topo["segments"] = [{"id": "seg-x", "subnet": "10.0.0.0/24", "members": ["r1::ghost"]}]
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "members" in str(ei.value) and "r1::ghost" in str(ei.value)


def test_dangling_routing_device(tmp_path):
    topo = _topo()
    topo["routing"]["static"] = [{"af": "v4", "device": "rQ", "next_hop": "1.1.1.1",
                                  "prefix": "0.0.0.0/0"}]
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "routing.static.yaml" in str(ei.value) and "rQ" in str(ei.value)


def test_roundtrip_with_routing_entries(tmp_path):
    topo = _topo()
    topo["routing"]["bgp"] = [{"af": "v4", "device": "r1", "local_as": 1, "local_ip": None,
                               "neighbor_ip": "10.0.0.2", "peer_as": 2, "type": "ebgp"}]
    dump_topology(topo, str(tmp_path))
    loaded = load_topology(str(tmp_path))
    assert loaded["routing"]["bgp"][0]["neighbor_ip"] == "10.0.0.2"
    assert loaded["routing"]["ospf"] == [] and loaded["routing"]["static"] == []


def test_empty_routing_file_treated_as_empty_list(tmp_path):
    # 手編集で空になった routing ファイルは空リスト扱い（§3.2）— 内部例外を出さない
    dump_topology(_topo(), str(tmp_path))
    (tmp_path / "routing.bgp.yaml").write_text("", encoding="utf-8")   # 空ファイル
    loaded = load_topology(str(tmp_path))
    assert loaded["routing"]["bgp"] == []


def test_empty_devices_file_degrades_gracefully(tmp_path):
    # 手編集で空になった devices.yaml は空リスト扱い（§3.1）— TypeError を出さない
    dump_topology(_topo(), str(tmp_path))
    (tmp_path / "devices.yaml").write_text("", encoding="utf-8")
    loaded = load_topology(str(tmp_path))
    assert loaded["devices"] == [] and loaded["interfaces"] == []


def test_empty_physical_file_degrades_gracefully(tmp_path):
    dump_topology(_topo(), str(tmp_path))
    (tmp_path / "physical.yaml").write_text("", encoding="utf-8")
    loaded = load_topology(str(tmp_path))
    assert loaded["links"] == [] and loaded["segments"] == []


# ---------------------------------------------------------------------------
# C1 [test HIGH-2]: routing.bgp に update_source を含む YAML ラウンドトリップ
# ---------------------------------------------------------------------------

def test_roundtrip_bgp_with_update_source(tmp_path):
    """routing.bgp エントリに update_source を含む topology を dump→load して
    update_source が保持されることを検証する。

    update_source は任意フィールド（None の場合は省略）のため、
    値あり・値なしの両ケースで ラウンドトリップを確認する。
    """
    # Arrange
    topo = _topo()
    topo["routing"]["bgp"] = [
        # update_source あり（iBGP over loopback ケース）
        {"af": "v4", "device": "r1", "local_as": 65001, "local_ip": "1.1.1.1",
         "neighbor_ip": "2.2.2.2", "peer_as": 65001, "type": "ibgp",
         "update_source": "Loopback0"},
        # update_source なし（通常の eBGP ケース）
        {"af": "v4", "device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
         "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp"},
    ]
    # Act
    dump_topology(topo, str(tmp_path))
    loaded = load_topology(str(tmp_path))
    # Assert: update_source が保持されること
    bgp = loaded["routing"]["bgp"]
    assert len(bgp) == 2
    # update_source あり → 保持
    entry_with_src = next(e for e in bgp if e["neighbor_ip"] == "2.2.2.2")
    assert entry_with_src["update_source"] == "Loopback0"
    # update_source なし → キーが存在しないか None
    entry_without_src = next(e for e in bgp if e["neighbor_ip"] == "10.0.0.2")
    assert entry_without_src.get("update_source") is None


# ---------------------------------------------------------------------------
# CONFIG ビュー — raw_config.yaml 読込・参照整合
# ---------------------------------------------------------------------------

def test_raw_config_roundtrip_multiline(tmp_path):
    """raw_config.yaml の dump→load で多行テキストがそのまま保持されること。"""
    topo = _topo()
    text = "hostname R1\n!\ninterface Gi0\n ip address 10.0.0.1 255.255.255.252\n!\n"
    topo["raw_configs"] = {"r1": text}
    dump_topology(topo, str(tmp_path))
    loaded = load_topology(str(tmp_path))
    assert loaded["raw_configs"] == {"r1": text}


def test_raw_config_absent_gives_empty(tmp_path):
    """raw_config.yaml が無いディレクトリ（旧成果物）でも load でき raw_configs は空 dict。"""
    dump_topology(_topo(), str(tmp_path))
    loaded = load_topology(str(tmp_path))
    assert loaded["raw_configs"] == {}


def test_raw_config_dangling_device_key(tmp_path):
    """raw_configs のキーが未知 device → ValueError（ファイル名・キー付き）。"""
    topo = _topo()
    topo["raw_configs"] = {"rNope": "hostname X\n"}
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    msg = str(ei.value)
    assert "raw_config.yaml" in msg and "rNope" in msg


def test_parse_status_roundtrip(tmp_path):
    topo = _topo()
    topo["raw_configs"] = {"r1": "hostname R1\n interface Gi0\n"}
    topo["parse_status"] = {"r1": ["parsed", "parsed"]}
    dump_topology(topo, str(tmp_path))
    loaded = load_topology(str(tmp_path))
    assert loaded["parse_status"] == {"r1": ["parsed", "parsed"]}


def test_parse_status_absent_gives_empty(tmp_path):
    dump_topology(_topo(), str(tmp_path))
    loaded = load_topology(str(tmp_path))
    assert loaded["parse_status"] == {}


def test_parse_status_dangling_key(tmp_path):
    topo = _topo()
    topo["raw_configs"] = {"r1": "x\n"}
    topo["parse_status"] = {"rNope": ["parsed"]}
    dump_topology(topo, str(tmp_path))
    with pytest.raises(ValueError) as ei:
        load_topology(str(tmp_path))
    assert "raw_config.yaml" in str(ei.value) and "rNope" in str(ei.value)
