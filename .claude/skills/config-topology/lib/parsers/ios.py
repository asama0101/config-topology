"""Cisco IOS / IOS-XE パーサ（要件書 §6.1）。"""
import re

from ..models import Address, BgpNeighbor, Device, Interface, OspfNetwork, Redistribute, StaticRoute
from ..normalize import (mask_to_prefix, norm_cidr, norm_cidr_str, norm_ipv4,
                         norm_ipv6, norm_ospf_area, v6_scope, wildcard_to_prefix)
from .base import ensure_ospf, is_sensitive_line


def _set_l3(iface: Interface) -> None:
    """iface を L3 としてマークする（§6.1 L3/L2 優先度: L3 は無条件上書き）。"""
    iface.l2_l3 = "l3"   # L3 は switchport より優先（無条件上書き）


def _set_l2(iface: Interface) -> None:
    """iface を L2 としてマークする（§6.1 L2/L3 優先度: L3 が既にあれば変更しない）。"""
    if iface.l2_l3 != "l3":   # L3 が既にあれば L2 にしない
        iface.l2_l3 = "l2"


def _ensure_switchport(iface: Interface) -> None:
    """switchport が未初期化なら空 dict で初期化する。"""
    if iface.switchport is None:
        iface.switchport = {}


def _iface_v6_network(iface: Interface):
    """IF の最初のグローバル v6 アドレスのサブネットを返す（§6.1）。無ければ None。"""
    for a in iface.sorted_addresses():
        if a.af == "v6" and a.scope != "link-local":
            return norm_cidr_str("%s/%s" % (a.ip, a.prefix))
    return None


def _parse_iface_line(iface: Interface, s: str, warnings: list) -> None:
    """interface ブロック内の1行 s を解析し iface をミューテートする（§6.1）。失敗は warnings へ。"""
    m = re.match(r"^description\s+(.*)$", s)
    if m:
        iface.description = m.group(1).strip().strip('"')
        return
    m = re.match(r"^ip address\s+(\S+)\s+(\S+)(\s+secondary)?\s*$", s)
    if m:
        ip, mask, sec = m.group(1), m.group(2), bool(m.group(3))
        try:
            iface.addresses.append(Address("v4", norm_ipv4(ip), mask_to_prefix(mask),
                                            secondary=sec))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("ip address parse failed: %s (%s)" % (s, e))
        return
    m = re.match(r"^ipv6 address\s+(\S+)(\s+link-local)?\s*$", s, re.IGNORECASE)
    if m:
        cidr, ll = m.group(1), bool(m.group(2))
        try:
            host, plen = cidr.split("/")
            ip = norm_ipv6(host)
            scope = "link-local" if ll else v6_scope(ip)
            iface.addresses.append(Address("v6", ip, int(plen), scope=scope))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("ipv6 address parse failed: %s (%s)" % (s, e))
        return
    if s == "shutdown":
        iface.shutdown = True
        return
    if s == "no shutdown":
        iface.shutdown = False
        return
    if s == "no switchport":
        _set_l3(iface)
        return
    m = re.match(r"^mtu\s+(\d+)", s)
    if m:
        iface.mtu = int(m.group(1))
        return
    m = re.match(r"^speed\s+(\S+)", s)
    if m:
        iface.speed = m.group(1)
        return
    m = re.match(r"^duplex\s+(\S+)", s)
    if m:
        iface.duplex = m.group(1)
        return
    m = re.match(r"^encapsulation\s+dot1q\b", s, re.IGNORECASE)
    if m:
        iface.encapsulation = "dot1q"
        return
    m = re.match(r"^switchport mode\s+(access|trunk)", s)
    if m:
        _ensure_switchport(iface)
        iface.switchport["mode"] = m.group(1)
        _set_l2(iface)
        return
    m = re.match(r"^switchport access vlan\s+(\d+)", s)
    if m:
        _ensure_switchport(iface)
        iface.switchport["access_vlan"] = int(m.group(1))
        _set_l2(iface)
        return
    m = re.match(r"^switchport trunk allowed vlan\s+(\S+)", s)
    if m:
        _ensure_switchport(iface)
        iface.switchport["trunk_vlans"] = m.group(1)
        _set_l2(iface)
        return
    m = re.match(r"^ip ospf cost\s+(\d+)", s)
    if m:
        ensure_ospf(iface)["cost"] = int(m.group(1))
        return
    m = re.match(r"^ip ospf network\s+(\S+)", s)
    if m:
        ensure_ospf(iface)["network_type"] = m.group(1)
        return


