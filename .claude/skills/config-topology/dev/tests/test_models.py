"""§4.1 データモデル: addresses 並び順・派生 ip・to_dict のテスト。"""
import pytest

from lib.models import Address, BgpNeighbor, Interface, Device, OspfNetwork

pytestmark = pytest.mark.unit


def test_address_to_dict_omits_default_flags():
    assert Address("v4", "10.0.0.1", 30).to_dict() == {"af": "v4", "ip": "10.0.0.1", "prefix": 30}


def test_address_to_dict_includes_flags_when_set():
    d = Address("v4", "192.168.1.2", 24, secondary=True).to_dict()
    assert d == {"af": "v4", "ip": "192.168.1.2", "prefix": 24, "secondary": True}
    d6 = Address("v6", "fe80::1", 64, scope="link-local").to_dict()
    assert d6 == {"af": "v6", "ip": "fe80::1", "prefix": 64, "scope": "link-local"}


def test_sorted_addresses_v4_before_v6_then_ip_then_prefix():
    addrs = [
        Address("v6", "2001:db8::1", 64),
        Address("v4", "192.168.1.1", 24),
        Address("v4", "10.0.0.1", 24),
        Address("v4", "10.0.0.1", 30),
    ]
    iface = Interface(name="x", addresses=addrs)
    order = [(a.af, a.ip, a.prefix) for a in iface.sorted_addresses()]
    assert order == [
        ("v4", "10.0.0.1", 24),
        ("v4", "10.0.0.1", 30),
        ("v4", "192.168.1.1", 24),
        ("v6", "2001:db8::1", 64),
    ]


def test_derived_ip_first_non_secondary_v4():
    iface = Interface(name="x", addresses=[
        Address("v4", "10.0.0.9", 24, secondary=True),
        Address("v4", "10.0.0.1", 24),
    ])
    assert iface.derived_ip() == "10.0.0.1/24"


def test_derived_ip_none_for_v6_only():
    iface = Interface(name="x", addresses=[Address("v6", "2001:db8::1", 64)])
    assert iface.derived_ip() is None


def test_derived_ip_none_when_no_address():
    assert Interface(name="x").derived_ip() is None


def test_device_as_key_mapping():
    dev = Device(hostname="R1", vendor="cisco_ios", as_=65001)
    assert dev.to_dict()["as"] == 65001
    assert dev.to_dict()["hostname"] == "R1"


# ---------------------------------------------------------------------------
# Interface.ospf フィールドテスト（C2 OSPF interface パラメータ）
# ---------------------------------------------------------------------------

def test_interface_ospf_none_omits_key_from_dict():
    """ospf=None（デフォルト）のとき to_dict() に 'ospf' キーが出ないこと。"""
    iface = Interface(name="GigabitEthernet0/0")
    d = iface.to_dict()
    assert "ospf" not in d


def test_interface_ospf_value_appears_in_dict():
    """ospf が dict 値のとき to_dict() に 'ospf' キーが出ること。"""
    iface = Interface(name="GigabitEthernet0/0", ospf={"cost": 100})
    d = iface.to_dict()
    assert "ospf" in d
    assert d["ospf"] == {"cost": 100}


def test_interface_ospf_subkeys_cost_network_type_passive():
    """ospf サブキーは cost(int)/network_type(str)/passive(True) の組み合わせで出せること。"""
    iface = Interface(name="Gi0/0", ospf={"cost": 10, "network_type": "point-to-point", "passive": True})
    d = iface.to_dict()
    assert d["ospf"] == {"cost": 10, "network_type": "point-to-point", "passive": True}


def test_interface_ospf_partial_subkeys():
    """サブキーは不在のものは含まない（cost のみ等）。"""
    iface = Interface(name="Gi0/0", ospf={"cost": 200})
    d = iface.to_dict()
    assert d["ospf"] == {"cost": 200}
    assert "network_type" not in d["ospf"]
    assert "passive" not in d["ospf"]


# ---------------------------------------------------------------------------
# 修正 3: ospf={} 空 dict の to_dict 防御テスト
# ---------------------------------------------------------------------------

def test_interface_ospf_empty_dict_omits_key_from_dict():
    """ospf={} 空 dict のとき to_dict() に 'ospf' キーが出ないこと。

    None も空 dict {} も値なし扱いとしてキーを省略し、ゴールデン YAML の byte 不変を保つ
    （requirements.md §5.2 の例外的フィールド: 他 None フィールドと意図的に非対称）。
    """
    iface = Interface(name="Gi0/0", ospf={})
    d = iface.to_dict()
    assert "ospf" not in d


# ---------------------------------------------------------------------------
# C1: BgpNeighbor.update_source フィールドテスト
# ---------------------------------------------------------------------------

def test_bgpneighbor_update_source_none_omits_key_from_dict():
    """update_source=None（デフォルト）のとき to_dict() に 'update_source' キーが出ないこと。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
    d = nb.to_dict()
    assert "update_source" not in d
    assert d == {"neighbor_ip": "10.0.0.2", "peer_as": 65002, "af": "v4"}


def test_bgpneighbor_update_source_ifname_appears_in_dict():
    """update_source にインターフェース名がある場合、to_dict() に 'update_source' キーが出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", update_source="Loopback0")
    d = nb.to_dict()
    assert "update_source" in d
    assert d["update_source"] == "Loopback0"


