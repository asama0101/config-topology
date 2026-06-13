"""topology dict → DATA（JS が消費する形）。pure・決定的。"""
import ipaddress
from collections import defaultdict


def _primary_ip6(addresses):
    for a in addresses:
        if a["af"] == "v6" and a.get("scope") != "link-local":
            return "%s/%s" % (a["ip"], a["prefix"])
    return None


def _build_if(itf):
    return {
        "n": itf["name"], "ip": itf["ip"], "ip6": _primary_ip6(itf["addresses"]),
        "d": itf["description"], "st": itf["admin_status"],
        "mtu": itf["mtu"], "sp": itf["speed"],
        "addrs": itf["addresses"],
        "ospf": itf.get("ospf"),
    }


def build_devices(topo):
    """DATA.devices（id キーのオブジェクト）を構築。ifs は config 順。routing は device 別。"""
    by_dev_if = {}
    for itf in topo["interfaces"]:
        by_dev_if.setdefault(itf["device"], []).append(itf)

    bgp_by_dev, ospf_by_dev, static_by_dev = {}, {}, {}
    for e in topo["routing"].get("bgp", []):
        bgp_by_dev.setdefault(e["device"], []).append(
            {"nb": e["neighbor_ip"], "pas": e["peer_as"], "type": e["type"],
             "af": e["af"], "lip": e["local_ip"], "link": None})
    for e in topo["routing"].get("ospf", []):
        ospf_by_dev.setdefault(e["device"], []).append(
            {"net": e["network"], "area": e["area"], "proc": e["process"]})
    for e in topo["routing"].get("static", []):
        static_by_dev.setdefault(e["device"], []).append(
            {"p": e["prefix"], "nh": e["next_hop"]})

    out = {}
    for d in topo["devices"]:
        out[d["id"]] = {
            "hostname": d["hostname"], "vendor": d["vendor"], "as": d["as"],
            "ospf_rid": d["ospf_router_id"], "bgp_rid": d["bgp_router_id"],
            "ifs": [_build_if(i) for i in by_dev_if.get(d["id"], [])],
            "bgp": bgp_by_dev.get(d["id"], []),
            "ospf": ospf_by_dev.get(d["id"], []),
            "static": static_by_dev.get(d["id"], []),
        }
    return out


def link_id(a_dev, a_if, b_dev, b_if):
    """端点ペアから対称・決定的なリンク id を作る。"""
    ends = sorted(["%s::%s" % (a_dev, a_if), "%s::%s" % (b_dev, b_if)])
    return "lnk:" + "|".join(ends)


def _host_in_subnet(interfaces_index, device, ifname, subnet):
    """device::ifname の addresses から subnet に属するホストアドレス（prefix なし）を返す。"""
    net = ipaddress.ip_network(subnet, strict=False)
    itf = interfaces_index.get("%s::%s" % (device, ifname))
    if not itf:
        return None
    for a in itf["addresses"]:
        try:
            if ipaddress.ip_address(a["ip"]) in net:
                return a["ip"]
        except ValueError:
            continue
    return None


def build_segments(topo):
    """dict segments の members(iface_id) を {dev,ifn,ip} へ解決し DATA.segments を構築（§8.4）。"""
    idx = {i["id"]: i for i in topo["interfaces"]}
    out = []
    for seg in topo["segments"]:
        members = []
        for mid in seg["members"]:
            itf = idx.get(mid)
            if not itf:
                continue
            ip = _host_in_subnet(idx, itf["device"], itf["name"], seg["subnet"])
            members.append({"dev": itf["device"], "ifn": itf["name"], "ip": ip})
        s = {"id": seg["id"], "subnet": seg["subnet"], "members": members}
        if seg.get("ospf_area") is not None:
            s["area"] = seg["ospf_area"]
        out.append(s)
    return out