def _parse_redistribute_line(dev: Device, s: str, into: str) -> bool:
    """router bgp / router ospf ブロック内の redistribute 行を解析する（§6.1 C5）。

    `redistribute <source> [<process/AS>] [metric <n>] [route-map <name>] [subnets ...]`
    - into:   現在の文脈（"bgp" または "ospf"）。
    - source: 直後のトークン（connected / static / ospf / bgp / rip / eigrp / isis 等）。
    - metric: `metric <整数>` があれば int。
    - route_map: `route-map <名前>` があれば文字列。
    - `no redistribute ...` は対象外（呼出し元でフィルタ済み）。
    - プロセス ID / AS 番号（source の直後のトークン）や subnets 等は無視。

    認識した場合は True を返す（_parse_bgp_line / _parse_ospf_line の早期リターン用）。
    """
    m = re.match(r"^redistribute\s+(\S+)(.*)", s)
    if not m:
        return False
    source = m.group(1)
    rest = m.group(2)
    # metric を抽出
    metric = None
    mm = re.search(r"\bmetric\s+(\d+)\b", rest)
    if mm:
        metric = int(mm.group(1))
    # route-map を抽出
    route_map = None
    rm = re.search(r"\broute-map\s+(\S+)", rest)
    if rm:
        route_map = rm.group(1)
    dev.redistribute.append(Redistribute(into, source, metric, route_map))
    return True