def test_bgpneighbor_update_source_ip_appears_in_dict():
    """update_source に IP アドレスがある場合（JunOS local-address）、to_dict() に出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", update_source="1.1.1.1")
    d = nb.to_dict()
    assert d["update_source"] == "1.1.1.1"


def test_bgpneighbor_default_fields_unchanged():
    """update_source 追加後も既存フィールド（neighbor_ip/peer_as/af）の型・意味が変わらないこと。"""
    nb = BgpNeighbor(neighbor_ip="2001:db8::2", peer_as=65002, af="v6")
    d = nb.to_dict()
    assert d["neighbor_ip"] == "2001:db8::2"
    assert d["peer_as"] == 65002
    assert d["af"] == "v6"
    assert set(d.keys()) == {"neighbor_ip", "peer_as", "af"}  # update_source なし → 3キーのみ


# ---------------------------------------------------------------------------
# C3: OspfNetwork.area_type フィールドテスト
# ---------------------------------------------------------------------------

def test_ospfnetwork_area_type_none_omits_key_from_dict():
    """area_type=None（デフォルト）のとき to_dict() に 'area_type' キーが出ないこと。"""
    o = OspfNetwork(process=1, network="10.0.0.0/24", area="1", af="v4")
    d = o.to_dict()
    assert "area_type" not in d
    assert set(d.keys()) == {"process", "network", "area", "af"}


def test_ospfnetwork_area_type_stub_appears_in_dict():
    """area_type='stub' のとき to_dict() に 'area_type' キーが出ること。"""
    o = OspfNetwork(process=1, network="10.0.0.0/24", area="1", af="v4", area_type="stub")
    d = o.to_dict()
    assert "area_type" in d
    assert d["area_type"] == "stub"


def test_ospfnetwork_area_type_totally_stubby_appears_in_dict():
    """area_type='totally-stubby' のとき to_dict() に出ること。"""
    o = OspfNetwork(process=1, network="10.0.0.0/24", area="2", af="v4", area_type="totally-stubby")
    d = o.to_dict()
    assert d["area_type"] == "totally-stubby"


def test_ospfnetwork_area_type_nssa_appears_in_dict():
    """area_type='nssa' のとき to_dict() に出ること。"""
    o = OspfNetwork(process=1, network="10.0.0.0/24", area="3", af="v4", area_type="nssa")
    d = o.to_dict()
    assert d["area_type"] == "nssa"


def test_ospfnetwork_area_type_totally_nssa_appears_in_dict():
    """area_type='totally-nssa' のとき to_dict() に出ること。"""
    o = OspfNetwork(process=None, network="10.0.0.0/24", area="3", af="v6",
                    area_type="totally-nssa")
    d = o.to_dict()
    assert d["area_type"] == "totally-nssa"


def test_ospfnetwork_existing_fields_unchanged():
    """area_type 追加後も既存フィールド（process/network/area/af）の型・意味が変わらないこと。"""
    o = OspfNetwork(process=10, network="192.168.0.0/24", area="0", af="v4")
    d = o.to_dict()
    assert d["process"] == 10
    assert d["network"] == "192.168.0.0/24"
    assert d["area"] == "0"
    assert d["af"] == "v4"
    assert set(d.keys()) == {"process", "network", "area", "af"}  # area_type なし → 4キーのみ


# ---------------------------------------------------------------------------
# C4: BgpNeighbor.route_reflector_client / next_hop_self フラグテスト
# ---------------------------------------------------------------------------

def test_bgpneighbor_rrc_false_omits_key_from_dict():
    """route_reflector_client=False（デフォルト）のとき to_dict() に 'route_reflector_client' キーが出ないこと。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
    d = nb.to_dict()
    assert "route_reflector_client" not in d


def test_bgpneighbor_rrc_true_appears_in_dict():
    """route_reflector_client=True のとき to_dict() に 'route_reflector_client': True が出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", route_reflector_client=True)
    d = nb.to_dict()
    assert d.get("route_reflector_client") is True


def test_bgpneighbor_nhs_false_omits_key_from_dict():
    """next_hop_self=False（デフォルト）のとき to_dict() に 'next_hop_self' キーが出ないこと。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
    d = nb.to_dict()
    assert "next_hop_self" not in d


def test_bgpneighbor_nhs_true_appears_in_dict():
    """next_hop_self=True のとき to_dict() に 'next_hop_self': True が出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", next_hop_self=True)
    d = nb.to_dict()
    assert d.get("next_hop_self") is True


def test_bgpneighbor_both_flags_true_appear():
    """route_reflector_client=True かつ next_hop_self=True のとき、両キーが to_dict() に出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.3", peer_as=65001, af="v4",
                     route_reflector_client=True, next_hop_self=True)
    d = nb.to_dict()
    assert d.get("route_reflector_client") is True
    assert d.get("next_hop_self") is True


