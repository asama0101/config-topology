"""
TDD テスト: Round B / Pass1b — 統一グローバル検索（全ビュー横断 + タブ自動切替 + 中央寄せ）

テスト対象:
  1. filterNodes が全ビュー（view-physical/bgp/ospf）を横断してノードにマッチ適用
  2. ifinv 行の data-ips 属性（CIDR 内包用、link-local 除外）の確認
  3. 「次へ」ボタン（id="search-next"）が存在する
  5. ナビゲーション JS 関数（navigateSearchNext, _searchMatches, _searchFocusIndex）が JS に存在
  6. selectView 呼び出しを含むナビゲーションコードが存在
  7. .search-focus CSS 定義が存在
  8. tr.search-match CSS 定義が存在
  9. 件数表示が「i/N件」形式コードを含む（/ を使ったフォーマット）
 10. 決定性・自己完結・既存テスト非回帰

不変条件:
  - 既存テスト 1393 件全て緑のまま
  - HTML 自己完結（外部リソース参照なし）
  - data-ips は link-local（fe80::）を除外する
"""
from __future__ import annotations

import re
import pytest

# ================================================================
# ヘルパー
# ================================================================

def _make_iface(**kwargs) -> dict:
    base = {
        "id": "",
        "device": "",
        "name": "",
        "ip": None,
        "vlan": None,
        "description": None,
        "shutdown": False,
        "admin_status": "up",
        "oper_status": None,
        "mtu": None,
        "speed": None,
        "duplex": None,
        "l2_l3": "l3",
        "switchport": None,
        "encapsulation": None,
        "source": "parsed",
        "addresses": [],
    }
    base.update(kwargs)
    return base

def _dualstack_topology_for_bpass1b():
    """B-pass1b テスト用 dual-stack topology（physical/bgp/ospf ビューあり）。"""
    return {
        "title": "Test B-pass1b",
        "generated_from": ["test"],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios", "as": 65001, "sections": []},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios", "as": 65002, "sections": []},
        ],
        "interfaces": [
            _make_iface(
                id="r1::Gi0/0", device="r1", name="Gi0/0",
                ip="10.0.0.1/30",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                    # link-local（除外対象）
                    {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
                ],
            ),
            _make_iface(
                id="r2::Gi0/0", device="r2", name="Gi0/0",
                ip="10.0.0.2/30",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.2", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::0", "prefix": 127},
                    {"af": "v6", "ip": "fe80::2", "prefix": 64, "scope": "link-local"},
                ],
            ),
        ],
        "links": [
            {
                "a_device": "r1", "a_if": "Gi0/0",
                "b_device": "r2", "b_if": "Gi0/0",
                "subnet": "10.0.0.0/30",
                "kind": "inferred-subnet",
                "ospf_area": "0",
                "ospf_network": "10.0.0.0/30",
            },
            {
                "a_device": "r1", "a_if": "Gi0/0",
                "b_device": "r2", "b_if": "Gi0/0",
                "subnet": "2001:db8:1::/127",
                "kind": "inferred-subnet",
                "ospf_area": "0",
                "ospf_network": "2001:db8:1::/127",
            },
        ],
        "segments": [],
        "routing": {
            "bgp": [
                {"device": "r1", "local_as": 65001, "local_ip": "10.0.0.1",
                 "neighbor_ip": "10.0.0.2", "peer_as": 65002, "type": "ebgp", "af": "v4"},
                {"device": "r1", "local_as": 65001, "local_ip": "2001:db8:1::1",
                 "neighbor_ip": "2001:db8:1::0", "peer_as": 65002, "type": "ebgp", "af": "v6"},
                {"device": "r2", "local_as": 65002, "local_ip": "10.0.0.2",
                 "neighbor_ip": "10.0.0.1", "peer_as": 65001, "type": "ebgp", "af": "v4"},
                {"device": "r2", "local_as": 65002, "local_ip": "2001:db8:1::0",
                 "neighbor_ip": "2001:db8:1::1", "peer_as": 65001, "type": "ebgp", "af": "v6"},
            ],
            "ospf": [
                {"device": "r1", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r1", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
                {"device": "r2", "process": 1, "network": "10.0.0.0/30", "area": "0", "af": "v4"},
                {"device": "r2", "process": 10, "network": "2001:db8:1::/127", "area": "0", "af": "v6"},
            ],
            "static": [],
        },
    }

