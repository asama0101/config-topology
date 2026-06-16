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


def test_bgp_af_ipv6_activate_flips_af():
    # §6.1: address-family ipv6 下の neighbor <v6> activate で af が v6 に確定
    text = ("hostname X\nrouter bgp 65001\n"
            " neighbor 2001:db8::2 remote-as 65002\n"
            " address-family ipv6\n"
            "  neighbor 2001:db8::2 activate\n"
            " exit-address-family\n!\n")
    dev, _ = _parse(text)
    nb = [n for n in dev.bgp if n.neighbor_ip == "2001:db8::2"][0]
    assert nb.af == "v6"


def test_bgp_and_ospf_router_id_captured():
    # §5.2.1: 両 router-id は独立に取得される
    text = ("hostname X\nrouter bgp 65001\n bgp router-id 9.9.9.9\n!\n"
            "router ospf 1\n router-id 8.8.8.8\n!\n")
    dev, _ = _parse(text)
    assert dev.bgp_router_id == "9.9.9.9"
    assert dev.ospf_router_id == "8.8.8.8"


def test_description_quotes_stripped():
    text = ('hostname X\ninterface GigabitEthernet0/0\n description "link to core"\n!\n')
    dev, _ = _parse(text)
    assert dev.interfaces[0].description == "link to core"


def test_b1_all_interface_details(ios_cfg_text):
    # 附録 B.1 の 2/3 番目 IF も検証（gi1=LAN, lo0）
    dev, _ = _parse(ios_cfg_text)
    gi1 = dev.interfaces[1]
    assert gi1.name == "GigabitEthernet0/1" and gi1.description == "LAN"
    assert gi1.derived_ip() == "192.168.1.1/24" and gi1.l2_l3 == "l3"
    lo0 = dev.interfaces[2]
    assert lo0.name == "Loopback0" and lo0.derived_ip() == "1.1.1.1/32"


# ---------------------------------------------------------------------------
# C2: OSPF interface パラメータ抽出（IOS）
# ---------------------------------------------------------------------------

def test_ios_ospf_cost_parsed():
    """ip ospf cost <n> が Interface.ospf["cost"] に int で入ること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
            " ip ospf cost 100\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    iface = dev.interfaces[0]
    assert iface.ospf is not None
    assert iface.ospf["cost"] == 100


def test_ios_ospf_network_type_parsed():
    """ip ospf network point-to-point が Interface.ospf["network_type"] に入ること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
            " ip ospf network point-to-point\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    iface = dev.interfaces[0]
    assert iface.ospf is not None
    assert iface.ospf["network_type"] == "point-to-point"


def test_ios_ospf_network_type_broadcast():
    """ip ospf network broadcast が Interface.ospf["network_type"] に入ること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip ospf network broadcast\n!\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].ospf["network_type"] == "broadcast"


def test_ios_ospf_passive_interface_sets_passive():
    """router ospf 配下の passive-interface <ifname> が対応 IF の ospf["passive"]=True を立てること。"""
    text = ("hostname X\n"
            "interface GigabitEthernet0/1\n"
            " ip address 192.168.1.1 255.255.255.0\n!\n"
            "router ospf 1\n"
            " passive-interface GigabitEthernet0/1\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    iface = dev.interfaces[0]
    assert iface.ospf is not None
    assert iface.ospf.get("passive") is True


def test_ios_ospf_cost_and_passive_combined():
    """cost + passive-interface が同一 IF に同時に設定されること。"""
    text = ("hostname X\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
            " ip ospf cost 50\n!\n"
            "router ospf 1\n"
            " passive-interface GigabitEthernet0/0\n!\n")
    dev, _ = _parse(text)
    iface = dev.interfaces[0]
    assert iface.ospf["cost"] == 50
    assert iface.ospf["passive"] is True


def test_ios_ospf_passive_only_targets_named_interface():
    """passive-interface は指定 IF のみに passive を付け、他の IF には影響しないこと。"""
    text = ("hostname X\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n!\n"
            "interface GigabitEthernet0/1\n"
            " ip address 192.168.1.1 255.255.255.0\n!\n"
            "router ospf 1\n"
            " passive-interface GigabitEthernet0/1\n!\n")
    dev, _ = _parse(text)
    gi0 = dev.interfaces[0]
    gi1 = dev.interfaces[1]
    assert gi0.ospf is None
    assert gi1.ospf is not None and gi1.ospf["passive"] is True


def test_ios_ospf_no_ospf_param_leaves_ospf_none():
    """OSPF interface パラメータが無い IF は ospf=None のまま（既存動作維持）。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n!\n")
    dev, _ = _parse(text)
    assert dev.interfaces[0].ospf is None


def test_ios_ospf_all_three_subkeys():
    """cost + network_type + passive の3サブキーが同時に設定されること。"""
    text = ("hostname X\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
            " ip ospf cost 10\n"
            " ip ospf network point-to-point\n!\n"
            "router ospf 1\n"
            " passive-interface GigabitEthernet0/0\n!\n")
    dev, _ = _parse(text)
    iface = dev.interfaces[0]
    assert iface.ospf == {"cost": 10, "network_type": "point-to-point", "passive": True}


# ---------------------------------------------------------------------------
# 修正 4: passive-interface default ネガティブテスト
# ---------------------------------------------------------------------------

def test_ios_ospf_passive_interface_default_ignored():
    """router ospf 配下の `passive-interface default` のみでは、どの IF にも ospf["passive"] が付かないこと。

    現実装は `passive-interface default` および `no passive-interface <if>` 非対応。
    明示的な `passive-interface <ifname>` のみを処理する（非対応を明示的にテストで記録）。
    """
    text = ("hostname X\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n!\n"
            "interface GigabitEthernet0/1\n"
            " ip address 192.168.1.1 255.255.255.0\n!\n"
            "router ospf 1\n"
            " passive-interface default\n!\n")
    dev, warnings = _parse(text)
    # passive-interface default は無視され、どの IF にも passive が付かない
    for iface in dev.interfaces:
        assert iface.ospf is None or iface.ospf.get("passive") is not True, (
            f"{iface.name}: ospf passive が誤って設定された（passive-interface default は非対応）"
        )


# ---------------------------------------------------------------------------
# #3: IOS static route IF 形対応（ip route / ipv6 route）
# ---------------------------------------------------------------------------

def test_static_route_regression_ip_nh():
    """既存の ip route 0.0.0.0 0.0.0.0 <IP> 形式が不変であること（回帰）。"""
    text = "hostname X\nip route 0.0.0.0 0.0.0.0 10.0.0.2\n"
    dev, warnings = _parse(text)
    assert warnings == []
    assert len(dev.static) == 1
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("0.0.0.0/0", "10.0.0.2", "v4")


def test_static_route_ifname_only():
    """ip route <net> <mask> <IF名> の場合、next_hop に IF 名が入ること。"""
    text = "hostname X\nip route 10.1.0.0 255.255.0.0 GigabitEthernet0/0\n"
    dev, warnings = _parse(text)
    assert warnings == []
    assert len(dev.static) == 1
    s = dev.static[0]
    assert s.prefix == "10.1.0.0/16"
    assert s.next_hop == "GigabitEthernet0/0"
    assert s.af == "v4"


def test_static_route_ifname_plus_nh_ip_wins():
    """IF 名 + NH IP 併記の場合、next_hop に IP が優先されること。"""
    text = "hostname X\nip route 0.0.0.0 0.0.0.0 GigabitEthernet0/0 192.168.1.1\n"
    dev, warnings = _parse(text)
    assert warnings == []
    s = dev.static[0]
    assert s.next_hop == "192.168.1.1"


def test_static_route_ad_suffix_stripped():
    """末尾の AD（数字）が除かれ経路として正常パースされること。"""
    text = "hostname X\nip route 10.0.0.0 255.0.0.0 10.0.0.1 200\n"
    dev, warnings = _parse(text)
    assert warnings == []
    s = dev.static[0]
    assert (s.prefix, s.next_hop) == ("10.0.0.0/8", "10.0.0.1")


def test_static_route_name_suffix_stripped():
    """末尾の `name <x>` が除かれ経路として正常パースされること。"""
    text = "hostname X\nip route 10.2.0.0 255.255.0.0 10.2.0.1 name DEFAULT-GW\n"
    dev, warnings = _parse(text)
    assert warnings == []
    s = dev.static[0]
    assert (s.prefix, s.next_hop) == ("10.2.0.0/16", "10.2.0.1")


