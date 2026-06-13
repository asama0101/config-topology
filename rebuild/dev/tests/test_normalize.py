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