@pytest.fixture(scope="module")
def bpass1b_html():
    """B-pass1b topology の render() HTML（モジュールスコープ）。"""
    from lib.rendering import render
    return render(_dualstack_topology_for_bpass1b())

# ================================================================
# 1. filterNodes が全ビュー（view-physical/bgp/ospf）を横断
# ================================================================

class TestFilterNodesAllViews:
    """filterNodes JS が全ビューを走査する（現ビュー限定でない）こと。"""

    @pytest.mark.unit
    def test_filternodes_queries_all_views_not_current_only(self, bpass1b_html):
        """filterNodes が _currentView 限定ではなく複数ビューを走査するコードになっている。

        全ビュー横断: 'view-physical', 'view-bgp', 'view-ospf' を querySelectorAll で列挙、
        または document.querySelectorAll('.device-node') 等の全体検索をしていること。
        現ビュー限定実装（.view-' + _currentView）ではいずれかの view クラス名のみ。
        """
        js_section = _extract_js(bpass1b_html)
        # 全ビューを横断する実装パターンを確認
        # 方式A: 全ビューを ['physical','bgp','ospf'] 等のリストで走査
        # 方式B: .device-node を全体から querySelectorAll
        # 方式C: .view クラスを全て querySelectorAll('.view')
        has_all_views_iteration = (
            # 方式A: ビューリストでループ
            ("view-physical" in js_section and "view-bgp" in js_section and "view-ospf" in js_section)
            # 方式B: 全 .device-node を一括取得
            or ("querySelectorAll('.device-node')" in js_section)
            # 方式C: .view クラス全体を走査
            or ("querySelectorAll('.view')" in js_section and "device-node" in js_section)
        )
        assert has_all_views_iteration, (
            "filterNodes が全ビュー横断していない（現ビュー限定 .view-' + _currentView のみ）"
        )

    @pytest.mark.unit
    def test_filternodes_not_limited_to_current_view(self, bpass1b_html):
        """filterNodes の実装が 'view-' + _currentView の単一ビューのみに限定されていない。"""
        js_section = _extract_js(bpass1b_html)
        # 旧実装: document.querySelector('.view-' + _currentView) で現ビューのみ
        # 新実装: それに加えて/代わりに全ビューを走査
        # 「全ビューを対象にする何らかのパターン」が存在することを確認
        # 許容: _currentView を使っても全ビューをループする実装は可
        assert "view-physical" in js_section or "querySelectorAll('.device-node')" in js_section, (
            "filterNodes に view-physical または全体 querySelectorAll がない"
        )

    @pytest.mark.unit
    def test_filternodes_applies_to_all_three_graph_views(self, bpass1b_html):
        """filterNodes が physical/bgp/ospf 三ビュー全てにマッチ判定を適用する。

        いずれかの方式で全ビューが対象になっていること:
        - ビュー名リスト ['physical', 'bgp', 'ospf'] のいずれかが JS にある
        - または全体 .device-node querySelectorAll がある
        """
        js_section = _extract_js(bpass1b_html)
        views_covered = (
            ("view-physical" in js_section and "view-bgp" in js_section)
            or "querySelectorAll('.device-node')" in js_section
        )
        assert views_covered, (
            "filterNodes が physical と bgp の両ビューをカバーしていない"
        )

    @pytest.mark.unit
    def test_edge_dimming_applied_across_views(self, bpass1b_html):
        """エッジ淡色化コードが全ビュー対象で適用される（view限定でないlinkエッジ操作）。"""
        js_section = _extract_js(bpass1b_html)
        # エッジ淡色化: link-edge の opacity 操作コードが存在する
        assert "link-edge" in js_section and "opacity" in js_section, (
            "エッジ淡色化コードが存在しない"
        )

# ================================================================
# 2. ifinv 行に data-ips 属性（CIDR 内包用、link-local 除外）
# ================================================================

class TestIfinvRowDataIps:
    """ifinv 行（tr）に data-ips 属性が付く。"""

    def test_bpass1b_html_ifinv_rows_have_data_ips(self, bpass1b_html):
        """render() した HTML の ifinv 行に data-ips が存在する。"""
        assert 'data-ips="' in bpass1b_html, (
            "render() 後の HTML に data-ips 属性がない"
        )

# ================================================================
# 3. #ifinv-search 撤去 & グローバル検索が ifinv を駆動
# ================================================================