def test_static_route_track_permanent_stripped():
    """末尾の `track <n>` / `permanent` が除かれ経路として正常パースされること。"""
    text = ("hostname X\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.2 track 1\n"
            "ip route 192.168.0.0 255.255.0.0 10.0.0.3 permanent\n")
    dev, warnings = _parse(text)
    assert warnings == []
    assert len(dev.static) == 2
    assert dev.static[0].next_hop == "10.0.0.2"
    assert dev.static[1].next_hop == "10.0.0.3"


def test_static_route_ifname_with_ad_and_name():
    """IF 名 + AD + name が同時に付いた場合もパースできること。"""
    text = "hostname X\nip route 0.0.0.0 0.0.0.0 GigabitEthernet0/1 100 name ISP\n"
    dev, warnings = _parse(text)
    assert warnings == []
    s = dev.static[0]
    assert s.next_hop == "GigabitEthernet0/1"
    assert s.prefix == "0.0.0.0/0"


def test_ipv6_static_route_regression():
    """既存の ipv6 route <pfx> <IPv6 NH> 形式が不変であること（回帰）。"""
    text = "hostname X\nipv6 route 2001:db8:1::/48 2001:db8::2\n"
    dev, warnings = _parse(text)
    assert warnings == []
    s = dev.static[0]
    assert (s.prefix, s.next_hop, s.af) == ("2001:db8:1::/48", "2001:db8::2", "v6")


def test_ipv6_static_route_ifname_only():
    """ipv6 route <pfx> <IF名> の場合、next_hop に IF 名が入ること。"""
    text = "hostname X\nipv6 route ::/0 GigabitEthernet0/0\n"
    dev, warnings = _parse(text)
    assert warnings == []
    s = dev.static[0]
    assert s.next_hop == "GigabitEthernet0/0"
    assert s.af == "v6"


def test_ipv6_static_route_ifname_plus_nh():
    """ipv6 route <pfx> <IF名> <IPv6 NH> の場合、next_hop に IPv6 IP が優先されること。"""
    text = "hostname X\nipv6 route ::/0 GigabitEthernet0/0 2001:db8::1\n"
    dev, warnings = _parse(text)
    assert warnings == []
    s = dev.static[0]
    assert s.next_hop == "2001:db8::1"


# ---------------------------------------------------------------------------
# #6: IOS OSPFv3 新形式（ospfv3 <pid> ipv6 area <a>）
# ---------------------------------------------------------------------------

def test_ospfv3_new_form_v6_subnet():
    """ospfv3 <pid> ipv6 area <a> が OspfNetwork(af='v6') を生成し network が IF v6 サブネットであること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address 2001:db8:10::1/64\n"
            " ospfv3 2 ipv6 area 0\n!\n")
    dev, warnings = _parse(text)
    ospf_v6 = [o for o in dev.ospf if o.af == "v6"]
    assert len(ospf_v6) == 1
    o = ospf_v6[0]
    assert o.process == 2
    assert o.network == "2001:db8:10::/64"
    assert o.area == "0"
    assert o.af == "v6"


def test_ospfv3_new_form_fallback_ifname():
    """ospfv3 形式で v6 アドレスが無い場合、network に IF 名がフォールバックすること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ospfv3 1 ipv6 area 1\n!\n")
    dev, warnings = _parse(text)
    ospf_v6 = [o for o in dev.ospf if o.af == "v6"]
    assert len(ospf_v6) == 1
    assert ospf_v6[0].network == "GigabitEthernet0/0"
    assert ospf_v6[0].area == "1"


def test_ospfv3_ipv4_keyword_ignored():
    """ospfv3 ... ipv4 area ... は v1 スコープ外として無視されること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
            " ospfv3 1 ipv4 area 0\n!\n")
    dev, warnings = _parse(text)
    ospf_v6 = [o for o in dev.ospf if o.af == "v6"]
    assert ospf_v6 == []


def test_ospfv3_and_legacy_coexist():
    """ospfv3 ipv6 と legacy ipv6 ospf が同一 IF に共存できること（両方 OspfNetwork を生成）。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address 2001:db8:20::1/64\n"
            " ipv6 ospf 1 area 0\n"
            " ospfv3 2 ipv6 area 1\n!\n")
    dev, warnings = _parse(text)
    ospf_v6 = [o for o in dev.ospf if o.af == "v6"]
    assert len(ospf_v6) == 2
    procs = {o.process for o in ospf_v6}
    assert procs == {1, 2}


# ---------------------------------------------------------------------------
# #9: IOS asdot 4-byte ASN + dhcp/unnumbered 警告
# ---------------------------------------------------------------------------

def test_bgp_asdot_router_bgp():
    """`router bgp 1.0` が as_=65536 として解釈されること。"""
    text = "hostname X\nrouter bgp 1.0\n!\n"
    dev, warnings = _parse(text)
    assert dev.as_ == 65536


