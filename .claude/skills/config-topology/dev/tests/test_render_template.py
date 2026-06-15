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
    assert 'data-view="static"' in html    # golden は routing.static あり → STATIC 図ビュー出現


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
# 改修⑥ STATS タブ削除 — HTML 組み込み確認
# ---------------------------------------------------------------------------

def test_stats_tab_not_in_html():
    """改修⑥後: 生成 HTML に stats タブが含まれないこと。"""
    html = _html()
    assert 'data-view="stats"' not in html


def test_stats_not_in_views_array():
    """改修⑥後: 埋め込み VIEWS 配列に 'stats' が含まれないこと。"""
    html = _html()
    views = json.loads(_embedded(html, "VIEWS"))
    assert "stats" not in views


def test_data_stats_not_embedded_in_html():
    """改修⑥後: 埋め込み DATA に 'stats' キーが含まれないこと。"""
    html = _html()
    data = json.loads(_embedded(html, "DATA"))
    assert "stats" not in data


def test_table_view_order_in_html():
    """改修後: 表ビュー順は addr→ifs→[config]→[diff]→checks（先頭=addr・末尾=checks・usage 無し）。"""
    html = _html()
    views = json.loads(_embedded(html, "VIEWS"))
    assert "usage" not in views
    table_views = [v for v in views if v not in ("physical", "static", "bgp", "ospf")]
    assert table_views[0] == "addr", "addr が表ビュー先頭でない: %s" % table_views
    assert table_views[-1] == "checks", "checks が表ビュー末尾でない: %s" % table_views


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

# ---------------------------------------------------------------------------
# A3: render_html layout パラメータ（CLI / template テスト）
# ---------------------------------------------------------------------------

def test_render_html_layout_param_default_force():
    """render_html(topo) と render_html(topo, layout='force') が完全一致すること（デフォルト=force）。"""
    topo = load_topology(str(GOLDEN))
    html_default = render_html(topo)
    html_force = render_html(topo, layout="force")
    assert html_default == html_force, (
        "render_html のデフォルト layout が force でない（byte 不一致）"
    )


def test_render_html_layout_hierarchical_differs_from_force():
    """render_html(topo, layout='hierarchical') の POS が force と異なること。

    golden（r1,r2 の 2 ノード）で hierarchical の POS が force の POS と異なることを確認する。
    """
    topo = load_topology(str(GOLDEN))
    import re
    import json

    def _get_pos(html):
        m = re.search(r"const POS\s*=\s*(.*?);</script>", html, re.DOTALL)
        assert m, "const POS が見つからない"
        return json.loads(m.group(1))

    html_force = render_html(topo, layout="force")
    html_hier = render_html(topo, layout="hierarchical")
    # POS が異なること（hierarchical は格子状、force は force-directed で必ず異なる）
    pos_force = _get_pos(html_force)
    pos_hier = _get_pos(html_hier)
    assert pos_force != pos_hier, (
        "hierarchical mode の POS が force と同一（モード分岐が機能していない）"
    )


def test_render_html_layout_force_golden_byte_unchanged():
    """render_html(topo) — layout 省略 — が従来と byte 一致（golden 不変の担保）。

    layout 引数を追加しても既存の force-directed POS が変わらないことを確認する。
    2回呼んで一致、かつ layout='force' 明示と一致。
    """
    topo = load_topology(str(GOLDEN))
    html1 = render_html(topo)
    html2 = render_html(topo)
    html_force = render_html(topo, layout="force")
    assert html1 == html2, "render_html が決定的でない"
    assert html1 == html_force, (
        "render_html(topo) と render_html(topo, layout='force') が byte 不一致"
    )


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


# ---------------------------------------------------------------------------
# CONFIG ビュー — template / DATA 埋め込み
# ---------------------------------------------------------------------------

def _topo_with_raw():
    topo = _minimal_topo()
    topo["raw_configs"] = {"r1": "hostname R1\n!\ninterface Gi0/0\n"}
    return topo


