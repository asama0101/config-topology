"""topology dict → DATA（JS が消費する形）。pure・決定的。"""
import ipaddress


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
        else:
            # loopback: 両端デバイスは既知だが共有 subnet なし（iBGP over loopback 典型）
            pair = tuple(sorted([dev, peer_dev]))
            eid = "be:lb:%s:%s" % pair
            if eid not in edges:
                edges[eid] = {
                    "id": eid, "kind": "loopback", "a": pair[0], "b": pair[1],
                    "aip": lip, "bip": nb,
                    "type": e["type"],
                    "label": "iBGP" if e["type"] == "ibgp" else "BGP",
                }
                edge_order.append(eid)

        bgp_rows.append({"device": dev, "nb": nb, "link": eid})

    ext_list = [ext_peers[k] for k in sorted(ext_peers)]
    return {
        "extPeers": ext_list,
        "bgpEdges": [edges[k] for k in edge_order],
        "bgp_rows": bgp_rows,
    }
