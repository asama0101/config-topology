"""§4.1 データモデル: addresses 並び順・派生 ip・to_dict のテスト。"""
import pytest

from lib.models import Address, Interface, Device

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