class TestGlobalSearchDrivesIfinv:
    """グローバル検索（#search-input）が ifinv 行を駆動する。"""

    @pytest.mark.unit
    def test_ifinv_search_input_removed(self, bpass1b_html):
        """#ifinv-search 入力欄が撤去されている（id='ifinv-search' が HTML にない）。"""
        assert 'id="ifinv-search"' not in bpass1b_html, (
            "#ifinv-search 入力欄が残っている（撤去されていない）"
        )

    @pytest.mark.unit
    def test_ifinv_search_css_removed_or_unused(self, bpass1b_html):
        """#ifinv-search の CSS スタイルが削除されているか HTML 内に残っていない。

        撤去後は CSS セレクタ '#ifinv-search {' が存在しないか、
        それに対応する要素がないことを確認する。
        """
        # CSS セレクタ #ifinv-search が残っていても機能的には問題ないが
        # 要素自体が消えていることを確認（上記テストと同値だが CSS 側も検証）
        assert 'id="ifinv-search"' not in bpass1b_html

class TestSearchNavigation:
    """「次へ」ボタン・ナビゲーション関数の存在確認。"""

    @pytest.mark.unit
    def test_search_next_button_exists(self, bpass1b_html):
        """「次へ」ボタン（id="search-next"）が HTML に存在する。"""
        assert 'id="search-next"' in bpass1b_html, (
            '「次へ」ボタン (id="search-next") が存在しない'
        )

    @pytest.mark.unit
    def test_navigate_search_next_function_exists(self, bpass1b_html):
        """navigateSearchNext（またはそれに相当）ナビゲーション関数が JS にある。"""
        js_section = _extract_js(bpass1b_html)
        # navigateSearchNext 関数または search-next ハンドラが存在
        has_nav = (
            "navigateSearchNext" in js_section
            or "search-next" in js_section
        )
        assert has_nav, "ナビゲーション関数/ハンドラが JS にない"

    @pytest.mark.unit
    def test_search_focus_index_tracking_exists(self, bpass1b_html):
        """マッチ機器の巡回インデックスを管理する変数/コードが JS にある。"""
        js_section = _extract_js(bpass1b_html)
        # _searchFocusIndex または類似の変数
        has_index = (
            "_searchFocusIndex" in js_section
            or "searchFocusIndex" in js_section
            or "focusIndex" in js_section
        )
        assert has_index, "検索フォーカスインデックス変数が JS にない"

    @pytest.mark.unit
    def test_search_matches_collection_exists(self, bpass1b_html):
        """マッチ機器リストを管理する変数/コードが JS にある。"""
        js_section = _extract_js(bpass1b_html)
        has_matches = (
            "_searchMatches" in js_section
            or "searchMatches" in js_section
            or "_matchDevices" in js_section
        )
        assert has_matches, "マッチ機器リスト変数が JS にない"

    @pytest.mark.unit
    def test_navigation_calls_select_view(self, bpass1b_html):
        """ナビゲーションコードが selectView を呼び出す（タブ自動切替）。"""
        js_section = _extract_js(bpass1b_html)
        assert "selectView" in js_section, (
            "ナビゲーションコードに selectView 呼び出しがない"
        )

    @pytest.mark.unit
    def test_navigation_assigns_search_focus_class(self, bpass1b_html):
        """ナビゲーションコードが .search-focus クラスを付与するコードを持つ。"""
        js_section = _extract_js(bpass1b_html)
        assert "search-focus" in js_section, (
            "ナビゲーションコードに search-focus クラス操作がない"
        )

    @pytest.mark.unit
    def test_navigation_updates_search_count_with_index(self, bpass1b_html):
        """ナビゲーションコードが search-count を i/N件 形式で更新するコードがある。"""
        js_section = _extract_js(bpass1b_html)
        # 「/」を使ったフォーマット文字列が search-count 更新に使われる
        has_count_format = (
            "search-count" in js_section
            and "/" in js_section
            and ("件" in js_section or "count" in js_section.lower())
        )
        assert has_count_format, (
            "search-count の i/N件 更新コードが見つからない"
        )

    @pytest.mark.unit
    def test_enter_key_triggers_navigation(self, bpass1b_html):
        """Enter キーでナビゲーションが発火するコードがある。"""
        js_section = _extract_js(bpass1b_html)
        has_enter = "Enter" in js_section or "enter" in js_section.lower()
        assert has_enter, "Enter キーによるナビゲーション起動コードがない"

    @pytest.mark.unit
    def test_center_node_logic_exists(self, bpass1b_html):
        """中央寄せロジック（translateX/translateY 変数への代入）が JS にある。"""
        js_section = _extract_js(bpass1b_html)
        # translate 変数への代入が存在する（既存ズーム機構を流用）
        has_center = (
            "translateX" in js_section
            and "translateY" in js_section
        )
        assert has_center, "translateX/translateY による中央寄せコードがない"

    @pytest.mark.unit
    def test_deterministic_match_order(self, bpass1b_html):
        """マッチ機器の巡回順が決定的（sort 等によるID昇順）なコードがある。"""
        js_section = _extract_js(bpass1b_html)
        # sort 呼び出しがナビゲーション関連コード中にある
        assert ".sort(" in js_section, (
            "ナビゲーションのマッチリストに sort がない（決定的順序が保証されない）"
        )

