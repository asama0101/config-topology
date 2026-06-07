"""
パーサ層のテスト (TDD: RED → GREEN → REFACTOR)

テスト対象:
  - lib/parsers/base.py    — 正規化モデル (dataclass)
  - lib/parsers/cisco_ios.py   — detect / parse
  - lib/parsers/juniper_junos.py — detect / parse
  - lib/parsers/__init__.py    — parse_text (registry)
  - scripts/parse_configs.py       — parse_paths / collect_inputs
"""

import ipaddress
import os
import tempfile
import pytest

# ================================================================
# サンプルコンフィグ（テスト内インライン定義）
# ================================================================

IOS_SAMPLE = """!
! Cisco IOS / IOS-XE running-config (sample)
!
hostname R1
!
interface GigabitEthernet0/0
 description to-R2
 ip address 10.0.0.1 255.255.255.252
 no shutdown
!
interface GigabitEthernet0/1
 description LAN
 ip address 192.168.1.1 255.255.255.0
!
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
!
router bgp 65001
 neighbor 10.0.0.2 remote-as 65002
!
router ospf 1
 network 192.168.1.0 0.0.0.255 area 0
!
ip route 0.0.0.0 0.0.0.0 10.0.0.2
!
end
"""

JUNOS_SAMPLE = """## Juniper JunOS configuration in `set` format (sample)
set system host-name R2
set interfaces ge-0/0/0 description to-R1
set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30
set interfaces ge-0/0/1 description LAN2
set interfaces ge-0/0/1 unit 0 family inet address 192.168.2.1/24
set interfaces lo0 unit 0 family inet address 2.2.2.2/32
set routing-options autonomous-system 65002
set protocols bgp group ext type external
set protocols bgp group ext neighbor 10.0.0.1 peer-as 65001
set routing-options static route 0.0.0.0/0 next-hop 10.0.0.1
"""


# ================================================================
# base.py — 正規化モデルのインポートテスト
# ================================================================

class TestBaseModels:
    """dataclass の構造が契約通りかを検証する。"""

    def test_import_dataclasses(self):
        from lib.parsers.base import Device, Interface, BgpNeighbor, OspfNetwork, StaticRoute
        assert Device is not None

    def test_interface_defaults(self):
        from lib.parsers.base import Interface
        iface = Interface(name="Gi0/0", ip="10.0.0.1/30", description="test")
        assert iface.shutdown is False
        assert iface.vlan is None

    def test_interface_shutdown_true(self):
        from lib.parsers.base import Interface
        iface = Interface(name="Gi0/1", ip=None, description=None, shutdown=True)
        assert iface.shutdown is True

    def test_bgp_neighbor_none_as(self):
        from lib.parsers.base import BgpNeighbor
        n = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=None)
        assert n.peer_as is None

    def test_ospf_network_fields(self):
        from lib.parsers.base import OspfNetwork
        o = OspfNetwork(process=1, network="192.168.1.0/24", area="0")
        assert o.area == "0"

    def test_static_route_fields(self):
        from lib.parsers.base import StaticRoute
        s = StaticRoute(prefix="0.0.0.0/0", next_hop="10.0.0.2")
        assert s.prefix == "0.0.0.0/0"

    def test_device_fields(self):
        from lib.parsers.base import Device
        d = Device(hostname="R1", vendor="cisco_ios", asn=65001,
                   interfaces=[], bgp=[], ospf=[], static=[])
        assert d.hostname == "R1"
        assert d.vendor == "cisco_ios"
        assert d.asn == 65001

    def test_device_asn_none(self):
        from lib.parsers.base import Device
        d = Device(hostname="R1", vendor="cisco_ios", asn=None,
                   interfaces=[], bgp=[], ospf=[], static=[])
        assert d.asn is None

    def test_device_to_dict(self):
        """to_dict() もしくは dataclasses.asdict が使えること。"""
        import dataclasses
        from lib.parsers.base import Device, Interface
        d = Device(
            hostname="R1", vendor="cisco_ios", asn=65001,
            interfaces=[Interface(name="Gi0/0", ip="10.0.0.1/30", description=None)],
            bgp=[], ospf=[], static=[]
        )
        d_dict = dataclasses.asdict(d)
        assert d_dict["hostname"] == "R1"
        assert d_dict["interfaces"][0]["name"] == "Gi0/0"


# ================================================================
# cisco_ios.py — detect
# ================================================================

class TestCiscoIosDetect:
    """detect は IOS テキストで True、JunOS テキストで False。"""

    def test_detect_ios_sample(self):
        from lib.parsers.cisco_ios import detect
        assert detect(IOS_SAMPLE) is True

    def test_detect_junos_sample_is_false(self):
        from lib.parsers.cisco_ios import detect
        assert detect(JUNOS_SAMPLE) is False

    def test_detect_empty_string(self):
        from lib.parsers.cisco_ios import detect
        assert detect("") is False

    def test_detect_minimal_ios(self):
        from lib.parsers.cisco_ios import detect
        text = "hostname SW1\ninterface GigabitEthernet0/0\n!\n"
        assert detect(text) is True

    def test_detect_random_text(self):
        from lib.parsers.cisco_ios import detect
        assert detect("hello world\nfoo bar") is False


# ================================================================
# juniper_junos.py — detect
# ================================================================