def build_links(topo):
    """dict links（v4/v6 別行）を端点ペアで 1 本に統合し DATA.links を構築（§8.4）。"""
    idx = {i["id"]: i for i in topo["interfaces"]}
    merged = {}
    order = []
    for ln in topo["links"]:
        lid = link_id(ln["a_device"], ln["a_if"], ln["b_device"], ln["b_if"])
        is_v6 = ipaddress.ip_network(ln["subnet"], strict=False).version == 6
        if lid not in merged:
            merged[lid] = {"id": lid, "a": ln["a_device"], "ai": ln["a_if"],
                           "b": ln["b_device"], "bi": ln["b_if"]}
            order.append(lid)
        m = merged[lid]
        aip = _host_in_subnet(idx, ln["a_device"], ln["a_if"], ln["subnet"])
        bip = _host_in_subnet(idx, ln["b_device"], ln["b_if"], ln["subnet"])
        if is_v6:
            m["dual"] = ln["subnet"]
            m["aip6"], m["bip6"] = aip, bip
            m.setdefault("subnet", None)
            m.setdefault("aip", None)
            m.setdefault("bip", None)
        else:
            m["subnet"] = ln["subnet"]
            m["aip"], m["bip"] = aip, bip
        if ln.get("admin_down"):
            m["admin_down"] = True
        if ln.get("ospf_area") is not None:
            m["area"] = ln["ospf_area"]
    return [merged[lid] for lid in order]


# ---------------------------------------------------------------------------
# BGP topology helpers (§7.3 / §8.4)
# ---------------------------------------------------------------------------

def _ip_to_device(topo):
    """interfaces の addresses から ip → device の逆引き辞書を構築。"""
    m = {}
    for itf in topo["interfaces"]:
        for a in itf["addresses"]:
            m.setdefault(a["ip"], itf["device"])
    return m


def _ip_owner_if(topo, ip):
    """ip を持つ最初の interface の (device, name) を返す。なければ (None, None)。"""
    for itf in topo["interfaces"]:
        for a in itf["addresses"]:
            if a["ip"] == ip:
                return itf["device"], itf["name"]
    return None, None


def _link_id_for_pair(topo, ip_a, ip_b):
    """ip_a と ip_b が同一物理リンク（subnet 共有）に乗るなら、その link_id を返す。"""
    for ln in topo["links"]:
        net = ipaddress.ip_network(ln["subnet"], strict=False)
        try:
            if ipaddress.ip_address(ip_a) in net and ipaddress.ip_address(ip_b) in net:
                return link_id(ln["a_device"], ln["a_if"], ln["b_device"], ln["b_if"])
        except ValueError:
            continue
    return None


