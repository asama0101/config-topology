"""#5A VRF モデル・パーサ・build 対応テスト（TDD 先行失敗テスト群）。

実装内容:
  - models.py: Interface/BgpNeighbor/StaticRoute/OspfNetwork に vrf: Optional[str] = None
  - ios.py: IF vrf forwarding / BGP address-family vrf / ip route vrf / ipv6 route vrf
  - junos.py: routing-instances <vrf> interface / static / bgp
  - build.py: 各 build_* で vrf を omit-when-None で転記

不変条件:
  - vrf=None（デフォルト）のとき to_dict()/build の出力に 'vrf' キーが一切出ない（golden byte 不変）。
"""
import pytest

from lib.models import BgpNeighbor, Interface, OspfNetwork, StaticRoute
from lib.parsers.ios import parse_ios
from lib.parsers.junos import parse_junos
from lib.build import build_bgp, build_static, build_ospf, build_devices_interfaces


def _ios(text):
    """parse_ios のラッパー: (dev, warnings) を返す。"""
    w = []
    return parse_ios(text, w), w


def _junos(text):
    """parse_junos のラッパー: (dev, warnings) を返す。"""
    w = []
    return parse_junos(text, w), w

pytestmark = pytest.mark.unit


# ===========================================================================
# 1. モデル: vrf フィールドの omit-when-None テスト
# ===========================================================================

class TestModelVrfOmitWhenNone:
    """全モデルで vrf=None のとき to_dict() に 'vrf' キーが出ない（golden byte 不変）。"""

    def test_interface_vrf_none_omits_key(self):
        iface = Interface(name="Gi0/0")
        d = iface.to_dict()
        assert "vrf" not in d

    def test_interface_vrf_set_appears_in_dict(self):
        iface = Interface(name="Gi0/0", vrf="RED")
        d = iface.to_dict()
        assert d["vrf"] == "RED"

    def test_bgpneighbor_vrf_none_omits_key(self):
        nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
        d = nb.to_dict()
        assert "vrf" not in d
        # 既存キー集合が変わらないこと
        assert set(d.keys()) == {"neighbor_ip", "peer_as", "af"}

    def test_bgpneighbor_vrf_set_appears_in_dict(self):
        nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4", vrf="CUST")
        d = nb.to_dict()
        assert d["vrf"] == "CUST"

    def test_staticroute_vrf_none_omits_key(self):
        sr = StaticRoute(prefix="0.0.0.0/0", next_hop="10.0.0.1", af="v4")
        d = sr.to_dict()
        assert "vrf" not in d
        assert set(d.keys()) == {"prefix", "next_hop", "af"}

    def test_staticroute_vrf_set_appears_in_dict(self):
        sr = StaticRoute(prefix="0.0.0.0/0", next_hop="10.0.0.1", af="v4", vrf="MGMT")
        d = sr.to_dict()
        assert d["vrf"] == "MGMT"

    def test_ospfnetwork_vrf_none_omits_key(self):
        o = OspfNetwork(process=1, network="10.0.0.0/24", area="0", af="v4")
        d = o.to_dict()
        assert "vrf" not in d

    def test_ospfnetwork_vrf_set_appears_in_dict(self):
        o = OspfNetwork(process=1, network="10.0.0.0/24", area="0", af="v4", vrf="VRF_A")
        d = o.to_dict()
        assert d["vrf"] == "VRF_A"


# ===========================================================================
# 2. IOS パーサ: interface vrf forwarding
# ===========================================================================

