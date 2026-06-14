"""§8.2 タブ生成（図ビュー動的・表ビュー常設・static 除外・キー連番）のテスト。"""
import pytest

from lib.rendering.tabs import build_tabs

pytestmark = pytest.mark.unit


def _routing(bgp=False, ospf=False, static=False):
    return {"bgp": [1] if bgp else [], "ospf": [1] if ospf else [],
            "static": [1] if static else []}


def test_physical_and_tables_always():
    # D4 SUBNETS 追加後: ["physical", "stats", "checks", "addr", "ifs", "usage"]
    tabs = build_tabs(_routing())
    assert [t["view"] for t in tabs] == ["physical", "stats", "checks", "addr", "ifs", "usage"]


def test_bgp_ospf_conditional():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    assert [t["view"] for t in tabs] == ["physical", "bgp", "ospf", "stats", "checks", "addr", "ifs", "usage"]


def test_only_bgp():
    assert [t["view"] for t in build_tabs(_routing(bgp=True))] == \
        ["physical", "bgp", "stats", "checks", "addr", "ifs", "usage"]


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
    # D4 SUBNETS 追加後: physical, bgp, stats, checks, addr, ifs, usage の 7 タブ
    assert [t["key"] for t in tabs] == [1, 2, 3, 4, 5, 6, 7]
    no_bgp = build_tabs(_routing())
    # physical, stats, checks, addr, ifs, usage の 6 タブ
    assert next(t["key"] for t in no_bgp if t["view"] == "stats") == 2
    assert next(t["key"] for t in no_bgp if t["view"] == "checks") == 3
    assert next(t["key"] for t in no_bgp if t["view"] == "addr") == 4
    assert next(t["key"] for t in tabs if t["view"] == "addr") == 5


def test_labels():
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    labels = {t["view"]: t["label"] for t in tabs}
    # D4 SUBNETS 追加後: usage タブのラベルも含む
    assert labels == {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
                      "stats": "STATS", "checks": "CHECKS",
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


def test_checks_tab_after_stats():
    """checks タブが stats タブの直後に配置されること。"""
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    assert views.index("checks") == views.index("stats") + 1


def test_tabs_order_with_all_routing():
    """全 routing あり: physical→bgp→ospf→stats→checks→addr→ifs→usage の順であること（D4 追加後）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True, static=True))
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "stats", "checks", "addr", "ifs", "usage"]


def test_tabs_order_no_routing():
    """routing なし: physical→stats→checks→addr→ifs→usage の順であること（D4 追加後）。"""
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    assert views == ["physical", "stats", "checks", "addr", "ifs", "usage"]


def test_key_numbers_sequential_with_checks():
    """checks 追加後もキー番号が連番であること（D4 SUBNETS 追加後更新）。"""
    tabs = build_tabs(_routing())
    # D4: physical=1, stats=2, checks=3, addr=4, ifs=5, usage=6
    assert [t["key"] for t in tabs] == [1, 2, 3, 4, 5, 6]

    tabs_bgp = build_tabs(_routing(bgp=True))
    # D4: physical=1, bgp=2, stats=3, checks=4, addr=5, ifs=6, usage=7
    assert [t["key"] for t in tabs_bgp] == [1, 2, 3, 4, 5, 6, 7]


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


def test_diff_tab_before_stats():
    """diff タブは stats タブより前に配置されること。"""
    tabs = build_tabs(_routing(), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views.index("diff") < views.index("stats")


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
    """全 routing + has_diff=True: physical→bgp→ospf→diff→stats→checks→addr→ifs→usage の順（D4 追加後）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "diff", "stats", "checks", "addr", "ifs", "usage"]


def test_diff_order_no_routing():
    """routing なし + has_diff=True: physical→diff→stats→checks→addr→ifs→usage の順（D4 追加後）。"""
    tabs = build_tabs(_routing(), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views == ["physical", "diff", "stats", "checks", "addr", "ifs", "usage"]


def test_existing_tabs_unaffected_without_diff():
    """has_diff 未指定（省略）での呼び出しが期待順序を維持すること（D4 追加後回帰）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True))
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "stats", "checks", "addr", "ifs", "usage"]


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
    """routing なし・usage 含む全タブ順の確認。test_tabs_order_no_routing と同等（重複整理済み）。

    D4 追加後の全タブ順: physical→stats→checks→addr→ifs→usage。
    test_tabs_order_no_routing が同一アサーションを持つためここでは明示的に同一性を記録する。
    """
    tabs = build_tabs(_routing())
    views = [t["view"] for t in tabs]
    # test_tabs_order_no_routing と同一の期待値（重複だが D4 確認の文書化として残す）
    assert views == ["physical", "stats", "checks", "addr", "ifs", "usage"]


def test_tabs_order_all_routing_with_usage():
    """全 routing あり: physical→bgp→ospf→stats→checks→addr→ifs→usage の順であること。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True, static=True))
    views = [t["view"] for t in tabs]
    assert views == ["physical", "bgp", "ospf", "stats", "checks", "addr", "ifs", "usage"]


def test_tabs_order_with_diff_and_usage():
    """has_diff=True: physical→diff→stats→checks→addr→ifs→usage の順であること。"""
    tabs = build_tabs(_routing(), has_diff=True)
    views = [t["view"] for t in tabs]
    assert views == ["physical", "diff", "stats", "checks", "addr", "ifs", "usage"]


def test_key_numbers_sequential_with_usage():
    """usage タブ追加後もキー番号が連番であること。"""
    tabs = build_tabs(_routing())
    # physical=1, stats=2, checks=3, addr=4, ifs=5, usage=6
    assert [t["key"] for t in tabs] == list(range(1, len(tabs) + 1))

    tabs_bgp = build_tabs(_routing(bgp=True))
    # physical=1, bgp=2, stats=3, checks=4, addr=5, ifs=6, usage=7
    assert [t["key"] for t in tabs_bgp] == list(range(1, len(tabs_bgp) + 1))


def test_usage_tab_one_only():
    """usage タブが 1 つだけ出ること（重複なし）。"""
    tabs = build_tabs(_routing(bgp=True, ospf=True), has_diff=True)
    usage_views = [t for t in tabs if t["view"] == "usage"]
    assert len(usage_views) == 1