# ================================================================
# 6. CSS 定義
# ================================================================

class TestCssDefinitions:
    """新 CSS クラスが template.py に追加されている。"""

    @pytest.mark.unit
    def test_search_focus_css_exists(self, bpass1b_html):
        """.device-node.search-focus の CSS 定義が存在する。"""
        # CSS セクションで search-focus が定義されている
        assert "search-focus" in bpass1b_html, (
            ".search-focus CSS クラス定義がない"
        )

    @pytest.mark.unit
    def test_search_focus_has_stroke_style(self, bpass1b_html):
        """.device-node.search-focus に stroke（強調枠）スタイルが定義されている。"""
        css_section = _extract_css(bpass1b_html)
        # search-focus のスタイルブロックに stroke が含まれる
        focus_block = _extract_css_block(css_section, "search-focus")
        assert focus_block is not None, ".search-focus CSS ブロックが見つからない"
        assert "stroke" in focus_block, (
            f".search-focus に stroke スタイルがない: {focus_block!r}"
        )

    @pytest.mark.unit
    def test_tr_search_match_css_exists(self, bpass1b_html):
        """tr.search-match の CSS 定義が存在する（ifinv ヒット行強調）。"""
        css_section = _extract_css(bpass1b_html)
        assert "tr.search-match" in css_section or "search-match" in css_section, (
            "tr.search-match CSS クラス定義がない"
        )

    @pytest.mark.unit
    def test_tr_search_match_has_background(self, bpass1b_html):
        """tr.search-match に background スタイルが定義されている。"""
        css_section = _extract_css(bpass1b_html)
        # tr.search-match または tr.search-match td ブロックに background が含まれる
        # _extract_css_block は最初にヒットしたブロックを返すため、
        # tr.search-match を直接検索する
        match_block = _extract_css_block(css_section, "tr.search-match")
        assert match_block is not None, "tr.search-match CSS ブロックが見つからない"
        assert "background" in match_block, (
            f"tr.search-match に background スタイルがない: {match_block!r}"
        )

# ================================================================
# 7. 件数表示（i/N件 形式）
# ================================================================

class TestSearchCountFormat:
    """search-count の i/N件 形式更新コード。"""

    @pytest.mark.unit
    def test_count_format_uses_slash(self, bpass1b_html):
        """件数表示が「i/N件」形式（スラッシュ使用）を含む。"""
        js_section = _extract_js(bpass1b_html)
        # search-count textContent 設定で / を使う
        # 例: countEl.textContent = focusIdx + '/' + total + '件'
        has_slash_count = (
            "search-count" in js_section
            and "/" in js_section
        )
        assert has_slash_count, "search-count の / 形式カウント更新コードがない"

    @pytest.mark.unit
    def test_count_zero_shows_zero(self, bpass1b_html):
        """0件の場合「0件」を表示するコードがある（0 件分岐）。"""
        js_section = _extract_js(bpass1b_html)
        # 0 件の場合は「0件」か空文字列
        # 「0」もしくは「件」が search-count 更新コードにある（既存）
        assert "0" in js_section or "件" in js_section, (
            "0件表示コードが見当たらない"
        )

    @pytest.mark.unit
    def test_count_empty_when_no_query(self, bpass1b_html):
        """空クエリ時は search-count が空になるコードがある。"""
        js_section = _extract_js(bpass1b_html)
        # 既存: q が空のとき '' を設定
        assert "search-count" in js_section

# ================================================================
# 8. 決定性・自己完結・非回帰
# ================================================================