class TestIosInterfaceVrf:
    """IOS: `ip vrf forwarding <name>` / `vrf forwarding <name>` で Interface.vrf を設定。"""

    def test_ios_iface_ip_vrf_forwarding(self):
        cfg = (
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            " ip vrf forwarding RED\n"
            " ip address 10.1.1.1 255.255.255.0\n"
        )
        dev, _ = _ios(cfg)
        gi = dev.interfaces[0]
        assert gi.vrf == "RED"

    def test_ios_iface_vrf_forwarding_iosxe(self):
        """IOS-XE 形式: `vrf forwarding <name>`"""
        cfg = (
            "hostname R1\n"
            "interface GigabitEthernet0/1\n"
            " vrf forwarding BLUE\n"
            " ip address 10.2.2.1 255.255.255.0\n"
        )
        dev, _ = _ios(cfg)
        gi = dev.interfaces[0]
        assert gi.vrf == "BLUE"

    def test_ios_iface_no_vrf_keyword_gives_none(self):
        """vrf 設定がない IF は vrf=None（golden byte 不変）。"""
        cfg = (
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
        )
        dev, _ = _ios(cfg)
        assert dev.interfaces[0].vrf is None

    def test_ios_iface_vrf_in_to_dict(self):
        """vrf 設定 IF は to_dict() に 'vrf' キーが出ること。"""
        cfg = (
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            " ip vrf forwarding RED\n"
            " ip address 10.1.1.1 255.255.255.0\n"
        )
        dev, _ = _ios(cfg)
        d = dev.interfaces[0].to_dict()
        assert d["vrf"] == "RED"

    def test_ios_global_iface_no_vrf_in_to_dict(self):
        """global IF（vrf なし）の to_dict() に 'vrf' キーが出ないこと（golden byte 不変）。"""
        cfg = (
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
        )
        dev, _ = _ios(cfg)
        d = dev.interfaces[0].to_dict()
        assert "vrf" not in d

    def test_ios_vrf_definition_line_no_crash(self):
        """vrf definition / ip vrf 宣言行でクラッシュしないこと（無害スキップ）。"""
        cfg = (
            "hostname R1\n"
            "vrf definition RED\n"
            " address-family ipv4\n"
            " exit-address-family\n"
            "!\n"
            "ip vrf MGMT\n"
            "!\n"
            "interface Loopback0\n"
            " ip address 1.1.1.1 255.255.255.255\n"
        )
        dev, warnings = _ios(cfg)
        # クラッシュしない・インターフェースが正常にパースされること
        assert dev.hostname == "R1"
        assert len(dev.interfaces) >= 1
        assert dev.interfaces[0].name == "Loopback0"


# ===========================================================================
# 3. IOS パーサ: BGP address-family vrf
# ===========================================================================

class TestIosBgpVrf:
    """IOS: `address-family ipv4 vrf <name>` 配下 neighbor → BgpNeighbor.vrf="<name>"。
    `exit-address-family` 後の neighbor は vrf=None（global）。
    global `address-family ipv4`（vrf 無し）は vrf=None のまま。
    """

    def test_ios_bgp_af_vrf_neighbor_gets_vrf(self):
        cfg = (
            "hostname R1\n"
            "router bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
            " address-family ipv4 vrf RED\n"
            "  neighbor 10.1.1.2 remote-as 65003\n"
            " exit-address-family\n"
        )
        dev, _ = _ios(cfg)
        vrf_nb = next(nb for nb in dev.bgp if nb.neighbor_ip == "10.1.1.2")
        assert vrf_nb.vrf == "RED"

    def test_ios_bgp_global_neighbor_has_no_vrf(self):
        cfg = (
            "hostname R1\n"
            "router bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
            " address-family ipv4 vrf RED\n"
            "  neighbor 10.1.1.2 remote-as 65003\n"
            " exit-address-family\n"
        )
        dev, _ = _ios(cfg)
        global_nb = next(nb for nb in dev.bgp if nb.neighbor_ip == "10.0.0.2")
        assert global_nb.vrf is None

    def test_ios_bgp_exit_af_returns_to_global(self):
        """exit-address-family 後の neighbor は global（vrf=None）。"""
        cfg = (
            "hostname R1\n"
            "router bgp 65001\n"
            " address-family ipv4 vrf RED\n"
            "  neighbor 10.1.1.2 remote-as 65003\n"
            " exit-address-family\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
        )
        dev, _ = _ios(cfg)
        global_nb = next(nb for nb in dev.bgp if nb.neighbor_ip == "10.0.0.2")
        assert global_nb.vrf is None
        vrf_nb = next(nb for nb in dev.bgp if nb.neighbor_ip == "10.1.1.2")
        assert vrf_nb.vrf == "RED"

    def test_ios_bgp_global_af_ipv4_no_vrf_neighbor_none(self):
        """global `address-family ipv4`（vrf 無し）配下 neighbor は vrf=None（golden byte 不変）。"""
        cfg = (
            "hostname R1\n"
            "router bgp 65001\n"
            " address-family ipv4\n"
            "  neighbor 10.0.0.2 remote-as 65002\n"
            " exit-address-family\n"
        )
        dev, _ = _ios(cfg)
        assert len(dev.bgp) == 1
        assert dev.bgp[0].vrf is None

    def test_ios_bgp_af_vrf_to_dict_has_vrf(self):
        """vrf 設定 BgpNeighbor の to_dict() に 'vrf' が出ること。"""
        cfg = (
            "hostname R1\n"
            "router bgp 65001\n"
            " address-family ipv4 vrf RED\n"
            "  neighbor 10.1.1.2 remote-as 65003\n"
            " exit-address-family\n"
        )
        dev, _ = _ios(cfg)
        d = dev.bgp[0].to_dict()
        assert d["vrf"] == "RED"

    def test_ios_bgp_global_to_dict_no_vrf(self):
        """global neighbor の to_dict() に 'vrf' キーが出ないこと（golden byte 不変）。"""
        cfg = (
            "hostname R1\n"
            "router bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
        )
        dev, _ = _ios(cfg)
        d = dev.bgp[0].to_dict()
        assert "vrf" not in d

    def test_ios_bgp_ipv6_af_vrf(self):
        """address-family ipv6 vrf でも vrf が設定されること。"""
        cfg = (
            "hostname R1\n"
            "router bgp 65001\n"
            " address-family ipv6 vrf BLUE\n"
            "  neighbor 2001:db8::2 remote-as 65002\n"
            " exit-address-family\n"
        )
        dev, _ = _ios(cfg)
        assert len(dev.bgp) == 1
        assert dev.bgp[0].vrf == "BLUE"


