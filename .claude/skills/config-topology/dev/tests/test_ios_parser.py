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
