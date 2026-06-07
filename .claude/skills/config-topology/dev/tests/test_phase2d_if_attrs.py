"""
Phase 2D: IF属性拡充テスト (TDD RED → GREEN → REFACTOR)

テスト対象:
  - lib/parsers/base.py         — Interface dataclass に新属性を追加
  - lib/parsers/cisco_ios.py    — mtu/speed/duplex/switchport/encap/admin_status/l2_l3
  - lib/parsers/juniper_junos.py — mtu/speed/encapsulation/ethernet-switching/admin_status
  - scripts/build_topology.py   — interface dict に新属性を transcribe
  - lib/rendering/cards.py      — Interfaces 表に新列（Status/MTU/Speed）を追加
  - 後方互換性                  — 既存IPv4ゴールデンに新キーが追加されるだけ（既存キー値不変）
  - 決定性・round-trip           — dump → load → dump で値一致

TDD方針:
  1. まずこのファイル全体を書く (RED: テストは失敗する)
  2. 実装を足して GREEN にする
  3. リファクタリング → GREEN のまま
"""

from __future__ import annotations

import dataclasses
import os
import sys
import pytest

# ================================================================
# rich-IF config fixtures (インライン)
# ================================================================

IOS_RICH_IF = """\
!
hostname SW1
!
interface GigabitEthernet0/0
 description routed-port
 ip address 10.0.1.1 255.255.255.252
 no shutdown
 mtu 9000
 speed 1000
 duplex full
!
interface GigabitEthernet0/1
 description access-port-vlan10
 no ip address
 switchport mode access
 switchport access vlan 10
 mtu 1500
 speed 100
 duplex half
!
interface GigabitEthernet0/2
 description trunk-port-to-sw2
 no ip address
 switchport mode trunk
 switchport trunk allowed vlan 10,20,30
 mtu 1500
 speed 1000
 duplex full
!
interface GigabitEthernet0/3
 description blocked-port
 no ip address
 shutdown
!
interface GigabitEthernet0/3.100
 description sub-interface-vlan100
 encapsulation dot1Q 100
 ip address 192.168.100.1 255.255.255.0
!
interface Loopback0
 description mgmt-loopback
 ip address 1.1.1.1 255.255.255.255
!
end
"""

JUNOS_RICH_IF = """\
set system host-name SW2
set interfaces ge-0/0/0 description "uplink-to-core"
set interfaces ge-0/0/0 mtu 9000
set interfaces ge-0/0/0 speed 1g
set interfaces ge-0/0/0 unit 0 family inet address 10.0.1.2/30
set interfaces ge-0/0/1 description "access-port-vlan20"
set interfaces ge-0/0/1 mtu 1500
set interfaces ge-0/0/1 unit 0 family ethernet-switching interface-mode access
set interfaces ge-0/0/1 unit 0 family ethernet-switching vlan members 20
set interfaces ge-0/0/2 description "trunk-to-sw1"
set interfaces ge-0/0/2 mtu 1500
set interfaces ge-0/0/2 encapsulation flexible-ethernet-services
set interfaces ge-0/0/2 unit 0 family ethernet-switching interface-mode trunk
set interfaces ge-0/0/2 unit 0 family ethernet-switching vlan members 10-30
set interfaces ge-0/0/3 description "disabled-port"
set interfaces ge-0/0/3 disable
set interfaces ge-0/0/3 unit 0 family inet address 10.99.0.1/30
set interfaces lo0 description "mgmt-loopback"
set interfaces lo0 unit 0 family inet address 2.2.2.2/32
"""


# ================================================================
# [1] base.py — Interface dataclass に新フィールドが存在すること
# ================================================================

