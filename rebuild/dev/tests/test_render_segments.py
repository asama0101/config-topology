"""DATA.segments（members iface_id → {dev,ifn,ip}）のテスト（§8.4）。"""
import pytest

from lib.rendering.data_transform import build_segments

pytestmark = pytest.mark.unit


def _topo(interfaces, segments):
    return {"meta": {}, "devices": [], "interfaces": interfaces,
            "links": [], "segments": segments, "routing": {"bgp": [], "ospf": [], "static": []}}


def _if(device, name, addresses):
    return {"id": "%s::%s" % (device, name), "device": device, "name": name,
            "addresses": addresses}


def test_segment_members_resolved():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "192.168.1.1", "prefix": 24}]),
           _if("r2", "Gi0", [{"af": "v4", "ip": "192.168.1.2", "prefix": 24}]),
           _if("r3", "Gi0", [{"af": "v4", "ip": "192.168.1.3", "prefix": 24}])]
    segs = [{"id": "seg-192_168_1_0_24", "subnet": "192.168.1.0/24",
             "members": ["r1::Gi0", "r2::Gi0", "r3::Gi0"]}]
    out = build_segments(_topo(ifs, segs))
    assert len(out) == 1
    s = out[0]
    assert s["id"] == "seg-192_168_1_0_24" and s["subnet"] == "192.168.1.0/24"
    assert s["members"] == [{"dev": "r1", "ifn": "Gi0", "ip": "192.168.1.1"},
                            {"dev": "r2", "ifn": "Gi0", "ip": "192.168.1.2"},
                            {"dev": "r3", "ifn": "Gi0", "ip": "192.168.1.3"}]
    assert "area" not in s


def test_segment_area_projected():
    ifs = [_if("r1", "Gi0", [{"af": "v4", "ip": "10.0.0.1", "prefix": 24}]),
           _if("r2", "Gi0", [{"af": "v4", "ip": "10.0.0.2", "prefix": 24}]),
           _if("r3", "Gi0", [{"af": "v4", "ip": "10.0.0.3", "prefix": 24}])]
    segs = [{"id": "seg-x", "subnet": "10.0.0.0/24",
             "members": ["r1::Gi0", "r2::Gi0", "r3::Gi0"], "ospf_area": "0/1"}]
    assert build_segments(_topo(ifs, segs))[0]["area"] == "0/1"
