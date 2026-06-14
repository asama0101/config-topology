"""topology diff エンジン（要件書 §10 拡張・独立ツール）。

diff_topology(old, new) -> dict
    2 つの topology dict を決定的に比較し、構造化 diff を返す。

format_diff_report(diff, old_label, new_label) -> str
    diff dict を Markdown テキストにフォーマットする（時刻・乱数非依存）。

決定性保証:
  - 全リストはキー昇順でソートして返す。
  - 時刻・乱数に依存しない。
  - old/new の入力 dict を変更しない（読み取り専用）。
"""

# ---------------------------------------------------------------------------
# 内部ヘルパー
# ---------------------------------------------------------------------------

def _section_result(added=None, removed=None, changed=None):
    return {
        "added": added if added is not None else [],
        "removed": removed if removed is not None else [],
        "changed": changed if changed is not None else [],
    }


def _to_first_wins(items, key_fn):
    """list を自然キーで first-wins な dict に変換する。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。
    """
    d = {}
    for e in items:
        d.setdefault(key_fn(e), e)
    return d


def _diff_generic(old_list, new_list, key_fn, compare_fields, entry_summary_fn=None):
    """汎用 added/removed/changed 計算。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。

    Parameters
    ----------
    old_list, new_list : list[dict]
    key_fn             : dict -> comparable key（タプルまたは文字列）
    compare_fields     : list[str]  両側に存在する場合に比較するフィールド名リスト
    entry_summary_fn   : key -> dict  added/removed に入れるサマリ dict（None なら元 dict そのまま）

    Returns
    -------
    dict  {"added": [...], "removed": [...], "changed": [...]}
        各リストはキー昇順ソート済み。
    """
    old_by_key = _to_first_wins(old_list, key_fn)
    new_by_key = _to_first_wins(new_list, key_fn)

    old_keys = set(old_by_key)
    new_keys = set(new_by_key)

    added_keys = sorted(new_keys - old_keys)
    removed_keys = sorted(old_keys - new_keys)
    common_keys = sorted(old_keys & new_keys)

    def _summary(key, entry):
        if entry_summary_fn is not None:
            return entry_summary_fn(key, entry)
        return dict(entry)

    added = [_summary(k, new_by_key[k]) for k in added_keys]
    removed = [_summary(k, old_by_key[k]) for k in removed_keys]

    changed = []
    for k in common_keys:
        old_e = old_by_key[k]
        new_e = new_by_key[k]
        fields = {}
        for f in compare_fields:
            ov = old_e.get(f)
            nv = new_e.get(f)
            if ov != nv:
                fields[f] = [ov, nv]
        if fields:
            changed.append({"key": k, "fields": fields})

    return _section_result(added=added, removed=removed, changed=changed)


# ---------------------------------------------------------------------------
# セクション別 diff 関数
# ---------------------------------------------------------------------------

def _diff_devices(old_devices, new_devices):
    """devices: キー=id、changed フィールド=(hostname,vendor,as,ospf_router_id,bgp_router_id)。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。
    """
    COMPARE = ["hostname", "vendor", "as", "ospf_router_id", "bgp_router_id"]

    def key_fn(d):
        return d["id"]

    old_by_id = _to_first_wins(old_devices, key_fn)
    new_by_id = _to_first_wins(new_devices, key_fn)

    old_ids = set(old_by_id)
    new_ids = set(new_by_id)

    added_ids = sorted(new_ids - old_ids)
    removed_ids = sorted(old_ids - new_ids)
    common_ids = sorted(old_ids & new_ids)

    added = [new_by_id[i] for i in added_ids]
    removed = [old_by_id[i] for i in removed_ids]

    changed = []
    for dev_id in common_ids:
        oe = old_by_id[dev_id]
        ne = new_by_id[dev_id]
        fields = {}
        for f in COMPARE:
            ov, nv = oe.get(f), ne.get(f)
            if ov != nv:
                fields[f] = [ov, nv]
        if fields:
            changed.append({"id": dev_id, "fields": fields})

    return _section_result(added=added, removed=removed, changed=changed)


