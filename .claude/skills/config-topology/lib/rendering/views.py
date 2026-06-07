"""
rendering/views.py — ビュー別 SVG 生成モジュール
"""
from __future__ import annotations

import re

from lib.rendering.layout import (
    _adaptive_iter,
    _canvas_size_for_nodes,
    _compute_canvas,
    _compute_layout,
    _layout_force_directed,
    _make_bbox_str,
    _node_size_for,
    OSPF_AREA_LABEL_FORMAT,
)
from lib.rendering.layout import _NODE_WIDTH, _NODE_HEIGHT
from lib.rendering.svg import (
    _build_ip_to_device,
    _build_ip_to_iface_id,
    _chip_positions,
    _esc,
    _ext_id_to_ip,
    _is_loopback,
    _make_ext_id,
    _make_link_id,
    _merge_links_by_link_id,
    _normalize_subnet,
    _svg_bgp_as_groups,
    _svg_bgp_as_groups_split,
    _svg_bgp_edges,
    _svg_bgp_edges_split,
    _svg_bgp_external_edges,
    _svg_bgp_external_nodes,
    _svg_label_bg_rect,
    _svg_links,
    _svg_nodes,
    _svg_ospf_segment_edges,
    _svg_ospf_segments,
    _svg_segment_edges,
    _svg_segments,
    _as_color,
    _ospf_area_color,
)


# AS枠分離の最小ギャップ定数（px）: overlap+1.0 だけでは枠が近接しすぎるため最低限この距離を保証する
_MIN_AS_GAP = 24


def _build_legend_as_html(asns: list[int]) -> str:
    """BGP AS 番号リストから凡例パネル用 AS スウォッチ HTML を生成する。

    副作用なし・色は `_as_color(asn)` 委譲で同一 asn は常に同色（決定的）。
    `asns` は昇順ユニーク前提（`_collect_bgp_asns` の戻り値を渡すこと）。

    Args:
        asns: 重複なし・昇順ソート済みの AS 番号リスト（呼び出し側で保証）

    Returns:
        AS が1つ以上あれば見出し＋各 AS 行の HTML 文字列。空リストなら空文字。
    """
    if not asns:
        return ""
    rows = []
    rows.append('<div class="legend-section-title">AS 枠</div>')
    for asn in asns:
        stroke, _, _ = _as_color(asn)
        rows.append(
            f'<div class="legend-row">'
            f'<svg width="16" height="12" style="flex-shrink:0;vertical-align:middle">'
            f'<rect x="1" y="1" width="14" height="10" rx="2" fill="none"'
            f' stroke="{stroke}" stroke-width="2"/></svg>'
            f'<span>AS{asn}</span>'
            f'</div>'
        )
    return "\n".join(rows)


def _collect_ospf_areas(links: list[dict], segments: list[dict]) -> list[str]:
    """OSPF リンク・セグメントから area 文字列を収集し、重複除去・数値優先ソートで返す。

    複合 area（"0/1"）は "/" で分割して両方を収集する。None は除外する。

    Args:
        links:    topology["links"] リスト（各要素に ospf_area キーがあればよい）
        segments: topology["segments"] リスト（各要素に ospf_area キーがあればよい）

    Returns:
        重複なし・数値優先ソート済みの area 文字列リスト
    """
    areas: set[str] = set()
    for lk in links:
        raw = lk.get("ospf_area")
        if raw is None:
            continue
        for part in str(raw).split("/"):
            part = part.strip()
            if part:
                areas.add(part)
    for seg in segments:
        raw = seg.get("ospf_area")
        if raw is None:
            continue
        for part in str(raw).split("/"):
            part = part.strip()
            if part:
                areas.add(part)
    return sorted(areas, key=lambda a: (0, int(a)) if a.isdigit() else (1, a))


def _build_legend_ospf_area_html(areas: list[str]) -> str:
    """OSPF area リストから凡例パネル用 Area スウォッチ HTML を生成する。

    副作用なし・色は `_ospf_area_color(area)` 委譲で同一 area は常に同色（決定的）。
    `areas` は重複なし・数値優先ソート前提（`_collect_ospf_areas` の戻り値を渡すこと）。

    Args:
        areas: 重複なし・ソート済みの OSPF area 文字列リスト

    Returns:
        area が1つ以上あれば各 area 行の HTML 文字列。空リストなら空文字。
    """
    if not areas:
        return ""
    rows = []
    for area in areas:
        color = _ospf_area_color(area)
        stroke = color if color else "var(--color-ospf)"
        rows.append(
            f'<div class="legend-row">'
            f'<svg width="16" height="12" style="flex-shrink:0;vertical-align:middle">'
            f'<line x1="1" y1="6" x2="15" y2="6" stroke="{stroke}" stroke-width="2"/></svg>'
            f'<span>area {_esc(area)}</span>'
            f'</div>'
        )
    return "\n".join(rows)


def _collect_bgp_asns(devices: list[dict], bgp_entries: list[dict]) -> list[int]:
    """BGP 参加デバイスから AS 番号を収集し、重複なし昇順で返す。

    devices[].as および bgp_entries[].local_as を両方参照し、
    int 化できるもののみ収集する。

    Args:
        devices:     topology["devices"]
        bgp_entries: topology["routing"]["bgp"]

    Returns:
        重複なし昇順 int リスト
    """
    asns: set[int] = set()
    for dev in devices:
        asn = dev.get("as")
        if asn is not None:
            try:
                asns.add(int(asn))
            except (ValueError, TypeError):
                pass
    for entry in bgp_entries:
        local_as = entry.get("local_as")
        if local_as is not None:
            try:
                asns.add(int(local_as))
            except (ValueError, TypeError):
                pass
    return sorted(asns)


