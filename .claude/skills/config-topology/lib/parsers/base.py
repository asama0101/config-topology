"""パーサ共通ヘルパ。"""

_SENSITIVE = ("password", "secret", "snmp community", "snmp-server community")


def is_sensitive_line(line):
    """機密キーワードを含む行か（要件書 §9.2）。含む行はパースしない。"""
    low = line.lower()
    return any(k in low for k in _SENSITIVE)


def ensure_ospf(iface) -> dict:
    """iface.ospf が未初期化（None）なら空 dict で初期化して返す。

    ios.py / junos.py で重複していた _ensure_ospf を一箇所に集約（DRY 解消）。
    Interface 型を import せず汎用に書くことで循環 import を回避する。
    """
    if iface.ospf is None:
        iface.ospf = {}
    return iface.ospf