class TestJuniperJunosDetect:
    """detect は JunOS テキストで True、IOS テキストで False。"""

    def test_detect_junos_sample(self):
        from lib.parsers.juniper_junos import detect
        assert detect(JUNOS_SAMPLE) is True

    def test_detect_ios_sample_is_false(self):
        from lib.parsers.juniper_junos import detect
        assert detect(IOS_SAMPLE) is False

    def test_detect_empty_string(self):
        from lib.parsers.juniper_junos import detect
        assert detect("") is False

    def test_detect_minimal_junos(self):
        from lib.parsers.juniper_junos import detect
        text = "set system host-name X\nset interfaces ge-0/0/0 disable\n"
        assert detect(text) is True

    def test_detect_random_text(self):
        from lib.parsers.juniper_junos import detect
        assert detect("hello world\nfoo bar") is False


# ================================================================
# cisco_ios.py — parse
# ================================================================

class TestCiscoIosParse:
    """sample-ios-r1.cfg をパースした結果を詳細検証。"""

    @pytest.fixture(autouse=True)
    def parsed(self):
        from lib.parsers.cisco_ios import parse
        self.device = parse(IOS_SAMPLE)

    # --- Device 全体 ---
    def test_hostname(self):
        assert self.device.hostname == "R1"

    def test_vendor(self):
        assert self.device.vendor == "cisco_ios"

    def test_asn(self):
        assert self.device.asn == 65001

    # --- Interfaces ---
    def test_interface_count(self):
        assert len(self.device.interfaces) == 3

    def test_gi0_0_ip(self):
        gi0 = next(i for i in self.device.interfaces if i.name == "GigabitEthernet0/0")
        assert gi0.ip == "10.0.0.1/30"

    def test_gi0_0_description(self):
        gi0 = next(i for i in self.device.interfaces if i.name == "GigabitEthernet0/0")
        assert gi0.description == "to-R2"

    def test_gi0_0_not_shutdown(self):
        gi0 = next(i for i in self.device.interfaces if i.name == "GigabitEthernet0/0")
        assert gi0.shutdown is False

    def test_gi0_1_ip(self):
        gi1 = next(i for i in self.device.interfaces if i.name == "GigabitEthernet0/1")
        assert gi1.ip == "192.168.1.1/24"

    def test_loopback0_ip(self):
        lb = next(i for i in self.device.interfaces if i.name == "Loopback0")
        assert lb.ip == "1.1.1.1/32"

    def test_loopback0_description_none(self):
        lb = next(i for i in self.device.interfaces if i.name == "Loopback0")
        assert lb.description is None

    # --- BGP ---
    def test_bgp_neighbor_ip(self):
        assert len(self.device.bgp) == 1
        assert self.device.bgp[0].neighbor_ip == "10.0.0.2"

    def test_bgp_peer_as(self):
        assert self.device.bgp[0].peer_as == 65002

    # --- OSPF ---
    def test_ospf_count(self):
        assert len(self.device.ospf) == 1

    def test_ospf_network(self):
        o = self.device.ospf[0]
        assert o.network == "192.168.1.0/24"

    def test_ospf_area(self):
        assert self.device.ospf[0].area == "0"

    def test_ospf_process(self):
        assert self.device.ospf[0].process == 1

    # --- Static ---
    def test_static_prefix(self):
        assert len(self.device.static) == 1
        assert self.device.static[0].prefix == "0.0.0.0/0"

    def test_static_next_hop(self):
        assert self.device.static[0].next_hop == "10.0.0.2"


# ================================================================
# cisco_ios.py — IP 変換（wildcard → CIDR, mask → CIDR）
# ================================================================

class TestCiscoIosIpConversion:
    """ipaddress を使った CIDR 変換の正確性。"""

    def test_mask_to_prefixlen_30(self):
        """255.255.255.252 → /30"""
        from lib.parsers.cisco_ios import parse
        device = parse(IOS_SAMPLE)
        gi0 = next(i for i in device.interfaces if i.name == "GigabitEthernet0/0")
        net = ipaddress.ip_interface(gi0.ip)
        assert net.network.prefixlen == 30

    def test_ospf_wildcard_to_cidr(self):
        """0.0.0.255 wildcard → /24"""
        from lib.parsers.cisco_ios import parse
        device = parse(IOS_SAMPLE)
        assert device.ospf[0].network == "192.168.1.0/24"

    def test_static_default_route(self):
        """0.0.0.0 0.0.0.0 → 0.0.0.0/0"""
        from lib.parsers.cisco_ios import parse
        device = parse(IOS_SAMPLE)
        assert device.static[0].prefix == "0.0.0.0/0"


# ================================================================
# cisco_ios.py — shutdown 検出
# ================================================================

class TestCiscoIosShutdown:
    """shutdown / no shutdown の正しい検出。"""

    def test_shutdown_interface(self):
        """shutdown 文があれば True。"""
        from lib.parsers.cisco_ios import parse
        text = "hostname R1\n!\ninterface FastEthernet0/0\n shutdown\n!\n"
        device = parse(text)
        iface = device.interfaces[0]
        assert iface.shutdown is True

    def test_no_shutdown_is_false(self):
        """no shutdown があれば False。"""
        from lib.parsers.cisco_ios import parse
        text = "hostname R1\n!\ninterface FastEthernet0/0\n no shutdown\n!\n"
        device = parse(text)
        iface = device.interfaces[0]
        assert iface.shutdown is False

    def test_default_is_not_shutdown(self):
        """shutdown も no shutdown もなければ False（デフォルト）。"""
        from lib.parsers.cisco_ios import parse
        text = "hostname R1\n!\ninterface Loopback0\n ip address 1.1.1.1 255.255.255.255\n!\n"
        device = parse(text)
        assert device.interfaces[0].shutdown is False


