"""§8.2 タブ生成（図ビュー動的・表ビュー常設・static 除外・キー連番）のテスト。"""
import pytest

from lib.rendering.tabs import build_tabs

pytestmark = pytest.mark.unit


def _routing(bgp=False, ospf=False, static=False):
    return {"bgp": [1] if bgp else [], "ospf": [1] if ospf else [],
            "static": [1] if static else []}


def test_physical_and_tables_always():
    # 改修⑥ STATS 削除後: ["physical", "checks", "addr", "ifs", "usage"]
    tabs = build_tabs(_routing())
    assert [t["view"] for t in tabs] == ["physical", "checks", "addr", "ifs", "usage"]


def test_bgp_ospf_conditional():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    assert [t["view"] for t in tabs] == ["physical", "bgp", "ospf", "checks", "addr", "ifs", "usage"]


def test_only_bgp():
    assert [t["view"] for t in build_tabs(_routing(bgp=True))] == \
        ["physical", "bgp", "checks", "addr", "ifs", "usage"]


def test_static_never_a_tab():
    assert "static" not in [t["view"] for t in build_tabs(_routing(static=True))]


def test_key_numbers_sequential():
    tabs = build_tabs(_routing(bgp=True))
    # 改修⑥ STATS 削除後: physical, bgp, checks, addr, ifs, usage の 6 タブ
    assert [t["key"] for t in tabs] == [1, 2, 3, 4, 5, 6]
    no_bgp = build_tabs(_routing())
    # physical, checks, addr, ifs, usage の 5 タブ
    assert next(t["key"] for t in no_bgp if t["view"] == "checks") == 2
    assert next(t["key"] for t in no_bgp if t["view"] == "addr") == 3
    assert next(t["key"] for t in tabs if t["view"] == "addr") == 4


def test_labels():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    labels = {t["view"]: t["label"] for t in tabs}
    # 改修⑥ STATS 削除後: stats を除く全タブ
    assert labels == {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
                      "checks": "CHECKS",
                      "addr": "ADDRESSES", "ifs": "INTERFACES",
                      "usage": "SUBNETS"}


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


def test_checks_tab_is_first_table_view():
    """checks が表ビュー先頭（physical の直後）に配置されること。"""
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    assert views == ["physical", "checks", "addr", "ifs", "usage"]


def test_tabs_order_with_all_routing():
    """全 routing あり: physical→bgp→ospf→checks→addr→ifs→usage の順であること（改修⑥後）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True, static=True))
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "checks", "addr", "ifs", "usage"]


def test_tabs_order_no_routing():
    """routing なし: physical→checks→addr→ifs→usage の順であること（改修⑥後）。"""
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    assert views == ["physical", "checks", "addr", "ifs", "usage"]


def test_key_numbers_sequential_with_checks():
    """改修⑥後もキー番号が連番であること。"""
    tabs = build_tabs(_routing())
    # 改修⑥: physical=1, checks=2, addr=3, ifs=4, usage=5
    assert [t["key"] for t in tabs] == [1, 2, 3, 4, 5]

    tabs_bgp = build_tabs(_routing(bgp=True))
    # 改修⑥: physical=1, bgp=2, checks=3, addr=4, ifs=5, usage=6
    assert [t["key"] for t in tabs_bgp] == [1, 2, 3, 4, 5, 6]


# ---------------------------------------------------------------------------
# D3b DIFF ビュー — タブ生成テスト
# ---------------------------------------------------------------------------

def test_diff_tab_absent_by_default():
    """has_diff=False（既定）のとき diff タブが出ないこと。"""
    tabs = build_tabs(_routing())
    assert "diff" not in [t["view"] for t in tabs]


def test_diff_tab_present_when_has_diff():
    """has_diff=True のとき diff タブが出ること。"""
    tabs = build_tabs(_routing(), has_diff=True)
    assert "diff" in [t["view"] for t in tabs]


def test_diff_tab_label():
    """diff タブのラベルが 'DIFF' であること。"""
    tabs = build_tabs(_routing(), has_diff=True)
    diff_tab = next(t for t in tabs if t["view"] == "diff")
    assert diff_tab["label"] == "DIFF"


def test_diff_tab_before_checks():
    """改修⑥後: diff タブは checks タブより前に配置されること（stats が削除されたため）。"""
    tabs = build_tabs(_routing(), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views.index("diff") < views.index("checks")


def test_diff_tab_sequential_keys_with_diff():
    """diff タブ追加後もキー番号が連番であること。"""
    tabs = build_tabs(_routing(), has_diff=True)
    assert [t["key"] for t in tabs] == list(range(1, len(tabs) + 1))


def test_diff_tab_no_duplicate_view():
    """has_diff=True でも diff タブが1つだけ出ること。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True), has_diff=True)
    diff_views = [t for t in tabs if t["view"] == "diff"]
    assert len(diff_views) == 1