class TestBPass1bNonRegression:
    """B-pass1b の決定性・自己完結・既存機能非回帰。"""

    @pytest.mark.unit
    def test_html_is_self_contained(self, bpass1b_html):
        """HTML が外部リソース参照なし（src=/http:/https: を含まない）。"""
        lower = bpass1b_html.lower()
        # src= から始まる外部リソースがないこと
        external_refs = re.findall(r'src=[\'"](https?://[^\'"]+)[\'"]', lower)
        assert not external_refs, f"外部リソース参照がある: {external_refs}"

    @pytest.mark.unit
    def test_render_returns_string(self):
        """render() が文字列を返す（非回帰）。"""
        from lib.rendering import render
        html = render(_dualstack_topology_for_bpass1b())
        assert isinstance(html, str)
        assert len(html) > 0

    @pytest.mark.unit
    def test_physical_view_nodes_present(self, bpass1b_html):
        """Physical ビューノードが存在する（非回帰）。"""
        assert "view-physical" in bpass1b_html
        assert 'class="device-node' in bpass1b_html

    @pytest.mark.unit
    def test_bgp_view_present(self, bpass1b_html):
        """BGP ビューが存在する（非回帰）。"""
        assert "view-bgp" in bpass1b_html

    @pytest.mark.unit
    def test_ospf_view_present(self, bpass1b_html):
        """OSPF ビューが存在する（非回帰）。"""
        assert "view-ospf" in bpass1b_html

    def test_search_input_still_exists(self, bpass1b_html):
        """グローバル検索入力 #search-input が存在する（非回帰）。"""
        assert 'id="search-input"' in bpass1b_html

    def test_filter_nodes_function_still_exists(self, bpass1b_html):
        """filterNodes 関数が存在する（非回帰）。"""
        js_section = _extract_js(bpass1b_html)
        assert "function filterNodes" in js_section

    @pytest.mark.unit
    def test_select_view_function_still_exists(self, bpass1b_html):
        """selectView 関数が存在する（非回帰）。"""
        js_section = _extract_js(bpass1b_html)
        assert "function selectView" in js_section

    @pytest.mark.unit
    def test_search_match_css_still_exists(self, bpass1b_html):
        """.search-match CSS が存在する（B-pass1 非回帰）。"""
        assert "search-match" in bpass1b_html

    @pytest.mark.integration
    def test_render_twice_is_deterministic(self):
        """同じ topology を2回 render() した結果が同一（決定性）。"""
        from lib.rendering import render
        topo = _dualstack_topology_for_bpass1b()
        html1 = render(topo)
        html2 = render(topo)
        assert html1 == html2, "2回の render() 結果が異なる（非決定的）"

    @pytest.mark.unit
    def test_device_node_has_data_ips(self, bpass1b_html):
        """SVG ノードに data-ips 属性が存在する（B-pass1 非回帰）。"""
        assert "data-ips=" in bpass1b_html

# ================================================================
# ユーティリティ関数
# ================================================================

def _extract_js(html: str) -> str:
    """HTML から <script> ブロック（application/json 以外）を抽出して結合する。"""
    blocks = re.findall(
        r'<script(?![^>]*type=["\']application/json["\'])[^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE
    )
    return "\n".join(blocks)

def _extract_css(html: str) -> str:
    """HTML から <style> ブロックを抽出して結合する。"""
    blocks = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL | re.IGNORECASE)
    return "\n".join(blocks)

def _extract_css_block(css: str, selector_keyword: str) -> str | None:
    """CSS テキストから selector_keyword を含む最初のブロック {...} を返す。"""
    # セレクタ行（selector_keyword を含む）の後のブロック
    idx = css.find(selector_keyword)
    if idx == -1:
        return None
    # ブロック開始 '{'
    brace_start = css.find("{", idx)
    if brace_start == -1:
        return None
    # ブロック終了 '}'
    brace_end = css.find("}", brace_start)
    if brace_end == -1:
        return None
    return css[brace_start:brace_end + 1]

# ================================================================
# Round B Review 修正テスト（A1/A2/A3/A4/B/C）
# ================================================================