# ================================================================
# cisco_ios.py — IP なし IF
# ================================================================

class TestCiscoIosNoIp:
    """IP アドレスが設定されていない IF は ip=None。"""

    def test_interface_without_ip(self):
        from lib.parsers.cisco_ios import parse
        text = "hostname R1\n!\ninterface GigabitEthernet0/2\n description no-ip\n!\n"
        device = parse(text)
        iface = device.interfaces[0]
        assert iface.ip is None
        assert iface.description == "no-ip"


# ================================================================
# juniper_junos.py — parse
# ================================================================

class TestJuniperJunosParse:
    """sample-junos-r2.conf をパースした結果を詳細検証。"""

    @pytest.fixture(autouse=True)
    def parsed(self):
        from lib.parsers.juniper_junos import parse
        self.device = parse(JUNOS_SAMPLE)

    def test_hostname(self):
        assert self.device.hostname == "R2"

    def test_vendor(self):
        assert self.device.vendor == "juniper_junos"

    def test_asn(self):
        assert self.device.asn == 65002

    # --- Interfaces ---
    def test_interface_count(self):
        # ge-0/0/0, ge-0/0/1, lo0
        assert len(self.device.interfaces) == 3

    def test_ge000_ip(self):
        ge = next(i for i in self.device.interfaces if i.name == "ge-0/0/0")
        assert ge.ip == "10.0.0.2/30"

    def test_ge000_description(self):
        ge = next(i for i in self.device.interfaces if i.name == "ge-0/0/0")
        assert ge.description == "to-R1"

    def test_ge000_not_shutdown(self):
        ge = next(i for i in self.device.interfaces if i.name == "ge-0/0/0")
        assert ge.shutdown is False

    def test_ge001_ip(self):
        ge = next(i for i in self.device.interfaces if i.name == "ge-0/0/1")
        assert ge.ip == "192.168.2.1/24"

    def test_lo0_ip(self):
        lo = next(i for i in self.device.interfaces if i.name == "lo0")
        assert lo.ip == "2.2.2.2/32"

    def test_lo0_description_none(self):
        lo = next(i for i in self.device.interfaces if i.name == "lo0")
        assert lo.description is None

    # --- BGP ---
    def test_bgp_neighbor_ip(self):
        assert len(self.device.bgp) == 1
        assert self.device.bgp[0].neighbor_ip == "10.0.0.1"

    def test_bgp_peer_as(self):
        assert self.device.bgp[0].peer_as == 65001

    # --- Static ---
    def test_static_prefix(self):
        assert len(self.device.static) == 1
        assert self.device.static[0].prefix == "0.0.0.0/0"

    def test_static_next_hop(self):
        assert self.device.static[0].next_hop == "10.0.0.1"


# ================================================================
# juniper_junos.py — shutdown / disable
# ================================================================

class TestJuniperJunosShutdown:
    """set interfaces <if> disable → shutdown=True。"""

    def test_disable_sets_shutdown(self):
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name X\n"
            "set interfaces ge-0/0/9 disable\n"
            "set interfaces ge-0/0/9 unit 0 family inet address 10.1.0.1/30\n"
        )
        device = parse(text)
        iface = next(i for i in device.interfaces if i.name == "ge-0/0/9")
        assert iface.shutdown is True

    def test_no_disable_is_false(self):
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
        )
        device = parse(text)
        iface = device.interfaces[0]
        assert iface.shutdown is False


# ================================================================
# juniper_junos.py — description クォート除去
# ================================================================

class TestJuniperJunosDescription:
    """description のクォートが除去されること。"""

    def test_quoted_description_stripped(self):
        from lib.parsers.juniper_junos import parse
        text = (
            'set system host-name X\n'
            'set interfaces ge-0/0/0 description "uplink to core"\n'
            'set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n'
        )
        device = parse(text)
        iface = device.interfaces[0]
        assert iface.description == "uplink to core"

    def test_unquoted_description_kept(self):
        from lib.parsers.juniper_junos import parse
        text = (
            'set system host-name X\n'
            'set interfaces ge-0/0/0 description to-R1\n'
            'set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n'
        )
        device = parse(text)
        iface = device.interfaces[0]
        assert iface.description == "to-R1"


# ================================================================
# parsers/__init__.py — registry / parse_text
# ================================================================

class TestParsersRegistry:
    """parse_text はベンダーを自動判別して正しいパーサを呼ぶ。"""

    def test_parse_text_ios(self):
        from lib.parsers import parse_text
        device = parse_text(IOS_SAMPLE)
        assert device.vendor == "cisco_ios"
        assert device.hostname == "R1"

    def test_parse_text_junos(self):
        from lib.parsers import parse_text
        device = parse_text(JUNOS_SAMPLE)
        assert device.vendor == "juniper_junos"
        assert device.hostname == "R2"

    def test_parse_text_unknown_returns_none_or_raises(self):
        """
        未知ベンダー時は None を返す（または ValueError を上げる）。
        どちらの設計を選んでも、クラッシュでなく制御された結果が返ること。
        """
        from lib.parsers import parse_text
        result = parse_text("random text without vendor signatures")
        # None を返す設計（ValueError も許容するが、ここでは None を想定）
        assert result is None

    def test_ios_not_detected_as_junos(self):
        """IOS テキストで JunOS パーサが選ばれないこと（二重チェック）。"""
        from lib.parsers import parse_text
        device = parse_text(IOS_SAMPLE)
        assert device.vendor != "juniper_junos"

    def test_junos_not_detected_as_ios(self):
        """JunOS テキストで IOS パーサが選ばれないこと。"""
        from lib.parsers import parse_text
        device = parse_text(JUNOS_SAMPLE)
        assert device.vendor != "cisco_ios"


