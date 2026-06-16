"""Juniper JunOS（set 形式）パーサ（要件書 §6.2）。"""
import re

from ..models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from ..normalize import norm_cidr_str, norm_ipv4, norm_ipv6, norm_ospf_area, v6_scope
from .base import ensure_ospf, is_sensitive_line


def _check_apply_groups(lines: list, diagnostics: list, filename) -> None:
    """parse_junos が収集した全行から groups 多用を検査し診断を追加する（#2）。

    閾値（決定的固定値）:
      - groups 系行（set groups / set apply-groups）を groups_count とする。
      - 実体行（interfaces / protocols / routing-options / routing-instances で始まる set 行）
        を body_count とする。
      - groups_count >= body_count * 0.5 かつ groups_count >= 3 → 多用と判定。

    偽陽性抑制: 実体行数が 0 のとき（= 完全に groups のみの config は実用的にあり得ないため）
    body_count=0 でも groups_count >= 3 なら警告する。
    通常の JunOS set config（groups 不使用）では groups_count=0 → 条件不成立・警告なし。
    """
    groups_count = 0
    body_count = 0
    # body 実体プレフィックス（set の後に続く最初のトークン）
    BODY_PREFIXES = (
        "interfaces ", "protocols ", "routing-options ",
        "routing-instances ", "policy-options ",
    )
    for raw in lines:
        s = raw.strip()
        if not s.startswith("set "):
            continue
        body = s[4:].strip()
        if body.startswith("groups ") or body.startswith("apply-groups "):
            groups_count += 1
        elif any(body.startswith(p) for p in BODY_PREFIXES):
            body_count += 1

    if groups_count < 3:
        return
    if body_count > 0 and groups_count < body_count * 0.5:
        return

    refs = [filename] if filename is not None else []
    diagnostics.append({
        "severity": "warning",
        "kind": "junos_apply_groups_unexpanded",
        "message": (
            "apply-groups/groups を多用した config です。"
            "`show configuration | display inheritance | display set` で展開した出力を"
            "渡すと取りこぼしを防げます。"
        ),
        "refs": refs,
    })


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


