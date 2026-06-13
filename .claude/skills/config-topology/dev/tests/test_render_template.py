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
    assert 'data-view="bgp"' not in html      # bgp 無し → タブ無し
    assert 'data-view="ospf"' not in html


def test_no_if_chip_or_select_marker():
    html = _html()
    assert "selglyph" not in html
    assert "if-chip" not in html and "ifchip" not in html


def test_deterministic_same_input():
    assert _html() == _html()
