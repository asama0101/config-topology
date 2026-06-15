"""§8.2 タブ生成。図ビュー（physical→bgp?→ospf?）→ 表ビュー（addr,ifs,[config],[diff],checks）。

タブ仕様（SUBNETS 廃止・DIFF/CHECKS を CONFIG の次へ・改修後）:
  表ビュー順序 = ADDRESSES → INTERFACES → [CONFIG] → [DIFF] → CHECKS
    - ADDRESSES / INTERFACES … 常設（先頭）
    - CONFIG … has_config=True のみ
    - DIFF   … has_diff=True のみ
    - CHECKS … 常設（末尾）
  SUBNETS(usage) タブは廃止（存在しない）。STATIC は routing.static 非空時の図ビュー（physical の次）。
"""
import pytest

from lib.rendering.tabs import build_tabs

pytestmark = pytest.mark.unit


def _routing(bgp=False, ospf=False, static=False):
    return {"bgp": [1] if bgp else [], "ospf": [1] if ospf else [],
            "static": [1] if static else []}


# --- 基本順序 -------------------------------------------------------------

def test_no_routing_order():
    assert [t["view"] for t in build_tabs(_routing())] == \
        ["physical", "addr", "ifs", "checks"]


def test_bgp_ospf_conditional():
    assert [t["view"] for t in build_tabs(_routing(bgp=True, ospf=True))] == \
        ["physical", "bgp", "ospf", "addr", "ifs", "checks"]


def test_only_bgp():
    assert [t["view"] for t in build_tabs(_routing(bgp=True))] == \
        ["physical", "bgp", "addr", "ifs", "checks"]


def test_static_tab_present_when_static_routes():
    """routing.static 非空 → STATIC 図ビューが physical の直後に出る。"""
    assert [t["view"] for t in build_tabs(_routing(static=True))] == \
        ["physical", "static", "addr", "ifs", "checks"]


def test_static_tab_absent_without_static_routes():
    assert "static" not in [t["view"] for t in build_tabs(_routing())]


def test_figure_view_order_static_before_bgp_ospf():
    assert [t["view"] for t in build_tabs(_routing(static=True, bgp=True, ospf=True))] == \
        ["physical", "static", "bgp", "ospf", "addr", "ifs", "checks"]


# --- SUBNETS(usage) 廃止 ---------------------------------------------------

def test_usage_tab_removed():
    """usage(SUBNETS) タブはどの routing/フラグでも存在しないこと。"""
    for routing in [_routing(), _routing(bgp=True), _routing(ospf=True), _routing(static=True)]:
        for has_diff in (False, True):
            for has_config in (False, True):
                views = [t["view"] for t in build_tabs(routing, has_diff=has_diff, has_config=has_config)]
                assert "usage" not in views


def test_no_subnets_label():
    """_LABELS に SUBNETS / usage が無いこと。"""
    from lib.rendering.tabs import _LABELS
    assert "usage" not in _LABELS
    assert "SUBNETS" not in _LABELS.values()


# --- CONFIG / DIFF / CHECKS 配置 ------------------------------------------

def test_config_tab_absent_by_default():
    assert "config" not in [t["view"] for t in build_tabs(_routing())]


def test_config_tab_present_when_has_config():
    views = [t["view"] for t in build_tabs(_routing(), has_config=True)]
    assert views == ["physical", "addr", "ifs", "config", "checks"]


def test_config_label():
    tabs = build_tabs(_routing(), has_config=True)
    assert next(t for t in tabs if t["view"] == "config")["label"] == "CONFIG"


def test_diff_tab_absent_by_default():
    assert "diff" not in [t["view"] for t in build_tabs(_routing())]


def test_diff_present_when_has_diff():
    views = [t["view"] for t in build_tabs(_routing(), has_diff=True)]
    assert views == ["physical", "addr", "ifs", "diff", "checks"]


def test_config_then_diff_then_checks_order():
    """CONFIG → DIFF → CHECKS の順（ADDRESSES/INTERFACES の後）。"""
    views = [t["view"] for t in build_tabs(_routing(bgp=True, ospf=True), has_diff=True, has_config=True)]
    assert views == ["physical", "bgp", "ospf", "addr", "ifs", "config", "diff", "checks"]


def test_checks_is_last_table_view():
    """CHECKS は表ビュー末尾。"""
    for kw in [{}, {"has_config": True}, {"has_diff": True}, {"has_config": True, "has_diff": True}]:
        views = [t["view"] for t in build_tabs(_routing(bgp=True), **kw)]
        assert views[-1] == "checks"


def test_addresses_is_first_table_view():
    """ADDRESSES が表ビュー先頭（図ビューの直後）。"""
    views = [t["view"] for t in build_tabs(_routing(bgp=True, ospf=True))]
    table = [v for v in views if v not in ("physical", "bgp", "ospf")]
    assert table[0] == "addr"


# --- キー連番・ラベル -----------------------------------------------------

def test_key_numbers_sequential():
    for kw in [{}, {"has_config": True}, {"has_diff": True},
               {"has_config": True, "has_diff": True}]:
        tabs = build_tabs(_routing(bgp=True), **kw)
        assert [t["key"] for t in tabs] == list(range(1, len(tabs) + 1))


def test_labels():
    tabs = build_tabs(_routing(bgp=True, ospf=True), has_diff=True, has_config=True)
    labels = {t["view"]: t["label"] for t in tabs}
    assert labels == {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
                      "addr": "ADDRESSES", "ifs": "INTERFACES",
                      "config": "CONFIG", "diff": "DIFF", "checks": "CHECKS"}


def test_no_stats_tab():
    for routing in [_routing(), _routing(bgp=True)]:
        assert "stats" not in [t["view"] for t in build_tabs(routing, has_diff=True, has_config=True)]
