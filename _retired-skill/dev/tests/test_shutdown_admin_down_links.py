"""
TDD テスト: shutdown IF が張る admin_down リンク機能

仕様:
  shutdown=True の IF が対向（同一サブネットの別機器 IF）と結ぶはずだったリンクを、
  図から消さずグレー破線で残す。ただし対向が無いスタブ（リンク不成立）は図に何も出さない。

観点:
  1. build: 両端 up     → admin_down なし（非回帰）
  2. build: 片側 shutdown → admin_down=True
  3. build: 両側 shutdown → admin_down=True
  4. build: shutdown スタブ → link 出ない
  5. build: shutdown かつ IP 無し → link 出ない
  6. build: 3メンバー+1shutdown → segment（members 全員、admin_down 概念なし）
  7. svg: admin_down link に link-down クラスが付く
  8. svg: admin_down link の端点チップに if-chip-shutdown が付く
  9. topology_io: admin_down 付き links が round-trip で保存される
  10. topology_io: admin_down 付き links が _validate_references を通過する
  11. assets: _CSS に .link-down セレクタが含まれる
  12. build: 両端 up の link に admin_down フィールドが付かない（非回帰）
  13. build: admin_down リンクに ospf_area が付かない（OSPF ガード）
"""

from __future__ import annotations

import os
import sys

import pytest

from lib.parsers.base import Device, Interface, OspfNetwork


# ================================================================
# ヘルパー
# ================================================================

def make_device(
    hostname: str,
    vendor: str = "cisco_ios",
    interfaces: list[Interface] | None = None,
    ospf: list[OspfNetwork] | None = None,
) -> Device:
    return Device(
        hostname=hostname,
        vendor=vendor,
        asn=None,
        interfaces=interfaces or [],
        bgp=[],
        ospf=ospf or [],
        static=[],
    )


def make_iface(
    name: str,
    ip: str | None = None,
    shutdown: bool = False,
) -> Interface:
    return Interface(name=name, ip=ip, description=None, shutdown=shutdown)


def _build(devices):
    """build() を呼び出して topology dict を返す。"""
    from scripts.build_topology import build
    return build(devices, generated_from=[])


# ================================================================
# 1. build: 両端 up → admin_down なし（非回帰）
# ================================================================

@pytest.mark.unit
def test_both_up_no_admin_down():
    """両端 up のリンクには admin_down フィールドが付かない（既存動作の非回帰）。"""
    # Arrange
    d1 = make_device("R1", interfaces=[make_iface("eth0", ip="10.0.0.1/30")])
    d2 = make_device("R2", interfaces=[make_iface("eth0", ip="10.0.0.2/30")])

    # Act
    result = _build([d1, d2])

    # Assert
    assert len(result["links"]) == 1
    link = result["links"][0]
    assert "admin_down" not in link, "両端 up のリンクに admin_down フィールドが付いてはいけない"


# ================================================================
# 2. build: 片側 shutdown → admin_down=True
# ================================================================

@pytest.mark.unit
def test_one_side_shutdown_creates_admin_down_link():
    """片側 shutdown の IF が対向 up IF と同一サブネット → admin_down=True のリンクが生成される。"""
    # Arrange
    d1 = make_device("R1", interfaces=[make_iface("eth0", ip="10.0.0.1/30", shutdown=True)])
    d2 = make_device("R2", interfaces=[make_iface("eth0", ip="10.0.0.2/30", shutdown=False)])

    # Act
    result = _build([d1, d2])

    # Assert
    assert len(result["links"]) == 1, "shutdown 側でもリンクが生成されなければならない"
    link = result["links"][0]
    assert link.get("admin_down") is True
    assert link["kind"] == "inferred-subnet"


# ================================================================
# 3. build: 両側 shutdown → admin_down=True
# ================================================================

@pytest.mark.unit
def test_both_shutdown_creates_admin_down_link():
    """両端 shutdown の IF が同一サブネット → admin_down=True のリンクが生成される。"""
    # Arrange
    d1 = make_device("R1", interfaces=[make_iface("eth0", ip="10.0.0.1/30", shutdown=True)])
    d2 = make_device("R2", interfaces=[make_iface("eth0", ip="10.0.0.2/30", shutdown=True)])

    # Act
    result = _build([d1, d2])

    # Assert
    assert len(result["links"]) == 1
    link = result["links"][0]
    assert link.get("admin_down") is True


# ================================================================
# 4. build: shutdown スタブ → link 出ない
# ================================================================

