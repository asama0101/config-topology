"""正規化 Device 群 → topology dict（要件書 §5・§7）。"""
import ipaddress

from .idgen import assign_device_ids, interface_id, segment_id

DEFAULT_TITLE = "Network Topology (config-derived)"


def build_devices_interfaces(parsed):
    """parsed(appearance 順) → (device_ids, devices[id昇順], interfaces[出現順×config順])。"""
    device_ids = assign_device_ids(parsed)
    devices, interfaces = [], []
    for dev_id, dev in zip(device_ids, parsed):
        devices.append({
            "id": dev_id, "hostname": dev.hostname, "vendor": dev.vendor,
            "as": dev.as_, "ospf_router_id": dev.ospf_router_id,
            "bgp_router_id": dev.bgp_router_id, "sections": [],
        })
        for itf in dev.interfaces:                       # config 記述順を保持
            itf_dict = {
                "id": interface_id(dev_id, itf.name), "device": dev_id, "name": itf.name,
                "ip": itf.derived_ip(), "vlan": itf.vlan, "description": itf.description,
                "shutdown": itf.shutdown, "admin_status": itf.admin_status,
                "oper_status": itf.oper_status, "mtu": itf.mtu, "speed": itf.speed,
                "duplex": itf.duplex, "l2_l3": itf.l2_l3, "switchport": itf.switchport,
                "encapsulation": itf.encapsulation, "source": "parsed",
                "addresses": [a.to_dict() for a in itf.sorted_addresses()],
            }
            # ospf は値があるときのみ出力。None も空 dict {} も省略してゴールデン YAML の byte 不変を保つ
            # （他 None フィールドとの意図的な非対称。requirements.md §5.2 の例外）
            if itf.ospf:
                itf_dict["ospf"] = itf.ospf
            interfaces.append(itf_dict)
    devices_sorted = sorted(devices, key=lambda d: d["id"])   # 出力は id 昇順（§7.5）
    return device_ids, devices_sorted, interfaces


def _iface_subnets(itf):
    """IF の addresses から所属ネットワーク CIDR 集合（link-local 除外・重複除去）を返す。

    §7.1 step1 の「addresses 空なら ip にフォールバック」は本パイプラインでは不要のため未実装:
    interfaces dict は正規化モデル由来で addresses が正本・ip はその派生（addresses==[] ⟺ ip is None）。
    """
    nets = []
    seen = set()
    for a in itf["addresses"]:
        if a["af"] == "v6" and a.get("scope") == "link-local":
            continue
        net = ipaddress.ip_network("%s/%s" % (a["ip"], a["prefix"]), strict=False)
        cidr = "%s/%s" % (net.network_address, net.prefixlen)
        if cidr not in seen:
            seen.add(cidr)
            nets.append(cidr)
    return nets


def infer_links_segments(interfaces):
    """サブネット一致で links/segments を推論（§7.1）＋ admin_down 付与（§7.2）。"""
    groups = {}   # cidr -> [iface dict, ...]（同一 IF は 1 回）
    for itf in interfaces:
        for cidr in _iface_subnets(itf):
            groups.setdefault(cidr, []).append(itf)

    links, segments = [], []
    for cidr, members in groups.items():
        if len(members) == 2 and members[0]["device"] != members[1]["device"]:
            a, b = members
            if (b["device"], b["name"]) < (a["device"], a["name"]):
                a, b = b, a                             # a_device<b_device で安定化
            link = {"a_device": a["device"], "a_if": a["name"],
                    "b_device": b["device"], "b_if": b["name"],
                    "subnet": cidr, "kind": "inferred-subnet"}
            if a["shutdown"] or b["shutdown"]:          # §7.2 片端/両端 shutdown → true
                link["admin_down"] = True
            links.append(link)
        elif len(members) >= 3:
            segments.append({"id": segment_id(cidr), "subnet": cidr,
                             "members": sorted(m["id"] for m in members)})
        # len==1、または同一機器 2 メンバー → スタブ/自己ループ（生成しない）
    return links, segments


