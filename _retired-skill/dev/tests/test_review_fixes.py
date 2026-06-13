"""TDD テスト: コードレビュー指摘修正の回帰テスト

修正1: clearLinkHighlight が .if-chip.highlighted を解除する
修正2: .link-down.highlighted .link-line でハイライト色を出す CSS ルール
修正3: コメント/docstring の正確性
修正4: _build_ibgp_loopback_map に DEPRECATED コメント
"""
from __future__ import annotations

import re
import pytest


# ---------------------------------------------------------------------------
# 修正1: clearLinkHighlight が .if-chip.highlighted を解除する（JS 文字列回帰）
# ---------------------------------------------------------------------------

class TestClearLinkHighlightRemovesIfChipHighlighted:
    """clearLinkHighlight が if-chip の .highlighted を解除する記述を持つ。"""

    @pytest.fixture
    def js_src(self):
        from lib.rendering.assets import _JS
        return _JS

    @pytest.mark.unit
    def test_clear_link_highlight_removes_if_chip_highlighted(self, js_src):
        """clearLinkHighlight 関数ブロック内に if-chip.highlighted の解除コードが存在する。"""
        # clearLinkHighlight 関数の範囲を抽出
        # 関数開始から次の最上位 function 定義まで（または十分な行数）
        match = re.search(
            r'function clearLinkHighlight\(\)\s*\{(.+?)(?=\n\s{4}//\s*={3,}|\n\s{4}function\s)',
            js_src,
            re.DOTALL,
        )
        assert match is not None, "clearLinkHighlight 関数が JS に見つからない"
        body = match.group(1)

        # if-chip.highlighted の解除コードが含まれること
        assert "if-chip" in body and "highlighted" in body, (
            "clearLinkHighlight 内に .if-chip.highlighted 解除コードが見つからない\n"
            f"関数本体: {body[:500]}"
        )

    @pytest.mark.unit
    def test_clear_link_highlight_queries_if_chip_highlighted(self, js_src):
        """clearLinkHighlight が querySelectorAll('.if-chip.highlighted') を呼ぶ。"""
        # clearLinkHighlight 関数ブロックを抽出
        match = re.search(
            r'function clearLinkHighlight\(\)\s*\{(.+?)(?=\n\s{4}//\s*={3,}|\n\s{4}function\s)',
            js_src,
            re.DOTALL,
        )
        assert match is not None, "clearLinkHighlight 関数が JS に見つからない"
        body = match.group(1)

        # '.if-chip.highlighted' セレクタが clearLinkHighlight 内で使われること
        assert ".if-chip.highlighted" in body, (
            "clearLinkHighlight 内で '.if-chip.highlighted' セレクタが使われていない\n"
            f"関数本体（先頭 500 文字）: {body[:500]}"
        )

    @pytest.mark.unit
    def test_clear_link_highlight_removes_highlighted_from_if_chip(self, js_src):
        """clearLinkHighlight が if-chip から 'highlighted' クラスを除去する。"""
        match = re.search(
            r'function clearLinkHighlight\(\)\s*\{(.+?)(?=\n\s{4}//\s*={3,}|\n\s{4}function\s)',
            js_src,
            re.DOTALL,
        )
        assert match is not None, "clearLinkHighlight 関数が JS に見つからない"
        body = match.group(1)

        # if-chip に対して classList.remove('highlighted') が呼ばれること
        # パターン: if-chip 関連のコードに remove('highlighted') が含まれる
        has_remove = (
            "classList.remove('highlighted')" in body
            or 'classList.remove("highlighted")' in body
        )
        assert has_remove, (
            "clearLinkHighlight 内で classList.remove('highlighted') が呼ばれていない\n"
            f"関数本体（先頭 800 文字）: {body[:800]}"
        )


# ---------------------------------------------------------------------------
# 修正2: .link-down.highlighted .link-line で stroke: var(--color-highlight) ルール
# ---------------------------------------------------------------------------

class TestLinkDownHighlightedCssRule:
    """.link-down.highlighted .link-line CSS ルールが存在する。"""

    @pytest.fixture
    def css_src(self):
        from lib.rendering.assets import _CSS
        return _CSS

    @pytest.mark.unit
    def test_link_down_highlighted_selector_exists(self, css_src):
        """.link-down.highlighted .link-line セレクタが CSS に存在する。"""
        # .link-edge.link-down.highlighted や .link-edge.link-down:hover に対するルール
        assert ".link-down.highlighted" in css_src, (
            "CSS に .link-down.highlighted セレクタが見つからない"
        )

    @pytest.mark.unit
    def test_link_down_highlighted_uses_color_highlight(self, css_src):
        """.link-down.highlighted ルールが --color-highlight を使う。"""
        # .link-down.highlighted を含むブロック内に --color-highlight が使われること
        # セレクタを探して近傍の CSS ブロックを確認
        match = re.search(
            r'\.link-down\.highlighted[^}]*\}',
            css_src,
            re.DOTALL,
        )
        # セレクタ行からブロック終端まで
        idx = css_src.find(".link-down.highlighted")
        assert idx >= 0, "CSS に .link-down.highlighted セレクタが見つからない"

        # そのブロック（末尾の } まで）を抽出
        block_start = idx
        block_end = css_src.find("}", block_start)
        assert block_end > block_start, "ブロック末尾 } が見つからない"
        block = css_src[block_start:block_end + 1]

        assert "--color-highlight" in block, (
            f".link-down.highlighted ブロックに --color-highlight が見つからない\nブロック: {block}"
        )

    @pytest.mark.unit
    def test_link_down_highlighted_maintains_dasharray(self, css_src):
        """.link-down.highlighted ルールが stroke-dasharray を維持する（破線を保つ）。"""
        idx = css_src.find(".link-down.highlighted")
        assert idx >= 0, "CSS に .link-down.highlighted セレクタが見つからない"
        block_end = css_src.find("}", idx)
        block = css_src[idx:block_end + 1]

        assert "stroke-dasharray" in block, (
            f".link-down.highlighted ブロックに stroke-dasharray がない（破線維持できていない）\n"
            f"ブロック: {block}"
        )

    @pytest.mark.unit
    def test_link_down_highlighted_rule_after_link_down_rule(self, css_src):
        """.link-down.highlighted ルールが .link-down ルールより後に定義されている（特異度優先）。"""
        idx_down = css_src.find(".link-edge.link-down .link-line")
        idx_down_hl = css_src.find(".link-down.highlighted")
        assert idx_down >= 0, "CSS に .link-edge.link-down .link-line が見つからない"
        assert idx_down_hl >= 0, "CSS に .link-down.highlighted が見つからない"
        assert idx_down_hl > idx_down, (
            ".link-down.highlighted ルールが .link-edge.link-down .link-line より前に定義されている"
        )


