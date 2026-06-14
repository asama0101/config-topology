"""topology dict → DATA（JS が消費する形）。pure・決定的。"""
import ipaddress
import re
from collections import defaultdict

# static_dangling_next_hop ルールでスキップする特殊ネクストホップ値。
# デフォルトルート（0.0.0.0/0・::/0）の NH として使われる代表値と、
# ブロードキャスト・未指定アドレスを含む。
_SPECIAL_NH = frozenset(["0.0.0.0", "::", "255.255.255.255"])

# サブネット使用率 exhausted 判定閾値（util >= この値 → exhausted=True）。
# assets.py の renderSubnetUsageView tnote 文言「exhausted = 使用率 80% 以上」と同値。
_EXHAUSTED_THRESHOLD = 0.8

# loopback インタフェース名の判定正規表現。JS の ifKind 判定 /^lo(opback)?\d*$/i と同一基準。
# 一致例: lo / lo0 / Loopback0 / Lo10 / loopback1 / LOOPBACK0
# 非一致例: GigabitEthernet0/0 / Gi0/0 / ge-0/0/0 / eth0 / Vlan1
_LOOPBACK_RE = re.compile(r"^lo(opback)?\d*$", re.IGNORECASE)


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


def _compute_degrees(topo):
    """各 device の物理接続数（degree）を決定的に算出する。

    degree = その device に隣接する**相異なるノード数**。
    - links: 端点ペアから対向 device を取得し、set で重複排除（dual-stack 対応）。
    - segments: メンバー IF の device から自分以外のメンバー device を set で収集。

    返り値: {device_id: int}（全 device を含む。リンクなし孤立機器は 0）
    """
    # 全 device_id を初期化
    degrees = {d["id"]: set() for d in topo["devices"]}

    # interface id → device id の逆引き（segment 解決用）
    if_to_dev = {itf["id"]: itf["device"] for itf in topo["interfaces"]}

    # links: a_device の隣接に b_device を追加（逆も同様）
    for ln in topo["links"]:
        a, b = ln["a_device"], ln["b_device"]
        if a in degrees and b in degrees:
            degrees[a].add(b)
            degrees[b].add(a)

    # segments: メンバー全員が互いに隣接（自分以外全員）
    for seg in topo["segments"]:
        # メンバー IF id → device id を解決
        member_devs = []
        for mid in seg.get("members", []):
            dev = if_to_dev.get(mid)
            if dev is not None:
                member_devs.append(dev)
        # 重複排除（同一 device の複数 IF が 1 セグメントに参加する場合）
        member_dev_set = set(member_devs)
        for dev in member_dev_set:
            if dev in degrees:
                degrees[dev] |= (member_dev_set - {dev})

    return {dev_id: len(adj_set) for dev_id, adj_set in degrees.items()}


