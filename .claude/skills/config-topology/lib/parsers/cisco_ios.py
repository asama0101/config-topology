"""
Cisco IOS / IOS-XE パーサ

行指向・`!` 区切り形式のコンフィグをパースし、正規化 Device を返す。

パース規則（vendor-parsing.md より）:
- hostname X → Device.hostname
- interface <name> ブロック:
  - ip address A.B.C.D MASK → addresses に {af:"v4", ip:"...", prefix:n} エントリを追加。
    secondary は addresses に secondary=True で収録（無視せず全て保持）。
  - ipv6 address X:Y:Z/PL → addresses に {af:"v6", ip:"正規化済みアドレス", prefix:n} エントリを追加。
  - shutdown → shutdown=True
  - no shutdown → shutdown=False
  - description X → description
  - ipv6 ospf <pid> area <a> → OSPFv3 仮登録（パース後処理で OspfNetwork(af=v6) に変換）
- router bgp <asn> → Device.asn。配下 neighbor <ip> remote-as <peer> → BgpNeighbor（v4/v6 仮登録）
  - address-family ipv6 配下 neighbor <v6ip> activate → BgpNeighbor(af=v6) として確定
- router ospf <pid> 配下 network <addr> <wildcard> area <a> → OspfNetwork(af=v4)
- ipv6 router ospf <pid> ブロック: PID 宣言のみ（配下行 router-id 等は無視）。
  OSPFv3 の確定は interface ブロックの `ipv6 ospf <pid> area <a>` で行う。
- ip route <prefix> <mask> <next_hop> → StaticRoute(af=v4)
- ipv6 route <prefix/len> <nexthop> → StaticRoute(af=v6, prefix=ipaddress 正規化済み CIDR)
"""

from __future__ import annotations

import ipaddress
import re

from .base import (
    ADMIN_DOWN, ADMIN_UP, AF_V4, AF_V6, L2, L3, SCOPE_LINK_LOCAL, SOURCE_PARSED,
    BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute,
    derive_ip_from_addresses, normalize_v6, sort_addresses,
)


def detect(text: str) -> bool:
    """
    IOS config かどうかを判定。

    条件（いずれかが満たされ、かつ set 行が支配的でないこと）:
    - "hostname " で始まる行がある
    - "interface ...Ethernet" や "interface Loopback" 等の行がある
    - "!" 区切り行が複数ある
    """
    if not text.strip():
        return False

    lines = text.splitlines()

    # set 行が過半数なら JunOS
    set_lines = sum(1 for ln in lines if ln.strip().startswith("set "))
    non_empty = sum(1 for ln in lines if ln.strip())
    if non_empty > 0 and set_lines / non_empty > 0.4:
        return False

    # IOS 特徴チェック
    for ln in lines:
        stripped = ln.strip()
        if re.match(r'^hostname\s+\S', stripped):
            return True
        if re.match(r'^interface\s+\S', stripped):
            return True
        if stripped == "!":
            return True

    return False


def _ensure_switchport(sp: dict | None) -> dict:
    """switchport dict が None なら空 dict を返す小ヘルパー（重複初期化を排除）。"""
    return sp if sp is not None else {}


def _mask_to_prefixlen(mask: str) -> int:
    """サブネットマスク文字列を prefix 長に変換する。"""
    return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen


def _wildcard_to_prefixlen(wildcard: str) -> int:
    """OSPF ワイルドカードマスクを prefix 長に変換する（逆マスク）。"""
    # ワイルドカードの各オクテットを 255 から引いてサブネットマスクを得る
    parts = wildcard.split(".")
    subnet_mask = ".".join(str(255 - int(p)) for p in parts)
    return _mask_to_prefixlen(subnet_mask)


