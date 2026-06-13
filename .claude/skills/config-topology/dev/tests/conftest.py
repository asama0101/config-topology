import sys
from pathlib import Path

import pytest

# rebuild/ をインポートパスに追加（rebuild/lib を import 可能にする）
REBUILD_ROOT = Path(__file__).resolve().parents[2]
if str(REBUILD_ROOT) not in sys.path:
    sys.path.insert(0, str(REBUILD_ROOT))

CONFIG_DIR = REBUILD_ROOT / "dev" / "examples" / "configs"


@pytest.fixture
def ios_cfg_text():
    return (CONFIG_DIR / "sample-ios-r1.cfg").read_text(encoding="utf-8")


@pytest.fixture
def junos_cfg_text():
    return (CONFIG_DIR / "sample-junos-r2.conf").read_text(encoding="utf-8")