def test_config_tab_absent_without_raw():
    """raw_configs が無いトポロジーでは config タブが出ないこと（既定・後方互換）。"""
    html = render_html(_minimal_topo())
    assert 'data-view="config"' not in html


def test_config_tab_present_with_raw():
    """raw_configs を持つトポロジーでは config タブが出ること。"""
    html = render_html(_topo_with_raw())
    assert 'data-view="config"' in html


def test_data_raw_configs_embedded_with_raw():
    """raw_configs が埋め込み DATA.raw_configs に入ること。"""
    html = render_html(_topo_with_raw())
    data = json.loads(_embedded(html, "DATA"))
    assert data["raw_configs"]["r1"].startswith("hostname R1")


def test_config_view_in_views_array_with_raw():
    """埋め込み VIEWS 配列に 'config' が含まれ、ifs の後・checks の前に配置されること（raw あり時）。"""
    html = render_html(_topo_with_raw())
    views = json.loads(_embedded(html, "VIEWS"))
    assert "config" in views
    assert views.index("ifs") < views.index("config") < views.index("checks")


def test_render_html_deterministic_with_raw():
    """raw_configs ありでも render_html が2回バイト一致すること（決定性）。"""
    topo = _topo_with_raw()
    assert render_html(topo) == render_html(topo)


def test_golden_has_config_tab():
    """golden（再生成後 raw_config.yaml を持つ）に config タブが出ること。"""
    html = render_html(load_topology(str(GOLDEN)))
    assert 'data-view="config"' in html


def test_raw_config_script_tag_escaped():
    """raw_configs に </script> を含む生 config を埋め込んでも script ブロックが
    早期終了しないこと（_json の </ → <\\/ エスケープが DATA.raw_configs にも効く）。"""
    topo = _minimal_topo()
    topo["raw_configs"] = {"r1": "banner motd </script><script>alert(1)</script>\n"}
    html = render_html(topo)
    assert "</script><script>alert(1)" not in html
    assert "<\\/script>" in html


# ---------------------------------------------------------------------------
# CONFIG ワークベンチ Phase B — raw_configs_prev 配線
# ---------------------------------------------------------------------------

def test_raw_configs_prev_embedded_when_passed():
    topo = _topo_with_raw()
    html = render_html(topo, prev_raw_configs={"r1": "hostname R1-old\n"})
    data = json.loads(_embedded(html, "DATA"))
    assert data["raw_configs_prev"]["r1"].startswith("hostname R1-old")


def test_raw_configs_prev_empty_by_default():
    html = render_html(_topo_with_raw())
    data = json.loads(_embedded(html, "DATA"))
    assert data["raw_configs_prev"] == {}


# ---------------------------------------------------------------------------
# STATIC 図ビュー（フォワーディング・トレース）— HTML/DATA 組み込み確認
# ---------------------------------------------------------------------------

def test_static_view_and_trace_controls_in_html():
    """golden は routing.static あり → STATIC タブ・トレース UI・矢じり marker が HTML に含まれる。"""
    html = _html()
    assert 'data-view="static"' in html
    assert 'id="trace-src"' in html and 'id="trace-dst"' in html and 'id="trace-go"' in html
    assert 'id="se-arrow"' in html                 # 方向矢じり marker
    assert 'data-elem="sedge"' in html             # STATIC エッジ描画コード（render JS 内）


def test_static_data_keys_embedded():
    """埋め込み DATA に fib / static_edges / static_stubs キーが含まれ、static_edges が非空。"""
    html = _html()
    data = json.loads(_embedded(html, "DATA"))
    assert isinstance(data["fib"], dict) and data["fib"]
    assert isinstance(data["static_edges"], list) and len(data["static_edges"]) >= 1
    assert isinstance(data["static_stubs"], list)
    assert "static" in json.loads(_embedded(html, "VIEWS"))