def _sort_key_for_address(addr):
    """addresses エントリのソートキー: (af, ip, prefix)。"""
    return (addr.get("af", ""), addr.get("ip", ""), addr.get("prefix", 0))


def _diff_interfaces(old_ifaces, new_ifaces):
    """interfaces: キー=id、changed フィールド=(description,shutdown,mtu,speed,addresses,ospf)。

    addresses 比較はキー(af,ip,prefix)昇順ソート後に行い、
    順序のみ異なる場合を false-positive として除外する。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。
    """
    COMPARE_SIMPLE = ["description", "shutdown", "mtu", "speed", "ospf"]

    old_by_id = _to_first_wins(old_ifaces, lambda i: i["id"])
    new_by_id = _to_first_wins(new_ifaces, lambda i: i["id"])

    old_ids = set(old_by_id)
    new_ids = set(new_by_id)

    added_ids = sorted(new_ids - old_ids)
    removed_ids = sorted(old_ids - new_ids)
    common_ids = sorted(old_ids & new_ids)

    added = [new_by_id[i] for i in added_ids]
    removed = [old_by_id[i] for i in removed_ids]

    changed = []
    for iface_id in common_ids:
        oe = old_by_id[iface_id]
        ne = new_by_id[iface_id]
        fields = {}
        for f in COMPARE_SIMPLE:
            ov, nv = oe.get(f), ne.get(f)
            if ov != nv:
                fields[f] = [ov, nv]
        # addresses はキーソート後に比較（順序 false-positive 排除）
        ov_addrs = sorted(oe.get("addresses") or [], key=_sort_key_for_address)
        nv_addrs = sorted(ne.get("addresses") or [], key=_sort_key_for_address)
        if ov_addrs != nv_addrs:
            fields["addresses"] = [oe.get("addresses"), ne.get("addresses")]
        if fields:
            changed.append({"id": iface_id, "fields": fields})

    return _section_result(added=added, removed=removed, changed=changed)


def _link_key(ln):
    """links の自然キー: (subnet, a_device, a_if, b_device, b_if)。端点は a<b で安定。"""
    a_dev, a_if = ln["a_device"], ln["a_if"]
    b_dev, b_if = ln["b_device"], ln["b_if"]
    # 端点を (device, if) で辞書順 a<b に正規化
    side_a = (a_dev, a_if)
    side_b = (b_dev, b_if)
    if side_a > side_b:
        side_a, side_b = side_b, side_a
    return (ln["subnet"], side_a[0], side_a[1], side_b[0], side_b[1])


def _link_summary(key, entry):
    """links: subnet と両端 device::if を返す。"""
    subnet, a_dev, a_if, b_dev, b_if = key
    return {
        "subnet": subnet,
        "a_device": a_dev,
        "a_if": a_if,
        "b_device": b_dev,
        "b_if": b_if,
    }


def _diff_links(old_links, new_links):
    """links: キー=(subnet,a_device,a_if,b_device,b_if)、added/removed のみ。

    kind/admin_down/ospf_area の変更は changed として追跡しない（将来拡張）。
    _changed_label も links の changed は空を前提としている。
    将来 changed を追加する場合は assets.py の changedLabel にも links 分岐が必要。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。
    """
    old_by_key = _to_first_wins(old_links, _link_key)
    new_by_key = _to_first_wins(new_links, _link_key)

    old_keys = set(old_by_key)
    new_keys = set(new_by_key)

    added_keys = sorted(new_keys - old_keys)
    removed_keys = sorted(old_keys - new_keys)

    added = [_link_summary(k, new_by_key[k]) for k in added_keys]
    removed = [_link_summary(k, old_by_key[k]) for k in removed_keys]

    return _section_result(added=added, removed=removed, changed=[])


