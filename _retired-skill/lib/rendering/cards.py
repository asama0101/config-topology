"""
rendering/cards.py — 機器カード HTML 生成モジュール
"""
from __future__ import annotations

from lib.rendering.svg import _esc, _format_iface_ip_cell


def _get_display_ip(iface: dict) -> str:
    """IF の表示用 IP 文字列を返す（内部テキスト・SVG title 用途）。

    HTML セル表示には _format_iface_ip_cell（svg.py）を使うこと。
    本関数は <br> を含まない生テキストを返す。

    dual-stack（ip フィールド + addresses に v6 GUA あり）の場合、
    v4 アドレスと v6 アドレスを '\\n' で結合して返す。
    v6-only IF（ip=None かつ addresses に v6 GUA あり）の場合、
    addresses の先頭 v6 GUA（link-local 除く）を "ip/prefix" 形式で返す。
    それ以外は iface["ip"] または "" を返す（後方互換）。

    Args:
        iface: インタフェース辞書

    Returns:
        表示用 IP 文字列（single: "a.b.c.d/prefix" / dual: "v4\\nv6" / v6-only: "addr::/prefix" / ""）
    """
    ip_val = iface.get("ip") or ""
    addresses = iface.get("addresses") or []

    # dual-stack 判定: ip フィールド（v4）があり、かつ addresses に v6 GUA がある
    if ip_val:
        v6_gua = ""
        for addr in addresses:
            if addr.get("af") != "v6":
                continue
            if addr.get("scope") == "link-local":
                continue
            v6_ip = addr.get("ip", "")
            v6_prefix = addr.get("prefix")
            if not v6_ip:
                continue
            v6_gua = f"{v6_ip}/{v6_prefix}" if v6_prefix is not None else v6_ip
            break
        if v6_gua:
            return f"{ip_val}\n{v6_gua}"
        return ip_val

    # ip が None/空: addresses から先頭 v6 GUA を取得
    for addr in addresses:
        if addr.get("af") != "v6":
            continue
        if addr.get("scope") == "link-local":
            continue
        ip_str = addr.get("ip", "")
        prefix = addr.get("prefix")
        if not ip_str:
            continue
        if prefix is not None:
            return f"{ip_str}/{prefix}"
        return ip_str

    return ""


