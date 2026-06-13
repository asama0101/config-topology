"""C5: IOS redistribute 抽出のテスト（models/parsers/build/topology_io/render）。

対象:
  - lib/models.py: Redistribute dataclass + Device.redistribute
  - lib/parsers/ios.py: bgp/ospf 文脈の redistribute 抽出
  - lib/build.py: build_redistribute + routing dict への追加
  - lib/topology_io.py: dump/load で routing.redistribute を配線
  - lib/rendering/data_transform.py: build_devices に redist リスト追加
"""
import pytest

pytestmark = pytest.mark.unit


# ===========================================================================
# 1. models.py: Redistribute dataclass + Device.redistribute
# ===========================================================================

class TestRedistributeModel:
    """Redistribute dataclass と Device.redistribute フィールドのテスト。"""

    def test_redistribute_to_dict_minimal(self):
        """metric/route_map が None のとき to_dict() に省略されること。"""
        from lib.models import Redistribute
        r = Redistribute(into="bgp", source="connected")
        d = r.to_dict()
        assert d == {"into": "bgp", "source": "connected"}

    def test_redistribute_to_dict_with_metric(self):
        """metric が値を持つとき to_dict() に含まれること。"""
        from lib.models import Redistribute
        r = Redistribute(into="bgp", source="static", metric=100)
        d = r.to_dict()
        assert d == {"into": "bgp", "source": "static", "metric": 100}

    def test_redistribute_to_dict_with_route_map(self):
        """route_map が値を持つとき to_dict() に含まれること。"""
        from lib.models import Redistribute
        r = Redistribute(into="ospf", source="bgp", route_map="RM-OUT")
        d = r.to_dict()
        assert d == {"into": "ospf", "source": "bgp", "route_map": "RM-OUT"}

    def test_redistribute_to_dict_full(self):
        """metric と route_map が両方値を持つとき to_dict() に両方含まれること。"""
        from lib.models import Redistribute
        r = Redistribute(into="bgp", source="ospf", metric=50, route_map="RM-OSPF-TO-BGP")
        d = r.to_dict()
        assert d == {"into": "bgp", "source": "ospf", "metric": 50, "route_map": "RM-OSPF-TO-BGP"}

    def test_redistribute_metric_none_omitted(self):
        """metric=None（デフォルト）のとき to_dict() に 'metric' キーが出ないこと。"""
        from lib.models import Redistribute
        r = Redistribute(into="ospf", source="connected", metric=None)
        d = r.to_dict()
        assert "metric" not in d

    def test_redistribute_route_map_none_omitted(self):
        """route_map=None（デフォルト）のとき to_dict() に 'route_map' キーが出ないこと。"""
        from lib.models import Redistribute
        r = Redistribute(into="bgp", source="static", route_map=None)
        d = r.to_dict()
        assert "route_map" not in d

    def test_device_has_redistribute_field(self):
        """Device に redistribute フィールドがありデフォルト空リストであること。"""
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios")
        assert hasattr(dev, "redistribute")
        assert dev.redistribute == []

    def test_device_to_dict_includes_redistribute_key(self):
        """Device.to_dict() に 'redistribute' キーが含まれること。"""
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios")
        d = dev.to_dict()
        assert "redistribute" in d
        assert d["redistribute"] == []

    def test_device_to_dict_redistribute_with_entries(self):
        """Device.to_dict() の 'redistribute' に Redistribute エントリが展開されること。"""
        from lib.models import Device, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.redistribute.append(Redistribute(into="bgp", source="connected"))
        dev.redistribute.append(Redistribute(into="bgp", source="static", metric=100))
        d = dev.to_dict()
        assert len(d["redistribute"]) == 2
        assert d["redistribute"][0] == {"into": "bgp", "source": "connected"}
        assert d["redistribute"][1] == {"into": "bgp", "source": "static", "metric": 100}

    def test_redistribute_existing_fields_unchanged(self):
        """Redistribute 追加後も Device の既存フィールド（bgp/ospf/static）が変わらないこと。"""
        from lib.models import Device, BgpNeighbor, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios", as_=65001)
        dev.bgp.append(BgpNeighbor("10.0.0.2", 65002, "v4"))
        dev.redistribute.append(Redistribute(into="bgp", source="connected"))
        d = dev.to_dict()
        assert len(d["bgp"]) == 1
        assert len(d["redistribute"]) == 1
        assert d["hostname"] == "R1"
        assert d["as"] == 65001


# ===========================================================================
# 2. parsers/ios.py: redistribute 抽出
# ===========================================================================

