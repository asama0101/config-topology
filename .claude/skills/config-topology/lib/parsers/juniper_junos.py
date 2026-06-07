"""
Juniper JunOS パーサ（set 形式）

全行 `set ...` 形式のコンフィグをパースし、正規化 Device を返す。

パース規則（vendor-parsing.md より）:
- set system host-name X → Device.hostname
- set interfaces <if> description "X" → description（クォート除去）
- set interfaces <if> unit N family inet address A.B.C.D/PL → ip（v4 → L3 判定）
- set interfaces <if> unit N family inet6 address X:Y:Z/PL → v6（v6 → L3 判定）
  - fe80::/10（link-local）には scope:"link-local" を付与
- set interfaces <if> disable → shutdown=True
- set routing-options autonomous-system <asn> → Device.asn
- set protocols bgp group <g> neighbor <ip> peer-as <peer> → BgpNeighbor
- set routing-options static route <prefix> next-hop <ip> → StaticRoute
- OSPF: best-effort（v1）

IF 名の取り扱い:
- `set interfaces <if>` の <if> 部分をそのまま使う
- unit は名前に含めない（ge-0/0/0 unit 0 → name="ge-0/0/0"）
"""

from __future__ import annotations

import ipaddress
import re

from .base import (
    ADMIN_DOWN, ADMIN_UP, AF_V4, AF_V6, L2, L3, SCOPE_LINK_LOCAL,
    BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute,
    derive_ip_from_addresses, normalize_v6, sort_addresses,
)


def detect(text: str) -> bool:
    """
    JunOS set 形式 config かどうかを判定。

    行の過半数が `set ` で始まること。
    """
    if not text.strip():
        return False

    lines = text.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]
    if not non_empty:
        return False

    set_count = sum(1 for ln in non_empty if ln.strip().startswith("set "))
    return set_count / len(non_empty) > 0.5


