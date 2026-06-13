"""Juniper JunOS（set 形式）パーサ（要件書 §6.2）。"""
import re

from ..models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from ..normalize import norm_cidr_str, norm_ipv4, norm_ipv6, norm_ospf_area, v6_scope
from .base import is_sensitive_line


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
        m = re.match(r"^protocols bgp group \S+ neighbor\s+(\S+)\s+peer-as\s+(\d+)", body)
        if m:
            ip, peer = m.group(1), int(m.group(2))
            try:
                af = "v6" if ":" in ip else "v4"
                nip = norm_ipv6(ip) if af == "v6" else norm_ipv4(ip)
                dev.bgp.append(BgpNeighbor(nip, peer, af))
            except Exception as e:                   # noqa: BLE001
                warnings.append("junos bgp neighbor parse failed: %s (%s)" % (body, e))
            continue

        # OSPFv2: protocols ospf area <a> interface <if>
        m = re.match(r"^protocols ospf area\s+(\S+)\s+interface\s+(\S+)", body)
        if m:
            ospf_decls.append((m.group(1), _base_if(m.group(2)), "v4"))
            continue

        # OSPFv3: protocols ospf3 area <a> interface <if>
        m = re.match(r"^protocols ospf3 area\s+(\S+)\s+interface\s+(\S+)", body)
        if m:
            ospf_decls.append((m.group(1), _base_if(m.group(2)), "v6"))
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

    # OSPF network を全 IF 確定後に解決（宣言前 address 対応）
    for area, base_if, af in ospf_decls:
        if af == "v4":
            network = _ospf_v4_network(ifaces.get(base_if)) or base_if
        else:
            network = base_if
        dev.ospf.append(OspfNetwork(None, network, norm_ospf_area(area), af))

    # admin_status 確定・出現順で interfaces 確定
    for iface in ifaces.values():
        iface.admin_status = "down" if iface.shutdown else "up"
        dev.interfaces.append(iface)

    # OSPF 専用 router-id 不在時は routing-options router-id をフォールバック（§5.2.1）
    if dev.ospf_router_id is None:
        dev.ospf_router_id = dev.bgp_router_id

    return dev
