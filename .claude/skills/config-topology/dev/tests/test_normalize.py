"""§6.3 共通規則: IP / CIDR / OSPF area 正規化のテスト。"""
import pytest

from lib import normalize as N

pytestmark = pytest.mark.unit


def test_norm_ipv4_strips_leading_zeros():
    assert N.norm_ipv4("010.000.000.001") == "10.0.0.1"
    assert N.norm_ipv4("10.0.0.1") == "10.0.0.1"


def test_mask_to_prefix():
    assert N.mask_to_prefix("255.255.255.252") == 30
    assert N.mask_to_prefix("255.255.255.0") == 24
    assert N.mask_to_prefix("255.255.255.255") == 32


def test_wildcard_to_prefix():
    assert N.wildcard_to_prefix("0.0.0.255") == 24
    assert N.wildcard_to_prefix("0.0.0.0") == 32
    assert N.wildcard_to_prefix("0.0.0.3") == 30


def test_norm_cidr_removes_host_bits():
    assert N.norm_cidr("192.168.1.0", 24) == "192.168.1.0/24"
    assert N.norm_cidr("10.0.0.1", 30) == "10.0.0.0/30"


def test_norm_cidr_str_v4_and_v6():
    assert N.norm_cidr_str("0.0.0.0/0") == "0.0.0.0/0"
    assert N.norm_cidr_str("2001:db8:0:0::/64") == "2001:db8::/64"


def test_norm_ipv6_rfc5952():
    assert N.norm_ipv6("2001:0db8:0000:0000:0000:0000:0000:0001") == "2001:db8::1"
    assert N.norm_ipv6("FE80::1") == "fe80::1"


def test_v6_scope_link_local():
    assert N.v6_scope("fe80::1") == "link-local"
    assert N.v6_scope("2001:db8::1") is None


@pytest.mark.parametrize("raw,expected", [
    ("0", "0"),
    ("1", "1"),
    ("100", "100"),
    ("00", "0"),
    ("01", "1"),
    ("0.0.0.0", "0"),
    ("0.0.0.1", "1"),
    ("0.0.1.0", "256"),
    ("1.2.3.4", "16909060"),
    ("backbone", "backbone"),
    ("0.0.0.999", "0.0.0.999"),
])
def test_norm_ospf_area(raw, expected):
    assert N.norm_ospf_area(raw) == expected


# ---------------------------------------------------------------------------
# #9: asdot_to_asplain 単体テスト
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("65001", 65001),          # ドット無し → そのまま int
    ("0", 0),
    ("4294967295", 4294967295),  # 最大 32bit ASN
    ("0.0", 0),                # asdot: 0*65536+0
    ("0.1", 1),                # asdot: 0*65536+1
    ("1.0", 65536),            # asdot: 1*65536+0
    ("1.1", 65537),            # asdot: 1*65536+1
    ("2.100", 2 * 65536 + 100),
    ("65535.65535", 65535 * 65536 + 65535),
])
def test_asdot_to_asplain(raw, expected):
    assert N.asdot_to_asplain(raw) == expected


# ---------------------------------------------------------------------------
# E: asdot_to_asplain の範囲バリデーション
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "65536.0",    # 65536*65536+0 = 4294967296 > 2^32-1
    "65536.1",
    "100000.0",
])
def test_asdot_to_asplain_out_of_range_raises(bad):
    """asdot の結果が 0〜4294967295 の範囲外なら ValueError を投げること。"""
    with pytest.raises(ValueError):
        N.asdot_to_asplain(bad)


def test_asdot_to_asplain_max_valid_unchanged():
    """asdot の最大有効値 65535.65535 = 4294967295 は ValueError を投げないこと（境界値）。"""
    assert N.asdot_to_asplain("65535.65535") == 4294967295


def test_asdot_to_asplain_plain_out_of_range_raises():
    """ドット無し（asplain）で 4294967296 は ValueError を投げること。"""
    with pytest.raises(ValueError):
        N.asdot_to_asplain("4294967296")