def parse(text: str) -> Device:
    """
    IOS コンフィグテキストをパースして Device を返す。

    Phase 3F 拡張:
    - ip address（primary / secondary）と ipv6 address を addresses リストに収集
    - ip フィールドは addresses 中の最初の非 secondary v4 から派生（_derive_ip_from_addresses 相当）
    - addresses は (af 順, ipaddress オブジェクト, prefix) でソート（決定的）

    Phase 3G 拡張:
    - ipv6 router ospf N ブロック: PID 登録（ブロック内 router-id 等は無視）
    - interface ブロック内 ipv6 ospf N area A: (if_name, pid, area) を仮収集
    - パース後: 仮収集エントリを addresses から v6 サブネットに変換して OspfNetwork(af=v6) 生成
    - router bgp <asn> ブロック内 address-family ipv6 / neighbor X activate: BgpNeighbor(af=v6) 生成
      （neighbor X remote-as Y は v4/v6 ともに事前に仮登録し、activate 済み v6 のみ af=v6 で確定）
    - ipv6 route PREFIX NEXTHOP: StaticRoute(af=v6) 生成
    """
    hostname = ""
    asn: int | None = None
    interfaces: list[Interface] = []
    bgp_neighbors: list[BgpNeighbor] = []
    ospf_networks: list[OspfNetwork] = []
    static_routes: list[StaticRoute] = []
    # Phase 4 (router-id): device 単位の router-id
    ospf_router_id: str | None = None
    bgp_router_id: str | None = None

    # Phase 3G: OSPFv3 仮収集バッファ
    # key: if_name（config 上の名前）→ [(pid, area), ...]
    # OSPFv3 確定は _ospfv3_if_buf で完結（_ospfv3_pids は不要のため削除）
    _ospfv3_if_buf: dict[str, list[tuple[int, str]]] = {}
    # Phase 3G: BGP ネイバー仮登録バッファ（router bgp ブロック内 neighbor <ip> remote-as <peer>）
    # {neighbor_ip: peer_as}（v4/v6 両方を先に収集し、address-family ipv6 で activate 済みのみ v6 確定）
    _bgp_pre: dict[str, int | None] = {}
    # Phase 3G: address-family ipv6 で activate された v6 ネイバーの集合
    _bgp_v6_activated: set[str] = set()

    lines = text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # hostname
        m = re.match(r'^hostname\s+(\S+)', stripped)
        if m:
            hostname = m.group(1)
            i += 1
            continue

        # interface ブロック
        m = re.match(r'^interface\s+(\S+)', stripped)
        if m:
            if_name = m.group(1)
            if_ip: str | None = None
            if_desc: str | None = None
            if_shutdown = False
            if_mtu: int | None = None
            if_speed: str | None = None
            if_duplex: str | None = None
            if_switchport: dict | None = None
            if_encapsulation: str | None = None
            if_has_ip_cmd = False      # "ip address" コマンドがあったか
            if_no_switchport = False   # "no switchport" があったか
            # Phase 3F: addresses 収集用リスト（パース中の生データ）
            if_addresses: list[dict] = []
            i += 1
            # ブロック内を読む（インデントされた行か次のトップレベルまで）
            while i < len(lines):
                inner = lines[i]
                inner_stripped = inner.strip()
                # ブロック終端: 空行 or "!" or インデントなしの非空行
                if not inner or inner_stripped == "!" or (inner and not inner[0].isspace() and inner_stripped):
                    break
                # ip address（primary / secondary 両方対応）
                m2 = re.match(r'^ip\s+address\s+(\S+)\s+(\S+)(\s+secondary)?$', inner_stripped)
                if m2:
                    addr = m2.group(1)
                    mask = m2.group(2)
                    is_secondary = bool(m2.group(3) and "secondary" in m2.group(3))
                    try:
                        prefixlen = _mask_to_prefixlen(mask)
                        addr_entry: dict = {"af": "v4", "ip": addr, "prefix": prefixlen}
                        if is_secondary:
                            addr_entry["secondary"] = True
                        else:
                            # primary のみ if_ip に採用（後方互換）
                            if_ip = f"{addr}/{prefixlen}"
                            if_has_ip_cmd = True
                        if_addresses.append(addr_entry)
                    except ValueError:
                        pass
                # ipv6 address（グローバル / link-local 両方対応）
                m_v6 = re.match(r'^ipv6\s+address\s+(\S+)(?:\s+(\S+))?$', inner_stripped, re.IGNORECASE)
                if m_v6:
                    v6_spec = m_v6.group(1)
                    v6_qualifier = (m_v6.group(2) or "").lower()
                    if "/" in v6_spec:
                        # グローバルアドレス: "2001:db8::1/64" 形式
                        v6_addr_str, v6_prefix_str = v6_spec.rsplit("/", 1)
                        try:
                            v6_prefix = int(v6_prefix_str)
                            v6_normalized = normalize_v6(v6_addr_str)
                            addr_entry = {"af": AF_V6, "ip": v6_normalized, "prefix": v6_prefix}
                            if_addresses.append(addr_entry)
                            if_has_ip_cmd = True  # ip が設定されている = L3 扱い
                        except (ValueError, TypeError):
                            pass
                    elif v6_qualifier == "link-local":
                        # link-local: "fe80::1 link-local" 形式
                        try:
                            v6_normalized = normalize_v6(v6_spec)
                            addr_entry = {"af": AF_V6, "ip": v6_normalized, "prefix": 64, "scope": SCOPE_LINK_LOCAL}
                            if_addresses.append(addr_entry)
                        except (ValueError, TypeError):
                            pass
                # description
                m3 = re.match(r'^description\s+(.*)', inner_stripped)
                if m3:
                    if_desc = m3.group(1).strip()
                # shutdown / no shutdown
                if inner_stripped == "shutdown":
                    if_shutdown = True
                if inner_stripped == "no shutdown":
                    if_shutdown = False
                # mtu（\d+ マッチ済みなので ValueError は発生しない）
                m_mtu = re.match(r'^mtu\s+(\d+)', inner_stripped)
                if m_mtu:
                    if_mtu = int(m_mtu.group(1))
                # speed
                m_speed = re.match(r'^speed\s+(\S+)', inner_stripped)
                if m_speed:
                    if_speed = m_speed.group(1)
                # duplex
                m_duplex = re.match(r'^duplex\s+(\S+)', inner_stripped)
                if m_duplex:
                    if_duplex = m_duplex.group(1)
                # switchport mode access / trunk
                m_sw_mode = re.match(r'^switchport\s+mode\s+(\S+)', inner_stripped)
                if m_sw_mode:
                    if_switchport = _ensure_switchport(if_switchport)
                    if_switchport["mode"] = m_sw_mode.group(1)
                # switchport access vlan <id>（\d+ マッチ済みなので ValueError は発生しない）
                m_sw_av = re.match(r'^switchport\s+access\s+vlan\s+(\d+)', inner_stripped)
                if m_sw_av:
                    if_switchport = _ensure_switchport(if_switchport)
                    if_switchport["access_vlan"] = int(m_sw_av.group(1))
                # switchport trunk allowed vlan <range>
                m_sw_tv = re.match(r'^switchport\s+trunk\s+allowed\s+vlan\s+(\S+)', inner_stripped)
                if m_sw_tv:
                    if_switchport = _ensure_switchport(if_switchport)
                    if_switchport["trunk_vlans"] = m_sw_tv.group(1)
                # no switchport
                if inner_stripped == "no switchport":
                    if_no_switchport = True
                # encapsulation dot1Q <vlan>（IGNORECASE で DOT1Q 等も許容）
                m_enc = re.match(r'^encapsulation\s+dot1[Qq]\s+(\d+)', inner_stripped, re.IGNORECASE)
                if m_enc:
                    if_encapsulation = "dot1q"
                # Phase 3G: ipv6 ospf <pid> area <area>（インターフェースブロック内）
                m_v6ospf = re.match(r'^ipv6\s+ospf\s+(\d+)\s+area\s+(\S+)', inner_stripped, re.IGNORECASE)
                if m_v6ospf:
                    v6o_pid = int(m_v6ospf.group(1))
                    v6o_area = m_v6ospf.group(2)
                    _ospfv3_if_buf.setdefault(if_name, []).append((v6o_pid, v6o_area))
                i += 1
            # l2_l3 判定（IOS: ip あり / no switchport が L3 判定で優先される）
            if if_has_ip_cmd or if_no_switchport:
                if_l2_l3 = L3
            elif if_switchport is not None:
                if_l2_l3 = L2
            else:
                if_l2_l3 = None
            # admin_status: shutdown 由来（定数使用）
            if_admin_status = ADMIN_DOWN if if_shutdown else ADMIN_UP
            # Phase 3F: addresses をソートして格納（base.sort_addresses で DRY）
            sorted_addrs = sort_addresses(if_addresses)
            # ip: addresses から派生（primary v4 が存在すれば if_ip と同値・v6-only なら None）
            derived_ip = derive_ip_from_addresses(sorted_addrs) if sorted_addrs else if_ip
            interfaces.append(Interface(
                name=if_name,
                ip=derived_ip,
                description=if_desc,
                shutdown=if_shutdown,
                mtu=if_mtu,
                speed=if_speed,
                duplex=if_duplex,
                switchport=if_switchport,
                encapsulation=if_encapsulation,
                l2_l3=if_l2_l3,
                admin_status=if_admin_status,
                addresses=sorted_addrs,
            ))
            continue

        # router bgp <asn>
        m = re.match(r'^router\s+bgp\s+(\d+)', stripped)
        if m:
            asn = int(m.group(1))
            i += 1
            # Phase 3G: address-family ipv6 内フラグ
            _in_af_ipv6 = False
            while i < len(lines):
                inner = lines[i]
                inner_stripped = inner.strip()
                if not inner or inner_stripped == "!" or (inner and not inner[0].isspace() and inner_stripped):
                    break
                # address-family ipv6 開始
                if re.match(r'^address-family\s+ipv6', inner_stripped, re.IGNORECASE):
                    _in_af_ipv6 = True
                    i += 1
                    continue
                # exit-address-family / address-family 切替: ipv6 AF 終了
                if re.match(r'^exit-address-family', inner_stripped, re.IGNORECASE):
                    _in_af_ipv6 = False
                    i += 1
                    continue
                if re.match(r'^address-family\s+', inner_stripped, re.IGNORECASE):
                    _in_af_ipv6 = False
                    i += 1
                    continue
                # Phase 4: bgp router-id <id>
                m_rid = re.match(r'^bgp\s+router-id\s+(\S+)', inner_stripped)
                if m_rid:
                    bgp_router_id = m_rid.group(1)
                    i += 1
                    continue
                # neighbor <ip> remote-as <peer>: グローバル（v4/v6）に仮登録
                m2 = re.match(r'^neighbor\s+(\S+)\s+remote-as\s+(\d+)', inner_stripped)
                if m2:
                    _bgp_pre[m2.group(1)] = int(m2.group(2))
                    i += 1
                    continue
                # address-family ipv6 内: neighbor <ip> activate → v6 として確定
                if _in_af_ipv6:
                    m_act = re.match(r'^neighbor\s+(\S+)\s+activate', inner_stripped)
                    if m_act:
                        _bgp_v6_activated.add(m_act.group(1))
                i += 1
            continue

        # router ospf <pid>
        m = re.match(r'^router\s+ospf\s+(\d+)', stripped)
        if m:
            pid = int(m.group(1))
            i += 1
            while i < len(lines):
                inner = lines[i]
                inner_stripped = inner.strip()
                if not inner or inner_stripped == "!" or (inner and not inner[0].isspace() and inner_stripped):
                    break
                # Phase 4: router-id <id>（複数プロセスで複数出現時は最初を採用: 既にセット済みなら上書きしない）
                m_rid = re.match(r'^router-id\s+(\S+)', inner_stripped)
                if m_rid and ospf_router_id is None:
                    ospf_router_id = m_rid.group(1)
                    i += 1
                    continue
                # network <addr> <wildcard> area <a>
                m2 = re.match(r'^network\s+(\S+)\s+(\S+)\s+area\s+(\S+)', inner_stripped)
                if m2:
                    addr = m2.group(1)
                    wildcard = m2.group(2)
                    area = m2.group(3)
                    try:
                        prefixlen = _wildcard_to_prefixlen(wildcard)
                        # prefixlen=0 は wildcard 全1（全ホストマッチ）で不正な OSPF network
                        if prefixlen > 0:
                            network_cidr = f"{addr}/{prefixlen}"
                            ospf_networks.append(OspfNetwork(
                                process=pid,
                                network=network_cidr,
                                area=area,
                            ))
                    except ValueError:
                        pass
                i += 1
            continue

        # ip route <prefix> <mask> <next_hop>
        m = re.match(r'^ip\s+route\s+(\S+)\s+(\S+)\s+(\S+)', stripped)
        if m:
            prefix_addr = m.group(1)
            prefix_mask = m.group(2)
            next_hop = m.group(3)
            try:
                prefixlen = _mask_to_prefixlen(prefix_mask)
                prefix_cidr = f"{prefix_addr}/{prefixlen}"
                static_routes.append(StaticRoute(
                    prefix=prefix_cidr,
                    next_hop=next_hop,
                    af=AF_V4,
                ))
            except ValueError:
                pass
            i += 1
            continue

        # Phase 3G: ipv6 router ospf <pid> ブロック（配下行は無視。インターフェース参照は interface ブロックで収集済み）
        m = re.match(r'^ipv6\s+router\s+ospf\s+(\d+)', stripped, re.IGNORECASE)
        if m:
            i += 1
            while i < len(lines):
                inner = lines[i]
                inner_stripped = inner.strip()
                if not inner or inner_stripped == "!" or (inner and not inner[0].isspace() and inner_stripped):
                    break
                i += 1
            continue

        # Phase 3G: ipv6 route <prefix/len> <nexthop>
        m = re.match(r'^ipv6\s+route\s+(\S+)\s+(\S+)', stripped, re.IGNORECASE)
        if m:
            v6_prefix = m.group(1)
            v6_nexthop = m.group(2)
            try:
                # prefix 正規化: ipaddress でホストビット除去
                v6_net = str(ipaddress.ip_network(v6_prefix, strict=False))
                static_routes.append(StaticRoute(
                    prefix=v6_net,
                    next_hop=normalize_v6(v6_nexthop),
                    af=AF_V6,
                ))
            except ValueError:
                pass
            i += 1
            continue

        i += 1

    # Phase 3G: パース後処理 — BGP v4 確定（_bgp_pre のうち v6 activated 以外、v6 側と対称にソート）
    for nbr_ip, peer_as in sorted(_bgp_pre.items()):
        if nbr_ip not in _bgp_v6_activated:
            bgp_neighbors.append(BgpNeighbor(
                neighbor_ip=nbr_ip,
                peer_as=peer_as,
                af=AF_V4,
            ))

    # Phase 3G: パース後処理 — BGP v6 確定（address-family ipv6 で activate 済み）
    for nbr_ip in sorted(_bgp_v6_activated):
        peer_as = _bgp_pre.get(nbr_ip)
        bgp_neighbors.append(BgpNeighbor(
            neighbor_ip=normalize_v6(nbr_ip),
            peer_as=peer_as,
            af=AF_V6,
        ))

    # Phase 3G: パース後処理 — OSPFv3 確定
    # _ospfv3_if_buf: {if_name: [(pid, area), ...]}
    # IF の addresses から v6 グローバルアドレスを参照して v6 サブネットを導出
    if_name_to_addrs: dict[str, list[dict]] = {iface.name: iface.addresses for iface in interfaces}
    for if_name, pid_area_list in sorted(_ospfv3_if_buf.items()):
        addrs = if_name_to_addrs.get(if_name, [])
        # 非 link-local v6 アドレスを取得
        v6_addrs = [
            a for a in addrs
            if a.get("af") == AF_V6 and a.get("scope") != "link-local"
        ]
        for pid, area in pid_area_list:
            if v6_addrs:
                # v6 アドレスからサブネット CIDR を導出（最初の1件を使用）
                a = v6_addrs[0]
                try:
                    net_str = str(ipaddress.ip_interface(f"{a['ip']}/{a['prefix']}").network)
                    ospf_networks.append(OspfNetwork(
                        process=pid,
                        network=net_str,
                        area=area,
                        af=AF_V6,
                    ))
                except (ValueError, KeyError):
                    pass
            else:
                # v6 アドレスが不明な場合は IF 名を格納（JunOS 方式と同様の fallback）
                ospf_networks.append(OspfNetwork(
                    process=pid,
                    network=if_name,
                    area=area,
                    af=AF_V6,
                ))

    return Device(
        hostname=hostname,
        vendor="cisco_ios",
        asn=asn,
        interfaces=interfaces,
        bgp=bgp_neighbors,
        ospf=ospf_networks,
        static=static_routes,
        ospf_router_id=ospf_router_id,
        bgp_router_id=bgp_router_id,
    )
