"""
rendering/layout.py — レイアウト計算モジュール

定数と座標計算関数を提供する。
"""
from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

_NODE_WIDTH = 120      # ノード矩形の幅（px）
_NODE_HEIGHT = 50      # ノード矩形の高さ（基本高さ: IF 0 本時 px）
_NODE_HEADER_H = 36   # ノード上部 hostname + sublabel 領域の高さ（px）
_NODE_IF_ROW_H = 16   # 1 IF 行あたりの高さ（px）
_NODE_IF_PADDING = 4  # IF 列の上下パディング合計（px）
_SEG_RX = 50           # セグメント楕円の横半径
_SEG_RY = 25           # セグメント楕円の縦半径
_MARGIN = 80           # キャンバス外周マージン（px）
_MIN_CANVAS_W = 600    # 動的キャンバス最小幅
_MIN_CANVAS_H = 400    # 動的キャンバス最小高さ

# AS グルーピング枠（BGP ビュー用）定数
_AS_GROUP_PADDING = 20    # AS 枠とノード矩形間のパディング（px）
_AS_GROUP_LABEL_OFFSET = 14  # AS 枠ラベルの上端からのオフセット（px）
_AS_GROUP_RX = 10         # AS 枠角丸半径 x（px）
_AS_GROUP_RY = 10         # AS 枠角丸半径 y（px）

# OSPF ラベル書式定数
OSPF_AREA_LABEL_FORMAT = "area {area} · {subnet}"

# キャンバスサイズ計算定数（DRY 化用）
_CANVAS_SCALE_EXP = 0.7   # ノード数のスケーリング指数
_CANVAS_FACTOR_W = 3      # 幅方向ファクター（間延び抑制のため段階的に縮小: 15→11→8→6→3）
_CANVAS_FACTOR_H = 2.5    # 高さ方向ファクター（間延び抑制のため段階的に縮小: 12→9→7→5→2.5）


def _node_size_for(n_ifaces: int) -> tuple[float, float]:
    """
    IF 数 n_ifaces からノードの (width, height) を返す（svg.py と共有する DRY ヘルパー）。

    高さ = ヘッダー領域 + IF 行数 × 1行高 + パディング
    width は常に _NODE_WIDTH 固定。

    >>> _node_size_for(0)[0] == _NODE_WIDTH
    >>> _node_size_for(0)[1] == _NODE_HEIGHT
    >>> _node_size_for(3)[1] > _node_size_for(0)[1]
    """
    h = _NODE_HEADER_H + max(0, n_ifaces) * _NODE_IF_ROW_H + _NODE_IF_PADDING
    # IF なしの場合は最低限 _NODE_HEIGHT を確保
    h = max(float(_NODE_HEIGHT), float(h))
    return float(_NODE_WIDTH), h


def _adaptive_iter(n: int) -> int:
    """
    ノード数 n に応じた force-directed 反復回数を返す（適応反復）。

    小さいグラフ: 300 反復（高品質）
    大きいグラフ: n に応じて削減（パフォーマンス）
    最低保証: 100 反復（決定性維持のため同一 n なら常に同一値）

    >>> _adaptive_iter(1) == 300
    >>> _adaptive_iter(200) == 100
    """
    return max(100, 300 - n)


def _canvas_size_for_nodes(n: int, max_node_h: float | None = None) -> tuple[float, float]:
    """
    ノード数 n からキャンバスサイズ (w, h) を計算する（DRY ヘルパー）。

    5 箇所に分散していた est_w/est_h 計算をここに集約する。
    n=0 または n=1 の場合は最小キャンバスサイズを返す。

    Args:
        n:          ノード数
        max_node_h: 最大ノード高 (px)。省略時は _NODE_HEIGHT（IF 0本ノードのデフォルト高さ）を使用。
                    多 IF ノードを含む場合は実際の最大高を渡すことでキャンバス高を自動拡張する。
    """
    node_h = float(max_node_h) if max_node_h is not None else float(_NODE_HEIGHT)
    min_h = max(float(_MIN_CANVAS_H), node_h * 2 + 2 * _MARGIN)
    if n <= 1:
        return float(_MIN_CANVAS_W), min_h
    w = max(_MIN_CANVAS_W, n * (_NODE_WIDTH + 20) ** _CANVAS_SCALE_EXP * _CANVAS_FACTOR_W)
    h = max(min_h, n * (node_h + 20) ** _CANVAS_SCALE_EXP * _CANVAS_FACTOR_H)
    return w, h