class TestInterfaceBaseNewFields:
    """Interface dataclass に Phase 2D 属性が追加されたことを検証。"""

    @pytest.mark.unit
    def test_interface_has_admin_status_field(self):
        """Interface に admin_status フィールドがあること（default None）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "admin_status"), "admin_status フィールドがない"

    @pytest.mark.unit
    def test_interface_has_oper_status_field(self):
        """Interface に oper_status フィールドがあること（default None）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "oper_status"), "oper_status フィールドがない"

    @pytest.mark.unit
    def test_interface_has_mtu_field(self):
        """Interface に mtu フィールドがあること（default None）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "mtu"), "mtu フィールドがない"

    @pytest.mark.unit
    def test_interface_has_speed_field(self):
        """Interface に speed フィールドがあること（default None）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "speed"), "speed フィールドがない"

    @pytest.mark.unit
    def test_interface_has_duplex_field(self):
        """Interface に duplex フィールドがあること（default None）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "duplex"), "duplex フィールドがない"

    @pytest.mark.unit
    def test_interface_has_l2_l3_field(self):
        """Interface に l2_l3 フィールドがあること（default None）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "l2_l3"), "l2_l3 フィールドがない"

    @pytest.mark.unit
    def test_interface_has_switchport_field(self):
        """Interface に switchport フィールドがあること（default None）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "switchport"), "switchport フィールドがない"

    @pytest.mark.unit
    def test_interface_has_encapsulation_field(self):
        """Interface に encapsulation フィールドがあること（default None）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "encapsulation"), "encapsulation フィールドがない"

    @pytest.mark.unit
    def test_interface_has_source_field(self):
        """Interface に source フィールドがあること（default 'parsed'）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert hasattr(iface, "source"), "source フィールドがない"

    @pytest.mark.unit
    def test_all_new_fields_default_none_except_source(self):
        """新フィールドのデフォルト値（source以外はNone、sourceは'parsed'）。"""
        from lib.parsers.base import Interface
        iface = Interface(name="eth0", ip=None, description=None)
        assert iface.admin_status is None
        assert iface.oper_status is None
        assert iface.mtu is None
        assert iface.speed is None
        assert iface.duplex is None
        assert iface.l2_l3 is None
        assert iface.switchport is None
        assert iface.encapsulation is None
        assert iface.source == "parsed"

    @pytest.mark.unit
    def test_existing_fields_unchanged(self):
        """既存フィールド（name/ip/description/shutdown/vlan）のデフォルト値が変わらない。"""
        from lib.parsers.base import Interface
        iface = Interface(name="Gi0/0", ip="10.0.0.1/30", description="test")
        assert iface.shutdown is False
        assert iface.vlan is None

    @pytest.mark.unit
    def test_dataclass_asdict_includes_new_fields(self):
        """dataclasses.asdict に新フィールドが含まれる。"""
        from lib.parsers.base import Interface
        iface = Interface(
            name="eth0", ip="10.0.0.1/30", description="test",
            mtu=9000, speed="1g", duplex="full",
        )
        d = dataclasses.asdict(iface)
        assert "mtu" in d
        assert "speed" in d
        assert "duplex" in d
        assert "admin_status" in d
        assert d["mtu"] == 9000
        assert d["speed"] == "1g"
        assert d["duplex"] == "full"


# ================================================================
# [2] cisco_ios.py — 新属性パーステスト
# ================================================================

class TestCiscoRichIfParse:
    """IOS rich-IF config から各属性が正しく抽出されること。"""

    @pytest.fixture(autouse=True)
    def parsed(self):
        from lib.parsers.cisco_ios import parse
        self.device = parse(IOS_RICH_IF)

    def _iface(self, name: str):
        return next(i for i in self.device.interfaces if i.name == name)

    # --- admin_status: shutdown 由来 ---

    @pytest.mark.unit
    def test_admin_status_up_when_no_shutdown(self):
        """no shutdown or default → admin_status='up'。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.admin_status == "up", (
            f"Expected 'up', got {iface.admin_status!r}"
        )

    @pytest.mark.unit
    def test_admin_status_down_when_shutdown(self):
        """shutdown 文 → admin_status='down'。"""
        iface = self._iface("GigabitEthernet0/3")
        assert iface.admin_status == "down", (
            f"Expected 'down', got {iface.admin_status!r}"
        )

    @pytest.mark.unit
    def test_admin_status_up_for_loopback(self):
        """shutdown なし Loopback → admin_status='up'。"""
        iface = self._iface("Loopback0")
        assert iface.admin_status == "up"

    # --- mtu ---

    @pytest.mark.unit
    def test_mtu_9000_parsed(self):
        """mtu 9000 → mtu=9000 (int)。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.mtu == 9000, f"Expected 9000, got {iface.mtu!r}"

    @pytest.mark.unit
    def test_mtu_1500_parsed(self):
        """mtu 1500 → mtu=1500 (int)。"""
        iface = self._iface("GigabitEthernet0/1")
        assert iface.mtu == 1500

    @pytest.mark.unit
    def test_mtu_none_when_absent(self):
        """mtu 行なし → mtu=None。"""
        from lib.parsers.cisco_ios import parse
        text = "hostname R1\n!\ninterface Loopback1\n ip address 1.1.1.2 255.255.255.255\n!\n"
        device = parse(text)
        assert device.interfaces[0].mtu is None

    # --- speed ---

    @pytest.mark.unit
    def test_speed_1000_parsed(self):
        """speed 1000 → speed='1000'。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.speed == "1000", f"Expected '1000', got {iface.speed!r}"

    @pytest.mark.unit
    def test_speed_100_parsed(self):
        """speed 100 → speed='100'。"""
        iface = self._iface("GigabitEthernet0/1")
        assert iface.speed == "100"

    @pytest.mark.unit
    def test_speed_none_when_absent(self):
        """speed 行なし → speed=None。"""
        from lib.parsers.cisco_ios import parse
        text = "hostname R1\n!\ninterface Loopback1\n ip address 1.1.1.2 255.255.255.255\n!\n"
        device = parse(text)
        assert device.interfaces[0].speed is None

    # --- duplex ---

    @pytest.mark.unit
    def test_duplex_full_parsed(self):
        """duplex full → duplex='full'。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.duplex == "full", f"Expected 'full', got {iface.duplex!r}"

    @pytest.mark.unit
    def test_duplex_half_parsed(self):
        """duplex half → duplex='half'。"""
        iface = self._iface("GigabitEthernet0/1")
        assert iface.duplex == "half"

    @pytest.mark.unit
    def test_duplex_none_when_absent(self):
        """duplex 行なし → duplex=None。"""
        from lib.parsers.cisco_ios import parse
        text = "hostname R1\n!\ninterface Loopback1\n ip address 1.1.1.2 255.255.255.255\n!\n"
        device = parse(text)
        assert device.interfaces[0].duplex is None

    # --- switchport access ---

    @pytest.mark.unit
    def test_switchport_access_mode_parsed(self):
        """switchport mode access → switchport.mode='access'。"""
        iface = self._iface("GigabitEthernet0/1")
        assert iface.switchport is not None, "switchport が None"
        assert iface.switchport.get("mode") == "access", (
            f"Expected mode='access', got {iface.switchport!r}"
        )

    @pytest.mark.unit
    def test_switchport_access_vlan_parsed(self):
        """switchport access vlan 10 → switchport.access_vlan=10。"""
        iface = self._iface("GigabitEthernet0/1")
        assert iface.switchport is not None
        assert iface.switchport.get("access_vlan") == 10, (
            f"Expected access_vlan=10, got {iface.switchport!r}"
        )

    # --- switchport trunk ---

    @pytest.mark.unit
    def test_switchport_trunk_mode_parsed(self):
        """switchport mode trunk → switchport.mode='trunk'。"""
        iface = self._iface("GigabitEthernet0/2")
        assert iface.switchport is not None
        assert iface.switchport.get("mode") == "trunk", (
            f"Expected mode='trunk', got {iface.switchport!r}"
        )

    @pytest.mark.unit
    def test_switchport_trunk_vlans_parsed(self):
        """switchport trunk allowed vlan 10,20,30 → switchport.trunk_vlans='10,20,30'。"""
        iface = self._iface("GigabitEthernet0/2")
        assert iface.switchport is not None
        assert iface.switchport.get("trunk_vlans") == "10,20,30", (
            f"Expected trunk_vlans='10,20,30', got {iface.switchport!r}"
        )

    @pytest.mark.unit
    def test_switchport_none_for_routed_if(self):
        """IP あり（routed）の IF は switchport=None。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.switchport is None, (
            f"routed IF に switchport が設定された: {iface.switchport!r}"
        )

    # --- encapsulation ---

    @pytest.mark.unit
    def test_encapsulation_dot1q_parsed(self):
        """encapsulation dot1Q 100 → encapsulation='dot1q'（小文字正規化）。"""
        iface = self._iface("GigabitEthernet0/3.100")
        assert iface.encapsulation is not None, "encapsulation が None"
        assert "dot1q" in iface.encapsulation.lower(), (
            f"Expected 'dot1q' in encapsulation, got {iface.encapsulation!r}"
        )

    @pytest.mark.unit
    def test_encapsulation_none_when_absent(self):
        """encapsulation 行なし → encapsulation=None。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.encapsulation is None

    # --- l2_l3 ---

    @pytest.mark.unit
    def test_l2_l3_is_l3_when_ip_present(self):
        """IP あり → l2_l3='l3'。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.l2_l3 == "l3", f"Expected 'l3', got {iface.l2_l3!r}"

    @pytest.mark.unit
    def test_l2_l3_is_l2_when_switchport(self):
        """switchport mode access → l2_l3='l2'。"""
        iface = self._iface("GigabitEthernet0/1")
        assert iface.l2_l3 == "l2", f"Expected 'l2', got {iface.l2_l3!r}"

    @pytest.mark.unit
    def test_l2_l3_is_l2_for_trunk(self):
        """switchport mode trunk → l2_l3='l2'。"""
        iface = self._iface("GigabitEthernet0/2")
        assert iface.l2_l3 == "l2"

    @pytest.mark.unit
    def test_l2_l3_is_l3_for_subif_with_encap(self):
        """encap + ip → l2_l3='l3'（subif は L3 扱い）。"""
        iface = self._iface("GigabitEthernet0/3.100")
        assert iface.l2_l3 == "l3", f"Expected 'l3' for subif, got {iface.l2_l3!r}"

    # --- source ---

    @pytest.mark.unit
    def test_source_is_parsed(self):
        """IOS パーサで作った Interface の source は 'parsed'。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.source == "parsed"

    # --- 取得不能フィールドは None ---

    @pytest.mark.unit
    def test_oper_status_is_none(self):
        """oper_status は IOS configから取れない → None。"""
        iface = self._iface("GigabitEthernet0/0")
        assert iface.oper_status is None


# ================================================================
# [3] juniper_junos.py — 新属性パーステスト
# ================================================================

class TestJunosRichIfParse:
    """JunOS rich-IF config から各属性が正しく抽出されること。"""

    @pytest.fixture(autouse=True)
    def parsed(self):
        from lib.parsers.juniper_junos import parse
        self.device = parse(JUNOS_RICH_IF)

    def _iface(self, name: str):
        return next(i for i in self.device.interfaces if i.name == name)

    # --- admin_status: disable 由来 ---

    @pytest.mark.unit
    def test_admin_status_up_when_not_disabled(self):
        """disable なし → admin_status='up'。"""
        iface = self._iface("ge-0/0/0")
        assert iface.admin_status == "up", (
            f"Expected 'up', got {iface.admin_status!r}"
        )

    @pytest.mark.unit
    def test_admin_status_down_when_disabled(self):
        """set interfaces X disable → admin_status='down'。"""
        iface = self._iface("ge-0/0/3")
        assert iface.admin_status == "down", (
            f"Expected 'down', got {iface.admin_status!r}"
        )

    # --- mtu ---

    @pytest.mark.unit
    def test_mtu_9000_parsed_junos(self):
        """set interfaces X mtu 9000 → mtu=9000 (int)。"""
        iface = self._iface("ge-0/0/0")
        assert iface.mtu == 9000, f"Expected 9000, got {iface.mtu!r}"

    @pytest.mark.unit
    def test_mtu_1500_parsed_junos(self):
        """set interfaces X mtu 1500 → mtu=1500 (int)。"""
        iface = self._iface("ge-0/0/1")
        assert iface.mtu == 1500

    @pytest.mark.unit
    def test_mtu_none_when_absent_junos(self):
        """mtu 行なし → mtu=None。"""
        iface = self._iface("lo0")
        assert iface.mtu is None

    # --- speed ---

    @pytest.mark.unit
    def test_speed_1g_parsed_junos(self):
        """set interfaces X speed 1g → speed='1g'。"""
        iface = self._iface("ge-0/0/0")
        assert iface.speed == "1g", f"Expected '1g', got {iface.speed!r}"

    @pytest.mark.unit
    def test_speed_none_when_absent_junos(self):
        """speed 行なし → speed=None。"""
        iface = self._iface("lo0")
        assert iface.speed is None

    # --- encapsulation ---

    @pytest.mark.unit
    def test_encapsulation_parsed_junos(self):
        """set interfaces X encapsulation <val> → encapsulation=<val>。"""
        iface = self._iface("ge-0/0/2")
        assert iface.encapsulation == "flexible-ethernet-services", (
            f"Expected 'flexible-ethernet-services', got {iface.encapsulation!r}"
        )

    @pytest.mark.unit
    def test_encapsulation_none_when_absent_junos(self):
        """encapsulation 行なし → encapsulation=None。"""
        iface = self._iface("ge-0/0/0")
        assert iface.encapsulation is None

    # --- l2_l3: family ethernet-switching → L2 ---

    @pytest.mark.unit
    def test_l2_l3_is_l2_for_ethernet_switching(self):
        """family ethernet-switching → l2_l3='l2'。"""
        iface = self._iface("ge-0/0/1")
        assert iface.l2_l3 == "l2", f"Expected 'l2', got {iface.l2_l3!r}"

    @pytest.mark.unit
    def test_l2_l3_is_l3_for_inet(self):
        """family inet のみ → l2_l3='l3'。"""
        iface = self._iface("ge-0/0/0")
        assert iface.l2_l3 == "l3", f"Expected 'l3', got {iface.l2_l3!r}"

    # --- source ---

    @pytest.mark.unit
    def test_source_is_parsed_junos(self):
        """JunOS パーサで作った Interface の source は 'parsed'。"""
        iface = self._iface("ge-0/0/0")
        assert iface.source == "parsed"

    # --- 取得不能フィールドは None ---

    @pytest.mark.unit
    def test_oper_status_is_none_junos(self):
        """oper_status は JunOS config から取れない → None。"""
        iface = self._iface("ge-0/0/0")
        assert iface.oper_status is None

    @pytest.mark.unit
    def test_duplex_is_none_junos(self):
        """duplex は JunOS set 形式では通常取れない → None。"""
        iface = self._iface("ge-0/0/0")
        assert iface.duplex is None

    @pytest.mark.unit
    def test_switchport_none_for_l3_junos(self):
        """L3 IF (family inet) は switchport=None。"""
        iface = self._iface("ge-0/0/0")
        assert iface.switchport is None

    @pytest.mark.unit
    def test_junos_l2_access_switchport_is_none(self):
        """JunOS L2 access IF: l2_l3='l2' かつ switchport=None（JunOS は switchport フィールドを使わない）。"""
        iface = self._iface("ge-0/0/1")
        assert iface.l2_l3 == "l2", (
            f"ge-0/0/1 (access) の l2_l3={iface.l2_l3!r}, expected 'l2'"
        )
        assert iface.switchport is None, (
            f"JunOS L2 IF に switchport が設定された: {iface.switchport!r}。"
            "JunOS は l2_l3='l2' で L2 を表現し switchport は Cisco IOS 専用"
        )

    @pytest.mark.unit
    def test_junos_l2_trunk_switchport_is_none(self):
        """JunOS L2 trunk IF (ge-0/0/2): l2_l3='l2' かつ switchport=None。"""
        iface = self._iface("ge-0/0/2")
        assert iface.l2_l3 == "l2", (
            f"ge-0/0/2 (trunk) の l2_l3={iface.l2_l3!r}, expected 'l2'"
        )
        assert iface.switchport is None, (
            f"JunOS trunk IF に switchport が設定された: {iface.switchport!r}"
        )

    @pytest.mark.unit
    def test_junos_trunk_l2_l3_individually(self):
        """JunOS trunk port (ge-0/0/2) が l2_l3='l2' を個別に検証する。"""
        iface = self._iface("ge-0/0/2")
        assert iface.l2_l3 == "l2", (
            f"Expected l2_l3='l2' for trunk ge-0/0/2, got {iface.l2_l3!r}"
        )


# ================================================================
# [4] build_topology.py — interface dict に新属性が出ること
# ================================================================

class TestBuildInterfaceNewAttrs:
    """build() の interfaces に新属性が正しく transcribe されること。"""

    @pytest.fixture
    def ios_result(self):
        from lib.parsers.cisco_ios import parse
        from scripts.build_topology import build
        device = parse(IOS_RICH_IF)
        return build([device], generated_from=["sw1.cfg"])

    @pytest.fixture
    def junos_result(self):
        from lib.parsers.juniper_junos import parse
        from scripts.build_topology import build
        device = parse(JUNOS_RICH_IF)
        return build([device], generated_from=["sw2.conf"])

    def _get_iface(self, result, name):
        return next(i for i in result["interfaces"] if i["name"] == name)

    # --- admin_status ---

    @pytest.mark.unit
    def test_build_ios_admin_status_up(self, ios_result):
        """GigabitEthernet0/0 の admin_status='up' が dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/0")
        assert iface.get("admin_status") == "up", (
            f"Expected 'up', got {iface.get('admin_status')!r}"
        )

    @pytest.mark.unit
    def test_build_ios_admin_status_down(self, ios_result):
        """GigabitEthernet0/3 (shutdown) の admin_status='down' が dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/3")
        assert iface.get("admin_status") == "down"

    @pytest.mark.unit
    def test_build_junos_admin_status_down(self, junos_result):
        """JunOS ge-0/0/3 (disable) の admin_status='down' が dict に出る。"""
        iface = self._get_iface(junos_result, "ge-0/0/3")
        assert iface.get("admin_status") == "down"

    # --- mtu ---

    @pytest.mark.unit
    def test_build_mtu_in_interface_dict(self, ios_result):
        """mtu が interface dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/0")
        assert iface.get("mtu") == 9000

    @pytest.mark.unit
    def test_build_mtu_none_when_absent(self, ios_result):
        """mtu 未設定 IF は mtu=null。"""
        from lib.parsers.cisco_ios import parse
        from scripts.build_topology import build
        device = parse("hostname R1\n!\ninterface Loopback1\n ip address 1.1.1.2 255.255.255.255\n!\n")
        result = build([device], generated_from=[])
        iface = result["interfaces"][0]
        assert iface.get("mtu") is None

    # --- speed / duplex ---

    @pytest.mark.unit
    def test_build_speed_in_interface_dict(self, ios_result):
        """speed が interface dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/0")
        assert iface.get("speed") == "1000"

    @pytest.mark.unit
    def test_build_duplex_in_interface_dict(self, ios_result):
        """duplex が interface dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/0")
        assert iface.get("duplex") == "full"

    # --- l2_l3 ---

    @pytest.mark.unit
    def test_build_l2_l3_in_interface_dict(self, ios_result):
        """l2_l3 が interface dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/1")
        assert iface.get("l2_l3") == "l2"

    # --- switchport ---

    @pytest.mark.unit
    def test_build_switchport_in_interface_dict(self, ios_result):
        """switchport dict が interface dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/1")
        sp = iface.get("switchport")
        assert sp is not None
        assert sp.get("mode") == "access"
        assert sp.get("access_vlan") == 10

    # --- encapsulation ---

    @pytest.mark.unit
    def test_build_encapsulation_in_interface_dict(self, ios_result):
        """encapsulation が interface dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/3.100")
        assert iface.get("encapsulation") is not None
        assert "dot1q" in iface.get("encapsulation", "").lower()

    # --- source ---

    @pytest.mark.unit
    def test_build_source_in_interface_dict(self, ios_result):
        """source='parsed' が interface dict に出る。"""
        iface = self._get_iface(ios_result, "GigabitEthernet0/0")
        assert iface.get("source") == "parsed"

    # --- 決定性 ---

    @pytest.mark.unit
    def test_build_deterministic_with_new_attrs(self, ios_result):
        """同一入力で2回 build しても結果が同じ（決定性）。"""
        from lib.parsers.cisco_ios import parse
        from scripts.build_topology import build
        device = parse(IOS_RICH_IF)
        r1 = build([device], generated_from=["sw1.cfg"])
        r2 = build([device], generated_from=["sw1.cfg"])
        assert r1 == r2, "build() が非決定的になった"


# ================================================================
# [5] round-trip テスト — dump → load → dump で値一致
# ================================================================

class TestRoundTrip:
    """topology dict の dump/load round-trip が新属性を透過的に保持する。"""

    @pytest.mark.unit
    def test_roundtrip_new_attrs_transparent(self, tmp_path):
        """新属性を含む topology dict を dump→load すると完全に一致する。"""
        from lib.parsers.cisco_ios import parse
        from scripts.build_topology import build
        from lib.topology_io import dump_topology, load_topology

        device = parse(IOS_RICH_IF)
        topo = build([device], generated_from=["sw1.cfg"])

        out_dir = str(tmp_path / "topo_rt")
        dump_topology(topo, out_dir)
        loaded = load_topology(out_dir)
        assert loaded == topo, (
            f"Round-trip mismatch.\n"
            f"Expected interfaces[0]: {topo['interfaces'][0]}\n"
            f"Actual interfaces[0]:   {loaded['interfaces'][0]}"
        )

    @pytest.mark.unit
    def test_roundtrip_dump_twice_identical(self, tmp_path):
        """2回 dump した YAML が同一（決定性 + yaml sort_keys=True）。"""
        import yaml
        from lib.parsers.cisco_ios import parse
        from scripts.build_topology import build
        from lib.topology_io import dump_topology

        device = parse(IOS_RICH_IF)
        topo = build([device], generated_from=["sw1.cfg"])

        out1 = str(tmp_path / "dump1")
        out2 = str(tmp_path / "dump2")
        dump_topology(topo, out1)
        dump_topology(topo, out2)

        for fname in ["_meta.yaml", "devices.yaml", "physical.yaml"]:
            p1 = os.path.join(out1, fname)
            p2 = os.path.join(out2, fname)
            if os.path.exists(p1) and os.path.exists(p2):
                with open(p1) as f1, open(p2) as f2:
                    assert f1.read() == f2.read(), f"{fname} が2回 dump で不一致"


# ================================================================
# [6] 後方互換テスト — 既存 IPv4 ゴールデンは addition-only
# ================================================================

class TestBackwardCompatibility:
    """既存 IPv4 ゴールデン（examples/topology/）が addition-only であること。

    条件:
    - 既存キー（name/ip/description/shutdown/vlan/id/device）の値が不変
    - links/segments/routing は完全不変
    - devices（id/hostname/vendor/as/sections）は完全不変
    - interfaces に新属性キーが増えるだけ
    """

    EXAMPLES_DIR = os.path.join(
        os.path.dirname(__file__), "..", "examples"
    )
    GOLDEN_DIR = os.path.join(EXAMPLES_DIR, "topology")
    CONFIGS_DIR = os.path.join(EXAMPLES_DIR, "configs")

    # Phase 2D 新属性を含む全キー（ゴールデンと完全一致検証に使う）
    LEGACY_IF_KEYS = {"id", "device", "name", "ip", "vlan", "description", "shutdown"}
    NEW_IF_KEYS = {
        "admin_status", "oper_status", "mtu", "speed", "duplex",
        "l2_l3", "switchport", "encapsulation", "source",
    }

    @pytest.fixture(scope="class")
    def actual(self):
        from scripts.parse_configs import parse_paths
        from scripts.build_topology import build
        paths = [
            os.path.join(self.CONFIGS_DIR, "sample-ios-r1.cfg"),
            os.path.join(self.CONFIGS_DIR, "sample-junos-r2.conf"),
        ]
        devices = parse_paths(paths)
        return build(
            devices,
            generated_from=["sample-ios-r1.cfg", "sample-junos-r2.conf"],
            title="Network Topology (config-derived)",
        )

    @pytest.fixture(scope="class")
    def golden(self):
        from lib.topology_io import load_topology
        return load_topology(self.GOLDEN_DIR)

    @pytest.mark.unit
    def test_links_unchanged(self, golden, actual):
        """links が不変であること（addition-only: links は変わらない）。"""
        assert actual["links"] == golden["links"], (
            f"links changed!\ngolden: {golden['links']}\nactual: {actual['links']}"
        )

    @pytest.mark.unit
    def test_segments_unchanged(self, golden, actual):
        """segments が不変であること。"""
        assert actual["segments"] == golden["segments"]

    @pytest.mark.unit
    def test_routing_unchanged(self, golden, actual):
        """routing 全体が不変であること。"""
        assert actual["routing"] == golden["routing"]

    @pytest.mark.unit
    def test_devices_section_unchanged(self, golden, actual):
        """devices[] の各エントリが不変であること。"""
        assert actual["devices"] == golden["devices"], (
            f"devices changed!\ngolden: {golden['devices']}\nactual: {actual['devices']}"
        )

    @pytest.mark.unit
    def test_interface_count_unchanged(self, golden, actual):
        """interface の数が変わっていないこと。"""
        assert len(actual["interfaces"]) == len(golden["interfaces"]), (
            f"interfaces count changed: "
            f"golden={len(golden['interfaces'])}, actual={len(actual['interfaces'])}"
        )

    @pytest.mark.unit
    def test_interface_legacy_keys_unchanged(self, golden, actual):
        """各 interface の既存キー（name/ip/description/shutdown/vlan/id/device）が不変。

        新属性キーが増えるのは問題なし。既存キーの値だけ変わっていないことを確認。
        """
        golden_by_id = {i["id"]: i for i in golden["interfaces"]}
        actual_by_id = {i["id"]: i for i in actual["interfaces"]}

        assert set(golden_by_id.keys()) == set(actual_by_id.keys()), (
            "interface ID 集合が変化した"
        )

        for iface_id, golden_if in golden_by_id.items():
            actual_if = actual_by_id[iface_id]
            for key in self.LEGACY_IF_KEYS:
                if key in golden_if:
                    assert actual_if.get(key) == golden_if[key], (
                        f"interface {iface_id!r}: "
                        f"既存キー '{key}' の値が変化した: "
                        f"golden={golden_if[key]!r}, actual={actual_if.get(key)!r}"
                    )

    @pytest.mark.unit
    def test_interfaces_have_new_attrs(self, actual):
        """interfaces に新属性キーが追加され、かつ値がゴールデンと一致すること。

        - キー存在だけでなく値まで検証（vacuous 排除）
        - source は常に 'parsed'
        - oper_status は常に None
        - admin_status は "up" or "down" のいずれか（sample config に shutdown なし → 全 "up"）
        """
        for iface in actual["interfaces"]:
            iface_id = iface["id"]
            assert "admin_status" in iface, f"{iface_id!r} に admin_status がない"
            assert "source" in iface, f"{iface_id!r} に source がない"
            assert iface["source"] == "parsed", (
                f"{iface_id!r}: source={iface['source']!r}, expected 'parsed'"
            )
            assert iface.get("oper_status") is None, (
                f"{iface_id!r}: oper_status={iface.get('oper_status')!r}, expected None"
            )
            assert iface["admin_status"] in ("up", "down"), (
                f"{iface_id!r}: admin_status={iface['admin_status']!r}, expected 'up' or 'down'"
            )

    @pytest.mark.unit
    def test_interfaces_new_attrs_match_golden(self, golden, actual):
        """interfaces の新属性値がゴールデンと完全一致すること。

        ゴールデンには Phase 2D 以降の全属性が含まれる。
        実装が変わっても値が不変であることを担保する。
        """
        golden_by_id = {i["id"]: i for i in golden["interfaces"]}
        actual_by_id = {i["id"]: i for i in actual["interfaces"]}

        all_keys = self.LEGACY_IF_KEYS | self.NEW_IF_KEYS
        for iface_id, golden_if in golden_by_id.items():
            actual_if = actual_by_id[iface_id]
            for key in all_keys:
                if key in golden_if:
                    assert actual_if.get(key) == golden_if[key], (
                        f"interface {iface_id!r}: "
                        f"キー '{key}' の値が変化した: "
                        f"golden={golden_if[key]!r}, actual={actual_if.get(key)!r}"
                    )


# ================================================================
# [7] cards.py — Interfaces 表に新列が表示されること
# ================================================================

class TestCardsNewColumns:
    """cards.py の Interfaces テーブルに新属性列が表示されること。"""

    def _build_cards_html(self, ios_text: str) -> str:
        from lib.parsers.cisco_ios import parse
        from scripts.build_topology import build
        from lib.rendering.cards import _device_cards

        device = parse(ios_text)
        topo = build([device], generated_from=[])
        html = _device_cards(
            devices=topo["devices"],
            interfaces=topo["interfaces"],
            routing=topo["routing"],
        )
        return html

    @pytest.mark.unit
    def test_cards_has_status_column_header(self):
        """Interfaces テーブルに 'Status' ヘッダ列があること。"""
        html = self._build_cards_html(IOS_RICH_IF)
        assert "Status" in html, (
            f"'Status' ヘッダが見つからない（html 先頭500文字）: {html[:500]}"
        )

    @pytest.mark.unit
    def test_cards_has_mtu_column_header(self):
        """Interfaces テーブルに 'MTU' ヘッダ列があること。"""
        html = self._build_cards_html(IOS_RICH_IF)
        assert "MTU" in html, (
            f"'MTU' ヘッダが見つからない（html 先頭500文字）: {html[:500]}"
        )

    @pytest.mark.unit
    def test_cards_shows_mtu_value(self):
        """MTU 列に mtu の値 (9000) が表示されること。"""
        html = self._build_cards_html(IOS_RICH_IF)
        assert "9000" in html, f"mtu=9000 が html に表示されない"

    @pytest.mark.unit
    def test_cards_shows_admin_status_up(self):
        """admin_status=up が <td>up</td> セルとして html に含まれること。

        fixture の description には "up"/"down" 部分文字列が含まれないため、
        <td>up</td> の出現は admin_status セル由来と断定できる。
        """
        html = self._build_cards_html(IOS_RICH_IF)
        assert "<td>up</td>" in html, (
            f"<td>up</td> セルが見つからない。admin_status='up' が正しく出力されていない。"
        )

    @pytest.mark.unit
    def test_cards_shows_admin_status_down(self):
        """admin_status=down が <td>down</td> セルとして html に含まれること（shutdown した IF がある）。

        fixture の description には "up"/"down" 部分文字列が含まれないため、
        <td>down</td> の出現は admin_status セル由来と断定できる。
        """
        html = self._build_cards_html(IOS_RICH_IF)
        assert "<td>down</td>" in html, (
            f"<td>down</td> セルが見つからない。shutdown=True の IF の admin_status='down' が正しく出力されていない。"
        )

    @pytest.mark.unit
    def test_existing_name_column_preserved(self):
        """既存の Name 列ヘッダが維持されること。"""
        html = self._build_cards_html(IOS_RICH_IF)
        assert "Name" in html, "'Name' 列が失われた"

    @pytest.mark.unit
    def test_existing_ip_column_preserved(self):
        """既存の IP 列ヘッダが維持されること。"""
        html = self._build_cards_html(IOS_RICH_IF)
        assert "IP" in html, "'IP' 列が失われた"

    @pytest.mark.unit
    def test_existing_description_column_preserved(self):
        """既存の Description 列ヘッダが維持されること。"""
        html = self._build_cards_html(IOS_RICH_IF)
        assert "Description" in html, "'Description' 列が失われた"

    @pytest.mark.unit
    def test_null_mtu_shows_empty_not_none_string(self):
        """mtu=None の場合、セルが空欄であること（'None'文字列が出ない）。"""
        from lib.parsers.cisco_ios import parse
        from scripts.build_topology import build
        from lib.rendering.cards import _device_cards

        # mtu のない config
        text = (
            "hostname R1\n!\n"
            "interface Loopback0\n"
            " ip address 1.1.1.1 255.255.255.255\n!\n"
        )
        device = parse(text)
        topo = build([device], generated_from=[])
        html = _device_cards(
            devices=topo["devices"],
            interfaces=topo["interfaces"],
            routing=topo["routing"],
        )
        assert "None" not in html, "'None' 文字列が html に出力されている"

    @pytest.mark.unit
    def test_cards_shows_speed_value(self):
        """speed 値 (1000) が html に表示されること。"""
        html = self._build_cards_html(IOS_RICH_IF)
        assert "1000" in html, "speed=1000 が html に表示されない"
