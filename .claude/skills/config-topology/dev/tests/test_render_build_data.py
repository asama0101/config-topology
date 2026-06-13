"""DATA 全体組立（build_data）— 附録 B.3 トポロジーでの統合テスト。"""
import json
from pathlib import Path

import pytest

from lib.topology_io import load_topology
from lib.rendering.data_transform import build_data

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).resolve().parents[1] / "examples" / "topology"


def test_build_data_from_golden():
    topo = load_topology(str(GOLDEN))
    data = build_data(topo)
    assert set(data["devices"]) == {"r1", "r2"}
    assert data["devices"]["r1"]["hostname"] == "R1"
    assert len(data["links"]) == 1 and data["links"][0]["subnet"] == "10.0.0.0/30"
    assert data["segments"] == []
    assert data["extPeers"] == []
    overs = [e for e in data["bgpEdges"] if e["kind"] == "over-link"]
    assert len(overs) == 1
    # 実 build_data 経路で afs が付与される（v4-only ゴールデンなので ["v4"]）
    assert isinstance(overs[0]["afs"], list) and overs[0]["afs"] == ["v4"]
    for dev in ("r1", "r2"):
        for row in data["devices"][dev]["bgp"]:
            assert row["link"] == overs[0]["id"]
    assert data["meta"]["generated_from"] == ["sample-ios-r1.cfg", "sample-junos-r2.conf"]


def test_build_data_deterministic():
    topo = load_topology(str(GOLDEN))
    a = json.dumps(build_data(topo), sort_keys=True)
    b = json.dumps(build_data(topo), sort_keys=True)
    assert a == b


def test_same_neighbor_two_sessions_distinct_links():
    # 同一 (device, neighbor_ip) の 2 セッションが別エッジを指すケースで前行が誤らない
    topo = {
        "meta": {"generated_from": []},
        "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []},
                    {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65001,
                     "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
        "interfaces": [
            {"id": "r1::Gi0", "device": "r1", "name": "Gi0", "ip": "10.0.0.1/30", "vlan": None,
             "description": None, "shutdown": False, "admin_status": "up", "oper_status": None,
             "mtu": None, "speed": None, "duplex": None, "l2_l3": None, "switchport": None,
             "encapsulation": None, "source": "parsed",
             "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}]},
            {"id": "r2::ge0", "device": "r2", "name": "ge0", "ip": "10.0.0.2/30", "vlan": None,
             "description": None, "shutdown": False, "admin_status": "up", "oper_status": None,
             "mtu": None, "speed": None, "duplex": None, "l2_l3": None, "switchport": None,
             "encapsulation": None, "source": "parsed",
             "addresses": [{"af": "v4", "ip": "10.0.0.2", "prefix": 30}]},
        ],
        "links": [{"a_device": "r1", "a_if": "Gi0", "b_device": "r2", "b_if": "ge0",
                   "subnet": "10.0.0.0/30", "kind": "inferred-subnet"}],
        "segments": [],
        "routing": {"bgp": [
            {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
             "neighbor_ip": "10.0.0.2", "peer_as": 65001, "type": "ibgp", "af": "v4"}],
            "ospf": [], "static": []},
    }
    data = build_data(topo)
    # over-link セッションは over-link エッジを指す
    assert data["devices"]["r1"]["bgp"][0]["link"].startswith("be:ol:")
