"""
TDD テスト: OSPF process=None のときのカード HTML 表示バグ修正

バグ: JunOS は OSPF process ID 概念が無いため routing.ospf.yaml で process: null
     になるが、o.get('process', '') は None を返す（キーが存在するため default の ''
     は使われない）。結果 HTML に "PID None" と表示される。

期待: process が None または '' のときは "PID —"（em ダッシュ）を表示する。
     process に値があるときは "PID 1" のように表示する。

テスト方針:
  - _device_cards() を直接呼び出してユニットテスト
  - 既存テストの様式（AAAパターン, pytest.mark.unit）に倣う
  - conftest.py が sys.path を設定済みのため lib インポートは直接使用可能
"""

from __future__ import annotations

import pytest


# ================================================================
# ヘルパー: 最小 topology オブジェクトのファクトリ
# ================================================================

def _make_topology_with_ospf(process) -> tuple[list, list, dict]:
    """OSPF エントリを1件持つ最小 topology を返す。

    Args:
        process: routing.ospf[].process に設定する値（None / '' / 1 等）

    Returns:
        (devices, interfaces, routing) のタプル — _device_cards() の引数用
    """
    devices = [
        {
            "id": "dev1",
            "hostname": "R1",
            "vendor": "juniper",
            "as": None,
            "sections": [],
        }
    ]
    interfaces = []
    routing = {
        "bgp": [],
        "ospf": [
            {
                "device": "dev1",
                "network": "10.0.0.0/24",
                "area": "0",
                "process": process,  # テスト対象: None / '' / 整数など
            }
        ],
        "static": [],
    }
    return devices, interfaces, routing


# ================================================================
# ユニットテスト: OSPF process=None のとき "PID —" が表示される
# ================================================================

class TestOspfProcessNoneDisplay:
    """OSPF route の process が None のとき表示バグが発生しないことを保証する。"""

    @pytest.mark.unit
    def test_ospf_process_none_shows_em_dash(self):
        """process=None のとき HTML に 'PID —' が含まれ 'PID None' が含まれない。

        JunOS は OSPF process ID が無いため routing.ospf[].process が
        yaml.safe_load で null（= Python None）になる。
        このとき _device_cards() が 'PID None' を出力するバグを検証する。
        """
        # Arrange
        from lib.rendering.cards import _device_cards
        devices, interfaces, routing = _make_topology_with_ospf(process=None)

        # Act
        html = _device_cards(devices, interfaces, routing)

        # Assert: "PID None" が含まれていてはいけない
        assert "PID None" not in html, (
            "process=None のとき HTML に 'PID None' が出力された。"
            " o.get('process', '') が None を返すバグが修正されていない。"
        )
        # Assert: "PID —" が含まれている（em ダッシュ表示）
        assert "PID —" in html, (
            "process=None のとき HTML に 'PID —' が含まれるべきだが見つからない。"
        )

    @pytest.mark.unit
    def test_ospf_process_none_no_trailing_space(self):
        """process=None のとき HTML に 'PID '（末尾空白のみ）が含まれない。

        仮に None → '' への変換が部分的に機能した場合でも、
        'PID '（PID + 半角スペース）という中途半端な表示にならないことを確認する。
        """
        # Arrange
        from lib.rendering.cards import _device_cards
        devices, interfaces, routing = _make_topology_with_ospf(process=None)

        # Act
        html = _device_cards(devices, interfaces, routing)

        # Assert: "PID " の直後が ">" で終わる（= 空の PID セル）パターンが含まれない
        # <td>PID </td> という空文字ケースを検出する
        assert "<td>PID </td>" not in html, (
            "process=None のとき '<td>PID </td>' という空 PID セルが出力された。"
        )

    @pytest.mark.unit
    def test_ospf_process_empty_string_shows_em_dash(self):
        """process='' (空文字) のときも HTML に 'PID —' が含まれる。

        空文字は「値なし」として em ダッシュで表示すべき。
        """
        # Arrange
        from lib.rendering.cards import _device_cards
        devices, interfaces, routing = _make_topology_with_ospf(process="")

        # Act
        html = _device_cards(devices, interfaces, routing)

        # Assert
        assert "PID —" in html, (
            "process='' のとき HTML に 'PID —' が含まれるべきだが見つからない。"
        )
        assert "<td>PID </td>" not in html, (
            "process='' のとき '<td>PID </td>' という空 PID セルが出力された。"
        )


# ================================================================
# 回帰テスト: process に値があるときは "PID 1" のように表示される
# ================================================================

class TestOspfProcessWithValueDisplay:
    """OSPF route の process に値があるとき、正しく 'PID <値>' が表示される（回帰確認）。"""

    @pytest.mark.unit
    def test_ospf_process_int_shows_pid_value(self):
        """process=1 のとき HTML に 'PID 1' が含まれる。"""
        # Arrange
        from lib.rendering.cards import _device_cards
        devices, interfaces, routing = _make_topology_with_ospf(process=1)

        # Act
        html = _device_cards(devices, interfaces, routing)

        # Assert
        assert "PID 1" in html, (
            "process=1 のとき HTML に 'PID 1' が含まれるべきだが見つからない。"
        )
        # em ダッシュが出てはいけない
        assert "PID —" not in html, (
            "process=1 のとき 'PID —' が誤って出力された。"
        )

    @pytest.mark.unit
    def test_ospf_process_string_shows_pid_value(self):
        """process='100' のとき HTML に 'PID 100' が含まれる。"""
        # Arrange
        from lib.rendering.cards import _device_cards
        devices, interfaces, routing = _make_topology_with_ospf(process="100")

        # Act
        html = _device_cards(devices, interfaces, routing)

        # Assert
        assert "PID 100" in html, (
            "process='100' のとき HTML に 'PID 100' が含まれるべきだが見つからない。"
        )
        assert "PID —" not in html, (
            "process='100' のとき 'PID —' が誤って出力された。"
        )

    @pytest.mark.unit
    def test_ospf_process_none_does_not_affect_area_display(self):
        """process=None のとき Area 表示（Area 0）は影響を受けない。"""
        # Arrange
        from lib.rendering.cards import _device_cards
        devices, interfaces, routing = _make_topology_with_ospf(process=None)

        # Act
        html = _device_cards(devices, interfaces, routing)

        # Assert: Area セルは正常に表示される
        assert "Area 0" in html, (
            "process=None の修正が Area 表示を壊した可能性がある。"
        )

    @pytest.mark.unit
    def test_ospf_process_esc_applied(self):
        """process に XSS 文字列を含む場合、_esc によりエスケープされる。"""
        # Arrange
        from lib.rendering.cards import _device_cards
        devices, interfaces, routing = _make_topology_with_ospf(process="<evil>")

        # Act
        html = _device_cards(devices, interfaces, routing)

        # Assert: 生の <evil> タグは現れない
        assert "<evil>" not in html, (
            "process に含まれる XSS 文字列がエスケープされずに出力された。"
        )
        # エスケープ済み表現が存在する
        assert "&lt;evil&gt;" in html, (
            "process の XSS 文字列 <evil> が &lt;evil&gt; にエスケープされていない。"
        )
