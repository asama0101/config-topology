"""DATA.devices（機器・ifs・addrs[]）変換のテスト（§8.4/§8.5/§8.7・全アドレス保持）。"""
import pytest

from lib.rendering.data_transform import build_devices

pytestmark = pytest.mark.unit


def _topo(devices, interfaces, bgp=None, ospf=None, static=None):
    return {"meta": {}, "devices": devices, "interfaces": interfaces,
            "links": [], "segments": [],
            "routing": {"bgp": bgp or [], "ospf": ospf or [], "static": static or []}}


def _dev(id, hostname="H", vendor="cisco_ios", as_=None, ospf_rid=None, bgp_rid=None):
    return {"id": id, "hostname": hostname, "vendor": vendor, "as": as_,
            "ospf_router_id": ospf_rid, "bgp_router_id": bgp_rid, "sections": []}


def _if(device, name, addresses, ip=None, **kw):
    base = {"id": "%s::%s" % (device, name), "device": device, "name": name,
            "ip": ip, "vlan": None, "description": None, "shutdown": False,
            "admin_status": "up", "oper_status": None, "mtu": None, "speed": None,
            "duplex": None, "l2_l3": None, "switchport": None, "encapsulation": None,
            "source": "parsed", "addresses": addresses}
    base.update(kw)
    return base


def test_device_basic_fields():
    topo = _topo([_dev("r1", "R1", "cisco_ios", as_=65001, ospf_rid="1.1.1.1", bgp_rid="9.9.9.9")],
                 [])
    d = build_devices(topo)["r1"]
    assert d["hostname"] == "R1" and d["vendor"] == "cisco_ios" and d["as"] == 65001
    assert d["ospf_rid"] == "1.1.1.1" and d["bgp_rid"] == "9.9.9.9"
    assert d["ifs"] == [] and d["bgp"] == [] and d["ospf"] == [] and d["static"] == []


def test_if_primary_v4_and_gua_and_addrs():
    addrs = [{"af": "v4", "ip": "10.0.0.1", "prefix": 30},
             {"af": "v4", "ip": "10.0.0.9", "prefix": 30, "secondary": True},
             {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
             {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"}]
    topo = _topo([_dev("r1")], [_if("r1", "Gi0", addrs, ip="10.0.0.1/30",
                                    description="to-R2", mtu=1500, speed="1000")])
    itf = build_devices(topo)["r1"]["ifs"][0]
    assert itf["n"] == "Gi0"
    assert itf["ip"] == "10.0.0.1/30"
    assert itf["ip6"] == "2001:db8::1/64"
    assert itf["d"] == "to-R2" and itf["st"] == "up" and itf["mtu"] == 1500 and itf["sp"] == "1000"
    assert itf["addrs"] == addrs
    assert "role" not in itf and "note" not in itf


def test_if_v6_only_has_null_v4():
    topo = _topo([_dev("r1")], [_if("r1", "lo0",
                  [{"af": "v6", "ip": "2001:db8::9", "prefix": 128}], ip=None)])
    itf = build_devices(topo)["r1"]["ifs"][0]
    assert itf["ip"] is None and itf["ip6"] == "2001:db8::9/128"


def test_if_link_local_only_has_null_v6():
    topo = _topo([_dev("r1")], [_if("r1", "Gi0",
                  [{"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"}])])
    itf = build_devices(topo)["r1"]["ifs"][0]
    assert itf["ip6"] is None
    assert len(itf["addrs"]) == 1


def test_ifs_in_config_order():
    topo = _topo([_dev("r1")],
                 [_if("r1", "Gi0", []), _if("r1", "Gi1", []), _if("r1", "lo0", [])])
    assert [i["n"] for i in build_devices(topo)["r1"]["ifs"]] == ["Gi0", "Gi1", "lo0"]