class TestIosParserRedistribute:
    """IOS パーサの redistribute 抽出テスト。"""

    def _parse(self, text):
        from lib.parsers.ios import parse_ios
        warnings = []
        return parse_ios(text, warnings), warnings

    # --- BGP 文脈 ---

    def test_bgp_redistribute_connected(self):
        """bgp 文脈の `redistribute connected` を into='bgp', source='connected' で抽出すること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute connected\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.into == "bgp"
        assert r.source == "connected"
        assert r.metric is None
        assert r.route_map is None

    def test_bgp_redistribute_static_with_metric(self):
        """bgp 文脈の `redistribute static metric 100` を metric=100 で抽出すること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute static metric 100\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.into == "bgp"
        assert r.source == "static"
        assert r.metric == 100
        assert r.route_map is None

    def test_bgp_redistribute_ospf_with_route_map(self):
        """bgp 文脈の `redistribute ospf 1 route-map RM` を source='ospf', route_map='RM' で抽出すること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute ospf 1 route-map RM\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.into == "bgp"
        assert r.source == "ospf"
        assert r.route_map == "RM"
        assert r.metric is None

    def test_bgp_redistribute_metric_and_route_map_order(self):
        """bgp 文脈で metric と route-map が順不同に現れても両方抽出されること。"""
        # route-map が metric より前の場合
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute connected route-map RM-CONN metric 50\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.source == "connected"
        assert r.metric == 50
        assert r.route_map == "RM-CONN"

    def test_bgp_redistribute_subnets_ignored(self):
        """`subnets` キーワードが余分トークンとして無視されること（source が変わらない）。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute ospf 1 subnets\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.source == "ospf"

    def test_bgp_no_redistribute_skipped(self):
        """`no redistribute ...` 行は無視されること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " no redistribute connected\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 0

    def test_bgp_multiple_redistributes(self):
        """bgp 文脈で複数の redistribute 行が config 順に抽出されること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute connected\n"
            " redistribute static metric 100\n"
            " redistribute ospf 1 route-map RM-OSPF\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 3
        assert dev.redistribute[0].source == "connected"
        assert dev.redistribute[1].source == "static"
        assert dev.redistribute[1].metric == 100
        assert dev.redistribute[2].source == "ospf"
        assert dev.redistribute[2].route_map == "RM-OSPF"

    # --- OSPF 文脈 ---

    def test_ospf_redistribute_bgp_as(self):
        """ospf 文脈の `redistribute bgp 65001 subnets` を into='ospf', source='bgp' で抽出すること。"""
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " redistribute bgp 65001 subnets\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.into == "ospf"
        assert r.source == "bgp"

    def test_ospf_redistribute_connected_with_metric(self):
        """ospf 文脈の `redistribute connected metric 20` を into='ospf', metric=20 で抽出すること。"""
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " redistribute connected metric 20\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.into == "ospf"
        assert r.source == "connected"
        assert r.metric == 20

    def test_ospf_redistribute_static_route_map(self):
        """ospf 文脈の `redistribute static route-map RM-STATIC` を into='ospf', route_map='RM-STATIC' で抽出すること。"""
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " redistribute static route-map RM-STATIC\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.into == "ospf"
        assert r.source == "static"
        assert r.route_map == "RM-STATIC"

    def test_ospf_no_redistribute_skipped(self):
        """`no redistribute ...` 行は ospf 文脈でも無視されること。"""
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " no redistribute bgp 65001\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 0

    def test_device_without_redistribute_has_empty_list(self):
        """redistribute のない device は空リストを持つこと。"""
        text = (
            "hostname R1\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.252\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert dev.redistribute == []

    def test_bgp_context_into_is_bgp(self):
        """router bgp ブロック内の redistribute は into='bgp' であること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute static\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert dev.redistribute[0].into == "bgp"

    def test_ospf_context_into_is_ospf(self):
        """router ospf ブロック内の redistribute は into='ospf' であること。"""
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " redistribute static\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert dev.redistribute[0].into == "ospf"

    def test_bgp_and_ospf_redistribute_combined(self):
        """bgp と ospf の両ブロックに redistribute が設定された場合、それぞれの into が正しいこと。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute connected\n"
            "!\n"
            "router ospf 1\n"
            " redistribute bgp 65001 subnets\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 2
        bgp_redist = [r for r in dev.redistribute if r.into == "bgp"]
        ospf_redist = [r for r in dev.redistribute if r.into == "ospf"]
        assert len(bgp_redist) == 1 and bgp_redist[0].source == "connected"
        assert len(ospf_redist) == 1 and ospf_redist[0].source == "bgp"

    def test_redistribute_does_not_break_neighbor_parse(self):
        """redistribute 行が neighbor パースを壊さないこと（既存 BGP パースの回帰テスト）。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " neighbor 10.0.0.2 remote-as 65002\n"
            " redistribute connected\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.bgp) == 1
        assert dev.bgp[0].neighbor_ip == "10.0.0.2"
        assert len(dev.redistribute) == 1

    def test_redistribute_does_not_break_ospf_network_parse(self):
        """redistribute 行が network パースを壊さないこと（既存 OSPF パースの回帰テスト）。"""
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " network 192.168.1.0 0.0.0.255 area 0\n"
            " redistribute bgp 65001 subnets\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.ospf) == 1
        assert dev.ospf[0].network == "192.168.1.0/24"
        assert len(dev.redistribute) == 1
        assert dev.redistribute[0].source == "bgp"

    def test_bgp_redistribute_rip(self):
        """bgp 文脈で source='rip' が抽出されること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute rip\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        assert dev.redistribute[0].source == "rip"

    def test_bgp_redistribute_eigrp(self):
        """bgp 文脈で source='eigrp' が抽出されること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute eigrp 100\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        assert dev.redistribute[0].source == "eigrp"

    def test_bgp_redistribute_isis(self):
        """bgp 文脈で source='isis' が抽出されること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " redistribute isis TAG\n"
            "!\n"
        )
        dev, warnings = self._parse(text)
        assert len(dev.redistribute) == 1
        assert dev.redistribute[0].source == "isis"