# ===========================================================================
# 4. IOS パーサ: ip route vrf / ipv6 route vrf
# ===========================================================================

class TestIosStaticVrf:
    """IOS: `ip route vrf <name> <net> <mask> <nh>` → StaticRoute.vrf="<name>"。"""

    def test_ios_ip_route_vrf_v4(self):
        cfg = (
            "hostname R1\n"
            "ip route vrf RED 10.100.0.0 255.255.0.0 10.1.1.254\n"
        )
        dev, _ = _ios(cfg)
        assert len(dev.static) == 1
        sr = dev.static[0]
        assert sr.vrf == "RED"
        assert sr.af == "v4"
        assert sr.prefix == "10.100.0.0/16"
        assert sr.next_hop == "10.1.1.254"

    def test_ios_ip_route_vrf_v6(self):
        cfg = (
            "hostname R1\n"
            "ipv6 route vrf BLUE ::/0 2001:db8::1\n"
        )
        dev, _ = _ios(cfg)
        assert len(dev.static) == 1
        sr = dev.static[0]
        assert sr.vrf == "BLUE"
        assert sr.af == "v6"

    def test_ios_global_ip_route_no_vrf(self):
        """global `ip route ...`（vrf なし）は vrf=None（golden byte 不変）。"""
        cfg = (
            "hostname R1\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.1\n"
        )
        dev, _ = _ios(cfg)
        assert len(dev.static) == 1
        assert dev.static[0].vrf is None

    def test_ios_ip_route_vrf_to_dict_has_vrf(self):
        cfg = (
            "hostname R1\n"
            "ip route vrf RED 10.100.0.0 255.255.0.0 10.1.1.254\n"
        )
        dev, _ = _ios(cfg)
        d = dev.static[0].to_dict()
        assert d["vrf"] == "RED"

    def test_ios_global_ip_route_to_dict_no_vrf(self):
        cfg = (
            "hostname R1\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.1\n"
        )
        dev, _ = _ios(cfg)
        d = dev.static[0].to_dict()
        assert "vrf" not in d

    def test_ios_ip_route_vrf_with_ad(self):
        """vrf 付き static に AD が続いても正しく next-hop を取得すること。"""
        cfg = (
            "hostname R1\n"
            "ip route vrf RED 192.168.99.0 255.255.255.0 10.1.1.254 200\n"
        )
        dev, _ = _ios(cfg)
        sr = dev.static[0]
        assert sr.vrf == "RED"
        assert sr.next_hop == "10.1.1.254"


