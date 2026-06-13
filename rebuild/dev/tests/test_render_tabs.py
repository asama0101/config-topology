"""§8.2 タブ生成（図ビュー動的・表ビュー常設・static 除外・キー連番）のテスト。"""
import pytest

from lib.rendering.tabs import build_tabs

pytestmark = pytest.mark.unit


def _routing(bgp=False, ospf=False, static=False):
    return {"bgp": [1] if bgp else [], "ospf": [1] if ospf else [],
            "static": [1] if static else []}


def test_physical_and_tables_always():
    tabs = build_tabs(_routing())
    assert [t["view"] for t in tabs] == ["physical", "addr", "ifs"]


def test_bgp_ospf_conditional():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    assert [t["view"] for t in tabs] == ["physical", "bgp", "ospf", "addr", "ifs"]


def test_only_bgp():
    assert [t["view"] for t in build_tabs(_routing(bgp=True))] == \
        ["physical", "bgp", "addr", "ifs"]


def test_static_never_a_tab():
    assert "static" not in [t["view"] for t in build_tabs(_routing(static=True))]


def test_key_numbers_sequential():
    tabs = build_tabs(_routing(bgp=True))
    assert [t["key"] for t in tabs] == [1, 2, 3, 4]
    no_bgp = build_tabs(_routing())
    assert next(t["key"] for t in no_bgp if t["view"] == "addr") == 2
    assert next(t["key"] for t in tabs if t["view"] == "addr") == 3


def test_labels():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    labels = {t["view"]: t["label"] for t in tabs}
    assert labels == {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
                      "addr": "ADDRESSES", "ifs": "INTERFACES"}
