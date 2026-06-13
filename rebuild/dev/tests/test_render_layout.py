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
