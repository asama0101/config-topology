"""Cisco IOS / IOS-XE パーサ（要件書 §6.1）。"""
import re

from ..models import Address, BgpNeighbor, Device, Interface, OspfNetwork, StaticRoute
from ..normalize import (mask_to_prefix, norm_cidr, norm_cidr_str, norm_ipv4,
                         norm_ipv6, norm_ospf_area, v6_scope, wildcard_to_prefix)
from .base import is_sensitive_line


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


def _parse_bgp_line(dev: Device, s: str, bgp_af: str, neighbors: dict, warnings: list) -> None:
    """router bgp ブロック内の1行を解析（§6.1）。neighbor / bgp router-id / v6 activate。"""
    m = re.match(r"^bgp router-id\s+(\S+)", s)
    if m:
        dev.bgp_router_id = m.group(1)
        return
    m = re.match(r"^neighbor\s+(\S+)\s+remote-as\s+(\d+)", s)
    if m:
        ip, peer = m.group(1), int(m.group(2))
        try:
            af = "v6" if ":" in ip else "v4"
            nip = norm_ipv6(ip) if af == "v6" else norm_ipv4(ip)
            nb = BgpNeighbor(nip, peer, af)
            dev.bgp.append(nb)
            neighbors[nip] = nb
        except Exception as e:                       # noqa: BLE001
            warnings.append("bgp neighbor parse failed: %s (%s)" % (s, e))
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


def _parse_ospf_line(dev: Device, s: str, ospf_pid, warnings: list) -> None:
    """router ospf ブロック内の1行を解析（§6.1）。router-id / network area。"""
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


def parse_ios(text: str, warnings: list) -> Device:
    """Cisco IOS / IOS-XE config テキストを解析し正規化 Device を返す（要件書 §6.1）。

    パース失敗行は握りつぶし warnings(list) に文字列を追記し継続する（§6.3）。
    """
    dev = Device(hostname="", vendor="cisco_ios")
    cur = None
    context = None        # None | "interface" | "bgp" | "ospf"
    ospf_pid = None
    bgp_af = "v4"
    neighbors = {}
    pending_ospf3 = []   # [(iface, pid, area)] — IF アドレス確定後に network 解決

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
                _parse_bgp_line(dev, s, bgp_af, neighbors, warnings)
        elif context == "ospf":
            _parse_ospf_line(dev, s, ospf_pid, warnings)

    finish_iface()
    for iface, pid, area in pending_ospf3:
        network = _iface_v6_network(iface) or iface.name
        dev.ospf.append(OspfNetwork(pid, network, area, "v6"))
    return dev