def _parse_if_body(iface: Interface, rest: str, warnings: list) -> bool:
    """`set interfaces <if> <rest>` の <rest> を解析し iface をミューテートする（§6.2）。

    認識できない行は無視する（クラッシュしない）。パース失敗は warnings へ追記する（§6.3）。
    認識した（パターン一致した）場合 True、未対応は False を返す（parse 状態判定用）。
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
        return True
    if rest == "disable":
        iface.shutdown = True
        return True
    m = re.match(r"^mtu\s+(\d+)", rest)
    if m:
        iface.mtu = int(m.group(1))
        return True
    m = re.match(r"^speed\s+(\S+)", rest)
    if m:
        iface.speed = m.group(1)
        return True
    m = re.match(r"^encapsulation\s+(\S+)", rest)
    if m:
        iface.encapsulation = m.group(1)
        return True
    m = re.match(r"^unit\s+\d+\s+family\s+inet\s+address\s+(\S+)", rest)
    if m:
        cidr = m.group(1)
        try:
            host, plen = cidr.split("/")
            iface.addresses.append(Address("v4", norm_ipv4(host), int(plen)))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("junos inet address parse failed: %s (%s)" % (rest, e))
        return True
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
        return True
    if re.match(r"^unit\s+\d+\s+family\s+ethernet-switching", rest):
        iface.l2_l3 = "l2"
        return True
    return False


def parse_junos(text: str, warnings: list, line_status=None, diagnostics=None, filename=None) -> Device:
    """JunOS set 形式 config を解析し正規化 Device を返す（要件書 §6.2）。

    パース失敗行は握りつぶし warnings(list) に文字列を追記し継続する（§6.3）。

    line_status: 任意の出力リスト。指定時は各行を "parsed"/"ignored"/"unparsed" で分類し
    末尾で extend する。非 set 行（コメント/空行等）は "ignored"。**未指定時はモデル出力は従来通り**。

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
    ospf_decls: list[tuple] = []        # (area, base_if, af, rest) — 全 IF 確定後に解決
    bgp_neighbors: dict[tuple, BgpNeighbor] = {}  # (vrf, nip) → BgpNeighbor（vrf=None は global）
    pending_local_address: dict[tuple, str] = {}   # (vrf, nip) → local-address（peer-as より先に来た場合）
    area_types: dict[tuple[str, str], str] = {}  # {(norm_area, af): area_type_str} — 末尾で適用
    bgp_neighbor_group: dict[tuple, str] = {}    # (vrf, nip) → group name（cluster/group-peer-as 後付け適用用）
    cluster_groups: set[str] = set()             # cluster 宣言を持つ group 集合
    group_peer_as: dict[str, int] = {}           # group name → peer-as（group レベル peer-as 継承用）
    group_type: dict[str, str] = {}              # group name → "ibgp"/"ebgp"（group type internal/external）
    group_local_as: dict[str, int] = {}          # group name → local-as（group レベル local-as 継承用）
    neighbor_local_as: dict[str, int] = {}       # nip → local-as（neighbor 個別 local-as）

    def get_if(name: str) -> Interface:
        """ifaces dict から取得、未登録なら新規 Interface を作成する。"""
        if name not in ifaces:
            ifaces[name] = Interface(name=name)
        return ifaces[name]

    lines = text.splitlines()
    status = ["unparsed"] * len(lines)   # 既定は未対応。set 行は楽観的に parsed、未マッチ末尾で unparsed に戻す

    for i, raw in enumerate(lines):
        if is_sensitive_line(raw):
            # 機密行は意図的にパースしない設計 → "ignored"（見落とし候補=unparsed には含めない）
            status[i] = "ignored"
            continue
        s = raw.strip()
        if not s.startswith("set "):
            status[i] = "ignored"   # 非 set 行（コメント/空行/他ディレクティブ）はパース対象外
            continue
        body = s[4:].strip()
        status[i] = "parsed"        # set 行は楽観的に parsed（どのハンドラにも一致しなければ末尾で unparsed）

        # system host-name
        m = re.match(r"^system host-name\s+(\S+)", body)
        if m:
            dev.hostname = m.group(1).strip('"')
            continue

        # interfaces <name> <rest>
        m = re.match(r"^interfaces\s+(\S+)\s+(.*)$", body)
        if m:
            # interfaces 行と認識しても body（サブコマンド）が未対応なら unparsed（突合の正確性）
            status[i] = "parsed" if _parse_if_body(get_if(m.group(1)), m.group(2), warnings) else "unparsed"
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
                key = (None, nip)   # global は vrf=None
                if key in bgp_neighbors:
                    # neighbor のみ行（peer-as 無し）で先に BgpNeighbor 生成済みの場合は peer_as を更新
                    bgp_neighbors[key].peer_as = peer
                else:
                    nb = BgpNeighbor(nip, peer, af)
                    # peer-as より先に local-address が来たケースを適用
                    if key in pending_local_address:
                        nb.update_source = pending_local_address.pop(key)
                    dev.bgp.append(nb)
                    bgp_neighbors[key] = nb
                bgp_neighbor_group[key] = grp   # group 名を記録（cluster/group-peer-as 後付け用）
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
                key = (None, nip)   # global は vrf=None
                if key not in bgp_neighbors:
                    nb = BgpNeighbor(nip, None, af)
                    if key in pending_local_address:
                        nb.update_source = pending_local_address.pop(key)
                    dev.bgp.append(nb)
                    bgp_neighbors[key] = nb
                bgp_neighbor_group[key] = grp
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

        # BGP group type: protocols bgp group <g> type (internal|external)
        # internal → "ibgp"、external → "ebgp"。group→member 末尾一括継承。
        m = re.match(r"^protocols bgp group (\S+) type (internal|external)$", body)
        if m:
            grp, tval = m.group(1), m.group(2)
            group_type[grp] = "ibgp" if tval == "internal" else "ebgp"
            continue

        # BGP group level local-as: protocols bgp group <g> local-as <asn>
        # group の全 neighbor に local_as を補完する（末尾一括解決）。
        m = re.match(r"^protocols bgp group (\S+) local-as\s+(\d+)$", body)
        if m:
            grp, asn = m.group(1), int(m.group(2))
            group_local_as[grp] = asn
            continue

        # BGP neighbor level local-as: protocols bgp group <g> neighbor <ip> local-as <asn>
        # neighbor 個別指定は group 値より優先（末尾一括解決）。
        m = re.match(r"^protocols bgp group \S+ neighbor\s+(\S+)\s+local-as\s+(\d+)$", body)
        if m:
            ip, asn = m.group(1), int(m.group(2))
            try:
                nip = norm_ipv6(ip) if ":" in ip else norm_ipv4(ip)
                neighbor_local_as[nip] = asn
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos bgp neighbor local-as parse failed: %s (%s)" % (body, e))
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
                key = (None, nip)   # global は vrf=None
                if key in bgp_neighbors:
                    bgp_neighbors[key].update_source = local_ip
                else:
                    # peer-as がまだ現れていない — pending に積む
                    pending_local_address[key] = local_ip
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos bgp local-address parse failed: %s (%s)" % (body, e))
            continue

        # OSPFv2: protocols ospf area <a> interface <if> [metric <n> | interface-type <t> | passive]
        m = re.match(r"^protocols ospf area\s+(\S+)\s+interface\s+(\S+)(.*)$", body)
        if m:
            area_raw, ifname_raw, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
            base_if = _base_if(ifname_raw)
            ospf_decls.append((area_raw, base_if, "v4", rest))
            # "all" の場合はパラメータ適用を末尾解決（全 IF 確定後）まで保留する
            if rest and base_if != "all":
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
            ospf_decls.append((area_raw, base_if, "v6", rest))
            # "all" の場合はパラメータ適用を末尾解決（全 IF 確定後）まで保留する
            if rest and base_if != "all":
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

        # v6 static discard/reject: routing-options rib inet6.0 static route <pfx> discard|reject
        m = re.match(
            r"^routing-options rib inet6\.0 static route\s+(\S+)\s+(discard|reject)(?:\s|$)", body
        )
        if m:
            pfx, action = m.group(1), m.group(2)
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), action, "v6"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos v6 static %s parse failed: %s (%s)" % (action, body, e))
            continue

        # v6 qualified-next-hop: routing-options rib inet6.0 static route <pfx> qualified-next-hop <nh> [...]
        m = re.match(
            r"^routing-options rib inet6\.0 static route\s+(\S+)\s+qualified-next-hop\s+(\S+)", body
        )
        if m:
            pfx, nh = m.group(1), m.group(2)
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv6(nh), "v6"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos v6 static qualified-next-hop parse failed: %s (%s)" % (body, e))
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

        # v4 static discard/reject: routing-options static route <pfx> discard|reject
        m = re.match(
            r"^routing-options static route\s+(\S+)\s+(discard|reject)(?:\s|$)", body
        )
        if m:
            pfx, action = m.group(1), m.group(2)
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), action, "v4"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos static %s parse failed: %s (%s)" % (action, body, e))
            continue

        # v4 qualified-next-hop: routing-options static route <pfx> qualified-next-hop <nh> [metric N|...]
        m = re.match(
            r"^routing-options static route\s+(\S+)\s+qualified-next-hop\s+(\S+)", body
        )
        if m:
            pfx, nh = m.group(1), m.group(2)
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv4(nh), "v4"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos static qualified-next-hop parse failed: %s (%s)" % (body, e))
            continue

        # routing-instances <vrf> interface <ifname>
        # → 当該 IF の Interface.vrf を設定（IF 自体は interfaces ハンドラで登録済みであること前提）
        m = re.match(r"^routing-instances\s+(\S+)\s+interface\s+(\S+)$", body)
        if m:
            vrf_name, ifname_raw = m.group(1), m.group(2)
            base_if = _base_if(ifname_raw)
            get_if(base_if).vrf = vrf_name
            continue

        # routing-instances <vrf> routing-options static route <pfx> next-hop <nh>
        m = re.match(
            r"^routing-instances\s+(\S+)\s+routing-options\s+static\s+route\s+(\S+)\s+next-hop\s+(\S+)",
            body
        )
        if m:
            vrf_name, pfx, nh = m.group(1), m.group(2), m.group(3)
            af = "v6" if ":" in pfx else "v4"
            try:
                if af == "v6":
                    dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv6(nh), "v6", vrf=vrf_name))
                else:
                    dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv4(nh), "v4", vrf=vrf_name))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos ri static next-hop parse failed: %s (%s)" % (body, e))
            continue

        # routing-instances <vrf> routing-options static route <pfx> discard|reject
        m = re.match(
            r"^routing-instances\s+(\S+)\s+routing-options\s+static\s+route\s+(\S+)\s+(discard|reject)(?:\s|$)",
            body
        )
        if m:
            vrf_name, pfx, action = m.group(1), m.group(2), m.group(3)
            af = "v6" if ":" in pfx else "v4"
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), action, af, vrf=vrf_name))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos ri static %s parse failed: %s (%s)" % (action, body, e))
            continue

        # routing-instances <vrf> routing-options static route <pfx> qualified-next-hop <nh>
        m = re.match(
            r"^routing-instances\s+(\S+)\s+routing-options\s+static\s+route\s+(\S+)\s+qualified-next-hop\s+(\S+)",
            body
        )
        if m:
            vrf_name, pfx, nh = m.group(1), m.group(2), m.group(3)
            af = "v6" if ":" in pfx else "v4"
            try:
                if af == "v6":
                    dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv6(nh), "v6", vrf=vrf_name))
                else:
                    dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv4(nh), "v4", vrf=vrf_name))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos ri static qnh parse failed: %s (%s)" % (body, e))
            continue

        # routing-instances <vrf> routing-options rib <rib_name> static route <pfx> next-hop <nh>
        # rib 名に "inet6" が含まれる場合のみ v6、それ以外は v4 として処理する。
        m = re.match(
            r"^routing-instances\s+(\S+)\s+routing-options\s+rib\s+(\S+)\s+static\s+route\s+(\S+)\s+next-hop\s+(\S+)",
            body
        )
        if m:
            vrf_name, rib_name, pfx, nh = m.group(1), m.group(2), m.group(3), m.group(4)
            af = "v6" if "inet6" in rib_name else "v4"
            try:
                if af == "v6":
                    dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv6(nh), "v6", vrf=vrf_name))
                else:
                    dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv4(nh), "v4", vrf=vrf_name))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos ri rib next-hop parse failed: %s (%s)" % (body, e))
            continue

        # routing-instances <vrf> routing-options rib <rib_name> static route <pfx> discard|reject
        m = re.match(
            r"^routing-instances\s+(\S+)\s+routing-options\s+rib\s+(\S+)\s+static\s+route\s+(\S+)\s+(discard|reject)(?:\s|$)",
            body
        )
        if m:
            vrf_name, rib_name, pfx, action = m.group(1), m.group(2), m.group(3), m.group(4)
            af = "v6" if "inet6" in rib_name else "v4"
            try:
                dev.static.append(StaticRoute(norm_cidr_str(pfx), action, af, vrf=vrf_name))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos ri rib static %s parse failed: %s (%s)" % (action, body, e))
            continue

        # routing-instances <vrf> routing-options rib <rib_name> static route <pfx> qualified-next-hop <nh>
        m = re.match(
            r"^routing-instances\s+(\S+)\s+routing-options\s+rib\s+(\S+)\s+static\s+route\s+(\S+)\s+qualified-next-hop\s+(\S+)",
            body
        )
        if m:
            vrf_name, rib_name, pfx, nh = m.group(1), m.group(2), m.group(3), m.group(4)
            af = "v6" if "inet6" in rib_name else "v4"
            try:
                if af == "v6":
                    dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv6(nh), "v6", vrf=vrf_name))
                else:
                    dev.static.append(StaticRoute(norm_cidr_str(pfx), norm_ipv4(nh), "v4", vrf=vrf_name))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos ri rib qnh parse failed: %s (%s)" % (body, e))
            continue

        # routing-instances <vrf> protocols bgp group <g> neighbor <ip> peer-as <asn>
        m = re.match(
            r"^routing-instances\s+(\S+)\s+protocols bgp group (\S+) neighbor\s+(\S+)\s+peer-as\s+(\d+)",
            body
        )
        if m:
            vrf_name, grp, ip, peer = m.group(1), m.group(2), m.group(3), int(m.group(4))
            try:
                af = "v6" if ":" in ip else "v4"
                nip = norm_ipv6(ip) if af == "v6" else norm_ipv4(ip)
                key = (vrf_name, nip)   # VRF ごとに独立したキー（global と同 IP でも別エントリ）
                nb = BgpNeighbor(nip, peer, af, vrf=vrf_name)
                if key in pending_local_address:
                    nb.update_source = pending_local_address.pop(key)
                dev.bgp.append(nb)
                bgp_neighbors[key] = nb
                bgp_neighbor_group[key] = grp
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos ri bgp neighbor parse failed: %s (%s)" % (body, e))
            continue

        # routing-instances <vrf> protocols bgp group <g> neighbor <ip>（peer-as は group 継承）
        m = re.match(
            r"^routing-instances\s+(\S+)\s+protocols bgp group (\S+) neighbor\s+(\S+)$",
            body
        )
        if m:
            vrf_name, grp, ip = m.group(1), m.group(2), m.group(3)
            try:
                af = "v6" if ":" in ip else "v4"
                nip = norm_ipv6(ip) if af == "v6" else norm_ipv4(ip)
                key = (vrf_name, nip)
                if key not in bgp_neighbors:
                    nb = BgpNeighbor(nip, None, af, vrf=vrf_name)
                    if key in pending_local_address:
                        nb.update_source = pending_local_address.pop(key)
                    dev.bgp.append(nb)
                    bgp_neighbors[key] = nb
                bgp_neighbor_group[key] = grp
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos ri bgp neighbor (peer-as inherited) parse failed: %s (%s)" % (body, e))
            continue

        # routing-instances <vrf> protocols bgp group <g> peer-as <asn>（group レベル peer-as）
        m = re.match(
            r"^routing-instances\s+\S+\s+protocols bgp group (\S+) peer-as\s+(\d+)$",
            body
        )
        if m:
            grp, peer = m.group(1), int(m.group(2))
            group_peer_as[grp] = peer
            continue

        # routing-instances <vrf> protocols bgp group <g> type (internal|external)（VRF BGP group type）
        m = re.match(
            r"^routing-instances\s+\S+\s+protocols bgp group (\S+) type (internal|external)$",
            body
        )
        if m:
            grp, tval = m.group(1), m.group(2)
            group_type[grp] = "ibgp" if tval == "internal" else "ebgp"
            continue

        # routing-instances <vrf> protocols bgp group <g> cluster <id>（VRF BGP cluster）
        m = re.match(
            r"^routing-instances\s+\S+\s+protocols bgp group (\S+) cluster\s+\S+",
            body
        )
        if m:
            cluster_groups.add(m.group(1))
            continue

        # どのハンドラにも一致しなかった set 行 = 未対応（見落とし候補）
        status[i] = "unparsed"

    if line_status is not None:
        line_status.extend(status)

    # cluster を持つ group の neighbor に route_reflector_client=True を設定（末尾一括適用）
    # JunOS の next_hop_self はポリシーベースのため本実装では対象外（False 固定・docstring 明記）
    # group レベル peer-as: peer_as が None のメンバー neighbor に group_peer_as を補完（個別指定が優先）
    if cluster_groups or group_peer_as or group_type or group_local_as or neighbor_local_as:
        for (vrf_k, nip), nb in bgp_neighbors.items():
            grp = bgp_neighbor_group.get((vrf_k, nip))
            if grp:
                if cluster_groups and grp in cluster_groups:
                    nb.route_reflector_client = True
                if group_peer_as and nb.peer_as is None and grp in group_peer_as:
                    nb.peer_as = group_peer_as[grp]
                if group_type and grp in group_type and nb.bgp_type is None:
                    nb.bgp_type = group_type[grp]
                if group_local_as and grp in group_local_as and nb.local_as is None:
                    nb.local_as = group_local_as[grp]
            # neighbor 個別 local-as は group 値より優先（後勝ち）
            if neighbor_local_as and nip in neighbor_local_as:
                nb.local_as = neighbor_local_as[nip]

    # OSPF network を全 IF 確定後に解決（宣言前 address 対応）
    for area, base_if, af, rest in ospf_decls:
        if base_if == "all":
            # "interface all": 当該 af を持つ L3 IF（addresses あり）へ出現順に展開
            for iface in ifaces.values():
                has_af = any(a.af == af for a in iface.addresses)
                if not has_af:
                    continue
                if rest:
                    _apply_ospf_if_param(iface, rest)
                if af == "v4":
                    network = _ospf_v4_network(iface) or iface.name
                else:
                    network = iface.name
                dev.ospf.append(OspfNetwork(None, network, norm_ospf_area(area), af))
        else:
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

    # #2 apply-groups 多用診断（diagnostics リスト指定時のみ評価・後方互換）
    if diagnostics is not None:
        _check_apply_groups(lines, diagnostics, filename)

    return dev
