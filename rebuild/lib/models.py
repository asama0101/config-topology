"""ベンダー中立の正規化データモデル（要件書 §4.1）。パイプライン全体の中心。"""
import ipaddress
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Address:
    af: str            # "v4" | "v6"
    ip: str            # ホストアドレス（prefix なし・正規化済み）
    prefix: int
    secondary: bool = False
    scope: Optional[str] = None   # "link-local" | None

    def sort_key(self):
        fam = 0 if self.af == "v4" else 1
        return (fam, int(ipaddress.ip_address(self.ip)), self.prefix)

    def to_dict(self):
        d = {"af": self.af, "ip": self.ip, "prefix": self.prefix}
        if self.secondary:
            d["secondary"] = True
        if self.scope:
            d["scope"] = self.scope
        return d


@dataclass
class BgpNeighbor:
    neighbor_ip: str
    peer_as: Optional[int]
    af: str

    def to_dict(self):
        return {"neighbor_ip": self.neighbor_ip, "peer_as": self.peer_as, "af": self.af}


@dataclass
class OspfNetwork:
    process: Optional[int]
    network: str
    area: str
    af: str

    def to_dict(self):
        return {"process": self.process, "network": self.network,
                "area": self.area, "af": self.af}


@dataclass
class StaticRoute:
    prefix: str
    next_hop: str
    af: str

    def to_dict(self):
        return {"prefix": self.prefix, "next_hop": self.next_hop, "af": self.af}


@dataclass
class Interface:
    name: str
    addresses: List[Address] = field(default_factory=list)
    description: Optional[str] = None
    shutdown: bool = False
    admin_status: Optional[str] = None
    oper_status: Optional[str] = None
    mtu: Optional[int] = None
    speed: Optional[str] = None
    duplex: Optional[str] = None
    l2_l3: Optional[str] = None
    switchport: Optional[dict] = None
    encapsulation: Optional[str] = None
    vlan: Optional[int] = None

    def sorted_addresses(self):
        return sorted(self.addresses, key=lambda a: a.sort_key())

    def derived_ip(self):
        """addresses 中、並び順先頭の非 secondary v4 から `a.b.c.d/prefix` を派生（§4.1）。"""
        for a in self.sorted_addresses():
            if a.af == "v4" and not a.secondary:
                return "%s/%s" % (a.ip, a.prefix)
        return None

    def to_dict(self):
        return {
            "name": self.name,
            "addresses": [a.to_dict() for a in self.sorted_addresses()],
            "ip": self.derived_ip(),
            "description": self.description,
            "shutdown": self.shutdown,
            "admin_status": self.admin_status,
            "oper_status": self.oper_status,
            "mtu": self.mtu,
            "speed": self.speed,
            "duplex": self.duplex,
            "l2_l3": self.l2_l3,
            "switchport": self.switchport,
            "encapsulation": self.encapsulation,
            "vlan": self.vlan,
        }


@dataclass
class Device:
    hostname: str
    vendor: str
    as_: Optional[int] = None
    ospf_router_id: Optional[str] = None
    bgp_router_id: Optional[str] = None
    interfaces: List[Interface] = field(default_factory=list)
    bgp: List[BgpNeighbor] = field(default_factory=list)
    ospf: List[OspfNetwork] = field(default_factory=list)
    static: List[StaticRoute] = field(default_factory=list)

    def to_dict(self):
        return {
            "hostname": self.hostname,
            "vendor": self.vendor,
            "as": self.as_,
            "ospf_router_id": self.ospf_router_id,
            "bgp_router_id": self.bgp_router_id,
            "interfaces": [i.to_dict() for i in self.interfaces],
            "bgp": [n.to_dict() for n in self.bgp],
            "ospf": [o.to_dict() for o in self.ospf],
            "static": [s.to_dict() for s in self.static],
        }
