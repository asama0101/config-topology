"""§5.5 ID 採番規則のテスト。"""
import pytest

from lib.idgen import assign_device_ids, interface_id, segment_id

pytestmark = pytest.mark.unit


class _D:
    def __init__(self, hostname):
        self.hostname = hostname


def _ids(hostnames):
    return assign_device_ids([_D(h) for h in hostnames])


def test_simple_dedup():
    assert _ids(["r1", "r1", "r2"]) == ["r1", "r1-2", "r2"]


def test_collision_bump():
    # 2台目 R1 が r1-2、R1-2 はそれと衝突するため r1-3（§5.5 訂正済み例）
    assert _ids(["R1", "R1", "R1-2"]) == ["r1", "r1-2", "r1-3"]


def test_empty_hostname():
    assert _ids(["", ""]) == ["device", "device-2"]


def test_slug_non_alnum_replaced():
    assert _ids(["Core.SW_1"]) == ["core-sw-1"]   # 英数字とハイフン以外 → '-'


def test_interface_id():
    assert interface_id("r1", "GigabitEthernet0/0") == "r1::GigabitEthernet0/0"
    assert interface_id("r2", "ge-0/0/0") == "r2::ge-0/0/0"


def test_segment_id_v4():
    assert segment_id("192.168.1.0/24") == "seg-192_168_1_0_24"


def test_segment_id_v6_deterministic():
    sid = segment_id("2001:db8:1::/64")
    assert sid.startswith("seg-2001_db8_1")
    assert ":" not in sid and "/" not in sid and "." not in sid
