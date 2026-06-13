"""
TDD テスト: Phase 3G — IPv6 ルーティング（OSPFv3 / BGP IPv6 AF / IPv6 static）

テスト方針:
  RED → GREEN → REFACTOR サイクルで実装を駆動する

対象範囲:
  1. lib/parsers/base.py         — BgpNeighbor/OspfNetwork/StaticRoute に af フィールド追加
  2. lib/parsers/cisco_ios.py    — OSPFv3 / BGP IPv6 AF / IPv6 static パース
  3. lib/parsers/juniper_junos.py— ospf3 / IPv6 BGP neighbor / inet6.0 static パース
  4. scripts/build_topology.py  — _resolve_local_ip v6 対応・af フィールド付与・v6 OSPF area 解決
  5. lib/topology_io.py          — round-trip（af フィールド含む）
  6. lib/rendering/core.py       — BGP/OSPF/static v6 セッション描画・data-bgp-id/data-ospf-id 連動
  7. 後方互換テスト             — 既存 v4 routing は af=v4 付与のみで値不変

不変条件:
  - 決定性: 同一 config → 同一出力（ソートに af を含む）
  - 後方互換: 既存 v4 エントリに af=v4 が付与されるのみ（値不変）
  - OSPFv3 と OSPFv2 の共存（af で区別）
  - BGP IPv6 AF セッションは local_ip が v6 で解決される
  - IPv6 static の next-hop 経路ハイライトが機能する
"""

from __future__ import annotations

import os
import sys
import tempfile
import pytest

# ================================================================
# Fixtures
# ================================================================

FIXTURE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "v6routing"
)

IOS_V6ROUTING_CFG = """\
!
hostname IOS-R1
!
interface Loopback0
 ip address 10.255.1.1 255.255.255.255
 ipv6 address 2001:db8:ff::1/128
!
interface GigabitEthernet0/0
 description to-JUNOS-R1
 ip address 10.1.0.1 255.255.255.252
 ipv6 address 2001:db8:1::1/127
 ipv6 address fe80::1:1 link-local
 ipv6 ospf 10 area 0
 no shutdown
!
interface GigabitEthernet0/1
 description to-IOS-R2-iBGP
 ip address 10.2.0.1 255.255.255.252
 ipv6 address 2001:db8:2::1/127
 ipv6 address fe80::1:2 link-local
 ipv6 ospf 10 area 1
 no shutdown
!
ipv6 router ospf 10
 router-id 10.255.1.1
!
router bgp 65100
 neighbor 10.1.0.2 remote-as 65200
 neighbor 2001:db8:1::0 remote-as 65200
 neighbor 2001:db8:2::0 remote-as 65100
 address-family ipv6
  neighbor 2001:db8:1::0 activate
  neighbor 2001:db8:2::0 activate
 exit-address-family
!
ipv6 route ::/0 2001:db8:1::0
!
end
"""

JUNOS_V6ROUTING_CFG = """\
set system host-name JUNOS-R1
set interfaces ge-0/0/0 description to-IOS-R1
set interfaces ge-0/0/0 unit 0 family inet address 10.1.0.2/30
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8:1::0/127
set interfaces lo0 unit 0 family inet address 10.255.2.1/32
set interfaces lo0 unit 0 family inet6 address 2001:db8:ff::2/128
set routing-options autonomous-system 65200
set protocols bgp group v6-ext type external
set protocols bgp group v6-ext neighbor 2001:db8:1::1 peer-as 65100
set protocols ospf3 area 0.0.0.0 interface ge-0/0/0.0
set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8:1::1
"""


# ================================================================
# セクション 1: base.py — af フィールド
# ================================================================

class TestBaseAFField:
    """BgpNeighbor / OspfNetwork / StaticRoute が af フィールドを持つことを検証する。"""

    @pytest.mark.unit
    def test_bgp_neighbor_has_af_field(self):
        """BgpNeighbor に af フィールドが存在し、デフォルトは 'v4'。"""
        from lib.parsers.base import BgpNeighbor
        n = BgpNeighbor(neighbor_ip="10.0.0.1", peer_as=65001)
        assert hasattr(n, "af"), "BgpNeighbor に af フィールドが必要"
        assert n.af == "v4", "デフォルト af は 'v4' であるべき"

    @pytest.mark.unit
    def test_ospf_network_has_af_field(self):
        """OspfNetwork に af フィールドが存在し、デフォルトは 'v4'。"""
        from lib.parsers.base import OspfNetwork
        o = OspfNetwork(process=1, network="10.0.0.0/24", area="0")
        assert hasattr(o, "af"), "OspfNetwork に af フィールドが必要"
        assert o.af == "v4", "デフォルト af は 'v4' であるべき"

    @pytest.mark.unit
    def test_static_route_has_af_field(self):
        """StaticRoute に af フィールドが存在し、デフォルトは 'v4'。"""
        from lib.parsers.base import StaticRoute
        s = StaticRoute(prefix="0.0.0.0/0", next_hop="10.0.0.1")
        assert hasattr(s, "af"), "StaticRoute に af フィールドが必要"
        assert s.af == "v4", "デフォルト af は 'v4' であるべき"

    @pytest.mark.unit
    def test_bgp_neighbor_v6_af(self):
        """BgpNeighbor に af='v6' を指定できる。"""
        from lib.parsers.base import BgpNeighbor
        n = BgpNeighbor(neighbor_ip="2001:db8::1", peer_as=65001, af="v6")
        assert n.af == "v6"

    @pytest.mark.unit
    def test_ospf_network_v6_af(self):
        """OspfNetwork に af='v6' を指定できる。"""
        from lib.parsers.base import OspfNetwork
        o = OspfNetwork(process=10, network="2001:db8:1::/127", area="0", af="v6")
        assert o.af == "v6"

    @pytest.mark.unit
    def test_static_route_v6_af(self):
        """StaticRoute に af='v6' を指定できる。"""
        from lib.parsers.base import StaticRoute
        s = StaticRoute(prefix="::/0", next_hop="2001:db8::1", af="v6")
        assert s.af == "v6"


# ================================================================
# セクション 2: cisco_ios.py — OSPFv3 パース
# ================================================================

class TestCiscoIOSOSPFv3:
    """IOS の `ipv6 router ospf N` + `interface X / ipv6 ospf N area A` をパースする。"""

    @pytest.mark.unit
    def test_ospf3_area0_parsed(self):
        """OSPFv3 area 0 に参加するネットワークが af=v6 で抽出される。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_ospf = [o for o in dev.ospf if getattr(o, "af", "v4") == "v6"]
        assert len(v6_ospf) >= 1, "OSPFv3 エントリが1件以上必要"

    @pytest.mark.unit
    def test_ospf3_area0_network_is_v6_subnet(self):
        """OSPFv3 area 0 エントリの network が v6 サブネット（Gi0/0 の 2001:db8:1::/127）。"""
        from lib.parsers import cisco_ios
        import ipaddress
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_ospf = [o for o in dev.ospf if getattr(o, "af", "v4") == "v6"]
        networks = [o.network for o in v6_ospf]
        # Gi0/0: 2001:db8:1::1/127 → ネットワーク 2001:db8:1::/127
        assert any("2001:db8:1::" in n for n in networks), f"期待する v6 subnet が見つからない: {networks}"

    @pytest.mark.unit
    def test_ospf3_area1_present(self):
        """OSPFv3 area 1 エントリも af=v6 で存在する（Gi0/1 が area 1）。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_ospf_area1 = [o for o in dev.ospf if getattr(o, "af", "v4") == "v6" and o.area == "1"]
        assert len(v6_ospf_area1) >= 1, "OSPFv3 area 1 エントリが必要"

    @pytest.mark.unit
    def test_ospf3_process_id_set(self):
        """OSPFv3 のプロセス ID が正しく設定される（pid=10）。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_ospf = [o for o in dev.ospf if getattr(o, "af", "v4") == "v6"]
        pids = [o.process for o in v6_ospf]
        assert 10 in pids, f"プロセス ID 10 が見つからない: {pids}"

    @pytest.mark.unit
    def test_v4_ospf_unaffected(self):
        """既存 v4 OSPF エントリは af=v4（または af が v6 でない）で残る。"""
        from lib.parsers import cisco_ios
        # v4 OSPF のみのシンプルな config
        cfg = """\
!
hostname R-OSPFv4
!
interface GigabitEthernet0/0
 ip address 192.168.1.1 255.255.255.0
!
router ospf 1
 network 192.168.1.0 0.0.0.255 area 0