def _build_legend_panel_inner(
    view_ids: list[str],
    legend_as_html: str,
    legend_ospf_area_html: str = "",
) -> str:
    """凡例パネルの内側 HTML をビュー存在に応じて条件生成する。

    常に表示するセクション:
    - ノード節（通常ノード・外部ピア・next-hop 経路対象）
    - Physical リンク節
    - IF チップ節

    ビュー存在依存のセクション:
    - BGP 節（eBGP/iBGP/unknown）: ``'bgp' in view_ids`` の時のみ
    - OSPF 節: ``'ospf' in view_ids`` の時のみ（Area スウォッチも含む）

    動的 AS 節（``legend_as_html``）: 空文字でなければ末尾に追記。

    Args:
        view_ids: 生成済みビュー ID リスト（例: ["physical", "bgp", "ospf"]）
        legend_as_html: _build_legend_as_html() の戻り値。空文字なら出力しない。
        legend_ospf_area_html: _build_legend_ospf_area_html() の戻り値。空文字なら出力しない。

    Returns:
        legend-panel div の内側 HTML 文字列（決定的・副作用なし）。
    """
    parts: list[str] = []

    # ---- ノード節（常時）----
    parts.append("""\
        <div class="legend-section-title">ノード</div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <rect x="1" y="1" width="20" height="12" rx="3" class="node-rect"/></svg>
          <span>通常ノード</span>
        </div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <rect x="1" y="1" width="20" height="12" rx="3" class="node-rect external-rect"/></svg>
          <span>外部ピア（topology外）</span>
        </div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <rect x="1" y="1" width="20" height="12" rx="3" class="node-rect route-target" style="fill:#d1fae5;stroke:#059669;stroke-width:2"/></svg>
          <span>next-hop 経路対象</span>
        </div>""")

    # ---- Physical リンク節（常時）----
    parts.append("""\
        <div class="legend-section-title">リンク（Physical）</div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <line x1="1" y1="7" x2="21" y2="7" stroke="var(--color-link)" stroke-width="2"/></svg>
          <span>Physical リンク</span>
        </div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <line x1="1" y1="7" x2="21" y2="7" stroke="var(--color-highlight)" stroke-width="2"/></svg>
          <span>ハイライト</span>
        </div>""")

    # ---- BGP 節（bgp ビューが存在する場合のみ）----
    if "bgp" in view_ids:
        parts.append("""\
        <div class="legend-section-title">BGP</div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <line x1="1" y1="7" x2="21" y2="7" stroke="var(--color-bgp-ebgp)" stroke-width="2"/></svg>
          <span>eBGP</span>
        </div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <line x1="1" y1="7" x2="21" y2="7" stroke="var(--color-bgp-ibgp)" stroke-width="2"/></svg>
          <span>iBGP</span>
        </div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <line x1="1" y1="7" x2="21" y2="7" stroke="var(--color-bgp-unknown)" stroke-width="2"/></svg>
          <span>unknown</span>
        </div>""")

    # ---- OSPF 節（ospf ビューが存在する場合のみ）----
    if "ospf" in view_ids:
        ospf_section = """\
        <div class="legend-section-title">OSPF</div>
        <div class="legend-row">
          <svg width="22" height="14" style="flex-shrink:0;vertical-align:middle">
            <line x1="1" y1="7" x2="21" y2="7" stroke="var(--color-ospf)" stroke-width="2"/></svg>
          <span>OSPF リンク・ラベル</span>
        </div>"""
        if legend_ospf_area_html:
            ospf_section += f"\n        {legend_ospf_area_html}"
        parts.append(ospf_section)

    # ---- IF チップ節（常時）----
    parts.append("""\
        <div class="legend-section-title">IF チップ</div>
        <div class="legend-row">
          <svg width="12" height="12" style="flex-shrink:0;vertical-align:middle"><g class="if-chip"><circle cx="6" cy="6" r="5"/></g></svg>
          <span>接続 IF</span>
        </div>
        <div class="legend-row">
          <svg width="12" height="12" style="flex-shrink:0;vertical-align:middle"><g class="if-chip if-chip-loopback"><circle cx="6" cy="6" r="5"/></g></svg>
          <span>Loopback</span>
        </div>
        <div class="legend-row">
          <svg width="12" height="12" style="flex-shrink:0;vertical-align:middle"><g class="if-chip highlighted"><circle cx="6" cy="6" r="5" fill="#fef08a" stroke="#f59e0b" stroke-width="2"/></g></svg>
          <span>ハイライト IF</span>
        </div>""")

    # ---- 動的 AS 節（空文字でなければ）----
    if legend_as_html:
        parts.append(f"        {legend_as_html}")

    return "\n".join(parts)


def _as_cluster_bbox(
    dev_ids: list[str],
    positions: dict[str, tuple[float, float]],
    node_sizes: dict[str, int],
    padding: float,
) -> tuple[float, float, float, float]:
    """AS クラスタの bounding box (min_x, min_y, max_x, max_y) を返す。

    node_sizes は {dev_id: n_ifaces} マップ。padding は AS 枠と同じ値を使う。

    Raises:
        ValueError: dev_ids が空のとき
    """
    if not dev_ids:
        raise ValueError("dev_ids must not be empty")
    xs = [positions[d][0] for d in dev_ids]
    tops = []
    bottoms = []
    for d in dev_ids:
        cy = positions[d][1]
        _w, node_h = _node_size_for(node_sizes.get(d, 0))
        tops.append(cy - node_h / 2)
        bottoms.append(cy + node_h / 2)
    min_x = min(xs) - _NODE_WIDTH / 2 - padding
    min_y = min(tops) - padding
    max_x = max(xs) + _NODE_WIDTH / 2 + padding
    max_y = max(bottoms) + padding
    return min_x, min_y, max_x, max_y


def _separate_as_clusters(
    positions: dict[str, tuple[float, float]],
    bgp_devices: list[dict],
    node_sizes: dict[str, int],
    padding: float,
    max_iters: int = 50,
) -> dict[str, tuple[float, float]]:
    """BGP ビューのノード座標確定後、AS 枠 bbox が重なるクラスタを分離する後処理。

    各 AS のメンバーノード全体を平行移動することで AS 枠同士が重ならない状態にする。
    クラスタ内の相対配置（force-directed 結果）は保持する。

    アルゴリズム:
    1. AS番号昇順で asn -> [dev_id, ...] を構築（as=None は除外）。
    2. 全 AS ペアについて bbox 重なりを検出。
    3. 重なりがある場合、後発 AS（大きい番号）のクラスタを重なり方向に応じてシフト。
    4. 重なりがなくなるか max_iters 回で打ち切る（決定的・有限回）。

    決定性: ASN 昇順・ペア処理順が固定のため、同一入力で常に同一結果。

    Args:
        positions:   force-directed 後の {dev_id: (cx, cy)} 座標辞書
        bgp_devices: BGP 参加デバイスリスト
        node_sizes:  {dev_id: n_ifaces} マップ
        padding:     AS 枠パディング（_svg_bgp_as_groups_split と同じ値）
        max_iters:   最大反復回数

    Returns:
        AS 分離後の {dev_id: (cx, cy)} 座標辞書（コピー）
    """
    from collections import defaultdict

    # asn -> [dev_id] マップを ASN 昇順で構築
    asn_to_devs: dict[int, list[str]] = defaultdict(list)
    for dev in sorted(bgp_devices, key=lambda d: d["id"]):
        asn = dev.get("as")
        if asn is None:
            continue
        if dev["id"] in positions:
            asn_to_devs[asn].append(dev["id"])

    # AS が 1 種類以下 → 分離不要
    asns = sorted(asn_to_devs.keys())
    if len(asns) <= 1:
        return dict(positions)

    # 座標をコピーして操作
    pos = {k: list(v) for k, v in positions.items()}  # {dev_id: [x, y]}

    def _bbox(asn: int) -> tuple[float, float, float, float]:
        dev_ids = asn_to_devs[asn]
        pts = {d: (pos[d][0], pos[d][1]) for d in dev_ids}
        min_x, min_y, max_x, max_y = _as_cluster_bbox(dev_ids, pts, node_sizes, padding)
        return min_x, min_y, max_x, max_y

    def _rects_overlap(r1: tuple, r2: tuple) -> bool:
        ax, ay, aw_end, ah_end = r1
        bx, by, bw_end, bh_end = r2
        return not (aw_end <= bx or bw_end <= ax or ah_end <= by or bh_end <= ay)

    def _shift_cluster(asn: int, dx: float, dy: float) -> None:
        for dev_id in asn_to_devs[asn]:
            pos[dev_id][0] += dx
            pos[dev_id][1] += dy

    # F3: max_iters を AS 数に応じた動的値に変更（50固定の打ち切りサイレント化を防止）
    # n 個の AS クラスタが全て重なるとき最悪 O(n^2) 回の分離パスが必要になるため
    # max(50, n * n) を上限とすることで実用ケースで確実収束させる。
    n_as = len(asns)
    effective_max_iters = max(max_iters, n_as * n_as)
    for _ in range(effective_max_iters):
        any_overlap = False
        for i, asn_a in enumerate(asns):
            for j in range(i + 1, len(asns)):
                asn_b = asns[j]
                bb_a = _bbox(asn_a)
                bb_b = _bbox(asn_b)
                if not _rects_overlap(bb_a, bb_b):
                    continue
                any_overlap = True
                # 重なり量を x/y 方向それぞれ計算し、小さい方向にシフト（最小移動）
                ax, ay, ax2, ay2 = bb_a
                bx, by, bx2, by2 = bb_b
                overlap_x = min(ax2, bx2) - max(ax, bx)
                overlap_y = min(ay2, by2) - max(ay, by)
                # asn_b（後発 AS）を重なりが解消する方向にシフト
                # x/y どちらか小さい方でシフト（最小移動原則）
                if overlap_x <= overlap_y:
                    # x 軸方向にシフト
                    # asn_b 中心が asn_a 中心より右なら右へ、左なら左へ
                    cx_a = (ax + ax2) / 2
                    cx_b = (bx + bx2) / 2
                    direction = 1.0 if cx_b >= cx_a else -1.0
                    _shift_cluster(asn_b, direction * (overlap_x + _MIN_AS_GAP), 0.0)
                else:
                    # y 軸方向にシフト
                    cy_a = (ay + ay2) / 2
                    cy_b = (by + by2) / 2
                    direction = 1.0 if cy_b >= cy_a else -1.0
                    _shift_cluster(asn_b, 0.0, direction * (overlap_y + _MIN_AS_GAP))
        if not any_overlap:
            break

    return {k: (v[0], v[1]) for k, v in pos.items()}