def test_bgp_asdot_remote_as():
    """`neighbor X remote-as 1.0` が peer_as=65536 として解釈されること。"""
    text = ("hostname X\nrouter bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 1.0\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.peer_as == 65536


def test_bgp_asplain_unchanged():
    """`router bgp 65001` が従来通り as_=65001 のままであること（回帰）。"""
    text = "hostname X\nrouter bgp 65001\n!\n"
    dev, _ = _parse(text)
    assert dev.as_ == 65001


def test_bgp_asdot_large():
    """`router bgp 2.100` が 2*65536+100=131172 として解釈されること。"""
    text = "hostname X\nrouter bgp 2.100\n!\n"
    dev, _ = _parse(text)
    assert dev.as_ == 2 * 65536 + 100


def test_ip_address_dhcp_no_addr_and_warning():
    """`ip address dhcp` でアドレスが付与されず warnings に dhcp 旨のメッセージが入ること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address dhcp\n!\n")
    dev, warnings = _parse(text)
    assert dev.interfaces[0].addresses == []
    assert any("dhcp" in w.lower() for w in warnings)


def test_ip_address_negotiated_warning():
    """`ip address negotiated` でアドレスが付与されず警告が出ること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip address negotiated\n!\n")
    dev, warnings = _parse(text)
    assert dev.interfaces[0].addresses == []
    assert any("negotiated" in w.lower() or "dhcp" in w.lower() for w in warnings)


def test_ip_unnumbered_warning():
    """`ip unnumbered <if>` でアドレスが付与されず warnings に unnumbered 旨が入ること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ip unnumbered Loopback0\n!\n")
    dev, warnings = _parse(text)
    assert dev.interfaces[0].addresses == []
    assert any("unnumbered" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# #10: IPv6 末尾キーワード eui-64/anycast/autoconfig
# ---------------------------------------------------------------------------

def test_ipv6_address_eui64_prefix_extracted():
    """`ipv6 address <prefix> eui-64` で prefix のみが抽出されること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address 2001:db8::/64 eui-64\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    addrs = dev.interfaces[0].addresses
    assert len(addrs) == 1
    a = addrs[0]
    assert a.af == "v6"
    assert a.prefix == 64
    # eui-64 はホストビット未解決のため prefix 部のみ格納（ネットワークアドレス相当）
    assert "2001:db8" in a.ip


def test_ipv6_address_anycast_prefix_extracted():
    """`ipv6 address <addr>/128 anycast` で Address 生成・例外なし。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address 2001:db8::1/128 anycast\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    addrs = dev.interfaces[0].addresses
    assert len(addrs) == 1
    assert addrs[0].ip == "2001:db8::1"


def test_ipv6_address_autoconfig_no_addr_and_warning():
    """`ipv6 address autoconfig` でアドレスが付与されず警告が出ること。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address autoconfig\n!\n")
    dev, warnings = _parse(text)
    assert dev.interfaces[0].addresses == []
    assert any("autoconfig" in w.lower() for w in warnings)


def test_ipv6_address_link_local_unchanged():
    """既存の `ipv6 address fe80::1/64 link-local` が不変であること（回帰）。"""
    text = ("hostname X\ninterface GigabitEthernet0/0\n"
            " ipv6 address fe80::1/64 link-local\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    a = dev.interfaces[0].addresses[0]
    assert a.scope == "link-local"


# ---------------------------------------------------------------------------
# C1: BGP update-source 抽出（IOS）
# ---------------------------------------------------------------------------

def test_ios_bgp_update_source_extracted():
    """neighbor <ip> update-source <ifname> で BgpNeighbor.update_source にインターフェース名が入ること。"""
    text = ("hostname X\nrouter bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65001\n"
            " neighbor 10.0.0.2 update-source Loopback0\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.update_source == "Loopback0"


def test_ios_bgp_update_source_before_remote_as():
    """update-source が remote-as より前に出現しても正しく紐付けられること（順不同保証）。"""
    text = ("hostname X\nrouter bgp 65001\n"
            " neighbor 10.0.0.2 update-source Loopback0\n"
            " neighbor 10.0.0.2 remote-as 65001\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.update_source == "Loopback0"


def test_ios_bgp_update_source_multiple_neighbors():
    """複数 neighbor それぞれの update-source が正しい neighbor に紐付けられること。"""
    text = ("hostname X\nrouter bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65001\n"
            " neighbor 10.0.0.2 update-source Loopback0\n"
            " neighbor 10.0.0.3 remote-as 65002\n"
            " neighbor 10.0.0.3 update-source GigabitEthernet0/1\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    nb_map = {n.neighbor_ip: n for n in dev.bgp}
    assert nb_map["10.0.0.2"].update_source == "Loopback0"
    assert nb_map["10.0.0.3"].update_source == "GigabitEthernet0/1"


def test_ios_bgp_update_source_under_address_family():
    """address-family 配下の neighbor <ip> update-source も拾えること。"""
    text = ("hostname X\nrouter bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65001\n"
            " address-family ipv4\n"
            "  neighbor 10.0.0.2 update-source Loopback0\n"
            " exit-address-family\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.update_source == "Loopback0"


def test_ios_bgp_update_source_none_when_not_configured():
    """update-source が設定されていない neighbor の update_source は None のままであること。"""
    text = ("hostname X\nrouter bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65002\n!\n")
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.update_source is None


# ---------------------------------------------------------------------------
# C1 [test MED-1]: address-family ipv6 配下の v6 neighbor update-source 抽出
# ---------------------------------------------------------------------------

def test_ios_bgp_update_source_v6_neighbor_under_af_ipv6():
    """address-family ipv6 配下の v6 neighbor に update-source が付くケースで update_source が抽出されること。

    §6.1: address-family ipv6 配下でも neighbor update-source は _parse_bgp_line で処理される。
    bgp_af が "v6" の文脈で v6 neighbor の update-source が取得できること。
    """
    # Arrange: v6 neighbor を address-family ipv6 配下で activate し、
    #          同じく address-family ipv6 配下で update-source を宣言
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 2001:db8::2 remote-as 65001\n"
        " address-family ipv6\n"
        "  neighbor 2001:db8::2 activate\n"
        "  neighbor 2001:db8::2 update-source Loopback0\n"
        " exit-address-family\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    nb = [n for n in dev.bgp if n.neighbor_ip == "2001:db8::2"][0]
    assert nb.af == "v6"
    assert nb.update_source == "Loopback0"


# ---------------------------------------------------------------------------
# C3: OSPF area type 抽出（IOS）
# ---------------------------------------------------------------------------

def test_ios_ospf_area_stub_extracted():
    """area <a> stub が area_type='stub' として対応 OspfNetwork に設定されること。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.1.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.1.0.0 0.0.0.255 area 1\n"
        " area 1 stub\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    ospf_area1 = [o for o in dev.ospf if o.area == "1"]
    assert len(ospf_area1) == 1
    assert ospf_area1[0].area_type == "stub"


def test_ios_ospf_area_stub_no_summary_extracted():
    """area <a> stub no-summary が area_type='totally-stubby' として設定されること。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.2.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.2.0.0 0.0.0.255 area 2\n"
        " area 2 stub no-summary\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    ospf_area2 = [o for o in dev.ospf if o.area == "2"]
    assert len(ospf_area2) == 1
    assert ospf_area2[0].area_type == "totally-stubby"


def test_ios_ospf_area_nssa_extracted():
    """area <a> nssa が area_type='nssa' として設定されること。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.3.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.3.0.0 0.0.0.255 area 3\n"
        " area 3 nssa\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    ospf_area3 = [o for o in dev.ospf if o.area == "3"]
    assert len(ospf_area3) == 1
    assert ospf_area3[0].area_type == "nssa"


def test_ios_ospf_area_nssa_no_summary_extracted():
    """area <a> nssa no-summary が area_type='totally-nssa' として設定されること。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.4.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.4.0.0 0.0.0.255 area 4\n"
        " area 4 nssa no-summary\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    ospf_area4 = [o for o in dev.ospf if o.area == "4"]
    assert len(ospf_area4) == 1
    assert ospf_area4[0].area_type == "totally-nssa"


def test_ios_ospf_area_type_order_independent():
    """network 宣言より area-type 宣言が先に来ても正しく適用されること（順不同保証）。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.5.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " area 5 stub\n"
        " network 10.5.0.0 0.0.0.255 area 5\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    ospf_area5 = [o for o in dev.ospf if o.area == "5"]
    assert len(ospf_area5) == 1
    assert ospf_area5[0].area_type == "stub"


def test_ios_ospf_area_type_no_network_no_ospf_entry():
    """area-type 宣言だけで network 宣言が無い area では OspfNetwork が生成されないこと（例外なし）。"""
    text = (
        "hostname X\n"
        "router ospf 1\n"
        " area 99 stub\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    # area 99 の OspfNetwork は存在しない（例外も起きない）
    assert all(o.area != "99" for o in dev.ospf)


def test_ios_ospf_area_type_does_not_affect_other_areas():
    """area-type 宣言が同一 process 内の他 area のエントリに影響しないこと。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.0.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/1\n"
        " ip address 10.6.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.0.0.0 0.0.0.255 area 0\n"
        " network 10.6.0.0 0.0.0.255 area 6\n"
        " area 6 nssa\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    area0 = [o for o in dev.ospf if o.area == "0"]
    area6 = [o for o in dev.ospf if o.area == "6"]
    assert area0[0].area_type is None
    assert area6[0].area_type == "nssa"


def test_ios_ospf_area_type_dotted_area_normalized():
    """area 0.0.0.1 stub のように dotted 表記の area も norm_ospf_area で正規化されること。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.7.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.7.0.0 0.0.0.255 area 0.0.0.1\n"
        " area 0.0.0.1 stub\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    ospf_area = [o for o in dev.ospf if o.area == "1"]
    assert len(ospf_area) == 1
    assert ospf_area[0].area_type == "stub"


def test_ios_ospf_area_type_does_not_apply_to_v6():
    """IOS router ospf の area-type (OSPFv2) は v6 (OSPFv3) エントリには適用されないこと。

    IOS の `router ospf <pid>` ブロックの area-type 宣言は OSPFv2 (af=='v4') スコープ。
    同じ area の OSPFv3 エントリ (af=='v6') に area_type が漏れ込んではならない。
    """
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.8.0.1 255.255.255.0\n"
        " ipv6 address 2001:db8:8::1/64\n"
        " ipv6 ospf 1 area 8\n!\n"
        "router ospf 1\n"
        " network 10.8.0.0 0.0.0.255 area 8\n"
        " area 8 stub\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    area8 = [o for o in dev.ospf if o.area == "8"]
    assert len(area8) == 2  # v4 + v6
    v4_entries = [o for o in area8 if o.af == "v4"]
    v6_entries = [o for o in area8 if o.af == "v6"]
    # v4 には area_type が付く
    assert v4_entries[0].area_type == "stub"
    # v6 (OSPFv3) には IOS router ospf の area-type は漏れない
    assert v6_entries[0].area_type is None


def test_ios_ospf_area_type_no_cross_process_contamination():
    """異なる OSPF プロセスの同一 area 番号に area-type が漏れないこと（クロス汚染防止）。

    `router ospf 1 / area 1 stub` の area-type が `router ospf 2` の area 1 エントリに
    適用されてはならない。
    """
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.1.0.1 255.255.255.0\n!\n"
        "interface GigabitEthernet0/1\n"
        " ip address 10.11.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.1.0.0 0.0.0.255 area 1\n"
        " area 1 stub\n!\n"
        "router ospf 2\n"
        " network 10.11.0.0 0.0.0.255 area 1\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    pid1_area1 = [o for o in dev.ospf if o.area == "1" and o.process == 1]
    pid2_area1 = [o for o in dev.ospf if o.area == "1" and o.process == 2]
    assert len(pid1_area1) == 1
    assert len(pid2_area1) == 1
    # process=1 の area 1 には stub が付く
    assert pid1_area1[0].area_type == "stub"
    # process=2 の area 1 には area_type が付かない（クロス汚染防止）
    assert pid2_area1[0].area_type is None


def test_ios_ospf_area_stub_default_metric_no_match():
    """area 1 stub-default-metric 10 のような非標準キーワードが area_type に誤マッチしないこと。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.1.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.1.0.0 0.0.0.255 area 1\n"
        " area 1 stub-default-metric 10\n!\n"
    )
    dev, warnings = _parse(text)
    # stub-default-metric は area_type を設定しない
    area1 = [o for o in dev.ospf if o.area == "1"]
    assert len(area1) == 1
    assert area1[0].area_type is None


def test_ios_ospf_area_stubby_no_match():
    """area 1 stubby のような非標準語が area_type='stub' に誤マッチしないこと。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.1.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.1.0.0 0.0.0.255 area 1\n"
        " area 1 stubby\n!\n"
    )
    dev, warnings = _parse(text)
    area1 = [o for o in dev.ospf if o.area == "1"]
    assert len(area1) == 1
    assert area1[0].area_type is None


def test_ios_ospf_area_type_last_declaration_wins():
    """同一 area に stub → nssa と再宣言した場合、後者 (nssa) が有効になること（後勝ち決定性）。"""
    text = (
        "hostname X\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.9.0.1 255.255.255.0\n!\n"
        "router ospf 1\n"
        " network 10.9.0.0 0.0.0.255 area 9\n"
        " area 9 stub\n"
        " area 9 nssa\n!\n"
    )
    dev, warnings = _parse(text)
    area9 = [o for o in dev.ospf if o.area == "9"]
    assert len(area9) == 1
    assert area9[0].area_type == "nssa"


# ---------------------------------------------------------------------------
# C4: BGP route-reflector-client / next-hop-self 抽出（IOS）
# ---------------------------------------------------------------------------

def test_ios_bgp_route_reflector_client_extracted():
    """neighbor <ip> route-reflector-client で BgpNeighbor.route_reflector_client=True になること。"""
    text = (
        "hostname RR\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65001\n"
        " neighbor 10.0.0.2 route-reflector-client\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.route_reflector_client is True


def test_ios_bgp_next_hop_self_extracted():
    """neighbor <ip> next-hop-self で BgpNeighbor.next_hop_self=True になること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 next-hop-self\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.next_hop_self is True


def test_ios_bgp_rrc_before_remote_as_order_independent():
    """route-reflector-client が remote-as より前に来ても正しく紐付けられること（順不同保証）。"""
    text = (
        "hostname RR\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 route-reflector-client\n"
        " neighbor 10.0.0.2 remote-as 65001\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.route_reflector_client is True


def test_ios_bgp_nhs_before_remote_as_order_independent():
    """next-hop-self が remote-as より前に来ても正しく紐付けられること（順不同保証）。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 next-hop-self\n"
        " neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.next_hop_self is True


def test_ios_bgp_rrc_only_targets_named_neighbor():
    """route-reflector-client は指定 neighbor のみに True を設定し、他 neighbor は False のままであること（誤適用検出）。"""
    text = (
        "hostname RR\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65001\n"
        " neighbor 10.0.0.2 route-reflector-client\n"
        " neighbor 10.0.0.3 remote-as 65001\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb_map = {n.neighbor_ip: n for n in dev.bgp}
    assert nb_map["10.0.0.2"].route_reflector_client is True
    assert nb_map["10.0.0.3"].route_reflector_client is False


def test_ios_bgp_nhs_only_targets_named_neighbor():
    """next-hop-self は指定 neighbor のみに True を設定し、他 neighbor は False のままであること（誤適用検出）。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 next-hop-self\n"
        " neighbor 10.0.0.3 remote-as 65003\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb_map = {n.neighbor_ip: n for n in dev.bgp}
    assert nb_map["10.0.0.2"].next_hop_self is True
    assert nb_map["10.0.0.3"].next_hop_self is False


def test_ios_bgp_rrc_not_set_defaults_false():
    """route-reflector-client が設定されていない neighbor の route_reflector_client は False であること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.route_reflector_client is False


def test_ios_bgp_nhs_not_set_defaults_false():
    """next-hop-self が設定されていない neighbor の next_hop_self は False であること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.next_hop_self is False


def test_ios_bgp_rrc_and_nhs_combined():
    """route-reflector-client と next-hop-self が同一 neighbor に同時に設定されること。"""
    text = (
        "hostname RR\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65001\n"
        " neighbor 10.0.0.2 route-reflector-client\n"
        " neighbor 10.0.0.2 next-hop-self\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.route_reflector_client is True
    assert nb.next_hop_self is True


def test_ios_bgp_rrc_under_address_family():
    """address-family 配下の neighbor route-reflector-client も拾えること。"""
    text = (
        "hostname RR\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65001\n"
        " address-family ipv4\n"
        "  neighbor 10.0.0.2 route-reflector-client\n"
        " exit-address-family\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.route_reflector_client is True


def test_ios_bgp_nhs_under_address_family_ipv6():
    """address-family ipv6 配下の neighbor next-hop-self で next_hop_self=True が抽出されること。

    rrc の address-family テストはあるが nhs の address-family テストが欠落していたため追加。
    """
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 2001:db8::2 remote-as 65002\n"
        " address-family ipv6\n"
        "  neighbor 2001:db8::2 activate\n"
        "  neighbor 2001:db8::2 next-hop-self\n"
        " exit-address-family\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.next_hop_self is True


# ---------------------------------------------------------------------------
# C4b: timers / send-community 抽出（IOS）+ pending dict 統合
# ---------------------------------------------------------------------------

def test_ios_bgp_timers_extracted():
    """neighbor <ip> timers <ka> <hold> で BgpNeighbor.timers == (ka, hold)（厳密等価）。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 timers 10 30\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.timers == (10, 30)


def test_ios_bgp_timers_before_remote_as_pending():
    """timers 行が remote-as より前に出現しても pending 経由で正しく適用されること（順不同保証）。

    これは統合 pending_attrs が機能していることの証明テスト。
    """
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 timers 10 30\n"
        " neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.timers == (10, 30)


def test_ios_bgp_send_community_both_extracted():
    """neighbor <ip> send-community both で send_community == 'both'（厳密等価）。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 send-community both\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community == "both"


def test_ios_bgp_send_community_plain_defaults_to_standard():
    """引数なし send-community（`neighbor <ip> send-community` のみ）→ 'standard'。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 send-community\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community == "standard"


def test_ios_bgp_send_community_extended_extracted():
    """send-community extended → 'extended'（厳密等価）。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 send-community extended\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community == "extended"


def test_ios_bgp_send_community_standard_explicit():
    """send-community standard → 'standard'（明示指定）。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 send-community standard\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community == "standard"


def test_ios_bgp_send_community_before_remote_as_pending():
    """send-community が remote-as より前に出現しても pending 経由で正しく適用されること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 send-community both\n"
        " neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community == "both"


def test_ios_bgp_timers_none_when_not_configured():
    """timers が設定されていない neighbor の timers は None のままであること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.timers is None


def test_ios_bgp_send_community_none_when_not_configured():
    """send-community が設定されていない neighbor の send_community は None のままであること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community is None


def test_ios_bgp_multiple_neighbors_no_attr_cross_contamination():
    """複数 neighbor で update-source/rr/nhs/timers/send-community が混在しても
    それぞれ正しい neighbor に分離適用されること（取り違え防止・統合 pending 弱くないテスト）。
    """
    text = (
        "hostname RR\n"
        "router bgp 65001\n"
        # neighbor A: timers + rr（remote-as 後）
        " neighbor 10.0.0.2 remote-as 65001\n"
        " neighbor 10.0.0.2 timers 10 30\n"
        " neighbor 10.0.0.2 route-reflector-client\n"
        # neighbor B: send-community + nhs + update-source（remote-as 前）
        " neighbor 10.0.0.3 send-community both\n"
        " neighbor 10.0.0.3 next-hop-self\n"
        " neighbor 10.0.0.3 update-source Loopback0\n"
        " neighbor 10.0.0.3 remote-as 65002\n"
        # neighbor C: timers のみ（remote-as 前）
        " neighbor 10.0.0.4 timers 20 60\n"
        " neighbor 10.0.0.4 remote-as 65003\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb_map = {n.neighbor_ip: n for n in dev.bgp}
    assert set(nb_map.keys()) == {"10.0.0.2", "10.0.0.3", "10.0.0.4"}

    # neighbor A の検証（取り違え: timers/rr が A に、B の属性が混入しないこと）
    a = nb_map["10.0.0.2"]
    assert a.timers == (10, 30)
    assert a.route_reflector_client is True
    assert a.next_hop_self is False
    assert a.send_community is None
    assert a.update_source is None

    # neighbor B の検証
    b = nb_map["10.0.0.3"]
    assert b.send_community == "both"
    assert b.next_hop_self is True
    assert b.update_source == "Loopback0"
    assert b.timers is None
    assert b.route_reflector_client is False

    # neighbor C の検証
    c = nb_map["10.0.0.4"]
    assert c.timers == (20, 60)
    assert c.send_community is None
    assert c.route_reflector_client is False
    assert c.next_hop_self is False


def test_ios_bgp_timers_only_targets_named_neighbor():
    """timers は指定 neighbor のみに適用され、他 neighbor の timers は None のままであること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65001\n"
        " neighbor 10.0.0.2 timers 5 15\n"
        " neighbor 10.0.0.3 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb_map = {n.neighbor_ip: n for n in dev.bgp}
    assert nb_map["10.0.0.2"].timers == (5, 15)
    assert nb_map["10.0.0.3"].timers is None


def test_ios_bgp_send_community_only_targets_named_neighbor():
    """send-community は指定 neighbor のみに適用され、他 neighbor の send_community は None のままであること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65001\n"
        " neighbor 10.0.0.2 send-community extended\n"
        " neighbor 10.0.0.3 remote-as 65002\n!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb_map = {n.neighbor_ip: n for n in dev.bgp}
    assert nb_map["10.0.0.2"].send_community == "extended"
    assert nb_map["10.0.0.3"].send_community is None


# ---------------------------------------------------------------------------
# 修正1: send-community large の silent 誤登録バグ修正テスト（実装壊すと赤）
# ---------------------------------------------------------------------------

def test_ios_bgp_send_community_large_not_registered():
    """send-community large は未対応キーワードのため send_community を設定せず None のままであること。

    修正前は group(2)=None → 'standard' に誤登録していた実バグ。
    このテストは実装を壊すと必ず赤になる（壊すと 'standard' が返り None アサートが失敗）。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 send-community large\n!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: large は未対応のためスキップ → None のまま（'standard' に誤登録しない）
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community is None, (
        f"send-community large は未対応キーワード。'standard' などに誤登録してはならない。"
        f"実際の値: {nb.send_community!r}"
    )


def test_ios_bgp_send_community_large_before_remote_as_not_registered():
    """send-community large が remote-as より前に来ても pending に誤登録しないこと。

    pending 経由で 'standard' 相当で適用されてしまう経路も塞ぐ。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 send-community large\n"
        " neighbor 10.0.0.2 remote-as 65002\n!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community is None, (
        f"send-community large が pending 経由で誤登録された。実際の値: {nb.send_community!r}"
    )


def test_ios_bgp_send_community_valid_after_large_skipped():
    """同じ neighbor に large の後 valid キーワードが来ても、valid だけ正しく登録されること。

    large 行はスキップ（return）のため次の send-community 行で上書きされる想定。
    実際のコンフィグでこの組み合わせは稀だが、スキップが副作用を持たないことを確認。
    """
    # Arrange: large → both の順。large はスキップ、both は登録される
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " neighbor 10.0.0.2 send-community large\n"
        " neighbor 10.0.0.2 send-community both\n!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community == "both", (
        f"large はスキップ後に both が登録されるはず。実際の値: {nb.send_community!r}"
    )


# ---------------------------------------------------------------------------
# 修正6: address-family 配下の timers / send-community 抽出テスト
# ---------------------------------------------------------------------------

def test_ios_bgp_timers_under_address_family():
    """address-family 配下の neighbor timers も _parse_bgp_line を通じて正しく適用されること。

    rrc_under_address_family / nhs_under_address_family_ipv6 と同様の address-family 配下テスト。
    実装は af 配下行も _parse_bgp_line に委譲するため、そこで timers が処理されることを担保。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65001\n"
        " address-family ipv4\n"
        "  neighbor 10.0.0.2 timers 10 30\n"
        " exit-address-family\n!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.timers == (10, 30), (
        f"address-family 配下の timers が適用されていない。実際の値: {nb.timers!r}"
    )


def test_ios_bgp_timers_under_address_family_ipv6():
    """address-family ipv6 配下の v6 neighbor timers も正しく適用されること。"""
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 2001:db8::2 remote-as 65002\n"
        " address-family ipv6\n"
        "  neighbor 2001:db8::2 activate\n"
        "  neighbor 2001:db8::2 timers 5 15\n"
        " exit-address-family\n!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    nb = [n for n in dev.bgp if n.neighbor_ip == "2001:db8::2"][0]
    assert nb.timers == (5, 15), (
        f"address-family ipv6 配下の timers が適用されていない。実際の値: {nb.timers!r}"
    )


def test_ios_bgp_send_community_under_address_family():
    """address-family 配下の neighbor send-community both も正しく適用されること。

    rrc_under_address_family と同様の address-family 配下テスト（send-community 版）。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.2 remote-as 65002\n"
        " address-family ipv4\n"
        "  neighbor 10.0.0.2 send-community both\n"
        " exit-address-family\n!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.send_community == "both", (
        f"address-family 配下の send-community が適用されていない。実際の値: {nb.send_community!r}"
    )


def test_ios_bgp_send_community_under_address_family_ipv6():
    """address-family ipv6 配下の v6 neighbor send-community も正しく適用されること。"""
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 2001:db8::2 remote-as 65002\n"
        " address-family ipv6\n"
        "  neighbor 2001:db8::2 activate\n"
        "  neighbor 2001:db8::2 send-community extended\n"
        " exit-address-family\n!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    nb = [n for n in dev.bgp if n.neighbor_ip == "2001:db8::2"][0]
    assert nb.send_community == "extended", (
        f"address-family ipv6 配下の send-community が適用されていない。実際の値: {nb.send_community!r}"
    )


# ---------------------------------------------------------------------------
# C1b: BGP peer-group 継承（IOS）
# ---------------------------------------------------------------------------

def test_peer_group_inherits_remote_as():
    """peer-group の remote-as がメンバー neighbor に継承されること（厳密等価）。

    IOS: `neighbor PG remote-as 65010` + `neighbor 10.0.0.5 peer-group PG`
    → nb(10.0.0.5).peer_as == 65010, peer_group == "PG"
    実装を壊すと peer_as が None のまま → アサート失敗（壊すと赤）。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65010\n"
        " neighbor 10.0.0.5 peer-group PG\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.neighbor_ip == "10.0.0.5"
    assert nb.peer_as == 65010, (
        f"peer-group PG の remote-as 65010 が継承されていない。実際: {nb.peer_as!r}"
    )
    assert nb.peer_group == "PG", (
        f"peer_group フィールドが設定されていない。実際: {nb.peer_group!r}"
    )


def test_peer_group_member_created_without_individual_remote_as():
    """peer-group メンバー行のみ（個別 remote-as なし）でも BgpNeighbor が生成されること。

    壊すと neighbor 欠落 → len(dev.bgp)==0 で赤。
    """
    # Arrange: メンバー行のみ、個別 remote-as は存在しない
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65020\n"
        " neighbor 10.0.0.6 peer-group PG\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert len(dev.bgp) == 1, (
        f"peer-group メンバー行で BgpNeighbor が生成されるべき。実際の件数: {len(dev.bgp)}"
    )
    assert dev.bgp[0].neighbor_ip == "10.0.0.6"


def test_peer_group_member_override_wins():
    """メンバーが個別 remote-as を持つ場合、template より個別指定が優先されること。

    壊すと個別値 65099 がテンプレート 65010 に上書きされ → アサート失敗（壊すと赤）。
    """
    # Arrange: メンバーに個別 remote-as 65099 があり、template は 65010
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65010\n"
        " neighbor 10.0.0.5 remote-as 65099\n"
        " neighbor 10.0.0.5 peer-group PG\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.peer_as == 65099, (
        f"個別 remote-as 65099 が template 65010 に上書きされた。実際: {nb.peer_as!r}"
    )


def test_peer_group_inherits_update_source_rr_nhs_timers():
    """peer-group template の update-source / rr / nhs / timers / send-community が
    メンバーに継承されること（各属性の厳密等価）。

    壊すと各属性が None/False のまま → アサート失敗（壊すと赤）。
    """
    # Arrange: template に全属性を設定、メンバーは個別指定なし
    text = (
        "hostname RR\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65001\n"
        " neighbor PG update-source Loopback0\n"
        " neighbor PG route-reflector-client\n"
        " neighbor PG next-hop-self\n"
        " neighbor PG timers 10 30\n"
        " neighbor PG send-community both\n"
        " neighbor 10.0.0.5 peer-group PG\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.peer_as == 65001, f"remote_as 継承失敗: {nb.peer_as!r}"
    assert nb.update_source == "Loopback0", f"update_source 継承失敗: {nb.update_source!r}"
    assert nb.route_reflector_client is True, "route_reflector_client 継承失敗"
    assert nb.next_hop_self is True, "next_hop_self 継承失敗"
    assert nb.timers == (10, 30), f"timers 継承失敗: {nb.timers!r}"
    assert nb.send_community == "both", f"send_community 継承失敗: {nb.send_community!r}"


def test_peer_group_unknown_template_no_crash():
    """存在しない peer-group 名を参照しても例外が起きず、peer_as は既存値を維持すること。"""
    # Arrange: PG-GHOST は定義されていない
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.5 remote-as 65002\n"
        " neighbor 10.0.0.5 peer-group PG-GHOST\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: 例外なし、peer_as は個別設定値 65002 を維持
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.peer_as == 65002, f"未定義 PG 参照で peer_as が壊れた: {nb.peer_as!r}"


def test_peer_group_order_independent():
    """peer-group 定義行・属性行・メンバー行が順不同でも継承が成立すること（決定性）。

    属性行 → メンバー行 → 定義行の逆順で来てもテンプレート継承が機能する。
    壊すと pg_template が空でメンバーに継承されない → peer_as==None でアサート失敗。
    """
    # Arrange: メンバー行が最初に来るパターン（最も壊れやすい順序）
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.5 peer-group PG\n"
        " neighbor PG remote-as 65010\n"
        " neighbor PG peer-group\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.peer_as == 65010, f"順不同パターンで継承失敗: {nb.peer_as!r}"
    assert nb.peer_group == "PG"


def test_peer_group_multiple_members():
    """同一 peer-group に複数メンバーがいる場合、全員に継承されること。"""
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65010\n"
        " neighbor PG timers 5 15\n"
        " neighbor 10.0.0.5 peer-group PG\n"
        " neighbor 10.0.0.6 peer-group PG\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    assert len(dev.bgp) == 2
    nb_map = {n.neighbor_ip: n for n in dev.bgp}
    for ip in ("10.0.0.5", "10.0.0.6"):
        assert nb_map[ip].peer_as == 65010
        assert nb_map[ip].peer_group == "PG"
        assert nb_map[ip].timers == (5, 15)


# ---------------------------------------------------------------------------
# C1b 修正: ゾンビ neighbor 排除・逆順・属性優先・重複登録防止・v6
# ---------------------------------------------------------------------------

def test_peer_group_undefined_no_zombie_neighbor():
    """存在しない peer-group 名のみ参照（個別 remote-as なし）→ dev.bgp が空。

    修正前: メンバー行で peer_as=None の BgpNeighbor を即生成→ゾンビが残る。
    修正後: 末尾解決で未定義 PG かつ個別情報なし → BgpNeighbor を生成しない。
    実装を壊すと dev.bgp に peer_as=None のゾンビが残り len==1 でアサート失敗（壊すと赤）。
    """
    # Arrange: GHOST は宣言されていない
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.0.0.5 peer-group GHOST\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert len(dev.bgp) == 0, (
        f"未定義 peer-group のみ参照でゾンビ neighbor が生成された。"
        f"dev.bgp={[(n.neighbor_ip, n.peer_as) for n in dev.bgp]!r}"
    )


def test_peer_group_override_reverse_order():
    """メンバー割当が先・個別 remote-as が後の逆順でも個別値が勝つ。

    IOS 設定例:
      neighbor 10.0.0.5 peer-group PG   ← メンバー割当（先）
      neighbor 10.0.0.5 remote-as 65099 ← 個別 remote-as（後）
    個別 65099 が template 65010 より優先されるべき（個別 > template 厳守）。
    実装を壊すと 65010 が返り アサート失敗（壊すと赤）。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65010\n"
        " neighbor 10.0.0.5 peer-group PG\n"
        " neighbor 10.0.0.5 remote-as 65099\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.peer_as == 65099, (
        f"逆順で個別 remote-as 65099 が template 65010 に上書きされた。実際: {nb.peer_as!r}"
    )
    assert nb.peer_group == "PG"


def test_peer_group_attr_override_wins():
    """メンバーが個別 update-source / timers を持ち template にも別値がある → 個別が勝つ。

    個別指定: update-source Loopback1, timers 3 9
    template:  update-source Loopback0, timers 10 30
    個別 > template を厳守。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65010\n"
        " neighbor PG update-source Loopback0\n"
        " neighbor PG timers 10 30\n"
        " neighbor 10.0.0.5 peer-group PG\n"
        " neighbor 10.0.0.5 update-source Loopback1\n"
        " neighbor 10.0.0.5 timers 3 9\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.update_source == "Loopback1", (
        f"個別 update-source Loopback1 が template Loopback0 に上書きされた。実際: {nb.update_source!r}"
    )
    assert nb.timers == (3, 9), (
        f"個別 timers (3,9) が template (10,30) に上書きされた。実際: {nb.timers!r}"
    )


def test_peer_group_no_double_registration():
    """neighbor remote-as + neighbor peer-group の両指定で BgpNeighbor が1件のみ登録される。

    remote-as 行で生成後にメンバー行で重複生成してはならない。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65010\n"
        " neighbor 10.0.0.5 remote-as 65099\n"
        " neighbor 10.0.0.5 peer-group PG\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    assert len(dev.bgp) == 1, (
        f"BgpNeighbor が重複生成された。実際の件数: {len(dev.bgp)}"
    )


def test_peer_group_ipv6_member():
    """v6 アドレスのメンバー neighbor が PG6 template から peer_as を継承し af=='v6' になる。"""
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG6 peer-group\n"
        " neighbor PG6 remote-as 65020\n"
        " neighbor 2001:db8::5 peer-group PG6\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert warnings == []
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.neighbor_ip == "2001:db8::5"
    assert nb.peer_as == 65020, (
        f"v6 メンバーへの remote-as 継承失敗。実際: {nb.peer_as!r}"
    )
    assert nb.af == "v6", f"af が v6 になっていない。実際: {nb.af!r}"
    assert nb.peer_group == "PG6"


def test_peer_group_member_created_without_individual_remote_as_peer_as_value():
    """test_peer_group_member_created_without_individual_remote_as の強化版。

    peer-group テンプレートの remote-as 65020 が継承されていることを厳密等価で検証。
    元テストは len チェックのみで peer_as 値を検証していなかった（弱さを解消）。
    """
    # Arrange
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor PG remote-as 65020\n"
        " neighbor 10.0.0.6 peer-group PG\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    assert len(dev.bgp) == 1
    nb = dev.bgp[0]
    assert nb.neighbor_ip == "10.0.0.6"
    assert nb.peer_as == 65020, (
        f"peer-group template の remote-as 65020 が継承されていない。実際: {nb.peer_as!r}"
    )


# ---------------------------------------------------------------------------
# 改修②③: IOS interface-level OSPF area パース（ip ospf <pid> area <a>）
# ---------------------------------------------------------------------------

def test_ios_ip_ospf_iface_area():
    """interface 直下 `ip ospf <pid> area <a>` で OspfNetwork(v4) が生成されること。

    IOS-XE モダン形式の interface-level OSPF area 宣言を解析し、
    IF の v4 アドレスからサブネット CIDR を生成して dev.ospf に追加する。
    """
    # Arrange
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.0.1 255.255.255.252\n"
        " ip ospf 1 area 0\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    ospf_v4 = [o for o in dev.ospf if o.af == "v4"]
    assert len(ospf_v4) == 1
    o = ospf_v4[0]
    assert o.process == 1
    assert o.network == "10.0.0.0/30"
    assert o.area == "0"
    assert o.af == "v4"


def test_ios_ip_ospf_iface_area_dotted():
    """ip ospf <pid> area <dotted> のドット表記が norm_ospf_area で正規化されること。

    area 0.0.0.0 → "0"、area 0.0.0.1 → "1" に正規化されることを検証する。
    """
    # Arrange: area 0.0.0.0
    text_zero = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.1.1 255.255.255.252\n"
        " ip ospf 1 area 0.0.0.0\n"
        "!\n"
    )
    # Arrange: area 0.0.0.1
    text_one = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.2.1 255.255.255.252\n"
        " ip ospf 1 area 0.0.0.1\n"
        "!\n"
    )
    # Act
    dev_zero, w_zero = _parse(text_zero)
    dev_one, w_one = _parse(text_one)
    # Assert: 0.0.0.0 → "0"
    ospf_zero = [o for o in dev_zero.ospf if o.af == "v4"]
    assert len(ospf_zero) == 1
    assert ospf_zero[0].area == "0"
    # Assert: 0.0.0.1 → "1"
    ospf_one = [o for o in dev_one.ospf if o.af == "v4"]
    assert len(ospf_one) == 1
    assert ospf_one[0].area == "1"


def test_ios_ip_ospf_iface_no_v4_addr_skipped():
    """v4 address を持たない IF に `ip ospf <pid> area <a>` がある場合、
    OspfNetwork を生成せず、例外も発生せず、warnings に致命的エラーが入らないこと。
    """
    # Arrange: v4 アドレス無し、ipv6 のみ
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ipv6 address 2001:db8::1/64\n"
        " ip ospf 1 area 0\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: OspfNetwork 非生成
    ospf_v4 = [o for o in dev.ospf if o.af == "v4"]
    assert ospf_v4 == []
    # Assert: クラッシュなし・致命的 warning なし（警告一覧に "ip ospf" 関連クラッシュが出ない）
    fatal = [w for w in warnings if "ip ospf" in w and "failed" in w]
    assert fatal == []


def test_ios_ip_ospf_iface_coexist_with_network_stmt():
    """classic `network … area` と IF-level `ip ospf … area` が共存したとき、両方の
    OspfNetwork エントリが dev.ospf に出ること。
    """
    # Arrange
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.0.1 255.255.255.252\n"
        " ip ospf 1 area 0\n"
        "!\n"
        "interface GigabitEthernet0/1\n"
        " ip address 192.168.1.1 255.255.255.0\n"
        "!\n"
        "router ospf 1\n"
        " network 192.168.1.0 0.0.0.255 area 1\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: 両エントリ存在
    networks = {o.network for o in dev.ospf}
    assert "10.0.0.0/30" in networks, "IF-level area エントリが欠落"
    assert "192.168.1.0/24" in networks, "classic network stmt エントリが欠落"
    assert len(dev.ospf) == 2


def test_ios_ipv6_ospf_iface_area_unchanged():
    """`ipv6 ospf <pid> area <a>`（v6）が引き続き正しく動作すること（回帰テスト）。

    IF-level v4 area サポート追加後も v6 の既存動作が変わらないことを確認する。
    """
    # Arrange
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ipv6 address 2001:db8:5::1/64\n"
        " ipv6 ospf 1 area 0\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: v6 エントリが正しく生成されている
    ospf_v6 = [o for o in dev.ospf if o.af == "v6"]
    assert len(ospf_v6) == 1
    o = ospf_v6[0]
    assert o.process == 1
    assert o.network == "2001:db8:5::/64"
    assert o.area == "0"
    assert o.af == "v6"
    # Assert: v4 エントリは生成されない
    ospf_v4 = [o for o in dev.ospf if o.af == "v4"]
    assert ospf_v4 == []


def test_ios_ip_ospf_iface_loopback():
    """Loopback IF の `ip ospf <pid> area <a>` で OspfNetwork が正しく生成されること。

    /32 マスク（255.255.255.255）からネットワーク CIDR "1.1.1.1/32" を生成し、
    後続の build_ospf_stubs がスタブとして拾えるエントリを出力する。
    """
    # Arrange
    text = (
        "hostname R1\n"
        "interface Loopback0\n"
        " ip address 1.1.1.1 255.255.255.255\n"
        " ip ospf 1 area 5\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert
    ospf_v4 = [o for o in dev.ospf if o.af == "v4"]
    assert len(ospf_v4) == 1
    o = ospf_v4[0]
    assert o.process == 1
    assert o.network == "1.1.1.1/32"
    assert o.area == "5"
    assert o.af == "v4"


# ---------------------------------------------------------------------------
# 修正1: _iface_v4_network を sorted_addresses() に統一
# 修正2: 同一 subnet の重複 OspfNetwork を dedup
# 修正3: テスト強化
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_ios_ip_ospf_iface_coexist_with_network_stmt_strict():
    """classic `network … area` と IF-level `ip ospf … area` が共存したとき、
    両方のエントリが dev.ospf に出て、process/area/af まで厳密に検証されること。
    （修正3: 既存 coexist テストの厳密版）
    """
    # Arrange
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.0.1 255.255.255.252\n"
        " ip ospf 1 area 0\n"
        "!\n"
        "interface GigabitEthernet0/1\n"
        " ip address 192.168.1.1 255.255.255.0\n"
        "!\n"
        "router ospf 1\n"
        " network 192.168.1.0 0.0.0.255 area 1\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: 両エントリ存在・process/area/af を厳密検証
    assert len(dev.ospf) == 2
    # IF-level エントリ (10.0.0.0/30)
    if_entry = next((o for o in dev.ospf if o.network == "10.0.0.0/30"), None)
    assert if_entry is not None, "IF-level area エントリが欠落"
    assert if_entry.process == 1
    assert if_entry.area == "0"
    assert if_entry.af == "v4"
    # network 文エントリ (192.168.1.0/24)
    net_entry = next((o for o in dev.ospf if o.network == "192.168.1.0/24"), None)
    assert net_entry is not None, "classic network stmt エントリが欠落"
    assert net_entry.process == 1
    assert net_entry.area == "1"
    assert net_entry.af == "v4"


@pytest.mark.unit
def test_ios_ip_ospf_iface_dedup_same_subnet_as_network_stmt():
    """同一 subnet を `ip ospf 1 area 0`（IF）と `network … area 0`（文）で宣言した場合、
    OspfNetwork が 1 件のみ生成され重複しないこと（修正2: dedup）。

    network 文側のエントリが残る（pending 解決時点で既に dev.ospf にある）。
    """
    # Arrange: 10.0.0.0/30 を IF-level と network 文の両方で宣言
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.0.1 255.255.255.252\n"
        " ip ospf 1 area 0\n"
        "!\n"
        "router ospf 1\n"
        " network 10.0.0.0 0.0.0.3 area 0\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: 重複せず 1 件のみ
    v4_entries = [o for o in dev.ospf if o.af == "v4" and o.network == "10.0.0.0/30"]
    assert len(v4_entries) == 1, (
        f"同一 subnet の OspfNetwork が重複している: {[o.to_dict() for o in dev.ospf]}"
    )
    # network 文側が残る（process/area/af を確認）
    o = v4_entries[0]
    assert o.process == 1
    assert o.area == "0"
    assert o.af == "v4"


@pytest.mark.unit
def test_ios_ip_ospf_iface_cost_and_area_coexist():
    """同一 IF に `ip ospf cost 100` と `ip ospf 1 area 0` を併記した場合、
    cost は iface.ospf["cost"]==100、area は OspfNetwork(1, subnet, "0", "v4") の
    両方が出ること（実機で頻出の組合せ）。（修正3: 新規テスト）
    """
    # Arrange
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.1.0.1 255.255.255.252\n"
        " ip ospf cost 100\n"
        " ip ospf 1 area 0\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: iface.ospf["cost"] == 100
    iface = dev.interfaces[0]
    assert iface.ospf is not None
    assert iface.ospf.get("cost") == 100, f"cost が設定されていない: {iface.ospf}"
    # Assert: OspfNetwork(process=1, network="10.1.0.0/30", area="0", af="v4")
    ospf_v4 = [o for o in dev.ospf if o.af == "v4"]
    assert len(ospf_v4) == 1
    o = ospf_v4[0]
    assert o.process == 1
    assert o.network == "10.1.0.0/30"
    assert o.area == "0"
    assert o.af == "v4"


@pytest.mark.unit
def test_ios_ip_ospf_iface_area_dotted_strict():
    """ip ospf <pid> area <dotted> のドット表記テストで network/process/af も assert する。
    （修正3: 既存 dotted テストに network/process/af 検証を追加した厳密版）
    """
    # Arrange: area 0.0.0.1
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.2.1 255.255.255.252\n"
        " ip ospf 1 area 0.0.0.1\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: area/network/process/af すべて検証
    ospf_v4 = [o for o in dev.ospf if o.af == "v4"]
    assert len(ospf_v4) == 1
    o = ospf_v4[0]
    assert o.area == "1"
    assert o.network == "10.0.2.0/30"
    assert o.process == 1
    assert o.af == "v4"


@pytest.mark.unit
def test_ios_ip_ospf_iface_secondary_only_skipped():
    """v4 が secondary のみ（primary 無し）の IF に `ip ospf 1 area 0` がある場合、
    _iface_v4_network が None を返し OspfNetwork が生成されないこと。（修正3: 新規テスト）

    sorted_addresses() を使っているため、挿入順に関わらず secondary only では
    非 secondary v4 が見つからず None となる。
    """
    # Arrange: secondary のみ（primary v4 なし）
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ip address 10.0.3.2 255.255.255.252 secondary\n"
        " ip ospf 1 area 0\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: OspfNetwork 非生成（secondary のみなので primary subnet が取れない）
    ospf_v4 = [o for o in dev.ospf if o.af == "v4"]
    assert ospf_v4 == [], (
        f"secondary only IF に OspfNetwork が生成されてしまった: {[o.to_dict() for o in dev.ospf]}"
    )


@pytest.mark.unit
def test_ios_ip_ospf_iface_no_v4_addr_skipped_strict():
    """v4 address を持たない IF に `ip ospf <pid> area <a>` がある場合、
    OspfNetwork を生成せず、warnings がゼロであること（修正3: 警告ゼロを厳格化）。
    """
    # Arrange: v4 アドレス無し、ipv6 のみ
    text = (
        "hostname R1\n"
        "interface GigabitEthernet0/0\n"
        " ipv6 address 2001:db8::1/64\n"
        " ip ospf 1 area 0\n"
        "!\n"
    )
    # Act
    dev, warnings = _parse(text)
    # Assert: OspfNetwork 非生成
    ospf_v4 = [o for o in dev.ospf if o.af == "v4"]
    assert ospf_v4 == []
    # Assert: 警告ゼロ（この最小 config では警告は一切出ない）
    assert warnings == []


# ---------------------------------------------------------------------------
# CONFIG parse 状態モード — line_status（実消費行記録・3段階）
# ---------------------------------------------------------------------------

def test_line_status_three_states():
    """line_status に parsed / ignored / unparsed が行ごとに記録されること。"""
    text = (
        "!\n"                              # 0 ignored (comment)
        "hostname R1\n"                    # 1 parsed
        "\n"                               # 2 ignored (blank)
        "interface Gi0/0\n"                # 3 parsed
        " ip address 10.0.0.1 255.255.255.252\n"  # 4 parsed
        " foobar-unknown-command\n"        # 5 unparsed (見落とし候補)
        "!\n"                              # 6 ignored
        "router ospf 1\n"                  # 7 parsed
        " network 192.168.1.0 0.0.0.255 area 0\n"  # 8 parsed
        "end\n"                            # 9 ignored
    )
    ls = []
    parse_ios(text, [], line_status=ls)
    assert len(ls) == len(text.splitlines())
    assert ls[0] == "ignored"
    assert ls[1] == "parsed"
    assert ls[2] == "ignored"
    assert ls[3] == "parsed"
    assert ls[4] == "parsed"
    assert ls[5] == "unparsed"
    assert ls[6] == "ignored"
    assert ls[7] == "parsed"
    assert ls[8] == "parsed"
    assert ls[9] == "ignored"


def test_line_status_optional_no_regression(ios_cfg_text):
    """line_status 未指定時は従来通り Device を返す（モデル出力不変・回帰ガード）。"""
    dev_a = parse_ios(ios_cfg_text, [])
    ls = []
    dev_b = parse_ios(ios_cfg_text, [], line_status=ls)
    # 同一入力 → 同一モデル（to_dict で比較）
    assert dev_a.to_dict() == dev_b.to_dict()
    # line_status は全行分の長さ
    assert len(ls) == len(ios_cfg_text.splitlines())
    assert set(ls) <= {"parsed", "ignored", "unparsed"}


def test_line_status_comment_with_text_is_ignored():
    """`! コメント文`（! の後にテキスト）も ignored 分類されること（unparsed 誤検知を防ぐ）。"""
    text = "! this is a banner comment\nhostname R1\n"
    ls = []
    parse_ios(text, [], line_status=ls)
    assert ls == ["ignored", "parsed"]


# ---------------------------------------------------------------------------
# F: IOS static の Null0 / global キーワード未テスト
# ---------------------------------------------------------------------------

def test_static_route_null0_as_nexthop():
    """`ip route 0.0.0.0 0.0.0.0 Null0` → StaticRoute(next_hop="Null0") が生成されること。"""
    text = "hostname X\nip route 0.0.0.0 0.0.0.0 Null0\n"
    dev, warnings = _parse(text)
    assert warnings == []
    assert len(dev.static) == 1
    s = dev.static[0]
    assert s.prefix == "0.0.0.0/0"
    assert s.next_hop == "Null0"
    assert s.af == "v4"


def test_static_route_global_keyword_skipped():
    """`ip route 10.0.0.0 255.0.0.0 10.0.0.1 global` → global がスキップされ next_hop="10.0.0.1" になること。"""
    text = "hostname X\nip route 10.0.0.0 255.0.0.0 10.0.0.1 global\n"
    dev, warnings = _parse(text)
    assert warnings == []
    assert len(dev.static) == 1
    s = dev.static[0]
    assert s.prefix == "10.0.0.0/8"
    assert s.next_hop == "10.0.0.1"


def test_static_route_null0_with_ad():
    """`ip route 192.168.0.0 255.255.0.0 Null0 254` → next_hop="Null0"、AD 254 は除かれること。"""
    text = "hostname X\nip route 192.168.0.0 255.255.0.0 Null0 254\n"
    dev, warnings = _parse(text)
    assert warnings == []
    s = dev.static[0]
    assert s.next_hop == "Null0"
    assert s.prefix == "192.168.0.0/16"


# ---------------------------------------------------------------------------
# G: IOS address-family vrf 内で既存 neighbor の peer_as 更新時に vrf 未設定
# ---------------------------------------------------------------------------

def test_ios_bgp_vrf_af_sets_vrf_on_existing_neighbor():
    """peer-group で先に生成された neighbor が address-family vrf 内で remote-as 指定されたとき、
    vrf フィールドが正しく設定されること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.1.0.2 remote-as 65002\n"
        " address-family ipv4 vrf RED\n"
        "  neighbor 10.1.0.2 remote-as 65003\n"
        " exit-address-family\n"
        "!\n"
    )
    dev, warnings = _parse(text)
    # address-family vrf RED 内で remote-as が来たとき vrf が設定される
    # 同一 IP が global と VRF 両方に存在する構成（既存 neighbor の vrf 更新）
    nb_list = [n for n in dev.bgp if n.neighbor_ip == "10.1.0.2"]
    # 少なくとも 1 つ存在すること
    assert len(nb_list) >= 1
    # VRF RED 文脈で remote-as が来た neighbor には vrf が設定されること
    vrf_nb = [n for n in nb_list if n.vrf == "RED"]
    assert len(vrf_nb) >= 1, "vrf='RED' の BgpNeighbor が生成されていない"


def test_ios_bgp_vrf_af_existing_neighbor_peer_as_updated_with_vrf():
    """peer-group メンバーとして先に pg_member に登録された neighbor が
    address-family vrf 内で remote-as を受けたとき、vrf と peer_as が正しく設定されること。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor PG peer-group\n"
        " neighbor 10.2.0.2 peer-group PG\n"
        " address-family ipv4 vrf BLUE\n"
        "  neighbor 10.2.0.2 remote-as 65004\n"
        " exit-address-family\n"
        "!\n"
    )
    dev, warnings = _parse(text)
    nb_list = [n for n in dev.bgp if n.neighbor_ip == "10.2.0.2"]
    assert len(nb_list) >= 1
    vrf_nb = [n for n in nb_list if n.vrf == "BLUE"]
    assert len(vrf_nb) >= 1, "vrf='BLUE' の BgpNeighbor が生成されていない"
    assert vrf_nb[0].peer_as == 65004


def test_ios_bgp_global_neighbor_vrf_stays_none():
    """global 文脈（address-family vrf 外）の neighbor は vrf=None のままであること（回帰）。"""
    text = (
        "hostname X\n"
        "router bgp 65001\n"
        " neighbor 10.3.0.2 remote-as 65002\n"
        "!\n"
    )
    dev, warnings = _parse(text)
    assert warnings == []
    nb = dev.bgp[0]
    assert nb.vrf is None