def _strip_quotes(s: str) -> str:
    """前後のダブルクォートを除去する。"""
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def parse(text: str) -> Device:
    """
    JunOS set 形式コンフィグをパースして Device を返す。

    Phase 3F 拡張:
    - family inet address と family inet6 address を addresses リストに収集
    - addresses は (af 順 v4<v6, ipaddress オブジェクト, prefix) でソート（決定的）
    - ip フィールドは addresses 中の最初の非 secondary v4 から派生（後方互換）
    - unit は v1 では IF 名に含めない（unit 集約方針踏襲）
    """
    hostname = ""
    asn: int | None = None
    bgp_neighbors: list[BgpNeighbor] = []
    ospf_networks: list[OspfNetwork] = []
    static_routes: list[StaticRoute] = []
    # Phase 4 (router-id): device 単位の router-id
    ospf_router_id: str | None = None
    bgp_router_id: str | None = None
    _global_router_id: str | None = None  # set routing-options router-id（フォールバック用）

    # IF ごとのデータを収集するための辞書
    # key: if_name, value: dict with keys ip, description, shutdown, mtu, speed,
    #                       encapsulation, l2_flag (bool), addresses (list)
    if_data: dict[str, dict] = {}

    def ensure_if(name: str) -> None:
        if name not in if_data:
            if_data[name] = {
                "ip": None,
                "description": None,
                "shutdown": False,
                "mtu": None,
                "speed": None,
                "encapsulation": None,
                "l2_flag": False,   # family ethernet-switching が出現したか
                "addresses": [],    # Phase 3F: アドレスリスト
            }

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("set "):
            continue
        # "set " を除去してトークン分割
        rest = stripped[4:]

        # set system host-name X
        m = re.match(r'^system\s+host-name\s+(\S+)', rest)
        if m:
            hostname = m.group(1)
            continue

        # set interfaces <if> description "X"
        m = re.match(r'^interfaces\s+(\S+)\s+description\s+(.*)', rest)
        if m:
            if_name = m.group(1)
            desc = _strip_quotes(m.group(2).strip())
            ensure_if(if_name)
            if_data[if_name]["description"] = desc
            continue

        # set interfaces <if> unit N family inet address A.B.C.D/PL
        m = re.match(r'^interfaces\s+(\S+)\s+unit\s+\d+\s+family\s+inet\s+address\s+(\S+)', rest)
        if m:
            if_name = m.group(1)
            cidr = m.group(2)
            ensure_if(if_name)
            # Phase 3F: addresses に v4 エントリを追加（先勝ち廃止・全アドレス収集）
            if "/" in cidr:
                addr_str, prefix_str = cidr.rsplit("/", 1)
                try:
                    prefix = int(prefix_str)
                    if_data[if_name]["addresses"].append(
                        {"af": "v4", "ip": addr_str, "prefix": prefix}
                    )
                    # ip フィールド: 後方互換（最初の v4 を採用・先勝ちは維持）
                    if if_data[if_name]["ip"] is None:
                        if_data[if_name]["ip"] = cidr
                except (ValueError, TypeError):
                    pass
            continue

        # set interfaces <if> unit N family inet6 address X:Y:Z/PL（Phase 3F 追加）
        m = re.match(r'^interfaces\s+(\S+)\s+unit\s+\d+\s+family\s+inet6\s+address\s+(\S+)', rest)
        if m:
            if_name = m.group(1)
            cidr6 = m.group(2)
            ensure_if(if_name)
            if "/" in cidr6:
                addr6_str, prefix6_str = cidr6.rsplit("/", 1)
                try:
                    prefix6 = int(prefix6_str)
                    normalized = normalize_v6(addr6_str)
                    addr_entry: dict = {"af": AF_V6, "ip": normalized, "prefix": prefix6}
                    # link-local（fe80::/10）に scope:"link-local" を付与（IOS と対称）
                    try:
                        if ipaddress.ip_address(normalized).is_link_local:
                            addr_entry["scope"] = SCOPE_LINK_LOCAL
                    except ValueError:
                        pass
                    if_data[if_name]["addresses"].append(addr_entry)
                except (ValueError, TypeError):
                    pass
            continue

        # set interfaces <if> disable
        m = re.match(r'^interfaces\s+(\S+)\s+disable$', rest)
        if m:
            if_name = m.group(1)
            ensure_if(if_name)
            if_data[if_name]["shutdown"] = True
            continue

        # set interfaces <if> mtu <val>（\d+ マッチ済みなので ValueError は発生しない）
        m = re.match(r'^interfaces\s+(\S+)\s+mtu\s+(\d+)', rest)
        if m:
            if_name = m.group(1)
            ensure_if(if_name)
            if_data[if_name]["mtu"] = int(m.group(2))
            continue

        # set interfaces <if> speed <val>
        m = re.match(r'^interfaces\s+(\S+)\s+speed\s+(\S+)', rest)
        if m:
            if_name = m.group(1)
            ensure_if(if_name)
            if_data[if_name]["speed"] = m.group(2)
            continue

        # set interfaces <if> encapsulation <val>
        m = re.match(r'^interfaces\s+(\S+)\s+encapsulation\s+(\S+)', rest)
        if m:
            if_name = m.group(1)
            ensure_if(if_name)
            if_data[if_name]["encapsulation"] = m.group(2)
            continue

        # set interfaces <if> unit N family ethernet-switching ...  → L2 フラグ
        m = re.match(r'^interfaces\s+(\S+)\s+unit\s+\d+\s+family\s+ethernet-switching', rest)
        if m:
            if_name = m.group(1)
            ensure_if(if_name)
            if_data[if_name]["l2_flag"] = True
            continue

        # set routing-options autonomous-system <asn>
        m = re.match(r'^routing-options\s+autonomous-system\s+(\d+)', rest)
        if m:
            asn = int(m.group(1))
            continue

        # Phase 4: set routing-options router-id <id>（グローバル router-id）
        m = re.match(r'^routing-options\s+router-id\s+(\S+)', rest)
        if m:
            _global_router_id = m.group(1)
            bgp_router_id = m.group(1)
            continue

        # Phase 4: set protocols ospf router-id <id>（OSPF 専用 router-id）
        m = re.match(r'^protocols\s+ospf\s+router-id\s+(\S+)', rest)
        if m:
            ospf_router_id = m.group(1)
            continue

        # Phase 4: set protocols ospf3 router-id <id>（OSPFv3 専用 router-id）
        # ospf 専用 router-id が未設定の場合のみセット（ospf 専用 > ospf3 > グローバル 優先）
        m = re.match(r'^protocols\s+ospf3\s+router-id\s+(\S+)', rest)
        if m and ospf_router_id is None:
            ospf_router_id = m.group(1)
            continue

        # set protocols bgp group <g> neighbor <ip> peer-as <peer>
        m = re.match(r'^protocols\s+bgp\s+group\s+\S+\s+neighbor\s+(\S+)\s+peer-as\s+(\d+)', rest)
        if m:
            nbr_ip = m.group(1)
            peer_as = int(m.group(2))
            # Phase 3G: neighbor IP が v6 なら af=v6、それ以外は af=v4
            try:
                nbr_af = AF_V6 if ipaddress.ip_address(nbr_ip).version == 6 else AF_V4
            except ValueError:
                nbr_af = AF_V4
            if nbr_af == AF_V6:
                nbr_ip = normalize_v6(nbr_ip)
            bgp_neighbors.append(BgpNeighbor(
                neighbor_ip=nbr_ip,
                peer_as=peer_as,
                af=nbr_af,
            ))
            continue

        # set routing-options static route <prefix> next-hop <ip>（v4）
        m = re.match(r'^routing-options\s+static\s+route\s+(\S+)\s+next-hop\s+(\S+)', rest)
        if m:
            static_routes.append(StaticRoute(
                prefix=m.group(1),
                next_hop=m.group(2),
                af=AF_V4,
            ))
            continue

        # Phase 3G: set routing-options rib inet6.0 static route <prefix> next-hop <ip>
        m = re.match(r'^routing-options\s+rib\s+inet6\.0\s+static\s+route\s+(\S+)\s+next-hop\s+(\S+)', rest)
        if m:
            v6_prefix_raw = m.group(1)
            v6_nexthop = m.group(2)
            try:
                # 修正2: IOS と対称に ipaddress で正規化（ホストビット除去）
                v6_prefix_normalized = str(ipaddress.ip_network(v6_prefix_raw, strict=False))
            except ValueError:
                continue
            static_routes.append(StaticRoute(
                prefix=v6_prefix_normalized,
                next_hop=normalize_v6(v6_nexthop),
                af=AF_V6,
            ))
            continue

        # OSPF (best-effort v1):
        # set protocols ospf area <a> interface <if>
        m = re.match(r'^protocols\s+ospf\s+area\s+(\S+)\s+interface\s+(\S+)', rest)
        if m:
            area = m.group(1)
            if_ref = m.group(2)
            ospf_networks.append(OspfNetwork(
                process=None,
                network=if_ref,   # v1: IF 名を格納（build_topology で IP から導出可能）
                area=area,
                af=AF_V4,
            ))
            continue

        # Phase 3G: set protocols ospf3 area <a> interface <if>
        m = re.match(r'^protocols\s+ospf3\s+area\s+(\S+)\s+interface\s+(\S+)', rest)
        if m:
            area = m.group(1)
            if_ref = m.group(2)
            # IF 参照をベース名に正規化（ge-0/0/0.0 → ge-0/0/0）
            base_if = if_ref.split(".")[0]
            ospf_networks.append(OspfNetwork(
                process=None,
                network=base_if,  # IF 名を格納（build_topology で IP から導出可能）
                area=area,
                af=AF_V6,
            ))
            continue

    # IF データを Interface リストに変換（収集順を保持）
    interfaces: list[Interface] = []
    for name, data in if_data.items():
        # Phase 3F: addresses をソートして確定（base.sort_addresses で DRY）
        sorted_addrs = sort_addresses(data.get("addresses", []))
        # ip フィールド: addresses から派生（後方互換）
        # addresses がある場合は最初の非 secondary v4 から、なければ data["ip"] を信頼
        if sorted_addrs:
            derived_ip = derive_ip_from_addresses(sorted_addrs)
        else:
            derived_ip = data["ip"]
        # l2_l3 判定（JunOS: family ethernet-switching が L2 判定で優先される）
        # Phase 3F: v6-only IF（inet6 のみ）でも addresses があれば L3 扱い
        # switchport は常に None（JunOS には switchport コマンドがなく l2_l3='l2' で表現）
        if data["l2_flag"]:
            l2_l3 = L2
        elif derived_ip is not None or any(a.get("af") == "v6" for a in sorted_addrs):
            l2_l3 = L3
        else:
            l2_l3 = None
        # admin_status: disable 由来（定数使用）
        admin_status = ADMIN_DOWN if data["shutdown"] else ADMIN_UP
        interfaces.append(Interface(
            name=name,
            ip=derived_ip,
            description=data["description"],
            shutdown=data["shutdown"],
            mtu=data["mtu"],
            speed=data["speed"],
            encapsulation=data["encapsulation"],
            l2_l3=l2_l3,
            admin_status=admin_status,
            addresses=sorted_addrs,
        ))

    # Phase 4 (router-id): ospf 専用 router-id がない場合はグローバル値をフォールバック
    # Juniper はグローバル router-id を OSPF/BGP 共通に使う。優先: ospf 専用 > グローバル
    if ospf_router_id is None and _global_router_id is not None:
        ospf_router_id = _global_router_id

    return Device(
        hostname=hostname,
        vendor="juniper_junos",
        asn=asn,
        interfaces=interfaces,
        bgp=bgp_neighbors,
        ospf=ospf_networks,
        static=static_routes,
        ospf_router_id=ospf_router_id,
        bgp_router_id=bgp_router_id,
    )
