"""§8.3 決定的レイアウト（POS）のテスト。"""
import pytest

from lib.rendering.layout import compute_positions

pytestmark = pytest.mark.unit


def _data(dev_ids, seg_ids=(), ext_ids=()):
    return {
        "devices": {d: {} for d in dev_ids},
        "segments": [{"id": s, "members": []} for s in seg_ids],
        "extPeers": [{"id": e} for e in ext_ids],
        "links": [],
    }


def test_all_node_ids_present():
    pos = compute_positions(_data(["r1", "r2", "r3"], seg_ids=["seg-a"], ext_ids=["ext:x"]))
    assert set(pos) == {"r1", "r2", "r3", "seg-a", "ext:x"}
    for p in pos.values():
        assert set(p) == {"x", "y"} and isinstance(p["x"], float) and isinstance(p["y"], float)


def test_deterministic_two_runs():
    d = _data(["r1", "r2", "r3", "r4"], seg_ids=["s1"], ext_ids=["e1"])
    assert compute_positions(d) == compute_positions(d)


def test_coords_rounded_one_decimal():
    pos = compute_positions(_data(["r1", "r2"]))
    for p in pos.values():
        assert round(p["x"], 1) == p["x"] and round(p["y"], 1) == p["y"]


def test_independent_of_dict_input_order():
    a = compute_positions(_data(["r1", "r2", "r3"]))
    b = compute_positions(_data(["r3", "r1", "r2"]))
    assert a == b


def test_empty_data():
    assert compute_positions(_data([])) == {}


def test_segment_and_ext_nodes_stay_bounded():
    # link(d1-d2) + segment(members d1,d2) + extPeer(from d1)
    data = {
        "devices": {"d1": {}, "d2": {}},
        "links": [{"a": "d1", "b": "d2"}],
        "segments": [{"id": "seg-a", "members": [{"dev": "d1"}, {"dev": "d2"}]}],
        "extPeers": [{"id": "ext:203.0.113.7", "from": "d1"}],
        "bgpEdges": [],
    }
    pos = compute_positions(data)
    # 修正前は |座標| ~16000 で発散 → 全ノードが妥当範囲に収まること
    for nid, p in pos.items():
        assert abs(p["x"]) < 3000 and abs(p["y"]) < 3000, (nid, p)

    def dist(a, b):
        return ((pos[a]["x"] - pos[b]["x"]) ** 2 + (pos[a]["y"] - pos[b]["y"]) ** 2) ** 0.5

    # セグメントはいずれかのメンバーデバイス近傍、外部ピアは接続元近傍
    assert min(dist("seg-a", "d1"), dist("seg-a", "d2")) < 2000
    assert dist("ext:203.0.113.7", "d1") < 2000


def test_segment_bbox_does_not_explode_with_many_segments():
    devs = ["d%d" % i for i in range(6)]
    data = {
        "devices": {d: {} for d in devs},
        "links": [{"a": devs[i], "b": devs[i + 1]} for i in range(5)],
        "segments": [
            {"id": "seg-%d" % g,
             "members": [{"dev": devs[g]}, {"dev": devs[g + 1]}, {"dev": devs[(g + 2) % 6]}]}
            for g in range(3)
        ],
        "extPeers": [],
        "bgpEdges": [],
    }
    pos = compute_positions(data)
    xs = [p["x"] for p in pos.values()]
    ys = [p["y"] for p in pos.values()]
    diag = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
    assert diag < 6000, diag      # 発散していない（修正前は数万 px）
