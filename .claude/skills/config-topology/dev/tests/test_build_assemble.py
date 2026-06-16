"""§7.4 OSPF area 注釈・§7.5 順序・全体組立のテスト。"""
import pytest

from lib.models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from lib.build import (build_ospf, build_static, annotate_ospf, aggregate_areas,
                       build_topology)

pytestmark = pytest.mark.unit


def test_build_ospf_and_static_flatten():
    d = Device(hostname="R1", vendor="cisco_ios", as_=1)
    d.ospf = [OspfNetwork(1, "192.168.1.0/24", "0", "v4")]
    d.static = [StaticRoute("0.0.0.0/0", "10.0.0.2", "v4")]
    assert build_ospf([("r1", d)]) == [{"device": "r1", "process": 1,
                                        "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    assert build_static([("r1", d)]) == [{"device": "r1", "prefix": "0.0.0.0/0",
                                          "next_hop": "10.0.0.2", "af": "v4"}]


def test_aggregate_areas():
    assert aggregate_areas(["0"]) == "0"
    assert aggregate_areas(["0", "0"]) == "0"
    assert aggregate_areas(["1", "0"]) == "0/1"
    assert aggregate_areas(["10", "2"]) == "2/10"
    assert aggregate_areas(["backbone", "0"]) == "0/backbone"


def test_annotate_ospf_on_link():
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "192.168.1.0/24", "kind": "inferred-subnet"}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"},
            {"device": "r2", "process": None, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    annotate_ospf(links, [], ospf, {})
    assert links[0]["ospf_area"] == "0" and links[0]["ospf_network"] == "192.168.1.0/24"


def test_annotate_skips_admin_down_link():
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "192.168.1.0/24", "kind": "inferred-subnet", "admin_down": True}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    annotate_ospf(links, [], ospf, {})
    assert "ospf_area" not in links[0]


def test_annotate_segment_area():
    segments = [{"id": "seg-192_168_1_0_24", "subnet": "192.168.1.0/24",
                 "members": ["r1::Gi0", "r2::Gi0"]}]
    ospf = [{"device": "r1", "process": 1, "network": "192.168.1.0/24", "area": "1", "af": "v4"},
            {"device": "r2", "process": 1, "network": "192.168.1.0/24", "area": "0", "af": "v4"}]
    iface_dev = {"r1::Gi0": "r1", "r2::Gi0": "r2"}
    annotate_ospf([], segments, ospf, iface_dev)
    assert segments[0]["ospf_area"] == "0/1"


