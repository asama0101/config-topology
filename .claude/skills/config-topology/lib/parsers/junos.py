"""Juniper JunOS（set 形式）パーサ（要件書 §6.2）。"""
import re

from ..models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from ..normalize import norm_cidr_str, norm_ipv4, norm_ipv6, norm_ospf_area, v6_scope
from .base import ensure_ospf, is_sensitive_line


def _set_l3(iface: Interface) -> None:
    """family inet/inet6 に address があれば l3 としてマークする（§6.2）。

    ただし l2 が既設なら維持（L2 優先）。IOS と異なり JunOS は L2 優先のため、
    L3 は l2_l3 が "l2" でない場合のみ設定する。
    """
    if iface.l2_l3 != "l2":
        iface.l2_l3 = "l3"


def _base_if(ifname: str) -> str:
    """unit 付き IF 名（ge-0/0/0.0）から base 名（ge-0/0/0）を返す（§6.2）。

    JunOS は unit N を base IF に集約するため、unit 番号を除去する。
    """
    return ifname.split(".")[0]


def _apply_ospf_if_param(iface: Interface, rest: str) -> None:
    """protocols ospf(3) area <a> interface <if> <rest> の <rest> を解析し iface.ospf をミューテート。

    対応パラメータ:
      metric <n>          → ospf["cost"] = int(n)
      interface-type <t>  → ospf["network_type"] = t
      passive             → ospf["passive"] = True
    """
    m = re.match(r"^metric\s+(\d+)", rest)
    if m:
        ensure_ospf(iface)["cost"] = int(m.group(1))
        return
    m = re.match(r"^interface-type\s+(\S+)", rest)
    if m:
        ensure_ospf(iface)["network_type"] = m.group(1)
        return
    if rest == "passive":
        ensure_ospf(iface)["passive"] = True
        return


def _ospf_v4_network(iface: Interface) -> str | None:
    """IF の最初の v4 サブネットを CIDR 文字列で返す（§6.2 OSPFv2 network 解決）。

    v4 address が存在しない場合は None を返す。
    """
    if iface is None:
        return None
    for a in iface.sorted_addresses():
        if a.af == "v4":
            return norm_cidr_str("%s/%s" % (a.ip, a.prefix))
    return None


def _parse_if_body(iface: Interface, rest: str, warnings: list) -> None:
    """`set interfaces <if> <rest>` の <rest> を解析し iface をミューテートする（§6.2）。

    認識できない行は無視する（クラッシュしない）。パース失敗は warnings へ追記する（§6.3）。
    対応フィールド:
      - description
      - disable → shutdown / admin_status
      - mtu / speed / encapsulation
      - unit N family inet address <cidr>    → v4 address、l3 マーク
      - unit N family inet6 address <cidr>   → v6 address（scope 付き）、l3 マーク
      - unit N family ethernet-switching     → l2 マーク（L2 優先）
    """
    m = re.match(r"^description\s+(.*)$", rest)
    if m:
        iface.description = m.group(1).strip().strip('"')
        return
    if rest == "disable":
        iface.shutdown = True
        return
    m = re.match(r"^mtu\s+(\d+)", rest)
    if m:
        iface.mtu = int(m.group(1))
        return
    m = re.match(r"^speed\s+(\S+)", rest)
    if m:
        iface.speed = m.group(1)
        return
    m = re.match(r"^encapsulation\s+(\S+)", rest)
    if m:
        iface.encapsulation = m.group(1)
        return
    m = re.match(r"^unit\s+\d+\s+family\s+inet\s+address\s+(\S+)", rest)
    if m:
        cidr = m.group(1)
        try:
            host, plen = cidr.split("/")
            iface.addresses.append(Address("v4", norm_ipv4(host), int(plen)))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("junos inet address parse failed: %s (%s)" % (rest, e))
        return
    m = re.match(r"^unit\s+\d+\s+family\s+inet6\s+address\s+(\S+)", rest)
    if m:
        cidr = m.group(1)
        try:
            host, plen = cidr.split("/")
            ip = norm_ipv6(host)
            iface.addresses.append(Address("v6", ip, int(plen), scope=v6_scope(ip)))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("junos inet6 address parse failed: %s (%s)" % (rest, e))
        return
    if re.match(r"^unit\s+\d+\s+family\s+ethernet-switching", rest):
        iface.l2_l3 = "l2"
        return