# ================================================================
# parse_configs.py — parse_paths / collect_inputs
# ================================================================

class TestParseConfigs:
    """parse_paths と collect_inputs の動作確認。"""

    @pytest.fixture
    def sample_files(self, tmp_path):
        """サンプル cfg/conf ファイルを一時ディレクトリに作成する。"""
        ios_file = tmp_path / "r1.cfg"
        ios_file.write_text(IOS_SAMPLE)
        junos_file = tmp_path / "r2.conf"
        junos_file.write_text(JUNOS_SAMPLE)
        return str(ios_file), str(junos_file), str(tmp_path)

    def test_parse_paths_returns_list(self, sample_files):
        from scripts.parse_configs import parse_paths
        ios_path, junos_path, _ = sample_files
        devices = parse_paths([ios_path, junos_path])
        assert isinstance(devices, list)
        assert len(devices) == 2

    def test_parse_paths_order_preserved(self, sample_files):
        """ファイル順が保持されること。"""
        from scripts.parse_configs import parse_paths
        ios_path, junos_path, _ = sample_files
        devices = parse_paths([ios_path, junos_path])
        assert devices[0].vendor == "cisco_ios"
        assert devices[1].vendor == "juniper_junos"

    def test_parse_paths_unknown_vendor_skipped(self, tmp_path):
        """未知ベンダーのファイルはスキップ（None が入らない）。"""
        from scripts.parse_configs import parse_paths
        unknown = tmp_path / "unknown.cfg"
        unknown.write_text("random content without vendor")
        devices = parse_paths([str(unknown)])
        # None が含まれない or 空リスト
        for d in devices:
            assert d is not None

    def test_parse_paths_empty_file_skipped(self, tmp_path):
        """空ファイルはスキップされる。"""
        from scripts.parse_configs import parse_paths
        empty = tmp_path / "empty.cfg"
        empty.write_text("")
        devices = parse_paths([str(empty)])
        for d in devices:
            assert d is not None

    def test_collect_inputs_from_directory(self, sample_files):
        """ディレクトリを渡すと .cfg .conf .txt を収集する。"""
        from scripts.parse_configs import collect_inputs
        ios_path, junos_path, dir_path = sample_files
        paths = collect_inputs(dir_path)
        assert len(paths) == 2
        assert all(p.endswith((".cfg", ".conf", ".txt")) for p in paths)

    def test_collect_inputs_sorts_by_name(self, sample_files):
        """ファイルは名前順で返ること。"""
        from scripts.parse_configs import collect_inputs
        ios_path, junos_path, dir_path = sample_files
        paths = collect_inputs(dir_path)
        basenames = [os.path.basename(p) for p in paths]
        assert basenames == sorted(basenames)

    def test_collect_inputs_single_file(self, sample_files):
        """単一ファイルパスを渡すとそのまま返す。"""
        from scripts.parse_configs import collect_inputs
        ios_path, _, _ = sample_files
        paths = collect_inputs(ios_path)
        assert paths == [ios_path]

    def test_collect_inputs_no_arg_uses_workspace(self, tmp_path, monkeypatch):
        """引数なし時は workspace/ 配下を返す。"""
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "r1.cfg").write_text(IOS_SAMPLE)
        (workspace / "r2.conf").write_text(JUNOS_SAMPLE)
        # カレントディレクトリを tmp_path に偽装
        monkeypatch.chdir(tmp_path)
        from scripts import parse_configs
        import importlib
        importlib.reload(parse_configs)
        from scripts.parse_configs import collect_inputs
        paths = collect_inputs()
        assert len(paths) == 2

    def test_collect_inputs_glob_pattern(self, sample_files):
        """glob パターンが使える。"""
        import glob as glob_module
        from scripts.parse_configs import collect_inputs
        ios_path, junos_path, dir_path = sample_files
        pattern = os.path.join(dir_path, "*.cfg")
        paths = collect_inputs(pattern)
        assert len(paths) == 1
        assert paths[0].endswith(".cfg")


# ================================================================
# 境界値テスト — 空テキスト / 不完全な config
# ================================================================