def _device_cards(
    devices: list[dict],
    interfaces: list[dict],
    routing: dict,
    iface_link_id: dict[str, str] | None = None,
    iface_seg_id: dict[str, str] | None = None,
    static_route_map: dict[tuple[str, str], dict] | None = None,
    bgp_session_map: dict[tuple[str, str], str] | None = None,
    ospf_marking_map: dict[tuple[str, str], str] | None = None,
    bgp_source_iface_map: dict[tuple[str, str], str] | None = None,
    static_loopback_map: dict[tuple[str, str], str] | None = None,
) -> str:
    """機器ごとのカード HTML を生成する（図の下に表示）

    Args:
        devices:               デバイスリスト
        interfaces:            インタフェースリスト
        routing:               ルーティング dict
        iface_link_id:         ``{iface_id: link_id}`` マップ。
                               リンク端点の IF 行 <tr> に ``data-link-id`` を付与するために使用する。
                               None の場合は付与しない（後方互換）。
        iface_seg_id:          ``{iface_id: seg_id}`` マップ（#7）。
                               セグメントメンバーの IF 行 <tr> に ``data-seg-id`` を付与する。
        static_route_map:      ``{(device, prefix): {route_edge_id, nexthop_device_id}}`` マップ（#2/#6）。
                               static 行に ``data-route-edge`` / ``data-route-nexthop-device`` を付与する。
        bgp_session_map:       ``{(device, neighbor_ip): bgp_id}`` マップ（#5）。
                               BGP Sessions 行に ``data-bgp-id`` を付与する。
        ospf_marking_map:      ``{(device, network): ospf_id}`` マップ（#1B）。
                               OSPF Networks 行に ``data-ospf-id`` を付与する。
        bgp_source_iface_map:  ``{(device, neighbor_ip): source_iface_id}`` マップ。
                               BGP Sessions 行に ``data-iface-id`` を付与する（eBGP/iBGP 共通）。
                               IF チップとの双方向ハイライト連動に使用する。
                               None の場合は付与しない（後方互換）。
        static_loopback_map:   ``{(device, prefix): loopback_iface_id}`` マップ（A3）。
                               static /32 行に ``data-loopback-iface-id`` を付与する（宛先 Loopback 連動）。
                               None の場合は付与しない（後方互換）。
    """
    if iface_link_id is None:
        iface_link_id = {}
    if iface_seg_id is None:
        iface_seg_id = {}
    if static_route_map is None:
        static_route_map = {}
    if bgp_session_map is None:
        bgp_session_map = {}
    if ospf_marking_map is None:
        ospf_marking_map = {}
    if bgp_source_iface_map is None:
        bgp_source_iface_map = {}
    if static_loopback_map is None:
        static_loopback_map = {}

    # device_id -> interfaces マップ
    iface_by_device: dict[str, list[dict]] = {}
    for iface in interfaces:
        dev_id = iface["device"]
        iface_by_device.setdefault(dev_id, []).append(iface)

    # routing サマリー
    bgp_by_device: dict[str, list[dict]] = {}
    for entry in routing.get("bgp", []):
        bgp_by_device.setdefault(entry["device"], []).append(entry)

    ospf_by_device: dict[str, list[dict]] = {}
    for entry in routing.get("ospf", []):
        ospf_by_device.setdefault(entry["device"], []).append(entry)

    static_by_device: dict[str, list[dict]] = {}
    for entry in routing.get("static", []):
        static_by_device.setdefault(entry["device"], []).append(entry)

    cards = []
    for dev in sorted(devices, key=lambda d: d["id"]):
        dev_id = dev["id"]
        hostname = _esc(dev["hostname"])
        vendor = _esc(dev.get("vendor", ""))
        as_num = dev.get("as")
        as_str = f"AS{_esc(as_num)}" if as_num is not None else "—"

        # IF テーブル
        if_row_parts = []
        for iface in sorted(iface_by_device.get(dev_id, []), key=lambda i: i["name"]):
            shutdown_mark = " (shutdown)" if iface.get("shutdown") else ""
            # リンク端点の IF には data-link-id を付与する（Phase D）
            lid = iface_link_id.get(iface["id"], "")
            # セグメントメンバーの IF には data-seg-id を付与する（#7）
            sid = iface_seg_id.get(iface["id"], "")
            tr_attrs = ""
            if lid:
                tr_attrs += f' data-link-id="{_esc(lid)}"'
            if sid:
                tr_attrs += f' data-seg-id="{_esc(sid)}"'
            # Interfaces テーブルの表示列: Status / MTU / Speed
            # duplex / switchport / encapsulation / l2_l3 は YAML に保持するが表示対象外
            admin_status = iface.get("admin_status", "")
            mtu_val = iface.get("mtu")
            mtu_str = str(mtu_val) if mtu_val is not None else ""
            speed_val = iface.get("speed", "")
            # A6a: dual-stack IF の IP セルは _format_iface_ip_cell で <br> 区切り表示
            ip_cell = _format_iface_ip_cell(iface)
            if_row_parts.append(
                f"<tr{tr_attrs}>"
                f"<td>{_esc(iface['name'])}{_esc(shutdown_mark)}</td>"
                f"<td>{ip_cell}</td>"
                f"<td>{_esc(iface.get('description', ''))}</td>"
                f"<td>{_esc(admin_status)}</td>"
                f"<td>{_esc(mtu_str)}</td>"
                f"<td>{_esc(speed_val)}</td>"
                f"</tr>"
            )
        if_rows = "".join(if_row_parts)

        # BGP サマリー（#5: data-bgp-id 付与、IF 連動: data-iface-id 付与）
        bgp_row_parts = []
        for b in bgp_by_device.get(dev_id, []):
            neighbor_ip = b.get("neighbor_ip", "")
            bgp_id = bgp_session_map.get((dev_id, neighbor_ip), "")
            tr_bgp_attrs = f' data-bgp-id="{_esc(bgp_id)}"' if bgp_id else ""
            # IF 連動: source iface_id を解決して data-iface-id を付与（eBGP/iBGP 共通）
            src_iface_id = bgp_source_iface_map.get((dev_id, neighbor_ip), "")
            if src_iface_id:
                tr_bgp_attrs += f' data-iface-id="{_esc(src_iface_id)}"'
            bgp_row_parts.append(
                f"<tr{tr_bgp_attrs}>"
                f"<td>{_esc(neighbor_ip)}</td>"
                f"<td>{_esc(b.get('peer_as', ''))}</td>"
                f"<td>{_esc(b.get('type', ''))}</td>"
                f"</tr>"
            )
        bgp_rows = "".join(bgp_row_parts)

        # OSPF サマリー（#1B: data-ospf-id 付与）
        ospf_row_parts = []
        for o in ospf_by_device.get(dev_id, []):
            network = o.get("network", "")
            ospf_id = ospf_marking_map.get((dev_id, network), "")
            tr_ospf_attrs = f' data-ospf-id="{_esc(ospf_id)}"' if ospf_id else ""
            pid = o.get("process")
            pid_disp = pid if pid not in (None, "") else "—"
            ospf_row_parts.append(
                f"<tr{tr_ospf_attrs}>"
                f"<td>{_esc(network)}</td>"
                f"<td>Area {_esc(o.get('area', ''))}</td>"
                f"<td>PID {_esc(pid_disp)}</td>"
                f"</tr>"
            )
        ospf_rows = "".join(ospf_row_parts)

        # static サマリー（#2/#6: data-route-id で1行特定・data-route-edge / data-route-nexthop-device 付与）
        static_row_parts = []
        for idx, s in enumerate(static_by_device.get(dev_id, [])):
            prefix = s.get("prefix", "")
            next_hop = s.get("next_hop", "")
            route_info = static_route_map.get((dev_id, prefix), {})
            route_edge_id = route_info.get("route_edge_id") or ""
            nexthop_device_id = route_info.get("nexthop_device_id") or ""
            # #2: 行ごと一意 ID（"{device}::{prefix}::{idx}" 形式。同 prefix ECMP でも衝突しない）
            route_id = f"{dev_id}::{prefix}::{idx}"
            tr_attrs = f' data-route-id="{_esc(route_id)}"'
            if route_edge_id:
                tr_attrs += f' data-route-edge="{_esc(route_edge_id)}"'
            if nexthop_device_id:
                tr_attrs += f' data-route-nexthop-device="{_esc(nexthop_device_id)}"'
            # A3: static /32 行に宛先 Loopback iface-id を付与（解決できた場合のみ）
            static_lb_iface_id = static_loopback_map.get((dev_id, prefix), "")
            if static_lb_iface_id:
                tr_attrs += f' data-loopback-iface-id="{_esc(static_lb_iface_id)}"'
            static_row_parts.append(
                f"<tr{tr_attrs}>"
                f"<td>{_esc(prefix)}</td>"
                f"<td>{_esc(next_hop)}</td>"
                f"</tr>"
            )
        static_rows = "".join(static_row_parts)

        # sections 汎用テーブル
        section_parts = []
        for sec in dev.get("sections", []):
            sec_title = _esc(sec.get("title", ""))
            sec_row_parts = []
            for row in sec.get("rows", []):
                cells = "".join(f"<td>{_esc(c)}</td>" for c in row)
                sec_row_parts.append(f"<tr>{cells}</tr>")
            sec_rows = "".join(sec_row_parts)
            section_parts.append(
                f"<h4>{sec_title}</h4>"
                f"<table class='section-table'><tbody>{sec_rows}</tbody></table>"
            )
        section_html = "".join(section_parts)

        # Phase 4 (router-id): OSPF/BGP 両方の router-id をヘッダーに表示（無い場合は非表示）
        ospf_rid = dev.get("ospf_router_id")
        bgp_rid = dev.get("bgp_router_id")
        rid_badges = ""
        if ospf_rid:
            rid_badges += f' <span class="badge-rid badge-rid-ospf">OSPF RID: {_esc(ospf_rid)}</span>'
        if bgp_rid:
            rid_badges += f' <span class="badge-rid badge-rid-bgp">BGP RID: {_esc(bgp_rid)}</span>'

        card = f"""
<div class="device-card" data-device="{_esc(dev_id)}">
  <h3>{hostname} <span class="badge-vendor">{vendor}</span> <span class="badge-as">{as_str}</span>{rid_badges}</h3>
  <h4 class="layer-physical">Interfaces</h4>
  <table class="layer-physical">
    <thead><tr><th>Name</th><th>IP</th><th>Description</th><th>Status</th><th>MTU</th><th>Speed</th></tr></thead>
    <tbody>{if_rows}</tbody>
  </table>
  {f'''<h4 class="layer-bgp">BGP Sessions</h4>
  <table class="layer-bgp">
    <thead><tr><th>Neighbor</th><th>Peer AS</th><th>Type</th></tr></thead>
    <tbody>{bgp_rows}</tbody>
  </table>''' if bgp_rows else ''}
  {f'''<h4 class="layer-ospf">OSPF Networks</h4>
  <table class="layer-ospf">
    <thead><tr><th>Network</th><th>Area</th><th>Process</th></tr></thead>
    <tbody>{ospf_rows}</tbody>
  </table>''' if ospf_rows else ''}
  {f'''<h4 class="layer-static">Static Routes</h4>
  <table class="layer-static">
    <thead><tr><th>Prefix</th><th>Next Hop</th></tr></thead>
    <tbody>{static_rows}</tbody>
  </table>''' if static_rows else ''}
  {section_html}
</div>"""
        cards.append(card)

    return "\n".join(cards)
