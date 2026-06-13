"""§7.3 BGP 対向解決（local_ip / type / 片側オーバーレイ）のテスト。"""
import pytest

from lib.models import Address, BgpNeighbor, Device, Interface
from lib.build import build_bgp

pytestmark = pytest.mark.unit


def _dev(hostname, asn, ifs, nbs):
    d = Device(hostname=hostname, vendor="cisco_ios", as_=asn)
    d.interfaces = ifs
    d.bgp = nbs
    return d


def test_ebgp_with_local_ip_resolved():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    bgp = build_bgp([("r1", r1)])
    assert bgp == [{"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                    "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"}]


def test_ibgp_same_as():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("10.0.0.2", 65001, "v4")])
    assert build_bgp([("r1", r1)])[0]["type"] == "ibgp"


def test_unknown_peer_as_none():
    r1 = _dev("R1", 65001, [], [BgpNeighbor("203.0.113.9", None, "v4")])
    e = build_bgp([("r1", r1)])[0]
    assert e["type"] == "unknown" and e["peer_as"] is None and e["local_ip"] is None


def test_local_ip_none_when_no_matching_subnet():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v4", "192.168.1.1", 24)])],
              [BgpNeighbor("10.0.0.2", 65002, "v4")])
    assert build_bgp([("r1", r1)])[0]["local_ip"] is None


def test_v6_neighbor_uses_v6_local_ip():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v6", "2001:db8::1", 64),
                                                Address("v4", "10.0.0.1", 30)])],
              [BgpNeighbor("2001:db8::2", 65002, "v6")])
    e = build_bgp([("r1", r1)])[0]
    assert e["af"] == "v6" and e["local_ip"] == "2001:db8::1"


def test_v6_link_local_not_used_as_local_ip():
    r1 = _dev("R1", 65001,
              [Interface(name="Gi0", addresses=[Address("v6", "fe80::1", 64, scope="link-local")])],
              [BgpNeighbor("fe80::2", 65002, "v6")])
    # link-local は local_ip に使わない → None
    assert build_bgp([("r1", r1)])[0]["local_ip"] is None
