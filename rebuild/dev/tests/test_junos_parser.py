"""§6.2 Juniper JunOS パーサのテスト。附録 B.2 と各マッピング行を検証。"""
import pytest

from lib.parsers.junos import parse_junos

pytestmark = pytest.mark.unit


def _parse(text):
    warnings = []
    return parse_junos(text, warnings), warnings


def test_b2_device_fields(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert dev.hostname == "R2"
    assert dev.vendor == "juniper_junos"
    assert dev.as_ == 65002
    assert dev.ospf_router_id is None
    assert dev.bgp_router_id is None


def test_b2_interfaces(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    names = [i.name for i in dev.interfaces]
    assert names == ["ge-0/0/0", "ge-0/0/1", "lo0"]

    ge0 = dev.interfaces[0]
    assert ge0.description == "to-R1"
    assert [(a.af, a.ip, a.prefix) for a in ge0.addresses] == [("v4", "10.0.0.2", 30)]
    assert ge0.derived_ip() == "10.0.0.2/30"
    assert ge0.shutdown is False
    assert ge0.admin_status == "up"
    assert ge0.l2_l3 == "l3"
    assert ge0.switchport is None


def test_b2_bgp(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert (nb.neighbor_ip, nb.peer_as, nb.af) == ("10.0.0.1", 65001, "v4")


def test_b2_static(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert len(dev.static) == 1
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("0.0.0.0/0", "10.0.0.1", "v4")


def test_b2_no_ospf(junos_cfg_text):
    dev, _ = _parse(junos_cfg_text)
    assert dev.ospf == []


def test_unit_aggregation_multiple_addresses():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.1.1/24\n")
    dev, _ = _parse(text)
    assert len(dev.interfaces) == 1
    assert len(dev.interfaces[0].addresses) == 2


def test_disable_sets_admin_down():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 disable\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].shutdown is True
    assert dev.interfaces[0].admin_status == "down"


def test_inet6_and_link_local():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64\n"
            "set interfaces ge-0/0/0 unit 0 family inet6 address fe80::1/64\n")
    dev, _ = _parse(text)
    addrs = {(a.af, a.ip, a.scope) for a in dev.interfaces[0].addresses}
    assert ("v6", "2001:db8::1", None) in addrs
    assert ("v6", "fe80::1", "link-local") in addrs
    assert dev.interfaces[0].l2_l3 == "l3"


def test_ethernet_switching_is_l2():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family ethernet-switching\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l2"


def test_l2_priority_over_l3():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family ethernet-switching\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/24\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l2"


def test_mtu_speed_encapsulation():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 mtu 9000\n"
            "set interfaces ge-0/0/0 speed 10g\n"
            "set interfaces ge-0/0/0 encapsulation flexible-ethernet-services\n")
    dev, _ = _parse(text)
    i = dev.interfaces[0]
    assert i.mtu == 9000 and i.speed == "10g"
    assert i.encapsulation == "flexible-ethernet-services"


def test_router_id_sets_bgp_and_ospf_fallback():
    text = ("set system host-name X\n"
            "set routing-options router-id 9.9.9.9\n")
    dev, _ = _parse(text)
    assert dev.bgp_router_id == "9.9.9.9"
    assert dev.ospf_router_id == "9.9.9.9"


def test_v6_bgp_neighbor():
    text = ("set system host-name X\n"
            "set protocols bgp group g neighbor 2001:db8::2 peer-as 65010\n")
    dev, _ = _parse(text)
    nb = dev.bgp[0]
    assert (nb.neighbor_ip, nb.peer_as, nb.af) == ("2001:db8::2", 65010, "v6")


def test_ospf_v2_network_from_if_subnet():
    text = ("set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 192.168.5.1/24\n"
            "set protocols ospf area 0.0.0.0 interface ge-0/0/0.0\n")
    dev, _ = _parse(text)
    o = dev.ospf[0]
    assert (o.process, o.network, o.area, o.af) == (None, "192.168.5.0/24", "0", "v4")


def test_ospf3_network_is_base_if_name():
    text = ("set system host-name X\n"
            "set protocols ospf3 area 0.0.0.1 interface ge-0/0/0.0\n")
    dev, _ = _parse(text)
    o = dev.ospf[0]
    assert (o.process, o.network, o.area, o.af) == (None, "ge-0/0/0", "1", "v6")


def test_v6_static_route():
    text = ("set system host-name X\n"
            "set routing-options rib inet6.0 static route 2001:db8:1::/48 next-hop 2001:db8::2\n")
    dev, _ = _parse(text)
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("2001:db8:1::/48", "2001:db8::2", "v6")


def test_dispatch_parse_config(ios_cfg_text, junos_cfg_text):
    from lib.parsers import parse_config
    assert parse_config(ios_cfg_text).vendor == "cisco_ios"
    assert parse_config(junos_cfg_text).vendor == "juniper_junos"
    assert parse_config("foo bar\nbaz qux\n") is None