def build_devices(topo):
    """DATA.devices（id キーのオブジェクト）を構築。ifs は config 順。routing は device 別。"""
    by_dev_if = {}
    for itf in topo["interfaces"]:
        by_dev_if.setdefault(itf["device"], []).append(itf)

    bgp_by_dev, ospf_by_dev, static_by_dev, redist_by_dev = {}, {}, {}, {}
    for e in topo["routing"].get("bgp", []):
        row = {"nb": e["neighbor_ip"], "pas": e["peer_as"], "type": e["type"],
               "af": e["af"], "lip": e["local_ip"], "link": None,
               "src": e.get("update_source"),
               "rr": e.get("route_reflector_client"),
               "nhs": e.get("next_hop_self")}
        bgp_by_dev.setdefault(e["device"], []).append(row)
    for e in topo["routing"].get("ospf", []):
        row = {"net": e["network"], "area": e["area"], "proc": e["process"],
               "at": e.get("area_type")}
        ospf_by_dev.setdefault(e["device"], []).append(row)
    for e in topo["routing"].get("static", []):
        static_by_dev.setdefault(e["device"], []).append(
            {"p": e["prefix"], "nh": e["next_hop"]})
    for e in topo["routing"].get("redistribute", []):
        row = {"into": e["into"], "source": e["source"]}
        if "metric" in e:
            row["metric"] = e["metric"]
        if "route_map" in e:
            row["route_map"] = e["route_map"]
        redist_by_dev.setdefault(e["device"], []).append(row)

    # 物理接続数（degree）を決定的に算出
    degrees = _compute_degrees(topo)

    out = {}
    for d in topo["devices"]:
        out[d["id"]] = {
            "hostname": d["hostname"], "vendor": d["vendor"], "as": d["as"],
            "ospf_rid": d["ospf_router_id"], "bgp_rid": d["bgp_router_id"],
            "ifs": [_build_if(i) for i in by_dev_if.get(d["id"], [])],
            "bgp": bgp_by_dev.get(d["id"], []),
            "ospf": ospf_by_dev.get(d["id"], []),
            "static": static_by_dev.get(d["id"], []),
            "redistribute": redist_by_dev.get(d["id"], []),
            "degree": degrees.get(d["id"], 0),
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
    """interfaces の addresses から ip → device の逆引き辞書を構築。

    注意: link-local アドレスを含む（scope フィルタなし）。重複 IP は setdefault 先勝ち。
    BGP full-mesh 判定では link-local 除外と先勝ち順固定が必要なため
    _check_ibgp_fullmesh 内で host_ip_to_device を別途構築する（この関数は使わない）。
    """
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


def _collect_rid_duplicates(devices, field, kind, proto_label):
    """router-id 重複を検出し check エントリのリストを返す共通ヘルパー。

    引数:
      devices     : topology dict の devices リスト
      field       : 検査するフィールド名（"ospf_router_id" または "bgp_router_id"）
      kind        : check エントリの kind 文字列（"duplicate_ospf_router_id" 等）
      proto_label : メッセージ用プロトコル名（"OSPF" または "BGP"）

    返り値: [{"severity": "error", "kind": ..., "message": ..., "refs": [...]}, ...]
      - None は無視、1 台のみは検出しない
      - refs = sorted(dev_ids) + [rid]（device id 昇順 + router-id 値末尾）
      - message = "<proto_label> router-id <rid> が複数機器で重複: <dev1>, <dev2>, ..."
      - router-id 値の昇順で決定的に走査
    """
    rid_groups: dict = {}
    for d in devices:
        rid = d.get(field)
        if rid is None:
            continue
        rid_groups.setdefault(rid, [])
        if d["id"] not in rid_groups[rid]:
            rid_groups[rid].append(d["id"])

    results = []
    for rid in sorted(rid_groups):
        dev_ids = sorted(rid_groups[rid])
        if len(dev_ids) < 2:
            continue
        results.append({
            "severity": "error",
            "kind": kind,
            "message": "%s router-id %s が複数機器で重複: %s" % (proto_label, rid, ", ".join(dev_ids)),
            "refs": dev_ids + [rid],
        })
    return results


def _check_ospf_area0_connectivity(topo):
    """OSPF area0（backbone）を持たない device を検出し check エントリのリストを返す。

    近似: config 保有 area で判定（結線情報は不使用）。area "0" を持つ device を ABR とみなす。

    発火条件:
      - area "0" を持つ device が 1 台以上存在する（area0 不在環境では偽陽性を抑制するため非発火）。
      - OSPF エントリを持ちながら area "0" を 1 つも持たない device を id 昇順で列挙。

    返り値: [{"severity": "warning", "kind": "ospf_area0_disconnected", ...}, ...]
      - refs = [device] + sorted(areas)
    """
    # device → set(area) を決定的に構築
    # area=None のエントリは除外（手編集 YAML 等で混入した場合の TypeError 防止）
    dev_areas: dict = {}
    for e in topo["routing"].get("ospf", []):
        dev = e["device"]
        area = e.get("area")
        if area is None:
            continue  # area=None は判定対象外（sorted/join の TypeError 防止）
        dev_areas.setdefault(dev, set())
        dev_areas[dev].add(area)

    if not dev_areas:
        return []

    # area0 を持つ device が 1 台も居なければ非発火（偽陽性抑制）
    has_area0 = any("0" in areas for areas in dev_areas.values())
    if not has_area0:
        return []

    results = []
    for dev in sorted(dev_areas):
        areas = dev_areas[dev]
        if "0" in areas:
            continue  # area0 保有（ABR 含む）は対象外
        # 数値優先ソート: digit 文字列を数値として比較し、非 digit はフォールバックで末尾
        sorted_areas = sorted(areas, key=lambda a: (not a.isdigit(), int(a) if a.isdigit() else a))
        results.append({
            "severity": "warning",
            "kind": "ospf_area0_disconnected",
            "message": "機器 %s は area 0 (backbone) を持たず非バックボーン area %s のみです（area0 混在環境）" % (
                dev, ", ".join(sorted_areas)),
            "refs": [dev] + sorted_areas,
        })
    return results


def _check_ospf_area_mismatch(topo, resolved_links):
    """OSPF area 不一致のリンク・セグメントを検出し check エントリのリストを返す。

    引数:
      topo           : topology dict
      resolved_links : build_links(topo) の計算済み結果（二重計算回避のため build_checks から受け取る）

    build.py::aggregate_areas が複数 area を "/" で結合して "0/1" 等の形式で
    ospf_area フィールドに格納する。この形式は実機上で OSPF 隣接が確立できない
    設定誤りを示す。

    発火条件:
      - リンク（resolved_links）の area フィールドに "/" を含む。
      - セグメント（topo["segments"]）の ospf_area フィールドに "/" を含む。

    返り値: [{"severity": "warning", "kind": "ospf_area_mismatch", ...}, ...]
      - リンク refs = sorted([ln["a"], ln["b"]]) + [subnet]（subnet 優先で v4 > v6 > ""）
      - セグメント refs = [seg_id, subnet]
    """
    results = []

    # ---- リンク ----
    for ln in resolved_links:
        area_str = str(ln.get("area") or "")
        if "/" not in area_str:
            continue
        # 両端 device を辞書順ソートして決定的な refs にする
        devices = sorted([ln["a"], ln["b"]])
        subnet_ref = ln.get("subnet") or ln.get("dual") or ""
        results.append({
            "severity": "warning",
            "kind": "ospf_area_mismatch",
            "message": "OSPF area 不一致: %s — %s 間のリンク（%s）で area が %s に混在しています" % (
                devices[0], devices[1], subnet_ref, area_str),
            "refs": devices + ([subnet_ref] if subnet_ref else []),
        })

    # ---- セグメント ----
    for seg in topo["segments"]:
        area_str = str(seg.get("ospf_area") or "")
        if "/" not in area_str:
            continue
        results.append({
            "severity": "warning",
            "kind": "ospf_area_mismatch",
            "message": "OSPF area 不一致: セグメント %s（%s）で area が %s に混在しています" % (
                seg["id"], seg["subnet"], area_str),
            "refs": [seg["id"], seg["subnet"]],
        })

    return results


def _check_ibgp_fullmesh(topo):
    """iBGP full-mesh 未完成ペアを検出し check エントリのリストを返す（保守的判定）。

    偽陽性を強く抑える:
      - RR 構成（いずれかのセッションに route_reflector_client=True）の AS はスキップ。
      - neighbor_ip が解決不能な device が絡むペアはスキップ。
      - link-local（scope="link-local"）の IF アドレスは host_ip_to_device 構築から除外。

    返り値: [{"severity": "warning", "kind": "ibgp_fullmesh_incomplete", ...}, ...]
      - refs = [di, dj, str(asn)]  di < dj（id 昇順）
    """
    # host IP → device 逆引き（link-local 除外・先勝ち順固定）
    # _ip_to_device() を使わない理由: link-local 除外と先勝ち順固定（device/name 辞書順）が必要。
    # _ip_to_device() は link-local を含み・重複時の順序が保証されない。
    host_ip_to_device: dict = {}
    for itf in sorted(topo["interfaces"], key=lambda x: (x["device"], x["name"])):
        for a in itf["addresses"]:
            if a.get("scope") == "link-local":
                continue
            ip = a.get("ip")
            if ip and ip not in host_ip_to_device:
                host_ip_to_device[ip] = itf["device"]

    # AS ごとに iBGP セッションを集約
    # as_sessions: {local_as: [entry]}
    # local_as=None のエントリは sorted() の TypeError 防止のため除外（None キーはスキップ）
    as_sessions: dict = {}
    for e in topo["routing"].get("bgp", []):
        if e.get("type") != "ibgp":
            continue
        asn = e["local_as"]
        if asn is None:
            continue  # local_as=None は full-mesh 判定対象外（手編集 YAML 等で混入した場合）
        as_sessions.setdefault(asn, [])
        as_sessions[asn].append(e)

    results = []
    for asn in sorted(as_sessions):
        sessions = as_sessions[asn]

        # RR 構成チェック: 1 件でも route_reflector_client=True があればスキップ
        if any(e.get("route_reflector_client") is True for e in sessions):
            continue

        # AS 内 speaker 集合
        speakers = sorted({e["device"] for e in sessions})
        D = set(speakers)

        # 隣接集合（frozenset ペア）
        adjacency: set = set()
        # 解決不能 neighbor を持つ device
        unresolved_devs: set = set()

        for e in sessions:
            dev = e["device"]
            neighbor_ip = e.get("neighbor_ip")
            partner = host_ip_to_device.get(neighbor_ip)
            if partner == dev:
                # 自己セッション（ループバック neighbor 等）: unresolved には加えない
                pass
            elif partner is None or partner not in D:
                # 未解決 neighbor または D 外の AS（eBGP 等が混入した場合）:
                # dev を unresolved_devs に追加し、このデバイスが絡むペアをスキップ（偽陽性抑制）
                unresolved_devs.add(dev)
            else:
                adjacency.add(frozenset({dev, partner}))

        # 全ペアを検査（di < dj）
        for i, di in enumerate(speakers):
            for dj in speakers[i + 1:]:
                pair = frozenset({di, dj})
                if pair in adjacency:
                    continue
                # どちらかが unresolved_devs に含まれればスキップ（偽陽性回避）
                if di in unresolved_devs or dj in unresolved_devs:
                    continue
                results.append({
                    "severity": "warning",
                    "kind": "ibgp_fullmesh_incomplete",
                    "message": "AS %s の iBGP full-mesh 未完成（RR なし）: %s と %s の間に iBGP セッションがありません" % (
                        asn, di, dj),
                    "refs": [di, dj, str(asn)],
                })
    return results


def build_checks(topo, links=None):
    """topology dict を決定的に走査し設計上の注意点を検出したリストを返す。

    引数:
      topo  : topology dict
      links : 省略可能。build_links(topo) の計算済み結果（二重計算回避用）。

    各要素: {"severity": "error"|"warning", "kind": str, "message": str, "refs": [str,...]}
    返却前に severity(error→warning)→kind→refs の文字列キーで安定ソート。

    検出ルール:
      1. duplicate_ip (error): 同一ホスト IP が複数 IF に存在（v4/v6 双方・secondary 含む）。
         ただし link-local（scope="link-local"）は除外（fe80:: は各リンク固有でありアドレス重複ではない）。
      2. mtu_mismatch (warning): 同一物理リンク両端の MTU が双方非 None かつ不一致。
         build_links() で統合した resolved_links（端点ペア単位）を走査するため、
         dual-stack（同一端点に v4+v6 の raw リンク 2 行）でも 1 件のみ検出される。
         なお MTU 不一致は INTERFACES 表（renderIfsTable）でも個別 IF 単位で表示されるが、
         これは意図的な二重表示（CHECKS はリンク単位のまとまった警告、INTERFACES 表は IF 属性の参照用）。
      3. bgp_unresolved_local_ip (warning): BGP エントリで local_ip が None または欠如。
      4. static_dangling_next_hop (warning): static の next_hop がどの IF サブネット/ホスト IP にも属さない。
         スコープ: トポロジー全体（複数デバイスの全 IF を対象）。
         link-local アドレスは all_subnets / all_host_ips から除外（fe80:: サブネットへの誤属を防ぐ）。
         スキップ対象:
           - _SPECIAL_NH（0.0.0.0 / :: / 255.255.255.255）
           - デフォルトルート prefix（0.0.0.0/0・::/0）
           - IF 名が next_hop に使われる場合（Null0 等、ipaddress.ip_address でパース不能）
      5. duplicate_ospf_router_id (error): 同一 ospf_router_id を持つ2台以上の機器。
         None 無視・機器内 ospf=bgp 共用は非対象（同一機器内の一致は検出しない）。
      6. duplicate_bgp_router_id (error): 同一 bgp_router_id を持つ2台以上の機器。
         None 無視・機器内 ospf=bgp 共用は非対象（同一機器内の一致は検出しない）。
      7. ospf_area0_disconnected (warning): OSPF area0 混在環境で、area0 を持たない device。
         area0 が 1 台も存在しない環境では非発火（偽陽性抑制）。
         config 保有 area で近似判定（結線情報は不使用）。
      8. ibgp_fullmesh_incomplete (warning): iBGP full-mesh 未完成ペア（RR なし AS のみ）。
         いずれかのセッションに route_reflector_client=True があれば AS 全体をスキップ（RR 構成）。
         解決不能 neighbor_ip を持つ device が絡むペアもスキップ（偽陽性抑制）。
      9. ospf_area_mismatch (warning): リンクまたはセグメントの ospf_area が "/" 連結（例 "0/1"）。
         build.py::aggregate_areas が両端の area を "/" で結合するため、不一致時に検出可能。
         実機では area 不一致リンクで OSPF 隣接は張れない＝設定誤り。
    """
    results = []

    # ---- ルール 1: duplicate_ip ----
    # IP → [(device, ifname)] の逆引き（v4/v6 両方・secondary 含む）
    # link-local（scope="link-local"）は除外：fe80:: は各リンクで共通のアドレスが付くため
    ip_to_refs: dict = {}
    for itf in topo["interfaces"]:
        for a in itf["addresses"]:
            if a.get("scope") == "link-local":
                continue  # link-local(fe80::) はアドレス重複の対象外
            ip = a.get("ip")
            if not ip:
                continue
            key = "%s:%s" % (a.get("af", "v4"), ip)
            ref = "%s::%s" % (itf["device"], itf["name"])
            ip_to_refs.setdefault(key, [])
            if ref not in ip_to_refs[key]:
                ip_to_refs[key].append(ref)

    # IP 昇順でソート（決定的。af:ip の文字列順なので v4/v6 混在でも安定）
    for key in sorted(ip_to_refs):
        refs = ip_to_refs[key]
        if len(refs) < 2:
            continue
        _, ip = key.split(":", 1)
        results.append({
            "severity": "error",
            "kind": "duplicate_ip",
            "message": "IP %s が複数の interface に重複して設定されています" % ip,
            "refs": sorted(refs),
        })

    # ---- ルール 2: mtu_mismatch ----
    # interface ID → mtu の逆引き
    # resolved_links（build_links で端点ペア統合済み）を走査することで、
    # dual-stack（同一端点ペアに v4+v6 の raw 2 行）でも端点ペア単位に統一され重複解消。
    resolved_links = links if links is not None else build_links(topo)
    if_mtu = {itf["id"]: itf["mtu"] for itf in topo["interfaces"]}

    for ln in resolved_links:
        a_id = "%s::%s" % (ln["a"], ln["ai"])
        b_id = "%s::%s" % (ln["b"], ln["bi"])
        mtu_a = if_mtu.get(a_id)
        mtu_b = if_mtu.get(b_id)
        if mtu_a is None or mtu_b is None:
            continue
        if mtu_a == mtu_b:
            continue
        # サブネット表示は v4 を優先（subnet キー）し、v6 のみなら dual キーを使う
        subnet_ref = ln.get("subnet") or ln.get("dual", "")
        results.append({
            "severity": "warning",
            "kind": "mtu_mismatch",
            "message": "MTU 不一致: %s:%s と %s:%s（%s vs %s）" % (
                ln["a"], ln["ai"], ln["b"], ln["bi"],
                mtu_a, mtu_b),
            "refs": sorted([a_id, b_id]) + ([subnet_ref] if subnet_ref else []),
        })

    # ---- ルール 3: bgp_unresolved_local_ip ----
    for e in topo["routing"].get("bgp", []):
        if e.get("local_ip") is None:
            results.append({
                "severity": "warning",
                "kind": "bgp_unresolved_local_ip",
                "message": "BGP neighbor %s の local_ip が解決できませんでした（device: %s）" % (
                    e["neighbor_ip"], e["device"]),
                "refs": [e["device"], e["neighbor_ip"]],
            })

    # ---- ルール 4: static_dangling_next_hop ----
    # 全 IF のアドレスから、サブネット集合とホスト IP 集合を構築。
    # link-local（scope="link-local"）は除外：fe80::/64 が all_subnets に入ると
    # next_hop が fe80:: 帯に属するとして誤判定されるリスクがあるため。
    all_subnets = []   # [(network_object, ...)]
    all_host_ips = set()
    for itf in topo["interfaces"]:
        for a in itf["addresses"]:
            if a.get("scope") == "link-local":
                continue  # link-local は静的ルーティングの参照対象外
            ip = a.get("ip")
            if not ip:
                continue
            prefix = a.get("prefix")
            if prefix is None:
                continue
            try:
                net = ipaddress.ip_network("%s/%s" % (ip, prefix), strict=False)
                all_subnets.append(net)
                all_host_ips.add(ip)
            except ValueError:
                continue

    for e in topo["routing"].get("static", []):
        nh = e.get("next_hop")
        prefix = e.get("prefix", "")
        device = e.get("device", "")
        if not nh:
            continue
        # デフォルトルート・特殊値はスキップ（_SPECIAL_NH はモジュールレベル定数）
        if nh in _SPECIAL_NH:
            continue
        # デフォルトルート prefix（0.0.0.0/0 または ::/0）もスキップ
        if prefix in ("0.0.0.0/0", "::/0"):
            continue
        # ホスト IP と一致するか確認
        if nh in all_host_ips:
            continue
        # IF 名等の非 IP 文字列（Null0 等）はパース不能でスキップ
        try:
            nh_addr = ipaddress.ip_address(nh)
        except ValueError:
            continue
        in_subnet = any(nh_addr in net for net in all_subnets)
        if in_subnet:
            continue
        results.append({
            "severity": "warning",
            "kind": "static_dangling_next_hop",
            "message": "static ルート %s の next_hop %s がどの interface サブネットにも属しません（device: %s）" % (
                prefix, nh, device),
            "refs": [device, prefix, nh],
        })

    # ---- ルール 5: duplicate_ospf_router_id ----
    # ospf_router_id（非 None）でグループ化し、2 台以上の device が同一値を持つ場合に検出。
    # None は無視。1 台のみは検出しない。決定的にするため router-id 値昇順で走査。
    results.extend(_collect_rid_duplicates(
        topo["devices"], "ospf_router_id", "duplicate_ospf_router_id", "OSPF"))

    # ---- ルール 6: duplicate_bgp_router_id ----
    # bgp_router_id（非 None）でグループ化し、2 台以上の device が同一値を持つ場合に検出。
    results.extend(_collect_rid_duplicates(
        topo["devices"], "bgp_router_id", "duplicate_bgp_router_id", "BGP"))

    # ---- ルール 7: ospf_area0_disconnected ----
    # area0 混在環境で area0 を持たない device を警告（偽陽性抑制: area0 不在環境は非発火）。
    results.extend(_check_ospf_area0_connectivity(topo))

    # ---- ルール 8: ibgp_fullmesh_incomplete ----
    # iBGP full-mesh 未完成ペアを警告（RR 構成 AS はスキップ・解決不能 neighbor も偽陽性抑制）。
    results.extend(_check_ibgp_fullmesh(topo))

    # ---- ルール 9: ospf_area_mismatch ----
    # リンク/セグメントの ospf_area が "/" 連結（例 "0/1"）＝両端 area 不一致を警告。
    # resolved_links を再利用（二重計算回避）。
    results.extend(_check_ospf_area_mismatch(topo, resolved_links))

    # ---- 安定ソート: severity(error→warning)→kind→refs 文字列 ----
    _SEV_ORDER = {"error": 0, "warning": 1}
    results.sort(key=lambda c: (
        _SEV_ORDER.get(c["severity"], 9),
        c["kind"],
        "|".join(c["refs"]),
    ))
    return results


def build_subnet_usage(topo):
    """v4 サブネット単位の使用率集約。使用率(util)降順 → subnet 文字列昇順で安定ソート。

    返り値: [{"subnet":str,"af":"v4","usable":int,"used":int,"free":int,"util":float,"exhausted":bool}]

    集計ルール:
      - topo["interfaces"] の各 address で af=="v4"・scope!="link-local"・ip と prefix が有るもののみ対象。
      - prefix==32（ホスト/ループバック）は除外。
      - サブネットごとに used = len(set(host_ip))（重複排除）。secondary=True の IP も used にカウントする。
      - usable = /31→2、他 2^(32-p)-2（例: /30→2^2-2=2、/24→2^8-2=254）。
      - free = max(usable-used, 0)。
      - util = round(used/usable, 4) if usable else 0.0。
      - exhausted = util >= _EXHAUSTED_THRESHOLD（= 0.8）。
    """
    # サブネット文字列 → ホスト IP の set
    subnet_hosts: dict = {}

    for itf in topo["interfaces"]:
        for a in itf["addresses"]:
            # v4 のみ
            if a.get("af") != "v4":
                continue
            # link-local 除外
            if a.get("scope") == "link-local":
                continue
            ip = a.get("ip")
            prefix = a.get("prefix")
            if ip is None or prefix is None:
                continue
            # /32 除外（ホスト/ループバック）
            if int(prefix) == 32:
                continue
            try:
                net = ipaddress.ip_network("%s/%s" % (ip, prefix), strict=False)
            except ValueError:
                continue
            subnet_str = str(net)
            subnet_hosts.setdefault(subnet_str, set())
            subnet_hosts[subnet_str].add(ip)

    results = []
    for subnet_str, host_set in subnet_hosts.items():
        net = ipaddress.ip_network(subnet_str)
        p = net.prefixlen
        usable = 2 if p == 31 else (2 ** (32 - p) - 2)
        used = len(host_set)
        free = max(usable - used, 0)
        util = round(used / usable, 4) if usable else 0.0
        exhausted = util >= _EXHAUSTED_THRESHOLD
        results.append({
            "subnet": subnet_str,
            "af": "v4",
            "usable": usable,
            "used": used,
            "free": free,
            "util": util,
            "exhausted": exhausted,
        })

    # util 降順 → subnet 文字列昇順（安定ソート）
    results.sort(key=lambda r: (-r["util"], r["subnet"]))
    return results


def _natural_key(s):
    """文字列を「数値部を整数・非数値部を文字列」で交互に分割したリストで返す（自然順ソート用）。
    例: "Loopback10" → ["Loopback", 10, ""] / "lo0" → ["lo", 0, ""]。決定的・副作用なし。

    注意: JS の naturalKey とは大文字小文字扱い・方式が異なる Python 専用 sort ヘルパー
    （stub_nodes のソートは Python 単独責務のため実害なし）。
    isdigit() ではなく isdecimal() を使う: 上付き数字（'²' 等）は isdigit()=True だが
    int() 変換で ValueError になる差異を解消するため。ASCII の 0-9 では挙動は同一。
    """
    parts = []
    for tok in re.split(r"(\d+)", s):
        parts.append(int(tok) if tok.isdecimal() else tok)
    return parts


def build_stub_nodes(topo):
    """対向のない IF（stub / loopback）を segment 様式ノード化するための
    [{dev, ifn, ip, subnet, area, kind}] を返す（dev→ifn 自然順で安定ソート）。

    「stub」= link（異機器2メンバー）にも segment（≥3メンバー）にも属さない IF-サブネット。
    判定は build.infer_links_segments と整合する: links/segments が占有する cidr 集合を作り、
    それ以外の IF-サブネット（v4・非 secondary・非 link-local）の各メンバーを stub ノードにする。
    単独 IF サブネット（LAN 側・loopback /32 等）と同一機器2メンバーが該当する。

    各フィールド:
      - kind: IF 名が _LOOPBACK_RE 一致なら "loopback"、それ以外は "stub"。
      - subnet: str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))（segment と同じ中央表示用）。
      - area: 同一 device・af=="v4" の routing.ospf entry と ipaddress 内包判定で最長プレフィックス一致
              （同長は str(area) 昇順）。OSPF 非参加なら None（OSPF ビューでは area あり=参加のみ描画）。

    返り値は (dev, natural_key(ifn)) で安定ソート（決定的）。
    """
    # links/segments が占有する cidr 集合（これ以外の IF-サブネットが stub）
    linked_cidrs = set()
    for l in topo.get("links", []):
        if l.get("subnet"):
            linked_cidrs.add(l["subnet"])
    for s in topo.get("segments", []):
        if s.get("subnet"):
            linked_cidrs.add(s["subnet"])

    # device → ospf entries (v4 のみ) をあらかじめ整理（area 引き当て用）
    ospf_by_dev = {}
    for e in topo["routing"].get("ospf", []):
        if e.get("af") != "v4":
            continue
        dev = e["device"]
        try:
            net = ipaddress.ip_network(e["network"], strict=False)
        except ValueError:
            continue
        if net.version != 4:
            continue
        ospf_by_dev.setdefault(dev, []).append((net, str(e["area"])))

    results = []
    for itf in topo["interfaces"]:
        dev = itf["device"]
        is_loopback = bool(_LOOPBACK_RE.match(itf["name"]))
        seen = set()  # 同一 IF 内の cidr 重複除去
        # v4 かつ非 link-local かつ非 secondary のアドレスを対象
        for a in itf.get("addresses", []):
            if a.get("af") != "v4":
                continue
            if a.get("scope") == "link-local":
                continue
            if a.get("secondary"):
                continue
            ip_str = a.get("ip")
            prefix = a.get("prefix")
            if not ip_str or prefix is None:
                continue
            try:
                net_obj = ipaddress.ip_network(f"{ip_str}/{prefix}", strict=False)
            except ValueError:
                continue
            cidr = str(net_obj)
            if cidr in linked_cidrs:
                continue  # link/segment 所属 → stub ではない
            if cidr in seen:
                continue
            seen.add(cidr)

            # 同一 device の OSPF entry で最長プレフィックス一致の area を引く（無ければ None）
            try:
                ip_addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            candidates = [(net.prefixlen, area)
                          for net, area in ospf_by_dev.get(dev, []) if ip_addr in net]
            area = None
            if candidates:
                candidates.sort(key=lambda x: (-x[0], x[1]))
                area = candidates[0][1]

            results.append({
                "dev": dev, "ifn": itf["name"], "ip": ip_str,
                "subnet": cidr, "area": area,
                "kind": "loopback" if is_loopback else "stub",
            })

    # (dev, natural_key(ifn)) で安定ソート
    results.sort(key=lambda r: (r["dev"], _natural_key(r["ifn"])))
    return results


def build_data(topo):
    """topology dict → DATA（devices/links/segments/extPeers/bgpEdges/meta/checks/subnet_usage/stub_nodes）。決定的。"""
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
        "checks": build_checks(topo, links=links),
        "subnet_usage": build_subnet_usage(topo),
        "stub_nodes": build_stub_nodes(topo),
    }