def test_bgpneighbor_flags_false_leaves_base_keys_only():
    """両フラグが False のとき、to_dict() のキー集合に 'route_reflector_client'/'next_hop_self' が含まれないこと（golden byte 不変）。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
    d = nb.to_dict()
    assert "route_reflector_client" not in d
    assert "next_hop_self" not in d
    # 既存フィールドは不変
    assert set(d.keys()) == {"neighbor_ip", "peer_as", "af"}


# ---------------------------------------------------------------------------
# C4b: BgpNeighbor.timers / send_community フィールドテスト
# ---------------------------------------------------------------------------

def test_bgpneighbor_timers_none_omits_key_from_dict():
    """timers=None（デフォルト）のとき to_dict() に 'timers' キーが出ないこと（golden byte 不変）。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
    d = nb.to_dict()
    assert "timers" not in d


def test_bgpneighbor_timers_tuple_appears_in_dict():
    """timers=(10, 30) のとき to_dict() に {"keepalive": 10, "holdtime": 30} が出ること（厳密等価）。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", timers=(10, 30))
    d = nb.to_dict()
    assert "timers" in d
    assert d["timers"] == {"keepalive": 10, "holdtime": 30}


def test_bgpneighbor_timers_various_values():
    """timers=(0, 0) / (60, 180) など任意の整数ペアが正しく出力されること。"""
    nb0 = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", timers=(0, 0))
    assert nb0.to_dict()["timers"] == {"keepalive": 0, "holdtime": 0}
    nb1 = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", timers=(60, 180))
    assert nb1.to_dict()["timers"] == {"keepalive": 60, "holdtime": 180}


def test_bgpneighbor_send_community_none_omits_key_from_dict():
    """send_community=None（デフォルト）のとき to_dict() に 'send_community' キーが出ないこと（golden byte 不変）。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
    d = nb.to_dict()
    assert "send_community" not in d


def test_bgpneighbor_send_community_standard_appears_in_dict():
    """send_community='standard' のとき to_dict() に 'send_community': 'standard' が出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", send_community="standard")
    d = nb.to_dict()
    assert d.get("send_community") == "standard"


def test_bgpneighbor_send_community_extended_appears_in_dict():
    """send_community='extended' のとき to_dict() に 'send_community': 'extended' が出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", send_community="extended")
    d = nb.to_dict()
    assert d.get("send_community") == "extended"


def test_bgpneighbor_send_community_both_appears_in_dict():
    """send_community='both' のとき to_dict() に 'send_community': 'both' が出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4", send_community="both")
    d = nb.to_dict()
    assert d.get("send_community") == "both"


def test_bgpneighbor_timers_and_send_community_combined():
    """timers と send_community が同時に設定されたとき、両フィールドが to_dict() に出ること。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65001, af="v4",
                     timers=(10, 30), send_community="both")
    d = nb.to_dict()
    assert d["timers"] == {"keepalive": 10, "holdtime": 30}
    assert d["send_community"] == "both"


def test_bgpneighbor_new_fields_none_leaves_base_keys_only():
    """timers=None かつ send_community=None のとき、to_dict() に新規キーが混入しないこと（golden byte 不変）。"""
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
    d = nb.to_dict()
    # 新規フィールドがデフォルト状態では既存キーのみ
    assert set(d.keys()) == {"neighbor_ip", "peer_as", "af"}


# ---------------------------------------------------------------------------
# C1b: BgpNeighbor.peer_group フィールドテスト（omit-when-None）
# ---------------------------------------------------------------------------

def test_bgpneighbor_omits_none_peer_group():
    """peer_group=None（デフォルト）のとき to_dict() に 'peer_group' キーが出ないこと（golden byte 不変）。

    peer_group フィールドが追加されても None 時は省略されること。
    壊すと 'peer_group': None が混入しキー集合が変化 → アサート失敗（壊すと赤）。
    """
    nb = BgpNeighbor(neighbor_ip="10.0.0.2", peer_as=65002, af="v4")
    d = nb.to_dict()
    assert "peer_group" not in d
    assert set(d.keys()) == {"neighbor_ip", "peer_as", "af"}


def test_bgpneighbor_peer_group_set_appears_in_dict():
    """peer_group="PG" のとき to_dict() に 'peer_group': 'PG' が出ること。

    壊すと peer_group が省略される → アサート失敗（壊すと赤）。
    """
    nb = BgpNeighbor(neighbor_ip="10.0.0.5", peer_as=65010, af="v4", peer_group="PG")
    d = nb.to_dict()
    assert "peer_group" in d
    assert d["peer_group"] == "PG"


def test_bgpneighbor_peer_group_none_leaves_existing_keys_unchanged():
    """peer_group=None でも既存フィールド（neighbor_ip/peer_as/af）が変わらないこと（後方互換性）。"""
    nb = BgpNeighbor(neighbor_ip="2001:db8::2", peer_as=65002, af="v6")
    d = nb.to_dict()
    assert d["neighbor_ip"] == "2001:db8::2"
    assert d["peer_as"] == 65002
    assert d["af"] == "v6"
    assert "peer_group" not in d
