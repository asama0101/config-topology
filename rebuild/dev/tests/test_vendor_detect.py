"""§2.3 ベンダー自動判定・§9.2 機密行フィルタのテスト。"""
import pytest

from lib.parsers import detect_vendor
from lib.parsers.base import is_sensitive_line

pytestmark = pytest.mark.unit


def test_detect_ios(ios_cfg_text):
    assert detect_vendor(ios_cfg_text) == "cisco_ios"


def test_detect_junos(junos_cfg_text):
    assert detect_vendor(junos_cfg_text) == "juniper_junos"


def test_detect_junos_over_50pct_set():
    text = "## comment\n" + "\n".join("set x %d" % i for i in range(9))  # 9/10 = 90% set
    assert detect_vendor(text) == "juniper_junos"


def test_detect_ios_guard_excludes_over_40pct_set():
    # IOS 特徴行(hostname) を持つが set 行が 40% 超 50% 以下 → IOS 除外・JunOS にも届かず None。
    # 非空 20 行中 set 9 行 = 45%（>40% ガード該当・>50% JunOS 未満）→ None。
    lines = ["hostname R1"] + ["filler %d" % i for i in range(10)] + ["set x %d" % i for i in range(9)]
    assert detect_vendor("\n".join(lines)) is None


def test_detect_unknown_returns_none():
    assert detect_vendor("foo bar\nbaz qux\n") is None


def test_detect_blank_only_returns_none():
    assert detect_vendor("\n\n   \n") is None


def test_is_sensitive_line():
    assert is_sensitive_line(" enable secret 5 $1$abc")
    assert is_sensitive_line(" password cisco123")
    assert is_sensitive_line("set snmp community public")
    assert is_sensitive_line("snmp-server community public RO")
    assert not is_sensitive_line(" description to-R2")
    assert not is_sensitive_line(" ip address 10.0.0.1 255.255.255.252")


def test_detect_set_exactly_50pct_with_ios_features_is_none():
    # set ちょうど 50%（>0.5 不成立）かつ IOS 特徴あり（50%>40% で IOS 除外）→ None
    lines = ["hostname R1", "interface GigabitEthernet0/0", "set a", "set b"]  # 2/4 = 50%
    from lib.parsers import detect_vendor
    assert detect_vendor("\n".join(lines)) is None


def test_detect_set_exactly_40pct_with_ios_features_is_ios():
    # set ちょうど 40%（<=0.4 成立）かつ IOS 特徴あり → cisco_ios
    lines = ["hostname R1", "interface GigabitEthernet0/0", "x1", "set a", "set b"]  # 2/5 = 40%
    from lib.parsers import detect_vendor
    assert detect_vendor("\n".join(lines)) == "cisco_ios"


def test_set_ratio_ignores_indented_ios_route_map_set():
    # インデント付き route-map `set` は JunOS set としてカウントしない → cisco_ios のまま
    from lib.parsers import detect_vendor
    text = "hostname R1\ninterface GigabitEthernet0/0\nroute-map RM permit 10\n set community 65001:100\n set local-preference 200\n!\n"
    assert detect_vendor(text) == "cisco_ios"
