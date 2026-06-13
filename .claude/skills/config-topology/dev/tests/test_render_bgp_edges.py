"""DATA.extPeers / bgpEdges と bgp[].link 連結のテスト（§7.3/§8.4）。"""
import pytest

from lib.rendering.data_transform import build_bgp_topology

pytestmark = pytest.mark.unit


def _topo(interfaces, links, bgp):
    return {"meta": {}, "devices": [], "interfaces": interfaces,
            "links": links, "segments": [], "routing": {"bgp": bgp, "ospf": [], "static": []}}


def _if(device, name, addresses):
    return {"id": "%s::%s" % (device, name), "device": device, "name": name,
            "addresses": addresses}


def _bgp(device, local_ip, neighbor_ip, peer_as, type_, af="v4", local_as=None):
    return {"device": device, "local_as": local_as, "local_ip": local_ip,
            "neighbor_ip": neighbor_ip, "peer_as": peer_as, "type": type_, "af": af}


def test_over_link_edge():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])]
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    bgp = [_bgp("r1", "10.0.0.1", "10.0.0.2", 65002, "ebgp"),
           _bgp("r2", "10.0.0.2", "10.0.0.1", 65001, "ebgp")]
    res = build_bgp_topology(_topo(ifs, links, bgp))
    overs = [e for e in res["bgpEdges"] if e["kind"] == "over-link"]
    assert len(overs) == 1 and overs[0]["type"] == "ebgp"
    links_ref = {(e["device"], e["nb"]): e["link"] for e in res["bgp_rows"]}
    assert links_ref[("r1", "10.0.0.2")] == overs[0]["id"]
    assert links_ref[("r2", "10.0.0.1")] == overs[0]["id"]
    assert res["extPeers"] == []


def test_external_peer_and_edge():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "203.0.113.1", "prefix": 30}])]
    bgp = [_bgp("r1", "203.0.113.1", "203.0.113.2", 65100, "ebgp")]
    res = build_bgp_topology(_topo(ifs, [], bgp))
    assert len(res["extPeers"]) == 1
    ext = res["extPeers"][0]
    assert ext["id"] == "ext:203.0.113.2" and ext["as"] == 65100 and ext["from"] == "r1"
    assert ext["sub"] == "203.0.113.2"
    exts = [e for e in res["bgpEdges"] if e["kind"] == "external"]
    assert len(exts) == 1 and exts[0]["ext"] == "ext:203.0.113.2" and exts[0]["a"] == "r1"
    assert exts[0]["srcIf"] == "Gi0"
    assert ext["link"] == exts[0]["id"]


def test_loopback_ibgp_edge():
    ifs = [_if("r1", "lo0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
           _if("r2", "lo0", [{"af": "v4", "ip": "2.2.2.2", "prefix": 32}])]
    bgp = [_bgp("r1", "1.1.1.1", "2.2.2.2", 65001, "ibgp", local_as=65001),
           _bgp("r2", "2.2.2.2", "1.1.1.1", 65001, "ibgp", local_as=65001)]
    res = build_bgp_topology(_topo(ifs, [], bgp))
    lbs = [e for e in res["bgpEdges"] if e["kind"] == "loopback"]
    assert len(lbs) == 1 and lbs[0]["type"] == "ibgp"
    assert {lbs[0]["a"], lbs[0]["b"]} == {"r1", "r2"}


def test_extpeers_deduped_and_sorted():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 24}])]
    bgp = [_bgp("r1", "10.0.0.1", "10.0.0.9", 65100, "ebgp"),
           _bgp("r1", "10.0.0.1", "10.0.0.5", 65101, "ebgp")]
    res = build_bgp_topology(_topo(ifs, [], bgp))
    assert [e["id"] for e in res["extPeers"]] == ["ext:10.0.0.5", "ext:10.0.0.9"]


