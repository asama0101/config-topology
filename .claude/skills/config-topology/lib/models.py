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
    update_source: Optional[str] = None
    """IOS は `update-source <ifname>`（インターフェース名）、JunOS は `local-address <ip>`
    （ローカル IP 文字列）を格納する。build 側で IP かインターフェース名かを判別して解決する。
    値があるときのみ to_dict() に出力（None は省略）。
    """
    route_reflector_client: bool = False
    """IOS `neighbor route-reflector-client`（True 時のみ to_dict() に出力）。
    JunOS は group cluster 宣言を持つ group の neighbor に True を設定（§6.2）。
    """
    next_hop_self: bool = False
    """IOS `neighbor next-hop-self`（True 時のみ to_dict() に出力）。
    JunOS は next-hop-self をポリシーベースで制御するため本実装では常に False（§6.2）。
    """

    def to_dict(self):
        d = {"neighbor_ip": self.neighbor_ip, "peer_as": self.peer_as, "af": self.af}
        if self.update_source is not None:
            d["update_source"] = self.update_source
        if self.route_reflector_client:
            d["route_reflector_client"] = True
        if self.next_hop_self:
            d["next_hop_self"] = True
        return d


@dataclass
class OspfNetwork:
    process: Optional[int]
    network: str
    area: str
    af: str
    area_type: Optional[str] = None
    """OSPF area タイプ: "stub" / "totally-stubby" / "nssa" / "totally-nssa"。
    設定時のみ to_dict() に出力（None は省略 → golden byte 不変）。§6.1/§6.2 参照。
    """

    def to_dict(self):
        d = {"process": self.process, "network": self.network,
             "area": self.area, "af": self.af}
        if self.area_type is not None:
            d["area_type"] = self.area_type
        return d


@dataclass
class StaticRoute:
    prefix: str
    next_hop: str
    af: str

    def to_dict(self):
        return {"prefix": self.prefix, "next_hop": self.next_hop, "af": self.af}


@dataclass
class Redistribute:
    """ルーティングプロトコル間の再配布設定（要件書 §6.1 C5）。

    into:      再配布先プロトコル（"bgp" または "ospf"）= 文脈（router bgp / router ospf）。
    source:    再配布元プロトコル（connected / static / ospf / bgp / rip / eigrp / isis 等）。
    metric:    metric 値（値があるときのみ to_dict() に出力）。
    route_map: route-map 名（値があるときのみ to_dict() に出力）。
    """
    into: str
    source: str
    metric: Optional[int] = None
    route_map: Optional[str] = None

    def to_dict(self):
        d = {"into": self.into, "source": self.source}
        if self.metric is not None:
            d["metric"] = self.metric
        if self.route_map is not None:
            d["route_map"] = self.route_map
        return d


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
    ospf: Optional[dict] = None

    def sorted_addresses(self):
        return sorted(self.addresses, key=lambda a: a.sort_key())

    def derived_ip(self):
        """addresses 中、並び順先頭の非 secondary v4 から `a.b.c.d/prefix` を派生（§4.1）。"""
        for a in self.sorted_addresses():
            if a.af == "v4" and not a.secondary:
                return "%s/%s" % (a.ip, a.prefix)
        return None

    def to_dict(self):
        d = {
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
        # ospf は値があるときのみ出力。None も空 dict {} も省略してゴールデン YAML の byte 不変を保つ
        # （他 None フィールドとの意図的な非対称。requirements.md §5.2 の例外）
        if self.ospf:
            d["ospf"] = self.ospf
        return d


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
    redistribute: List[Redistribute] = field(default_factory=list)

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
            "redistribute": [r.to_dict() for r in self.redistribute],
        }