def test_diff_order_with_all_routing():
    """全 routing + has_diff=True: physical→bgp→ospf→diff→checks→addr→ifs→usage の順（改修⑥後）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "diff", "checks", "addr", "ifs", "usage"]


def test_diff_order_no_routing():
    """routing なし + has_diff=True: physical→diff→checks→addr→ifs→usage の順（改修⑥後）。"""
    tabs = build_tabs(_routing(), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views == ["physical", "diff", "checks", "addr", "ifs", "usage"]


def test_existing_tabs_unaffected_without_diff():
    """has_diff 未指定（省略）での呼び出しが期待順序を維持すること（改修⑥回帰）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "checks", "addr", "ifs", "usage"]


# ---------------------------------------------------------------------------
# D4: サブネット使用率集約ビュー — SUBNETS タブ テスト
# ---------------------------------------------------------------------------

def test_usage_tab_always_present():
    """usage タブは routing 有無に関係なく常設されること。"""
    for routing in [_routing(), _routing(bgp=True), _routing(ospf=True), _routing(static=True)]:
        views = [t["view"] for t in build_tabs(routing)]
        assert "usage" in views, "usage タブが見つからない: %s" % views


def test_usage_tab_label():
    """usage タブのラベルが 'SUBNETS' であること。"""
    tabs = build_tabs(_routing())
    usage_tab = next(t for t in tabs if t["view"] == "usage")
    assert usage_tab["label"] == "SUBNETS"


def test_usage_tab_after_ifs():
    """usage タブが ifs タブの直後に配置されること。"""
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    assert views.index("usage") == views.index("ifs") + 1


def test_tabs_order_no_routing_with_usage():
    """routing なし・usage 含む全タブ順の確認（改修⑥後）。

    改修⑥ STATS 削除後の全タブ順: physical→checks→addr→ifs→usage。
    """
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    assert views == ["physical", "checks", "addr", "ifs", "usage"]


def test_tabs_order_all_routing_with_usage():
    """全 routing あり: physical→bgp→ospf→checks→addr→ifs→usage の順であること（改修⑥後）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True, static=True))
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "checks", "addr", "ifs", "usage"]


def test_tabs_order_with_diff_and_usage():
    """has_diff=True: physical→diff→checks→addr→ifs→usage の順であること（改修⑥後）。"""
    tabs = build_tabs(_routing(), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views == ["physical", "diff", "checks", "addr", "ifs", "usage"]


def test_key_numbers_sequential_with_usage():
    """usage タブ含む全タブのキー番号が連番であること（改修⑥後）。"""
    tabs = build_tabs(_routing())
    # 改修⑥: physical=1, checks=2, addr=3, ifs=4, usage=5
    assert [t["key"] for t in tabs] == list(range(1, len(tabs) + 1))

    tabs_bgp = build_tabs(_routing(bgp=True))
    # 改修⑥: physical=1, bgp=2, checks=3, addr=4, ifs=5, usage=6
    assert [t["key"] for t in tabs_bgp] == list(range(1, len(tabs_bgp) + 1))


def test_usage_tab_one_only():
    """usage タブが 1 つだけ出ること（重複なし）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True), has_diff=True)
    usage_views = [t for t in tabs if t["view"] == "usage"]
    assert len(usage_views) == 1


# ---------------------------------------------------------------------------
# 改修⑥ STATS タブ削除
# ---------------------------------------------------------------------------

def test_tabs_no_stats():
    """build_tabs の返り値に view=="stats" が含まれないこと。"""
    for routing in [_routing(), _routing(bgp=True), _routing(ospf=True), _routing(static=True)]:
        views = [t["view"] for t in build_tabs(routing)]
        assert "stats" not in views, "stats タブが残っている: %s" % views


def test_tabs_no_stats_with_diff():
    """has_diff=True のときも stats タブが含まれないこと。"""
    views = [t["view"] for t in build_tabs(_routing(), has_diff=True)]
    assert "stats" not in views


def test_checks_is_first_table_view():
    """stats 削除後、checks が表ビュー先頭（physical 系の直後）であること。"""
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    # physical の次が checks
    assert views == ["physical", "checks", "addr", "ifs", "usage"]


def test_checks_is_first_table_view_with_bgp_ospf():
    """routing あり: physical→bgp→ospf→checks→addr→ifs→usage の順であること。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "checks", "addr", "ifs", "usage"]


def test_diff_before_checks_after_stats_removal():
    """has_diff=True: diff タブが checks タブより前に配置されること（stats 削除後）。"""
    tabs = build_tabs(_routing(), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views == ["physical", "diff", "checks", "addr", "ifs", "usage"]
