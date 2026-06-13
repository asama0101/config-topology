"""
パーサ registry

parse_text(text) -> Device | None

detect の特異度が高い順にパーサを試行する。
どのパーサも detect しない場合は None を返す（クラッシュしない設計）。
"""

from __future__ import annotations

from .base import Device
from . import cisco_ios, juniper_junos

# 特異度の高い順に並べる
# JunOS は "行の過半が set " という非常に特異な特徴を持つため先に試す
_PARSERS = [
    juniper_junos,
    cisco_ios,
]


def parse_text(text: str) -> Device | None:
    """
    テキストのベンダーを自動判別して Device を返す。

    未知ベンダー時は None を返す（ValueError を上げない）。
    これにより parse_configs.py が None をスキップできる。
    """
    for parser in _PARSERS:
        if parser.detect(text):
            return parser.parse(text)
    return None
