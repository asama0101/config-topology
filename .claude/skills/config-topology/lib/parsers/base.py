"""パーサ共通ヘルパ。"""

_SENSITIVE = ("password", "secret", "snmp community", "snmp-server community")


def is_sensitive_line(line):
    """機密キーワードを含む行か（要件書 §9.2）。含む行はパースしない。"""
    low = line.lower()
    return any(k in low for k in _SENSITIVE)
