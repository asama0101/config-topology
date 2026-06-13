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
    for dev in ("r1", "r2"):
        for row in data["devices"][dev]["bgp"]:
            assert row["link"] == overs[0]["id"]
    assert data["meta"]["generated_from"] == ["sample-ios-r1.cfg", "sample-junos-r2.conf"]


def test_build_data_deterministic():
    topo = load_topology(str(GOLDEN))
    a = json.dumps(build_data(topo), sort_keys=True)
    b = json.dumps(build_data(topo), sort_keys=True)
    assert a == b