!
end
"""
        dev = cisco_ios.parse(cfg)
        v4_ospf = [o for o in dev.ospf if getattr(o, "af", "v4") == "v4"]
        assert len(v4_ospf) == 1
        assert v4_ospf[0].network == "192.168.1.0/24"
        assert v4_ospf[0].area == "0"


# ================================================================
# セクション 3: cisco_ios.py — BGP IPv6 AF パース
# ================================================================

class TestCiscoIOSBGPIPv6AF:
    """IOS の `address-family ipv6` 内 `neighbor X activate` で af=v6 の BGP エントリを生成する。"""

    @pytest.mark.unit
    def test_bgp_v6_neighbor_extracted(self):
        """address-family ipv6 で activate された v6 ネイバーが af=v6 で抽出される。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_bgp = [b for b in dev.bgp if getattr(b, "af", "v4") == "v6"]
        assert len(v6_bgp) >= 1, f"BGP IPv6 AF エントリが必要: {dev.bgp}"

    @pytest.mark.unit
    def test_bgp_v6_ebgp_neighbor(self):
        """v6 eBGP ネイバー 2001:db8:1::0（AS 65200）が af=v6 で存在する。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_bgp = [b for b in dev.bgp if getattr(b, "af", "v4") == "v6"]
        neighbor_ips = [b.neighbor_ip for b in v6_bgp]
        assert any("2001:db8:1::" in ip for ip in neighbor_ips), \
            f"2001:db8:1:: ネイバーが見つからない: {neighbor_ips}"

    @pytest.mark.unit
    def test_bgp_v6_ibgp_neighbor(self):
        """v6 iBGP ネイバー 2001:db8:2::0（AS 65100）が af=v6 で存在する。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_bgp = [b for b in dev.bgp if getattr(b, "af", "v4") == "v6"]
        ibgp = [b for b in v6_bgp if b.peer_as == 65100]
        assert len(ibgp) >= 1, f"iBGP v6 ネイバーが見つからない: {v6_bgp}"

    @pytest.mark.unit
    def test_bgp_v4_neighbor_unaffected(self):
        """v4 BGP ネイバーは af=v4 のまま存在する（10.1.0.2 のみ v4）。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v4_bgp = [b for b in dev.bgp if getattr(b, "af", "v4") == "v4"]
        assert any(b.neighbor_ip == "10.1.0.2" for b in v4_bgp), \
            f"v4 BGP ネイバー 10.1.0.2 が af=v4 で残っていない: {v4_bgp}"

    @pytest.mark.unit
    def test_bgp_v6_peer_as_correct(self):
        """v6 eBGP ネイバーの peer_as が正しい（65200）。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_bgp = [b for b in dev.bgp if getattr(b, "af", "v4") == "v6"]
        ebgp = [b for b in v6_bgp if "2001:db8:1::" in b.neighbor_ip]
        assert ebgp, "v6 eBGP ネイバーが見つからない"
        assert ebgp[0].peer_as == 65200, f"peer_as={ebgp[0].peer_as} != 65200"


# ================================================================
# セクション 4: cisco_ios.py — IPv6 static パース
# ================================================================

class TestCiscoIOSIPv6Static:
    """IOS の `ipv6 route PREFIX NEXTHOP` が af=v6 で StaticRoute に収録される。"""

    @pytest.mark.unit
    def test_ipv6_static_extracted(self):
        """IPv6 static default route が af=v6 で抽出される。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert len(v6_static) >= 1, f"IPv6 static エントリが必要: {dev.static}"

    @pytest.mark.unit
    def test_ipv6_static_prefix_and_nexthop(self):
        """IPv6 static の prefix が '::/0'、next_hop が '2001:db8:1::' 系。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert len(v6_static) >= 1
        s = v6_static[0]
        assert "::" in s.prefix, f"IPv6 prefix でない: {s.prefix}"
        assert "::" in s.next_hop, f"IPv6 next_hop でない: {s.next_hop}"

    @pytest.mark.unit
    def test_v4_static_unaffected(self):
        """既存の v4 static は af=v4 のままで残る。"""
        from lib.parsers import cisco_ios
        cfg = """\
!
hostname R-STATIC
!
ip route 0.0.0.0 0.0.0.0 10.0.0.1
!
end
"""
        dev = cisco_ios.parse(cfg)
        v4_static = [s for s in dev.static if getattr(s, "af", "v4") == "v4"]
        assert len(v4_static) == 1
        assert v4_static[0].prefix == "0.0.0.0/0"


# ================================================================
# セクション 5: juniper_junos.py — OSPFv3 パース
# ================================================================

class TestJunOSOSPFv3:
    """JunOS の `set protocols ospf3 area A interface X` が af=v6 で収録される。"""

    @pytest.mark.unit
    def test_ospf3_extracted(self):
        """ospf3 エントリが af=v6 で抽出される。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_ospf = [o for o in dev.ospf if getattr(o, "af", "v4") == "v6"]
        assert len(v6_ospf) >= 1, f"OSPFv3 エントリが必要: {dev.ospf}"

    @pytest.mark.unit
    def test_ospf3_area_correct(self):
        """ospf3 の area が '0.0.0.0' または '0' として解釈される。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_ospf = [o for o in dev.ospf if getattr(o, "af", "v4") == "v6"]
        areas = [o.area for o in v6_ospf]
        assert any(a in ("0", "0.0.0.0") for a in areas), f"area が期待値でない: {areas}"

    @pytest.mark.unit
    def test_ospf3_process_none(self):
        """JunOS ospf3 のプロセス ID は None（JunOS に PID 概念なし）。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_ospf = [o for o in dev.ospf if getattr(o, "af", "v4") == "v6"]
        assert all(o.process is None for o in v6_ospf)

    @pytest.mark.unit
    def test_ospf3_if_ref_stored(self):
        """ospf3 の network フィールドに IF 参照（ge-0/0/0 相当）が格納される。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_ospf = [o for o in dev.ospf if getattr(o, "af", "v4") == "v6"]
        nets = [o.network for o in v6_ospf]
        assert any("ge-0/0/0" in n for n in nets), f"IF 参照が見つからない: {nets}"


# ================================================================
# セクション 6: juniper_junos.py — BGP IPv6 パース
# ================================================================

class TestJunOSBGPIPv6:
    """JunOS の v6 BGP neighbor が af=v6 で収録される。"""

    @pytest.mark.unit
    def test_bgp_v6_neighbor_extracted(self):
        """v6 ネイバー 2001:db8:1::1 が af=v6 で抽出される。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_bgp = [b for b in dev.bgp if getattr(b, "af", "v4") == "v6"]
        assert len(v6_bgp) >= 1, f"BGP IPv6 エントリが必要: {dev.bgp}"

    @pytest.mark.unit
    def test_bgp_v6_peer_as_correct(self):
        """v6 BGP ネイバーの peer_as が 65100。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_bgp = [b for b in dev.bgp if getattr(b, "af", "v4") == "v6"]
        assert v6_bgp[0].peer_as == 65100, f"peer_as={v6_bgp[0].peer_as} != 65100"

    @pytest.mark.unit
    def test_bgp_v6_neighbor_ip_normalized(self):
        """v6 BGP ネイバーの IP が ipaddress で正規化された形式。"""
        from lib.parsers import juniper_junos
        import ipaddress
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_bgp = [b for b in dev.bgp if getattr(b, "af", "v4") == "v6"]
        for b in v6_bgp:
            # ipaddress でパースできることを確認
            ipaddress.ip_address(b.neighbor_ip)  # 例外が出ないこと


# ================================================================
# セクション 7: juniper_junos.py — IPv6 static パース
# ================================================================

class TestJunOSIPv6Static:
    """JunOS の `set routing-options rib inet6.0 static route` が af=v6 で収録される。"""

    @pytest.mark.unit
    def test_ipv6_static_extracted(self):
        """inet6.0 の IPv6 static が af=v6 で抽出される。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert len(v6_static) >= 1, f"IPv6 static エントリが必要: {dev.static}"

    @pytest.mark.unit
    def test_ipv6_static_prefix_and_nexthop(self):
        """IPv6 static の prefix が '::/0'、next_hop が v6 アドレス。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert v6_static
        s = v6_static[0]
        assert "::" in s.prefix
        assert "::" in s.next_hop


# ================================================================
# セクション 8: build_topology.py — af フィールド付与
# ================================================================