# ===========================================================================
# 5. JunOS パーサ: routing-instances
# ===========================================================================

class TestJunosRoutingInstances:
    """JunOS: routing-instances <vrf> ...  ハンドラ群。"""

    # --- static ---

    def test_junos_ri_static_next_hop(self):
        """routing-instances CUST routing-options static route → StaticRoute.vrf='CUST'。"""
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST routing-options static route 10.100.0.0/16"
            " next-hop 10.1.1.254\n"
        )
        dev, _ = _junos(cfg)
        assert len(dev.static) == 1
        sr = dev.static[0]
        assert sr.vrf == "CUST"
        assert sr.af == "v4"
        assert sr.prefix == "10.100.0.0/16"
        assert sr.next_hop == "10.1.1.254"

    def test_junos_ri_static_discard(self):
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST routing-options static route 0.0.0.0/0 discard\n"
        )
        dev, _ = _junos(cfg)
        assert len(dev.static) == 1
        sr = dev.static[0]
        assert sr.vrf == "CUST"
        assert sr.next_hop == "discard"

    def test_junos_ri_static_reject(self):
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST routing-options static route 192.168.0.0/16 reject\n"
        )
        dev, _ = _junos(cfg)
        sr = dev.static[0]
        assert sr.vrf == "CUST"
        assert sr.next_hop == "reject"

    def test_junos_ri_static_qualified_next_hop(self):
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST routing-options static route 10.0.0.0/8"
            " qualified-next-hop 192.168.1.1\n"
        )
        dev, _ = _junos(cfg)
        sr = dev.static[0]
        assert sr.vrf == "CUST"
        assert sr.next_hop == "192.168.1.1"

    def test_junos_ri_static_v6_next_hop(self):
        """routing-instances <vrf> routing-options rib <vrf>.inet6.0 static → StaticRoute.vrf。"""
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST routing-options rib CUST.inet6.0 static route"
            " ::/0 next-hop 2001:db8::1\n"
        )
        dev, _ = _junos(cfg)
        assert len(dev.static) == 1
        sr = dev.static[0]
        assert sr.vrf == "CUST"
        assert sr.af == "v6"

    def test_junos_ri_static_to_dict_has_vrf(self):
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST routing-options static route 10.100.0.0/16"
            " next-hop 10.1.1.254\n"
        )
        dev, _ = _junos(cfg)
        d = dev.static[0].to_dict()
        assert d["vrf"] == "CUST"

    def test_junos_global_static_no_vrf(self):
        """global static（routing-instances 接頭なし）は vrf=None（golden byte 不変）。"""
        cfg = (
            "set system host-name R2\n"
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1\n"
        )
        dev, _ = _junos(cfg)
        assert dev.static[0].vrf is None

    def test_junos_global_static_to_dict_no_vrf(self):
        cfg = (
            "set system host-name R2\n"
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1\n"
        )
        dev, _ = _junos(cfg)
        d = dev.static[0].to_dict()
        assert "vrf" not in d

    # --- bgp ---

    def test_junos_ri_bgp_neighbor_gets_vrf(self):
        """routing-instances CUST protocols bgp → BgpNeighbor.vrf='CUST'。"""
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST protocols bgp group EXT neighbor 10.1.1.2 peer-as 65003\n"
        )
        dev, _ = _junos(cfg)
        assert len(dev.bgp) == 1
        nb = dev.bgp[0]
        assert nb.vrf == "CUST"
        assert nb.peer_as == 65003

    def test_junos_ri_bgp_to_dict_has_vrf(self):
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST protocols bgp group EXT neighbor 10.1.1.2 peer-as 65003\n"
        )
        dev, _ = _junos(cfg)
        d = dev.bgp[0].to_dict()
        assert d["vrf"] == "CUST"

    def test_junos_global_bgp_no_vrf(self):
        """global protocols bgp（routing-instances 接頭なし）は vrf=None（golden byte 不変）。"""
        cfg = (
            "set system host-name R2\n"
            "set protocols bgp group INT neighbor 10.0.0.1 peer-as 65001\n"
        )
        dev, _ = _junos(cfg)
        assert dev.bgp[0].vrf is None

    def test_junos_global_bgp_to_dict_no_vrf(self):
        cfg = (
            "set system host-name R2\n"
            "set protocols bgp group INT neighbor 10.0.0.1 peer-as 65001\n"
        )
        dev, _ = _junos(cfg)
        d = dev.bgp[0].to_dict()
        assert "vrf" not in d

    def test_junos_ri_bgp_group_peer_as_inherited(self):
        """routing-instances <vrf> の group レベル peer-as も vrf 継承されること。"""
        cfg = (
            "set system host-name R2\n"
            "set routing-instances CUST protocols bgp group EXT peer-as 65099\n"
            "set routing-instances CUST protocols bgp group EXT neighbor 10.1.1.2\n"
        )
        dev, _ = _junos(cfg)
        assert len(dev.bgp) == 1
        nb = dev.bgp[0]
        assert nb.vrf == "CUST"
        assert nb.peer_as == 65099

    # --- interface ---

    def test_junos_ri_interface_gets_vrf(self):
        """routing-instances CUST interface ge-0/0/1.0 → Interface("ge-0/0/1").vrf='CUST'。"""
        cfg = (
            "set system host-name R2\n"
            "set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/30\n"
            "set routing-instances CUST interface ge-0/0/1.0\n"
        )
        dev, _ = _junos(cfg)
        iface = next(i for i in dev.interfaces if i.name == "ge-0/0/1")
        assert iface.vrf == "CUST"

    def test_junos_ri_interface_to_dict_has_vrf(self):
        cfg = (
            "set system host-name R2\n"
            "set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/30\n"
            "set routing-instances CUST interface ge-0/0/1.0\n"
        )
        dev, _ = _junos(cfg)
        iface = next(i for i in dev.interfaces if i.name == "ge-0/0/1")
        d = iface.to_dict()
        assert d["vrf"] == "CUST"

    def test_junos_global_interface_no_vrf(self):
        """routing-instances 配下に置かれていない IF は vrf=None（golden byte 不変）。"""
        cfg = (
            "set system host-name R2\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30\n"
        )
        dev, _ = _junos(cfg)
        assert dev.interfaces[0].vrf is None

    def test_junos_global_interface_to_dict_no_vrf(self):
        cfg = (
            "set system host-name R2\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30\n"
        )
        dev, _ = _junos(cfg)
        d = dev.interfaces[0].to_dict()
        assert "vrf" not in d

    def test_junos_ri_mixed_global_and_vrf(self):
        """global IF と VRF IF が混在するとき、それぞれが正しく分類されること。"""
        cfg = (
            "set system host-name R2\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30\n"
            "set interfaces ge-0/0/1 unit 0 family inet address 10.1.1.1/30\n"
            "set routing-instances CUST interface ge-0/0/1.0\n"
        )
        dev, _ = _junos(cfg)
        ge0 = next(i for i in dev.interfaces if i.name == "ge-0/0/0")
        ge1 = next(i for i in dev.interfaces if i.name == "ge-0/0/1")
        assert ge0.vrf is None
        assert ge1.vrf == "CUST"