def _diff_segments(old_segs, new_segs):
    """segments: キー=id、changed=members 集合差のみ。

    ospf_area 等の他フィールドは changed として追跡しない（members のみ追跡）。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。
    """
    old_by_id = _to_first_wins(old_segs, lambda s: s["id"])
    new_by_id = _to_first_wins(new_segs, lambda s: s["id"])

    old_ids = set(old_by_id)
    new_ids = set(new_by_id)

    added_ids = sorted(new_ids - old_ids)
    removed_ids = sorted(old_ids - new_ids)
    common_ids = sorted(old_ids & new_ids)

    added = [new_by_id[i] for i in added_ids]
    removed = [old_by_id[i] for i in removed_ids]

    changed = []
    for seg_id in common_ids:
        oe = old_by_id[seg_id]
        ne = new_by_id[seg_id]
        old_members = oe.get("members") or []
        new_members = ne.get("members") or []
        if sorted(old_members) != sorted(new_members):
            changed.append({
                "id": seg_id,
                "fields": {"members": [old_members, new_members]},
            })

    return _section_result(added=added, removed=removed, changed=changed)


def _bgp_key(e):
    """routing.bgp の自然キー: (device, neighbor_ip, af)。"""
    return (e["device"], e["neighbor_ip"], e["af"])


def _diff_routing_bgp(old_bgp, new_bgp):
    """routing.bgp: キー=(device,neighbor_ip,af)、changed=(peer_as,type,local_ip,update_source,
    route_reflector_client,next_hop_self,timers,send_community)。

    local_as は COMPARE に含まれないため changed として追跡しない。
    route_reflector_client / next_hop_self は omit-when-False フィールドのため、
    キー欠如（.get() → None）と True の差異も検出される。
    timers / send_community は omit-when-None フィールドのため、
    キー欠如（.get() → None）と値ありの差異も検出される。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。
    """
    COMPARE = ["peer_as", "type", "local_ip", "update_source",
               "route_reflector_client", "next_hop_self", "timers", "send_community"]

    old_by_key = _to_first_wins(old_bgp, _bgp_key)
    new_by_key = _to_first_wins(new_bgp, _bgp_key)

    old_keys = set(old_by_key)
    new_keys = set(new_by_key)

    added_keys = sorted(new_keys - old_keys)
    removed_keys = sorted(old_keys - new_keys)
    common_keys = sorted(old_keys & new_keys)

    added = [new_by_key[k] for k in added_keys]
    removed = [old_by_key[k] for k in removed_keys]

    changed = []
    for k in common_keys:
        oe = old_by_key[k]
        ne = new_by_key[k]
        fields = {}
        for f in COMPARE:
            ov, nv = oe.get(f), ne.get(f)
            if ov != nv:
                fields[f] = [ov, nv]
        if fields:
            dev, neighbor_ip, af = k
            changed.append({
                "device": dev, "neighbor_ip": neighbor_ip, "af": af,
                "fields": fields,
            })

    return _section_result(added=added, removed=removed, changed=changed)


def _ospf_key(e):
    """routing.ospf の自然キー: (device, network, af)。"""
    return (e["device"], e["network"], e["af"])


def _diff_routing_ospf(old_ospf, new_ospf):
    """routing.ospf: キー=(device,network,af)、changed=(process,area,area_type)。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。
    """
    COMPARE = ["process", "area", "area_type"]

    old_by_key = _to_first_wins(old_ospf, _ospf_key)
    new_by_key = _to_first_wins(new_ospf, _ospf_key)

    old_keys = set(old_by_key)
    new_keys = set(new_by_key)

    added_keys = sorted(new_keys - old_keys)
    removed_keys = sorted(old_keys - new_keys)
    common_keys = sorted(old_keys & new_keys)

    added = [new_by_key[k] for k in added_keys]
    removed = [old_by_key[k] for k in removed_keys]

    changed = []
    for k in common_keys:
        oe = old_by_key[k]
        ne = new_by_key[k]
        fields = {}
        for f in COMPARE:
            ov, nv = oe.get(f), ne.get(f)
            if ov != nv:
                fields[f] = [ov, nv]
        if fields:
            dev, network, af = k
            changed.append({
                "device": dev, "network": network, "af": af,
                "fields": fields,
            })

    return _section_result(added=added, removed=removed, changed=changed)