class TestEdgeCases:
    """境界値とエラーパスの検証。"""

    def test_ios_parse_empty_returns_device(self):
        """空文字列でも Device が返る（hostname=空・リスト空）。"""
        from lib.parsers.cisco_ios import parse
        device = parse("")
        assert device.hostname == ""
        assert device.interfaces == []
        assert device.bgp == []

    def test_junos_parse_empty_returns_device(self):
        from lib.parsers.juniper_junos import parse
        device = parse("")
        assert device.hostname == ""
        assert device.interfaces == []

    def test_ios_interface_only_no_ip(self):
        """IF ブロックに IP がなければ ip=None。"""
        from lib.parsers.cisco_ios import parse
        text = "hostname X\n!\ninterface Serial0/0\n description WAN\n!\n"
        device = parse(text)
        assert device.interfaces[0].ip is None

    def test_ios_multiple_bgp_neighbors(self):
        """複数の BGP ネイバー。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
            " neighbor 10.0.0.6 remote-as 65003\n"
            "!\n"
        )
        device = parse(text)
        assert len(device.bgp) == 2
        ips = {n.neighbor_ip for n in device.bgp}
        assert "10.0.0.2" in ips
        assert "10.0.0.6" in ips

    def test_junos_no_hostname(self):
        """host-name 行がなければ hostname=空。"""
        from lib.parsers.juniper_junos import parse
        text = "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
        device = parse(text)
        assert device.hostname == ""

    def test_junos_multiple_static_routes(self):
        """複数の static route を正しく取得。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name X\n"
            "set routing-options static route 10.0.0.0/8 next-hop 1.1.1.1\n"
            "set routing-options static route 0.0.0.0/0 next-hop 2.2.2.2\n"
        )
        device = parse(text)
        assert len(device.static) == 2

    def test_ios_ospf_multiple_networks(self):
        """複数の OSPF ネットワーク文。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router ospf 1\n"
            " network 10.0.0.0 0.0.0.3 area 0\n"
            " network 192.168.1.0 0.0.0.255 area 1\n"
            "!\n"
        )
        device = parse(text)
        assert len(device.ospf) == 2
        nets = {o.network for o in device.ospf}
        assert "10.0.0.0/30" in nets
        assert "192.168.1.0/24" in nets

    def test_ios_secondary_address_ignored(self):
        """secondary アドレスは v1 で無視。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
            " ip address 192.168.1.1 255.255.255.0 secondary\n"
            "!\n"
        )
        device = parse(text)
        gi = device.interfaces[0]
        # プライマリアドレスのみ
        assert gi.ip == "10.0.0.1/30"

    def test_ios_detect_only_bang_lines(self):
        """! 行だけでも IOS として detect する。"""
        from lib.parsers.cisco_ios import detect
        text = "!\n!\nend\n"
        assert detect(text) is True

    def test_ios_interface_only_detects(self):
        """interface 行があれば IOS として detect する。"""
        from lib.parsers.cisco_ios import detect
        text = "interface FastEthernet0/0\n"
        assert detect(text) is True


# ================================================================
# parse_configs.py — エラーパスとCLI
# ================================================================

class TestParseConfigsErrorPaths:
    """OSError ハンドリングと未知ベンダー警告の検証。"""

    def test_parse_paths_file_not_found_skipped(self):
        """存在しないファイルはスキップされる（クラッシュしない）。"""
        from scripts.parse_configs import parse_paths
        devices = parse_paths(["/nonexistent/path/to/file.cfg"])
        assert devices == []

    def test_parse_paths_warns_on_os_error(self, capsys):
        """OSError 時に stderr に警告が出る。"""
        from scripts.parse_configs import parse_paths
        parse_paths(["/nonexistent/path/to/file.cfg"])
        captured = capsys.readouterr()
        assert "WARN" in captured.err

    def test_parse_paths_warns_on_unknown_vendor(self, tmp_path, capsys):
        """未知ベンダーで stderr に警告が出る。"""
        from scripts.parse_configs import parse_paths
        f = tmp_path / "unknown.txt"
        f.write_text("random text without vendor signatures\n")
        devices = parse_paths([str(f)])
        assert devices == []
        captured = capsys.readouterr()
        assert "WARN" in captured.err

    def test_cli_main_with_files(self, tmp_path, capsys, monkeypatch):
        """CLI main() が JSON を stdout に出力する。"""
        import sys
        from scripts import parse_configs
        import importlib
        ios_file = tmp_path / "r1.cfg"
        ios_file.write_text(IOS_SAMPLE)
        monkeypatch.setattr(sys, "argv", ["parse_configs.py", str(ios_file)])
        importlib.reload(parse_configs)
        from scripts.parse_configs import main
        main()
        captured = capsys.readouterr()
        import json
        data = json.loads(captured.out)
        assert len(data) == 1
        assert data[0]["hostname"] == "R1"

    def test_cli_main_no_args_uses_workspace(self, tmp_path, capsys, monkeypatch):
        """CLI 引数なし時は workspace/ を使う。"""
        import sys
        from scripts import parse_configs
        import importlib
        workspace = tmp_path / "workspace"
        workspace.mkdir(parents=True)
        (workspace / "r1.cfg").write_text(IOS_SAMPLE)
        monkeypatch.setattr(sys, "argv", ["parse_configs.py"])
        monkeypatch.chdir(tmp_path)
        importlib.reload(parse_configs)
        from scripts.parse_configs import main
        main()
        captured = capsys.readouterr()
        import json
        data = json.loads(captured.out)
        assert len(data) == 1

    def test_parse_paths_warns_on_os_error_actually_warns(self, capsys):
        """[修正版] OSError 時に実際に stderr へ警告が出ること（or True を除去）。"""
        from scripts.parse_configs import parse_paths
        parse_paths(["/nonexistent/path/to/file.cfg"])
        captured = capsys.readouterr()
        assert "WARN" in captured.err  # or True を使わず実際の警告を検証


# ================================================================
# [HIGH] JunOS 同一IF複数unit IP — 先勝ちテスト
# ================================================================