@pytest.mark.unit
def test_shutdown_stub_no_link():
    """shutdown=True かつ対向なし（スタブ）の IF はリンクを生成しない。"""
    # Arrange
    d1 = make_device("R1", interfaces=[make_iface("eth0", ip="10.0.0.1/30", shutdown=True)])

    # Act
    result = _build([d1])

    # Assert
    assert result["links"] == []
    assert result["segments"] == []


# ================================================================
# 5. build: shutdown かつ IP 無し → link 出ない
# ================================================================

@pytest.mark.unit
def test_shutdown_no_ip_no_link():
    """shutdown=True かつ IP なしの IF はリンクを生成しない。"""
    # Arrange
    d1 = make_device("R1", interfaces=[make_iface("eth0", ip=None, shutdown=True)])
    d2 = make_device("R2", interfaces=[make_iface("eth0", ip=None, shutdown=True)])

    # Act
    result = _build([d1, d2])

    # Assert
    assert result["links"] == []


# ================================================================
# 6. build: 3メンバー + 1 shutdown → segment（members 全員）
# ================================================================

@pytest.mark.unit
def test_segment_with_one_shutdown_member_includes_all():
    """segment では shutdown メンバーも members に含まれる。admin_down フィールドは付かない。"""
    # Arrange
    d1 = make_device("SW1", interfaces=[make_iface("eth0", ip="192.168.1.1/24", shutdown=False)])
    d2 = make_device("SW2", interfaces=[make_iface("eth0", ip="192.168.1.2/24", shutdown=False)])
    d3 = make_device("SW3", interfaces=[make_iface("eth0", ip="192.168.1.3/24", shutdown=True)])

    # Act
    result = _build([d1, d2, d3])

    # Assert
    assert len(result["segments"]) == 1, "3メンバーはセグメントになる"
    assert result["links"] == []
    seg = result["segments"][0]
    assert "sw1::eth0" in seg["members"]
    assert "sw2::eth0" in seg["members"]
    assert "sw3::eth0" in seg["members"]
    assert "admin_down" not in seg, "segment には admin_down フィールドを付けない"


# ================================================================
# 7 & 8. svg: admin_down link の <g> に link-down クラスが付く
#             かつ端点チップに if-chip-shutdown が付く
# ================================================================

@pytest.fixture
def admin_down_topology():
    """admin_down=True のリンクを含む最小 topology dict。"""
    return {
        "title": "Test",
        "generated_from": [],
        "devices": [
            {"id": "r1", "hostname": "R1", "vendor": "cisco_ios"},
            {"id": "r2", "hostname": "R2", "vendor": "cisco_ios"},
        ],
        "interfaces": [
            {
                "id": "r1::eth0",
                "device": "r1",
                "name": "eth0",
                "ip": "10.0.0.1/30",
                "shutdown": True,
            },
            {
                "id": "r2::eth0",
                "device": "r2",
                "name": "eth0",
                "ip": "10.0.0.2/30",
                "shutdown": False,
            },
        ],
        "links": [
            {
                "a_device": "r1",
                "a_if": "eth0",
                "b_device": "r2",
                "b_if": "eth0",
                "subnet": "10.0.0.0/30",
                "kind": "inferred-subnet",
                "admin_down": True,
            }
        ],
        "segments": [],
        "routing": {"bgp": [], "ospf": [], "static": []},
    }


@pytest.mark.unit
def test_svg_admin_down_link_has_link_down_class(admin_down_topology):
    """admin_down=True のリンク <g> に 'link-down' クラスが付与される。"""
    # Arrange
    from lib.rendering import render

    # Act
    html = render(admin_down_topology)

    # Assert
    assert "link-down" in html, "admin_down リンクに link-down クラスが付いていない"


@pytest.mark.unit
def test_svg_admin_down_link_edge_class_format(admin_down_topology):
    """admin_down=True のリンク <g> のクラスが 'link-edge link-down' を含む。"""
    # Arrange
    from lib.rendering import render

    # Act
    html = render(admin_down_topology)

    # Assert: link-edge link-down という組み合わせが存在する
    assert 'class="link-edge link-down"' in html or "link-edge link-down" in html, (
        "admin_down リンクの <g> クラスに 'link-edge link-down' が含まれていない"
    )


@pytest.mark.unit
def test_svg_admin_down_endpoint_chip_has_shutdown_class(admin_down_topology):
    """admin_down リンクの shutdown 端点チップに if-chip-shutdown クラスが付与される。"""
    # Arrange
    from lib.rendering import render

    # Act
    html = render(admin_down_topology)

    # Assert
    assert "if-chip-shutdown" in html, (
        "shutdown=True のチップに if-chip-shutdown クラスが付いていない"
    )


# ================================================================
# 9. topology_io: admin_down 付き links が round-trip で保存される
# ================================================================