def _build_bgp_layout(
    devices: list[dict],
    bgp_entries: list[dict],
    interfaces: list[dict],
) -> tuple[dict[str, tuple[float, float]], list[dict]]:
    """BGP ビュー用レイアウト計算（BGP 参加 device のみ）"""
    bgp_device_ids: set[str] = set()
    for entry in bgp_entries:
        bgp_device_ids.add(entry["device"])

    # neighbor_ip が解決できる device も含める
    # Phase 3G: v6 addresses 対応のため _build_ip_to_device を共用
    ip_to_device = _build_ip_to_device(interfaces)
    for entry in bgp_entries:
        neighbor_ip = entry.get("neighbor_ip", "")
        nbr_dev = ip_to_device.get(neighbor_ip)
        if nbr_dev:
            bgp_device_ids.add(nbr_dev)

    bgp_devices = [d for d in devices if d["id"] in bgp_device_ids]

    # エッジ: BGP セッション
    edge_list: list[tuple[str, str]] = []
    seen_pairs: set[frozenset] = set()
    for entry in bgp_entries:
        dev_id = entry["device"]
        nbr_dev = ip_to_device.get(entry.get("neighbor_ip", ""))
        if nbr_dev and nbr_dev != dev_id:
            pair = frozenset([dev_id, nbr_dev])
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                edge_list.append((dev_id, nbr_dev))

    node_ids = [d["id"] for d in bgp_devices]
    est_n = max(1, len(node_ids))
    est_w, est_h = _canvas_size_for_nodes(est_n)

    if not node_ids:
        return {}, bgp_devices
    if est_n <= 1:
        return _compute_layout(bgp_devices, []), bgp_devices

    # チップ数に基づく node_sizes（1行=チップあり、0=チップなし）
    bgp_chip_ids = _build_bgp_chip_iface_ids(bgp_entries, interfaces)
    iface_by_device_tmp: dict[str, list[dict]] = {}
    for iface in interfaces:
        iface_by_device_tmp.setdefault(iface["device"], []).append(iface)
    node_sizes: dict[str, int] = {
        dev_id: (1 if any(i["id"] in bgp_chip_ids for i in iface_by_device_tmp.get(dev_id, [])) else 0)
        for dev_id in node_ids
    }

    positions = _layout_force_directed(
        node_ids, edge_list, width=est_w, height=est_h,
        iterations=_adaptive_iter(est_n),
        node_sizes=node_sizes,
    )

    # F3: AS 枠 bbox 重なり分離（force-directed 後処理）
    # 外部ノード（"ext:" プレフィックス）を除いた BGP デバイスの AS クラスタを分離する。
    from lib.rendering.layout import _AS_GROUP_PADDING
    positions = _separate_as_clusters(
        positions, bgp_devices, node_sizes,
        padding=_AS_GROUP_PADDING,
    )

    return positions, bgp_devices


def _build_ospf_layout(
    devices: list[dict],
    ospf_entries: list[dict],
    links: list[dict],
    segments: list[dict] | None = None,
    interfaces: list[dict] | None = None,
) -> tuple[dict[str, tuple[float, float]], list[dict], list[dict]]:
    """OSPF ビュー用レイアウト計算（OSPF 参加 device + OSPF 参加 segment）

    Returns:
        positions: ノード ID → (x, y) 座標の辞書（device + segment）
        ospf_devices: OSPF 参加 device リスト
        ospf_segments: OSPF 参加セグメント（ospf_area 付き）リスト
    """
    if segments is None:
        segments = []
    if interfaces is None:
        interfaces = []

    ospf_device_ids: set[str] = set(entry["device"] for entry in ospf_entries)

    # OSPF 参加セグメント（ospf_area が付いているもの）
    ospf_segments = [s for s in segments if s.get("ospf_area") is not None]

    # interface id → device id のマップ（segment メンバー解決用）
    iface_to_device: dict[str, str] = {iface["id"]: iface["device"] for iface in interfaces}

    # H2: ospf_area 付きセグメントのメンバー device を ospf_device_ids に追加
    # routing.ospf が空でも ospf_area 付きセグメントがあればメンバーが孤立しない
    for seg in ospf_segments:
        for member_iface_id in seg.get("members", []):
            dev_id = iface_to_device.get(member_iface_id)
            if dev_id:
                ospf_device_ids.add(dev_id)

    ospf_devices = [d for d in devices if d["id"] in ospf_device_ids]

    # エッジリスト: p2p リンク（両端が OSPF 参加）
    edge_list: list[tuple[str, str]] = []
    for lk in links:
        if lk["a_device"] in ospf_device_ids and lk["b_device"] in ospf_device_ids:
            edge_list.append((lk["a_device"], lk["b_device"]))

    # セグメントノード → メンバー機器 のエッジ（OSPF 参加機器のみ）
    for seg in ospf_segments:
        for member_iface_id in seg.get("members", []):
            dev_id = iface_to_device.get(member_iface_id)
            if dev_id and dev_id in ospf_device_ids:
                edge_list.append((seg["id"], dev_id))

    # セグメント ID も node_ids に含める
    node_ids = [d["id"] for d in ospf_devices] + [s["id"] for s in ospf_segments]
    est_n = len(node_ids)
    if not node_ids:
        return {}, ospf_devices, ospf_segments
    if est_n == 1:
        return _compute_layout(ospf_devices, ospf_segments), ospf_devices, ospf_segments
    # ここに到達する時点で est_n >= 2 が保証される
    est_w, est_h = _canvas_size_for_nodes(est_n)

    # チップ数に基づく node_sizes（デバイスのみ; セグメントノードは 0）
    ospf_chip_ids = _build_ospf_chip_iface_ids(links, segments, interfaces or [], ospf_device_ids)
    iface_by_device_tmp: dict[str, list[dict]] = {}
    for iface in (interfaces or []):
        iface_by_device_tmp.setdefault(iface["device"], []).append(iface)
    node_sizes: dict[str, int] = {
        dev_id: (1 if any(i["id"] in ospf_chip_ids for i in iface_by_device_tmp.get(dev_id, [])) else 0)
        for dev_id in [d["id"] for d in ospf_devices]
    }
    # セグメントノードのサイズは 0（楕円）
    for seg in ospf_segments:
        node_sizes[seg["id"]] = 0

    positions = _layout_force_directed(
        node_ids, edge_list, width=est_w, height=est_h,
        iterations=_adaptive_iter(est_n),
        node_sizes=node_sizes,
    )
    return positions, ospf_devices, ospf_segments


