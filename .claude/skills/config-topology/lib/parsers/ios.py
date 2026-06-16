"""Cisco IOS / IOS-XE パーサ（要件書 §6.1）。"""
import re

from ..models import Address, BgpNeighbor, Device, Interface, OspfNetwork, Redistribute, StaticRoute
from ..normalize import (asdot_to_asplain, mask_to_prefix, norm_cidr, norm_cidr_str,
                         norm_ipv4, norm_ipv6, norm_ospf_area, v6_scope, wildcard_to_prefix)
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


def _iface_v4_network(iface: Interface):
    """IF の最初の非 secondary v4 アドレスのサブネットを返す（§6.1）。無ければ None。

    derived_ip() と選択順を一致させるため sorted_addresses() を使う（修正1）。
    """
    for a in iface.sorted_addresses():
        if a.af == "v4" and not a.secondary:
            return norm_cidr(a.ip, a.prefix)
    return None


def _resolve_static_tokens(tokens: list, af: str) -> str:
    """static route の残りトークン列から next-hop（IP または IF 名）を決定する（#3）。

    形式: [<IF名>] [<IP>] [<AD>] [name <x>] [track <n>] [tag <n>] [permanent] …
    優先度:
      - IF 名 + IP が両方ある → IP を next-hop（FIB P2P 解決精度が高い）
      - IP のみ              → IP
      - IF 名のみ            → IF 名
    末尾オプション（AD 数字・name/track/tag/<keyword> 等）は無視する。
    """
    _SKIP_KEYWORDS = {"name", "track", "tag", "permanent", "multicast", "global"}
    found_ip = None
    found_if = None
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok.lower() in _SKIP_KEYWORDS:
            skip_next = True   # 直後のトークン（値）もスキップ
            continue
        # 数字単独 → AD（administrative distance）→ スキップ
        if tok.isdigit():
            continue
        # IP として解釈を試みる
        try:
            if af == "v6":
                found_ip = norm_ipv6(tok)
            else:
                found_ip = norm_ipv4(tok)
            continue
        except Exception:
            pass
        # IP でない → IF 名
        if found_if is None:
            found_if = tok
    # IP 優先、無ければ IF 名
    if found_ip is not None:
        return found_ip
    if found_if is not None:
        return found_if
    raise ValueError("static route に next-hop が見つかりません: %s" % tokens)


