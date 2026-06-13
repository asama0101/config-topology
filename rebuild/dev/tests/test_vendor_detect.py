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
