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
            interfaces.append({
                "id": interface_id(dev_id, itf.name), "device": dev_id, "name": itf.name,
                "ip": itf.derived_ip(), "vlan": itf.vlan, "description": itf.description,
                "shutdown": itf.shutdown, "admin_status": itf.admin_status,
                "oper_status": itf.oper_status, "mtu": itf.mtu, "speed": itf.speed,
                "duplex": itf.duplex, "l2_l3": itf.l2_l3, "switchport": itf.switchport,
                "encapsulation": itf.encapsulation, "source": "parsed",
                "addresses": [a.to_dict() for a in itf.sorted_addresses()],
            })
    devices_sorted = sorted(devices, key=lambda d: d["id"])   # 出力は id 昇順（§7.5）
    return device_ids, devices_sorted, interfaces


def _iface_subnets(itf):
    """IF の addresses から所属ネットワーク CIDR 集合（link-local 除外・重複除去）を返す。"""
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
    """neighbor_ip と同一サブネットにある自機 IF の IP（af 一致）を返す。無ければ None（§7.3）。"""
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
    return None


def _bgp_type(local_as, peer_as):
    if peer_as is None:
        return "unknown"
    if local_as == peer_as:
        return "ibgp"
    return "ebgp"


def build_bgp(id_dev):
    """id_dev: [(device_id, Device)] → routing.bgp エントリ列（§7.3）。"""
    out = []
    for dev_id, dev in id_dev:
        for nb in dev.bgp:
            out.append({
                "device": dev_id, "local_as": dev.as_,
                "local_ip": _resolve_local_ip(dev, nb),
                "neighbor_ip": nb.neighbor_ip, "peer_as": nb.peer_as,
                "type": _bgp_type(dev.as_, nb.peer_as), "af": nb.af,
            })
    return out