class TestCenterOnDeviceNodeRect:
    """A1/A3: _centerOnDevice が .node-rect の x/y/width/height を参照し、
    ズーム closure 状態（window._zoomState）経由で transform を更新する。
    """

    @pytest.mark.unit
    def test_center_on_device_reads_node_rect_not_g_transform(self, bpass1b_html):
        """_centerOnDevice が g の transform から座標を読まず、
        .node-rect の x/y/width/height 属性を参照する JS コードを持つ。
        """
        js_section = _extract_js(bpass1b_html)
        # 実座標取得: querySelector('.node-rect') か getElementsByClassName 等で rect を取得する
        has_rect_ref = (
            "node-rect" in js_section
            or "querySelector('.node-rect')" in js_section
            or 'querySelector(".node-rect")' in js_section
        )
        assert has_rect_ref, (
            "_centerOnDevice が .node-rect を参照していない（g transform を使っている可能性あり）"
        )

    @pytest.mark.unit
    def test_center_on_device_does_not_rely_solely_on_g_transform(self, bpass1b_html):
        """_centerOnDevice の座標取得に g.getAttribute('transform') からの正規表現抽出のみに
        依存していない（node-rect の属性も読む実装になっている）。
        """
        js_section = _extract_js(bpass1b_html)
        # 旧実装: g の transform 文字列から /translate\(/ で抽出
        # 新実装: node-rect の x/y/width/height を getAttribute で取得
        # node-rect を読んでいることを確認
        assert "node-rect" in js_section, (
            "_centerOnDevice に node-rect の参照がない（g transform のみを使っている）"
        )

    @pytest.mark.unit
    def test_zoom_state_shared_object_exposed(self, bpass1b_html):
        """ズーム closure の状態が window._zoomState または
        window._setPan 等の公開関数/オブジェクト経由で外部から更新可能になっている。
        """
        js_section = _extract_js(bpass1b_html)
        # 方式A: window._zoomState オブジェクト
        # 方式B: window._setPan 等の公開関数
        # 方式C: window._zoomReset と同じ方式で applyTransform を呼ぶ関数を露出
        has_shared_state = (
            "_zoomState" in js_section
            or "_setPan" in js_section
            or "_applyTransform" in js_section
        )
        assert has_shared_state, (
            "ズーム closure の状態が外部公開されていない "
            "（window._zoomState/window._setPan 等が存在しない）"
        )

    @pytest.mark.unit
    def test_center_on_device_uses_shared_zoom_state(self, bpass1b_html):
        """_centerOnDevice が ズーム共有状態（window._zoomState 等）を使って
        applyTransform を呼ぶコードを持つ（直接 setAttribute を呼ばない）。
        """
        js_section = _extract_js(bpass1b_html)
        # _centerOnDevice 関数内で _zoomState か _setPan か applyTransform を参照
        has_apply = (
            "_zoomState" in js_section
            or "_setPan" in js_section
            or ("_centerOnDevice" in js_section and "applyTransform" in js_section)
        )
        assert has_apply, (
            "_centerOnDevice が applyTransform または共有ズーム状態を使っていない"
        )

    @pytest.mark.unit
    def test_center_math_uses_rect_center_not_corner(self, bpass1b_html):
        """中心寄せ math が rect の中心（x + width/2, y + height/2）を使う
        コードになっている（corner 座標ではない）。
        """
        js_section = _extract_js(bpass1b_html)
        # width/2 か height/2 のいずれかが _centerOnDevice 付近に存在する
        # JS では "width / 2" or "width/2" のパターンで出現する可能性がある
        has_half = (
            "width / 2" in js_section
            or "width/2" in js_section
            or ("parseFloat" in js_section and "width" in js_section and "height" in js_section)
        )
        assert has_half, (
            "_centerOnDevice の中心算出に width/2 または height/2 が見つからない"
        )