def _parse_bgp_line(dev: Device, s: str, bgp_af: str, bgp: dict,
                    warnings: list) -> None:
    """router bgp ブロック内の1行を解析（§6.1）。neighbor / bgp router-id / v6 activate /
    update-source / route-reflector-client / next-hop-self / timers / send-community /
    peer-group 宣言・メンバー割当 / redistribute。

    bgp: BGP パース状態コンテナ（parse_ios から渡される）。
      {
        "neighbors":   {nip: BgpNeighbor},         — 登録済み neighbor
        "pending_attrs": {nip: {key: val}},         — remote-as より先に来た属性を一時保持
        "pg_template": {pgname: {key: val}},        — peer-group 属性テンプレート
                       共通キー: remote_as/update_source/rr/nhs/timers/send_community
        "pg_member":   {nip: pgname},               — nip → 所属 peer-group 名
      }
      キーの対応: pending_attrs/pg_template 共通: rr=route-reflector-client, nhs=next-hop-self。

    peer-group メンバー BgpNeighbor の生成は末尾解決に遅延する（parse_ios 末尾参照）。
    メンバー割当行ハンドラは pg_member に記録するだけで BgpNeighbor を生成しない。
    これにより未定義 peer-group かつ個別情報なしのゾンビ neighbor を排除する。

    孤立 pending の挙動:
      対応する remote-as が最後まで現れなかった pending エントリは
      警告なくドロップされる（意図的）。既存の他パース失敗時の挙動（握りつぶし継続）と整合。
    """
    neighbors = bgp["neighbors"]
    pending_attrs = bgp["pending_attrs"]
    pg_template = bgp["pg_template"]
    pg_member = bgp["pg_member"]

    m = re.match(r"^bgp router-id\s+(\S+)", s)
    if m:
        dev.bgp_router_id = m.group(1)
        return
    m = re.match(r"^neighbor\s+(\S+)\s+remote-as\s+(\d+)", s)
    if m:
        token, peer = m.group(1), int(m.group(2))
        # token が IP かどうか判別して振り分け
        try:
            af = "v6" if ":" in token else "v4"
            nip = norm_ipv6(token) if af == "v6" else norm_ipv4(token)
            # IP として解析成功 → 通常の neighbor remote-as
            if nip in neighbors:
                # すでに BgpNeighbor が存在する（peer-group メンバー行で生成済み）→ peer_as を設定
                neighbors[nip].peer_as = peer
            else:
                nb = BgpNeighbor(nip, peer, af)
                # remote-as より先に来た属性を pending_attrs から取り出して適用
                attrs = pending_attrs.pop(nip, {})
                if "update_source" in attrs:
                    nb.update_source = attrs["update_source"]
                if attrs.get("rr"):
                    nb.route_reflector_client = True
                if attrs.get("nhs"):
                    nb.next_hop_self = True
                if "timers" in attrs:
                    nb.timers = attrs["timers"]
                if "send_community" in attrs:
                    nb.send_community = attrs["send_community"]
                dev.bgp.append(nb)
                neighbors[nip] = nb
        except Exception:                            # noqa: BLE001
            # IP として解析できない → peer-group 名として pg_template に格納
            pgname = token
            pg_template.setdefault(pgname, {})["remote_as"] = peer
        return
    # peer-group メンバー割当: neighbor <ip> peer-group <pgname>
    # BgpNeighbor の生成は末尾解決に遅延する（ゾンビ排除のため）。
    # ここでは pg_member に記録するだけで BgpNeighbor を生成しない。
    m = re.match(r"^neighbor\s+(\S+)\s+peer-group\s+(\S+)$", s)
    if m:
        token, pgname = m.group(1), m.group(2)
        try:
            nip = norm_ipv6(token) if ":" in token else norm_ipv4(token)
            pg_member[nip] = pgname
            # BgpNeighbor 生成は parse_ios 末尾の pg_member 解決ループで行う
        except Exception as e:                       # noqa: BLE001
            warnings.append("bgp peer-group member parse failed: %s (%s)" % (s, e))
        return
    # peer-group 宣言: neighbor <pgname> peer-group（末尾に名前なし）
    m = re.match(r"^neighbor\s+(\S+)\s+peer-group$", s)
    if m:
        pgname = m.group(1)
        pg_template.setdefault(pgname, {})  # キー確保のみ
        return
    m = re.match(r"^neighbor\s+(\S+)\s+activate", s)
    if m and bgp_af == "v6" and ":" in m.group(1):
        try:
            nip = norm_ipv6(m.group(1))
            if nip in neighbors:
                neighbors[nip].af = "v6"
        except Exception as e:                       # noqa: BLE001
            warnings.append("bgp activate parse failed: %s (%s)" % (s, e))
        return
    m = re.match(r"^neighbor\s+(\S+)\s+update-source\s+(\S+)", s)
    if m:
        token, ifname = m.group(1), m.group(2)
        try:
            nip = norm_ipv6(token) if ":" in token else norm_ipv4(token)
            if nip in neighbors:
                neighbors[nip].update_source = ifname
            else:
                pending_attrs.setdefault(nip, {})["update_source"] = ifname
        except Exception:                            # noqa: BLE001
            # IP でない → peer-group 名として pg_template に格納
            pg_template.setdefault(token, {})["update_source"] = ifname
        return
    m = re.match(r"^neighbor\s+(\S+)\s+route-reflector-client\b", s)
    if m:
        token = m.group(1)
        try:
            nip = norm_ipv6(token) if ":" in token else norm_ipv4(token)
            if nip in neighbors:
                neighbors[nip].route_reflector_client = True
            else:
                pending_attrs.setdefault(nip, {})["rr"] = True
        except Exception:                            # noqa: BLE001
            pg_template.setdefault(token, {})["rr"] = True
        return
    m = re.match(r"^neighbor\s+(\S+)\s+next-hop-self\b", s)
    if m:
        token = m.group(1)
        try:
            nip = norm_ipv6(token) if ":" in token else norm_ipv4(token)
            if nip in neighbors:
                neighbors[nip].next_hop_self = True
            else:
                pending_attrs.setdefault(nip, {})["nhs"] = True
        except Exception:                            # noqa: BLE001
            pg_template.setdefault(token, {})["nhs"] = True
        return
    m = re.match(r"^neighbor\s+(\S+)\s+timers\s+(\d+)\s+(\d+)", s)
    if m:
        token, ka, hold = m.group(1), int(m.group(2)), int(m.group(3))
        try:
            nip = norm_ipv6(token) if ":" in token else norm_ipv4(token)
            if nip in neighbors:
                neighbors[nip].timers = (ka, hold)
            else:
                pending_attrs.setdefault(nip, {})["timers"] = (ka, hold)
        except Exception:                            # noqa: BLE001
            pg_template.setdefault(token, {})["timers"] = (ka, hold)
        return
    m = re.match(r"^neighbor\s+(\S+)\s+send-community(?:\s+(\S+))?", s)
    if m:
        token = m.group(1)
        arg = m.group(2)
        if arg is not None and arg not in ("both", "standard", "extended"):
            return  # 未対応の community 種別（large 等）は誤分類せずスキップ
        sc = arg if arg else "standard"
        try:
            nip = norm_ipv6(token) if ":" in token else norm_ipv4(token)
            if nip in neighbors:
                neighbors[nip].send_community = sc
            else:
                pending_attrs.setdefault(nip, {})["send_community"] = sc
        except Exception:                            # noqa: BLE001
            pg_template.setdefault(token, {})["send_community"] = sc
        return
    # `no redistribute ...` はスキップ（加算的変更のみ対象）
    if s.startswith("no redistribute"):
        return
    _parse_redistribute_line(dev, s, "bgp")


