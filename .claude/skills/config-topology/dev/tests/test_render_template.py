"""HTML 組立・埋め込み DATA 一致・自己完結・条件タブ・IF チップ/●不在の構造テスト（§8.1/§8.2/§8.4.1）。"""
import json
import re
from pathlib import Path

import pytest

from lib.topology_io import load_topology
from lib.rendering.template import render_html

pytestmark = pytest.mark.integration

GOLDEN = Path(__file__).resolve().parents[1] / "examples" / "topology"


def _html():
    return render_html(load_topology(str(GOLDEN)))


def _embedded(html, name):
    m = re.search(r"const %s\s*=\s*(.*?);</script>" % name, html, re.DOTALL)
    assert m, "埋め込み %s が見つからない" % name
    return m.group(1)


def test_self_contained_no_external():
    html = _html()
    assert "http://" not in html and "https://" not in html
    assert "<script src" not in html.lower()
    assert "<link rel=\"stylesheet\"" not in html.lower() and "<link rel='stylesheet'" not in html.lower()


def test_doctype_and_inline_assets():
    html = _html()
    assert html.lstrip().lower().startswith("<!doctype html")
    assert "<style>" in html and "<script>" in html


def test_embedded_data_matches_topology():
    html = _html()
    data = json.loads(_embedded(html, "DATA"))
    assert set(data["devices"]) == {"r1", "r2"}
    assert len(data["links"]) == 1
    assert data["meta"]["generated_from"] == ["sample-ios-r1.cfg", "sample-junos-r2.conf"]


def test_pos_and_views_embedded():
    html = _html()
    pos = json.loads(_embedded(html, "POS"))
    assert "r1" in pos and "r2" in pos
    views = json.loads(_embedded(html, "VIEWS"))
    assert views[0] == "physical" and "addr" in views and "ifs" in views


def test_tab_rules_golden_has_bgp_ospf():
    html = _html()      # golden has routing.bgp and routing.ospf
    assert 'data-view="physical"' in html
    assert 'data-view="addr"' in html and 'data-view="ifs"' in html
    assert 'data-view="bgp"' in html and 'data-view="ospf"' in html
    assert 'data-view="checks"' in html    # D2: checks タブは常設
    assert 'data-view="static"' not in html


def test_tabs_conditional_no_bgp(tmp_path):
    # bgp/ospf を持たないトポロジー → bgp/ospf タブが出ない（_BODY のハードコード nav が差し替わっている証拠）
    from lib.rendering.template import render_html as rh
    topo = {"meta": {"generated_from": ["x.cfg"]},
            "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None,
                         "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
            "interfaces": [], "links": [], "segments": [],
            "routing": {"bgp": [], "ospf": [], "static": []}}
    html = rh(topo)
    assert 'data-view="physical"' in html
    assert 'data-view="addr"' in html and 'data-view="ifs"' in html
    assert 'data-view="checks"' in html    # D2: checks タブは常設
    assert 'data-view="bgp"' not in html      # bgp 無し → タブ無し
    assert 'data-view="ospf"' not in html


def test_no_if_chip_or_select_marker():
    html = _html()
    assert "selglyph" not in html
    assert "if-chip" not in html and "ifchip" not in html


def test_deterministic_same_input():
    assert _html() == _html()


# ---------------------------------------------------------------------------
# D1 統計ダッシュボード — HTML 組み込み確認
# ---------------------------------------------------------------------------

def test_stats_tab_in_html():
    """生成 HTML に stats タブが含まれること。"""
    html = _html()
    assert 'data-view="stats"' in html


def test_stats_view_in_views_array():
    """埋め込み VIEWS 配列に 'stats' が含まれること。"""
    html = _html()
    views = json.loads(_embedded(html, "VIEWS"))
    assert "stats" in views


def test_data_stats_embedded_in_html():
    """埋め込み DATA に 'stats' キーが含まれ、dict であること。"""
    html = _html()
    data = json.loads(_embedded(html, "DATA"))
    assert "stats" in data
    assert isinstance(data["stats"], dict)
    # 必須カウントキーの存在確認
    for k in ("devices", "interfaces", "links", "segments",
              "bgp_sessions", "ospf_networks", "static_routes", "dualstack_ifs"):
        assert k in data["stats"], f"data['stats'] に '{k}' が無い"


def test_render_stats_view_js_function():
    """JS に renderStatsView 関数が含まれること。"""
    from lib.rendering.assets import _JS
    assert "renderStatsView" in _JS


def test_is_table_view_includes_stats():
    """isTableView() が stats を table view として扱うこと（JS コード確認）。"""
    from lib.rendering.assets import _JS
    assert 'S.view === "stats"' in _JS


# ---------------------------------------------------------------------------
# D2 設計検証パネル — HTML 組み込み確認
# ---------------------------------------------------------------------------

def test_checks_tab_in_html():
    """生成 HTML に checks タブが含まれること。"""
    html = _html()
    assert 'data-view="checks"' in html


def test_checks_view_in_views_array():
    """埋め込み VIEWS 配列に 'checks' が含まれること。"""
    html = _html()
    views = json.loads(_embedded(html, "VIEWS"))
    assert "checks" in views


def test_data_checks_embedded_in_html():
    """埋め込み DATA に 'checks' キーが含まれること。"""
    html = _html()
    data = json.loads(_embedded(html, "DATA"))
    assert "checks" in data
    assert isinstance(data["checks"], list)


def test_render_html_deterministic_with_checks():
    """render_html を2回呼んでバイト一致すること（決定性・checks 追加後も維持）。"""
    topo = load_topology(str(GOLDEN))
    a = render_html(topo)
    b = render_html(topo)
    assert a == b