def parse_junos(text: str, warnings: list) -> Device:
    """JunOS set 形式 config を解析し正規化 Device を返す（要件書 §6.2）。

    パース失敗行は握りつぶし warnings(list) に文字列を追記し継続する（§6.3）。

    JunOS 固有の設計:
      - unit N address は base IF（ge-0/0/0.0 → ge-0/0/0）に集約（§6.2）
      - L2/L3: ethernet-switching → l2。L2 は L3 より優先（§6.2）
      - switchport は常に None（JunOS には IOS の switchport 概念がない）
      - OSPF network は全 IF 確定後に解決（宣言前に address が来る場合に対応）
      - routing-options router-id は bgp_router_id に設定し、
        OSPF 専用 router-id 不在時のフォールバックにも使用（§5.2.1）
      - interfaces は初出現順で確定（決定性保証）
    """
    dev = Device(hostname="", vendor="juniper_junos")
    ifaces: dict[str, Interface] = {}   # name → Interface（出現順保持）
    ospf_decls: list[tuple] = []        # (area, base_if, af) — 全 IF 確定後に解決
    bgp_neighbors: dict[str, BgpNeighbor] = {}  # nip → BgpNeighbor（update_source 後付け用）
    pending_local_address: dict[str, str] = {}   # nip → local-address（peer-as より先に来た場合）
    area_types: dict[tuple[str, str], str] = {}  # {(norm_area, af): area_type_str} — 末尾で適用
    bgp_neighbor_group: dict[str, str] = {}      # nip → group name（cluster/group-peer-as 後付け適用用）
    cluster_groups: set[str] = set()             # cluster 宣言を持つ group 集合
    group_peer_as: dict[str, int] = {}           # group name → peer-as（group レベル peer-as 継承用）

    def get_if(name: str) -> Interface:
        """ifaces dict から取得、未登録なら新規 Interface を作成する。"""
        if name not in ifaces:
            ifaces[name] = Interface(name=name)
        return ifaces[name]

    for raw in text.splitlines():
        if is_sensitive_line(raw):
            continue
        s = raw.strip()
        if not s.startswith("set "):
            continue
        body = s[4:].strip()

        # system host-name
        m = re.match(r"^system host-name\s+(\S+)", body)
        if m:
            dev.hostname = m.group(1).strip('"')
            continue

        # interfaces <name> <rest>
        m = re.match(r"^interfaces\s+(\S+)\s+(.*)$", body)
        if m:
            _parse_if_body(get_if(m.group(1)), m.group(2), warnings)
            continue

        # routing-options autonomous-system
        m = re.match(r"^routing-options autonomous-system\s+(\d+)", body)
        if m:
            dev.as_ = int(m.group(1))
            continue

        # routing-options router-id → bgp_router_id（OSPF フォールバックは末尾で設定）
        m = re.match(r"^routing-options router-id\s+(\S+)", body)
        if m:
            dev.bgp_router_id = m.group(1)
            continue

        # BGP neighbor: protocols bgp group <g> neighbor <ip> peer-as <asn>
        m = re.match(r"^protocols bgp group (\S+) neighbor\s+(\S+)\s+peer-as\s+(\d+)", body)
        if m:
            grp, ip, peer = m.group(1), m.group(2), int(m.group(3))
            try:
                af = "v6" if ":" in ip else "v4"
                nip = norm_ipv6(ip) if af == "v6" else norm_ipv4(ip)
                if nip in bgp_neighbors:
                    # neighbor のみ行（peer-as 無し）で先に BgpNeighbor 生成済みの場合は peer_as を更新
                    bgp_neighbors[nip].peer_as = peer
                else:
                    nb = BgpNeighbor(nip, peer, af)
                    # peer-as より先に local-address が来たケースを適用
                    if nip in pending_local_address:
                        nb.update_source = pending_local_address.pop(nip)
                    dev.bgp.append(nb)
                    bgp_neighbors[nip] = nb
                bgp_neighbor_group[nip] = grp   # group 名を記録（cluster/group-peer-as 後付け用）
                # 同一 neighbor IP が複数 group に跨るのは未定義（実 JunOS では発生しない・後勝ち。既存 update_source/local-address と一貫）
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos bgp neighbor parse failed: %s (%s)" % (body, e))
            continue

        # BGP neighbor のみ（peer-as 無し）: protocols bgp group <g> neighbor <ip>
        # group レベル peer-as を継承するメンバー neighbor（`set protocols bgp group <g> neighbor <ip>`）。
        # peer-as 有りパターンより後にマッチするよう配置（特異度: peer-as 有りを先にチェック済み）。
        m = re.match(r"^protocols bgp group (\S+) neighbor\s+(\S+)$", body)
        if m:
            grp, ip = m.group(1), m.group(2)
            try:
                af = "v6" if ":" in ip else "v4"
                nip = norm_ipv6(ip) if af == "v6" else norm_ipv4(ip)
                if nip not in bgp_neighbors:
                    nb = BgpNeighbor(nip, None, af)
                    if nip in pending_local_address:
                        nb.update_source = pending_local_address.pop(nip)
                    dev.bgp.append(nb)
                    bgp_neighbors[nip] = nb
                bgp_neighbor_group[nip] = grp
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos bgp neighbor (peer-as inherited from group) parse failed: %s (%s)" % (body, e))
            continue

        # BGP group レベル peer-as: protocols bgp group <g> peer-as <asn>（neighbor 無し）
        # group の全 neighbor に peer_as を補完する（末尾一括解決）。
        m = re.match(r"^protocols bgp group (\S+) peer-as\s+(\d+)$", body)
        if m:
            grp, peer = m.group(1), int(m.group(2))
            group_peer_as[grp] = peer
            continue

        # BGP cluster: protocols bgp group <g> cluster <cluster-id>
        # JunOS の route reflector は group に cluster を付けることで表現する。
        # cluster を持つ group に属する neighbor が route reflector client となる（§6.2）。
        # JunOS の next_hop_self はポリシーベースのため本実装では対象外（False 固定）。
        m = re.match(r"^protocols bgp group (\S+) cluster\s+\S+", body)
        if m:
            cluster_groups.add(m.group(1))
            continue

        # BGP local-address: protocols bgp group <g> neighbor <ip> local-address <localip>
        # JunOS local-address は BgpNeighbor.update_source に格納する（IP 直接指定）。
        # 孤立 pending local-address の挙動:
        #   対応する peer-as が最後まで現れなかった pending_local_address エントリは
        #   警告なくドロップされる（意図的）。既存の他パース失敗時の挙動（握りつぶし継続）と整合。
        m = re.match(r"^protocols bgp group \S+ neighbor\s+(\S+)\s+local-address\s+(\S+)", body)
        if m:
            ip, local_ip = m.group(1), m.group(2)
            try:
                nip = norm_ipv6(ip) if ":" in ip else norm_ipv4(ip)
                if nip in bgp_neighbors:
                    bgp_neighbors[nip].update_source = local_ip
                else:
                    # peer-as がまだ現れていない — pending に積む
                    pending_local_address[nip] = local_ip
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos bgp local-address parse failed: %s (%s)" % (body, e))
            continue

        # OSPFv2: protocols ospf area <a> interface <if> [metric <n> | interface-type <t> | passive]
        m = re.match(r"^protocols ospf area\s+(\S+)\s+interface\s+(\S+)(.*)$", body)
        if m:
            area_raw, ifname_raw, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
            base_if = _base_if(ifname_raw)
            ospf_decls.append((area_raw, base_if, "v4"))
            if rest:
                _apply_ospf_if_param(get_if(base_if), rest)
            continue

        # OSPFv2 area type: protocols ospf area <a> stub [no-summaries] / nssa [no-summaries]
        # 語境界付き: (stub|nssa) の直後は空白か行末のみ（stub-default-metric 等の誤マッチを防ぐ）
        m = re.match(r"^protocols ospf area\s+(\S+)\s+(stub|nssa)(\s.*|$)", body)
        if m:
            area_raw, kind, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
            norm_area = norm_ospf_area(area_raw)
            no_summaries = "no-summaries" in rest
            if kind == "stub":
                area_types[(norm_area, "v4")] = "totally-stubby" if no_summaries else "stub"
            else:  # nssa
                area_types[(norm_area, "v4")] = "totally-nssa" if no_summaries else "nssa"
            continue

        # OSPFv3: protocols ospf3 area <a> interface <if> [metric <n> | interface-type <t> | passive]
        m = re.match(r"^protocols ospf3 area\s+(\S+)\s+interface\s+(\S+)(.*)$", body)
        if m:
            area_raw, ifname_raw, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
            base_if = _base_if(ifname_raw)
            ospf_decls.append((area_raw, base_if, "v6"))
            if rest:
                _apply_ospf_if_param(get_if(base_if), rest)
            continue

        # OSPFv3 area type: protocols ospf3 area <a> stub [no-summaries] / nssa [no-summaries]
        # 語境界付き: (stub|nssa) の直後は空白か行末のみ（stub-default-metric 等の誤マッチを防ぐ）
        m = re.match(r"^protocols ospf3 area\s+(\S+)\s+(stub|nssa)(\s.*|$)", body)
        if m:
            area_raw, kind, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
            norm_area = norm_ospf_area(area_raw)
            no_summaries = "no-summaries" in rest
            if kind == "stub":
                area_types[(norm_area, "v6")] = "totally-stubby" if no_summaries else "stub"
            else:  # nssa
                area_types[(norm_area, "v6")] = "totally-nssa" if no_summaries else "nssa"
            continue

        # v6 static route: routing-options rib inet6.0 static route <pfx> next-hop <nh>
        m = re.match(
            r"^routing-options rib inet6\.0 static route\s+(\S+)\s+next-hop\s+(\S+)", body
        )
        if m:
            pfx, nh = m.groups()
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv6(nh), "v6"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos v6 static parse failed: %s (%s)" % (body, e))
            continue

        # v4 static route: routing-options static route <pfx> next-hop <nh>
        m = re.match(r"^routing-options static route\s+(\S+)\s+next-hop\s+(\S+)", body)
        if m:
            pfx, nh = m.groups()
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv4(nh), "v4"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos static parse failed: %s (%s)" % (body, e))
            continue

    # cluster を持つ group の neighbor に route_reflector_client=True を設定（末尾一括適用）
    # JunOS の next_hop_self はポリシーベースのため本実装では対象外（False 固定・docstring 明記）
    # group レベル peer-as: peer_as が None のメンバー neighbor に group_peer_as を補完（個別指定が優先）
    if cluster_groups or group_peer_as:
        for nip, nb in bgp_neighbors.items():
            grp = bgp_neighbor_group.get(nip)
            if grp:
                if cluster_groups and grp in cluster_groups:
                    nb.route_reflector_client = True
                if group_peer_as and nb.peer_as is None and grp in group_peer_as:
                    nb.peer_as = group_peer_as[grp]

    # OSPF network を全 IF 確定後に解決（宣言前 address 対応）
    for area, base_if, af in ospf_decls:
        if af == "v4":
            network = _ospf_v4_network(ifaces.get(base_if)) or base_if
        else:
            network = base_if
        dev.ospf.append(OspfNetwork(None, network, norm_ospf_area(area), af))
    # area_types: 収集した (norm_area, af)→type を同一 area+af の OspfNetwork に適用
    if area_types:
        for o in dev.ospf:
            key = (o.area, o.af)
            if key in area_types:
                o.area_type = area_types[key]

    # admin_status 確定・出現順で interfaces 確定
    for iface in ifaces.values():
        iface.admin_status = "down" if iface.shutdown else "up"
        dev.interfaces.append(iface)

    # OSPF 専用 router-id 不在時は routing-options router-id をフォールバック（§5.2.1）
    if dev.ospf_router_id is None:
        dev.ospf_router_id = dev.bgp_router_id

    return dev