def _resolve_local_ip(dev, neighbor):
    """neighbor_ip と同一サブネットにある自機 IF の IP（af 一致）を返す。無ければ None（§7.3）。

    サブネット一致が None で neighbor.update_source が設定されている場合にフォールバック:
    - update_source が IP として妥当（ipaddress.ip_address 成功）→ その IP を返す（JunOS local-address）。
      ただし AF が neighbor.af と一致する場合のみ。不一致なら None のまま。
    - そうでなければ（インターフェース名）→ dev.interfaces から name==update_source の IF を探し、
      その IF の neighbor.af 一致アドレス（v6 は link-local 除外）を返す。
      複数あれば config 順で最初。
    既存のサブネット一致ロジックは不変（フォールバックは None のときのみ）。
    """
    try:
        nbip = ipaddress.ip_address(neighbor.neighbor_ip)
    except ValueError:
        return None
    for itf in dev.interfaces:
        for a in itf.addresses:
            if a.af != neighbor.af:
                continue
            if a.af == "v6" and a.scope == "link-local":
                continue
            net = ipaddress.ip_network("%s/%s" % (a.ip, a.prefix), strict=False)
            if nbip in net:
                return a.ip

    # サブネット一致が失敗 → update_source フォールバック
    src = neighbor.update_source
    if src is None:
        return None

    # update_source が IP か判定
    try:
        src_addr = ipaddress.ip_address(src)
        # IP として有効 → AF 一致チェック
        src_af = "v6" if src_addr.version == 6 else "v4"
        if src_af != neighbor.af:
            return None
        # link-local（fe80::/10）は結線推論・サブネット一致ブランチと整合して除外する
        if src_addr.is_link_local:
            return None
        return src
    except ValueError:
        pass

    # IP でなければインターフェース名として解決
    for itf in dev.interfaces:
        if itf.name != src:
            continue
        for a in itf.addresses:
            if a.af != neighbor.af:
                continue
            if a.af == "v6" and a.scope == "link-local":
                continue
            return a.ip
    return None


def _bgp_type(local_as, peer_as):
    if peer_as is None or local_as is None:
        return "unknown"
    if local_as == peer_as:
        return "ibgp"
    return "ebgp"


def build_bgp(id_dev):
    """id_dev: [(device_id, Device)] → routing.bgp エントリ列（§7.3）。

    update_source は値があるときのみ出力（None は省略 → golden byte 不変）。
    route_reflector_client / next_hop_self は True のときのみ出力（False は省略 → golden byte 不変）。
    timers / send_community も同様に omit-when-None で転記（None は省略 → golden byte 不変）。
    peer_group も omit-when-None（None は省略 → golden byte 不変）。所属 peer-group 名を格納。
    """
    out = []
    for dev_id, dev in id_dev:
        for nb in dev.bgp:
            entry = {
                "device": dev_id, "local_as": dev.as_,
                "local_ip": _resolve_local_ip(dev, nb),
                "neighbor_ip": nb.neighbor_ip, "peer_as": nb.peer_as,
                "type": _bgp_type(dev.as_, nb.peer_as), "af": nb.af,
            }
            if nb.update_source is not None:
                entry["update_source"] = nb.update_source
            if nb.route_reflector_client:
                entry["route_reflector_client"] = True
            if nb.next_hop_self:
                entry["next_hop_self"] = True
            if nb.timers is not None:
                entry["timers"] = {"keepalive": nb.timers[0], "holdtime": nb.timers[1]}
            if nb.send_community is not None:
                entry["send_community"] = nb.send_community
            if nb.peer_group is not None:
                entry["peer_group"] = nb.peer_group
            out.append(entry)
    return out


def build_ospf(id_dev):
    """id_dev: [(device_id, Device)] → routing.ospf エントリ列（§5.4）。

    area_type は値があるときのみ出力（None は省略 → golden byte 不変）。
    """
    out = []
    for dev_id, dev in id_dev:
        for o in dev.ospf:
            entry = {"device": dev_id, "process": o.process,
                     "network": o.network, "area": o.area, "af": o.af}
            if o.area_type is not None:
                entry["area_type"] = o.area_type
            out.append(entry)
    return out


def build_static(id_dev):
    """id_dev: [(device_id, Device)] → routing.static エントリ列（§5.4）。"""
    out = []
    for dev_id, dev in id_dev:
        for s in dev.static:
            out.append({"device": dev_id, "prefix": s.prefix,
                        "next_hop": s.next_hop, "af": s.af})
    return out


def build_redistribute(id_dev):
    """id_dev: [(device_id, Device)] → routing.redistribute エントリ列（§C5）。

    metric / route_map は値があるときのみ出力（None は省略 → golden byte 不変）。
    """
    out = []
    for dev_id, dev in id_dev:
        for r in dev.redistribute:
            entry = {"device": dev_id, "into": r.into, "source": r.source}
            if r.metric is not None:
                entry["metric"] = r.metric
            if r.route_map is not None:
                entry["route_map"] = r.route_map
            out.append(entry)
    return out