# ---------------------------------------------------------------------------
# 修正3: コメント/docstring の正確性
# ---------------------------------------------------------------------------

class TestCommentAccuracy:
    """コメント・docstring が実装の実態と一致する。"""

    @pytest.fixture
    def js_src(self):
        from lib.rendering.assets import _JS
        return _JS

    @pytest.mark.unit
    def test_toggle_if_chip_highlight_comment_no_ibgp_static(self, js_src):
        """toggleIfChipHighlight のコメントから 'iBGP' という記述が除去されている。
        （BGP 行は data-iface-id に統一。static 行のみ data-loopback-iface-id を持つ）。"""
        # toggleIfChipHighlight 関数直前のコメントブロック
        match = re.search(
            r'(//[^\n]*toggleIfChipHighlight[^\n]*\n(?://[^\n]*\n)*)function toggleIfChipHighlight',
            js_src,
        )
        if match is None:
            # コメントなし・または形式が異なる場合は関数自体の存在確認に留める
            assert "function toggleIfChipHighlight" in js_src, \
                "toggleIfChipHighlight 関数が見つからない"
            return

        comment_block = match.group(1)
        # 誤ったコメント「iBGP/static 行の data-loopback-iface-id 連動も本関数が担う」がないこと
        assert "iBGP/static 行の data-loopback-iface-id" not in comment_block, (
            "toggleIfChipHighlight コメントに古い記述 'iBGP/static 行の data-loopback-iface-id' が残っている"
        )

    @pytest.mark.unit
    def test_static_row_click_register_comment_corrected(self, js_src):
        """static 行クリック登録コメントが BGP 行を含まないことを示す記述になっている。"""
        # data-loopback-iface-id のみ持つ行のクリック登録コメント付近
        idx = js_src.find("data-loopback-iface-id]:not([data-iface-id])")
        assert idx >= 0, "data-loopback-iface-id]:not([data-iface-id]) セレクタが見つからない"

        # セレクタ前後 500 文字のコンテキストを取得
        context = js_src[max(0, idx - 300):idx + 200]
        # 古いコメント「BGP/static 行（data-loopback-iface-id のみ持つ行）のクリック登録」がないこと
        assert "BGP/static 行（data-loopback-iface-id のみ持つ行）のクリック登録" not in context, (
            "古いコメント 'BGP/static 行（data-loopback-iface-id のみ持つ行）のクリック登録' が残っている"
        )


# ---------------------------------------------------------------------------
# 修正4: _build_ibgp_loopback_map に DEPRECATED コメント
# ---------------------------------------------------------------------------

class TestDeprecatedBuildIbgpLoopbackMap:
    """_build_ibgp_loopback_map の docstring に DEPRECATED コメントが追加されている。"""

    @pytest.mark.unit
    def test_ibgp_loopback_map_has_deprecated_comment(self):
        """_build_ibgp_loopback_map の docstring に DEPRECATED という語が含まれる。"""
        import inspect
        from lib.rendering.core import _build_ibgp_loopback_map
        doc = inspect.getdoc(_build_ibgp_loopback_map) or ""
        assert "DEPRECATED" in doc, (
            "_build_ibgp_loopback_map の docstring に DEPRECATED コメントが見つからない\n"
            f"現在の docstring: {doc!r}"
        )

    @pytest.mark.unit
    def test_ibgp_loopback_map_deprecated_mentions_replacement(self):
        """DEPRECATED コメントが代替関数 _build_bgp_source_iface_map を言及する。"""
        import inspect
        from lib.rendering.core import _build_ibgp_loopback_map
        doc = inspect.getdoc(_build_ibgp_loopback_map) or ""
        assert "_build_bgp_source_iface_map" in doc, (
            "_build_ibgp_loopback_map の DEPRECATED コメントに代替関数名が見つからない\n"
            f"現在の docstring: {doc!r}"
        )

    @pytest.mark.unit
    def test_ibgp_loopback_map_function_body_intact(self):
        """_build_ibgp_loopback_map 関数本体が削除されていない（廃止コメントのみ許可）。"""
        import inspect
        from lib.rendering.core import _build_ibgp_loopback_map
        src = inspect.getsource(_build_ibgp_loopback_map)
        # 関数本体があること（return 文が存在する）
        assert "return" in src, "_build_ibgp_loopback_map の関数本体が削除されている（return がない）"
