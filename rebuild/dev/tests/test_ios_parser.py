"""§6.1 Cisco IOS パーサのテスト。附録 B.1 と各マッピング行を検証。"""
import pytest

from lib.parsers.ios import parse_ios

pytestmark = pytest.mark.unit


def _parse(text):
    warnings = []
    return parse_ios(text, warnings), warnings


def test_b1_device_fields(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    assert dev.hostname == "R1"
    assert dev.vendor == "cisco_ios"
    assert dev.as_ == 65001
    assert dev.ospf_router_id is None
    assert dev.bgp_router_id is None


def test_b1_interfaces(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    names = [i.name for i in dev.interfaces]
    assert names == ["GigabitEthernet0/0", "GigabitEthernet0/1", "Loopback0"]

    gi0 = dev.interfaces[0]
    assert gi0.description == "to-R2"
    assert [(a.af, a.ip, a.prefix) for a in gi0.addresses] == [("v4", "10.0.0.1", 30)]
    assert gi0.derived_ip() == "10.0.0.1/30"
    assert gi0.shutdown is False
    assert gi0.admin_status == "up"
    assert gi0.l2_l3 == "l3"
    assert gi0.mtu is None and gi0.speed is None and gi0.duplex is None
    assert gi0.switchport is None and gi0.encapsulation is None and gi0.vlan is None
    assert gi0.oper_status is None

    lo0 = dev.interfaces[2]
    assert lo0.description is None
    assert [(a.af, a.ip, a.prefix) for a in lo0.addresses] == [("v4", "1.1.1.1", 32)]


def test_b1_bgp(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert (nb.neighbor_ip, nb.peer_as, nb.af) == ("10.0.0.2", 65002, "v4")


def test_b1_ospf(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    assert len(dev.ospf) == 1
    o = dev.ospf[0]
    assert (o.process, o.network, o.area, o.af) == (1, "192.168.1.0/24", "0", "v4")


def test_b1_static(ios_cfg_text):
    dev, _ = _parse(ios_cfg_text)
    assert len(dev.static) == 1
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("0.0.0.0/0", "10.0.0.2", "v4")


def test_shutdown_sets_admin_down():
    text = "hostname X\ninterface GigabitEthernet0/0\n shutdown\n!\n"
    dev, _ = _parse(text)
    assert dev.interfaces[0].shutdown is True
    assert dev.interfaces[0].admin_status == "down"


def test_secondary_address():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            " ip address 10.0.0.9 255.255.255.0 secondary\n!\n")
    dev, _ = _parse(text)
    addrs = dev.interfaces[0].addresses
    sec = [a for a in addrs if a.secondary]
    assert len(sec) == 1 and sec[0].ip == "10.0.0.9"
    assert dev.interfaces[0].derived_ip() == "10.0.0.1/24"


def test_ipv6_address_and_link_local():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address 2001:db8::1/64\n"
            " ipv6 address fe80::1/64 link-local\n!\n")
    dev, _ = _parse(text)
    addrs = {(a.af, a.ip, a.prefix, a.scope) for a in dev.interfaces[0].addresses}
    assert ("v6", "2001:db8::1", 64, None) in addrs
    assert ("v6", "fe80::1", 64, "link-local") in addrs


def test_switchport_access_l2():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " switchport mode access\n switchport access vlan 10\n!\n")
    dev, _ = _parse(text)
    i = dev.interfaces[0]
    assert i.switchport == {"mode": "access", "access_vlan": 10}
    assert i.l2_l3 == "l2"


def test_switchport_trunk_l2():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " switchport mode trunk\n switchport trunk allowed vlan 10,20-30\n!\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].switchport == {"mode": "trunk", "trunk_vlans": "10,20-30"}


def test_l3_priority_over_switchport():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " switchport mode access\n ip address 10.0.0.1 255.255.255.0\n!\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l3"


def test_no_switchport_is_l3():
    text = "hostname X\ninterface GigabitEthernet0/0\n no switchport\n!\n"
    dev, _ = _parse(text)
    assert dev.interfaces[0].l2_l3 == "l3"


def test_mtu_speed_duplex_encapsulation():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " mtu 9000\n speed 1000\n duplex full\n encapsulation dot1Q 100\n!\n")
    dev, _ = _parse(text)
    i = dev.interfaces[0]
    assert i.mtu == 9000 and i.speed == "1000" and i.duplex == "full"
    assert i.encapsulation == "dot1q"


def test_ospf_dotted_area_normalized():
    text = ("hostname X\nrouter ospf 1\n"
            " network 10.1.0.0 0.0.255.255 area 0.0.0.1\n!\n")
    dev, _ = _parse(text)
    assert dev.ospf[0].area == "1"
    assert dev.ospf[0].network == "10.1.0.0/16"


def test_ipv6_route_static():
    text = "hostname X\nipv6 route 2001:db8:1::/48 2001:db8::2\n"
    dev, _ = _parse(text)
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("2001:db8:1::/48", "2001:db8::2", "v6")


def test_sensitive_lines_skipped():
    text = ("hostname X\nenable secret 5 $1$xyz\ninterface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n!\n")
    dev, _ = _parse(text)
    assert dev.hostname == "X"
    assert dev.interfaces[0].derived_ip() == "10.0.0.1/24"


def test_bad_line_warns_not_crash():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address GARBAGE not-a-mask\n!\n")
    dev, warnings = _parse(text)
    assert dev.interfaces[0].addresses == []
    assert len(warnings) >= 1


def test_ipv6_ospf_interface_block_v6_subnet():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address 2001:db8:5::1/64\n"
            " ipv6 ospf 1 area 0\n!\n")
    dev, _ = _parse(text)
    o = [x for x in dev.ospf if x.af == "v6"]
    assert len(o) == 1
    assert (o[0].process, o[0].network, o[0].area, o[0].af) == (1, "2001:db8:5::/64", "0", "v6")


def test_ipv6_ospf_interface_block_fallback_ifname():
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 ospf 1 area 0.0.0.1\n!\n")
    dev, _ = _parse(text)
    o = [x for x in dev.ospf if x.af == "v6"]
    assert len(o) == 1
    assert (o[0].process, o[0].network, o[0].area, o[0].af) == (1, "GigabitEthernet0/0", "1", "v6")


def test_ipv6_ospf_decl_before_address_resolves():
    # ipv6 ospf 行が ipv6 address より前でも IF サブネットを解決できる
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 ospf 1 area 0\n"
            " ipv6 address 2001:db8:9::1/64\n!\n")
    dev, _ = _parse(text)
    o = [x for x in dev.ospf if x.af == "v6"]
    assert o[0].network == "2001:db8:9::/64"
