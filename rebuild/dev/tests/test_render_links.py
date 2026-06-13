"""DATA.links（端点ペア統合・dual-stack マージ・決定的 id）のテスト（§8.4）。"""
import pytest

from lib.rendering.data_transform import build_links, link_id

pytestmark = pytest.mark.unit


def _topo(interfaces, links):
    return {"meta": {}, "devices": [], "interfaces": interfaces,
            "links": links, "segments": [], "routing": {"bgp": [], "ospf": [], "static": []}}


def _if(device, name, addresses):
    return {"id": "%s::%s" % (device, name), "device": device, "name": name,
            "addresses": addresses}


def _link(a_dev, a_if, b_dev, b_if, subnet, **kw):
    d = {"a_device": a_dev, "a_if": a_if, "b_device": b_dev, "b_if": b_if,
         "subnet": subnet, "kind": "inferred-subnet"}
    d.update(kw)
    return d


def test_link_id_symmetric_deterministic():
    a = link_id("r1", "Gi0", "r2", "ge0")
    b = link_id("r2", "ge0", "r1", "Gi0")
    assert a == b and isinstance(a, str)


def test_single_stack_link():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])]
    links = [_link("r1", "Gi0", "r2", "ge0", "10.0.0.0/30")]
    out = build_links(_topo(ifs, links))
    assert len(out) == 1
    l = out[0]
    assert l["a"] == "r1" and l["ai"] == "Gi0" and l["aip"] == "10.0.0.1"
    assert l["b"] == "r2" and l["bi"] == "ge0" and l["bip"] == "10.0.0.2"
    assert l["subnet"] == "10.0.0.0/30"
    assert "dual" not in l and "admin_down" not in l and "area" not in l


def test_dual_stack_merge():
    # /126 は 4 アドレス。::1 と ::2 がともに範囲内に収まる（/127 は 2 アドレスのみで ::2 が範囲外）
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                             {"af": "v6", "ip": "2001:db8::1", "prefix": 126}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                             {"af": "v6", "ip": "2001:db8::2", "prefix": 126}])]
    links = [_link("r1", "Gi0", "r2", "ge0", "10.0.0.0/30"),
             _link("r1", "Gi0", "r2", "ge0", "2001:db8::/126")]
    out = build_links(_topo(ifs, links))
    assert len(out) == 1
    l = out[0]
    assert l["subnet"] == "10.0.0.0/30" and l["aip"] == "10.0.0.1" and l["bip"] == "10.0.0.2"
    assert l["dual"] == "2001:db8::/126"
    assert l["aip6"] == "2001:db8::1" and l["bip6"] == "2001:db8::2"


def test_admin_down_and_area_projected():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}])]
    links = [_link("r1", "Gi0", "r2", "ge0", "10.0.0.0/30",
                   admin_down=True, ospf_area="0", ospf_network="10.0.0.0/30")]
    l = build_links(_topo(ifs, links))[0]
    assert l["admin_down"] is True and l["area"] == "0"


def test_v6_only_link_has_null_v4_keys():
    ifs = [_if("r1", "Gi0", [{"af": "v6", "ip": "2001:db8::1", "prefix": 64}]),
           _if("r2", "ge0", [{"af": "v6", "ip": "2001:db8::2", "prefix": 64}])]
    links = [_link("r1", "Gi0", "r2", "ge0", "2001:db8::/64")]
    l = build_links(_topo(ifs, links))[0]
    assert l["subnet"] is None and l["aip"] is None and l["bip"] is None   # 契約キーは存在
    assert l["dual"] == "2001:db8::/64" and l["aip6"] == "2001:db8::1"


def test_dual_stack_v6_row_first_still_correct_v4_subnet():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                             {"af": "v6", "ip": "2001:db8::1", "prefix": 126}]),
           _if("r2", "ge0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                             {"af": "v6", "ip": "2001:db8::2", "prefix": 126}])]
    # v6 行を先に
    links = [_link("r1", "Gi0", "r2", "ge0", "2001:db8::/126"),
             _link("r1", "Gi0", "r2", "ge0", "10.0.0.0/30")]
    l = build_links(_topo(ifs, links))[0]
    assert l["subnet"] == "10.0.0.0/30" and l["aip"] == "10.0.0.1"   # v4 が None を上書き
    assert l["dual"] == "2001:db8::/126"
