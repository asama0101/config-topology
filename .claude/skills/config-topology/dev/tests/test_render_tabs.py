"""§8.2 タブ生成（図ビュー動的・表ビュー常設・static 除外・キー連番）のテスト。"""
import pytest

from lib.rendering.tabs import build_tabs

pytestmark = pytest.mark.unit


def _routing(bgp=False, ospf=False, static=False):
    return {"bgp": [1] if bgp else [], "ospf": [1] if ospf else [],
            "static": [1] if static else []}


def test_physical_and_tables_always():
    # stats/checks タブが常設で追加されるため views は ["physical", "stats", "checks", "addr", "ifs"]
    tabs = build_tabs(_routing())
    assert [t["view"] for t in tabs] == ["physical", "stats", "checks", "addr", "ifs"]


def test_bgp_ospf_conditional():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    assert [t["view"] for t in tabs] == ["physical", "bgp", "ospf", "stats", "checks", "addr", "ifs"]


def test_only_bgp():
    assert [t["view"] for t in build_tabs(_routing(bgp=True))] == \
        ["physical", "bgp", "stats", "checks", "addr", "ifs"]


def test_static_never_a_tab():
    assert "static" not in [t["view"] for t in build_tabs(_routing(static=True))]


def test_stats_always_present():
    """stats タブは routing 空でも常設されること。"""
    for routing in [_routing(), _routing(bgp=True), _routing(ospf=True), _routing(static=True)]:
        views = [t["view"] for t in build_tabs(routing)]
        assert "stats" in views, f"stats タブが見つからない: {views}"


def test_stats_label():
    """stats タブのラベルが 'STATS' であること。"""
    tabs = build_tabs(_routing())
    stats_tab = next(t for t in tabs if t["view"] == "stats")
    assert stats_tab["label"] == "STATS"


def test_key_numbers_sequential():
    tabs = build_tabs(_routing(bgp=True))
    # physical, bgp, stats, checks, addr, ifs の 6 タブ
    assert [t["key"] for t in tabs] == [1, 2, 3, 4, 5, 6]
    no_bgp = build_tabs(_routing())
    # physical, stats, checks, addr, ifs の 5 タブ
    assert next(t["key"] for t in no_bgp if t["view"] == "stats") == 2
    assert next(t["key"] for t in no_bgp if t["view"] == "checks") == 3
    assert next(t["key"] for t in no_bgp if t["view"] == "addr") == 4
    assert next(t["key"] for t in tabs if t["view"] == "addr") == 5


def test_labels():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    labels = {t["view"]: t["label"] for t in tabs}
    assert labels == {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
                      "stats": "STATS", "checks": "CHECKS",
                      "addr": "ADDRESSES", "ifs": "INTERFACES"}


# ---------------------------------------------------------------------------
# D2 設計検証パネル — checks タブのテスト
# ---------------------------------------------------------------------------

def test_checks_tab_always_present():
    """checks タブは routing 有無に関係なく常設されること。"""
    for routing in [_routing(), _routing(bgp=True), _routing(ospf=True), _routing(static=True)]:
        views = [t["view"] for t in build_tabs(routing)]
        assert "checks" in views, f"checks タブが見つからない: {views}"


def test_checks_tab_label():
    """checks タブのラベルが 'CHECKS' であること。"""
    tabs = build_tabs(_routing())
    checks_tab = next(t for t in tabs if t["view"] == "checks")
    assert checks_tab["label"] == "CHECKS"


def test_checks_tab_after_stats():
    """checks タブが stats タブの直後に配置されること。"""
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    assert views.index("checks") == views.index("stats") + 1


def test_tabs_order_with_all_routing():
    """全 routing あり: physical→bgp→ospf→stats→checks→addr→ifs の順であること。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True, static=True))
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "stats", "checks", "addr", "ifs"]


def test_tabs_order_no_routing():
    """routing なし: physical→stats→checks→addr→ifs の順であること。"""
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    assert views == ["physical", "stats", "checks", "addr", "ifs"]


def test_key_numbers_sequential_with_checks():
    """checks 追加後もキー番号が連番であること。"""
    tabs = build_tabs(_routing())
    # physical=1, stats=2, checks=3, addr=4, ifs=5
    assert [t["key"] for t in tabs] == [1, 2, 3, 4, 5]

    tabs_bgp = build_tabs(_routing(bgp=True))
    # physical=1, bgp=2, stats=3, checks=4, addr=5, ifs=6
    assert [t["key"] for t in tabs_bgp] == [1, 2, 3, 4, 5, 6]