# ===========================================================================
# 3. build.py: build_redistribute + routing dict への追加
# ===========================================================================

class TestBuildRedistribute:
    """build_redistribute 関数と build_topology の routing.redistribute テスト。"""

    def _make_id_dev(self, hostname, into, source, metric=None, route_map=None):
        from lib.models import Device, Redistribute
        dev = Device(hostname=hostname, vendor="cisco_ios")
        dev.redistribute.append(Redistribute(into=into, source=source, metric=metric, route_map=route_map))
        return hostname.lower(), dev

    def test_build_redistribute_basic(self):
        """build_redistribute が into/source を含むエントリを生成すること。"""
        from lib.build import build_redistribute
        from lib.models import Device, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.redistribute.append(Redistribute(into="bgp", source="connected"))
        entries = build_redistribute([("r1", dev)])
        assert len(entries) == 1
        assert entries[0] == {"device": "r1", "into": "bgp", "source": "connected"}

    def test_build_redistribute_with_metric(self):
        """build_redistribute が metric を含むエントリを生成すること（値ありのみ）。"""
        from lib.build import build_redistribute
        from lib.models import Device, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.redistribute.append(Redistribute(into="bgp", source="static", metric=100))
        entries = build_redistribute([("r1", dev)])
        assert entries[0]["metric"] == 100

    def test_build_redistribute_with_route_map(self):
        """build_redistribute が route_map を含むエントリを生成すること（値ありのみ）。"""
        from lib.build import build_redistribute
        from lib.models import Device, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.redistribute.append(Redistribute(into="ospf", source="bgp", route_map="RM-OUT"))
        entries = build_redistribute([("r1", dev)])
        assert entries[0]["route_map"] == "RM-OUT"

    def test_build_redistribute_omits_metric_when_none(self):
        """metric=None のとき build_redistribute エントリに 'metric' キーが出ないこと。"""
        from lib.build import build_redistribute
        from lib.models import Device, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.redistribute.append(Redistribute(into="bgp", source="connected", metric=None))
        entries = build_redistribute([("r1", dev)])
        assert "metric" not in entries[0]

    def test_build_redistribute_omits_route_map_when_none(self):
        """route_map=None のとき build_redistribute エントリに 'route_map' キーが出ないこと。"""
        from lib.build import build_redistribute
        from lib.models import Device, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.redistribute.append(Redistribute(into="ospf", source="static", route_map=None))
        entries = build_redistribute([("r1", dev)])
        assert "route_map" not in entries[0]

    def test_build_redistribute_empty_when_no_entries(self):
        """redistribute のない device では空リストを返すこと。"""
        from lib.build import build_redistribute
        from lib.models import Device
        dev = Device(hostname="R1", vendor="cisco_ios")
        entries = build_redistribute([("r1", dev)])
        assert entries == []

    def test_build_redistribute_multiple_devices(self):
        """複数 device の redistribute が結合されること。"""
        from lib.build import build_redistribute
        from lib.models import Device, Redistribute
        dev1 = Device(hostname="R1", vendor="cisco_ios")
        dev1.redistribute.append(Redistribute(into="bgp", source="connected"))
        dev2 = Device(hostname="R2", vendor="cisco_ios")
        dev2.redistribute.append(Redistribute(into="ospf", source="bgp"))
        entries = build_redistribute([("r1", dev1), ("r2", dev2)])
        assert len(entries) == 2
        assert entries[0]["device"] == "r1"
        assert entries[1]["device"] == "r2"

    def test_build_topology_routing_has_redistribute_key(self):
        """build_topology の routing dict に 'redistribute' キーが含まれること。"""
        from lib.build import build_topology
        from lib.models import Device, Interface, Address
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.interfaces = [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])]
        topo = build_topology([dev], ["r1.cfg"])
        assert "redistribute" in topo["routing"]

    def test_build_topology_redistribute_populated(self):
        """Device に redistribute がある場合 routing.redistribute にエントリが含まれること。"""
        from lib.build import build_topology
        from lib.models import Device, Interface, Address, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios")
        dev.interfaces = [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)])]
        dev.redistribute.append(Redistribute(into="bgp", source="connected"))
        topo = build_topology([dev], ["r1.cfg"])
        assert len(topo["routing"]["redistribute"]) == 1
        assert topo["routing"]["redistribute"][0]["device"] == "r1"
        assert topo["routing"]["redistribute"][0]["source"] == "connected"