def _parse_ospf_line(dev: Device, s: str, ospf_pid, warnings: list,
                     passive_ifaces: list, area_types: dict) -> None:
    """router ospf ブロック内の1行を解析（§6.1）。router-id / network area / passive-interface /
    area <a> stub|nssa [no-summary] / redistribute。

    area_types: {(ospf_pid, norm_area): area_type_str} — 収集した (process, area)→type マップ。
                パース末尾で af=='v4' かつ (o.process, o.area) が area_types にある
                OspfNetwork エントリのみに適用する（OSPFv2 スコープ限定）。
                異なるプロセスや OSPFv3 エントリには適用しない（§6.1 仕様）。
    """
    m = re.match(r"^router-id\s+(\S+)", s)
    if m:
        dev.ospf_router_id = m.group(1)
        return
    m = re.match(r"^network\s+(\S+)\s+(\S+)\s+area\s+(\S+)", s)
    if m:
        net, wild, area = m.groups()
        try:
            prefix = wildcard_to_prefix(wild)
            dev.ospf.append(OspfNetwork(ospf_pid, norm_cidr(norm_ipv4(net), prefix),
                                        norm_ospf_area(area), "v4"))
        except Exception as e:                       # noqa: BLE001
            warnings.append("ospf network parse failed: %s (%s)" % (s, e))
        return
    m = re.match(r"^passive-interface\s+(\S+)", s)
    if m:
        ifname = m.group(1)
        # `passive-interface default` および `no passive-interface <if>` は非対応。
        # 明示的な `passive-interface <ifname>` のみ対応（default キーワードはスキップ）。
        if ifname.lower() != "default":
            passive_ifaces.append(ifname)
        return
    # area <a> stub [no-summary] / area <a> nssa [no-summary]
    # 語境界付き: (stub|nssa) の直後は空白か行末のみ（stub-default-metric 等の誤マッチを防ぐ）
    m = re.match(r"^area\s+(\S+)\s+(stub|nssa)(\s.*|$)", s)
    if m:
        area_raw, kind, rest = m.group(1), m.group(2), (m.group(3) or "").strip()
        norm_area = norm_ospf_area(area_raw)
        no_summary = "no-summary" in rest
        if kind == "stub":
            area_types[(ospf_pid, norm_area)] = "totally-stubby" if no_summary else "stub"
        else:  # nssa
            area_types[(ospf_pid, norm_area)] = "totally-nssa" if no_summary else "nssa"
        return
    # `no redistribute ...` はスキップ（加算的変更のみ対象）
    if s.startswith("no redistribute"):
        return
    _parse_redistribute_line(dev, s, "ospf")