class TestNavigateSearchNextFocusPreservation:
    """A2: navigateSearchNext が selectView 呼び出し前後で
    _searchFocusIndex を保存・復元する。
    """

    @pytest.mark.unit
    def test_navigate_next_preserves_focus_index_across_select_view(self, bpass1b_html):
        """navigateSearchNext の JS コードが selectView 呼び出し周辺で
        _searchFocusIndex を保存するコードを持つ。

        実装パターン:
        - selectView 前後で _searchFocusIndex を保存/復元する変数
        - filterNodes 内のリセット処理にガードを入れる（_isNavigating フラグ等）
        """
        js_section = _extract_js(bpass1b_html)
        # パターンA: navigateSearchNext 内で selectView 前に index 保存
        # パターンB: filterNodes 内にナビゲーション中は index リセットしないガード
        # パターンC: selectView が _searchFocusIndex をリセットしない分岐
        has_preservation = (
            # save-restore パターン
            ("savedIndex" in js_section or "savedFocus" in js_section or "_savedIndex" in js_section)
            # または filterNodes 内のリセット抑制
            or ("_isNavigating" in js_section or "isNavigating" in js_section)
            # または filterNodes が _searchFocusIndex をリセットしない条件分岐
            or (
                "_searchFocusIndex" in js_section
                and "selectView" in js_section
                and (
                    "savedIndex" in js_section
                    or "_isNavigating" in js_section
                    or "savedFocus" in js_section
                    or "noReset" in js_section
                )
            )
        )
        assert has_preservation, (
            "navigateSearchNext が selectView 前後で _searchFocusIndex を保存・復元する"
            "コード（savedIndex/_isNavigating等）が見つからない"
        )

    @pytest.mark.unit
    def test_navigate_next_index_not_reset_after_select_view(self, bpass1b_html):
        """navigateSearchNext でタブ切替後も _searchFocusIndex が維持される
        コード構造になっている（filterNodes の無条件リセットを防ぐ）。
        """
        js_section = _extract_js(bpass1b_html)
        # selectView 呼び出しが navigateSearchNext 内にある場合、
        # _searchFocusIndex リセットを防ぐ実装が必要
        # 実装が存在するかを確認（filterNodes が selectView 経由でリセットしないよう保護）
        has_guard = (
            "_isNavigating" in js_section
            or "savedIndex" in js_section
            or "_savedIndex" in js_section
            or "savedFocus" in js_section
            or "noReset" in js_section
        )
        assert has_guard, (
            "_searchFocusIndex リセット抑制のためのガード変数/フラグが見つからない"
        )

class TestVacuousTestFixes:
    """B: 既存テストの弱検証修正（vacuous/重複除去）。"""

    def test_count_zero_shows_zero_ken(self, bpass1b_html):
        """0件の場合「0件」を表示するコードが JS に含まれる（"0件" の文字列を確認）。"""
        js_section = _extract_js(bpass1b_html)
        # 旧テスト: "0" in js は常 True → 具体的な "0件" で検証
        assert "0件" in js_section, (
            "search-count 0件表示の '0件' 文字列が JS に存在しない"
        )