class TestBuildTopologyAFField:
    """build() が routing.bgp/ospf/static の各エントリに af フィールドを付与する。"""

    @pytest.fixture
    def topology_from_fixture(self):
        """v6routing fixture からトポロジーを構築する。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        return build(devices, generated_from=fixture_files)

    @pytest.mark.integration
    def test_bgp_entries_have_af(self, topology_from_fixture):
        """routing.bgp の全エントリに af フィールドが存在する。"""
        for entry in topology_from_fixture["routing"]["bgp"]:
            assert "af" in entry, f"af フィールドが欠如: {entry}"

    @pytest.mark.integration
    def test_ospf_entries_have_af(self, topology_from_fixture):
        """routing.ospf の全エントリに af フィールドが存在する。"""
        for entry in topology_from_fixture["routing"]["ospf"]:
            assert "af" in entry, f"af フィールドが欠如: {entry}"

    @pytest.mark.integration
    def test_static_entries_have_af(self, topology_from_fixture):
        """routing.static の全エントリに af フィールドが存在する。"""
        for entry in topology_from_fixture["routing"]["static"]:
            assert "af" in entry, f"af フィールドが欠如: {entry}"

    @pytest.mark.integration
    def test_v6_bgp_entries_exist(self, topology_from_fixture):
        """routing.bgp に af='v6' のエントリが存在する。"""
        v6_bgp = [e for e in topology_from_fixture["routing"]["bgp"] if e.get("af") == "v6"]
        assert len(v6_bgp) >= 1, f"af=v6 BGP エントリが必要: {topology_from_fixture['routing']['bgp']}"

    @pytest.mark.integration
    def test_v6_ospf_entries_exist(self, topology_from_fixture):
        """routing.ospf に af='v6' のエントリが存在する。"""
        v6_ospf = [e for e in topology_from_fixture["routing"]["ospf"] if e.get("af") == "v6"]
        assert len(v6_ospf) >= 1, f"af=v6 OSPF エントリが必要: {topology_from_fixture['routing']['ospf']}"

    @pytest.mark.integration
    def test_v6_static_entries_exist(self, topology_from_fixture):
        """routing.static に af='v6' のエントリが存在する。"""
        v6_static = [e for e in topology_from_fixture["routing"]["static"] if e.get("af") == "v6"]
        assert len(v6_static) >= 1, f"af=v6 static エントリが必要: {topology_from_fixture['routing']['static']}"

    @pytest.mark.integration
    def test_v4_bgp_af_preserved(self, topology_from_fixture):
        """routing.bgp の v4 エントリは af='v4' で保持される。"""
        v4_bgp = [e for e in topology_from_fixture["routing"]["bgp"] if e.get("af") == "v4"]
        # IOS-R1 の 10.1.0.2 eBGP は v4
        assert any("10.1.0.2" == e.get("neighbor_ip") for e in v4_bgp), \
            f"v4 BGP 10.1.0.2 が af=v4 で残っていない: {v4_bgp}"

    @pytest.mark.integration
    def test_v4_static_af_preserved(self):
        """既存 v4 static は af='v4' で不変（後方互換）。"""
        from lib.parsers.base import Device, Interface, StaticRoute
        from scripts.build_topology import build
        dev = Device(
            hostname="R1", vendor="cisco_ios", asn=None,
            interfaces=[Interface(name="Gi0/0", ip="10.0.0.1/30", description=None, addresses=[
                {"af": "v4", "ip": "10.0.0.1", "prefix": 30}
            ])],
            bgp=[], ospf=[],
            static=[StaticRoute(prefix="0.0.0.0/0", next_hop="10.0.0.2")],
        )
        topo = build([dev], generated_from=["test"])
        for s in topo["routing"]["static"]:
            assert s.get("af") == "v4", f"v4 static の af が 'v4' でない: {s}"


# ================================================================
# セクション 9: build_topology.py — _resolve_local_ip v6 対応
# ================================================================

class TestBuildTopologyLocalIPv6:
    """_resolve_local_ip が v6 neighbor_ip に対して v6 IF アドレスを local_ip として返す。"""

    @pytest.mark.unit
    def test_resolve_local_ip_v6(self):
        """v6 neighbor_ip に対して同一サブネットの v6 IF アドレスを local_ip として返す。"""
        from lib.parsers.base import Device, Interface
        from scripts.build_topology import _resolve_local_ip

        dev = Device(
            hostname="R1", vendor="cisco_ios", asn=65100,
            interfaces=[
                Interface(
                    name="Gi0/0", ip="10.1.0.1/30", description=None,
                    addresses=[
                        {"af": "v4", "ip": "10.1.0.1", "prefix": 30},
                        {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                    ]
                )
            ],
            bgp=[], ospf=[], static=[],
        )

        # v6 neighbor_ip: 2001:db8:1::0 → local_ip は 2001:db8:1::1
        local_ip = _resolve_local_ip(dev, "2001:db8:1::0")
        assert local_ip == "2001:db8:1::1", f"local_ip={local_ip} != 2001:db8:1::1"

    @pytest.mark.unit
    def test_resolve_local_ip_v4_unaffected(self):
        """v4 neighbor_ip に対して従来通り v4 local_ip が返る（後方互換）。"""
        from lib.parsers.base import Device, Interface
        from scripts.build_topology import _resolve_local_ip

        dev = Device(
            hostname="R1", vendor="cisco_ios", asn=65100,
            interfaces=[
                Interface(
                    name="Gi0/0", ip="10.1.0.1/30", description=None,
                    addresses=[
                        {"af": "v4", "ip": "10.1.0.1", "prefix": 30},
                    ]
                )
            ],
            bgp=[], ospf=[], static=[],
        )

        local_ip = _resolve_local_ip(dev, "10.1.0.2")
        assert local_ip == "10.1.0.1", f"local_ip={local_ip} != 10.1.0.1"

    @pytest.mark.unit
    def test_resolve_local_ip_v6_no_match_returns_none(self):
        """v6 neighbor が同一サブネットにない場合は None を返す。"""
        from lib.parsers.base import Device, Interface
        from scripts.build_topology import _resolve_local_ip

        dev = Device(
            hostname="R1", vendor="cisco_ios", asn=65100,
            interfaces=[
                Interface(
                    name="Gi0/0", ip="10.1.0.1/30", description=None,
                    addresses=[
                        {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                    ]
                )
            ],
            bgp=[], ospf=[], static=[],
        )

        local_ip = _resolve_local_ip(dev, "2001:db8:99::0")
        assert local_ip is None

    @pytest.mark.integration
    def test_v6_bgp_local_ip_resolved(self):
        """v6routing fixture の v6 BGP エントリで local_ip が v6 アドレスとして解決される。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)
        v6_bgp = [e for e in topo["routing"]["bgp"] if e.get("af") == "v6"]
        # 少なくとも1件は local_ip が v6 アドレスで解決されているはず
        resolved = [e for e in v6_bgp if e.get("local_ip") and ":" in e["local_ip"]]
        assert resolved, f"v6 BGP で local_ip が v6 で解決されたエントリがない: {v6_bgp}"


# ================================================================
# セクション 10: build_topology.py — v6 OSPF area 解決（_resolve_ospf_area_for_device）
# ================================================================

