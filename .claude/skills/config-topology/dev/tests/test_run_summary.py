# rebuild/dev/tests/test_run_summary.py
"""§10.4 実行サマリー（build_summary_lines）のテスト。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # rebuild/
from lib.run_summary import build_summary_lines  # noqa: E402

pytestmark = pytest.mark.unit


def _topo(n_dev=1, n_if=2, n_link=1, n_seg=0, bgp=0, ospf=0, static=0):
    return {
        "meta": {}, "devices": [{}] * n_dev, "interfaces": [{}] * n_if,
        "links": [{}] * n_link, "segments": [{}] * n_seg,
        "routing": {"bgp": [{}] * bgp, "ospf": [{}] * ospf, "static": [{}] * static},
    }


def test_summary_lists_each_file_verdict():
    verdicts = [("r1.cfg", "cisco_ios"), ("r2.conf", "juniper_junos")]
    lines = build_summary_lines(verdicts, [], _topo())
    text = "\n".join(lines)
    assert "r1.cfg: cisco_ios" in text
    assert "r2.conf: juniper_junos" in text


def test_summary_skipped_label_and_incompleteness_notice():
    verdicts = [("r1.cfg", "cisco_ios"), ("weird.txt", None)]
    lines = build_summary_lines(verdicts, [], _topo())
    text = "\n".join(lines)
    assert "weird.txt: skipped (unknown vendor)" in text
    assert "不完全" in text                     # §10.4 注意喚起


def test_summary_warning_count_and_example():
    lines = build_summary_lines([("r1.cfg", "cisco_ios")],
                                ["bad line 'foo'", "bad line 'bar'"], _topo())
    text = "\n".join(lines)
    assert "警告: 2 件" in text
    assert "bad line 'foo'" in text             # 代表例を併記
    assert "不完全" in text                     # 警告>=1 でも注意喚起


def test_summary_counts_and_no_notice_when_clean():
    lines = build_summary_lines([("r1.cfg", "cisco_ios")], [],
                                _topo(n_dev=2, n_if=5, n_link=3, n_seg=1,
                                      bgp=4, ospf=2, static=1))
    text = "\n".join(lines)
    assert "devices=2" in text and "interfaces=5" in text
    assert "links=3" in text and "segments=1" in text
    assert "routing.bgp=4" in text and "routing.ospf=2" in text and "routing.static=1" in text
    assert "不完全" not in text                 # スキップ0・警告0 なら注意喚起なし
