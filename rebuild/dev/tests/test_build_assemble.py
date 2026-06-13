"""§7.4 OSPF area 注釈・§7.5 順序・全体組立のテスト。"""
import pytest

from lib.models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from lib.build import (build_ospf, build_static, annotate_ospf, aggregate_areas,
                       build_topology)

pytestmark = pytest.mark.unit


def test_build_ospf_and_static_flatten():
    d = Device(hostname="R1", vendor="cisco_ios", as_=1)
    d.ospf = [OspfNetwork(1, "192.168.1.0/24", "0", "v4")]
    d.static = [StaticRoute("0.0.0.0/0", "10.0.0.2", "v4")]
    assert build_ospf([("r1", d)]) == [{"device": "r1", "process": 1,
                                        "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    assert build_static([("r1", d)]) == [{"device": "r1", "prefix": "0.0.0.0/0",
                                          "next_hop": "10.0.0.2", "af": "v4"}]


def test_aggregate_areas():
    assert aggregate_areas(["0"]) == "0"
    assert aggregate_areas(["0", "0"]) == "0"
    assert aggregate_areas(["1", "0"]) == "0/1"
    assert aggregate_areas(["10", "2"]) == "2/10"
    assert aggregate_areas(["backbone", "0"]) == "0/backbone"


def test_annotate_ospf_on_link():
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "192.168.1.0/24", "kind": "inferred-subnet"}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"},
            {"device": "r2", "process": None, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    annotate_ospf(links, [], ospf, {})
    assert links[0]["ospf_area"] == "0" and links[0]["ospf_network"] == "192.168.1.0/24"


def test_annotate_skips_admin_down_link():
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "192.168.1.0/24", "kind": "inferred-subnet", "admin_down": True}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    annotate_ospf(links, [], ospf, {})
    assert "ospf_area" not in links[0]


def test_annotate_segment_area():
    segments = [{"id": "seg-192_168_1_0_24", "subnet": "192.168.1.0/24",
                 "members": ["r1::Gi0", "r2::Gi0"]}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "1", "af": "v4"},
            {"device": "r2", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    iface_dev = {"r1::Gi0": "r1", "r2::Gi0": "r2"}
    annotate_ospf([], segments, ospf, iface_dev)
    assert segments[0]["ospf_area"] == "0/1"


def test_annotate_only_endpoint_devices_count():
    # subnet が一致しても、端点でない device の ospf エントリは集約に含めない
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    ospf = [{"device": "r3", "process": 1, "network": "10.0.0.0/30", "area": "5", "af": "v4"}]
    annotate_ospf(links, [], ospf, {})
    assert "ospf_area" not in links[0]


def test_build_topology_orders_and_routing_keys():
    r1 = Device(hostname="R1", vendor="cisco_ios", as_=65001)
    r1.interfaces = [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)],
                               admin_status="up")]
    r1.bgp = [BgpNeighbor("10.0.0.2", 65002, "v4")]
    r2 = Device(hostname="R2", vendor="juniper_junos", as_=65002)
    r2.interfaces = [Interface(name="ge0", addresses=[Address("v4", "10.0.0.2", 30)],
                               admin_status="up")]
    r2.bgp = [BgpNeighbor("10.0.0.1", 65001, "v4")]
    topo = build_topology([r1, r2], ["r1.cfg", "r2.conf"])
    assert topo["meta"] == {"schema_version": "1.0",
                            "title": "Network Topology (config-derived)",
                            "generated_from": ["r1.cfg", "r2.conf"]}
    assert [d["id"] for d in topo["devices"]] == ["r1", "r2"]
    assert len(topo["links"]) == 1
    assert [e["device"] for e in topo["routing"]["bgp"]] == ["r1", "r2"]
    assert topo["routing"]["ospf"] == [] and topo["routing"]["static"] == []