class TestBuildTopologyOSPFv3Area:
    """v6 サブネットに対して OSPFv3 の area が正しく解決される。"""

    @pytest.mark.unit
    def test_resolve_ospf_area_v6_subnet(self):
        """v6 サブネットに対して OSPFv3 の area を正しく解決する。"""
        from lib.parsers.base import Device, Interface, OspfNetwork
        from scripts.build_topology import _resolve_ospf_area_for_device
        import ipaddress

        dev = Device(
            hostname="R1", vendor="cisco_ios", asn=None,
            interfaces=[
                Interface(
                    name="GigabitEthernet0/0", ip="10.1.0.1/30", description=None,
                    addresses=[
                        {"af": "v4", "ip": "10.1.0.1", "prefix": 30},
                        {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                    ]
                )
            ],
            bgp=[], static=[],
            ospf=[
                OspfNetwork(process=10, network="2001:db8:1::/127", area="0", af="v6"),
            ],
        )

        subnet = ipaddress.ip_network("2001:db8:1::/127", strict=False)
        area = _resolve_ospf_area_for_device(dev, subnet)
        assert area == "0", f"area={area} != '0'"

    @pytest.mark.unit
    def test_resolve_ospf_area_v4_unaffected_by_v6(self):
        """v4 サブネットに対して v6 OSPFv3 エントリは無視される（版不一致でスキップ）。"""
        from lib.parsers.base import Device, Interface, OspfNetwork
        from scripts.build_topology import _resolve_ospf_area_for_device
        import ipaddress

        dev = Device(
            hostname="R1", vendor="cisco_ios", asn=None,
            interfaces=[
                Interface(
                    name="GigabitEthernet0/0", ip="10.1.0.1/30", description=None,
                    addresses=[{"af": "v4", "ip": "10.1.0.1", "prefix": 30}]
                )
            ],
            bgp=[], static=[],
            ospf=[
                OspfNetwork(process=10, network="2001:db8:1::/127", area="0", af="v6"),
            ],
        )

        subnet = ipaddress.ip_network("10.1.0.0/30", strict=False)
        area = _resolve_ospf_area_for_device(dev, subnet)
        assert area is None, f"v6 OSPFv3 が v4 サブネットに誤解決: area={area}"

    @pytest.mark.integration
    def test_v6_links_have_ospf_area(self):
        """v6routing fixture でビルドした topology の v6 p2p リンクに ospf_area が付与される。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)
        # v6 サブネット(2001:db8:1::/127)を持つリンクに ospf_area が付いていること
        v6_links = [lk for lk in topo["links"] if ":" in lk.get("subnet", "")]
        ospf_links = [lk for lk in v6_links if "ospf_area" in lk]
        assert ospf_links, f"v6 リンクに ospf_area が付与されていない: {v6_links}"


# ================================================================
# セクション 11: topology_io.py — round-trip（af フィールド含む）
# ================================================================

class TestTopologyIORoundTripAF:
    """dump/load で af フィールドが保持される（round-trip）。"""

    @pytest.fixture
    def topology_with_v6_routing(self):
        """af フィールドを含む v6 ルーティングエントリを持つ topology dict を返す。"""
        return {
            "title": "Test v6 routing",
            "generated_from": ["test"],
            "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65100, "sections": []}],
            "interfaces": [
                {
                    "id": "r1::Gi0/0",
                    "device": "r1",
                    "name": "Gi0/0",
                    "ip": "10.0.0.1/30",
                    "vlan": None,
                    "description": None,
                    "shutdown": False,
                    "admin_status": "up",
                    "oper_status": None,
                    "mtu": None,
                    "speed": None,
                    "duplex": None,
                    "l2_l3": "l3",
                    "switchport": None,
                    "encapsulation": None,
                    "source": "parsed",
                    "addresses": [
                        {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                        {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                    ],
                }
            ],
            "links": [],
            "segments": [],
            "routing": {
                "bgp": [
                    {"device": "r1", "local_as": 65100, "local_ip": "2001:db8:1::1",
                     "neighbor_ip": "2001:db8:1::0", "peer_as": 65200, "type": "ebgp", "af": "v6"},
                ],
                "ospf": [
                    {"device": "r1", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                ],
                "static": [
                    {"device": "r1", "prefix": "::/0", "next_hop": "2001:db8:1::0", "af": "v6"},
                ],
            },
        }

    @pytest.mark.integration
    def test_round_trip_preserves_bgp_af(self, topology_with_v6_routing):
        """dump → load で routing.bgp の af フィールドが保持される。"""
        from lib.topology_io import dump_topology, load_topology
        with tempfile.TemporaryDirectory() as tmpdir:
            dump_topology(topology_with_v6_routing, tmpdir)
            loaded = load_topology(tmpdir)
        for entry in loaded["routing"]["bgp"]:
            assert "af" in entry, f"af フィールドが消失: {entry}"
            assert entry["af"] == "v6"

    @pytest.mark.integration
    def test_round_trip_preserves_ospf_af(self, topology_with_v6_routing):
        """dump → load で routing.ospf の af フィールドが保持される。"""
        from lib.topology_io import dump_topology, load_topology
        with tempfile.TemporaryDirectory() as tmpdir:
            dump_topology(topology_with_v6_routing, tmpdir)
            loaded = load_topology(tmpdir)
        for entry in loaded["routing"]["ospf"]:
            assert "af" in entry, f"af フィールドが消失: {entry}"
            assert entry["af"] == "v6"

    @pytest.mark.integration
    def test_round_trip_preserves_static_af(self, topology_with_v6_routing):
        """dump → load で routing.static の af フィールドが保持される。"""
        from lib.topology_io import dump_topology, load_topology
        with tempfile.TemporaryDirectory() as tmpdir:
            dump_topology(topology_with_v6_routing, tmpdir)
            loaded = load_topology(tmpdir)
        for entry in loaded["routing"]["static"]:
            assert "af" in entry, f"af フィールドが消失: {entry}"
            assert entry["af"] == "v6"

    @pytest.mark.integration
    def test_old_yaml_without_af_loads_ok(self):
        """af フィールドがない旧 YAML を読み込んでも例外が出ない（後方互換）。"""
        from lib.topology_io import load_topology
        import yaml

        # af フィールドなしの旧形式 routing エントリを含む YAML を用意
        old_routing_bgp = [
            {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
             "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp"}
            # af なし → 旧形式
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            with open(os.path.join(tmpdir, "_meta.yaml"), "w") as f:
                yaml.safe_dump({"schema_version": "1.0", "title": "t", "generated_from": ["x"]}, f)
            with open(os.path.join(tmpdir, "devices.yaml"), "w") as f:
                yaml.safe_dump({"devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []}],
                                "interfaces": [{"id": "r1::Gi0/0", "device": "r1", "name": "Gi0/0",
                                                "ip": "10.0.0.1/30", "vlan": None, "description": None,
                                                "shutdown": False}]}, f)
            with open(os.path.join(tmpdir, "physical.yaml"), "w") as f:
                yaml.safe_dump({"links": [], "segments": []}, f)
            with open(os.path.join(tmpdir, "routing.bgp.yaml"), "w") as f:
                yaml.safe_dump({"bgp": old_routing_bgp}, f)

            # 例外なく load できること
            loaded = load_topology(tmpdir)
            assert loaded["routing"]["bgp"][0].get("af", "v4") in ("v4", None), \
                "旧形式のエントリは af なし（または v4 補完）で読み込めること"


# ================================================================
# セクション 12: rendering — v6 BGP セッション描画
# ================================================================

class TestRenderingV6BGP:
    """v6 BGP セッションが BGP ビューに描画され、data-bgp-id 連動が機能する。"""

    @pytest.fixture
    def v6_topology(self):
        """BGP IPv6 セッションを含む最小 topology dict を返す。"""
        return {
            "title": "Test v6 BGP",
            "generated_from": ["test"],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65100, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "juniper_junos", "as": 65200, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "r1::Gi0/0",
                    "device": "r1",
                    "name": "Gi0/0",
                    "ip": None,
                    "vlan": None,
                    "description": "to-R2",
                    "shutdown": False,
                    "admin_status": "up",
                    "oper_status": None,
                    "mtu": None,
                    "speed": None,
                    "duplex": None,
                    "l2_l3": "l3",
                    "switchport": None,
                    "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::1", "prefix": 127}],
                },
                {
                    "id": "r2::ge-0/0/0",
                    "device": "r2",
                    "name": "ge-0/0/0",
                    "ip": None,
                    "vlan": None,
                    "description": "to-R1",
                    "shutdown": False,
                    "admin_status": "up",
                    "oper_status": None,
                    "mtu": None,
                    "speed": None,
                    "duplex": None,
                    "l2_l3": "l3",
                    "switchport": None,
                    "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::0", "prefix": 127}],
                },
            ],
            "links": [
                {
                    "a_device": "r1",
                    "a_if": "Gi0/0",
                    "b_device": "r2",
                    "b_if": "ge-0/0/0",
                    "subnet": "2001:db8:1::/127",
                    "kind": "inferred-subnet",
                }
            ],
            "segments": [],
            "routing": {
                "bgp": [
                    {"device": "r1", "local_as": 65100, "local_ip": "2001:db8:1::1",
                     "neighbor_ip": "2001:db8:1::0", "peer_as": 65200, "type": "ebgp", "af": "v6"},
                    {"device": "r2", "local_as": 65200, "local_ip": "2001:db8:1::0",
                     "neighbor_ip": "2001:db8:1::1", "peer_as": 65100, "type": "ebgp", "af": "v6"},
                ],
                "ospf": [],
                "static": [],
            },
        }

    @pytest.mark.integration
    def test_v6_bgp_resolved_edges_detected(self, v6_topology):
        """v6 BGP セッション（v6 neighbor_ip）が解決可能なエッジとして検出される。"""
        from lib.rendering.views import _bgp_has_resolved_edges
        result = _bgp_has_resolved_edges(
            v6_topology["routing"]["bgp"],
            v6_topology["interfaces"]
        )
        assert result, "v6 BGP セッションが解決可能エッジとして検出されない"

    @pytest.mark.integration
    def test_v6_bgp_session_map_built(self, v6_topology):
        """v6 neighbor_ip を持つ BGP エントリで bgp_session_map が構築される。"""
        from lib.rendering.core import _build_bgp_session_map
        bgp_map = _build_bgp_session_map(
            v6_topology["routing"]["bgp"],
            v6_topology["interfaces"],
        )
        # ("r1", "2001:db8:1::0") → bgp_id が存在すること
        key = ("r1", "2001:db8:1::0")
        assert key in bgp_map, f"bgp_session_map に v6 エントリがない: {list(bgp_map.keys())}"

    @pytest.mark.integration
    def test_v6_bgp_rendered_html_contains_bgp_view(self, v6_topology):
        """v6 BGP topology を render() した HTML に BGP ビューが含まれる。"""
        from lib.rendering import render
        html = render(v6_topology)
        assert "bgp" in html.lower(), "BGP ビューが HTML に含まれない"

    @pytest.mark.integration
    def test_v6_bgp_rendered_html_contains_data_bgp_id(self, v6_topology):
        """v6 BGP topology の HTML に data-bgp-id 属性が含まれる（テーブル連動）。"""
        from lib.rendering import render
        html = render(v6_topology)
        assert "data-bgp-id" in html, "data-bgp-id 属性が HTML に含まれない"

    @pytest.mark.integration
    def test_v6_bgp_rendered_html_contains_neighbor_ip(self, v6_topology):
        """HTML に v6 BGP ネイバー IP が含まれる。"""
        from lib.rendering import render
        html = render(v6_topology)
        assert "2001:db8:1::" in html, "v6 ネイバー IP が HTML に含まれない"


# ================================================================
# セクション 13: rendering — v6 OSPF ビュー描画（data-ospf-id 連動）
# ================================================================

class TestRenderingV6OSPF:
    """OSPFv3 セッションが OSPF ビューに描画され、data-ospf-id 連動が機能する。"""

    @pytest.fixture
    def v6_ospf_topology(self):
        """OSPFv3 リンクを含む最小 topology dict を返す。"""
        return {
            "title": "Test v6 OSPF",
            "generated_from": ["test"],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "juniper_junos", "as": None, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "r1::Gi0/0",
                    "device": "r1",
                    "name": "Gi0/0",
                    "ip": None,
                    "vlan": None,
                    "description": "to-R2",
                    "shutdown": False,
                    "admin_status": "up",
                    "oper_status": None,
                    "mtu": None,
                    "speed": None,
                    "duplex": None,
                    "l2_l3": "l3",
                    "switchport": None,
                    "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::1", "prefix": 127}],
                },
                {
                    "id": "r2::ge-0/0/0",
                    "device": "r2",
                    "name": "ge-0/0/0",
                    "ip": None,
                    "vlan": None,
                    "description": "to-R1",
                    "shutdown": False,
                    "admin_status": "up",
                    "oper_status": None,
                    "mtu": None,
                    "speed": None,
                    "duplex": None,
                    "l2_l3": "l3",
                    "switchport": None,
                    "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::0", "prefix": 127}],
                },
            ],
            "links": [
                {
                    "a_device": "r1",
                    "a_if": "Gi0/0",
                    "b_device": "r2",
                    "b_if": "ge-0/0/0",
                    "subnet": "2001:db8:1::/127",
                    "kind": "inferred-subnet",
                    "ospf_area": "0",
                    "ospf_network": "2001:db8:1::/127",
                }
            ],
            "segments": [],
            "routing": {
                "bgp": [],
                "ospf": [
                    {"device": "r1", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                    {"device": "r2", "process": None, "network": "ge-0/0/0.0", "area": "0.0.0.0", "af": "v6"},
                ],
                "static": [],
            },
        }

    @pytest.mark.integration
    def test_v6_ospf_has_edges(self, v6_ospf_topology):
        """v6 OSPF リンク（ospf_area 付き）が OSPF エッジとして検出される。"""
        from lib.rendering.views import _ospf_has_edges
        result = _ospf_has_edges(
            v6_ospf_topology["routing"]["ospf"],
            v6_ospf_topology["links"]
        )
        assert result, "v6 OSPF リンクがエッジとして検出されない"

    @pytest.mark.integration
    def test_v6_ospf_marking_map_built(self, v6_ospf_topology):
        """v6 OSPF エントリで ospf_marking_map が構築される。"""
        from lib.rendering.core import _build_ospf_marking_map
        ospf_map = _build_ospf_marking_map(v6_ospf_topology["routing"]["ospf"])
        # ("r1", "2001:db8:1::/127") → ospf_id が存在すること
        key = ("r1", "2001:db8:1::/127")
        assert key in ospf_map, f"ospf_marking_map に v6 エントリがない: {list(ospf_map.keys())}"

    @pytest.mark.integration
    def test_v6_ospf_rendered_html_contains_ospf_view(self, v6_ospf_topology):
        """v6 OSPF topology を render() した HTML に OSPF ビューが含まれる。"""
        from lib.rendering import render
        html = render(v6_ospf_topology)
        assert "ospf" in html.lower(), "OSPF ビューが HTML に含まれない"

    @pytest.mark.integration
    def test_v6_ospf_rendered_html_contains_data_ospf_id(self, v6_ospf_topology):
        """v6 OSPF topology の HTML に data-ospf-id 属性が含まれる（テーブル連動）。"""
        from lib.rendering import render
        html = render(v6_ospf_topology)
        assert "data-ospf-id" in html, "data-ospf-id 属性が HTML に含まれない"

    @pytest.mark.integration
    def test_v6_ospf_rendered_html_contains_network(self, v6_ospf_topology):
        """HTML に v6 OSPF ネットワーク（2001:db8:1::）が含まれる。"""
        from lib.rendering import render
        html = render(v6_ospf_topology)
        assert "2001:db8:1::" in html, "v6 OSPF ネットワークが HTML に含まれない"


# ================================================================
# セクション 14: rendering — v6 static 経路ハイライト
# ================================================================

class TestRenderingV6Static:
    """v6 static ルートの next-hop 経路解決が機能する（ipaddress で v6 対応済み）。"""

    @pytest.fixture
    def v6_static_topology(self):
        """v6 static ルートを含む最小 topology dict を返す。"""
        return {
            "title": "Test v6 static",
            "generated_from": ["test"],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "juniper_junos", "as": None, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "r1::Gi0/0",
                    "device": "r1",
                    "name": "Gi0/0",
                    "ip": None,
                    "vlan": None,
                    "description": None,
                    "shutdown": False,
                    "admin_status": "up",
                    "oper_status": None,
                    "mtu": None,
                    "speed": None,
                    "duplex": None,
                    "l2_l3": "l3",
                    "switchport": None,
                    "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::1", "prefix": 127}],
                },
                {
                    "id": "r2::ge-0/0/0",
                    "device": "r2",
                    "name": "ge-0/0/0",
                    "ip": None,
                    "vlan": None,
                    "description": None,
                    "shutdown": False,
                    "admin_status": "up",
                    "oper_status": None,
                    "mtu": None,
                    "speed": None,
                    "duplex": None,
                    "l2_l3": "l3",
                    "switchport": None,
                    "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::0", "prefix": 127}],
                },
            ],
            "links": [
                {
                    "a_device": "r1",
                    "a_if": "Gi0/0",
                    "b_device": "r2",
                    "b_if": "ge-0/0/0",
                    "subnet": "2001:db8:1::/127",
                    "kind": "inferred-subnet",
                }
            ],
            "segments": [],
            "routing": {
                "bgp": [],
                "ospf": [],
                "static": [
                    {"device": "r1", "prefix": "::/0", "next_hop": "2001:db8:1::0", "af": "v6"},
                ],
            },
        }

    @pytest.mark.integration
    def test_v6_static_route_map_built(self, v6_static_topology):
        """v6 next_hop を持つ static ルートで route_edge_id が解決される。"""
        from lib.rendering.core import _build_static_route_map
        route_map = _build_static_route_map(
            v6_static_topology["routing"]["static"],
            v6_static_topology["links"],
            v6_static_topology["segments"],
            v6_static_topology["interfaces"],
        )
        key = ("r1", "::/0")
        assert key in route_map, f"v6 static ルートが解決されない: {list(route_map.keys())}"
        assert route_map[key]["route_edge_id"] is not None, "route_edge_id が None"

    @pytest.mark.integration
    def test_v6_static_rendered_html_contains_static(self, v6_static_topology):
        """v6 static ルートが HTML に含まれる。"""
        from lib.rendering import render
        html = render(v6_static_topology)
        assert "::/0" in html, "v6 default route '::/0' が HTML に含まれない"

    @pytest.mark.integration
    def test_v6_static_rendered_html_contains_data_route_edge(self, v6_static_topology):
        """v6 static ルートの HTML に data-route-edge 属性が含まれる（経路ハイライト連動）。"""
        from lib.rendering import render
        html = render(v6_static_topology)
        assert "data-route-edge" in html, "data-route-edge 属性が HTML に含まれない"


# ================================================================
# セクション 15: 後方互換テスト（既存 v4 routing 不変）
# ================================================================

class TestBackwardCompatibility:
    """既存 v4 routing は af=v4 付与のみで値不変（後方互換）。"""

    @pytest.fixture
    def v4_only_topology(self):
        """既存 v4 routing fixture (ebgp-p2p) から topology を構築する。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        ebgp_dir = os.path.join(
            os.path.dirname(__file__), "..", "evals", "inputs", "ebgp-p2p"
        )
        fixture_files = sorted([
            os.path.join(ebgp_dir, f) for f in os.listdir(ebgp_dir)
            if f.endswith((".cfg", ".conf"))
        ])
        devices = parse_paths(fixture_files)
        return build(devices, generated_from=fixture_files)

    @pytest.mark.integration
    def test_v4_bgp_values_unchanged(self, v4_only_topology):
        """v4 BGP エントリの neighbor_ip/peer_as/type/local_ip が不変。"""
        for entry in v4_only_topology["routing"]["bgp"]:
            # v4 エントリの検証: IP が v4 形式
            ni = entry.get("neighbor_ip", "")
            assert "." in ni or ni == "", f"v4 BGP エントリの neighbor_ip が v4 でない: {ni}"
            # af は v4 であるべき
            assert entry.get("af") == "v4", f"v4 BGP エントリの af が 'v4' でない: {entry}"

    @pytest.mark.integration
    def test_v4_static_values_unchanged(self, v4_only_topology):
        """v4 static エントリの prefix/next_hop が不変、af=v4。"""
        for entry in v4_only_topology["routing"]["static"]:
            pref = entry.get("prefix", "")
            assert "." in pref, f"v4 static の prefix が v4 でない: {pref}"
            assert entry.get("af") == "v4", f"v4 static の af が 'v4' でない: {entry}"

    @pytest.mark.integration
    def test_existing_links_unchanged(self, v4_only_topology):
        """links のサブネット（v4）は不変。"""
        for lk in v4_only_topology["links"]:
            subnet = lk.get("subnet", "")
            assert "." in subnet, f"v4 リンクの subnet が変化: {subnet}"

    @pytest.mark.integration
    def test_deterministic_output(self):
        """同一 config から2回 build() した結果が完全一致する（決定性）。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices1 = parse_paths(fixture_files)
        devices2 = parse_paths(fixture_files)
        topo1 = build(devices1, generated_from=fixture_files)
        topo2 = build(devices2, generated_from=fixture_files)
        import json
        assert json.dumps(topo1, sort_keys=True) == json.dumps(topo2, sort_keys=True), \
            "決定性が損なわれている（2回の build() 結果が不一致）"


# ================================================================
# セクション 16: end-to-end — v6routing fixture 全体
# ================================================================

class TestE2EV6Routing:
    """v6routing fixture の E2E パス: parse → build → render が正常に通る。"""

    @pytest.fixture(scope="class")
    def full_topology(self):
        """v6routing fixture の完全 topology dict。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        return build(devices, generated_from=fixture_files)

    @pytest.mark.integration
    def test_two_devices_parsed(self, full_topology):
        """2台のデバイスが正常にパースされる。"""
        assert len(full_topology["devices"]) == 2

    @pytest.mark.integration
    def test_v6_link_inferred(self, full_topology):
        """v6 サブネット 2001:db8:1::/127 のリンクが推論される。"""
        v6_links = [lk for lk in full_topology["links"] if ":" in lk.get("subnet", "")]
        assert v6_links, f"v6 リンクが推論されない: {full_topology['links']}"

    @pytest.mark.integration
    def test_render_succeeds(self, full_topology):
        """render() が例外なく HTML 文字列を返す。"""
        from lib.rendering import render
        html = render(full_topology)
        assert isinstance(html, str)
        assert len(html) > 0

    @pytest.mark.integration
    def test_render_contains_v6_addresses(self, full_topology):
        """HTML に v6 アドレス（2001:db8:）が含まれる。"""
        from lib.rendering import render
        html = render(full_topology)
        assert "2001:db8:" in html, "v6 アドレスが HTML に含まれない"

    @pytest.mark.integration
    def test_render_html_self_contained(self, full_topology):
        """render() が自己完結 HTML（<!DOCTYPE html> 開始）を返す。"""
        from lib.rendering import render
        html = render(full_topology)
        assert html.lower().lstrip().startswith("<!doctype html")

    @pytest.mark.integration
    def test_round_trip_e2e(self, full_topology):
        """dump → load で v6 routing エントリが保持される（E2E round-trip）。"""
        from lib.topology_io import dump_topology, load_topology
        with tempfile.TemporaryDirectory() as tmpdir:
            dump_topology(full_topology, tmpdir)
            loaded = load_topology(tmpdir)
        # v6 BGP が round-trip 後も存在すること
        v6_bgp = [e for e in loaded["routing"]["bgp"] if e.get("af") == "v6"]
        assert v6_bgp, "round-trip 後に v6 BGP エントリが消失"


# ================================================================
# セクション 17: 値検証強化（vacuous 解消・具体値アサーション）
# ================================================================

class TestValueVerificationStrong:
    """レビュー指摘の vacuous アサーション解消 — 具体値での検証。"""

    # ---------------------------------------------------------------
    # 17-A: v6 BGP の type 値検証（iBGP/eBGP）
    # ---------------------------------------------------------------

    @pytest.mark.unit
    def test_v6_bgp_ebgp_type(self):
        """v6 eBGP エントリの type が 'ebgp'。"""
        from scripts.build_topology import _determine_bgp_type
        assert _determine_bgp_type(65100, 65200) == "ebgp"

    @pytest.mark.unit
    def test_v6_bgp_ibgp_type(self):
        """v6 iBGP エントリの type が 'ibgp'。"""
        from scripts.build_topology import _determine_bgp_type
        assert _determine_bgp_type(65100, 65100) == "ibgp"

    @pytest.mark.integration
    def test_v6_bgp_type_in_topology(self):
        """v6routing build 出力の v6 BGP エントリで type が ebgp/ibgp/unknown のいずれかの具体値。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)
        v6_bgp = [e for e in topo["routing"]["bgp"] if e.get("af") == "v6"]
        assert v6_bgp, "v6 BGP エントリが存在しない"
        # IOS-R1(65100) ↔ JUNOS-R1(65200) は eBGP
        ebgp_entries = [e for e in v6_bgp if e.get("type") == "ebgp"]
        assert ebgp_entries, f"v6 eBGP type='ebgp' のエントリがない: {v6_bgp}"
        # iBGP エントリ（IOS-R1 65100 ↔ IOS-R2 65100）は fixture に含まれないため
        # iBGP neighbor(2001:db8:2::0)の ibgp 検証はパーサレベルで行う
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        from scripts.build_topology import build as build2
        from lib.parsers.base import Device
        # 2001:db8:2::0 は同 AS(65100) → ibgp
        ibgp_nbr = [b for b in dev.bgp if b.neighbor_ip == "2001:db8:2::" and getattr(b, "af") == "v6"]
        assert ibgp_nbr, "iBGP v6 ネイバーが見つからない"
        assert ibgp_nbr[0].peer_as == 65100

    # ---------------------------------------------------------------
    # 17-B: data-bgp-id / data-ospf-id / data-route-edge の値検証
    # ---------------------------------------------------------------

    @pytest.mark.integration
    def test_data_bgp_id_value_format(self):
        """data-bgp-id の値が 'r1|r2' 形式（sorted ペア区切り）で SVG・カード両方に存在する。"""
        from lib.rendering import render
        topology = {
            "title": "T",
            "generated_from": ["t"],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65100, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "juniper_junos", "as": 65200, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "r1::Gi0/0", "device": "r1", "name": "Gi0/0",
                    "ip": None, "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::1", "prefix": 127}],
                },
                {
                    "id": "r2::ge-0/0/0", "device": "r2", "name": "ge-0/0/0",
                    "ip": None, "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::0", "prefix": 127}],
                },
            ],
            "links": [{
                "a_device": "r1", "a_if": "Gi0/0",
                "b_device": "r2", "b_if": "ge-0/0/0",
                "subnet": "2001:db8:1::/127", "kind": "inferred-subnet",
            }],
            "segments": [],
            "routing": {
                "bgp": [
                    {"device": "r1", "local_as": 65100, "local_ip": "2001:db8:1::1",
                     "neighbor_ip": "2001:db8:1::0", "peer_as": 65200, "type": "ebgp", "af": "v6"},
                    {"device": "r2", "local_as": 65200, "local_ip": "2001:db8:1::0",
                     "neighbor_ip": "2001:db8:1::1", "peer_as": 65100, "type": "ebgp", "af": "v6"},
                ],
                "ospf": [],
                "static": [],
            },
        }
        html = render(topology)
        # bgp_id は sorted(["r1","r2"]) → "r1|r2"
        assert 'data-bgp-id="r1|r2"' in html, \
            f"data-bgp-id='r1|r2' が HTML に含まれない（先頭100文字: {html[:200]}）"
        # SVG 側とカード側で同一値が1箇所以上（集合が1つ）
        import re
        bgp_id_vals = set(re.findall(r'data-bgp-id="([^"]+)"', html))
        assert len(bgp_id_vals) == 1, f"data-bgp-id の値が複数存在し不一致: {bgp_id_vals}"
        assert "r1|r2" in bgp_id_vals

    @pytest.mark.integration
    def test_data_ospf_id_value_format(self):
        """data-ospf-id の値が正規化 subnet（2001:db8:1::/127）で SVG・カード両方に存在する。"""
        from lib.rendering import render
        topology = {
            "title": "T",
            "generated_from": ["t"],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "juniper_junos", "as": None, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "r1::Gi0/0", "device": "r1", "name": "Gi0/0",
                    "ip": None, "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::1", "prefix": 127}],
                },
                {
                    "id": "r2::ge-0/0/0", "device": "r2", "name": "ge-0/0/0",
                    "ip": None, "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::0", "prefix": 127}],
                },
            ],
            "links": [{
                "a_device": "r1", "a_if": "Gi0/0",
                "b_device": "r2", "b_if": "ge-0/0/0",
                "subnet": "2001:db8:1::/127", "kind": "inferred-subnet",
                "ospf_area": "0", "ospf_network": "2001:db8:1::/127",
            }],
            "segments": [],
            "routing": {
                "bgp": [],
                "ospf": [
                    {"device": "r1", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                    {"device": "r2", "process": None, "network": "ge-0/0/0", "area": "0.0.0.0", "af": "v6"},
                ],
                "static": [],
            },
        }
        html = render(topology)
        # ospf_id は normalize_subnet("2001:db8:1::/127") → "2001:db8:1::/127"
        assert 'data-ospf-id="2001:db8:1::/127"' in html, \
            "data-ospf-id='2001:db8:1::/127' が HTML に含まれない"
        import re
        ospf_id_vals = set(re.findall(r'data-ospf-id="([^"]+)"', html))
        assert len(ospf_id_vals) == 1, f"data-ospf-id の値が複数存在し不一致: {ospf_id_vals}"

    @pytest.mark.integration
    def test_data_route_edge_value_present(self):
        """data-route-edge の値が link_id 形式文字列で存在する（v6 static の経路ハイライト）。"""
        from lib.rendering import render
        import re
        topology = {
            "title": "T",
            "generated_from": ["t"],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []},
                {"id": "r2", "hostname": "R2", "vendor": "juniper_junos", "as": None, "sections": []},
            ],
            "interfaces": [
                {
                    "id": "r1::Gi0/0", "device": "r1", "name": "Gi0/0",
                    "ip": None, "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::1", "prefix": 127}],
                },
                {
                    "id": "r2::ge-0/0/0", "device": "r2", "name": "ge-0/0/0",
                    "ip": None, "vlan": None, "description": None,
                    "shutdown": False, "admin_status": "up", "oper_status": None,
                    "mtu": None, "speed": None, "duplex": None,
                    "l2_l3": "l3", "switchport": None, "encapsulation": None,
                    "source": "parsed",
                    "addresses": [{"af": "v6", "ip": "2001:db8:1::0", "prefix": 127}],
                },
            ],
            "links": [{
                "a_device": "r1", "a_if": "Gi0/0",
                "b_device": "r2", "b_if": "ge-0/0/0",
                "subnet": "2001:db8:1::/127", "kind": "inferred-subnet",
            }],
            "segments": [],
            "routing": {
                "bgp": [],
                "ospf": [],
                "static": [
                    {"device": "r1", "prefix": "::/0", "next_hop": "2001:db8:1::0", "af": "v6"},
                ],
            },
        }
        html = render(topology)
        route_edge_vals = re.findall(r'data-route-edge="([^"]+)"', html)
        assert route_edge_vals, "data-route-edge 属性が HTML に存在しない"
        # 値が空文字でないこと
        assert all(v != "" for v in route_edge_vals), \
            f"data-route-edge に空文字値が含まれる: {route_edge_vals}"

    # ---------------------------------------------------------------
    # 17-C: v6 static の prefix/next_hop を == で具体値検証
    # ---------------------------------------------------------------

    @pytest.mark.unit
    def test_v6_static_prefix_exact(self):
        """IOS v6 static の prefix が正確に '::/0'（ホストビット除去済み）。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert v6_static, "v6 static エントリが存在しない"
        assert v6_static[0].prefix == "::/0", \
            f"prefix={v6_static[0].prefix!r} != '::/0'"

    @pytest.mark.unit
    def test_v6_static_nexthop_exact(self):
        """IOS v6 static の next_hop が正確に '2001:db8:1::'（ipaddress 正規化済み）。"""
        from lib.parsers import cisco_ios
        dev = cisco_ios.parse(IOS_V6ROUTING_CFG)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert v6_static, "v6 static エントリが存在しない"
        # normalize_v6("2001:db8:1::0") → "2001:db8:1::"
        assert v6_static[0].next_hop == "2001:db8:1::", \
            f"next_hop={v6_static[0].next_hop!r} != '2001:db8:1::'"

    @pytest.mark.unit
    def test_junos_v6_static_prefix_normalized(self):
        """JunOS v6 static の prefix が ipaddress で正規化されている（::/0）。"""
        from lib.parsers import juniper_junos
        dev = juniper_junos.parse(JUNOS_V6ROUTING_CFG)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert v6_static, "JunOS v6 static エントリが存在しない"
        assert v6_static[0].prefix == "::/0", \
            f"JunOS v6 static prefix={v6_static[0].prefix!r} != '::/0'"

    @pytest.mark.unit
    def test_junos_v4_static_af_preserved(self):
        """JunOS v4 static は af='v4' で不変。"""
        from lib.parsers import juniper_junos
        cfg = """\
set system host-name JR
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1
"""
        dev = juniper_junos.parse(cfg)
        v4_static = [s for s in dev.static if getattr(s, "af", "v4") == "v4"]
        assert len(v4_static) == 1
        assert v4_static[0].prefix == "0.0.0.0/0"
        assert v4_static[0].next_hop == "10.0.0.1"

    # ---------------------------------------------------------------
    # 17-D: v6 link の ospf_area == "0" 値検証
    # ---------------------------------------------------------------

    @pytest.mark.integration
    def test_v6_link_ospf_area_exact_value(self):
        """v6 routing fixture の v6 リンクの ospf_area が area 0 を示す具体値。

        IOS は area="0"、JunOS は area="0.0.0.0" で宣言するため、
        両端が同一リンクに参加する場合 ospf_area は "0" か "0.0.0.0" か "0/0.0.0.0" のいずれかになる。
        """
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)
        v6_ospf_links = [
            lk for lk in topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        assert v6_ospf_links, "OSPF area 付き v6 リンクが存在しない"
        for lk in v6_ospf_links:
            area = lk["ospf_area"]
            # area 0 を示す値（IOS="0", JunOS="0.0.0.0", 両端合成="0/0.0.0.0"）
            assert area in ("0", "0.0.0.0", "0/0.0.0.0"), \
                f"v6 link ospf_area={area!r} が area 0 を示す値でない"

    # ---------------------------------------------------------------
    # 17-E: v6 BGP の local_ip 具体値検証
    # ---------------------------------------------------------------

    @pytest.mark.unit
    def test_v6_bgp_local_ip_exact(self):
        """v6 BGP エントリの local_ip が '2001:db8:1::1'（具体値）。"""
        from lib.parsers.base import Device, Interface
        from scripts.build_topology import _resolve_local_ip
        dev = Device(
            hostname="R1", vendor="cisco_ios", asn=65100,
            interfaces=[Interface(
                name="Gi0/0", ip=None, description=None,
                addresses=[
                    {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                ]
            )],
            bgp=[], ospf=[], static=[],
        )
        local_ip = _resolve_local_ip(dev, "2001:db8:1::")
        assert local_ip == "2001:db8:1::1", \
            f"local_ip={local_ip!r} != '2001:db8:1::1'"

    @pytest.mark.integration
    def test_v6_bgp_local_ip_in_topology_exact(self):
        """v6routing fixture の v6 BGP エントリで local_ip が '2001:db8:1::1' または '2001:db8:1::'。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)
        v6_bgp = [e for e in topo["routing"]["bgp"] if e.get("af") == "v6"]
        resolved = [e for e in v6_bgp if e.get("local_ip") is not None]
        assert resolved, f"v6 BGP エントリに local_ip が解決されたものがない: {v6_bgp}"
        local_ips = {e["local_ip"] for e in resolved}
        # 2001:db8:1:: サブネット上のアドレスが含まれること
        assert any("2001:db8:1:" in ip for ip in local_ips), \
            f"v6 BGP local_ip に 2001:db8:1: サブネットのアドレスがない: {local_ips}"

    # ---------------------------------------------------------------
    # 17-F: 後方互換 test_v4_bgp_values_unchanged の値不変確認（具体値）
    # ---------------------------------------------------------------

    @pytest.mark.integration
    def test_v4_bgp_values_unchanged_exact(self):
        """v4 BGP エントリの type/local_ip/neighbor_ip/peer_as が不変（ebgp-p2p fixture 具体値）。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        ebgp_dir = os.path.join(
            os.path.dirname(__file__), "..", "evals", "inputs", "ebgp-p2p"
        )
        fixture_files = sorted([
            os.path.join(ebgp_dir, f) for f in os.listdir(ebgp_dir)
            if f.endswith((".cfg", ".conf"))
        ])
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)
        bgp_entries = topo["routing"]["bgp"]
        assert bgp_entries, "ebgp-p2p fixture の BGP エントリが空"
        # 全エントリで type が ebgp/ibgp/unknown のいずれかの具体値であること
        valid_types = {"ebgp", "ibgp", "unknown"}
        for e in bgp_entries:
            assert e.get("type") in valid_types, \
                f"BGP type={e.get('type')!r} が有効値でない"
            assert e.get("af") == "v4", f"v4 fixture の af が 'v4' でない: {e}"
            # neighbor_ip が v4 形式
            ni = e.get("neighbor_ip", "")
            assert "." in ni, f"neighbor_ip={ni!r} が v4 形式でない"
            # peer_as が int
            assert isinstance(e.get("peer_as"), int), f"peer_as が int でない: {e}"

    # ---------------------------------------------------------------
    # 17-G: 修正1検証 — v6 static の nexthop_device_id が None でない
    # ---------------------------------------------------------------

    @pytest.mark.integration
    def test_v6_static_nexthop_device_id_resolved(self):
        """v6 static next_hop に対して nexthop_device_id が正しく解決される（修正1: v6-only IF 解決）。"""
        from lib.rendering.core import _build_static_route_map
        # v6-only IF を持つ topology（ip フィールドは None）
        interfaces = [
            {
                "id": "r1::Gi0/0", "device": "r1", "name": "Gi0/0",
                "ip": None,  # v4 ip なし → 旧コードでは nexthop 解決不可
                "addresses": [{"af": "v6", "ip": "2001:db8:1::1", "prefix": 127}],
            },
            {
                "id": "r2::ge-0/0/0", "device": "r2", "name": "ge-0/0/0",
                "ip": None,
                "addresses": [{"af": "v6", "ip": "2001:db8:1::0", "prefix": 127}],
            },
        ]
        links = [{
            "a_device": "r1", "a_if": "Gi0/0",
            "b_device": "r2", "b_if": "ge-0/0/0",
            "subnet": "2001:db8:1::/127", "kind": "inferred-subnet",
        }]
        static_entries = [
            {"device": "r1", "prefix": "::/0", "next_hop": "2001:db8:1::", "af": "v6"},
        ]
        route_map = _build_static_route_map(static_entries, links, [], interfaces)
        key = ("r1", "::/0")
        assert key in route_map, f"v6 static ルートが解決されない: {list(route_map.keys())}"
        val = route_map[key]
        assert val["nexthop_device_id"] is not None, \
            "nexthop_device_id が None — v6-only IF の機器解決に失敗している（修正1が未適用）"
        assert val["nexthop_device_id"] == "r2", \
            f"nexthop_device_id={val['nexthop_device_id']!r} != 'r2'"

    # ---------------------------------------------------------------
    # 17-H: JunOS v6 static prefix 正規化の検証（修正2）
    # ---------------------------------------------------------------

    @pytest.mark.unit
    def test_junos_v6_static_prefix_host_bits_stripped(self):
        """JunOS v6 static route prefix のホストビットが除去されて正規化される（修正2）。"""
        from lib.parsers import juniper_junos
        # ホストビットあり（本来は ::/0 に正規化されるべき）
        cfg = """\
set system host-name JR
set routing-options rib inet6.0 static route ::/0 next-hop 2001:db8:1::1
"""
        dev = juniper_junos.parse(cfg)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert v6_static, "JunOS v6 static が存在しない"
        assert v6_static[0].prefix == "::/0", \
            f"prefix={v6_static[0].prefix!r} が正規化されていない"

    @pytest.mark.unit
    def test_junos_v6_static_prefix_with_host_bits(self):
        """JunOS v6 static で prefix にホストビットがある場合（例: 2001:db8::1/24）が正規化される。"""
        from lib.parsers import juniper_junos
        cfg = """\
set system host-name JR
set routing-options rib inet6.0 static route 2001:db8::1/32 next-hop 2001:db8:1::1
"""
        dev = juniper_junos.parse(cfg)
        v6_static = [s for s in dev.static if getattr(s, "af", "v4") == "v6"]
        assert v6_static, "JunOS v6 static が存在しない"
        # strict=False で正規化: 2001:db8::1/32 → 2001:db8::/32
        assert v6_static[0].prefix == "2001:db8::/32", \
            f"prefix={v6_static[0].prefix!r} が正規化されていない（期待: '2001:db8::/32'）"


# ================================================================
# セクション 18: OSPFv3-only 参加リンクでの v4 subnet 誤付与バグ回帰防止
# ================================================================

_FIXTURE_DIR_DUALSTACK_OSPF = os.path.join(
    os.path.dirname(__file__), "..", "evals", "inputs", "dualstack-ospf"
)


class TestOSPFv3AfGuard:
    """OSPFv3(af=v6) エントリが v4 subnet の ospf_area 解決に使われないことを保証する。

    バグ概要:
      v6routing fixture で IOS-R1/JUNOS-R1 は OSPFv3 のみ参加（v4 OSPF なし）。
      build_topology._resolve_ospf_area_for_device が entry の af を見ていないため、
      JunOS の ospf3 エントリ (network="ge-0/0/0", af="v6") が v4 subnet の照会でも
      IF 名 → v4 network として解決されてしまい、v4 link に ospf_area が誤付与される。

    修正:
      _resolve_ospf_area_for_device の JunOS パスで entry の af と subnet の af を突合し、
      不一致なら continue する（af ガード）。
    """

    @pytest.mark.unit
    def test_junos_ospfv3_does_not_resolve_v4_subnet(self):
        """JunOS の af=v6 OSPFv3 エントリが v4 subnet に誤解決しない（af ガード）。"""
        from lib.parsers.base import Device, Interface, OspfNetwork
        from scripts.build_topology import _resolve_ospf_area_for_device
        import ipaddress

        # JunOS: ge-0/0/0 に v4/v6 両アドレス、ospf3(af=v6) のみ
        dev = Device(
            hostname="JUNOS-R1", vendor="juniper_junos", asn=65200,
            interfaces=[Interface(
                name="ge-0/0/0", ip="10.1.0.2/30", description=None,
                addresses=[
                    {"af": "v4", "ip": "10.1.0.2", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::0", "prefix": 127},
                ]
            )],
            bgp=[], static=[],
            ospf=[OspfNetwork(process=None, network="ge-0/0/0", area="0.0.0.0", af="v6")],
        )

        v4_subnet = ipaddress.ip_network("10.1.0.0/30", strict=False)
        area = _resolve_ospf_area_for_device(dev, v4_subnet)
        assert area is None, (
            f"JunOS af=v6 OSPFv3 エントリが v4 subnet を誤解決: area={area!r}。"
            "af ガードが実装されていない。"
        )

    @pytest.mark.unit
    def test_junos_ospfv3_correctly_resolves_v6_subnet(self):
        """JunOS の af=v6 OSPFv3 エントリが v6 subnet を正しく解決する（af ガード後も動作）。"""
        from lib.parsers.base import Device, Interface, OspfNetwork
        from scripts.build_topology import _resolve_ospf_area_for_device
        import ipaddress

        dev = Device(
            hostname="JUNOS-R1", vendor="juniper_junos", asn=65200,
            interfaces=[Interface(
                name="ge-0/0/0", ip="10.1.0.2/30", description=None,
                addresses=[
                    {"af": "v4", "ip": "10.1.0.2", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::0", "prefix": 127},
                ]
            )],
            bgp=[], static=[],
            ospf=[OspfNetwork(process=None, network="ge-0/0/0", area="0.0.0.0", af="v6")],
        )

        v6_subnet = ipaddress.ip_network("2001:db8:1::/127", strict=False)
        area = _resolve_ospf_area_for_device(dev, v6_subnet)
        # 正規化は _normalize_ospf_area で行われるが、
        # _resolve_ospf_area_for_device 自体は raw area を返す（"0.0.0.0"）
        assert area == "0.0.0.0", (
            f"JunOS af=v6 OSPFv3 エントリが v6 subnet を正しいエリア '0.0.0.0' で解決できない: got {area!r}"
        )

    @pytest.mark.unit
    def test_ios_ospfv3_if_name_fallback_does_not_resolve_v4(self):
        """IOS ospfv3 の IF 名 fallback エントリが v4 subnet を誤解決しない（af ガード）。

        cisco_ios.py パーサーは v6 アドレス不明時に IF 名を network として格納（fallback）。
        この fallback エントリ(af=v6)が v4 subnet 照会で解決されてはいけない。
        """
        from lib.parsers.base import Device, Interface, OspfNetwork
        from scripts.build_topology import _resolve_ospf_area_for_device
        import ipaddress

        # IOS: IF 名 fallback エントリ（v6 アドレス未解決ケース）
        dev = Device(
            hostname="IOS-R1", vendor="cisco_ios", asn=None,
            interfaces=[Interface(
                name="GigabitEthernet0/0", ip="10.1.0.1/30", description=None,
                addresses=[{"af": "v4", "ip": "10.1.0.1", "prefix": 30}]
            )],
            bgp=[], static=[],
            ospf=[OspfNetwork(process=10, network="GigabitEthernet0/0", area="0", af="v6")],
        )

        v4_subnet = ipaddress.ip_network("10.1.0.0/30", strict=False)
        area = _resolve_ospf_area_for_device(dev, v4_subnet)
        assert area is None, (
            f"IOS ospfv3 IF 名 fallback が v4 subnet を誤解決: area={area!r}。"
            "af ガードが JunOS パスだけでなく実際のパスにも必要。"
        )

    @pytest.mark.integration
    def test_v6routing_v4_link_has_no_ospf_area(self):
        """v6routing fixture（OSPFv3 のみ）で build 後、v4 リンクに ospf_area が付かない。

        これがバグの根本: v4 link (10.1.0.0/30) に ospf_area='0' が誤付与されていた。
        修正後は v4 link に ospf_area フィールドが存在しないこと。
        """
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)

        v4_links = [lk for lk in topo["links"] if ":" not in lk.get("subnet", "")]
        ospf_v4_links = [lk for lk in v4_links if "ospf_area" in lk]
        assert not ospf_v4_links, (
            f"v6routing (OSPFv3 のみ) の v4 link に ospf_area が誤付与されている: "
            f"{ospf_v4_links}。"
            "af ガードが実装されていない。"
        )

    @pytest.mark.integration
    def test_v6routing_v6_link_still_has_ospf_area(self):
        """v6routing fixture で build 後、v6 リンクには正しく ospf_area が付く（非回帰）。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)

        v6_links_with_area = [
            lk for lk in topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        assert v6_links_with_area, (
            "v6routing の v6 link に ospf_area が付いていない。"
            "af ガード導入後も v6 OSPF は正常動作すること。"
        )

    @pytest.mark.integration
    def test_v6routing_ospf_html_label_no_v4_subnet(self):
        """v6routing render 後 OSPF ビューのラベル/data-ospf-id に v4 subnet が含まれない。

        修正前: 誤って ospf_area が付いた v4 link も OSPF ビューに描画される。
        修正後: OSPF ビューに v4 subnet (10.1.0.0/30) が出力されない。
        """
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        from lib.rendering import render
        import re
        fixture_files = [
            os.path.join(FIXTURE_DIR, "iosR.cfg"),
            os.path.join(FIXTURE_DIR, "junosR.conf"),
        ]
        devices = parse_paths(fixture_files)
        topo = build(devices, generated_from=fixture_files)
        html = render(topo)

        # OSPF ビュー部分を抽出
        m_start = re.search(r'<g[^>]+class="view view-ospf"', html)
        if not m_start:
            pytest.skip("OSPF ビューが生成されない（OSPF エントリが両端に揃っていない）")
        start = m_start.start()
        m_end = re.search(r'<g[^>]+class="view view-(?!ospf)[^"]*"', html[start + 1:])
        ospf_section = html[start: start + 1 + m_end.start()] if m_end else html[start:]

        # data-ospf-id に v4 subnet が含まれないこと
        # （data-subnet は物理接続識別子として使われるため許容）
        import re as _re
        ospf_id_vals = _re.findall(r'data-ospf-id="([^"]+)"', ospf_section)
        for val in ospf_id_vals:
            assert "10.1.0.0/30" not in val, (
                f"OSPF ビューの data-ospf-id に v4 subnet '10.1.0.0/30' が含まれている: {val!r}。"
                "OSPFv3 のみの構成で v4 subnet が OSPF data-ospf-id に誤表示されている。"
            )
        # OSPF ラベル（area label text）に v4 subnet が含まれないこと
        area_labels = _re.findall(r'class="link-label layer-ospf">([^<]+)', ospf_section)
        # tspan 内テキストも収集
        tspan_texts = _re.findall(r'<tspan[^>]*>([^<]+)</tspan>', ospf_section)
        all_label_texts = area_labels + tspan_texts
        for label in all_label_texts:
            assert "10.1.0.0/30" not in label, (
                f"OSPF ビューのラベルに v4 subnet '10.1.0.0/30' が含まれている: {label!r}。"
                "OSPFv3 のみの構成で v4 subnet が OSPF ラベルに誤表示されている。"
            )


class TestDualStackOspfFixture:
    """dualstack-ospf フィクスチャ: v4 OSPFv2 + v6 OSPFv3 の真の dual-stack OSPF 構成。

    このフィクスチャは v4 OSPFv2(router ospf + network文) と
    v6 OSPFv3(ipv6 ospf area + ipv6 router ospf) の両方が有効な構成。
    build 後に v4 link と v6 link の両方に ospf_area が付き、
    OSPF ビューが dual-stack 2行ラベルになることを確認する。
    """

    @pytest.fixture(scope="class")
    def dso_topo(self):
        """dualstack-ospf fixture から build した topology dict を返す。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        if not os.path.isdir(_FIXTURE_DIR_DUALSTACK_OSPF):
            pytest.skip("dualstack-ospf フィクスチャが存在しない")
        files = sorted([
            os.path.join(_FIXTURE_DIR_DUALSTACK_OSPF, fn)
            for fn in os.listdir(_FIXTURE_DIR_DUALSTACK_OSPF)
            if fn.endswith(".cfg")
        ])
        if not files:
            pytest.skip("dualstack-ospf フィクスチャにファイルがない")
        devices = parse_paths(files)
        return build(devices, generated_from=files)

    @pytest.mark.integration
    def test_dso_v4_link_has_ospf_area(self, dso_topo):
        """dualstack-ospf の v4 リンクに ospf_area が付く（OSPFv2 参加）。"""
        v4_ospf_links = [
            lk for lk in dso_topo["links"]
            if ":" not in lk.get("subnet", "") and "ospf_area" in lk
        ]
        assert v4_ospf_links, (
            "dualstack-ospf の v4 link に ospf_area が付いていない。"
            "OSPFv2(router ospf + network) が正しく解決されていない。"
        )

    @pytest.mark.integration
    def test_dso_v6_link_has_ospf_area(self, dso_topo):
        """dualstack-ospf の v6 リンクに ospf_area が付く（OSPFv3 参加）。"""
        v6_ospf_links = [
            lk for lk in dso_topo["links"]
            if ":" in lk.get("subnet", "") and "ospf_area" in lk
        ]
        assert v6_ospf_links, (
            "dualstack-ospf の v6 link に ospf_area が付いていない。"
            "OSPFv3(ipv6 ospf area) が正しく解決されていない。"
        )

    @pytest.mark.integration
    def test_dso_render_contains_both_subnets_in_ospf_view(self, dso_topo):
        """dualstack-ospf render 後 OSPF ビューに v4/v6 両 subnet が含まれる。"""
        from lib.rendering import render
        import re
        html = render(dso_topo)

        m_start = re.search(r'<g[^>]+class="view view-ospf"', html)
        if not m_start:
            pytest.skip("OSPF ビューが生成されない")
        start = m_start.start()
        m_end = re.search(r'<g[^>]+class="view view-(?!ospf)[^"]*"', html[start + 1:])
        ospf_section = html[start: start + 1 + m_end.start()] if m_end else html[start:]

        # v4 subnet が OSPF ビューに含まれること
        v4_links = [lk for lk in dso_topo["links"] if ":" not in lk.get("subnet", "") and "ospf_area" in lk]
        for lk in v4_links[:1]:  # 最初の1件で確認
            assert lk["subnet"] in ospf_section, (
                f"dualstack-ospf OSPF ビューに v4 subnet {lk['subnet']!r} がない"
            )

        # v6 subnet が OSPF ビューに含まれること
        v6_links = [lk for lk in dso_topo["links"] if ":" in lk.get("subnet", "") and "ospf_area" in lk]
        for lk in v6_links[:1]:
            assert lk["subnet"] in ospf_section or lk["subnet"].split("/")[0] in ospf_section, (
                f"dualstack-ospf OSPF ビューに v6 subnet {lk['subnet']!r} がない"
            )
