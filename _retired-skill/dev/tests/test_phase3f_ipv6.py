"""
TDD テスト: Phase 3F — IPv6 dual-stack パース + v6 結線推論

テスト方針:
  RED  → GREEN → REFACTOR サイクルで実装を駆動する

対象範囲:
  1. lib/parsers/base.py         — Interface.addresses フィールド追加
  2. lib/parsers/cisco_ios.py    — ipv6 address / secondary ip パース → addresses
  3. lib/parsers/juniper_junos.py— family inet6 address パース → addresses
  4. scripts/build_topology.py  — addresses dict 出力・ip 派生ヘルパー・v6 結線推論・link-local 除外
  5. lib/topology_io.py          — round-trip（旧→新 addresses 合成・新→旧 ip 派生）
  6. lib/rendering/svg.py        — _build_ip_to_device / _build_ip_to_iface_id v6 対応
  7. 後方互換テスト             — 既存 IPv4 fixture で links/segments/routing 不変・addresses 追加のみ

不変条件:
  - 決定性: 同一 config → 同一出力（addresses は af/ip 昇順ソート）
  - link-local（fe80::/10）は結線推論から除外
  - IPv4-only config では links/segments が完全一致（後方互換）
"""

from __future__ import annotations

import ipaddress
import os
import sys
import tempfile
import pytest


# ================================================================
# ヘルパー: テスト用 Interface / Device ファクトリ
# ================================================================

def make_device_from_parsers(hostname: str, vendor: str, interfaces):
    """テスト用 Device を作るファクトリ（parsers.base の Device を使用）"""
    from lib.parsers.base import Device, BgpNeighbor, OspfNetwork, StaticRoute
    return Device(
        hostname=hostname,
        vendor=vendor,
        asn=None,
        interfaces=interfaces,
        bgp=[],
        ospf=[],
        static=[],
    )


def make_iface_with_addresses(name: str, ip=None, description=None, shutdown=False, addresses=None):
    """addresses フィールドを持つ Interface を作るファクトリ"""
    from lib.parsers.base import Interface
    iface = Interface(name=name, ip=ip, description=description, shutdown=shutdown)
    if addresses is not None:
        iface.addresses = addresses
    return iface


# ================================================================
# セクション 1: lib/parsers/base.py — Interface.addresses
# ================================================================