@pytest.mark.unit
def test_topology_io_admin_down_roundtrip(tmp_path, admin_down_topology):
    """admin_down=True のリンクが dump → load で保存・復元される。"""
    # Arrange
    from lib.topology_io import dump_topology, load_topology
    out_dir = str(tmp_path / "topo")

    # Act
    dump_topology(admin_down_topology, out_dir)
    loaded = load_topology(out_dir)

    # Assert
    assert len(loaded["links"]) == 1
    link = loaded["links"][0]
    assert link.get("admin_down") is True, "admin_down が round-trip で保存されていない"


# ================================================================
# 10. topology_io: admin_down 付き links が参照整合検証を通過する
# ================================================================

@pytest.mark.unit
def test_topology_io_admin_down_validates_ok(tmp_path, admin_down_topology):
    """admin_down=True のリンクを含む topology が load_topology の参照整合検証を通過する。"""
    # Arrange
    from lib.topology_io import dump_topology, load_topology
    out_dir = str(tmp_path / "validate_check")

    # Act & Assert: ValueError が発生しないこと
    dump_topology(admin_down_topology, out_dir)
    loaded = load_topology(out_dir)  # ここで ValueError が出なければ OK
    assert loaded is not None


# ================================================================
# 11. assets: _CSS に .link-down セレクタが含まれる
# ================================================================

@pytest.mark.unit
def test_css_contains_link_down_selector():
    """_CSS に .link-edge.link-down .link-line セレクタが含まれる。"""
    # Arrange
    from lib.rendering.assets import _CSS

    # Assert
    assert ".link-down" in _CSS, "_CSS に .link-down セレクタが含まれていない"


@pytest.mark.unit
def test_css_link_down_has_dasharray():
    """_CSS の link-down スタイルに stroke-dasharray が定義されている。"""
    # Arrange
    from lib.rendering.assets import _CSS

    # Assert
    assert "stroke-dasharray" in _CSS


# ================================================================
# 12. build: admin_down リンクの基本フィールドが正しい（非回帰チェック）
# ================================================================

@pytest.mark.unit
def test_admin_down_link_has_correct_fields():
    """admin_down=True のリンクに標準フィールド（a_device/b_device/subnet/kind）が揃っている。"""
    # Arrange
    d1 = make_device("A", interfaces=[make_iface("eth0", ip="10.0.0.1/30", shutdown=True)])
    d2 = make_device("B", interfaces=[make_iface("eth0", ip="10.0.0.2/30", shutdown=False)])

    # Act
    result = _build([d1, d2])

    # Assert
    assert len(result["links"]) == 1
    link = result["links"][0]
    assert "a_device" in link
    assert "b_device" in link
    assert "a_if" in link
    assert "b_if" in link
    assert "subnet" in link
    assert link["kind"] == "inferred-subnet"
    assert link["admin_down"] is True


# ================================================================
# 13. build: admin_down リンクには ospf_area が付かない（OSPF ガード）
# ================================================================

@pytest.mark.unit
def test_admin_down_link_no_ospf_area():
    """shutdown IF を持つ admin_down リンクには ospf_area が付与されない。"""
    # Arrange: OSPF エリア 0 に参加している機器で、片側の IF が shutdown
    ospf_entry = OspfNetwork(process=1, area="0", network="10.0.0.0/30")
    d1 = make_device(
        "R1",
        interfaces=[make_iface("eth0", ip="10.0.0.1/30", shutdown=True)],
        ospf=[ospf_entry],
    )
    d2 = make_device(
        "R2",
        interfaces=[make_iface("eth0", ip="10.0.0.2/30", shutdown=False)],
        ospf=[ospf_entry],
    )

    # Act
    result = _build([d1, d2])

    # Assert
    assert len(result["links"]) == 1
    link = result["links"][0]
    assert link.get("admin_down") is True
    assert "ospf_area" not in link, "admin_down リンクに ospf_area が付いてはいけない"


# ================================================================
# 14. build: a < b のソート安定性（admin_down でも維持される）
# ================================================================

@pytest.mark.unit
def test_admin_down_link_stable_sort():
    """admin_down リンクでも a_device < b_device の安定化が維持される。"""
    # Arrange: Z1 > A1 の順に device を作り、a < b に安定化されるか確認
    d1 = make_device("Z1", interfaces=[make_iface("eth0", ip="10.0.0.1/30", shutdown=True)])
    d2 = make_device("A1", interfaces=[make_iface("eth0", ip="10.0.0.2/30", shutdown=False)])

    # Act
    result = _build([d1, d2])

    # Assert
    link = result["links"][0]
    assert link["a_device"] <= link["b_device"], "a_device <= b_device が保証されていない"