# ===========================================================================
# 4. topology_io.py: routing.redistribute dump/load ラウンドトリップ
# ===========================================================================

class TestTopologyIoRedistribute:
    """topology_io が routing.redistribute を正しく dump/load すること。"""

    def _minimal_topo_with_redistribute(self):
        return {
            "meta": {"schema_version": "1.0", "title": "T", "generated_from": ["a.cfg"]},
            "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
                         "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
            "interfaces": [{"id": "r1::Gi0", "device": "r1", "name": "Gi0", "ip": "10.0.0.1/30",
                            "vlan": None, "description": None, "shutdown": False,
                            "admin_status": "up", "oper_status": None, "mtu": None, "speed": None,
                            "duplex": None, "l2_l3": "l3", "switchport": None,
                            "encapsulation": None, "source": "parsed",
                            "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]}],
            "links": [], "segments": [],
            "routing": {
                "bgp": [], "ospf": [], "static": [],
                "redistribute": [
                    {"device": "r1", "into": "bgp", "source": "connected"},
                ],
            },
        }

    def test_dump_creates_routing_redistribute_yaml(self, tmp_path):
        """非空の routing.redistribute があるとき routing.redistribute.yaml が生成されること。"""
        from lib.topology_io import dump_topology
        topo = self._minimal_topo_with_redistribute()
        dump_topology(topo, str(tmp_path))
        assert (tmp_path / "routing.redistribute.yaml").exists()

    def test_dump_routing_redistribute_yaml_content(self, tmp_path):
        """routing.redistribute.yaml の内容が正しいこと。"""
        from lib.topology_io import dump_topology
        topo = self._minimal_topo_with_redistribute()
        dump_topology(topo, str(tmp_path))
        text = (tmp_path / "routing.redistribute.yaml").read_text(encoding="utf-8")
        assert "redistribute:" in text
        assert "device: r1" in text
        assert "into: bgp" in text
        assert "source: connected" in text

    def test_empty_redistribute_file_not_written(self, tmp_path):
        """routing.redistribute が空のとき routing.redistribute.yaml が生成されないこと。"""
        from lib.topology_io import dump_topology
        topo = self._minimal_topo_with_redistribute()
        topo["routing"]["redistribute"] = []
        dump_topology(topo, str(tmp_path))
        assert not (tmp_path / "routing.redistribute.yaml").exists()

    def test_roundtrip_preserves_redistribute(self, tmp_path):
        """dump → load のラウンドトリップで routing.redistribute が保持されること。"""
        from lib.topology_io import dump_topology, load_topology
        topo = self._minimal_topo_with_redistribute()
        dump_topology(topo, str(tmp_path))
        loaded = load_topology(str(tmp_path))
        assert "redistribute" in loaded["routing"]
        entries = loaded["routing"]["redistribute"]
        assert len(entries) == 1
        assert entries[0]["device"] == "r1"
        assert entries[0]["into"] == "bgp"
        assert entries[0]["source"] == "connected"

    def test_roundtrip_preserves_metric_and_route_map(self, tmp_path):
        """dump → load で metric と route_map が保持されること。"""
        from lib.topology_io import dump_topology, load_topology
        topo = self._minimal_topo_with_redistribute()
        topo["routing"]["redistribute"] = [
            {"device": "r1", "into": "ospf", "source": "bgp", "metric": 50, "route_map": "RM-OUT"},
        ]
        dump_topology(topo, str(tmp_path))
        loaded = load_topology(str(tmp_path))
        e = loaded["routing"]["redistribute"][0]
        assert e["metric"] == 50
        assert e["route_map"] == "RM-OUT"

    def test_load_without_redistribute_file_returns_empty(self, tmp_path):
        """routing.redistribute.yaml が存在しない場合、routing.redistribute は空リストになること。"""
        from lib.topology_io import dump_topology, load_topology
        topo = self._minimal_topo_with_redistribute()
        topo["routing"]["redistribute"] = []  # 空なのでファイル生成されない
        dump_topology(topo, str(tmp_path))
        loaded = load_topology(str(tmp_path))
        assert loaded["routing"]["redistribute"] == []

    def test_dangling_redistribute_device_raises(self, tmp_path):
        """routing.redistribute に未知の device を参照すると ValueError が発生すること。"""
        from lib.topology_io import dump_topology, load_topology
        topo = self._minimal_topo_with_redistribute()
        # 存在しない device を参照
        topo["routing"]["redistribute"] = [
            {"device": "rX", "into": "bgp", "source": "connected"},
        ]
        dump_topology(topo, str(tmp_path))
        with pytest.raises(ValueError) as ei:
            load_topology(str(tmp_path))
        msg = str(ei.value)
        assert "routing.redistribute.yaml" in msg
        assert "rX" in msg


# ===========================================================================
# 5. rendering/data_transform.py: build_devices に redist リスト追加
# ===========================================================================

class TestBuildDevicesRedist:
    """build_devices が routing.redistribute から device 別 redistribute リストを構築すること。"""

    def _topo(self, devices, interfaces, redistribute=None, **routing_extra):
        routing = {"bgp": [], "ospf": [], "static": [], "redistribute": redistribute or []}
        routing.update(routing_extra)
        return {"meta": {}, "devices": devices, "interfaces": interfaces,
                "links": [], "segments": [], "routing": routing}

    def _dev(self, id, hostname="H", vendor="cisco_ios", as_=None):
        return {"id": id, "hostname": hostname, "vendor": vendor, "as": as_,
                "ospf_router_id": None, "bgp_router_id": None, "sections": []}

    def _if(self, device, name, addresses=None):
        return {"id": "%s::%s" % (device, name), "device": device, "name": name,
                "ip": None, "vlan": None, "description": None, "shutdown": False,
                "admin_status": "up", "oper_status": None, "mtu": None, "speed": None,
                "duplex": None, "l2_l3": None, "switchport": None, "encapsulation": None,
                "source": "parsed", "addresses": addresses or []}

    def test_device_has_redistribute_key(self):
        """build_devices の device dict に 'redistribute' キーが含まれること。"""
        from lib.rendering.data_transform import build_devices
        topo = self._topo([self._dev("r1")], [])
        d = build_devices(topo)
        assert "redistribute" in d["r1"]

    def test_device_redistribute_empty_when_no_redistribute(self):
        """routing.redistribute が空のとき device.redistribute が空リストであること。"""
        from lib.rendering.data_transform import build_devices
        topo = self._topo([self._dev("r1")], [])
        d = build_devices(topo)
        assert d["r1"]["redistribute"] == []

    def test_device_redistribute_populated(self):
        """routing.redistribute のエントリが device 別に集約されること。"""
        from lib.rendering.data_transform import build_devices
        redist = [{"device": "r1", "into": "bgp", "source": "connected"}]
        topo = self._topo([self._dev("r1")], [], redistribute=redist)
        d = build_devices(topo)
        assert len(d["r1"]["redistribute"]) == 1
        r = d["r1"]["redistribute"][0]
        assert r["into"] == "bgp"
        assert r["source"] == "connected"

    def test_device_redistribute_with_metric_and_route_map(self):
        """metric と route_map がある redistribute エントリが正しく集約されること。"""
        from lib.rendering.data_transform import build_devices
        redist = [{"device": "r1", "into": "ospf", "source": "bgp", "metric": 50, "route_map": "RM-OUT"}]
        topo = self._topo([self._dev("r1")], [], redistribute=redist)
        d = build_devices(topo)
        r = d["r1"]["redistribute"][0]
        assert r["metric"] == 50
        assert r["route_map"] == "RM-OUT"

    def test_device_redistribute_separate_per_device(self):
        """複数 device に redistribute があるとき device 別に分離されること。"""
        from lib.rendering.data_transform import build_devices
        redist = [
            {"device": "r1", "into": "bgp", "source": "connected"},
            {"device": "r2", "into": "ospf", "source": "bgp"},
        ]
        topo = self._topo([self._dev("r1"), self._dev("r2")], [], redistribute=redist)
        d = build_devices(topo)
        assert len(d["r1"]["redistribute"]) == 1 and d["r1"]["redistribute"][0]["source"] == "connected"
        assert len(d["r2"]["redistribute"]) == 1 and d["r2"]["redistribute"][0]["source"] == "bgp"

    def test_device_redistribute_only_own_entries(self):
        """あるデバイスには自分宛のエントリのみ集約されること（他デバイスのエントリを含まない）。"""
        from lib.rendering.data_transform import build_devices
        redist = [
            {"device": "r1", "into": "bgp", "source": "connected"},
            {"device": "r2", "into": "ospf", "source": "bgp"},
        ]
        topo = self._topo([self._dev("r1"), self._dev("r2")], [], redistribute=redist)
        d = build_devices(topo)
        # r1 は自分のエントリ(bgp/connected)のみ
        assert all(r["into"] == "bgp" for r in d["r1"]["redistribute"])
        # r2 は自分のエントリ(ospf/bgp)のみ
        assert all(r["into"] == "ospf" for r in d["r2"]["redistribute"])

    def test_redistribute_without_key_in_routing_defaults_empty(self):
        """routing に 'redistribute' キーが存在しない場合でも 'redistribute' が空リストであること（後方互換）。"""
        from lib.rendering.data_transform import build_devices
        topo = {"meta": {}, "devices": [self._dev("r1")], "interfaces": [],
                "links": [], "segments": [],
                "routing": {"bgp": [], "ospf": [], "static": []}}  # redistribute キーなし
        d = build_devices(topo)
        assert d["r1"]["redistribute"] == []


# ===========================================================================
# 6. Golden E2E 回帰テスト: routing.redistribute.yaml が生成されないこと
# ===========================================================================

class TestGoldenRedistributeAbsent:
    """sample config に redistribute がないため、golden ファイルが変わらないことを確認。"""

    @pytest.mark.integration
    def test_golden_no_redistribute_yaml(self, tmp_path):
        """サンプル config で build_topology を実行すると routing.redistribute.yaml が生成されないこと。"""
        from pathlib import Path
        from lib.parsers import parse_config
        from lib.build import build_topology
        from lib.topology_io import dump_topology

        cfg_dir = Path(__file__).resolve().parents[1] / "examples" / "configs"
        configs = list(cfg_dir.glob("*.cfg")) + list(cfg_dir.glob("*.conf"))
        parsed = []
        for p in sorted(configs):
            dev = parse_config(p.read_text(encoding="utf-8"), str(p))
            if dev is not None:
                parsed.append(dev)

        topo = build_topology(parsed, [c.name for c in sorted(configs)])
        dump_topology(topo, str(tmp_path))

        # redistribute がない → ファイルが生成されない
        assert not (tmp_path / "routing.redistribute.yaml").exists()
        # 他ファイルは常時生成される
        assert (tmp_path / "_meta.yaml").exists()
        assert (tmp_path / "devices.yaml").exists()
        assert (tmp_path / "physical.yaml").exists()


# ===========================================================================
# C5 修正1: data_transform.py キー名 "redist" → "redistribute"
# ===========================================================================

class TestBuildDevicesRedistributeKey:
    """build_devices の device dict キーが 'redist' から 'redistribute' に変わること。"""

    def _topo(self, devices, interfaces, redistribute=None):
        routing = {"bgp": [], "ospf": [], "static": [], "redistribute": redistribute or []}
        return {"meta": {}, "devices": devices, "interfaces": interfaces,
                "links": [], "segments": [], "routing": routing}

    def _dev(self, id_):
        return {"id": id_, "hostname": "H", "vendor": "cisco_ios", "as": None,
                "ospf_router_id": None, "bgp_router_id": None, "sections": []}

    def test_device_has_redistribute_key_not_redist(self):
        """build_devices の device dict に 'redistribute' キーが含まれること（旧 'redist' は廃止）。"""
        from lib.rendering.data_transform import build_devices
        topo = self._topo([self._dev("r1")], [])
        d = build_devices(topo)
        # 新キーが存在すること
        assert "redistribute" in d["r1"], "'redistribute' キーが存在しない"
        # 旧キーが存在しないこと
        assert "redist" not in d["r1"], "'redist' キーが残存している（'redistribute' に変更すること）"

    def test_device_redistribute_empty_when_no_entries(self):
        """routing.redistribute が空のとき device.redistribute が空リストであること。"""
        from lib.rendering.data_transform import build_devices
        topo = self._topo([self._dev("r1")], [])
        d = build_devices(topo)
        assert d["r1"]["redistribute"] == []

    def test_device_redistribute_populated(self):
        """routing.redistribute のエントリが device.redistribute に集約されること。"""
        from lib.rendering.data_transform import build_devices
        redist = [{"device": "r1", "into": "bgp", "source": "connected"}]
        topo = self._topo([self._dev("r1")], [], redistribute=redist)
        d = build_devices(topo)
        assert len(d["r1"]["redistribute"]) == 1
        assert d["r1"]["redistribute"][0]["into"] == "bgp"
        assert d["r1"]["redistribute"][0]["source"] == "connected"

    def test_device_redistribute_metric_and_route_map(self):
        """metric / route_map を含む redistribute エントリが device.redistribute に含まれること。"""
        from lib.rendering.data_transform import build_devices
        redist = [{"device": "r1", "into": "ospf", "source": "bgp",
                   "metric": 50, "route_map": "RM-OUT"}]
        topo = self._topo([self._dev("r1")], [], redistribute=redist)
        d = build_devices(topo)
        r = d["r1"]["redistribute"][0]
        assert r["metric"] == 50
        assert r["route_map"] == "RM-OUT"

    def test_device_redistribute_per_device_isolation(self):
        """複数 device の redistribute が正しく分離されること。"""
        from lib.rendering.data_transform import build_devices
        redist = [
            {"device": "r1", "into": "bgp", "source": "connected"},
            {"device": "r2", "into": "ospf", "source": "bgp"},
        ]
        topo = self._topo([self._dev("r1"), self._dev("r2")], [], redistribute=redist)
        d = build_devices(topo)
        assert len(d["r1"]["redistribute"]) == 1
        assert d["r1"]["redistribute"][0]["source"] == "connected"
        assert len(d["r2"]["redistribute"]) == 1
        assert d["r2"]["redistribute"][0]["source"] == "bgp"


# ===========================================================================
# C5 修正2: topology_io.py — _ROUTING_PROTOS 定数化
# ===========================================================================

class TestTopologyIoRoutingProtos:
    """topology_io に _ROUTING_PROTOS モジュール定数が存在し、dump/load で使われること。"""

    def test_routing_protos_constant_exists(self):
        """_ROUTING_PROTOS がモジュールレベルの定数として定義されていること。"""
        from lib import topology_io
        assert hasattr(topology_io, "_ROUTING_PROTOS"), (
            "_ROUTING_PROTOS 定数が topology_io に存在しない"
        )

    def test_routing_protos_is_tuple(self):
        """_ROUTING_PROTOS がタプル型であること。"""
        from lib import topology_io
        assert isinstance(topology_io._ROUTING_PROTOS, tuple)

    def test_routing_protos_contains_all_four_protos(self):
        """_ROUTING_PROTOS が bgp/ospf/static/redistribute を含むこと。"""
        from lib import topology_io
        protos = topology_io._ROUTING_PROTOS
        for p in ("bgp", "ospf", "static", "redistribute"):
            assert p in protos, "_ROUTING_PROTOS に '%s' が含まれていない" % p

    def test_routing_protos_used_in_dump(self):
        """dump_topology のソースコードが _ROUTING_PROTOS を参照していること（ハードコード廃止）。"""
        import inspect
        from lib import topology_io
        src = inspect.getsource(topology_io.dump_topology)
        assert "_ROUTING_PROTOS" in src, (
            "dump_topology でハードコードされたタプルを使用中。_ROUTING_PROTOS に統一すること"
        )

    def test_routing_protos_used_in_load(self):
        """load_topology のソースコードが _ROUTING_PROTOS を参照していること（ハードコード廃止）。"""
        import inspect
        from lib import topology_io
        src = inspect.getsource(topology_io.load_topology)
        assert "_ROUTING_PROTOS" in src, (
            "load_topology でハードコードされたタプルを使用中。_ROUTING_PROTOS に統一すること"
        )


# ===========================================================================
# C5 修正3: ios.py — _parse_bgp_line / _parse_ospf_line docstring
# ===========================================================================

class TestIosParserRedistributeDocstring:
    """_parse_bgp_line と _parse_ospf_line の docstring に redistribute 処理の記述があること。"""

    def test_parse_bgp_line_docstring_mentions_redistribute(self):
        """_parse_bgp_line の docstring に 'redistribute' が含まれること。"""
        import inspect
        from lib.parsers import ios
        doc = ios._parse_bgp_line.__doc__ or ""
        assert "redistribute" in doc, (
            "_parse_bgp_line の docstring に 'redistribute' の記述がない"
        )

    def test_parse_ospf_line_docstring_mentions_redistribute(self):
        """_parse_ospf_line の docstring に 'redistribute' が含まれること。"""
        import inspect
        from lib.parsers import ios
        doc = ios._parse_ospf_line.__doc__ or ""
        assert "redistribute" in doc, (
            "_parse_ospf_line の docstring に 'redistribute' の記述がない"
        )


# ===========================================================================
# C5 修正4: address-family ipv6 配下 redistribute + パース順序テスト
# ===========================================================================

class TestRedistributeAddressFamilyAndOrder:
    """BGP address-family ipv6 配下の redistribute と複数エントリの順序テスト。"""

    def _parse(self, text):
        from lib.parsers.ios import parse_ios
        warnings = []
        return parse_ios(text, warnings), warnings

    def test_bgp_af_ipv6_redistribute_connected(self):
        """router bgp の address-family ipv6 配下の redistribute connected が
        into='bgp', source='connected' として抽出されること（現挙動の固定）。
        """
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " address-family ipv6\n"
            "  redistribute connected\n"
            " exit-address-family\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.into == "bgp"
        assert r.source == "connected"

    def test_bgp_af_ipv6_redistribute_static(self):
        """address-family ipv6 配下の redistribute static が into='bgp' として抽出されること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " address-family ipv6\n"
            "  redistribute static route-map RM-V6\n"
            " exit-address-family\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        assert len(dev.redistribute) == 1
        r = dev.redistribute[0]
        assert r.into == "bgp"
        assert r.source == "static"
        assert r.route_map == "RM-V6"

    def test_bgp_af_ipv4_and_ipv6_redistribute_order(self):
        """address-family ipv4 と address-family ipv6 の両方に redistribute があるとき
        config 順（パース順）でエントリが並ぶこと。
        """
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " address-family ipv4\n"
            "  redistribute connected\n"
            " exit-address-family\n"
            " address-family ipv6\n"
            "  redistribute static\n"
            " exit-address-family\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        assert len(dev.redistribute) == 2
        # config 順: connected → static
        assert dev.redistribute[0].source == "connected"
        assert dev.redistribute[1].source == "static"

    def test_build_redistribute_preserves_config_order(self):
        """build_redistribute が複数エントリを config 順（パース順）で出力すること。"""
        from lib.build import build_redistribute
        from lib.models import Device, Redistribute
        dev = Device(hostname="R1", vendor="cisco_ios")
        # config の出現順を想定: ospf → connected → static
        dev.redistribute.append(Redistribute(into="bgp", source="ospf", metric=10))
        dev.redistribute.append(Redistribute(into="bgp", source="connected"))
        dev.redistribute.append(Redistribute(into="bgp", source="static", route_map="RM"))
        entries = build_redistribute([("r1", dev)])
        assert len(entries) == 3
        assert entries[0]["source"] == "ospf"
        assert entries[1]["source"] == "connected"
        assert entries[2]["source"] == "static"

    def test_build_redistribute_order_multiple_devices(self):
        """複数 device の redistribute は device 出現順に連結されること。"""
        from lib.build import build_redistribute
        from lib.models import Device, Redistribute
        dev1 = Device(hostname="R1", vendor="cisco_ios")
        dev1.redistribute.append(Redistribute(into="bgp", source="connected"))
        dev2 = Device(hostname="R2", vendor="cisco_ios")
        dev2.redistribute.append(Redistribute(into="ospf", source="bgp"))
        dev2.redistribute.append(Redistribute(into="ospf", source="static"))
        entries = build_redistribute([("r1", dev1), ("r2", dev2)])
        # device 順: r1 が先
        assert entries[0]["device"] == "r1"
        assert entries[1]["device"] == "r2"
        assert entries[2]["device"] == "r2"
        # r2 内順序: bgp → static
        assert entries[1]["source"] == "bgp"
        assert entries[2]["source"] == "static"


# ===========================================================================
# C5 修正5: ios.py — `no ` ガードの厳密化
# ===========================================================================

class TestNoRedistributeGuard:
    """`no redistribute` 専用ガードが他の `no ...` 行に影響しないこと。"""

    def _parse(self, text):
        from lib.parsers.ios import parse_ios
        warnings = []
        return parse_ios(text, warnings), warnings

    def test_no_redistribute_static_skipped_in_bgp(self):
        """`no redistribute static` は bgp 文脈でスキップされること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " no redistribute static\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        assert dev.redistribute == []

    def test_no_redistribute_connected_skipped_in_ospf(self):
        """`no redistribute connected` は ospf 文脈でスキップされること。"""
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " no redistribute connected\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        assert dev.redistribute == []

    def test_no_redistribute_bgp_skipped_in_ospf(self):
        """`no redistribute bgp 65001 subnets` は ospf 文脈でスキップされること。"""
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " no redistribute bgp 65001 subnets\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        assert dev.redistribute == []

    def test_bgp_no_other_line_does_not_break_parse(self):
        """bgp 文脈で redistribute 以外の `no ...` 行（`no auto-summary` 等）が
        redistribute パース全体を壊さないこと。
        """
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " no auto-summary\n"
            " no synchronization\n"
            " redistribute connected\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        # redistribute 行は正常に抽出される
        assert len(dev.redistribute) == 1
        assert dev.redistribute[0].source == "connected"

    def test_ospf_no_other_line_does_not_break_parse(self):
        """ospf 文脈で redistribute 以外の `no ...` 行（`no passive-interface` 等）が
        redistribute パースを壊さないこと。
        """
        text = (
            "hostname R1\n"
            "router ospf 1\n"
            " no passive-interface default\n"
            " redistribute bgp 65001 subnets\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        assert len(dev.redistribute) == 1
        assert dev.redistribute[0].source == "bgp"

    def test_no_redistribute_followed_by_valid_redistribute(self):
        """`no redistribute` の後に有効な redistribute 行が続くとき、有効行のみ抽出されること。"""
        text = (
            "hostname R1\n"
            "router bgp 65001\n"
            " no redistribute connected\n"
            " redistribute static metric 100\n"
            "!\n"
        )
        dev, _ = self._parse(text)
        assert len(dev.redistribute) == 1
        assert dev.redistribute[0].source == "static"
        assert dev.redistribute[0].metric == 100