class TestBaseAddresses:
    """Interface が addresses: list[dict] フィールドを持つことを検証する。"""

    @pytest.mark.unit
    def test_interface_has_addresses_field(self):
        """Interface dataclass に addresses フィールドが存在する。"""
        from lib.parsers.base import Interface
        iface = Interface(name="Gi0/0", ip="10.0.0.1/30", description=None)
        assert hasattr(iface, "addresses"), "Interface に addresses フィールドが必要"

    @pytest.mark.unit
    def test_addresses_default_empty_list(self):
        """addresses のデフォルトは空リスト。"""
        from lib.parsers.base import Interface
        iface = Interface(name="Gi0/0", ip=None, description=None)
        assert iface.addresses == []

    @pytest.mark.unit
    def test_address_dict_structure(self):
        """addresses エントリは af / ip / prefix キーを持つ dict。"""
        from lib.parsers.base import Interface
        addr = {"af": "v4", "ip": "10.0.0.1", "prefix": 30}
        iface = Interface(name="Gi0/0", ip="10.0.0.1/30", description=None, addresses=[addr])
        assert iface.addresses[0]["af"] == "v4"
        assert iface.addresses[0]["ip"] == "10.0.0.1"
        assert iface.addresses[0]["prefix"] == 30

    @pytest.mark.unit
    def test_address_v6_dict_structure(self):
        """addresses に v6 エントリを格納できる（af='v6'・ipaddress 正規化済み）。"""
        from lib.parsers.base import Interface
        addr = {"af": "v6", "ip": "2001:db8::1", "prefix": 64}
        iface = Interface(name="Gi0/0", ip=None, description=None, addresses=[addr])
        assert iface.addresses[0]["af"] == "v6"
        assert iface.addresses[0]["prefix"] == 64

    @pytest.mark.unit
    def test_address_secondary_flag(self):
        """secondary フィールドを持つ v4 アドレスを格納できる。"""
        from lib.parsers.base import Interface
        addr = {"af": "v4", "ip": "10.0.0.5", "prefix": 30, "secondary": True}
        iface = Interface(name="Gi0/0", ip="10.0.0.1/30", description=None, addresses=[addr])
        assert iface.addresses[0].get("secondary") is True

    @pytest.mark.unit
    def test_address_scope_field(self):
        """scope フィールドを持つ v6 アドレス（link-local 等）を格納できる。"""
        from lib.parsers.base import Interface
        addr = {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"}
        iface = Interface(name="Gi0/0", ip=None, description=None, addresses=[addr])
        assert iface.addresses[0].get("scope") == "link-local"


# ================================================================
# セクション 2: Cisco IOS パーサ — addresses パース
# ================================================================

IOS_DUALSTACK = """\
!
hostname DS-R1
!
interface GigabitEthernet0/0
 description to-DS-R2
 ip address 10.0.0.1 255.255.255.252
 ip address 10.0.0.5 255.255.255.252 secondary
 ipv6 address 2001:db8:1::1/127
 ipv6 address fe80::1 link-local
 no shutdown
!
interface GigabitEthernet0/1
 description LAN
 ip address 192.168.1.1 255.255.255.0
 ipv6 address 2001:db8:2::1/64
!
interface GigabitEthernet0/2
 description v6-only
 ipv6 address 2001:db8:3::1/127
 ipv6 address fe80::11 link-local
 no shutdown
!
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
 ipv6 address 2001:db8:ff::1/128
!
end
"""

IOS_V4_ONLY = """\
!
hostname V4-R1
!
interface GigabitEthernet0/0
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 ip address 192.168.1.1 255.255.255.0
!
end
"""


class TestCiscoIosAddresses:
    """Cisco IOS パーサが addresses を正しくパースする。"""

    @pytest.fixture(scope="class")
    def parsed(self):
        from lib.parsers.cisco_ios import parse
        return parse(IOS_DUALSTACK)

    @pytest.mark.unit
    def test_primary_v4_in_addresses(self, parsed):
        """primary ip address が addresses に v4 エントリとして含まれる。"""
        iface = next(i for i in parsed.interfaces if "GigabitEthernet0/0" in i.name)
        v4_addrs = [a for a in iface.addresses if a["af"] == "v4" and not a.get("secondary")]
        assert len(v4_addrs) == 1
        assert v4_addrs[0]["ip"] == "10.0.0.1"
        assert v4_addrs[0]["prefix"] == 30

    @pytest.mark.unit
    def test_secondary_v4_in_addresses(self, parsed):
        """secondary ip address が addresses に secondary=True の v4 エントリとして含まれる。"""
        iface = next(i for i in parsed.interfaces if "GigabitEthernet0/0" in i.name)
        secondary_addrs = [a for a in iface.addresses if a.get("secondary")]
        assert len(secondary_addrs) == 1
        assert secondary_addrs[0]["ip"] == "10.0.0.5"
        assert secondary_addrs[0]["prefix"] == 30

    @pytest.mark.unit
    def test_ipv6_global_in_addresses(self, parsed):
        """ipv6 address（グローバル）が af='v6' エントリとして addresses に含まれる。"""
        iface = next(i for i in parsed.interfaces if "GigabitEthernet0/0" in i.name)
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        ips = [a["ip"] for a in v6_addrs]
        # 正規化済みアドレスが含まれる（fe80 含む全て）
        # 2001:db8:1::1 が含まれる
        assert any("2001:db8:1::1" in ip or ip.startswith("2001:db8:1:") for ip in ips) or \
               any(str(ipaddress.ip_address("2001:db8:1::1")) in ip for ip in ips), \
               f"v6 global address not found in {ips}"

    @pytest.mark.unit
    def test_ipv6_linklocal_in_addresses_with_scope(self, parsed):
        """ipv6 address link-local が scope='link-local' エントリとして addresses に含まれる。"""
        iface = next(i for i in parsed.interfaces if "GigabitEthernet0/0" in i.name)
        ll_addrs = [a for a in iface.addresses if a.get("scope") == "link-local"]
        assert len(ll_addrs) >= 1
        ll_ips = [a["ip"] for a in ll_addrs]
        assert any("fe80" in ip.lower() for ip in ll_ips), f"fe80 not found in {ll_ips}"

    @pytest.mark.unit
    def test_ip_derived_from_primary_v4(self, parsed):
        """ip フィールドは addresses 中の最初の非 secondary v4 から派生する（後方互換）。"""
        iface = next(i for i in parsed.interfaces if "GigabitEthernet0/0" in i.name)
        assert iface.ip == "10.0.0.1/30"

    @pytest.mark.unit
    def test_v6_only_if_ip_null(self, parsed):
        """v6-only インターフェースの ip フィールドは null。"""
        iface = next(i for i in parsed.interfaces if "GigabitEthernet0/2" in i.name)
        assert iface.ip is None, f"expected None but got {iface.ip!r}"
        # v6 アドレスは addresses にある
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        assert len(v6_addrs) >= 1

    @pytest.mark.unit
    def test_addresses_sorted_deterministically(self, parsed):
        """addresses は af(v4<v6)/ip 順でソートされており決定的。"""
        iface = next(i for i in parsed.interfaces if "GigabitEthernet0/0" in i.name)
        addrs = iface.addresses
        # v4 が v6 より先に来る
        afs = [a["af"] for a in addrs]
        last_v4 = max((i for i, a in enumerate(afs) if a == "v4"), default=-1)
        first_v6 = min((i for i, a in enumerate(afs) if a == "v6"), default=len(afs))
        assert last_v4 < first_v6, f"v4 should come before v6, got afs={afs}"

    @pytest.mark.unit
    def test_v4_only_interface_backward_compat(self):
        """IPv4-only IF でも addresses に v4 エントリが含まれ ip が維持される（後方互換）。"""
        from lib.parsers.cisco_ios import parse
        dev = parse(IOS_V4_ONLY)
        iface = next(i for i in dev.interfaces if "GigabitEthernet0/0" in i.name)
        assert iface.ip == "10.0.0.1/30"
        v4_addrs = [a for a in iface.addresses if a["af"] == "v4"]
        assert len(v4_addrs) == 1
        assert v4_addrs[0]["ip"] == "10.0.0.1"

    @pytest.mark.unit
    def test_loopback_has_v4_and_v6(self, parsed):
        """Loopback0 に v4 と v6 両方のアドレスが含まれる。"""
        iface = next(i for i in parsed.interfaces if "Loopback0" in i.name)
        afs = {a["af"] for a in iface.addresses}
        assert "v4" in afs
        assert "v6" in afs

    @pytest.mark.unit
    def test_v6_address_normalized(self, parsed):
        """v6 アドレスは ipaddress で正規化された形式（省略形）で格納される。"""
        iface = next(i for i in parsed.interfaces if "Loopback0" in i.name)
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        assert len(v6_addrs) >= 1
        ip_str = v6_addrs[0]["ip"]
        # ipaddress で往復できることを確認（正規化済み）
        parsed_back = str(ipaddress.ip_address(ip_str))
        assert ip_str == parsed_back, f"Not normalized: {ip_str!r} vs {parsed_back!r}"


# ================================================================
# セクション 3: Juniper JunOS パーサ — addresses パース
# ================================================================

JUNOS_DUALSTACK = """\
set system host-name DS-R2
set interfaces ge-0/0/0 description to-DS-R1
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8:1::0/127
set interfaces ge-0/0/1 description LAN2
set interfaces ge-0/0/1 unit 0 family inet address 192.168.2.1/24
set interfaces ge-0/0/1 unit 0 family inet6 address 2001:db8:4::1/64
set interfaces ge-0/0/2 description v6-only-link-to-R1
set interfaces ge-0/0/2 unit 0 family inet6 address 2001:db8:3::0/127
set interfaces lo0 unit 0 family inet address 2.2.2.2/32
set interfaces lo0 unit 0 family inet6 address 2001:db8:ff::2/128
set routing-options autonomous-system 65002
"""

JUNOS_V4_ONLY = """\
set system host-name V4-R2
set interfaces ge-0/0/0 description to-peer
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30
set interfaces ge-0/0/1 unit 0 family inet address 192.168.2.1/24
set routing-options autonomous-system 65002
"""


class TestJuniperJunosAddresses:
    """Juniper JunOS パーサが addresses を正しくパースする。"""

    @pytest.fixture(scope="class")
    def parsed(self):
        from lib.parsers.juniper_junos import parse
        return parse(JUNOS_DUALSTACK)

    @pytest.mark.unit
    def test_inet_v4_in_addresses(self, parsed):
        """family inet address が v4 エントリとして addresses に含まれる。"""
        iface = next(i for i in parsed.interfaces if i.name == "ge-0/0/0")
        v4_addrs = [a for a in iface.addresses if a["af"] == "v4"]
        assert len(v4_addrs) == 1
        assert v4_addrs[0]["ip"] == "10.0.0.2"
        assert v4_addrs[0]["prefix"] == 30

    @pytest.mark.unit
    def test_inet6_v6_in_addresses(self, parsed):
        """family inet6 address が v6 エントリとして addresses に含まれる。"""
        iface = next(i for i in parsed.interfaces if i.name == "ge-0/0/0")
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        assert len(v6_addrs) >= 1

    @pytest.mark.unit
    def test_ip_derived_v4_primary(self, parsed):
        """ip フィールドは addresses 中の最初の非 secondary v4 から派生する。"""
        iface = next(i for i in parsed.interfaces if i.name == "ge-0/0/0")
        assert iface.ip == "10.0.0.2/30"

    @pytest.mark.unit
    def test_v6_only_if_ip_null(self, parsed):
        """v6-only インターフェース（ge-0/0/2）の ip は null。"""
        iface = next(i for i in parsed.interfaces if i.name == "ge-0/0/2")
        assert iface.ip is None
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        assert len(v6_addrs) >= 1

    @pytest.mark.unit
    def test_loopback_both_v4_and_v6(self, parsed):
        """lo0 に v4 と v6 両方のアドレスが含まれる。"""
        iface = next(i for i in parsed.interfaces if i.name == "lo0")
        afs = {a["af"] for a in iface.addresses}
        assert "v4" in afs
        assert "v6" in afs

    @pytest.mark.unit
    def test_v4_only_backward_compat(self):
        """IPv4-only JunOS config でも addresses に v4 エントリが含まれ ip が維持される。"""
        from lib.parsers.juniper_junos import parse
        dev = parse(JUNOS_V4_ONLY)
        iface = next(i for i in dev.interfaces if i.name == "ge-0/0/0")
        assert iface.ip == "10.0.0.2/30"
        v4_addrs = [a for a in iface.addresses if a["af"] == "v4"]
        assert len(v4_addrs) == 1

    @pytest.mark.unit
    def test_addresses_sorted_v4_before_v6(self, parsed):
        """addresses は v4 が v6 より先にソートされる。"""
        iface = next(i for i in parsed.interfaces if i.name == "ge-0/0/0")
        afs = [a["af"] for a in iface.addresses]
        last_v4 = max((i for i, a in enumerate(afs) if a == "v4"), default=-1)
        first_v6 = min((i for i, a in enumerate(afs) if a == "v6"), default=len(afs))
        assert last_v4 < first_v6, f"v4 should come before v6, got {afs}"

    @pytest.mark.unit
    def test_v6_address_normalized(self, parsed):
        """v6 アドレスは ipaddress で正規化された形式で格納される。"""
        iface = next(i for i in parsed.interfaces if i.name == "ge-0/0/0")
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        assert len(v6_addrs) >= 1
        ip_str = v6_addrs[0]["ip"]
        parsed_back = str(ipaddress.ip_address(ip_str))
        assert ip_str == parsed_back


# ================================================================
# セクション 4: build_topology.py — addresses 出力 + v6 結線推論
# ================================================================

class TestBuildTopologyAddresses:
    """build() が interfaces dict に addresses を出力する。"""

    @pytest.fixture(scope="class")
    def topology_dualstack(self):
        """dualstack fixture から topology を構築する。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_dir = os.path.join(os.path.dirname(__file__), "..", "evals", "inputs", "dualstack")
        paths = [
            os.path.join(fixture_dir, "r1.cfg"),
            os.path.join(fixture_dir, "r2.conf"),
        ]
        devices = parse_paths(paths)
        return build(devices, generated_from=paths)

    @pytest.mark.unit
    def test_interfaces_have_addresses_key(self, topology_dualstack):
        """topology['interfaces'] の全エントリが addresses キーを持つ。"""
        for iface in topology_dualstack["interfaces"]:
            assert "addresses" in iface, f"interface {iface['id']} に addresses がない"

    @pytest.mark.unit
    def test_addresses_is_list(self, topology_dualstack):
        """addresses は常にリスト型。"""
        for iface in topology_dualstack["interfaces"]:
            assert isinstance(iface["addresses"], list)

    @pytest.mark.unit
    def test_dualstack_if_addresses_contains_v4_and_v6(self, topology_dualstack):
        """dual-stack IF の addresses に v4 と v6 の両方が含まれる。"""
        iface = next(
            i for i in topology_dualstack["interfaces"]
            if i["name"] == "GigabitEthernet0/0"
        )
        afs = {a["af"] for a in iface["addresses"]}
        assert "v4" in afs, f"v4 not in addresses: {iface['addresses']}"
        assert "v6" in afs, f"v6 not in addresses: {iface['addresses']}"

    @pytest.mark.unit
    def test_ip_field_is_primary_v4(self, topology_dualstack):
        """ip フィールドは非 secondary v4 の CIDR（後方互換）。"""
        iface = next(
            i for i in topology_dualstack["interfaces"]
            if i["name"] == "GigabitEthernet0/0"
        )
        assert iface["ip"] == "10.0.0.1/30"

    @pytest.mark.unit
    def test_secondary_in_addresses(self, topology_dualstack):
        """secondary v4 アドレスが addresses に secondary=True で含まれる。"""
        iface = next(
            i for i in topology_dualstack["interfaces"]
            if i["name"] == "GigabitEthernet0/0"
        )
        secondary_entries = [a for a in iface["addresses"] if a.get("secondary")]
        assert len(secondary_entries) >= 1

    @pytest.mark.unit
    def test_v6_only_if_ip_null_in_topology(self, topology_dualstack):
        """v6-only IF の ip は null で addresses に v6 エントリが含まれる。"""
        iface = next(
            i for i in topology_dualstack["interfaces"]
            if i["name"] == "GigabitEthernet0/2"
        )
        assert iface["ip"] is None
        v6_addrs = [a for a in iface["addresses"] if a["af"] == "v6"]
        assert len(v6_addrs) >= 1

    @pytest.mark.unit
    def test_addresses_sorted_v4_before_v6_in_topology(self, topology_dualstack):
        """topology の addresses も v4 → v6 の順でソートされている。"""
        for iface in topology_dualstack["interfaces"]:
            addrs = iface["addresses"]
            afs = [a["af"] for a in addrs]
            last_v4 = max((i for i, af in enumerate(afs) if af == "v4"), default=-1)
            first_v6 = min((i for i, af in enumerate(afs) if af == "v6"), default=len(afs))
            assert last_v4 < first_v6 or last_v4 == -1 or first_v6 == len(afs), \
                f"iface {iface['id']} addresses not sorted: {afs}"


class TestBuildTopologyV6Links:
    """build() が v6 サブネット一致で v6 link/segment を生成する。"""

    @pytest.fixture(scope="class")
    def topology_dualstack(self):
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_dir = os.path.join(os.path.dirname(__file__), "..", "evals", "inputs", "dualstack")
        paths = [
            os.path.join(fixture_dir, "r1.cfg"),
            os.path.join(fixture_dir, "r2.conf"),
        ]
        devices = parse_paths(paths)
        return build(devices, generated_from=paths)

    @pytest.mark.unit
    def test_v4_link_exists(self, topology_dualstack):
        """10.0.0.0/30 の v4 p2p リンクが存在する。"""
        subnets = [l["subnet"] for l in topology_dualstack["links"]]
        assert "10.0.0.0/30" in subnets

    @pytest.mark.unit
    def test_v6_p2p_link_exists(self, topology_dualstack):
        """2001:db8:1::/127 の v6 p2p リンクが存在する（R1 ge0/0 ↔ R2 ge-0/0/0）。"""
        subnets = [l["subnet"] for l in topology_dualstack["links"]]
        # /127 は p2p で 2 メンバー
        assert "2001:db8:1::/127" in subnets, f"v6 /127 link not found in {subnets}"

    @pytest.mark.unit
    def test_v6_only_p2p_link_exists(self, topology_dualstack):
        """2001:db8:3::/127 の v6-only p2p リンクが存在する（R1 ge0/2 ↔ R2 ge-0/0/2）。"""
        subnets = [l["subnet"] for l in topology_dualstack["links"]]
        assert "2001:db8:3::/127" in subnets, f"v6-only /127 link not found in {subnets}"

    @pytest.mark.unit
    def test_linklocal_not_in_links(self, topology_dualstack):
        """link-local（fe80::/10）サブネットはリンクに含まれない。"""
        for link in topology_dualstack["links"]:
            subnet = link["subnet"]
            try:
                net = ipaddress.ip_network(subnet, strict=False)
                if net.version == 6:
                    assert not net.is_link_local, f"link-local subnet found in links: {subnet}"
            except ValueError:
                pass

    @pytest.mark.unit
    def test_linklocal_not_in_segments(self, topology_dualstack):
        """link-local サブネットはセグメントに含まれない。"""
        for seg in topology_dualstack["segments"]:
            subnet = seg["subnet"]
            try:
                net = ipaddress.ip_network(subnet, strict=False)
                if net.version == 6:
                    assert not net.is_link_local, f"link-local subnet found in segments: {subnet}"
            except ValueError:
                pass

    @pytest.mark.unit
    def test_v6_link_has_correct_af_independent_devices(self, topology_dualstack):
        """v6 リンクの a_device と b_device は異なる機器。"""
        v6_links = [
            l for l in topology_dualstack["links"]
            if ":" in l.get("subnet", "")
        ]
        for link in v6_links:
            assert link["a_device"] != link["b_device"], \
                f"self-loop v6 link: {link}"

    @pytest.mark.unit
    def test_v6_link_kind_inferred_subnet(self, topology_dualstack):
        """v6 リンクの kind は 'inferred-subnet'。"""
        v6_links = [
            l for l in topology_dualstack["links"]
            if ":" in l.get("subnet", "")
        ]
        for link in v6_links:
            assert link["kind"] == "inferred-subnet"

    @pytest.mark.unit
    def test_v4_links_unchanged_from_v4_only_config(self):
        """IPv4-only config では links が以前と完全一致する（後方互換）。"""
        from lib.parsers.base import Device, Interface
        from scripts.build_topology import build

        # IPv4-only devices（addresses なし相当: ip のみ）
        dev1 = Device(
            hostname="R1", vendor="cisco_ios", asn=None,
            interfaces=[
                Interface(name="Gi0/0", ip="10.0.0.1/30", description=None),
            ],
            bgp=[], ospf=[], static=[],
        )
        dev2 = Device(
            hostname="R2", vendor="cisco_ios", asn=None,
            interfaces=[
                Interface(name="Gi0/0", ip="10.0.0.2/30", description=None),
            ],
            bgp=[], ospf=[], static=[],
        )

        topo = build([dev1, dev2], generated_from=["r1.cfg", "r2.cfg"])
        # 旧動作と同じ: 1 リンク / 10.0.0.0/30
        assert len(topo["links"]) == 1
        assert topo["links"][0]["subnet"] == "10.0.0.0/30"
        assert len(topo["segments"]) == 0


# ================================================================
# セクション 5: 後方互換テスト — 既存 IPv4 fixture で不変
# ================================================================

class TestBackwardCompatibilityIPv4Fixtures:
    """既存の IPv4-only fixture で links/segments/routing が不変であることを検証する。"""

    @pytest.fixture(scope="class")
    def topo_ebgp(self):
        """既存 ebgp-p2p fixture の topology。"""
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_dir = os.path.join(os.path.dirname(__file__), "..", "evals", "inputs", "ebgp-p2p")
        paths = [
            os.path.join(fixture_dir, "rA.cfg"),
            os.path.join(fixture_dir, "rB.cfg"),
        ]
        devices = parse_paths(paths)
        return build(devices, generated_from=paths)

    @pytest.mark.unit
    def test_ebgp_links_unchanged(self, topo_ebgp):
        """ebgp-p2p fixture の links は Phase 3F で不変（subnet・kind・a_device・b_device・a_if・b_if）。"""
        # ebgp-p2p: rA.cfg の GE0/0 (10.1.0.1/30) ↔ rB.cfg の GE0/0 (10.1.0.2/30)
        links = topo_ebgp["links"]
        assert len(links) == 1
        link = links[0]
        assert link["subnet"] == "10.1.0.0/30"
        assert link["kind"] == "inferred-subnet"
        # a_device < b_device の安定ソート
        assert link["a_device"] < link["b_device"]

    @pytest.mark.unit
    def test_ebgp_segments_unchanged(self, topo_ebgp):
        """ebgp-p2p fixture の segments は Phase 3F で不変（空）。"""
        assert topo_ebgp["segments"] == []

    @pytest.mark.unit
    def test_ebgp_routing_unchanged(self, topo_ebgp):
        """ebgp-p2p fixture の routing.bgp が Phase 3F で不変。"""
        bgp = topo_ebgp["routing"]["bgp"]
        assert len(bgp) >= 1
        # bgp エントリに type='ebgp' が含まれる
        types = {b["type"] for b in bgp}
        assert "ebgp" in types

    @pytest.mark.unit
    def test_ipv4_interfaces_have_addresses_addition_only(self, topo_ebgp):
        """IPv4-only fixture の interfaces に addresses キーが追加されているが既存キー値は不変。"""
        EXPECTED_KEYS = {
            "id", "device", "name", "ip", "vlan", "description",
            "shutdown", "admin_status", "oper_status", "mtu",
            "speed", "duplex", "l2_l3", "switchport", "encapsulation", "source",
        }
        for iface in topo_ebgp["interfaces"]:
            # addresses が追加されていることを確認
            assert "addresses" in iface
            # 既存キーが全て残っている
            for key in EXPECTED_KEYS:
                assert key in iface, f"既存キー {key!r} が iface {iface['id']} から失われた"
            # ip フィールドが addresses から派生した正しい値のまま（v4-only なら従来通り）
            if iface["ip"] is not None:
                v4_addrs = [a for a in iface["addresses"] if a["af"] == "v4" and not a.get("secondary")]
                if v4_addrs:
                    expected_ip = f"{v4_addrs[0]['ip']}/{v4_addrs[0]['prefix']}"
                    assert iface["ip"] == expected_ip, \
                        f"ip派生不一致: {iface['ip']!r} vs {expected_ip!r}"


# ================================================================
# セクション 6: topology_io.py — round-trip（旧→新・新→旧）
# ================================================================

class TestTopologyIoRoundTrip:
    """topology_io の dump/load が addresses を含む round-trip で一致する。"""

    @pytest.fixture
    def topology_with_addresses(self, tmp_path):
        """addresses を持つ簡単な topology dict を返すフィクスチャ。"""
        return {
            "title": "Round-trip test",
            "generated_from": ["test.cfg"],
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []}
            ],
            "interfaces": [
                {
                    "id": "r1::Gi0/0",
                    "device": "r1",
                    "name": "Gi0/0",
                    "ip": "10.0.0.1/30",
                    "vlan": None,
                    "description": "test",
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
                        {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
                    ],
                }
            ],
            "links": [],
            "segments": [],
            "routing": {"bgp": [], "ospf": [], "static": []},
        }

    @pytest.mark.integration
    def test_dump_and_load_preserves_addresses(self, topology_with_addresses, tmp_path):
        """dump_topology → load_topology で addresses が保持される。"""
        from lib.topology_io import dump_topology, load_topology

        out_dir = str(tmp_path / "topo")
        dump_topology(topology_with_addresses, out_dir)
        loaded = load_topology(out_dir)

        assert len(loaded["interfaces"]) == 1
        iface = loaded["interfaces"][0]
        assert "addresses" in iface
        assert len(iface["addresses"]) == 2
        v4 = next(a for a in iface["addresses"] if a["af"] == "v4")
        v6 = next(a for a in iface["addresses"] if a["af"] == "v6")
        assert v4["ip"] == "10.0.0.1"
        assert v6["ip"] == "2001:db8::1"

    @pytest.mark.integration
    def test_dump_and_load_ip_preserved(self, topology_with_addresses, tmp_path):
        """dump_topology → load_topology で ip フィールドが保持される。"""
        from lib.topology_io import dump_topology, load_topology

        out_dir = str(tmp_path / "topo2")
        dump_topology(topology_with_addresses, out_dir)
        loaded = load_topology(out_dir)

        iface = loaded["interfaces"][0]
        assert iface["ip"] == "10.0.0.1/30"

    @pytest.mark.integration
    def test_old_format_without_addresses_synthesizes(self, tmp_path):
        """addresses キーがない旧形式の YAML を load_topology するとき addresses を ip から合成する。"""
        from lib.topology_io import dump_topology, load_topology
        import yaml

        # addresses なしの旧形式を直接書く
        os.makedirs(str(tmp_path / "topo_old"), exist_ok=True)
        meta = {"schema_version": "1.0", "title": "old", "generated_from": ["a.cfg"]}
        devices_data = {
            "devices": [
                {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None, "sections": []}
            ],
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
                    # addresses キーなし
                }
            ]
        }
        phys_data = {"links": [], "segments": []}

        for fname, data in [("_meta.yaml", meta), ("devices.yaml", devices_data), ("physical.yaml", phys_data)]:
            with open(str(tmp_path / "topo_old" / fname), "w") as f:
                yaml.safe_dump(data, f, sort_keys=True)

        loaded = load_topology(str(tmp_path / "topo_old"))
        iface = loaded["interfaces"][0]
        assert "addresses" in iface
        # ip=10.0.0.1/30 から v4 アドレスが合成される
        v4_addrs = [a for a in iface["addresses"] if a["af"] == "v4"]
        assert len(v4_addrs) == 1
        assert v4_addrs[0]["ip"] == "10.0.0.1"
        assert v4_addrs[0]["prefix"] == 30

    @pytest.mark.integration
    def test_round_trip_deterministic(self, topology_with_addresses, tmp_path):
        """同一 topology を2回 dump/load しても同一結果（決定性）。"""
        from lib.topology_io import dump_topology, load_topology

        out1 = str(tmp_path / "rt1")
        out2 = str(tmp_path / "rt2")

        dump_topology(topology_with_addresses, out1)
        loaded1 = load_topology(out1)
        dump_topology(loaded1, out2)
        loaded2 = load_topology(out2)

        assert loaded1["interfaces"] == loaded2["interfaces"]


# ================================================================
# セクション 7: lib/rendering/svg.py — v6 逆引き対応
# ================================================================

class TestSvgIpToDeviceV6:
    """_build_ip_to_device と _build_ip_to_iface_id が v6 アドレスを解決する。"""

    @pytest.mark.unit
    def test_build_ip_to_device_includes_v6(self):
        """_build_ip_to_device が addresses から v6 IP も逆引きできる。"""
        from lib.rendering.svg import _build_ip_to_device

        interfaces = [
            {
                "id": "r1::Gi0/0",
                "device": "r1",
                "ip": "10.0.0.1/30",
                "addresses": [
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
                ],
            }
        ]

        result = _build_ip_to_device(interfaces)
        assert result.get("10.0.0.1") == "r1"
        assert result.get("2001:db8::1") == "r1", f"v6 not found: {result}"

    @pytest.mark.unit
    def test_build_ip_to_iface_id_includes_v6(self):
        """_build_ip_to_iface_id が addresses から v6 IP も逆引きできる。"""
        from lib.rendering.svg import _build_ip_to_iface_id

        interfaces = [
            {
                "id": "r1::Gi0/0",
                "device": "r1",
                "ip": "10.0.0.1/30",
                "addresses": [
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
                ],
            }
        ]

        result = _build_ip_to_iface_id(interfaces)
        assert result.get("10.0.0.1") == "r1::Gi0/0"
        assert result.get("2001:db8::1") == "r1::Gi0/0", f"v6 not found: {result}"

    @pytest.mark.unit
    def test_build_ip_to_device_no_addresses_falls_back_to_ip(self):
        """addresses キーがない旧形式でも ip フィールドから正しく逆引きできる（後方互換）。"""
        from lib.rendering.svg import _build_ip_to_device

        interfaces = [
            {
                "id": "r1::Gi0/0",
                "device": "r1",
                "ip": "10.0.0.1/30",
                # addresses キーなし
            }
        ]

        result = _build_ip_to_device(interfaces)
        assert result.get("10.0.0.1") == "r1"

    @pytest.mark.unit
    def test_build_ip_to_device_v6_only_if(self):
        """v6-only IF（ip=null, addresses に v6 のみ）でも v6 IP が逆引きできる。"""
        from lib.rendering.svg import _build_ip_to_device

        interfaces = [
            {
                "id": "r1::Gi0/2",
                "device": "r1",
                "ip": None,
                "addresses": [
                    {"af": "v6", "ip": "2001:db8:3::1", "prefix": 127},
                ],
            }
        ]

        result = _build_ip_to_device(interfaces)
        assert result.get("2001:db8:3::1") == "r1"

    @pytest.mark.unit
    def test_build_ip_to_device_null_ip_no_addresses(self):
        """ip=null で addresses もない IF はマップに含まれない（クラッシュしない）。"""
        from lib.rendering.svg import _build_ip_to_device

        interfaces = [
            {
                "id": "r1::Gi0/3",
                "device": "r1",
                "ip": None,
                # addresses キーなし
            }
        ]

        result = _build_ip_to_device(interfaces)
        assert "r1::Gi0/3" not in result.values()


# ================================================================
# セクション 8: rendering — v6 IF でクラッシュしない（smoke test）
# ================================================================

class TestRenderingDualstack:
    """dual-stack topology を render() しても例外が発生しない。"""

    @pytest.fixture(scope="class")
    def topology_dualstack(self):
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        fixture_dir = os.path.join(os.path.dirname(__file__), "..", "evals", "inputs", "dualstack")
        paths = [
            os.path.join(fixture_dir, "r1.cfg"),
            os.path.join(fixture_dir, "r2.conf"),
        ]
        devices = parse_paths(paths)
        return build(devices, generated_from=paths)

    @pytest.mark.integration
    def test_render_does_not_crash(self, topology_dualstack):
        """dual-stack topology の render() が例外なく HTML を返す。"""
        from lib.rendering import render
        html = render(topology_dualstack)
        assert isinstance(html, str)
        assert len(html) > 100

    @pytest.mark.integration
    def test_render_contains_v6_subnet_label(self, topology_dualstack):
        """render() した HTML に v6 サブネット文字列が含まれる。"""
        from lib.rendering import render
        html = render(topology_dualstack)
        # v6 link subnet が含まれる
        assert "2001:db8:1::/127" in html or "2001:db8:1::" in html, \
            "v6 subnet not found in rendered HTML"

    @pytest.mark.integration
    def test_render_v4_topology_unchanged(self):
        """IPv4-only topology の render() 結果に影響がない（smoke test）。"""
        from lib.topology_io import load_topology
        from lib.rendering import render
        examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples")
        topo = load_topology(os.path.join(examples_dir, "topology"))
        html = render(topo)
        assert "10.0.0.0/30" in html  # 既存 v4 リンクが含まれる


# ================================================================
# セクション 9: ip 派生ヘルパー単体テスト
# ================================================================

class TestIpDerivationHelper:
    """build_topology._derive_ip_from_addresses の挙動を検証する。"""

    @pytest.mark.unit
    def test_derive_ip_first_nonsecondary_v4(self):
        """非 secondary v4 の最初のエントリから ip が導出される。"""
        from scripts.build_topology import _derive_ip_from_addresses
        addrs = [
            {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
            {"af": "v4", "ip": "10.0.0.5", "prefix": 30, "secondary": True},
            {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
        ]
        result = _derive_ip_from_addresses(addrs)
        assert result == "10.0.0.1/30"

    @pytest.mark.unit
    def test_derive_ip_v6_only_returns_none(self):
        """v4 アドレスがない場合（v6-only）は None を返す。"""
        from scripts.build_topology import _derive_ip_from_addresses
        addrs = [
            {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
        ]
        result = _derive_ip_from_addresses(addrs)
        assert result is None

    @pytest.mark.unit
    def test_derive_ip_empty_list_returns_none(self):
        """空リストは None を返す。"""
        from scripts.build_topology import _derive_ip_from_addresses
        result = _derive_ip_from_addresses([])
        assert result is None

    @pytest.mark.unit
    def test_derive_ip_all_secondary_returns_none(self):
        """全 v4 が secondary の場合は None を返す。"""
        from scripts.build_topology import _derive_ip_from_addresses
        addrs = [
            {"af": "v4", "ip": "10.0.0.5", "prefix": 30, "secondary": True},
        ]
        result = _derive_ip_from_addresses(addrs)
        assert result is None

    @pytest.mark.unit
    def test_derive_ip_link_local_not_selected(self):
        """link-local v6 が混在していても v4-only なら v4 から派生する。"""
        from scripts.build_topology import _derive_ip_from_addresses
        addrs = [
            {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
            {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
        ]
        result = _derive_ip_from_addresses(addrs)
        assert result == "10.0.0.1/30"


# ================================================================
# セクション 10: addresses ソートユーティリティ
# ================================================================

class TestAddressSorting:
    """addresses の決定的ソートを検証する。"""

    @pytest.mark.unit
    def test_sort_addresses_v4_before_v6(self):
        """_sort_addresses が v4 を v6 より先に並べる。"""
        from scripts.build_topology import _sort_addresses
        addrs = [
            {"af": "v6", "ip": "2001:db8::2", "prefix": 64},
            {"af": "v4", "ip": "192.168.1.1", "prefix": 24},
        ]
        sorted_addrs = _sort_addresses(addrs)
        assert sorted_addrs[0]["af"] == "v4"
        assert sorted_addrs[1]["af"] == "v6"

    @pytest.mark.unit
    def test_sort_addresses_same_af_by_ip(self):
        """同一 af 内では ip アドレス昇順にソートされる。"""
        from scripts.build_topology import _sort_addresses
        addrs = [
            {"af": "v4", "ip": "192.168.1.2", "prefix": 24},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
        ]
        sorted_addrs = _sort_addresses(addrs)
        assert sorted_addrs[0]["ip"] == "10.0.0.1"
        assert sorted_addrs[1]["ip"] == "192.168.1.2"

    @pytest.mark.unit
    def test_sort_addresses_empty_list(self):
        """空リストのソートはクラッシュしない。"""
        from scripts.build_topology import _sort_addresses
        result = _sort_addresses([])
        assert result == []

    @pytest.mark.unit
    def test_sort_addresses_deterministic(self):
        """同一入力（順序不定）から常に同じ出力が得られる。"""
        from scripts.build_topology import _sort_addresses
        addrs = [
            {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
            {"af": "v4", "ip": "10.0.0.5", "prefix": 30, "secondary": True},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
            {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
        ]
        result1 = _sort_addresses(addrs)
        result2 = _sort_addresses(list(reversed(addrs)))
        assert result1 == result2


# ================================================================
# セクション 11: レビュー指摘 修正確認テスト（タスク 6-10）
# ================================================================

# ----------------------------------------------------------------
# 共有フィクスチャ: dualstack topology（TestBuildTopologyAddresses と
# TestBuildTopologyV6Links の重複 scope="class" fixture を統一するため
# モジュールスコープで1か所に定義する）
# ----------------------------------------------------------------

@pytest.fixture(scope="module")
def topology_dualstack_module():
    """dualstack fixture（モジュールスコープ）。

    注意: scope="module" は同一モジュール内で共有されるため、
    各テストは topology dict を直接変更してはならない（read-only として扱うこと）。
    変更が必要な場合は copy.deepcopy() して使用する。
    """
    from scripts.parse_configs import parse_paths
    from scripts.build_topology import build
    fixture_dir = os.path.join(os.path.dirname(__file__), "..", "evals", "inputs", "dualstack")
    paths = [
        os.path.join(fixture_dir, "r1.cfg"),
        os.path.join(fixture_dir, "r2.conf"),
    ]
    devices = parse_paths(paths)
    return build(devices, generated_from=paths)


# ----------------------------------------------------------------
# タスク 6: v6 link 端点の具体値検証（HIGH）
# ----------------------------------------------------------------

class TestV6LinkEndpoints:
    """dualstack v6 link の a_device/a_if/b_device/b_if を具体値で検証する。（タスク6）"""

    @pytest.mark.unit
    def test_v6_dualstack_link_1_127_endpoints(self, topology_dualstack_module):
        """2001:db8:1::/127 リンクの端点が DS-R1::GigabitEthernet0/0 ↔ DS-R2::ge-0/0/0 であることを検証。"""
        link = next(
            (l for l in topology_dualstack_module["links"] if l["subnet"] == "2001:db8:1::/127"),
            None,
        )
        assert link is not None, "2001:db8:1::/127 link not found"
        # a < b で安定ソートされているため ds-r1 < ds-r2
        assert link["a_device"] == "ds-r1", f"a_device={link['a_device']!r}"
        assert link["b_device"] == "ds-r2", f"b_device={link['b_device']!r}"
        assert link["a_if"] == "GigabitEthernet0/0", f"a_if={link['a_if']!r}"
        assert link["b_if"] == "ge-0/0/0", f"b_if={link['b_if']!r}"

    @pytest.mark.unit
    def test_v6_only_link_3_127_endpoints(self, topology_dualstack_module):
        """2001:db8:3::/127 リンクの端点が DS-R1::GigabitEthernet0/2 ↔ DS-R2::ge-0/0/2 であることを検証。"""
        link = next(
            (l for l in topology_dualstack_module["links"] if l["subnet"] == "2001:db8:3::/127"),
            None,
        )
        assert link is not None, "2001:db8:3::/127 link not found"
        assert link["a_device"] == "ds-r1", f"a_device={link['a_device']!r}"
        assert link["b_device"] == "ds-r2", f"b_device={link['b_device']!r}"
        assert link["a_if"] == "GigabitEthernet0/2", f"a_if={link['a_if']!r}"
        assert link["b_if"] == "ge-0/0/2", f"b_if={link['b_if']!r}"


# ----------------------------------------------------------------
# タスク 7: 総数/スタブ除外検証（HIGH）
# ----------------------------------------------------------------

class TestDualstackTopologyCount:
    """dualstack topology の links/segments 総数とスタブ除外を検証する。（タスク7）"""

    @pytest.mark.unit
    def test_links_count_is_three(self, topology_dualstack_module):
        """dualstack topology の links は 3 本（v4 p2p + v6 p2p + v6-only p2p）。"""
        links = topology_dualstack_module["links"]
        subnets = [l["subnet"] for l in links]
        assert len(links) == 3, f"Expected 3 links but got {len(links)}: {subnets}"

    @pytest.mark.unit
    def test_segments_count_is_zero(self, topology_dualstack_module):
        """dualstack topology の segments は 0（3 メンバー以上のサブネットなし）。"""
        assert len(topology_dualstack_module["segments"]) == 0

    @pytest.mark.unit
    def test_v6_lan_64_not_in_links(self, topology_dualstack_module):
        """v6 LAN /64（1 メンバー）は links に出ない（スタブ除外）。"""
        subnets = [l["subnet"] for l in topology_dualstack_module["links"]]
        # 2001:db8:2::/64（R1 LAN）と 2001:db8:4::/64（R2 LAN）はスタブ
        assert "2001:db8:2::/64" not in subnets, "R1 LAN /64 should be stub (not in links)"
        assert "2001:db8:4::/64" not in subnets, "R2 LAN /64 should be stub (not in links)"

    @pytest.mark.unit
    def test_linklocal_fe80_not_in_links(self, topology_dualstack_module):
        """link-local（fe80::）サブネットは links に出ない。"""
        for link in topology_dualstack_module["links"]:
            subnet = link["subnet"]
            if ":" in subnet:
                net = ipaddress.ip_network(subnet, strict=False)
                assert not net.is_link_local, f"link-local found in links: {subnet}"

    @pytest.mark.unit
    def test_linklocal_fe80_not_in_segments(self, topology_dualstack_module):
        """link-local（fe80::）サブネットは segments に出ない。"""
        for seg in topology_dualstack_module["segments"]:
            subnet = seg["subnet"]
            if ":" in subnet:
                net = ipaddress.ip_network(subnet, strict=False)
                assert not net.is_link_local, f"link-local found in segments: {subnet}"


# ----------------------------------------------------------------
# タスク 8: base.derive_ip_from_addresses 単体テスト（HIGH）
# ----------------------------------------------------------------

class TestBaseDerivIpFromAddresses:
    """base.derive_ip_from_addresses の挙動を単体で検証する。（タスク8）"""

    @pytest.mark.unit
    def test_derive_ip_secondary_excluded(self):
        """secondary v4 は除外され、最初の非 secondary v4 が選択される。"""
        from lib.parsers.base import derive_ip_from_addresses
        addrs = [
            {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
            {"af": "v4", "ip": "10.0.0.5", "prefix": 30, "secondary": True},
            {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
        ]
        result = derive_ip_from_addresses(addrs)
        assert result == "10.0.0.2/30"

    @pytest.mark.unit
    def test_derive_ip_v6_only_returns_none(self):
        """v4 アドレスがない場合（v6-only）は None を返す。"""
        from lib.parsers.base import derive_ip_from_addresses
        addrs = [
            {"af": "v6", "ip": "2001:db8:3::1", "prefix": 127},
        ]
        result = derive_ip_from_addresses(addrs)
        assert result is None

    @pytest.mark.unit
    def test_derive_ip_deterministic_sort_10_0_0_2_lt_10_0_0_10(self):
        """決定的ソート: 10.0.0.2 < 10.0.0.10（辞書順でなく数値順）で先頭が選択される。"""
        from lib.parsers.base import derive_ip_from_addresses, sort_addresses
        addrs = [
            {"af": "v4", "ip": "10.0.0.10", "prefix": 30},
            {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
        ]
        sorted_addrs = sort_addresses(addrs)
        # 数値昇順なら 10.0.0.2 が先
        assert sorted_addrs[0]["ip"] == "10.0.0.2"
        result = derive_ip_from_addresses(sorted_addrs)
        assert result == "10.0.0.2/30"

    @pytest.mark.unit
    def test_derive_ip_v6_normalized_2001_db8_1_0(self):
        """v6 アドレスは正規化される: 2001:db8:1::0 → 2001:db8:1:: （ipaddress 正規化）。"""
        from lib.parsers.base import normalize_v6
        # 2001:db8:1::0 を正規化すると 2001:db8:1:: になる（末尾ゼロ省略）
        result = normalize_v6("2001:db8:1::0")
        assert result == "2001:db8:1::", f"normalize_v6('2001:db8:1::0') = {result!r}"

    @pytest.mark.unit
    def test_derive_ip_empty_returns_none(self):
        """空リストは None を返す。"""
        from lib.parsers.base import derive_ip_from_addresses
        assert derive_ip_from_addresses([]) is None

    @pytest.mark.unit
    def test_sort_addresses_constants_from_base(self):
        """base.sort_addresses が build_topology._sort_addresses と同一結果を返す。"""
        from lib.parsers.base import sort_addresses
        from scripts.build_topology import _sort_addresses
        addrs = [
            {"af": "v6", "ip": "2001:db8::1", "prefix": 64},
            {"af": "v4", "ip": "10.0.0.5", "prefix": 30, "secondary": True},
            {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
        ]
        assert sort_addresses(addrs) == _sort_addresses(addrs)


# ----------------------------------------------------------------
# タスク 9: JunOS v6 具体値・v6 segment・v4 BGP 回帰（MED）
# ----------------------------------------------------------------

class TestJunosV6Concrete:
    """JunOS v6 アドレスの具体値検証（OR/包含の脆弱アサーションを排除）。（タスク9）"""

    @pytest.fixture(scope="class")
    def parsed(self):
        from lib.parsers.juniper_junos import parse
        return parse(JUNOS_DUALSTACK)

    @pytest.mark.unit
    def test_ge000_v6_exact_address(self, parsed):
        """ge-0/0/0 の v6 アドレスは 2001:db8:1:: （2001:db8:1::0 を正規化した値）。"""
        iface = next(i for i in parsed.interfaces if i.name == "ge-0/0/0")
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        assert len(v6_addrs) == 1, f"Expected exactly 1 v6 addr, got {v6_addrs}"
        assert v6_addrs[0]["ip"] == "2001:db8:1::", f"Unexpected ip: {v6_addrs[0]['ip']!r}"
        assert v6_addrs[0]["prefix"] == 127

    @pytest.mark.unit
    def test_ge002_v6_exact_address(self, parsed):
        """ge-0/0/2 の v6 アドレスは 2001:db8:3:: （2001:db8:3::0 を正規化した値）。"""
        iface = next(i for i in parsed.interfaces if i.name == "ge-0/0/2")
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        assert len(v6_addrs) == 1, f"Expected exactly 1 v6 addr, got {v6_addrs}"
        assert v6_addrs[0]["ip"] == "2001:db8:3::", f"Unexpected ip: {v6_addrs[0]['ip']!r}"
        assert v6_addrs[0]["prefix"] == 127

    @pytest.mark.unit
    def test_lo0_v6_exact_address(self, parsed):
        """lo0 の v6 アドレスは 2001:db8:ff::2 / 128。"""
        iface = next(i for i in parsed.interfaces if i.name == "lo0")
        v6_addrs = [a for a in iface.addresses if a["af"] == "v6"]
        assert len(v6_addrs) == 1, f"Expected exactly 1 v6 addr, got {v6_addrs}"
        assert v6_addrs[0]["ip"] == "2001:db8:ff::2"
        assert v6_addrs[0]["prefix"] == 128

    @pytest.mark.unit
    def test_junos_link_local_scope_in_v6_address(self):
        """JunOS set 形式で fe80:: アドレスに scope:'link-local' が付与される。（タスク2: link-local scope）"""
        from lib.parsers.juniper_junos import parse
        config = """\
set system host-name R-LL
set interfaces ge-0/0/0 unit 0 family inet6 address fe80::1/64
set interfaces ge-0/0/0 unit 0 family inet6 address 2001:db8::1/64
"""
        dev = parse(config)
        iface = dev.interfaces[0]
        ll_addrs = [a for a in iface.addresses if a.get("scope") == "link-local"]
        assert len(ll_addrs) == 1, f"Expected 1 link-local addr, got {ll_addrs}"
        assert ll_addrs[0]["ip"].startswith("fe80:"), f"ip={ll_addrs[0]['ip']!r}"
        # global v6 には scope が付かない
        global_addrs = [a for a in iface.addresses if a["af"] == "v6" and not a.get("scope")]
        assert len(global_addrs) == 1, f"Expected 1 global v6, got {global_addrs}"


# v6 segment テスト用インラインデータ（3機器以上が同一 /64 を共有）
_V6_SEGMENT_CONFIG_R1 = """\
!
hostname seg-R1
!
interface GigabitEthernet0/0
 ipv6 address 2001:db8:10::1/64
 no shutdown
!
end
"""

_V6_SEGMENT_CONFIG_R2 = """\
!
hostname seg-R2
!
interface GigabitEthernet0/0
 ipv6 address 2001:db8:10::2/64
 no shutdown
!
end
"""

_V6_SEGMENT_CONFIG_R3 = """\
!
hostname seg-R3
!
interface GigabitEthernet0/0
 ipv6 address 2001:db8:10::3/64
 no shutdown
!
end
"""


class TestV6Segment:
    """同一 v6 /64 を 3 機器以上で共有するときセグメントが生成される。（タスク9）"""

    @pytest.fixture(scope="class")
    def topology_v6_segment(self):
        from lib.parsers.cisco_ios import parse
        from scripts.build_topology import build
        r1 = parse(_V6_SEGMENT_CONFIG_R1)
        r2 = parse(_V6_SEGMENT_CONFIG_R2)
        r3 = parse(_V6_SEGMENT_CONFIG_R3)
        return build([r1, r2, r3], generated_from=["r1.cfg", "r2.cfg", "r3.cfg"])

    @pytest.mark.unit
    def test_v6_segment_generated(self, topology_v6_segment):
        """同一 v6 /64（2001:db8:10::/64）を 3 機器が共有するとき segment が 1 個生成される。"""
        segs = topology_v6_segment["segments"]
        assert len(segs) == 1, f"Expected 1 segment, got {len(segs)}: {segs}"
        assert segs[0]["subnet"] == "2001:db8:10::/64"

    @pytest.mark.unit
    def test_v6_segment_has_three_members(self, topology_v6_segment):
        """生成された v6 segment は 3 メンバーを持つ。"""
        seg = topology_v6_segment["segments"][0]
        assert len(seg["members"]) == 3, f"Expected 3 members, got {seg['members']}"

    @pytest.mark.unit
    def test_v6_segment_links_empty(self, topology_v6_segment):
        """3 機器の v6 /64 はセグメントになるため links は 0 本。"""
        assert len(topology_v6_segment["links"]) == 0


class TestDualstackV4BgpRegression:
    """dualstack topology で v4 BGP（eBGP）結線が維持される回帰テスト。（タスク9）"""

    @pytest.mark.unit
    def test_v4_ebgp_preserved_in_dualstack(self, topology_dualstack_module):
        """dualstack 環境でも v4 eBGP エントリが routing.bgp に含まれる。"""
        bgp = topology_dualstack_module["routing"]["bgp"]
        assert len(bgp) >= 1, "BGP entries should exist"
        types = {b["type"] for b in bgp}
        assert "ebgp" in types, f"eBGP type not found in {types}"

    @pytest.mark.unit
    def test_v4_ebgp_neighbor_ip_exact(self, topology_dualstack_module):
        """eBGP ネイバー IP は 10.0.0.1 / 10.0.0.2 の具体値。"""
        bgp = topology_dualstack_module["routing"]["bgp"]
        neighbor_ips = {b["neighbor_ip"] for b in bgp}
        # DS-R1 → DS-R2 (10.0.0.2) と DS-R2 → DS-R1 (10.0.0.1) の両エントリ
        assert "10.0.0.2" in neighbor_ips, f"neighbor 10.0.0.2 not found in {neighbor_ips}"
        assert "10.0.0.1" in neighbor_ips, f"neighbor 10.0.0.1 not found in {neighbor_ips}"

    @pytest.mark.unit
    def test_v4_link_10_0_0_0_30_preserved(self, topology_dualstack_module):
        """dualstack 環境でも v4 リンク 10.0.0.0/30 が links に存在する（回帰）。"""
        subnets = [l["subnet"] for l in topology_dualstack_module["links"]]
        assert "10.0.0.0/30" in subnets, f"10.0.0.0/30 not found in {subnets}"