def aggregate_areas(areas):
    """端点の area を集約（§5.3.1/§7.4）。単一→そのまま、複数→昇順スラッシュ連結。"""
    uniq = sorted(set(areas))
    if len(uniq) == 1:
        return uniq[0]
    if all(a.isdigit() for a in uniq):
        uniq = sorted(uniq, key=int)                 # 全数値 → 数値昇順
    return "/".join(uniq)                            # 非数値混在 → 辞書式（既に sorted）


def annotate_ospf(links, segments, ospf_entries, iface_device_map):
    """link/segment に subnet 一致の OSPF area/network を注釈（§7.4）。admin_down は除外（§7.2）。"""
    by_subnet = {}   # network CIDR -> [(device, area)]
    for o in ospf_entries:
        by_subnet.setdefault(o["network"], []).append((o["device"], o["area"]))

    for link in links:
        if link.get("admin_down"):
            continue
        devs = {link["a_device"], link["b_device"]}
        areas = [area for (d, area) in by_subnet.get(link["subnet"], []) if d in devs]
        if areas:
            link["ospf_area"] = aggregate_areas(areas)
            link["ospf_network"] = link["subnet"]

    for seg in segments:
        devs = {iface_device_map[m] for m in seg["members"]}
        areas = [area for (d, area) in by_subnet.get(seg["subnet"], []) if d in devs]
        if areas:
            seg["ospf_area"] = aggregate_areas(areas)
            seg["ospf_network"] = seg["subnet"]


def build_topology(parsed, generated_from, title=DEFAULT_TITLE, raw_texts=None,
                   parse_statuses=None):
    """正規化 Device 群 → topology dict（§5・§7）。全リストを §7.5 の決定的順序で出力。

    generated_from は順序付きシーケンス（list）であること（set 渡しは決定性を壊す）。
    raw_texts は parsed と並走する生 config テキスト列（省略可）。指定時は device id を
    キーに raw_configs へ写像する（CONFIG ビュー用・原本そのまま保持）。
    parse_statuses は parsed と並走する行ステータス列（各要素は ["parsed"/"ignored"/"unparsed", ...]）。
    指定時は device id をキーに parse_status へ写像する（CONFIG parse 状態モード用）。
    """
    device_ids, devices, interfaces = build_devices_interfaces(parsed)
    id_dev = list(zip(device_ids, parsed))
    # raw_texts / parse_statuses は parsed と 1:1 対応。長さ不一致は zip の暗黙切り捨てで欠損を招くため明示的に弾く
    if raw_texts is not None and len(raw_texts) != len(parsed):
        raise ValueError("raw_texts length (%d) != parsed length (%d)"
                         % (len(raw_texts), len(parsed)))
    if parse_statuses is not None and len(parse_statuses) != len(parsed):
        raise ValueError("parse_statuses length (%d) != parsed length (%d)"
                         % (len(parse_statuses), len(parsed)))
    raw_configs = dict(zip(device_ids, raw_texts)) if raw_texts else {}
    parse_status = dict(zip(device_ids, parse_statuses)) if parse_statuses else {}

    links, segments = infer_links_segments(interfaces)
    bgp = build_bgp(id_dev)
    ospf = build_ospf(id_dev)
    static = build_static(id_dev)
    redistribute = build_redistribute(id_dev)

    iface_device_map = {itf["id"]: itf["device"] for itf in interfaces}
    annotate_ospf(links, segments, ospf, iface_device_map)

    # §7.5 決定的順序
    links.sort(key=lambda l: (l["a_device"], l["a_if"], l["b_device"], l["b_if"], l["subnet"]))
    segments.sort(key=lambda s: s["id"])
    bgp.sort(key=lambda e: (e["device"], e["af"], e["neighbor_ip"]))
    ospf.sort(key=lambda e: (e["device"], e["af"], e["area"], e["network"]))
    static.sort(key=lambda e: (e["device"], e["af"], e["prefix"], e["next_hop"]))
    # redistribute はパース順（config 順）を保持（決定的順序の不変条件に従う）

    return {
        "meta": {"schema_version": "1.0", "title": title,
                 "generated_from": list(generated_from)},
        "devices": devices, "interfaces": interfaces,
        "links": links, "segments": segments,
        "routing": {"bgp": bgp, "ospf": ospf, "static": static, "redistribute": redistribute},
        "raw_configs": raw_configs,
        "parse_status": parse_status,
    }