def build_bgp_topology(topo):
    """extPeers / bgpEdges を導出し bgp_rows に edge id を紐付ける（§7.3/§8.4）。

    返り値: {"extPeers":[...], "bgpEdges":[...], "bgp_rows":[{device, nb, link}, ...]}

    分類ロジック:
    - neighbor_ip が ip2dev に存在しない → external（extPeer ノードを生成）
    - 両端 IP が同一物理リンク subnet に属する → over-link
    - 両端は既知デバイスだが共有 subnet なし → loopback（iBGP 典型）

    edge dedup: 同一分類キーのエッジは初出のセッションで生成し、後続セッションは既存 id を参照。
    extPeers はソート済み（neighbor_ip の辞書順）。
    edge_order は routing.bgp のイテレーション順で決定的（入力が決定的なら出力も決定的）。
    """
    ip2dev = _ip_to_device(topo)
    edges: dict = {}
    edge_order: list = []
    ext_peers: dict = {}
    bgp_rows: list = []
    edge_afs: dict = {}

    for e in topo["routing"].get("bgp", []):
        dev = e["device"]
        lip = e["local_ip"]
        nb = e["neighbor_ip"]
        peer_dev = ip2dev.get(nb)

        if peer_dev is None:
            # external: neighbor がトポロジー内のどのデバイスにも属さない
            eid = "be:ext:%s:%s" % (dev, nb)
            if eid not in edges:
                _, srcif = _ip_owner_if(topo, lip) if lip else (None, None)
                edges[eid] = {
                    "id": eid, "kind": "external", "a": dev, "ext": "ext:" + nb,
                    "aip": lip, "bip": nb, "srcIf": srcif,
                    "type": e["type"], "peerAs": e["peer_as"],
                }
                edge_order.append(eid)
            edge_afs.setdefault(eid, set()).add(e.get("af", "v4"))
            ext_peers.setdefault(
                nb,
                {"id": "ext:" + nb, "label": "AS %s" % e["peer_as"],
                 "sub": nb, "as": e["peer_as"], "from": dev, "link": eid},
            )
            bgp_rows.append({"device": dev, "nb": nb, "link": eid})
            continue

        # over-link: 両端 IP が同一物理リンクの subnet に属する
        lk = _link_id_for_pair(topo, lip, nb) if lip else None
        if lk is not None:
            eid = "be:ol:%s" % lk
            if eid not in edges:
                edges[eid] = {
                    "id": eid, "kind": "over-link", "link": lk,
                    "type": e["type"], "peerAs": e["peer_as"],
                }
                edge_order.append(eid)
            edge_afs.setdefault(eid, set()).add(e.get("af", "v4"))
        else:
            # loopback: 両端デバイスは既知だが共有 subnet なし（iBGP over loopback 典型）
            pair = tuple(sorted([dev, peer_dev]))
            eid = "be:lb:%s:%s" % pair
            if eid not in edges:
                a_ip = lip if dev == pair[0] else nb
                b_ip = nb if dev == pair[0] else lip
                edges[eid] = {
                    "id": eid, "kind": "loopback", "a": pair[0], "b": pair[1],
                    "aip": a_ip, "bip": b_ip,
                    "type": e["type"],
                    "label": "iBGP" if e["type"] == "ibgp" else "BGP",
                }
                edge_order.append(eid)
            edge_afs.setdefault(eid, set()).add(e.get("af", "v4"))

        bgp_rows.append({"device": dev, "nb": nb, "link": eid})

    # afs を決定的なソート済みリストとして各エッジに付与（set を直列化しない）
    for eid in edge_order:
        edges[eid]["afs"] = sorted(edge_afs[eid])

    ext_list = [ext_peers[k] for k in sorted(ext_peers)]
    return {
        "extPeers": ext_list,
        "bgpEdges": [edges[k] for k in edge_order],
        "bgp_rows": bgp_rows,
    }