class TestJuniperJunosMultiUnitIp:
    """同一IF に複数 unit の IP がある場合、最初の IP が保持されること（先勝ち）。"""

    def test_first_unit_ip_preserved_when_second_unit_present(self):
        """
        [RED→GREEN] ge-0/0/0 unit 0 (10.0.0.1/30) の後に unit 1 (192.168.1.1/24) が
        来ても、最初の IP (10.0.0.1/30) が保持されること。
        """
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set interfaces ge-0/0/0 unit 1 family inet address 192.168.1.1/24\n"
        )
        device = parse(text)
        iface = next(i for i in device.interfaces if i.name == "ge-0/0/0")
        assert iface.ip == "10.0.0.1/30", (
            f"Expected first unit IP 10.0.0.1/30 to be preserved, got {iface.ip}"
        )

    def test_single_unit_ip_still_set(self):
        """unit が1つだけの場合は従来通り IP が設定される（回帰テスト）。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.2/30\n"
        )
        device = parse(text)
        iface = device.interfaces[0]
        assert iface.ip == "10.0.0.2/30"

    def test_different_ifs_each_get_own_ip(self):
        """別々の IF は互いに影響しない（回帰テスト）。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name X\n"
            "set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/30\n"
            "set interfaces ge-0/0/1 unit 0 family inet address 192.168.1.1/24\n"
        )
        device = parse(text)
        ge0 = next(i for i in device.interfaces if i.name == "ge-0/0/0")
        ge1 = next(i for i in device.interfaces if i.name == "ge-0/0/1")
        assert ge0.ip == "10.0.0.1/30"
        assert ge1.ip == "192.168.1.1/24"


# ================================================================
# [MEDIUM] IOS OSPF wildcard /0 防御テスト
# ================================================================

class TestCiscoIosOspfWildcardAllOnes:
    """wildcard 255.255.255.255（全1）は OspfNetwork を生成しないこと。"""

    def test_wildcard_all_ones_skipped(self):
        """
        [RED→GREEN] network 10.0.0.0 255.255.255.255 area 0 は prefixlen=0 となり
        不正なので OspfNetwork を生成しない。
        """
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router ospf 1\n"
            " network 10.0.0.0 255.255.255.255 area 0\n"
            "!\n"
        )
        device = parse(text)
        assert len(device.ospf) == 0, (
            f"Expected no OspfNetwork for /0 wildcard, got {device.ospf}"
        )

    def test_wildcard_all_ones_in_mixed_config_skips_only_invalid(self):
        """valid な wildcard は通常通り生成され、全1 wildcard だけスキップ。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router ospf 1\n"
            " network 192.168.1.0 0.0.0.255 area 0\n"
            " network 10.0.0.0 255.255.255.255 area 0\n"
            "!\n"
        )
        device = parse(text)
        assert len(device.ospf) == 1
        assert device.ospf[0].network == "192.168.1.0/24"

    def test_normal_wildcard_still_works(self):
        """通常の wildcard は引き続き正常にパースされる（回帰テスト）。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router ospf 1\n"
            " network 10.0.0.0 0.0.0.3 area 0\n"
            "!\n"
        )
        device = parse(text)
        assert len(device.ospf) == 1
        assert device.ospf[0].network == "10.0.0.0/30"


# ================================================================
# [maint HIGH] _collect_from_dir 重複排除テスト
# ================================================================

class TestCollectFromDirDeduplication:
    """
    _collect_from_dir が重複ファイルを排除し、安定順序で返すこと。
    （拡張子が複数の glob パターンにマッチするケースを想定）
    """

    def test_no_duplicates_in_result(self, tmp_path):
        """
        [RED→GREEN] 同じファイルが複数の glob にマッチしても重複しないこと。
        （例: *.cfg と *.conf の両方にマッチする拡張子は通常ないが、
        _collect_from_dir の重複排除実装を検証する）
        """
        from scripts.parse_configs import _collect_from_dir
        (tmp_path / "r1.cfg").write_text(IOS_SAMPLE)
        (tmp_path / "r2.conf").write_text(JUNOS_SAMPLE)
        (tmp_path / "r3.txt").write_text(IOS_SAMPLE)
        results = _collect_from_dir(str(tmp_path))
        # 重複がないこと
        assert len(results) == len(set(results)), (
            f"Duplicates found: {results}"
        )

    def test_stable_sorted_order(self, tmp_path):
        """
        [RED→GREEN] 返り値が名前順（安定ソート）であること。
        """
        from scripts.parse_configs import _collect_from_dir
        (tmp_path / "b.cfg").write_text(IOS_SAMPLE)
        (tmp_path / "a.conf").write_text(JUNOS_SAMPLE)
        (tmp_path / "c.txt").write_text(IOS_SAMPLE)
        results = _collect_from_dir(str(tmp_path))
        assert results == sorted(results), (
            f"Expected sorted, got {[os.path.basename(p) for p in results]}"
        )

    def test_empty_directory_returns_empty_list(self, tmp_path):
        """
        [追加] 空ディレクトリを渡すと空リストを返す。
        """
        from scripts.parse_configs import _collect_from_dir
        results = _collect_from_dir(str(tmp_path))
        assert results == []

    def test_collect_inputs_empty_directory_returns_empty_list(self, tmp_path):
        """
        [追加] collect_inputs に空ディレクトリを渡すと空リストを返す。
        """
        from scripts.parse_configs import collect_inputs
        results = collect_inputs(str(tmp_path))
        assert results == []


# ================================================================
# [追加カバレッジ] IOS /31 境界値テスト
# ================================================================

