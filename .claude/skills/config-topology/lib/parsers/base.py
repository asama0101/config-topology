"""
正規化モデル（ベンダー中立 dataclass）

各パーサは config テキストを受け取り、この Device を返す。
build_topology.py はこのモデルだけを見るので、パーサが差異を吸収する。

設計判断:
- asn は int | None（BGP/autonomous-system がなければ None）
- Interface.ip は CIDR 正規化済み文字列 or None（後方互換フィールド）
  Phase 3F から addresses が正本。ip は addresses 中の最初の非 secondary v4 から派生。
- Interface.addresses は [{af, ip, prefix, secondary?, scope?}] のリスト（Phase 3F 追加）
  - af: "v4" / "v6"
  - ip: ホストアドレス（プレフィックス長なし・ipaddress 正規化済み）
  - prefix: int
  - secondary: True のとき IOS secondary（省略 = False 相当）
  - scope: "link-local" 等（省略 = 通常グローバルアドレス）
  - ソート: (af 順 v4<v6, ipaddress オブジェクト, prefix) で決定的に整列
- shutdown のデフォルトは False
- vlan のデフォルトは None（v1 では未使用）
- device id はここでは付けない（build_topology の責務）
- switchport は Cisco IOS 専用フィールド。JunOS は l2_l3='l2' で L2 を表現し、
  switchport は常に None（JunOS には switchport コマンドが存在しない）。
- no ip address は「IP 未設定」を示す IOS 構文だが、これを検知して何かをすることはしない
  （ip address コマンドがなければ ip=None になる）。
"""

from __future__ import annotations

import dataclasses
import ipaddress
from dataclasses import dataclass, field

# ================================================================
# モジュール定数（マジック文字列を一元管理）
# ================================================================

ADMIN_UP: str = "up"
ADMIN_DOWN: str = "down"
L2: str = "l2"
L3: str = "l3"
SOURCE_PARSED: str = "parsed"

# Phase 3F: address family 定数（マジック文字列排除）
AF_V4: str = "v4"
AF_V6: str = "v6"
SCOPE_LINK_LOCAL: str = "link-local"


# ================================================================
# Phase 3F: アドレス共通ヘルパー（DRY 集約）
# ================================================================

def normalize_v6(addr_str: str) -> str:
    """IPv6 アドレス文字列を ipaddress で正規化（省略形）して返す。

    解析失敗時は元の文字列をそのまま返す（クラッシュ防止）。

    Args:
        addr_str: IPv6 アドレス文字列（プレフィックス長なし）

    Returns:
        ipaddress.ip_address で正規化された文字列、失敗時は原文
    """
    try:
        return str(ipaddress.ip_address(addr_str))
    except ValueError:
        return addr_str


def sort_addresses(addresses: list) -> list:
    """addresses リストを決定的にソートして新リストを返す（in-place 非破壊）。

    ソート順:
      1. af 順（"v4" < "v6"）
      2. 同一 af 内: ipaddress オブジェクトの昇順
      3. 同一 ip: prefix 昇順

    link-local を含む全アドレスをソートする（除外はしない）。

    Args:
        addresses: アドレス dict のリスト

    Returns:
        ソート済みの新しいリスト
    """
    def _key(addr: dict):
        af = addr.get("af", AF_V4)
        af_order = 0 if af == AF_V4 else 1
        ip_str = addr.get("ip", "")
        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            ip_obj = (
                ipaddress.ip_address("255.255.255.255") if af == AF_V4
                else ipaddress.ip_address("ffff::ffff")
            )
        return (af_order, ip_obj, addr.get("prefix", 0))

    return sorted(addresses, key=_key)


def derive_ip_from_addresses(addresses: list) -> str | None:
    """addresses リストから ip フィールド値（後方互換 CIDR）を導出する。

    規則:
      - addresses 中の最初の非 secondary v4 アドレスを "host/prefix" 形式で返す
      - v4 が存在しない（v6-only IF 等）または全て secondary の場合は None を返す
      - addresses が空の場合も None を返す

    注意: secondary は除外。v6 アドレスは選択されない。

    Args:
        addresses: アドレス dict のリスト（sort_addresses でソート済みを想定）

    Returns:
        "a.b.c.d/prefixlen" 形式の文字列、または None
    """
    for addr in addresses:
        if addr.get("af") == AF_V4 and not addr.get("secondary"):
            ip = addr.get("ip", "")
            prefix = addr.get("prefix", 0)
            if ip:
                return f"{ip}/{prefix}"
    return None


@dataclass
class Interface:
    name: str
    ip: str | None           # "a.b.c.d/prefixlen"（CIDR 正規化済み・後方互換フィールド）
                             # Phase 3F: addresses 中の最初の非 secondary v4 から派生
    description: str | None
    shutdown: bool = False
    vlan: int | None = None
    # IF属性拡充（optional, default None; source は SOURCE_PARSED）
    admin_status: str | None = None   # ADMIN_UP / ADMIN_DOWN（shutdown 由来）
    oper_status: str | None = None    # None（config から取得不可・将来 SNMP 拡張予定）
    mtu: int | None = None            # int | None
    speed: str | None = None          # 文字列（"1000", "1g" 等）
    duplex: str | None = None         # "full" / "half" / None（JunOS set 形式では通常 None）
    l2_l3: str | None = None          # L2 / L3 / None
    switchport: dict | None = None    # {mode, access_vlan?, trunk_vlans?} | None（IOS 専用）
    encapsulation: str | None = None  # "dot1q", "flexible-ethernet-services" 等
    source: str = SOURCE_PARSED       # 固定値 SOURCE_PARSED
    # Phase 3F: dual-stack アドレス正本
    # エントリ形式: {af: "v4"|"v6", ip: str, prefix: int, secondary?: bool, scope?: str}
    # ソート: (af 順 v4<v6, ipaddress オブジェクト, prefix) で決定的に整列
    addresses: list[dict] = field(default_factory=list)


@dataclass
class BgpNeighbor:
    neighbor_ip: str
    peer_as: int | None
    af: str = AF_V4          # Phase 3G: address family ("v4" / "v6")


@dataclass
class OspfNetwork:
    process: int | None
    network: str             # CIDR
    area: str
    af: str = AF_V4          # Phase 3G: address family ("v4" = OSPFv2 / "v6" = OSPFv3)


@dataclass
class StaticRoute:
    prefix: str              # CIDR
    next_hop: str
    af: str = AF_V4          # Phase 3G: address family ("v4" / "v6")


@dataclass
class Device:
    hostname: str
    vendor: str              # "cisco_ios" / "juniper_junos"
    asn: int | None
    interfaces: list[Interface] = field(default_factory=list)
    bgp: list[BgpNeighbor] = field(default_factory=list)
    ospf: list[OspfNetwork] = field(default_factory=list)
    static: list[StaticRoute] = field(default_factory=list)
    # Phase 4 (router-id): device 単位の router-id（None = 未設定）
    ospf_router_id: str | None = None
    bgp_router_id: str | None = None
