"""§5.2/§7.5 devices/interfaces 構築のテスト。"""
import pytest

from lib.models import Address, Device, Interface
from lib.build import build_devices_interfaces

pytestmark = pytest.mark.unit


def _dev(hostname, vendor="cisco_ios", **kw):
    return Device(hostname=hostname, vendor=vendor, **kw)


def test_device_dict_full_keys():
    d = _dev("R1", as_=65001)
    ids, devices, interfaces = build_devices_interfaces([d])
    assert ids == ["r1"]
    assert devices[0] == {"id": "r1", "hostname": "R1", "vendor": "cisco_ios",
                          "as": 65001, "ospf_router_id": None, "bgp_router_id": None,
                          "sections": []}


def test_interface_dict_full_keys():
    itf = Interface(name="GigabitEthernet0/0", description="to-R2",
                    addresses=[Address("v4", "10.0.0.1", 30)], l2_l3="l3", admin_status="up")
    d = _dev("R1", interfaces=[itf])
    _, _, interfaces = build_devices_interfaces([d])
    assert interfaces[0] == {
        "id": "r1::GigabitEthernet0/0", "device": "r1", "name": "GigabitEthernet0/0",
        "ip": "10.0.0.1/30", "vlan": None, "description": "to-R2", "shutdown": False,
        "admin_status": "up", "oper_status": None, "mtu": None, "speed": None,
        "duplex": None, "l2_l3": "l3", "switchport": None, "encapsulation": None,
        "source": "parsed", "addresses": [{"af": "v4", "ip": "10.0.0.1", "prefix": 30}],
    }


def test_devices_sorted_by_id_interfaces_in_appearance_order():
    d2 = _dev("R2", vendor="juniper_junos", interfaces=[Interface(name="ge-0/0/0")])
    d1 = _dev("R1", interfaces=[Interface(name="Gi0/0")])
    ids, devices, interfaces = build_devices_interfaces([d2, d1])
    assert ids == ["r2", "r1"]                          # appearance 順の採番
    assert [d["id"] for d in devices] == ["r1", "r2"]    # 出力は id 昇順
    assert [i["id"] for i in interfaces] == ["r2::ge-0/0/0", "r1::Gi0/0"]  # interfaces は出現順


def test_interface_addresses_sorted_and_derived_ip():
    itf = Interface(name="x", addresses=[
        Address("v6", "2001:db8::1", 64), Address("v4", "10.0.0.1", 24)])
    _, _, interfaces = build_devices_interfaces([_dev("R1", interfaces=[itf])])
    assert interfaces[0]["ip"] == "10.0.0.1/24"
    assert [a["af"] for a in interfaces[0]["addresses"]] == ["v4", "v6"]