def _build_generic_proto_layout(
    devices: list[dict],
    proto_entries: list[dict],
    links: list[dict],
) -> tuple[dict[str, tuple[float, float]], list[dict]]:
    """汎用プロトコルビュー用レイアウト計算（参加 device のみ）"""
    device_ids: set[str] = set(entry["device"] for entry in proto_entries if "device" in entry)
    proto_devices = [d for d in devices if d["id"] in device_ids]

    # エッジ: 同一リンクの両端が共に参加
    edge_list: list[tuple[str, str]] = []
    for lk in links:
        if lk["a_device"] in device_ids and lk["b_device"] in device_ids:
            edge_list.append((lk["a_device"], lk["b_device"]))

    node_ids = [d["id"] for d in proto_devices]
    est_n = max(1, len(node_ids))
    est_w, est_h = _canvas_size_for_nodes(est_n)

    if not node_ids:
        return {}, proto_devices
    if est_n <= 1:
        return _compute_layout(proto_devices, []), proto_devices

    positions = _layout_force_directed(
        node_ids, edge_list, width=est_w, height=est_h,
        iterations=_adaptive_iter(est_n)
    )
    return positions, proto_devices


def _build_physical_layout(
    devices: list[dict],
    interfaces: list[dict],
    links: list[dict],
    segments: list[dict],
) -> dict[str, tuple[float, float]]:
    """Physical ビュー用レイアウト計算（device + segment ノード）。

    可変高対応: デバイスの IF 数を node_sizes として渡し、
    重なり強制分離パスで矩形ベースの間隔を使用する。
    また最大ノード高からキャンバス高を補正し、多 IF ノードが viewBox に収まるよう保証する。
    """
    node_ids = [d["id"] for d in devices] + [s["id"] for s in segments]
    iface_to_device = {iface["id"]: iface["device"] for iface in interfaces}
    edge_list: list[tuple[str, str]] = []
    for lk in links:
        edge_list.append((lk["a_device"], lk["b_device"]))
    for seg in segments:
        for member_iface_id in seg.get("members", []):
            dev_id = iface_to_device.get(member_iface_id)
            if dev_id:
                edge_list.append((seg["id"], dev_id))

    # device ごとの IF 数マップ（可変高分離用）
    iface_count: dict[str, int] = {}
    for iface in interfaces:
        dev_id = iface["device"]
        iface_count[dev_id] = iface_count.get(dev_id, 0) + 1

    # 最大ノード高を算出してキャンバス高に反映（多 IF ノード対応）
    max_node_h = max(
        (_node_size_for(cnt)[1] for cnt in iface_count.values()),
        default=_node_size_for(0)[1],
    )

    est_n = max(1, len(node_ids))
    est_w, est_h = _canvas_size_for_nodes(est_n, max_node_h=max_node_h)

    if est_n <= 1:
        return _compute_layout(devices, segments)

    return _layout_force_directed(
        node_ids, edge_list, width=est_w, height=est_h,
        iterations=_adaptive_iter(est_n),
        node_sizes=iface_count,
    )


# C MED-1: BGP 外部ピアノード配置定数（モジュールレベル UPPER_SNAKE_CASE）
_EXT_COLUMN_MARGIN = 180.0  # 内部ノード右端からの水平マージン（px）
_EXT_NODE_SPACING = _NODE_HEIGHT + 40.0  # 外部ノード縦間隔（_NODE_HEIGHT=50 + margin 40）


def _bgp_has_resolved_edges(bgp_entries: list[dict], interfaces: list[dict]) -> bool:
    """内部に描画可能な BGP エッジ（= 双方向に相互設定された内部ピア）が存在するか

    Phase 3G: v6 BGP ネイバーに対応するため _build_ip_to_device を共用する。
    F4: BGP ピアは双方向設定が必須のため、片方向（A→B のみ）の内部ピアはエッジを
    描かない（_svg_bgp_edges_split と同じ判定）。ここでも双方向（A→B かつ B→A）の
    内部ペアが1つ以上ある場合のみ True を返し、片方向のみの topology で空の BGP ビューが
    生成されるのを防ぐ。外部ピアは _bgp_has_external_peers が別途ゲートする。
    """
    ip_to_device = _build_ip_to_device(interfaces)
    directed: set[tuple[str, str]] = set()
    for entry in bgp_entries:
        dev_id = entry.get("device", "")
        nbr = ip_to_device.get(entry.get("neighbor_ip", ""))
        if dev_id and nbr and nbr != dev_id:
            directed.add((dev_id, nbr))
    for a, b in directed:
        if (b, a) in directed:
            return True
    return False


def _bgp_has_external_peers(bgp_entries: list[dict], interfaces: list[dict]) -> bool:
    """BGP エントリに外部ピア（topology 外の neighbor_ip）が存在するか

    A1: 外部ピアのみの機器（ISP 接続エッジ等）で BGP ビューを生成するためのゲート。
    neighbor_ip が interfaces から逆引きできないものを外部ピアとみなす。
    """
    ip_to_device = _build_ip_to_device(interfaces)
    for entry in bgp_entries:
        neighbor_ip = entry.get("neighbor_ip", "")
        if not neighbor_ip:
            continue
        if not ip_to_device.get(neighbor_ip):
            return True
    return False