# ===========================================================================
# 6. build: vrf の omit-when-None 転記テスト
# ===========================================================================

class TestBuildVrf:
    """build_bgp / build_static / build_ospf の各出力エントリに vrf を omit-when-None で転記。"""

    def _dev(self, hostname, asn=None):
        from lib.models import Device
        return Device(hostname=hostname, vendor="cisco_ios", as_=asn)

    def test_build_bgp_vrf_omit_when_none(self):
        """vrf=None の BgpNeighbor は build_bgp エントリに 'vrf' キーが出ない。"""
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios", as_=65001)
        dev.bgp = [BgpNeighbor("10.0.0.2", 65002, "v4")]
        entries = build_bgp([("r1", dev)])
        assert "vrf" not in entries[0]

    def test_build_bgp_vrf_appears_when_set(self):
        """vrf="RED" の BgpNeighbor は build_bgp エントリに 'vrf': 'RED' が出る。"""
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios", as_=65001)
        dev.bgp = [BgpNeighbor("10.1.1.2", 65003, "v4", vrf="RED")]
        dev.interfaces = []
        entries = build_bgp([("r1", dev)])
        assert entries[0]["vrf"] == "RED"

    def test_build_static_vrf_omit_when_none(self):
        """vrf=None の StaticRoute は build_static エントリに 'vrf' キーが出ない。"""
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.static = [StaticRoute("0.0.0.0/0", "10.0.0.1", "v4")]
        entries = build_static([("r1", dev)])
        assert "vrf" not in entries[0]

    def test_build_static_vrf_appears_when_set(self):
        """vrf="RED" の StaticRoute は build_static エントリに 'vrf': 'RED' が出る。"""
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.static = [StaticRoute("10.100.0.0/16", "10.1.1.254", "v4", vrf="RED")]
        entries = build_static([("r1", dev)])
        assert entries[0]["vrf"] == "RED"

    def test_build_ospf_vrf_omit_when_none(self):
        """vrf=None の OspfNetwork は build_ospf エントリに 'vrf' キーが出ない。"""
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.ospf = [OspfNetwork(1, "10.0.0.0/24", "0", "v4")]
        entries = build_ospf([("r1", dev)])
        assert "vrf" not in entries[0]

    def test_build_ospf_vrf_appears_when_set(self):
        """vrf="VRF_A" の OspfNetwork は build_ospf エントリに 'vrf': 'VRF_A' が出る。"""
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.ospf = [OspfNetwork(1, "10.0.0.0/24", "0", "v4", vrf="VRF_A")]
        entries = build_ospf([("r1", dev)])
        assert entries[0]["vrf"] == "VRF_A"

    def test_build_devices_interfaces_vrf_omit_when_none(self):
        """vrf=None の Interface は build_devices_interfaces の interfaces エントリに 'vrf' キーが出ない。"""
        from lib.models import Device, Address
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.interfaces = [Interface(name="Gi0/0",
                                    addresses=[Address("v4", "10.0.0.1", 30)])]
        _, _, interfaces = build_devices_interfaces([dev])
        assert "vrf" not in interfaces[0]

    def test_build_devices_interfaces_vrf_appears_when_set(self):
        """vrf="RED" の Interface は build_devices_interfaces の interfaces エントリに 'vrf': 'RED' が出る。"""
        from lib.models import Device, Address
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.interfaces = [Interface(name="Gi0/0",
                                    addresses=[Address("v4", "10.0.0.1", 30)],
                                    vrf="RED")]
        _, _, interfaces = build_devices_interfaces([dev])
        assert interfaces[0]["vrf"] == "RED"