def _parse_iface_line(iface: Interface, s: str, warnings: list) -> bool:
    """interface ブロック内の1行 s を解析し iface をミューテートする（§6.1）。失敗は warnings へ。

    認識した（ハンドラがパターン一致した）場合 True、未対応行は False を返す（parse 状態判定用）。
    値が未対応・パース失敗でも「行を認識した」なら True（突合では『全く認識しない行』を炙り出すのが目的）。
    """
    m = re.match(r"^description\s+(.*)$", s)
    if m:
        iface.description = m.group(1).strip().strip('"')
        return True
    # dhcp / negotiated / unnumbered: IP 未付与・警告を積む
    if re.match(r"^ip address dhcp\b", s):
        warnings.append("%s: dhcp のためサブネット未確定・リンク推論から除外" % iface.name)
        return True
    if re.match(r"^ip address negotiated\b", s):
        warnings.append("%s: negotiated のためサブネット未確定・リンク推論から除外" % iface.name)
        return True
    if re.match(r"^ip unnumbered\b", s):
        warnings.append("%s: unnumbered のためサブネット未確定・リンク推論から除外" % iface.name)
        return True
    m = re.match(r"^ip address\s+(\S+)\s+(\S+)(\s+secondary)?\s*$", s)
    if m:
        ip, mask, sec = m.group(1), m.group(2), bool(m.group(3))
        try:
            iface.addresses.append(Address("v4", norm_ipv4(ip), mask_to_prefix(mask),
                                            secondary=sec))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("ip address parse failed: %s (%s)" % (s, e))
        return True
    # autoconfig（アドレス値なし）
    if re.match(r"^ipv6 address autoconfig\s*$", s, re.IGNORECASE):
        warnings.append("%s: autoconfig のためアドレス未確定・リンク推論から除外" % iface.name)
        return True
    # eui-64 / anycast / link-local 末尾キーワード付き ipv6 address
    m = re.match(r"^ipv6 address\s+(\S+)(\s+(?:link-local|eui-64|anycast))?\s*$", s, re.IGNORECASE)
    if m:
        cidr, kw = m.group(1), (m.group(2) or "").strip().lower()
        ll = (kw == "link-local")
        try:
            host, plen = cidr.split("/")
            ip = norm_ipv6(host)
            scope = "link-local" if ll else v6_scope(ip)
            iface.addresses.append(Address("v6", ip, int(plen), scope=scope))
            _set_l3(iface)
        except Exception as e:                       # noqa: BLE001
            warnings.append("ipv6 address parse failed: %s (%s)" % (s, e))
        return True
    if s == "shutdown":
        iface.shutdown = True
        return True
    if s == "no shutdown":
        iface.shutdown = False
        return True
    if s == "no switchport":
        _set_l3(iface)
        return True
    m = re.match(r"^mtu\s+(\d+)", s)
    if m:
        iface.mtu = int(m.group(1))
        return True
    m = re.match(r"^speed\s+(\S+)", s)
    if m:
        iface.speed = m.group(1)
        return True
    m = re.match(r"^duplex\s+(\S+)", s)
    if m:
        iface.duplex = m.group(1)
        return True
    m = re.match(r"^ip vrf forwarding\s+(\S+)", s)
    if m:
        iface.vrf = m.group(1)
        return True
    m = re.match(r"^vrf forwarding\s+(\S+)", s)
    if m:
        iface.vrf = m.group(1)
        return True
    m = re.match(r"^encapsulation\s+dot1q\b", s, re.IGNORECASE)
    if m:
        iface.encapsulation = "dot1q"
        return True
    m = re.match(r"^switchport mode\s+(access|trunk)", s)
    if m:
        _ensure_switchport(iface)
        iface.switchport["mode"] = m.group(1)
        _set_l2(iface)
        return True
    m = re.match(r"^switchport access vlan\s+(\d+)", s)
    if m:
        _ensure_switchport(iface)
        iface.switchport["access_vlan"] = int(m.group(1))
        _set_l2(iface)
        return True
    m = re.match(r"^switchport trunk allowed vlan\s+(\S+)", s)
    if m:
        _ensure_switchport(iface)
        iface.switchport["trunk_vlans"] = m.group(1)
        _set_l2(iface)
        return True
    m = re.match(r"^ip ospf cost\s+(\d+)", s)
    if m:
        ensure_ospf(iface)["cost"] = int(m.group(1))
        return True
    m = re.match(r"^ip ospf network\s+(\S+)", s)
    if m:
        ensure_ospf(iface)["network_type"] = m.group(1)
        return True
    return False


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
                    warnings: list, bgp_vrf: str = None) -> bool:
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
        return True
    m = re.match(r"^neighbor\s+(\S+)\s+remote-as\s+(\d+(?:\.\d+)?)", s)
    if m:
        token, peer = m.group(1), asdot_to_asplain(m.group(2))
        # token が IP かどうか判別して振り分け
        try:
            af = "v6" if ":" in token else "v4"
            nip = norm_ipv6(token) if af == "v6" else norm_ipv4(token)
            # IP として解析成功 → 通常の neighbor remote-as
            if nip in neighbors:
                # すでに BgpNeighbor が存在する（peer-group メンバー行で生成済み）→ peer_as を設定
                neighbors[nip].peer_as = peer
                # address-family vrf 文脈であれば vrf も更新（既存 neighbor が global で生成されていた場合に対応）
                if bgp_vrf is not None and neighbors[nip].vrf is None:
                    neighbors[nip].vrf = bgp_vrf
            else:
                nb = BgpNeighbor(nip, peer, af)
                nb.vrf = bgp_vrf   # address-family vrf 文脈
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
        return True
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
        return True
    # peer-group 宣言: neighbor <pgname> peer-group（末尾に名前なし）
    m = re.match(r"^neighbor\s+(\S+)\s+peer-group$", s)
    if m:
        pgname = m.group(1)
        pg_template.setdefault(pgname, {})  # キー確保のみ
        return True
    m = re.match(r"^neighbor\s+(\S+)\s+activate", s)
    if m:
        # v4 activate は既定で有効のため no-op。v6 のみ af を確定する。いずれも行は認識済み。
        if bgp_af == "v6" and ":" in m.group(1):
            try:
                nip = norm_ipv6(m.group(1))
                if nip in neighbors:
                    neighbors[nip].af = "v6"
            except Exception as e:                   # noqa: BLE001
                warnings.append("bgp activate parse failed: %s (%s)" % (s, e))
        return True
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
        return True
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
        return True
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
        return True
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
        return True
    m = re.match(r"^neighbor\s+(\S+)\s+send-community(?:\s+(\S+))?", s)
    if m:
        token = m.group(1)
        arg = m.group(2)
        if arg is not None and arg not in ("both", "standard", "extended"):
            return True  # 未対応の community 種別（large 等）は値だけスキップ（行は認識済み）
        sc = arg if arg else "standard"
        try:
            nip = norm_ipv6(token) if ":" in token else norm_ipv4(token)
            if nip in neighbors:
                neighbors[nip].send_community = sc
            else:
                pending_attrs.setdefault(nip, {})["send_community"] = sc
        except Exception:                            # noqa: BLE001
            pg_template.setdefault(token, {})["send_community"] = sc
        return True
    # `no redistribute ...` はスキップ（加算的変更のみ対象・行は認識済み）
    if s.startswith("no redistribute"):
        return True
    return _parse_redistribute_line(dev, s, "bgp")