def _static_key(e):
    """routing.static の自然キー: (device, prefix, af)。"""
    return (e["device"], e["prefix"], e["af"])


def _diff_routing_static(old_static, new_static):
    """routing.static: キー=(device,prefix,af)、changed=(next_hop)。

    自然キーは一意前提（load_topology が通常保証）。重複時は先勝ち。
    """
    COMPARE = ["next_hop"]

    old_by_key = _to_first_wins(old_static, _static_key)
    new_by_key = _to_first_wins(new_static, _static_key)

    old_keys = set(old_by_key)
    new_keys = set(new_by_key)

    added_keys = sorted(new_keys - old_keys)
    removed_keys = sorted(old_keys - new_keys)
    common_keys = sorted(old_keys & new_keys)

    added = [new_by_key[k] for k in added_keys]
    removed = [old_by_key[k] for k in removed_keys]

    changed = []
    for k in common_keys:
        oe = old_by_key[k]
        ne = new_by_key[k]
        fields = {}
        for f in COMPARE:
            ov, nv = oe.get(f), ne.get(f)
            if ov != nv:
                fields[f] = [ov, nv]
        if fields:
            dev, prefix, af = k
            changed.append({
                "device": dev, "prefix": prefix, "af": af,
                "fields": fields,
            })

    return _section_result(added=added, removed=removed, changed=changed)


# ---------------------------------------------------------------------------
# 公開 API
# ---------------------------------------------------------------------------

def diff_topology(old: dict, new: dict) -> dict:
    """2 つの topology dict を決定的に比較し、構造化 diff を返す。

    Parameters
    ----------
    old, new : dict
        load_topology() が返す topology dict（変更しない）。

    Returns
    -------
    dict  セクション別 {"added": [...], "removed": [...], "changed": [...]}
        キー: devices / interfaces / links / segments /
              routing_bgp / routing_ospf / routing_static
        全リストはキー昇順ソート。同一入力時は各リスト空。
    """
    routing_old = old.get("routing") or {}
    routing_new = new.get("routing") or {}

    return {
        "devices": _diff_devices(
            old.get("devices") or [], new.get("devices") or []),
        "interfaces": _diff_interfaces(
            old.get("interfaces") or [], new.get("interfaces") or []),
        "links": _diff_links(
            old.get("links") or [], new.get("links") or []),
        "segments": _diff_segments(
            old.get("segments") or [], new.get("segments") or []),
        "routing_bgp": _diff_routing_bgp(
            routing_old.get("bgp") or [], routing_new.get("bgp") or []),
        "routing_ospf": _diff_routing_ospf(
            routing_old.get("ospf") or [], routing_new.get("ospf") or []),
        "routing_static": _diff_routing_static(
            routing_old.get("static") or [], routing_new.get("static") or []),
    }


# ---------------------------------------------------------------------------
# Markdown レポートフォーマット
# ---------------------------------------------------------------------------

_SECTION_LABELS = {
    "devices": "Devices",
    "interfaces": "Interfaces",
    "links": "Links",
    "segments": "Segments",
    "routing_bgp": "Routing / BGP",
    "routing_ospf": "Routing / OSPF",
    "routing_static": "Routing / Static",
}

_SECTION_ORDER = [
    "devices", "interfaces", "links", "segments",
    "routing_bgp", "routing_ospf", "routing_static",
]