# ===========================================================================
# 7. global-only config（golden byte 不変の回帰テスト）
# ===========================================================================

class TestGlobalOnlyNoVrfKey:
    """既存 global-only config の出力に 'vrf' キーが一切混入しないこと。"""

    def test_ios_no_vrf_in_any_output(self):
        cfg = (
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
            "router bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
            "ip route 0.0.0.0 0.0.0.0 10.0.0.2\n"
        )
        dev, _ = _ios(cfg)
        # Interface to_dict
        for iface in dev.interfaces:
            assert "vrf" not in iface.to_dict(), f"{iface.name} に vrf キーが混入"
        # BgpNeighbor to_dict
        for nb in dev.bgp:
            assert "vrf" not in nb.to_dict(), f"bgp neighbor {nb.neighbor_ip} に vrf キーが混入"
        # StaticRoute to_dict
        for sr in dev.static:
            assert "vrf" not in sr.to_dict(), f"static {sr.prefix} に vrf キーが混入"

    def test_junos_no_vrf_in_any_output(self):
        cfg = (
            "set system host-name R2\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30\n"
            "set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1\n"
            "set protocols bgp group INT neighbor 10.0.0.1 peer-as 65001\n"
        )
        dev, _ = _junos(cfg)
        for iface in dev.interfaces:
            assert "vrf" not in iface.to_dict(), f"{iface.name} に vrf キーが混入"
        for nb in dev.bgp:
            assert "vrf" not in nb.to_dict(), f"bgp neighbor {nb.neighbor_ip} に vrf キーが混入"
        for sr in dev.static:
            assert "vrf" not in sr.to_dict(), f"static {sr.prefix} に vrf キーが混入"
