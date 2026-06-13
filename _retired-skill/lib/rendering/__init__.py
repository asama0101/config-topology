"""
lib.rendering パッケージ

公開 API:
    render(topology: dict) -> str   # 自己完結 HTML 文字列を返す

加えて、レイアウト計算の内部ヘルパー（force-directed・キャンバス算出・物理レイアウト）を
テスト/再利用向けに公開する。正本は各サブモジュール（layout.py / views.py）。
"""
from lib.rendering.core import render
from lib.rendering.layout import (
    _NODE_WIDTH,
    _MIN_CANVAS_W,
    _MIN_CANVAS_H,
    _adaptive_iter,
    _canvas_size_for_nodes,
    _layout_force_directed,
)
from lib.rendering.views import _build_physical_layout

__all__ = [
    "render",
    "_NODE_WIDTH",
    "_MIN_CANVAS_W",
    "_MIN_CANVAS_H",
    "_adaptive_iter",
    "_canvas_size_for_nodes",
    "_layout_force_directed",
    "_build_physical_layout",
]