def _compute_layout(devices: list[dict], segments: list[dict]) -> dict[str, tuple[float, float]]:
    """
    機器とセグメントノードの座標を決定的に計算する。

    配置アルゴリズム:
    - 機器は円形に等間隔配置（デバイス ID の安定ソート順）
    - セグメントノードは中心付近に配置
    - 1台の場合は中央、0台の場合も中央に配置
    """
    positions: dict[str, tuple[float, float]] = {}

    cx, cy = 460.0, 300.0  # SVG 中心
    device_radius = 200.0   # 機器配置円の半径

    sorted_devices = sorted(devices, key=lambda d: d["id"])
    n = len(sorted_devices)

    if n == 0:
        pass
    elif n == 1:
        positions[sorted_devices[0]["id"]] = (cx, cy)
    else:
        for i, dev in enumerate(sorted_devices):
            angle = (2 * math.pi * i / n) - math.pi / 2  # 上から時計回り
            x = cx + device_radius * math.cos(angle)
            y = cy + device_radius * math.sin(angle)
            positions[dev["id"]] = (x, y)

    # セグメントノードは中心寄りに配置
    sorted_segments = sorted(segments, key=lambda s: s["id"])
    m = len(sorted_segments)
    seg_radius = 80.0

    for j, seg in enumerate(sorted_segments):
        if m == 1:
            positions[seg["id"]] = (cx, cy - seg_radius)
        else:
            angle = (2 * math.pi * j / m)
            sx = cx + seg_radius * math.cos(angle)
            sy = cy + seg_radius * math.sin(angle)
            positions[seg["id"]] = (sx, sy)

    return positions


def _layout_force_directed(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    *,
    width: float,
    height: float,
    iterations: int = 300,
    node_sizes: dict[str, int] | None = None,
) -> dict[str, tuple[float, float]]:
    """
    決定的 Fruchterman–Reingold 系 force-directed レイアウト。

    設計上の決定性保証:
    - 初期配置はノードIDを安定ソートして円周上に等間隔配置（完全決定的）
    - 乱数・時刻・float ハッシュ非依存（Python dict はソートして走査）
    - 同一 (node_ids, edges, width, height, iterations, node_sizes) ならば毎回同一座標を返す

    重なり回避:
    - Fruchterman–Reingold の斥力は全ノードペアに作用し初期から分離を促す
    - 最終パスで矩形ベースの最小間隔を強制する（node_sizes で可変高対応）

    引数:
        node_ids:   ノード ID のリスト（順序不問。内部でソートして決定的初期配置）
        edges:      (a, b) ペアのリスト（有向/無向どちらでも同一として扱う）
        width:      キャンバス幅 px
        height:     キャンバス高さ px
        iterations: 緩和反復回数（デフォルト 300）
        node_sizes: {node_id: n_ifaces} — IF 数マップ。省略時は全ノードデフォルト高さ

    Returns:
        {node_id: (x, y)} — 全ノードが [0, width] x [0, height] 内に収まる座標
    """
    n = len(node_ids)
    if n == 0:
        return {}

    # 安定ソートして ID → インデックスマップを作る
    sorted_ids = sorted(node_ids)
    idx_map = {nid: i for i, nid in enumerate(sorted_ids)}

    # ---- 初期配置: 円周上に等間隔（完全決定的） ----
    cx, cy = width / 2.0, height / 2.0
    if n == 1:
        pos = [[cx, cy]]
    else:
        radius = min(width, height) * 0.35
        pos = []
        for i in range(n):
            angle = (2.0 * math.pi * i / n) - math.pi / 2.0
            pos.append([
                cx + radius * math.cos(angle),
                cy + radius * math.sin(angle),
            ])

    if n == 1:
        return {sorted_ids[0]: (pos[0][0], pos[0][1])}

    # ---- Fruchterman–Reingold パラメータ ----
    area = width * height
    k = math.sqrt(area / n)  # 最適距離

    def _repulsion(dist: float) -> float:
        """斥力（ノードペア）"""
        if dist < 1e-6:
            return k * k / 1e-6
        return k * k / dist

    def _attraction(dist: float) -> float:
        """引力（エッジ）"""
        return dist * dist / k

    # クーリングスケジュール（固定線形冷却）
    t_max = width / 10.0
    t_step = t_max / iterations

    # エッジを隣接リストに変換（存在するノードIDのみ）
    adj: list[list[int]] = [[] for _ in range(n)]
    for a, b in edges:
        if a in idx_map and b in idx_map:
            ia, ib = idx_map[a], idx_map[b]
            adj[ia].append(ib)
            adj[ib].append(ia)

    # ---- メイン緩和ループ ----
    for step in range(iterations):
        t = t_max - step * t_step  # 現在の温度

        disp = [[0.0, 0.0] for _ in range(n)]

        # 斥力: 全ノードペア
        for i in range(n):
            for j in range(i + 1, n):
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 1e-6:
                    # 縮退時は微小量でずらす（ID順で決定的）
                    dx, dy = 0.1 * (i - j), 0.1 * (j - i + 1)
                    dist = math.sqrt(dx * dx + dy * dy)
                rep = _repulsion(dist)
                ux, uy = dx / dist, dy / dist
                disp[i][0] += ux * rep
                disp[i][1] += uy * rep
                disp[j][0] -= ux * rep
                disp[j][1] -= uy * rep

        # 引力: エッジのみ
        for i in range(n):
            for j in adj[i]:
                if j <= i:
                    continue
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < 1e-6:
                    continue
                att = _attraction(dist)
                ux, uy = dx / dist, dy / dist
                disp[i][0] -= ux * att
                disp[i][1] -= uy * att
                disp[j][0] += ux * att
                disp[j][1] += uy * att

        # 位置更新（温度で制限）
        for i in range(n):
            dx, dy = disp[i]
            d = math.sqrt(dx * dx + dy * dy)
            if d > 1e-6:
                factor = min(d, t) / d
                pos[i][0] += dx * factor
                pos[i][1] += dy * factor
            # キャンバスにクランプ
            pos[i][0] = max(0.0, min(width, pos[i][0]))
            pos[i][1] = max(0.0, min(height, pos[i][1]))

    # ---- 最終パス: ノード重なり強制分離（可変高対応） ----
    # node_sizes が指定されている場合は矩形ベースで分離、なければ固定幅ベース
    _nsizes = node_sizes or {}
    sep_iters = 50
    for _ in range(sep_iters):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                n_ifaces_i = _nsizes.get(sorted_ids[i], 0)
                n_ifaces_j = _nsizes.get(sorted_ids[j], 0)
                wi, hi = _node_size_for(n_ifaces_i)
                wj, hj = _node_size_for(n_ifaces_j)
                # 矩形重なりを回避するための最小中心間距離（楕円近似）
                # 矩形の軸方向距離で独立に判定する方法より
                # 楕円近似（半径 = 対角長の半分 + マージン）で安全サイドに丸める
                min_sep = (math.sqrt(wi * wi + hi * hi) / 2.0
                           + math.sqrt(wj * wj + hj * hj) / 2.0
                           + 10.0)
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                dist = math.sqrt(dx * dx + dy * dy)
                if dist < min_sep:
                    overlap = (min_sep - dist + 0.5) / 2.0
                    if dist < 1e-6:
                        # 縮退: ID 順で決定的方向
                        angle = math.pi * (i * 2 + j) / (n + 1)
                        ux, uy = math.cos(angle), math.sin(angle)
                    else:
                        ux, uy = dx / dist, dy / dist
                    pos[i][0] = max(0.0, min(width, pos[i][0] + ux * overlap))
                    pos[i][1] = max(0.0, min(height, pos[i][1] + uy * overlap))
                    pos[j][0] = max(0.0, min(width, pos[j][0] - ux * overlap))
                    pos[j][1] = max(0.0, min(height, pos[j][1] - uy * overlap))
                    moved = True
        if not moved:
            break

    return {sorted_ids[i]: (pos[i][0], pos[i][1]) for i in range(n)}


