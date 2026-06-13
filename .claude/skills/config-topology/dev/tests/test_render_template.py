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


# ---------------------------------------------------------------------------
# D3b DIFF ビュー — template テスト
# ---------------------------------------------------------------------------

def _minimal_topo():
    return {"meta": {"generated_from": ["x.cfg"]},
            "devices": [{"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": None,
                         "ospf_router_id": None, "bgp_router_id": None, "sections": []}],
            "interfaces": [], "links": [], "segments": [],
            "routing": {"bgp": [], "ospf": [], "static": []}}


def _minimal_diff():
    """diff_topology が返す形式の最小差分 dict（devices に 1 件 added）。"""
    return {
        "devices": {"added": [{"id": "r2", "hostname": "R2", "vendor": "cisco_ios",
                                "as": None, "ospf_router_id": None, "bgp_router_id": None}],
                    "removed": [], "changed": []},
        "interfaces": {"added": [], "removed": [], "changed": []},
        "links": {"added": [], "removed": [], "changed": []},
        "segments": {"added": [], "removed": [], "changed": []},
        "routing_bgp": {"added": [], "removed": [], "changed": []},
        "routing_ospf": {"added": [], "removed": [], "changed": []},
        "routing_static": {"added": [], "removed": [], "changed": []},
    }


def test_render_html_without_diff_has_const_diff_null():
    """render_html(topo) — diff 引数なし — は const DIFF=null; を含むこと。"""
    html = render_html(_minimal_topo())
    assert "const DIFF=null;" in html


def test_render_html_without_diff_no_diff_tab():
    """render_html(topo) — diff 引数なし — は data-view="diff" タブを含まないこと。"""
    html = render_html(_minimal_topo())
    assert 'data-view="diff"' not in html


def test_render_html_with_diff_has_const_diff():
    """render_html(topo, diff=<dict>) は const DIFF=...;（null でない）を含むこと。"""
    html = render_html(_minimal_topo(), diff=_minimal_diff())
    assert "const DIFF=" in html
    assert "const DIFF=null;" not in html


def test_render_html_with_diff_has_diff_tab():
    """render_html(topo, diff=<dict>) は data-view="diff" タブを含むこと。"""
    html = render_html(_minimal_topo(), diff=_minimal_diff())
    assert 'data-view="diff"' in html


def test_render_html_with_diff_diff_script_correct_json():
    """render_html(topo, diff=<dict>) の const DIFF が JSON デコードできること。"""
    diff = _minimal_diff()
    html = render_html(_minimal_topo(), diff=diff)
    m = re.search(r"const DIFF=(.*?);</script>", html, re.DOTALL)
    assert m, "const DIFF=...;</script> が見つからない"
    parsed = json.loads(m.group(1).replace("<\\/", "</"))
    assert "devices" in parsed
    assert len(parsed["devices"]["added"]) == 1


def test_render_html_with_diff_deterministic():
    """render_html(topo, diff=<dict>) が2回バイト一致すること（決定性）。"""
    topo = _minimal_topo()
    diff = _minimal_diff()
    assert render_html(topo, diff=diff) == render_html(topo, diff=diff)


def test_render_html_without_diff_deterministic():
    """render_html(topo) — diff なし — が2回バイト一致すること（回帰）。"""
    topo = _minimal_topo()
    assert render_html(topo) == render_html(topo)


def test_render_html_golden_without_diff_unaffected():
    """golden トポロジーへの render_html(topo) が diff タブを含まないこと（回帰）。"""
    html = render_html(load_topology(str(GOLDEN)))
    assert 'data-view="diff"' not in html
    assert "const DIFF=null;" in html


# ---------------------------------------------------------------------------
# 修正 6: </script> 埋め込みテスト（XSS セキュリティ）
# ---------------------------------------------------------------------------

def test_render_html_script_tag_in_diff_escaped():
    """id/hostname に </script> を含む diff dict で render_html した HTML に
    生の </script>（DIFF コンテンツ内）が現れず <\\/script> にエスケープされること。

    JSON 埋め込み時の _json() が </script> → <\\/script> に変換し、
    script ブロックの早期終了を防ぐことを検証する。
    """
    xss_hostname = "</script><script>alert('xss')</script>"
    diff = {
        "devices": {
            "added": [{"id": "r_xss", "hostname": xss_hostname,
                        "vendor": "cisco_ios", "as": None}],
            "removed": [], "changed": [],
        },
        "interfaces": {"added": [], "removed": [], "changed": []},
        "links": {"added": [], "removed": [], "changed": []},
        "segments": {"added": [], "removed": [], "changed": []},
        "routing_bgp": {"added": [], "removed": [], "changed": []},
        "routing_ospf": {"added": [], "removed": [], "changed": []},
        "routing_static": {"added": [], "removed": [], "changed": []},
    }
    html = render_html(_minimal_topo(), diff=diff)
    # DIFF JSON 内の </script> が <\/script> にエスケープされていること
    # _json() の .replace("</", "<\\/") によって変換される
    assert "</script><script>alert" not in html, (
        "生の </script> が DIFF JSON 内に現れた（script ブロック早期終了リスク）"
    )
    # エスケープされた形式が存在すること
    assert "<\\/script>" in html or "&lt;/script&gt;" in html, (
        "</script> のエスケープが存在しない"
    )