def build_stats(topo, links=None, bgp_edges=None):
    """topology dict → 構成統計 dict。決定的・純粋関数。

    引数:
      topo      : topology dict
      links     : 省略可能。build_links(topo) の計算済み結果。
                  build_data() から呼ぶ際は計算済みを渡して二重呼び出しを避ける。
                  省略時（None）は内部で build_links を呼ぶ（単体テスト・旧コード互換）。
      bgp_edges : 省略可能。build_bgp_topology(topo)["bgpEdges"] の計算済み結果。
                  省略時（None）は内部で build_bgp_topology を呼ぶ。

    返り値キー:
      devices, interfaces, links, segments,
      by_vendor, by_as, by_area,
      link_kinds,
      dualstack_ifs, bgp_sessions, ospf_networks, static_routes

    注意:
      - link は build_links() で v4/v6 を統合した後の本数（merged 後）。
      - segment は raw（dual-stack 統合なし）の本数。
      - bgp_sessions = 重複排除後の BGP セッション数（方向・AF を問わない実セッション本数。
        ステータスバーの AF 総和とは別概念）。build_bgp_topology の bgpEdges 件数を使用。
    """
    # --- 基本カウント ---
    n_devices = len(topo["devices"])
    n_interfaces = len(topo["interfaces"])
    n_segments = len(topo["segments"])
    # build_links を使って v4/v6 を同一リンクに統合した後の本数。計算済みを再利用。
    resolved_links = links if links is not None else build_links(topo)
    n_links = len(resolved_links)

    # --- by_vendor: キー昇順 ---
    vendor_counts: dict = {}
    for d in topo["devices"]:
        v = d["vendor"]
        vendor_counts[v] = vendor_counts.get(v, 0) + 1
    by_vendor = {k: vendor_counts[k] for k in sorted(vendor_counts)}

    # --- by_as: AS は文字列キー。None は 'none'。数値 AS は数値昇順、'none' は末尾 ---
    as_counts: dict = {}
    for d in topo["devices"]:
        key = str(d["as"]) if d["as"] is not None else "none"
        as_counts[key] = as_counts.get(key, 0) + 1
    # 数値 AS キーを数値昇順（key=int）、'none' は末尾
    num_keys = sorted((k for k in as_counts if k != "none"), key=int)
    none_keys = ["none"] if "none" in as_counts else []
    by_as = {k: as_counts[k] for k in num_keys + none_keys}

    # --- by_area: routing.ospf の area 別件数。数値昇順、'none' は末尾 ---
    area_counts: dict = {}
    for e in topo["routing"].get("ospf", []):
        a = str(e["area"]) if e.get("area") is not None else "none"
        area_counts[a] = area_counts.get(a, 0) + 1
    num_area_keys = sorted((k for k in area_counts if k != "none"), key=int)
    none_area_keys = ["none"] if "none" in area_counts else []
    by_area = {k: area_counts[k] for k in num_area_keys + none_area_keys}

    # --- link_kinds: リンク1本 / セグメント / スタブ ---
    # stub = IF のうち links・segments いずれにも属さないもの
    linked_iface_ids: set = set()
    for ln in topo["links"]:
        linked_iface_ids.add("%s::%s" % (ln["a_device"], ln["a_if"]))
        linked_iface_ids.add("%s::%s" % (ln["b_device"], ln["b_if"]))
    for seg in topo["segments"]:
        for mid in seg.get("members", []):
            linked_iface_ids.add(mid)
    n_stub = sum(1 for itf in topo["interfaces"] if itf["id"] not in linked_iface_ids)
    link_kinds = {"link": n_links, "segment": n_segments, "stub": n_stub}

    # --- dual-stack IF: v4 と v6(scope != link-local) の両方を持つ IF ---
    n_dualstack = 0
    for itf in topo["interfaces"]:
        has_v4 = any(a["af"] == "v4" for a in itf["addresses"])
        has_v6_routable = any(
            a["af"] == "v6" and a.get("scope") != "link-local"
            for a in itf["addresses"]
        )
        if has_v4 and has_v6_routable:
            n_dualstack += 1

    # --- routing 件数 ---
    # bgp_sessions = 重複排除済み BGP セッション数（bgpEdges の件数）。計算済みを再利用。
    resolved_bgp_edges = bgp_edges if bgp_edges is not None else build_bgp_topology(topo)["bgpEdges"]
    n_bgp = len(resolved_bgp_edges)
    n_ospf = len(topo["routing"].get("ospf", []))
    n_static = len(topo["routing"].get("static", []))

    return {
        "devices": n_devices,
        "interfaces": n_interfaces,
        "links": n_links,
        "segments": n_segments,
        "by_vendor": by_vendor,
        "by_as": by_as,
        "by_area": by_area,
        "link_kinds": link_kinds,
        "dualstack_ifs": n_dualstack,
        "bgp_sessions": n_bgp,
        "ospf_networks": n_ospf,
        "static_routes": n_static,
    }


def build_data(topo):
    """topology dict → DATA（devices/links/segments/extPeers/bgpEdges/meta/stats）。決定的。"""
    devices = build_devices(topo)
    links = build_links(topo)
    segments = build_segments(topo)
    bgp_topo = build_bgp_topology(topo)

    rows_by_dev = defaultdict(list)
    for r in bgp_topo["bgp_rows"]:
        rows_by_dev[r["device"]].append(r["link"])
    for dev_id, dev in devices.items():
        links_list = rows_by_dev.get(dev_id, [])
        for i, row in enumerate(dev["bgp"]):
            row["link"] = links_list[i] if i < len(links_list) else None

    return {
        "meta": {"generated_from": topo["meta"].get("generated_from", [])},
        "devices": devices, "links": links, "segments": segments,
        "extPeers": bgp_topo["extPeers"], "bgpEdges": bgp_topo["bgpEdges"],
        "stats": build_stats(topo, links=links, bgp_edges=bgp_topo["bgpEdges"]),
    }