def _compute_canvas(
    positions: dict[str, tuple[float, float]],
    node_sizes: dict[str, int] | None = None,
) -> tuple[float, float, float, float]:
    """
    ノード座標群からキャンバスの viewBox パラメータを算出する。

    Args:
        positions:  {node_id: (cx, cy)} 中心座標マップ
        node_sizes: {node_id: n_ifaces} IF 数マップ。指定するとノード矩形の半寸法分を
                    追加マージンとして確保し、ノードが viewBox からはみ出ないようにする。

    Returns:
        (min_x, min_y, canvas_width, canvas_height)  — SVG viewBox 用
    """
    if not positions:
        return 0.0, 0.0, float(_MIN_CANVAS_W), float(_MIN_CANVAS_H)

    _nsizes = node_sizes or {}

    xs = [x for x, _ in positions.values()]
    ys = [y for _, y in positions.values()]

    # ノード矩形の半寸法を加味した外縁を計算
    extra_left = extra_right = _MARGIN
    extra_top = extra_bottom = _MARGIN
    for nid, (cx, cy) in positions.items():
        n_if = _nsizes.get(nid, 0)
        nw, nh = _node_size_for(n_if)
        half_w = nw / 2.0
        half_h = nh / 2.0
        # 矩形左端/右端
        extra_left = max(extra_left, half_w + _MARGIN - (cx - min(xs)))
        extra_right = max(extra_right, half_w + _MARGIN)
        extra_top = max(extra_top, half_h + _MARGIN - (cy - min(ys)))
        extra_bottom = max(extra_bottom, half_h + _MARGIN)

    min_x = min(xs) - extra_left
    min_y = min(ys) - extra_top
    max_x = max(xs) + extra_right
    max_y = max(ys) + extra_bottom
    w = max(float(_MIN_CANVAS_W), max_x - min_x)
    h = max(float(_MIN_CANVAS_H), max_y - min_y)
    return min_x, min_y, w, h


def _make_bbox_str(positions: dict[str, tuple[float, float]]) -> str:
    """positions から data-bbox 文字列を生成する"""
    if not positions:
        return f"0 0 {_MIN_CANVAS_W} {_MIN_CANVAS_H}"
    min_x, min_y, w, h = _compute_canvas(positions)
    return f"{min_x:.1f} {min_y:.1f} {w:.1f} {h:.1f}"
