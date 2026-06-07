"""pytest 起動時にスキルバンドルのルートを sys.path へ追加し、
`from lib...` / `from scripts...` を解決できるようにする。

<bundle>/dev/tests/ から見て ../../ がバンドルルート。
"""
import os
import sys

_SKILL_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _SKILL_ROOT not in sys.path:
    sys.path.insert(0, _SKILL_ROOT)