class TestCiscoIosMask31:
    """/31 マスク (255.255.255.254) が正しく /31 に変換されること。"""

    def test_mask_255_255_255_254_gives_prefixlen_31(self):
        """
        [追加] ip address 10.0.0.0 255.255.255.254 → 10.0.0.0/31。
        """
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.0 255.255.255.254\n"
            "!\n"
        )
        device = parse(text)
        iface = device.interfaces[0]
        assert iface.ip == "10.0.0.0/31", (
            f"Expected 10.0.0.0/31, got {iface.ip}"
        )

    def test_mask_31_is_valid_ip_interface(self):
        """/31 は ipaddress で有効なインターフェースアドレスとして扱えること。"""
        from lib.parsers.cisco_ios import parse
        import ipaddress
        text = (
            "hostname R1\n"
            "!\n"
            "interface Serial0/0\n"
            " ip address 192.168.0.1 255.255.255.254\n"
            "!\n"
        )
        device = parse(text)
        iface = device.interfaces[0]
        # ipaddress が解釈できること（例外が出ないこと）
        net = ipaddress.ip_interface(iface.ip)
        assert net.network.prefixlen == 31


# ================================================================
# [追加カバレッジ] JunOS OSPF パーステスト（仕様通りの回帰保護）
# ================================================================

class TestJuniperJunosOspf:
    """
    JunOS OSPF パス: set protocols ospf area <a> interface <if> の
    パース仕様（network フィールドに IF 名が格納される best-effort 仕様）
    を回帰保護するテスト。
    """

    def test_ospf_area_and_interface_parsed(self):
        """
        set protocols ospf area 0 interface ge-0/0/0.0 が OspfNetwork として
        収集されること。process=None、network=IF名、area="0" の仕様を検証。
        """
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf area 0 interface ge-0/0/0.0\n"
        )
        device = parse(text)
        assert len(device.ospf) == 1
        o = device.ospf[0]
        assert o.area == "0"
        assert o.process is None  # JunOS OSPF は best-effort: process=None
        assert o.network == "ge-0/0/0.0"  # v1 仕様: IF 名を network フィールドに格納

    def test_ospf_multiple_areas(self):
        """複数 area/interface が正しく収集される。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf area 0 interface ge-0/0/0.0\n"
            "set protocols ospf area 1 interface ge-0/0/1.0\n"
        )
        device = parse(text)
        assert len(device.ospf) == 2
        areas = {o.area for o in device.ospf}
        assert "0" in areas
        assert "1" in areas

    def test_ospf_network_is_interface_name(self):
        """
        v1 仕様: OspfNetwork.network は CIDR ではなく IF 名（best-effort）。
        この仕様が変わった場合にテストが壊れることで検出できる（回帰保護）。
        """
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf area 0.0.0.0 interface lo0.0\n"
        )
        device = parse(text)
        assert len(device.ospf) == 1
        # IF 名がそのまま network に入っていること
        assert device.ospf[0].network == "lo0.0"
        assert device.ospf[0].area == "0.0.0.0"


# ================================================================
# [段階1] router-id パーステスト（RED -> GREEN）
# ================================================================

class TestRouterIdBase:
    """Device dataclass に ospf_router_id / bgp_router_id フィールドがあること。"""

    def test_device_has_ospf_router_id_field(self):
        """Device に ospf_router_id フィールドがデフォルト None で存在する。"""
        from lib.parsers.base import Device
        d = Device(hostname="R1", vendor="cisco_ios", asn=None)
        assert hasattr(d, "ospf_router_id")
        assert d.ospf_router_id is None

    def test_device_has_bgp_router_id_field(self):
        """Device に bgp_router_id フィールドがデフォルト None で存在する。"""
        from lib.parsers.base import Device
        d = Device(hostname="R1", vendor="cisco_ios", asn=None)
        assert hasattr(d, "bgp_router_id")
        assert d.bgp_router_id is None

    def test_device_ospf_router_id_set(self):
        """Device を生成時に ospf_router_id を指定できる。"""
        from lib.parsers.base import Device
        d = Device(hostname="R1", vendor="cisco_ios", asn=None,
                   ospf_router_id="1.1.1.1")
        assert d.ospf_router_id == "1.1.1.1"

    def test_device_bgp_router_id_set(self):
        """Device を生成時に bgp_router_id を指定できる。"""
        from lib.parsers.base import Device
        d = Device(hostname="R1", vendor="cisco_ios", asn=None,
                   bgp_router_id="2.2.2.2")
        assert d.bgp_router_id == "2.2.2.2"

    def test_device_asdict_includes_router_ids(self):
        """dataclasses.asdict で ospf_router_id / bgp_router_id が出力される。"""
        import dataclasses
        from lib.parsers.base import Device
        d = Device(hostname="R1", vendor="cisco_ios", asn=None,
                   ospf_router_id="1.1.1.1", bgp_router_id="2.2.2.2")
        d_dict = dataclasses.asdict(d)
        assert d_dict["ospf_router_id"] == "1.1.1.1"
        assert d_dict["bgp_router_id"] == "2.2.2.2"

    def test_existing_device_construction_still_works(self):
        """既存テストと後方互換（router-id なしで Device 構築できる）。"""
        from lib.parsers.base import Device
        d = Device(hostname="R1", vendor="cisco_ios", asn=65001,
                   interfaces=[], bgp=[], ospf=[], static=[])
        assert d.ospf_router_id is None
        assert d.bgp_router_id is None


class TestCiscoIosRouterId:
    """IOS パーサが router ospf / router bgp ブロック内の router-id をパースする。"""

    def test_ospf_router_id_parsed(self):
        """router ospf ブロック内の router-id を ospf_router_id に格納する。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router ospf 1\n"
            " router-id 10.1.1.1\n"
            " network 10.0.0.0 0.0.0.3 area 0\n"
            "!\n"
        )
        device = parse(text)
        assert device.ospf_router_id == "10.1.1.1"

    def test_ospf_router_id_not_present_is_none(self):
        """router-id がなければ ospf_router_id は None。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router ospf 1\n"
            " network 10.0.0.0 0.0.0.3 area 0\n"
            "!\n"
        )
        device = parse(text)
        assert device.ospf_router_id is None

    def test_ospf_router_id_multiple_process_first_wins(self):
        """複数 OSPF プロセスがある場合、最初に出現した router-id を採用する。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router ospf 1\n"
            " router-id 10.1.1.1\n"
            "!\n"
            "router ospf 2\n"
            " router-id 10.1.1.2\n"
            "!\n"
        )
        device = parse(text)
        assert device.ospf_router_id == "10.1.1.1"

    def test_bgp_router_id_parsed(self):
        """router bgp ブロック内の bgp router-id を bgp_router_id に格納する。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router bgp 65001\n"
            " bgp router-id 10.2.2.2\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
            "!\n"
        )
        device = parse(text)
        assert device.bgp_router_id == "10.2.2.2"

    def test_bgp_router_id_not_present_is_none(self):
        """bgp router-id がなければ bgp_router_id は None。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
            "!\n"
        )
        device = parse(text)
        assert device.bgp_router_id is None

    def test_ospf_and_bgp_router_id_independent(self):
        """OSPF と BGP の router-id は独立して保持される。"""
        from lib.parsers.cisco_ios import parse
        text = (
            "hostname R1\n"
            "!\n"
            "router bgp 65001\n"
            " bgp router-id 10.2.2.2\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
            "!\n"
            "router ospf 1\n"
            " router-id 10.1.1.1\n"
            " network 10.0.0.0 0.0.0.3 area 0\n"
            "!\n"
        )
        device = parse(text)
        assert device.ospf_router_id == "10.1.1.1"
        assert device.bgp_router_id == "10.2.2.2"