def parse_ios(text: str, warnings: list) -> Device:
    """Cisco IOS / IOS-XE config テキストを解析し正規化 Device を返す（要件書 §6.1）。

    パース失敗行は握りつぶし warnings(list) に文字列を追記し継続する（§6.3）。
    """
    dev = Device(hostname="", vendor="cisco_ios")
    cur = None
    context = None        # None | "interface" | "bgp" | "ospf"
    ospf_pid = None
    bgp_af = "v4"
    bgp = {
        "neighbors":    {},   # {nip: BgpNeighbor} — 登録済み neighbor
        "pending_attrs": {},  # {nip: {key: val}} — remote-as より先に来た属性を一時保持
        "pg_template":  {},   # {pgname: {key: val}} — peer-group 属性テンプレート
        "pg_member":    {},   # {nip: pgname} — nip → 所属 peer-group 名
    }
    pending_ospf3 = []   # [(iface, pid, area)] — IF アドレス確定後に network 解決
    passive_ifaces = []  # router ospf 配下の passive-interface 名リスト
    area_types = {}      # {(ospf_pid, norm_area): area_type_str} — area stub/nssa 宣言を収集し末尾で適用

    def finish_iface():
        nonlocal cur
        if cur is not None:
            cur.admin_status = "down" if cur.shutdown else "up"
            dev.interfaces.append(cur)
            cur = None

    for raw in text.splitlines():
        if is_sensitive_line(raw):
            continue
        s = raw.strip()
        if not s:
            continue

        if s == "!" or s == "end":
            finish_iface()
            context = None
            continue

        m = re.match(r"^hostname\s+(\S+)$", s)
        if m:
            if not dev.hostname:
                dev.hostname = m.group(1)
            continue
        m = re.match(r"^interface\s+(\S+)", s)
        if m:
            finish_iface()
            cur = Interface(name=m.group(1))
            context = "interface"
            continue
        m = re.match(r"^router bgp\s+(\d+)", s)
        if m:
            finish_iface()
            dev.as_ = int(m.group(1))
            context, bgp_af = "bgp", "v4"
            continue
        m = re.match(r"^router ospf\s+(\d+)", s)
        if m:
            finish_iface()
            ospf_pid = int(m.group(1))
            context = "ospf"
            continue
        # §6.1: OSPFv3 の network 宣言は interface 内 `ipv6 ospf <pid> area` で確定するため、
        # ここ（ipv6 router ospf <pid>）は process ID 宣言のみ。配下行は無視する。
        if re.match(r"^ipv6 router ospf\s+\d+", s):
            finish_iface()
            context = None
            continue
        m = re.match(r"^ip route\s+(\S+)\s+(\S+)\s+(\S+)", s)
        if m:
            net, mask, nh = m.groups()
            try:
                prefix = mask_to_prefix(mask)
                dev.static.append(StaticRoute(norm_cidr(norm_ipv4(net), prefix),
                                              norm_ipv4(nh), "v4"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("ip route parse failed: %s (%s)" % (s, e))
            continue
        m = re.match(r"^ipv6 route\s+(\S+)\s+(\S+)", s)
        if m:
            cidr, nh = m.groups()
            try:
                dev.static.append(StaticRoute(norm_cidr_str(cidr), norm_ipv6(nh), "v6"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("ipv6 route parse failed: %s (%s)" % (s, e))
            continue

        if context == "interface" and cur is not None:
            m = re.match(r"^ipv6 ospf\s+(\d+)\s+area\s+(\S+)", s)
            if m:
                pending_ospf3.append((cur, int(m.group(1)), norm_ospf_area(m.group(2))))
            else:
                _parse_iface_line(cur, s, warnings)
        elif context == "bgp":
            if s.startswith("address-family ipv6"):
                bgp_af = "v6"
            elif s.startswith("address-family ipv4"):
                bgp_af = "v4"
            elif s == "exit-address-family":
                bgp_af = "v4"
            else:
                _parse_bgp_line(dev, s, bgp_af, bgp, warnings)
        elif context == "ospf":
            _parse_ospf_line(dev, s, ospf_pid, warnings, passive_ifaces, area_types)

    finish_iface()
    for iface, pid, area in pending_ospf3:
        network = _iface_v6_network(iface) or iface.name
        dev.ospf.append(OspfNetwork(pid, network, area, "v6"))
    # passive-interface: 収集した IF 名に対して ospf["passive"]=True を設定
    if passive_ifaces:
        iface_map = {i.name: i for i in dev.interfaces}
        for ifname in passive_ifaces:
            iface = iface_map.get(ifname)
            if iface is not None:
                ensure_ospf(iface)["passive"] = True
    # area_types: 収集した (pid, area)→type を af=='v4' かつ同一 (process, area) の
    # OspfNetwork エントリのみに適用（OSPFv2 スコープ限定。v6 エントリや他プロセスには漏らさない）
    # network 宣言と area-type 宣言は順不同のため末尾で一括適用（passive_ifaces と同方式）
    if area_types:
        for o in dev.ospf:
            if o.af == "v4" and (o.process, o.area) in area_types:
                o.area_type = area_types[(o.process, o.area)]
    # peer-group 継承: pg_member の全エントリを末尾一括解決（決定的順序: dict 挿入順）
    # 個別指定 > template を厳守。未定義 peer-group かつ個別情報なし → BgpNeighbor を生成しない。
    for nip, pg in bgp["pg_member"].items():
        if nip in bgp["neighbors"]:
            # 個別 remote-as 等で既に生成済み → 欠落属性のみ template から補完・peer_group 設定
            nb = bgp["neighbors"][nip]
        elif pg in bgp["pg_template"]:
            # 個別指定なしメンバー: template が定義済みのときだけ生成
            af = "v6" if ":" in nip else "v4"
            nb = BgpNeighbor(nip, None, af)
            # 個別 pending_attrs（remote-as 無しで来た個別属性）があれば先に適用（個別が勝つ）
            attrs = bgp["pending_attrs"].pop(nip, {})
            if "update_source" in attrs:
                nb.update_source = attrs["update_source"]
            if attrs.get("rr"):
                nb.route_reflector_client = True
            if attrs.get("nhs"):
                nb.next_hop_self = True
            if "timers" in attrs:
                nb.timers = attrs["timers"]
            if "send_community" in attrs:
                nb.send_community = attrs["send_community"]
            dev.bgp.append(nb)
            bgp["neighbors"][nip] = nb
        else:
            # 未定義 peer-group かつ個別情報なし → BgpNeighbor を生成しない（ゾンビ排除）
            continue
        # template から欠落属性のみ補完（個別優先）
        t = bgp["pg_template"].get(pg, {})
        if nb.peer_as is None and "remote_as" in t:
            nb.peer_as = t["remote_as"]
        if nb.update_source is None and "update_source" in t:
            nb.update_source = t["update_source"]
        if not nb.route_reflector_client and t.get("rr"):
            nb.route_reflector_client = True
        if not nb.next_hop_self and t.get("nhs"):
            nb.next_hop_self = True
        if nb.timers is None and "timers" in t:
            nb.timers = t["timers"]
        if nb.send_community is None and "send_community" in t:
            nb.send_community = t["send_community"]
        nb.peer_group = pg
    return dev
