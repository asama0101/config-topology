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