class TestJuniperJunosRouterId:
    """JunOS パーサが ospf/ospf3 router-id とグローバル router-id をパースする。"""

    def test_ospf_router_id_set_protocols_ospf(self):
        """set protocols ospf router-id <id> を ospf_router_id に格納する。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf router-id 10.1.1.2\n"
        )
        device = parse(text)
        assert device.ospf_router_id == "10.1.1.2"

    def test_ospf3_router_id_set_protocols_ospf3(self):
        """set protocols ospf3 router-id <id> を ospf_router_id に格納する。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf3 router-id 10.1.1.2\n"
        )
        device = parse(text)
        assert device.ospf_router_id == "10.1.1.2"

    def test_global_router_id_sets_bgp_router_id(self):
        """set routing-options router-id <id> を bgp_router_id に格納する。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set routing-options router-id 10.3.3.3\n"
        )
        device = parse(text)
        assert device.bgp_router_id == "10.3.3.3"

    def test_global_router_id_fallback_to_ospf(self):
        """ospf 専用 router-id がない場合、グローバル router-id を ospf_router_id にもセットする。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set routing-options router-id 10.3.3.3\n"
        )
        device = parse(text)
        assert device.ospf_router_id == "10.3.3.3"

    def test_ospf_specific_takes_priority_over_global(self):
        """ospf 専用 router-id がある場合、グローバル router-id はフォールバックされない。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf router-id 10.1.1.2\n"
            "set routing-options router-id 10.3.3.3\n"
        )
        device = parse(text)
        # ospf 専用が優先
        assert device.ospf_router_id == "10.1.1.2"
        # グローバルは bgp_router_id に入る
        assert device.bgp_router_id == "10.3.3.3"

    def test_no_router_id_is_none(self):
        """router-id がなければ両フィールド共に None。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set routing-options autonomous-system 65002\n"
        )
        device = parse(text)
        assert device.ospf_router_id is None
        assert device.bgp_router_id is None

    def test_ospf_takes_priority_over_ospf3_ospf_first(self):
        """ospf 専用と ospf3 両方ある場合、ospf 専用が優先（ospf 先記述）。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf router-id 10.1.1.1\n"
            "set protocols ospf3 router-id 10.2.2.2\n"
        )
        device = parse(text)
        # ospf 専用優先・記述順に依存しない
        assert device.ospf_router_id == "10.1.1.1", (
            f"ospf 専用が優先されるべきだが ospf3 値になった: {device.ospf_router_id!r}"
        )

    def test_ospf_takes_priority_over_ospf3_ospf3_first(self):
        """ospf 専用と ospf3 両方ある場合、ospf 専用が優先（ospf3 先記述・記述順非依存を確認）。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf3 router-id 10.2.2.2\n"
            "set protocols ospf router-id 10.1.1.1\n"
        )
        device = parse(text)
        # ospf3 が先に来ても ospf 専用が優先
        assert device.ospf_router_id == "10.1.1.1", (
            f"ospf3 先記述でも ospf 専用が優先されるべきだが: {device.ospf_router_id!r}"
        )

    def test_ospf3_only_sets_ospf_router_id(self):
        """ospf 専用がなく ospf3 のみの場合は ospf3 の値が使われる。"""
        from lib.parsers.juniper_junos import parse
        text = (
            "set system host-name R2\n"
            "set protocols ospf3 router-id 10.2.2.2\n"
        )
        device = parse(text)
        assert device.ospf_router_id == "10.2.2.2", (
            f"ospf3 単独時は ospf3 の値が使われるべきだが: {device.ospf_router_id!r}"
        )
