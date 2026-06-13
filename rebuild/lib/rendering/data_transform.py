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
