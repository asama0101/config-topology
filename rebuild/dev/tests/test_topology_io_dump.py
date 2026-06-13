"""§3.2 層別 YAML 書出（直列化規約・ファイル割当・空 routing 省略）のテスト。"""
import pytest

from lib.topology_io import dump_topology

pytestmark = pytest.mark.unit


def _minimal_topo():
    return {
        "meta": {"schema_version": "1.0", "title": "Network Topology (config-derived)",
                 "generated_from": ["a.cfg", "b.conf"]},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [{"id": "r1::lo0", "device": "r1", "name": "lo0", "ip": "1.1.1.1/32",
                        "vlan": None, "description": None, "shutdown": False,
                        "admin_status": "up", "oper_status": None, "mtu": None, "speed": None,
                        "duplex": None, "l2_l3": "l3", "switchport": None,
                        "encapsulation": None, "source": "parsed",
                        "addresses": [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]}],
        "links": [], "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }


def test_meta_yaml_serialization(tmp_path):
    dump_topology(_minimal_topo(), str(tmp_path))
    text = (tmp_path / "_meta.yaml").read_text(encoding="utf-8")
    assert text == (
        "generated_from:\n"
        "- a.cfg\n"
        "- b.conf\n"
        "schema_version: '1.0'\n"
        "title: Network Topology (config-derived)\n"
    )


def test_null_emitted_as_null(tmp_path):
    dump_topology(_minimal_topo(), str(tmp_path))
    devs = (tmp_path / "devices.yaml").read_text(encoding="utf-8")
    assert "bgp_router_id: null" in devs
    assert "ospf_router_id: null" in devs
    assert "sections: []" in devs


def test_physical_always_written_even_empty(tmp_path):
    dump_topology(_minimal_topo(), str(tmp_path))
    phys = (tmp_path / "physical.yaml").read_text(encoding="utf-8")
    assert phys == "links: []\nsegments: []\n"


def test_empty_routing_files_not_written(tmp_path):
    dump_topology(_minimal_topo(), str(tmp_path))
    assert not (tmp_path / "routing.bgp.yaml").exists()
    assert not (tmp_path / "routing.ospf.yaml").exists()
    assert not (tmp_path / "routing.static.yaml").exists()


def test_routing_written_when_present(tmp_path):
    topo = _minimal_topo()
    topo["routing"]["bgp"] = [{"af": "v4", "device": "r1", "local_as": 65001,
                               "local_ip": "10.0.0.1", "neighbor_ip": "10.0.0.2",
                               "peer_as": 65002, "type": "ebgp"}]
    dump_topology(topo, str(tmp_path))
    bgp = (tmp_path / "routing.bgp.yaml").read_text(encoding="utf-8")
    assert bgp.startswith("bgp:\n")
    assert "type: ebgp" in bgp


def test_area_string_quoted(tmp_path):
    topo = _minimal_topo()
    topo["routing"]["ospf"] = [{"af": "v4", "area": "0", "device": "r1",
                                "network": "192.168.1.0/24", "process": 1}]
    dump_topology(topo, str(tmp_path))
    ospf = (tmp_path / "routing.ospf.yaml").read_text(encoding="utf-8")
    assert "area: '0'" in ospf