def _compute_ext_bgp_positions(
    bgp_entries: list[dict],
    interfaces: list[dict],
    positions: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    """BGP 外部ピアノードの座標を決定的に計算する。

    外部ピア = neighbor_ip が interfaces の ip_to_device に解決されないもの。
    外部ノード ID: ``"ext:{neighbor_ip}"``（dedup）。

    配置方式: 内部ノード群の bbox 右端 + マージンを基準に、
    neighbor_ip 昇順で縦に等間隔配置（決定的 reserved column）。

    Args:
        bgp_entries:  BGP エントリリスト
        interfaces:   topology の interfaces リスト
        positions:    内部デバイスID → (cx, cy) 座標辞書

    Returns:
        ``{ext_id: (cx, cy)}`` 辞書（neighbor_ip 昇順決定的）。外部ピアがなければ空。
    """
    ip_to_device = _build_ip_to_device(interfaces)

    # 外部ピアの dedup（neighbor_ip 昇順）
    ext_ips: list[str] = []
    seen_ext: set[str] = set()
    for entry in sorted(bgp_entries, key=lambda e: (e["device"], e.get("neighbor_ip", ""))):
        neighbor_ip = entry.get("neighbor_ip", "")
        if not neighbor_ip:
            continue
        if ip_to_device.get(neighbor_ip):
            continue  # 内部解決: スキップ
        if neighbor_ip not in seen_ext:
            seen_ext.add(neighbor_ip)
            ext_ips.append(neighbor_ip)

    if not ext_ips:
        return {}

    # 内部ノード群の bbox 右端を計算（positions が空のケースを安全に処理）
    if positions:
        max_x = max(x for x, y in positions.values())
        min_y = min(y for x, y in positions.values())
        max_y = max(y for x, y in positions.values())
    else:
        max_x = 300.0
        min_y = 100.0
        max_y = 500.0

    # 外部ノード列: 右端 + マージン（モジュールレベル定数を使用）
    col_x = max_x + _NODE_WIDTH / 2 + _EXT_COLUMN_MARGIN

    # 垂直方向: 内部ノード群の縦中心を軸に等間隔
    n_ext = len(ext_ips)
    center_y = (min_y + max_y) / 2.0
    total_h = (n_ext - 1) * _EXT_NODE_SPACING
    start_y = center_y - total_h / 2.0

    result: dict[str, tuple[float, float]] = {}
    for k, neighbor_ip in enumerate(sorted(ext_ips)):  # 昇順ソートで決定的
        ext_id = _make_ext_id(neighbor_ip)
        y = start_y + k * _EXT_NODE_SPACING
        result[ext_id] = (col_x, y)

    return result


def _ospf_has_edges(ospf_entries: list[dict], links: list[dict]) -> bool:
    """OSPF エントリに、両端が OSPF 参加するリンクが存在するか"""
    ospf_device_ids = set(e["device"] for e in ospf_entries if "device" in e)
    for lk in links:
        if lk["a_device"] in ospf_device_ids and lk["b_device"] in ospf_device_ids:
            return True
    return False


def _generic_has_edges(proto_entries: list[dict], links: list[dict]) -> bool:
    """汎用プロトコルエントリに、両端が参加するリンクが存在するか"""
    device_ids = set(e["device"] for e in proto_entries if "device" in e)
    for lk in links:
        if lk["a_device"] in device_ids and lk["b_device"] in device_ids:
            return True
    return False


def _build_connected_iface_ids(
    links: list[dict],
    segments: list[dict],
    interfaces: list[dict],
) -> set[str]:
    """リンク/セグメントの端点になっている iface-id の集合を返す（iteration-3 #2）。

    接続IF判定に使用する。IF 名から iface-id へのマップを構築して効率化する。
    """
    connected: set[str] = set()

    # iface name → iface id マップ（device 付きで衝突回避）
    name_to_id: dict[tuple[str, str], str] = {
        (iface["device"], iface["name"]): iface["id"]
        for iface in interfaces
    }

    # リンク端点の iface-id を登録
    for link in links:
        a_dev = link.get("a_device", "")
        a_if = link.get("a_if") or ""
        b_dev = link.get("b_device", "")
        b_if = link.get("b_if") or ""
        if a_dev and a_if:
            iid = name_to_id.get((a_dev, a_if))
            if iid:
                connected.add(iid)
        if b_dev and b_if:
            iid = name_to_id.get((b_dev, b_if))
            if iid:
                connected.add(iid)

    # セグメントメンバーの iface-id を登録
    for seg in segments:
        for member_iface_id in seg.get("members", []):
            connected.add(member_iface_id)

    return connected


def _build_physical_chip_iface_ids(
    interfaces: list[dict],
    links: list[dict],
    segments: list[dict],
) -> set[str]:
    """Physical ビュー用チップ集合を返す（接続IF + Loopback）。

    iteration-3 #2 と同じ選定ロジックを集中管理する。
    devices パラメータは不要（interfaces/links/segments のみ使用）。
    """
    connected = _build_connected_iface_ids(links, segments, interfaces)
    result: set[str] = set()
    for iface in interfaces:
        if iface["id"] in connected or _is_loopback(iface.get("name", "")):
            result.add(iface["id"])
    return result


def _build_view_physical(
    devices: list[dict],
    interfaces: list[dict],
    links: list[dict],
    segments: list[dict],
    positions: dict[str, tuple[float, float]],
    iface_by_device: dict[str, list[dict]],
) -> str:
    """Physical ビュー SVG コンテンツを生成する（BGP オーバーレイなし）。

    ノードは chip_iface_ids=phys_chip_ids（接続IF + Loopback）でチップ型描画。
    iteration-3 #2: 接続IF/Loopback のみをチップとして表示し、全 IF はカード表に残す。
    iteration-4 #6: チップアンカー（リンク端点をチップ座標に接続）。
    整理: 描画チップ集合とアンカー集合の源泉を phys_chip_ids に一本化する（ドリフト防止）。
    """
    # Physical チップ集合（接続IF + Loopback）— 描画・アンカー共通の単一源泉
    phys_chip_ids = _build_physical_chip_iface_ids(interfaces, links, segments)

    # チップ座標マップを構築（全デバイス分）
    all_chip_positions: dict[str, tuple[float, float]] = {}
    for dev in devices:
        dev_pos = positions.get(dev["id"])
        if dev_pos is None:
            continue
        dev_ifaces = iface_by_device.get(dev["id"], [])
        dev_chip_ids = {i["id"] for i in dev_ifaces if i["id"] in phys_chip_ids}
        if dev_chip_ids:
            cp = _chip_positions(dev, dev_chip_ids, dev_ifaces, dev_pos[0], dev_pos[1])
            all_chip_positions.update(cp)

    # name_to_iface_id マップ（_svg_links のチップアンカー用）
    name_to_iface_id = {(i["device"], i["name"]): i["id"] for i in interfaces}

    seg_edges = _svg_segment_edges(segments, interfaces, positions,
                                    chip_positions=all_chip_positions)
    links_str = _svg_links(
        links, positions,
        chip_positions=all_chip_positions,
        name_to_iface_id=name_to_iface_id,
    )
    segs_str = _svg_segments(segments, positions)
    # Physical ビュー: chip_iface_ids=phys_chip_ids を単一経路として渡す。
    # _svg_nodes 内の show_interfaces/connected_iface_ids は chip_iface_ids が
    # 明示されたとき無視される（優先）ため、描画チップ集合とアンカー集合が同一源泉に統一される。
    nodes_str = _svg_nodes(
        devices, positions, iface_by_device,
        chip_iface_ids=phys_chip_ids,
    )
    bbox = _make_bbox_str(positions)
    inner = "\n".join(filter(None, [seg_edges, links_str, segs_str, nodes_str]))
    return (
        f'<g class="view view-physical" id="view-physical" data-bbox="{bbox}">\n'
        f'{inner}\n'
        f'</g>'
    )


def _build_bgp_chip_iface_ids(
    bgp_entries: list[dict],
    interfaces: list[dict],
) -> set[str]:
    """BGP ビュー用チップ集合を返す（BGP セッション関与 IF のみ）。

    各エントリの local_ip / neighbor_ip にマッチする IF を集める。
    - local_ip → 当該デバイスの IF
    - neighbor_ip → 逆引きで隣接デバイスの IF
    - local_ip=null（iBGP Loopback 源）のとき、当該デバイスの Loopback IF を追加
      （iBGP は Loopback アドレス経由が一般的であり、neighbor_ip で逆引きできない
       ケースを補完する）
    決定的（IP ソート）。
    """
    # ip_only -> iface_id マップ（共通ヘルパーを使用）
    ip_to_iface_id = _build_ip_to_iface_id(interfaces)

    # device -> Loopback iface_id リスト（local_ip=null 補完用）
    dev_loopbacks: dict[str, list[str]] = {}
    for iface in interfaces:
        if _is_loopback(iface.get("name", "")):
            dev_loopbacks.setdefault(iface["device"], []).append(iface["id"])

    result: set[str] = set()
    for entry in bgp_entries:
        local_ip = (entry.get("local_ip") or "").split("/")[0]
        neighbor_ip = (entry.get("neighbor_ip") or "").split("/")[0]
        if local_ip and local_ip in ip_to_iface_id:
            result.add(ip_to_iface_id[local_ip])
        elif not local_ip:
            # local_ip=null: 当該デバイスの Loopback を BGP ソース IF として追加
            dev_id = entry.get("device", "")
            for lb_id in dev_loopbacks.get(dev_id, []):
                result.add(lb_id)
        if neighbor_ip and neighbor_ip in ip_to_iface_id:
            result.add(ip_to_iface_id[neighbor_ip])
    return result


def _build_view_bgp(
    devices: list[dict],
    interfaces: list[dict],
    bgp_entries: list[dict],
    links: list[dict],
    iface_by_device: dict[str, list[dict]],
) -> str:
    """BGP ビュー SVG コンテンツを生成する。

    描画順: AS 枠（背面）→ BGP エッジ → ノード（前面）
    iteration-4 #6: BGP セッション関与 IF のみチップ表示、エッジ端点をチップにアンカー。
    """
    positions_bgp, bgp_devices = _build_bgp_layout(devices, bgp_entries, interfaces)

    # BGP チップ集合（セッション関与 IF のみ）
    bgp_chip_ids = _build_bgp_chip_iface_ids(bgp_entries, interfaces)

    # チップ座標マップを構築（BGP 参加デバイス分）
    all_chip_positions: dict[str, tuple[float, float]] = {}
    bgp_node_sizes: dict[str, int] = {}
    for dev in bgp_devices:
        dev_pos = positions_bgp.get(dev["id"])
        if dev_pos is None:
            continue
        dev_ifaces = iface_by_device.get(dev["id"], [])
        dev_chip_ids = {i["id"] for i in dev_ifaces if i["id"] in bgp_chip_ids}
        if dev_chip_ids:
            cp = _chip_positions(dev, dev_chip_ids, dev_ifaces, dev_pos[0], dev_pos[1])
            all_chip_positions.update(cp)
            bgp_node_sizes[dev["id"]] = 1 if dev_chip_ids else 0

    # B4: 外部ピアノードの座標を決定的に計算
    ext_positions = _compute_ext_bgp_positions(bgp_entries, interfaces, positions_bgp)

    # z-order 修正 (#3/#4): AS枠 rect/ラベル と BGPエッジ 線/バッジ を分離して描画順を制御する
    # 目標（背面→前面）: AS枠rect群 → BGPエッジ線 → 外部エッジ線 → device-nodes
    #                  → 外部nodes → AS番号ラベル群 → BGPバッジ群
    as_group_rects_str, as_group_labels_str = _svg_bgp_as_groups_split(
        bgp_devices, positions_bgp, node_sizes=bgp_node_sizes
    )
    bgp_lines_str, bgp_badges_str = _svg_bgp_edges_split(
        bgp_entries, interfaces, positions_bgp,
        chip_positions=all_chip_positions,
    )
    # B4: 外部ピアへのエッジ
    ext_edges_str = _svg_bgp_external_edges(
        bgp_entries, interfaces, positions_bgp, ext_positions,
        chip_positions=all_chip_positions,
    )
    nodes_str = _svg_nodes(
        bgp_devices, positions_bgp, iface_by_device,
        chip_iface_ids=bgp_chip_ids,
        router_id_field="bgp_router_id",  # Phase 4: BGP ビューは bgp_router_id を表示
    )
    # B4: 外部ピアノード（最前面: ノードの上に重ならないよう最後に描画）
    ext_nodes_str = _svg_bgp_external_nodes(
        bgp_entries, interfaces, ext_positions
    )

    # bbox は内部ノード + 外部ノードを含めて計算
    all_positions_for_bbox = dict(positions_bgp)
    all_positions_for_bbox.update(ext_positions)
    bbox = _make_bbox_str(all_positions_for_bbox)

    # 描画順（背面→前面）:
    #   AS枠rect群 → BGPエッジ線 → 外部エッジ線 → device-nodes → 外部nodes
    #   → AS番号ラベル群 → BGPバッジ群
    inner = "\n".join(filter(None, [
        as_group_rects_str,
        bgp_lines_str,
        ext_edges_str,
        nodes_str,
        ext_nodes_str,
        as_group_labels_str,
        bgp_badges_str,
    ]))
    return (
        f'<g class="view view-bgp" id="view-bgp" data-bbox="{bbox}" style="display:none">\n'
        f'{inner}\n'
        f'</g>'
    )


def _build_ospf_chip_iface_ids(
    links: list[dict],
    segments: list[dict],
    interfaces: list[dict],
    ospf_device_ids: set[str],
) -> set[str]:
    """OSPF ビュー用チップ集合を返す（リンク端点 IF + セグメントメンバー）。

    - OSPF p2p リンクの a_if / b_if（ospf_area 付き or 両端 OSPF 参加）
    - OSPF セグメントのメンバー iface_id
    interfaces から (device, name) -> iface_id を解決する。
    決定的。
    """
    name_to_id = {(i["device"], i["name"]): i["id"] for i in interfaces}
    result: set[str] = set()

    # p2p リンク端点（ospf_area があるか両端が OSPF 参加のリンク）
    for lk in links:
        is_ospf_link = (
            lk.get("ospf_area") is not None or
            (lk["a_device"] in ospf_device_ids and lk["b_device"] in ospf_device_ids)
        )
        if is_ospf_link:
            a_if = lk.get("a_if") or ""
            b_if = lk.get("b_if") or ""
            if a_if:
                iid = name_to_id.get((lk["a_device"], a_if))
                if iid:
                    result.add(iid)
            if b_if:
                iid = name_to_id.get((lk["b_device"], b_if))
                if iid:
                    result.add(iid)

    # セグメントメンバー
    for seg in segments:
        if seg.get("ospf_area") is not None:
            for member_iface_id in seg.get("members", []):
                result.add(member_iface_id)

    return result


def _build_view_ospf(
    devices: list[dict],
    ospf_entries: list[dict],
    links: list[dict],
    iface_by_device: dict[str, list[dict]],
    segments: list[dict] | None = None,
    interfaces: list[dict] | None = None,
) -> str:
    """OSPF ビュー SVG コンテンツを生成する。

    OSPF 参加リンクのエッジ中点に「area {area} · {subnet}」を常時 <text> 表示する。
    ospf_area が付いているリンクは area ラベルを表示。
    ospf_area が欠如しているリンクはサブネットのみ表示（後方互換）。
    両端で area が異なる場合（例 "0/1"）はそのまま表示。

    OSPF 参加セグメント（ospf_area 付き）を楕円ノードとして描画し、
    メンバー機器へ seg-edge を引き「area {area} · {subnet}」ラベルを表示する。

    iteration-4 #6: OSPF 参加 IF のみチップ表示、エッジ端点をチップにアンカー。

    ⑬: p2p link-edge <g> に端点 iface_id を ``data-a-iface`` / ``data-b-iface`` として
    付与する（Physical _svg_links と同型）。選択時の端点 IF チップ点灯
    （template.py ``_updateEdgeHighlightForSelection`` ospf 分岐）が
    ``.if-chip[data-iface-id]`` と照合するために使用する。
    """
    if segments is None:
        segments = []
    if interfaces is None:
        interfaces = []

    positions_ospf, ospf_devices, ospf_segments = _build_ospf_layout(
        devices, ospf_entries, links, segments, interfaces
    )

    # OSPF 参加デバイス集合
    ospf_device_ids: set[str] = set(d["id"] for d in ospf_devices)

    # OSPF チップ集合（p2p リンク端点 + セグメントメンバー）
    ospf_chip_ids = _build_ospf_chip_iface_ids(
        links, segments, interfaces, ospf_device_ids
    )

    # チップ座標マップを構築（OSPF 参加デバイス分）
    all_chip_positions: dict[str, tuple[float, float]] = {}
    for dev in ospf_devices:
        dev_pos = positions_ospf.get(dev["id"])
        if dev_pos is None:
            continue
        dev_ifaces = iface_by_device.get(dev["id"], [])
        dev_chip_ids = {i["id"] for i in dev_ifaces if i["id"] in ospf_chip_ids}
        if dev_chip_ids:
            cp = _chip_positions(dev, dev_chip_ids, dev_ifaces, dev_pos[0], dev_pos[1])
            all_chip_positions.update(cp)

    # name_to_iface_id マップ（OSPF p2p リンクのチップアンカー用）
    name_to_iface_id = {(i["device"], i["name"]): i["id"] for i in interfaces}

    # OSPF エッジ（同一リンクの両端が OSPF 参加）— チップアンカー対応
    # Phase 3H: 同一 link_id の v4/v6 エントリを1エッジに統合（dual-stack 重複防止）
    # OSPF 参加リンクのみ抽出
    ospf_links = [
        lk for lk in links
        if lk["a_device"] in ospf_device_ids and lk["b_device"] in ospf_device_ids
    ]
    # 同一 IF ペアを統合（v4/v6 → 1エントリ、subnets リストに両方を格納）
    merged_ospf_links = _merge_links_by_link_id(ospf_links)

    parts = []
    label_parts: list[str] = []  # z-order 修正 (#3-OSPF): ラベル群を別途収集
    for lk in sorted(merged_ospf_links, key=lambda l: (l.get("a_device", ""), l.get("b_device", ""))):
        # チップアンカー
        a_pos = positions_ospf.get(lk["a_device"], (0.0, 0.0))
        b_pos = positions_ospf.get(lk["b_device"], (0.0, 0.0))
        a_if = lk.get("a_if") or ""
        b_if = lk.get("b_if") or ""
        # ⑬: 端点 IF チップ点灯用に iface_id を保持（Physical _svg_links と同型）。
        # チップは all_chip_positions がある時のみ描画されるため、その場合のみ解決する。
        a_iface_id: str | None = None
        b_iface_id: str | None = None
        if all_chip_positions:
            a_iface_id = name_to_iface_id.get((lk["a_device"], a_if))
            b_iface_id = name_to_iface_id.get((lk["b_device"], b_if))
            if a_iface_id and a_iface_id in all_chip_positions:
                a_pos = all_chip_positions[a_iface_id]
            if b_iface_id and b_iface_id in all_chip_positions:
                b_pos = all_chip_positions[b_iface_id]
        x1, y1 = a_pos
        x2, y2 = b_pos

        # 統合エントリの全 subnet を取得（物理接続の line 描画・data-subnet に使用）
        subnets = lk.get("subnets") or [lk.get("subnet", "")]
        primary_subnet_raw = subnets[0] if subnets else lk.get("subnet", "")
        primary_subnet = _esc(primary_subnet_raw)

        ospf_area = lk.get("ospf_area")

        # ospf_subnets: OSPF 参加 subnet のみ（_merge_links_by_link_id で計算済み）
        # フォールバック: キー欠如（旧形式データ）のみ subnets を使用。
        # 空リスト（[]）は OSPF 非参加を意味するためそのまま維持する。
        # _merge_links_by_link_id は常に ospf_subnets を書き込むため is None は旧形式のみ。
        ospf_subnets = lk.get("ospf_subnets")
        if ospf_subnets is None:          # 旧形式データのみフォールバック
            ospf_subnets = subnets

        # data-ospf-id は OSPF 参加 subnet のみを空白区切りで列挙（双方向連動）
        # ospf_subnets を個別に _normalize_subnet() で正規化する。
        ospf_ids = [
            _normalize_subnet(s)
            for s in ospf_subnets
        ]
        ospf_ids = sorted(set(oid for oid in ospf_ids if oid))  # 決定的・重複除去
        if ospf_ids:
            ospf_id_attr = f' data-ospf-id="{_esc(" ".join(ospf_ids))}"'
        else:
            ospf_id_attr = ""

        # リンク中点
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2 - 15

        if ospf_area is not None:
            # #7: area を必ず独立 tspan 行にする。
            # 1行目: "area {area}"
            # 2行目以降: ospf_subnets の各 subnet を1つずつ別 tspan 行（v4→v6 の決定的順）
            # single-stack(subnet1個) → 2行（area / subnet）
            # dual-stack(2個) → 3行（area / v4 / v6）
            area_tspan = f'<tspan x="{mx:.1f}" dy="0">{_esc("area " + str(ospf_area))}</tspan>'
            if ospf_subnets:
                # v4→v6 の決定的順（":" なし → v4, ":" あり → v6）
                v4_subs = [s for s in ospf_subnets if s and ":" not in s]
                v6_subs = [s for s in ospf_subnets if s and ":" in s]
                ordered_subnets = v4_subs + v6_subs
                subnet_tspans = "".join(
                    f'<tspan x="{mx:.1f}" dy="14">{_esc(s)}</tspan>'
                    for s in ordered_subnets
                )
                _lines_ospf = ["area " + str(ospf_area)] + ordered_subnets
            else:
                # ospf_subnets が空: primary_subnet をフォールバック
                subnet_tspans = f'<tspan x="{mx:.1f}" dy="14">{primary_subnet}</tspan>'
                _lines_ospf = ["area " + str(ospf_area), primary_subnet_raw]
            _bg_ospf = _svg_label_bg_rect(_lines_ospf, cx=mx, first_baseline_y=my)
            label_elem = (
                f'{_bg_ospf}'
                f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" '
                f'class="link-label layer-ospf">'
                f'{area_tspan}'
                f'{subnet_tspans}'
                f'</text>'
            )
        else:
            # ospf_area 欠如: subnet のみ表示（後方互換）
            _bg_ospf = _svg_label_bg_rect([primary_subnet_raw], cx=mx, first_baseline_y=my)
            label_elem = (
                f'{_bg_ospf}'
                f'<text x="{mx:.1f}" y="{my:.1f}" text-anchor="middle" '
                f'class="link-label layer-ospf">{primary_subnet}</text>'
            )

        # z-order 修正 (#3-OSPF): 線とラベルを分離して収集する
        # TM-3: link-edge（線側）に data-link-id を付与（Interfaces 表行連動用）
        link_id_attr = ""
        a_if_raw = lk.get("a_if") or ""
        b_if_raw = lk.get("b_if") or ""
        if a_if_raw and b_if_raw:
            lid = _esc(_make_link_id(lk["a_device"], a_if_raw, lk["b_device"], b_if_raw))
            link_id_attr = f' data-link-id="{lid}"'
        # OSPF Area 色分け: data-ospf-area 属性と --area-stroke CSS カスタムプロパティ
        ospf_area_attr = f' data-ospf-area="{_esc(str(ospf_area))}"' if ospf_area is not None else ""
        area_color = _ospf_area_color(ospf_area)
        link_line_style = f' style="--area-stroke:{area_color}"' if area_color else ""
        # ⑬: IF チップ端点属性（iface_id が判明した端点のみ付与。Physical _svg_links と同型）
        iface_attrs = ""
        if a_iface_id:
            iface_attrs += f' data-a-iface="{_esc(a_iface_id)}"'
        if b_iface_id:
            iface_attrs += f' data-b-iface="{_esc(b_iface_id)}"'
        parts.append(
            f'<g class="link-edge" data-subnet="{primary_subnet}" '
            f'data-a="{_esc(lk["a_device"])}" data-b="{_esc(lk["b_device"])}"'
            f'{ospf_id_attr}{link_id_attr}{ospf_area_attr}{iface_attrs}>'
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'class="link-line layer-ospf"{link_line_style}/>'
            f'</g>'
        )
        # data-ospf-id はラベル側には不要: JS の表連動は .link-edge[data-ospf-id] のみ参照。
        # ラベル側に付けると [data-ospf-id].highlighted のクリア対象が二重になるが機能への影響は
        # 軽微であり、主に整合性のため除去する。data-ospf-id は線側 link-edge にのみ保持。
        label_parts.append(
            f'<g class="link-label-group" data-subnet="{primary_subnet}" '
            f'data-a="{_esc(lk["a_device"])}" data-b="{_esc(lk["b_device"])}"'
            f'{link_id_attr}>'
            f'{label_elem}'
            f'</g>'
        )
    edge_lines_str = "\n".join(parts)
    edge_labels_str = "\n".join(label_parts)

    # OSPF 参加セグメント描画（チップアンカー対応）
    ospf_seg_edges_str = _svg_ospf_segment_edges(
        ospf_segments, interfaces, positions_ospf,
        chip_positions=all_chip_positions,
    )
    ospf_segs_str = _svg_ospf_segments(ospf_segments, positions_ospf)

    nodes_str = _svg_nodes(
        ospf_devices, positions_ospf, iface_by_device,
        chip_iface_ids=ospf_chip_ids,
        router_id_field="ospf_router_id",  # Phase 4: OSPF ビューは ospf_router_id を表示
    )
    bbox = _make_bbox_str(positions_ospf)
    # 描画順（背面→前面）:
    #   ospf-seg-edges → p2pリンク線 → segments → device-nodes → リンクラベル群
    inner = "\n".join(filter(None, [
        ospf_seg_edges_str, edge_lines_str, ospf_segs_str, nodes_str, edge_labels_str
    ]))
    return (
        f'<g class="view view-ospf" id="view-ospf" data-bbox="{bbox}" style="display:none">\n'
        f'{inner}\n'
        f'</g>'
    )


def _build_view_generic(
    view_id: str,
    devices: list[dict],
    proto_entries: list[dict],
    links: list[dict],
    iface_by_device: dict[str, list[dict]],
) -> str:
    """汎用プロトコルビュー SVG コンテンツを生成する（bgp/ospf 以外）"""
    positions, proto_devices = _build_generic_proto_layout(devices, proto_entries, links)

    proto_device_ids: set[str] = set(d["id"] for d in proto_devices)
    parts = []
    for lk in sorted(links, key=lambda l: (l["a_device"], l["b_device"])):
        if lk["a_device"] in proto_device_ids and lk["b_device"] in proto_device_ids:
            x1, y1 = positions.get(lk["a_device"], (0, 0))
            x2, y2 = positions.get(lk["b_device"], (0, 0))
            subnet = _esc(lk["subnet"])
            safe_id = _esc(view_id)
            parts.append(
                f'<g class="link-edge" data-subnet="{subnet}" '
                f'data-a="{_esc(lk["a_device"])}" data-b="{_esc(lk["b_device"])}">'
                f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                f'class="link-line layer-{safe_id}"/>'
                f'<title>{subnet}</title>'
                f'</g>'
            )
    edges_str = "\n".join(parts)
    nodes_str = _svg_nodes(proto_devices, positions, iface_by_device)
    bbox = _make_bbox_str(positions)
    inner = "\n".join(filter(None, [edges_str, nodes_str]))
    return (
        f'<g class="view view-{_esc(view_id)}" id="view-{_esc(view_id)}" data-bbox="{bbox}" style="display:none">\n'
        f'{inner}\n'
        f'</g>'
    )


def _build_view_tabs(view_ids: list[str]) -> str:
    """ビュー切替タブ HTML を生成する"""
    labels = {
        "physical": "Physical",
        "bgp": "BGP",
        "ospf": "OSPF",
    }
    tabs = []
    for vid in view_ids:
        label = labels.get(vid, vid.upper())
        active = ' class="view-tab active"' if vid == "physical" else ' class="view-tab"'
        tabs.append(
            f'<button{active} data-view="{_esc(vid)}" '
            f'onclick="selectView(this.dataset.view)">{_esc(label)}</button>'
        )
    return "\n".join(tabs)