def _entry_label(section, entry):
    """エントリの一行表示ラベルを返す（セクション別）。"""
    if section == "devices":
        return entry.get("id", str(entry))
    if section == "interfaces":
        return entry.get("id", str(entry))
    if section == "links":
        return "%s  %s::%s -- %s::%s" % (
            entry.get("subnet", ""),
            entry.get("a_device", ""), entry.get("a_if", ""),
            entry.get("b_device", ""), entry.get("b_if", ""),
        )
    if section == "segments":
        return entry.get("id", str(entry))
    if section == "routing_bgp":
        return "%s -> %s (%s)" % (
            entry.get("device", ""), entry.get("neighbor_ip", ""), entry.get("af", ""))
    if section == "routing_ospf":
        return "%s network=%s (%s)" % (
            entry.get("device", ""), entry.get("network", ""), entry.get("af", ""))
    if section == "routing_static":
        return "%s prefix=%s (%s)" % (
            entry.get("device", ""), entry.get("prefix", ""), entry.get("af", ""))
    return str(entry)


def _changed_label(section, ch):
    """changed エントリの一行表示ラベルを返す。
    links は changed が空のため本関数では分岐しない（_diff_links 参照）。
    """
    if section == "devices":
        return ch.get("id", str(ch))
    if section == "interfaces":
        return ch.get("id", str(ch))
    if section == "segments":
        return ch.get("id", str(ch))
    if section == "routing_bgp":
        return "%s -> %s (%s)" % (ch.get("device", ""), ch.get("neighbor_ip", ""), ch.get("af", ""))
    if section == "routing_ospf":
        return "%s network=%s (%s)" % (ch.get("device", ""), ch.get("network", ""), ch.get("af", ""))
    if section == "routing_static":
        return "%s prefix=%s (%s)" % (ch.get("device", ""), ch.get("prefix", ""), ch.get("af", ""))
    return str(ch)


def format_diff_report(diff: dict, old_label: str, new_label: str) -> str:
    """diff dict を Markdown テキストにフォーマットして返す。

    時刻・乱数を含まない。ラベル以外の外部情報を入れない。
    差分ゼロなら「差分なし」を明示する。

    Parameters
    ----------
    diff      : diff_topology() の戻り値。
    old_label : old 側の識別ラベル（ディレクトリ名等）。
    new_label : new 側の識別ラベル。

    Returns
    -------
    str  Markdown テキスト（時刻非依存・決定的）。
    """
    lines = []
    lines.append("# Topology Diff Report")
    lines.append("")
    lines.append("- **old**: `%s`" % old_label)
    lines.append("- **new**: `%s`" % new_label)
    lines.append("")

    total_changes = 0
    section_parts = []

    for section in _SECTION_ORDER:
        sec = diff.get(section, _section_result())
        added = sec.get("added", [])
        removed = sec.get("removed", [])
        changed = sec.get("changed", [])
        n_added, n_removed, n_changed = len(added), len(removed), len(changed)
        total_changes += n_added + n_removed + n_changed
        section_parts.append((section, added, removed, changed, n_added, n_removed, n_changed))

    if total_changes == 0:
        lines.append("**差分なし** — old と new は同一です。")
        return "\n".join(lines)

    for section, added, removed, changed, n_added, n_removed, n_changed in section_parts:
        if n_added + n_removed + n_changed == 0:
            continue
        label = _SECTION_LABELS.get(section, section)
        summary = "+%d -%d ~%d" % (n_added, n_removed, n_changed)
        lines.append("## %s  `%s`" % (label, summary))
        lines.append("")
        for e in added:
            lines.append("+ %s" % _entry_label(section, e))
        for e in removed:
            lines.append("- %s" % _entry_label(section, e))
        for ch in changed:
            lbl = _changed_label(section, ch)
            lines.append("~ %s" % lbl)
            for field, (ov, nv) in sorted(ch["fields"].items()):
                lines.append("    %s: %r -> %r" % (field, ov, nv))
        lines.append("")

    return "\n".join(lines)