def test_loopback_aip_corresponds_to_a():
    # 先に来るのが b 側(r2)のセッションでも、aip は a(=r1, sorted先頭)の IP になる
    ifs = [_if("r1", "lo0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32}]),
           _if("r2", "lo0", [{"af": "v4", "ip": "2.2.2.2", "prefix": 32}])]
    # r2 のセッションを先に並べる
    bgp = [_bgp("r2", "2.2.2.2", "1.1.1.1", 65001, "ibgp", local_as=65001),
           _bgp("r1", "1.1.1.1", "2.2.2.2", 65001, "ibgp", local_as=65001)]
    e = [x for x in build_bgp_topology(_topo(ifs, [], bgp))["bgpEdges"] if x["kind"] == "loopback"][0]
    assert e["a"] == "r1" and e["aip"] == "1.1.1.1"
    assert e["b"] == "r2" and e["bip"] == "2.2.2.2"


# ---- dual-stack afs テスト ----

def test_over_link_dual_stack_one_edge_two_afs():
    """物理リンク上に v4+v6 BGP（双方向各2エントリ）→ over-link エッジ1本・afs=["v4","v6"]。"""
    ifs = [
        _if("rtr-a", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                              {"af": "v6", "ip": "2001:db8::1", "prefix": 64}]),
        _if("rtr-b", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                              {"af": "v6", "ip": "2001:db8::2", "prefix": 64}]),
    ]
    links = [
        {"a_device": "rtr-a", "a_if": "Gi0", "b_device": "rtr-b", "b_if": "ge0",
         "subnet": "10.0.0.0/30", "kind": "inferred-subnet"},
        {"a_device": "rtr-a", "a_if": "Gi0", "b_device": "rtr-b", "b_if": "ge0",
         "subnet": "2001:db8::/64", "kind": "inferred-subnet"},
    ]
    bgp = [
        _bgp("rtr-a", "10.0.0.1", "10.0.0.2", 65002, "ebgp", af="v4"),
        _bgp("rtr-b", "10.0.0.2", "10.0.0.1", 65001, "ebgp", af="v4"),
        _bgp("rtr-a", "2001:db8::1", "2001:db8::2", 65002, "ebgp", af="v6"),
        _bgp("rtr-b", "2001:db8::2", "2001:db8::1", 65001, "ebgp", af="v6"),
    ]
    res = build_bgp_topology(_topo(ifs, links, bgp))
    overs = [e for e in res["bgpEdges"] if e["kind"] == "over-link"]
    assert len(overs) == 1, "over-link エッジは1本のみであること"
    assert overs[0]["afs"] == ["v4", "v6"], "dual-stack なので afs は ['v4','v6']"


def test_loopback_dual_stack_one_edge_two_afs():
    """共有 subnet なしの2機器間 iBGP を v4+v6 で → loopback エッジ1本・afs=["v4","v6"]。"""
    ifs = [
        _if("r1", "lo0", [{"af": "v4", "ip": "1.1.1.1", "prefix": 32},
                           {"af": "v6", "ip": "fc00::1", "prefix": 128}]),
        _if("r2", "lo0", [{"af": "v4", "ip": "2.2.2.2", "prefix": 32},
                           {"af": "v6", "ip": "fc00::2", "prefix": 128}]),
    ]
    bgp = [
        _bgp("r1", "1.1.1.1", "2.2.2.2", 65001, "ibgp", af="v4", local_as=65001),
        _bgp("r2", "2.2.2.2", "1.1.1.1", 65001, "ibgp", af="v4", local_as=65001),
        _bgp("r1", "fc00::1", "fc00::2", 65001, "ibgp", af="v6", local_as=65001),
        _bgp("r2", "fc00::2", "fc00::1", 65001, "ibgp", af="v6", local_as=65001),
    ]
    res = build_bgp_topology(_topo(ifs, [], bgp))
    lbs = [e for e in res["bgpEdges"] if e["kind"] == "loopback"]
    assert len(lbs) == 1, "loopback エッジは1本のみであること"
    assert lbs[0]["afs"] == ["v4", "v6"], "dual-stack なので afs は ['v4','v6']"


def test_over_link_single_af_has_one_af():
    """v4 のみの over-link → afs=["v4"]（1要素リスト）。"""
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])]
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    bgp = [_bgp("r1", "10.0.0.1", "10.0.0.2", 65002, "ebgp", af="v4"),
           _bgp("r2", "10.0.0.2", "10.0.0.1", 65001, "ebgp", af="v4")]
    res = build_bgp_topology(_topo(ifs, links, bgp))
    overs = [e for e in res["bgpEdges"] if e["kind"] == "over-link"]
    assert len(overs) == 1
    assert overs[0]["afs"] == ["v4"], "v4 のみなので afs は ['v4']"


def test_external_edge_afs_single():
    """external エッジ（neighbor がトポロジー内にいない）の afs は単一要素リスト。"""
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "203.0.113.1", "prefix": 30}])]
    bgp = [_bgp("r1", "203.0.113.1", "203.0.113.2", 65100, "ebgp", af="v4")]
    res = build_bgp_topology(_topo(ifs, [], bgp))
    exts = [e for e in res["bgpEdges"] if e["kind"] == "external"]
    assert len(exts) == 1
    assert exts[0]["afs"] == ["v4"], "external エッジの afs は単一要素リスト"