def test_annotate_only_endpoint_devices_count():
    # subnet が一致しても、端点でない device の ospf エントリは集約に含めない
    links = [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
              "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}]
    ospf = [{"device": "r3", "process": 1, "network": "10.0.0.0/30", "area": "5", "af": "v4"}]
    annotate_ospf(links, [], ospf, {})
    assert "ospf_area" not in links[0]


def test_build_topology_orders_and_routing_keys():
    r1 = Device(hostname="R1", vendor="cisco_ios", as_=65001)
    r1.interfaces = [Interface(name="Gi0", addresses=[Address("v4", "10.0.0.1", 30)],
                               admin_status="up")]
    r1.bgp = [BgpNeighbor("10.0.0.2", 65002, "v4")]
    r2 = Device(hostname="R2", vendor="juniper_junos", as_=65002)
    r2.interfaces = [Interface(name="ge0", addresses=[Address("v4", "10.0.0.2", 30)],
                               admin_status="up")]
    r2.bgp = [BgpNeighbor("10.0.0.1", 65001, "v4")]
    topo = build_topology([r1, r2], ["r1.cfg", "r2.conf"])
    assert topo["meta"] == {"schema_version": "1.0",
                            "title": "Network Topology (config-derived)",
                            "generated_from": ["r1.cfg", "r2.conf"]}
    assert [d["id"] for d in topo["devices"]] == ["r1", "r2"]
    assert len(topo["links"]) == 1
    assert [e["device"] for e in topo["routing"]["bgp"]] == ["r1", "r2"]
    assert topo["routing"]["ospf"] == [] and topo["routing"]["static"] == []


# ---------------------------------------------------------------------------
# C3: build_ospf に area_type が透過すること（omit-when-None）
# ---------------------------------------------------------------------------

def test_build_ospf_area_type_transparent_when_set():
    """OspfNetwork.area_type が 'stub' のとき build_ospf エントリに 'area_type' キーが出ること。"""
    d = Device(hostname="R1", vendor="cisco_ios")
    d.ospf = [OspfNetwork(1, "10.1.0.0/24", "1", "v4", area_type="stub")]
    result = build_ospf([("r1", d)])
    assert len(result) == 1
    assert result[0]["area_type"] == "stub"


def test_build_ospf_area_type_omitted_when_none():
    """OspfNetwork.area_type が None のとき build_ospf エントリに 'area_type' キーが出ないこと
    （golden byte 不変を保証）。"""
    d = Device(hostname="R1", vendor="cisco_ios")
    d.ospf = [OspfNetwork(1, "192.168.1.0/24", "0", "v4")]
    result = build_ospf([("r1", d)])
    assert len(result) == 1
    assert "area_type" not in result[0]
    assert set(result[0].keys()) == {"device", "process", "network", "area", "af"}


def test_build_ospf_area_type_all_normalized_values():
    """stub/totally-stubby/nssa/totally-nssa の4値すべてが透過されること。"""
    d = Device(hostname="R1", vendor="cisco_ios")
    d.ospf = [
        OspfNetwork(1, "10.1.0.0/24", "1", "v4", area_type="stub"),
        OspfNetwork(1, "10.2.0.0/24", "2", "v4", area_type="totally-stubby"),
        OspfNetwork(1, "10.3.0.0/24", "3", "v4", area_type="nssa"),
        OspfNetwork(1, "10.4.0.0/24", "4", "v4", area_type="totally-nssa"),
    ]
    result = build_ospf([("r1", d)])
    types = {e["area"]: e.get("area_type") for e in result}
    assert types == {"1": "stub", "2": "totally-stubby", "3": "nssa", "4": "totally-nssa"}


# ---------------------------------------------------------------------------
# CONFIG ビュー — 生 running-config 保持（raw_texts → raw_configs）
# ---------------------------------------------------------------------------

def test_build_topology_raw_texts_mapped_to_device_ids():
    """raw_texts（parsed と並走）が device id をキーに raw_configs へ写像されること。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    d2 = Device(hostname="R2", vendor="cisco_ios", as_=2)
    topo = build_topology([d1, d2], ["r1.cfg", "r2.cfg"],
                          raw_texts=["hostname R1\n", "hostname R2\n"])
    assert topo["raw_configs"] == {"r1": "hostname R1\n", "r2": "hostname R2\n"}


def test_build_topology_raw_texts_none_gives_empty():
    """raw_texts 省略時は raw_configs が空 dict（後方互換）。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    topo = build_topology([d1], ["r1.cfg"])
    assert topo["raw_configs"] == {}


def test_build_topology_raw_texts_preserves_multiline():
    """複数行 config がそのまま（行末・空行含め）保持されること。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    text = "hostname R1\n!\ninterface Gi0/0\n ip address 10.0.0.1 255.255.255.252\n!\n"
    topo = build_topology([d1], ["r1.cfg"], raw_texts=[text])
    assert topo["raw_configs"]["r1"] == text


def test_build_topology_raw_texts_length_mismatch_raises():
    """raw_texts の長さが parsed と不一致なら ValueError（zip の暗黙切り捨て防止）。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    d2 = Device(hostname="R2", vendor="cisco_ios", as_=2)
    with pytest.raises(ValueError) as ei:
        build_topology([d1, d2], ["r1.cfg", "r2.cfg"], raw_texts=["only one"])
    assert "raw_texts length" in str(ei.value)


def test_build_topology_parse_statuses_mapped():
    """parse_statuses が device id をキーに topo['parse_status'] へ写像されること。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    d2 = Device(hostname="R2", vendor="cisco_ios", as_=2)
    topo = build_topology([d1, d2], ["r1.cfg", "r2.cfg"],
                          parse_statuses=[["parsed", "ignored"], ["unparsed"]])
    assert topo["parse_status"] == {"r1": ["parsed", "ignored"], "r2": ["unparsed"]}


def test_build_topology_parse_statuses_none_empty():
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    topo = build_topology([d1], ["r1.cfg"])
    assert topo["parse_status"] == {}


def test_build_topology_parse_statuses_length_mismatch_raises():
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    d2 = Device(hostname="R2", vendor="cisco_ios", as_=2)
    with pytest.raises(ValueError):
        build_topology([d1, d2], ["r1.cfg", "r2.cfg"], parse_statuses=[["parsed"]])


# ---------------------------------------------------------------------------
# diagnostics — build_topology diagnostics 引数（T0 インフラ）
# ---------------------------------------------------------------------------

def test_build_topology_diagnostics_stored_when_nonempty():
    """diagnostics=[{...}] を渡すと topology dict に 'diagnostics' キーが入ること。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    diag = [{"severity": "warning", "kind": "parse_warning",
              "message": "unknown command", "refs": ["r1.cfg"]}]
    topo = build_topology([d1], ["r1.cfg"], diagnostics=diag)
    assert "diagnostics" in topo
    assert topo["diagnostics"] == diag


def test_build_topology_diagnostics_key_absent_when_none():
    """diagnostics=None（デフォルト）のとき topology dict に 'diagnostics' キーが出ないこと。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    topo = build_topology([d1], ["r1.cfg"])
    assert "diagnostics" not in topo


def test_build_topology_diagnostics_key_absent_when_empty_list():
    """diagnostics=[] のとき topology dict に 'diagnostics' キーが出ないこと（omit-when-empty）。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    topo = build_topology([d1], ["r1.cfg"], diagnostics=[])
    assert "diagnostics" not in topo


def test_build_topology_diagnostics_multiple_entries():
    """複数の diagnostics エントリが順序を保って格納されること。"""
    d1 = Device(hostname="R1", vendor="cisco_ios", as_=1)
    diag = [
        {"severity": "warning", "kind": "parse_warning", "message": "line 5", "refs": ["r1.cfg"]},
        {"severity": "error", "kind": "unparsed_config", "message": "bad file", "refs": ["bad.cfg"]},
    ]
    topo = build_topology([d1], ["r1.cfg"], diagnostics=diag)
    assert topo["diagnostics"] == diag
