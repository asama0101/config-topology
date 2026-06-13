"""
test_colors_split.py — colors.py 分割の構造テスト

TDD: colors.py への移設と svg.py 再export が正しく機能していることを検証する。
- colors.py から直接 import 可能
- svg.py 経由でも同一オブジェクトが得られる（再export）
- circular import なし
"""
from __future__ import annotations

import pytest


@pytest.mark.unit
def test_colors_module_importable():
    """colors.py が import 可能であること。"""
    import lib.rendering.colors  # noqa: F401


@pytest.mark.unit
def test_as_color_palette_importable_from_colors():
    """_AS_COLOR_PALETTE を colors から import できること。"""
    from lib.rendering.colors import _AS_COLOR_PALETTE
    assert isinstance(_AS_COLOR_PALETTE, list)
    assert len(_AS_COLOR_PALETTE) > 0


@pytest.mark.unit
def test_ospf_area_color_importable_from_colors():
    """_ospf_area_color を colors から import できること。"""
    from lib.rendering.colors import _ospf_area_color
    assert callable(_ospf_area_color)


@pytest.mark.unit
def test_as_color_importable_from_colors():
    """_as_color を colors から import できること。"""
    from lib.rendering.colors import _as_color
    assert callable(_as_color)


@pytest.mark.unit
def test_as_color_palette_reexported_from_svg():
    """_AS_COLOR_PALETTE が svg.py から引き続き import できること（再export）。"""
    from lib.rendering.svg import _AS_COLOR_PALETTE
    assert isinstance(_AS_COLOR_PALETTE, list)
    assert len(_AS_COLOR_PALETTE) > 0


@pytest.mark.unit
def test_ospf_area_color_reexported_from_svg():
    """_ospf_area_color が svg.py から引き続き import できること（再export）。"""
    from lib.rendering.svg import _ospf_area_color
    assert callable(_ospf_area_color)


@pytest.mark.unit
def test_as_color_reexported_from_svg():
    """_as_color が svg.py から引き続き import できること（再export）。"""
    from lib.rendering.svg import _as_color
    assert callable(_as_color)


@pytest.mark.unit
def test_as_color_palette_is_same_object():
    """svg から import した _AS_COLOR_PALETTE と colors から import したものが同一オブジェクト。"""
    from lib.rendering.svg import _AS_COLOR_PALETTE as palette_svg
    from lib.rendering.colors import _AS_COLOR_PALETTE as palette_colors
    assert palette_svg is palette_colors


@pytest.mark.unit
def test_ospf_area_color_is_same_object():
    """svg から import した _ospf_area_color と colors から import したものが同一関数オブジェクト。"""
    from lib.rendering.svg import _ospf_area_color as fn_svg
    from lib.rendering.colors import _ospf_area_color as fn_colors
    assert fn_svg is fn_colors


@pytest.mark.unit
def test_as_color_is_same_object():
    """svg から import した _as_color と colors から import したものが同一関数オブジェクト。"""
    from lib.rendering.svg import _as_color as fn_svg
    from lib.rendering.colors import _as_color as fn_colors
    assert fn_svg is fn_colors


@pytest.mark.unit
def test_no_circular_import():
    """lib.rendering パッケージ全体が circular import なしで import できること。"""
    import lib.rendering  # noqa: F401
    import lib.rendering.colors  # noqa: F401
    import lib.rendering.svg  # noqa: F401


@pytest.mark.unit
def test_colors_module_does_not_import_svg():
    """colors.py が svg.py を import していないこと（circular import 防止）。"""
    import sys
    # colors を fresh に確認するため既にロード済みの場合はそのまま検査
    import lib.rendering.colors
    # colors モジュールの __dict__ に svg モジュールへの参照がないことを確認
    colors_mod = sys.modules["lib.rendering.colors"]
    assert "lib.rendering.svg" not in (
        getattr(v, "__name__", "") for v in vars(colors_mod).values()
        if hasattr(v, "__name__")
    ), "colors.py が svg.py を参照している（circular import の危険）"


@pytest.mark.unit
def test_as_color_palette_has_six_entries():
    """_AS_COLOR_PALETTE が 6 エントリを持つこと（仕様: 色覚配慮 6 色）。"""
    from lib.rendering.colors import _AS_COLOR_PALETTE
    assert len(_AS_COLOR_PALETTE) == 6


@pytest.mark.unit
def test_as_color_palette_each_entry_is_two_tuple():
    """_AS_COLOR_PALETTE の各エントリが (stroke, fill_rgba) の 2 要素タプルであること。"""
    from lib.rendering.colors import _AS_COLOR_PALETTE
    for entry in _AS_COLOR_PALETTE:
        assert len(entry) == 2, f"エントリ {entry!r} が 2 要素でない"


@pytest.mark.unit
def test_ospf_area_color_returns_str_for_valid_area():
    """colors から呼んだ _ospf_area_color が str を返すこと。"""
    from lib.rendering.colors import _ospf_area_color
    result = _ospf_area_color("0")
    assert isinstance(result, str)
    assert result.startswith("#")


@pytest.mark.unit
def test_ospf_area_color_returns_none_for_none():
    """colors から呼んだ _ospf_area_color(None) が None を返すこと。"""
    from lib.rendering.colors import _ospf_area_color
    assert _ospf_area_color(None) is None


@pytest.mark.unit
def test_as_color_returns_three_element_tuple():
    """colors から呼んだ _as_color が 3 要素タプルを返すこと。"""
    from lib.rendering.colors import _as_color
    result = _as_color(0)
    assert len(result) == 3


@pytest.mark.unit
def test_as_color_deterministic():
    """colors から呼んだ _as_color が同一 asn に対して同一色を返すこと（決定性）。"""
    from lib.rendering.colors import _as_color
    assert _as_color(5) == _as_color(5)
    assert _as_color(0) == _as_color(0)
