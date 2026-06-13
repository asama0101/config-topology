"""ベンダー判定と dispatch（要件書 §2.3）。"""
import re

from .base import is_sensitive_line  # noqa: F401  (再 export)

_IOS_IF_RE = re.compile(r"^\s*interface\s+\S*Ethernet", re.IGNORECASE)


def _nonempty_lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def _set_ratio(lines):
    if not lines:
        return 0.0
    n = sum(1 for ln in lines if ln.startswith("set "))
    return n / len(lines)


def _has_ios_features(lines):
    for ln in lines:
        s = ln.strip()
        if s.startswith("hostname "):
            return True
        if _IOS_IF_RE.match(ln):
            return True
        if s == "!":
            return True
    return False


def detect_vendor(text):
    """特異度の高い順（JunOS → IOS）に判定。未知は None（§2.3）。"""
    lines = _nonempty_lines(text)
    ratio = _set_ratio(lines)
    if ratio > 0.5:                                  # JunOS: set 行が過半
        return "juniper_junos"
    if ratio <= 0.4 and _has_ios_features(lines):    # IOS: 40% ガードを通過し特徴行あり
        return "cisco_ios"
    return None