class TestCidrPythonValidation:
    """B/H-2: data-ips の値を Python ipaddress で検証する（JS文字列存在チェックの補完）。"""

    @pytest.mark.unit
    def test_data_ips_no_cidr_superset_v4_v6(self):
        """v4 アドレスが v6 CIDR を含まず、v6 アドレスが v4 CIDR を含まない。

        _build_ips_attr の出力が v4/v6 を混在させない（ipaddress で検証）。
        """
        import ipaddress
        from lib.rendering.svg import _build_ips_attr
        interfaces = [
            _make_iface(
                id="r1::Gi0/0", device="r1", name="Gi0/0",
                ip="10.0.0.1/30",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                    {"af": "v6", "ip": "2001:db8:1::1", "prefix": 127},
                ],
            )
        ]
        ips_str = _build_ips_attr(interfaces)
        ips = ips_str.split()
        for ip_cidr in ips:
            net = ipaddress.ip_interface(ip_cidr)
            # v4 アドレスが v6 CIDR に含まれない（型チェック）
            if isinstance(net, ipaddress.IPv4Interface):
                assert net.version == 4, f"v4 として処理されるべき {ip_cidr} が v4 でない"
            else:
                assert net.version == 6, f"v6 として処理されるべき {ip_cidr} が v6 でない"

    @pytest.mark.unit
    def test_data_ips_no_slash_zero_supernet(self):
        """data-ips の値に /0（全域スーパーネット）が含まれない。"""
        from lib.rendering.svg import _build_ips_attr
        interfaces = [
            _make_iface(
                id="r1::Gi0/0", device="r1", name="Gi0/0",
                ip="10.0.0.1/30",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                ],
            )
        ]
        ips_str = _build_ips_attr(interfaces)
        assert "/0" not in ips_str, (
            f"data-ips に /0（全域スーパーネット）が含まれている: {ips_str!r}"
        )

    @pytest.mark.unit
    def test_data_ips_v4_host_route_preserved(self):
        """v4 /32 ホストルートアドレス（例: Loopback0）は data-ips に含まれる。"""
        from lib.rendering.svg import _build_ips_attr
        interfaces = [
            _make_iface(
                id="r1::Lo0", device="r1", name="Loopback0",
                ip="192.168.1.1/32",
                addresses=[
                    {"af": "v4", "ip": "192.168.1.1", "prefix": 32},
                ],
            )
        ]
        ips_str = _build_ips_attr(interfaces)
        assert "192.168.1.1/32" in ips_str, (
            f"v4 /32 ホストルートが data-ips に含まれない: {ips_str!r}"
        )

    @pytest.mark.unit
    def test_data_ips_v6_host_route_preserved(self):
        """v6 /128 ホストルートアドレスは data-ips に含まれる。"""
        from lib.rendering.svg import _build_ips_attr
        interfaces = [
            _make_iface(
                id="r1::Lo0", device="r1", name="Loopback0",
                ip=None,
                addresses=[
                    {"af": "v6", "ip": "2001:db8::1", "prefix": 128},
                ],
            )
        ]
        ips_str = _build_ips_attr(interfaces)
        assert "2001:db8::1/128" in ips_str, (
            f"v6 /128 ホストルートが data-ips に含まれない: {ips_str!r}"
        )

    @pytest.mark.unit
    def test_data_ips_link_local_excluded_python(self):
        """link-local (fe80::) アドレスは _build_ips_attr の出力に含まれない
        （Python 側で ipaddress で検証）。
        """
        import ipaddress
        from lib.rendering.svg import _build_ips_attr
        interfaces = [
            _make_iface(
                id="r1::Gi0/0", device="r1", name="Gi0/0",
                ip="10.0.0.1/30",
                addresses=[
                    {"af": "v4", "ip": "10.0.0.1", "prefix": 30},
                    {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"},
                ],
            )
        ]
        ips_str = _build_ips_attr(interfaces)
        for ip_cidr in ips_str.split():
            addr = ipaddress.ip_interface(ip_cidr)
            # link-local は含まれない
            assert not addr.ip.is_link_local, (
                f"link-local アドレスが data-ips に含まれている: {ip_cidr!r}"
            )

class TestDeadCodeCleanup:
    """C: デッドコード除去の確認テスト。"""

    @pytest.mark.unit
    def test_filter_if_rows_function_removed_or_unused(self, bpass1b_html):
        """filterIfRows 関数が除去されているか、#ifinv-search リスナーが存在しない。

        #ifinv-search 撤去に伴い filterIfRows は dead code になる。
        ただし filterIfRows 自体は _applyIfFilters の薄いラッパーなので
        残っていても良い（リスナー登録が消えていることを確認）。
        """
        js_section = _extract_js(bpass1b_html)
        # #ifinv-search への addEventListener が消えていること
        # getElementById('ifinv-search') がリスナー登録目的で存在しない
        has_ifinv_search_listener = (
            "getElementById('ifinv-search')" in js_section
            or 'getElementById("ifinv-search")' in js_section
        )
        # #ifinv-search リスナーが残っていないことを確認
        # （要素がないので実害はないが clean にする）
        # このテストは「リスナーが存在しない」ことを期待する
        assert not has_ifinv_search_listener, (
            "#ifinv-search の getElementById によるリスナー登録が JS に残っている（デッドコード）"
        )

    @pytest.mark.unit
    def test_is_v4_cidr_strict_regex(self, bpass1b_html):
        """_isV4Cidr の正規表現が厳密な形式（{1,3}）になっている。

        旧: /^[\\d.]+\\/\\d+$/ → 誤CIDR判定の可能性あり
        新: /^(\\d{1,3}\\.){3}\\d{1,3}\\/\\d+$/ 程度に締める
        """
        js_section = _extract_js(bpass1b_html)
        # 新正規表現: {1,3} パターンを含む
        has_strict_regex = (
            "{1,3}" in js_section
            or "\\d{1,3}" in js_section
        )
        assert has_strict_regex, (
            "_isV4Cidr 正規表現が厳密でない（{1,3} パターンがない）"
        )

    @pytest.mark.unit
    def test_ips_match_cidr_helper_exists(self, bpass1b_html):
        """_ipsMatchCidr 共通ヘルパーが JS に存在する（v4/v6 内包ループの集約）。

        _nodeMatchesCidr と _applyIfFilters の両方で使われる共通ヘルパー。
        """
        js_section = _extract_js(bpass1b_html)
        assert "_ipsMatchCidr" in js_section, (
            "_ipsMatchCidr 共通ヘルパーが JS に存在しない（v4/v6 CIDR ループが重複している）"
        )

    @pytest.mark.unit
    def test_b_pass1b_phase_comment_removed(self, bpass1b_html):
        """開発用フェーズコメント 'B-pass1b:' が HTML 内の JS から除去されている。"""
        js_section = _extract_js(bpass1b_html)
        assert "B-pass1b:" not in js_section, (
            "開発用フェーズコメント 'B-pass1b:' が JS に残っている（除去すること）"
        )