def _parse_ospf_line(dev: Device, s: str, ospf_pid, warnings: list,
                     passive_ifaces: list, area_types: dict) -> bool:
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
        return True
    m = re.match(r"^network\s+(\S+)\s+(\S+)\s+area\s+(\S+)", s)
    if m:
        net, wild, area = m.groups()
        try:
            prefix = wildcard_to_prefix(wild)
            dev.ospf.append(OspfNetwork(ospf_pid, norm_cidr(norm_ipv4(net), prefix),
                                        norm_ospf_area(area), "v4"))
        except Exception as e:                       # noqa: BLE001
            warnings.append("ospf network parse failed: %s (%s)" % (s, e))
        return True
    m = re.match(r"^passive-interface\s+(\S+)", s)
    if m:
        ifname = m.group(1)
        # `passive-interface default` および `no passive-interface <if>` は非対応。
        # 明示的な `passive-interface <ifname>` のみ対応（default キーワードはスキップ）。
        if ifname.lower() != "default":
            passive_ifaces.append(ifname)
        return True
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
        return True
    # `no redistribute ...` はスキップ（加算的変更のみ対象・行は認識済み）
    if s.startswith("no redistribute"):
        return True
    return _parse_redistribute_line(dev, s, "ospf")


def parse_ios(text: str, warnings: list, line_status=None) -> Device:
    """Cisco IOS / IOS-XE config テキストを解析し正規化 Device を返す（要件書 §6.1）。

    パース失敗行は握りつぶし warnings(list) に文字列を追記し継続する（§6.3）。

    line_status: 任意の出力リスト。指定時は各行を "parsed"/"ignored"/"unparsed" で分類し
    末尾で extend する（CONFIG parse 状態モード用）。**未指定時はモデル出力は完全に従来通り**。
    """
    dev = Device(hostname="", vendor="cisco_ios")
    cur = None
    context = None        # None | "interface" | "bgp" | "ospf"
    ospf_pid = None
    bgp_af = "v4"
    bgp_vrf = None      # 現在の address-family vrf 文脈（None = global）
    bgp = {
        "neighbors":    {},   # {nip: BgpNeighbor} — 登録済み neighbor
        "pending_attrs": {},  # {nip: {key: val}} — remote-as より先に来た属性を一時保持
        "pg_template":  {},   # {pgname: {key: val}} — peer-group 属性テンプレート
        "pg_member":    {},   # {nip: pgname} — nip → 所属 peer-group 名
    }
    pending_ospf3 = []   # [(iface, pid, area)] — IF アドレス確定後に v6 network 解決
    pending_ospf = []    # [(iface, pid, area)] — IF アドレス確定後に v4 network 解決
    passive_ifaces = []  # router ospf 配下の passive-interface 名リスト
    area_types = {}      # {(ospf_pid, norm_area): area_type_str} — area stub/nssa 宣言を収集し末尾で適用

    def finish_iface():
        nonlocal cur
        if cur is not None:
            cur.admin_status = "down" if cur.shutdown else "up"
            dev.interfaces.append(cur)
            cur = None

    lines = text.splitlines()
    status = ["unparsed"] * len(lines)   # 既定は未対応。認識した行で parsed / 無視行で ignored に更新

    for i, raw in enumerate(lines):
        if is_sensitive_line(raw):
            # 機密行は意図的にパースしない設計 → "ignored"（見落とし候補=unparsed には含めない）
            status[i] = "ignored"
            continue
        s = raw.strip()
        if not s:
            status[i] = "ignored"
            continue

        if s == "!" or s == "end":
            finish_iface()
            context = None
            status[i] = "ignored"
            continue
        if s.startswith("!"):
            # `! コメント文` は IOS のコメント行（モデルに寄与しない）→ ignored 分類。
            # bare `!` と異なり finish_iface/context リセットはしない（既存挙動を変えない）。
            status[i] = "ignored"
            continue

        # vrf definition <name> / ip vrf <name>: VRF 名宣言行（モデルに寄与しない → ignored）
        if re.match(r"^vrf definition\s+", s) or re.match(r"^ip vrf\s+\S+$", s):
            finish_iface()
            context = None
            status[i] = "ignored"
            continue
        m = re.match(r"^hostname\s+(\S+)$", s)
        if m:
            if not dev.hostname:
                dev.hostname = m.group(1)
            status[i] = "parsed"
            continue
        m = re.match(r"^interface\s+(\S+)", s)
        if m:
            finish_iface()
            cur = Interface(name=m.group(1))
            context = "interface"
            status[i] = "parsed"
            continue
        m = re.match(r"^router bgp\s+(\d+(?:\.\d+)?)", s)
        if m:
            finish_iface()
            dev.as_ = asdot_to_asplain(m.group(1))
            context, bgp_af = "bgp", "v4"
            status[i] = "parsed"
            continue
        m = re.match(r"^router ospf\s+(\d+)", s)
        if m:
            finish_iface()
            ospf_pid = int(m.group(1))
            context = "ospf"
            status[i] = "parsed"
            continue
        # §6.1: OSPFv3 の network 宣言は interface 内 `ipv6 ospf <pid> area` で確定するため、
        # ここ（ipv6 router ospf <pid>）は process ID 宣言のみ。配下行は無視する。
        if re.match(r"^ipv6 router ospf\s+\d+", s):
            finish_iface()
            context = None
            status[i] = "parsed"
            continue
        # ip route vrf <name> <net> <mask> <rest>（vrf 付き static route）
        m = re.match(r"^ip route vrf\s+(\S+)\s+(\S+)\s+(\S+)\s+(.*)", s)
        if m:
            vrf_name, net, mask, rest_str = m.group(1), m.group(2), m.group(3), m.group(4).split()
            try:
                prefix = mask_to_prefix(mask)
                net_cidr = norm_cidr(norm_ipv4(net), prefix)
                nh = _resolve_static_tokens(rest_str, "v4")
                dev.static.append(StaticRoute(net_cidr, nh, "v4", vrf=vrf_name))
            except Exception as e:                   # noqa: BLE001
                warnings.append("ip route vrf parse failed: %s (%s)" % (s, e))
            status[i] = "parsed"
            continue
        m = re.match(r"^ip route\s+(\S+)\s+(\S+)\s+(.*)", s)
        if m:
            net, mask, rest_str = m.group(1), m.group(2), m.group(3).split()
            try:
                prefix = mask_to_prefix(mask)
                net_cidr = norm_cidr(norm_ipv4(net), prefix)
                nh = _resolve_static_tokens(rest_str, "v4")
                dev.static.append(StaticRoute(net_cidr, nh, "v4"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("ip route parse failed: %s (%s)" % (s, e))
            status[i] = "parsed"
            continue
        # ipv6 route vrf <name> <cidr> <rest>（vrf 付き v6 static route）
        m = re.match(r"^ipv6 route vrf\s+(\S+)\s+(\S+)\s+(.*)", s)
        if m:
            vrf_name, cidr, rest_str = m.group(1), m.group(2), m.group(3).split()
            try:
                nh = _resolve_static_tokens(rest_str, "v6")
                dev.static.append(StaticRoute(norm_cidr_str(cidr), nh, "v6", vrf=vrf_name))
            except Exception as e:                   # noqa: BLE001
                warnings.append("ipv6 route vrf parse failed: %s (%s)" % (s, e))
            status[i] = "parsed"
            continue
        m = re.match(r"^ipv6 route\s+(\S+)\s+(.*)", s)
        if m:
            cidr, rest_str = m.group(1), m.group(2).split()
            try:
                nh = _resolve_static_tokens(rest_str, "v6")
                dev.static.append(StaticRoute(norm_cidr_str(cidr), nh, "v6"))
            except Exception as e:                   # noqa: BLE001
                warnings.append("ipv6 route parse failed: %s (%s)" % (s, e))
            status[i] = "parsed"
            continue

        if context == "interface" and cur is not None:
            m6 = re.match(r"^ipv6 ospf\s+(\d+)\s+area\s+(\S+)", s)
            m4 = re.match(r"^ip ospf\s+(\d+)\s+area\s+(\S+)", s)
            mv3 = re.match(r"^ospfv3\s+(\d+)\s+ipv6\s+area\s+(\S+)", s)
            if m6:
                pending_ospf3.append((cur, int(m6.group(1)), norm_ospf_area(m6.group(2))))
                status[i] = "parsed"
            elif mv3:
                # ospfv3 <pid> ipv6 area <a>: legacy ipv6 ospf と同じ v6 解決パスへ合流
                pending_ospf3.append((cur, int(mv3.group(1)), norm_ospf_area(mv3.group(2))))
                status[i] = "parsed"
            elif m4:
                pending_ospf.append((cur, int(m4.group(1)), norm_ospf_area(m4.group(2))))
                status[i] = "parsed"
            elif _parse_iface_line(cur, s, warnings):
                status[i] = "parsed"
        elif context == "bgp":
            if s.startswith("address-family ipv6") or s.startswith("address-family ipv4"):
                bgp_af = "v6" if s.startswith("address-family ipv6") else "v4"
                # vrf 文脈を抽出: address-family ipv4|ipv6 vrf <name>
                m_vrf = re.match(r"^address-family (?:ipv4|ipv6) vrf\s+(\S+)", s)
                bgp_vrf = m_vrf.group(1) if m_vrf else None
                status[i] = "parsed"
            elif s == "exit-address-family":
                bgp_af = "v4"
                bgp_vrf = None   # global に戻す
                status[i] = "parsed"
            elif _parse_bgp_line(dev, s, bgp_af, bgp, warnings, bgp_vrf):
                status[i] = "parsed"
        elif context == "ospf":
            if _parse_ospf_line(dev, s, ospf_pid, warnings, passive_ifaces, area_types):
                status[i] = "parsed"

    if line_status is not None:
        line_status.extend(status)

    finish_iface()
    for iface, pid, area in pending_ospf3:
        network = _iface_v6_network(iface) or iface.name
        dev.ospf.append(OspfNetwork(pid, network, area, "v6"))
    existing = {(o.network, o.process, o.af) for o in dev.ospf}
    for iface, pid, area in pending_ospf:
        net = _iface_v4_network(iface)
        if net and (net, pid, "v4") not in existing:
            dev.ospf.append(OspfNetwork(pid, net, area, "v4"))
            existing.add((net, pid, "v4"))
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
