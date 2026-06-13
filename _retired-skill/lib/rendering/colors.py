"""
rendering/colors.py — 色パレット定数・色決定関数モジュール

AS番号・OSPF area に対する決定的な色割り当てを提供する。
svg.py から分離した単独モジュール（circular import なし）。
"""
from __future__ import annotations


_AS_COLOR_PALETTE = [
    # (stroke, fill_rgba)  — 6色・色覚配慮・判別しやすい固定パレット
    # Phase 1C #5: AS番号ごとに決定的色分け（asn % len(_AS_COLOR_PALETTE) で循環）
    # label_bg は常に stroke と同色のため 2 要素に簡素化。
    # _as_color() 内で label_bg = stroke として展開する。
    ("#2563eb", "rgba(219,234,254,0.35)"),   # 青系  (index 0)
    ("#16a34a", "rgba(187,247,208,0.35)"),   # 緑系  (index 1)
    ("#d97706", "rgba(254,243,199,0.35)"),   # 橙系  (index 2)
    ("#9333ea", "rgba(243,232,255,0.35)"),   # 紫系  (index 3)
    ("#0891b2", "rgba(207,250,254,0.35)"),   # 水色系 (index 4)
    ("#dc2626", "rgba(254,226,226,0.35)"),   # 赤系  (index 5)
]


def _ospf_area_color(area: str | None) -> str | None:
    """OSPF area 文字列から決定的な stroke 色を返す（area が None または "" は None）。

    複合 area（"0/1"）は先頭 area の色（決定的）。数値 area は int%len で循環。
    非数値 area（ドット記法等）は文字コード和で決定的にフォールバック。
    呼び出し側は None のとき --area-stroke を出力せず従来色にフォールバックする。

    実装メモ: 色パレットは ``_AS_COLOR_PALETTE`` を意図的に流用。AS番号と OSPF area は
    独立した循環体系のため AS0 と area0 が同色になりうるが、これは意図的な設計。
    ``_as_color`` は (stroke, fill_rgba, label_bg) の3要素タプルを返すが、本関数は
    stroke のみを返す（OSPF 楕円に fill は不要なため）。

    Args:
        area: OSPF エリア文字列（例: "0", "1", "0/1", "0.0.0.1", "backbone"）。
              None または空文字のとき None を返す。

    Returns:
        stroke 色文字列（例: "#2563eb"）。area が None または "" のとき None。
    """
    if not area:
        return None
    first = str(area).split("/")[0].strip()
    try:
        idx = int(first) % len(_AS_COLOR_PALETTE)
    except (ValueError, TypeError):
        idx = sum(ord(c) for c in first) % len(_AS_COLOR_PALETTE)
    return _AS_COLOR_PALETTE[idx][0]  # stroke のみ


def _as_color(asn: int) -> tuple[str, str, str]:
    """AS番号から (stroke, fill_rgba, label_bg) 色タプルを返す（決定的・循環）。

    ``asn % len(_AS_COLOR_PALETTE)`` でパレットインデックスを決定する。
    同一 asn は常に同じ色（決定的）。asn が len を超えると循環する。
    label_bg は stroke と同色（_AS_COLOR_PALETTE は 2 要素で管理）。

    前提: asn は int（parser が int を保証する）。
    """
    idx = asn % len(_AS_COLOR_PALETTE)
    stroke, fill_rgba = _AS_COLOR_PALETTE[idx]
    label_bg = stroke  # ラベルチップ背景は枠線と同色
    return stroke, fill_rgba, label_bg
