"""§8.3 決定的レイアウト（POS）のテスト。"""
import math
import pytest

from lib.rendering.layout import compute_positions, cluster_order

pytestmark = pytest.mark.unit


def _data(dev_ids, seg_ids=(), ext_ids=()):
    return {
        "devices": {d: {} for d in dev_ids},
        "segments": [{"id": s, "members": []} for s in seg_ids],
        "extPeers": [{"id": e} for e in ext_ids],
        "links": [],
    }


def _data_with_as(dev_as_map, seg_ids=(), ext_ids=(), links=(), segments=None):
    """device に AS を付けた topology data を生成するヘルパー。
    dev_as_map: {dev_id: as_number_or_None}
    """
    return {
        "devices": {d: ({"as": asn} if asn is not None else {}) for d, asn in dev_as_map.items()},
        "segments": segments if segments is not None else [{"id": s, "members": []} for s in seg_ids],
        "extPeers": [{"id": e} for e in ext_ids],
        "links": list(links),
        "bgpEdges": [],
    }


def _dist(pos, a, b):
    """2ノード間のユークリッド距離。"""
    return math.hypot(pos[a]["x"] - pos[b]["x"], pos[a]["y"] - pos[b]["y"])


# ---------------------------------------------------------------------------
# AS クラスタリング: no-op ガード（既存挙動の温存）
# ---------------------------------------------------------------------------

class TestAsClusteringNoOp:
    """AS クラスタリングが発動しないケースで、現行 _initial_circle と同じ出力になること。"""

    def test_no_as_info_matches_baseline(self):
        """AS 情報が全くない場合、AS付きと同等の円周配置で既存動作を維持すること。"""
        # Arrange: AS なし（従来の _data ヘルパーと同じ構造）
        baseline = compute_positions(_data(["r1", "r2", "r3"]))
        with_empty_as = compute_positions(_data_with_as({"r1": None, "r2": None, "r3": None}))

        # Assert: AS キーが明示的に None の場合もベースラインと一致
        assert baseline == with_empty_as

    def test_all_singleton_as_equals_no_as(self):
        """2台が別々の AS（各 singleton）の場合、クラスタリング非発動で AS なしと同一 POS。"""
        # Arrange: d1 → AS65001, d2 → AS65002（各 AS が 1 台のみ = singleton）
        no_as = compute_positions(_data(["d1", "d2"]))
        singleton_as = compute_positions(_data_with_as({"d1": 65001, "d2": 65002}))

        # Assert: singleton のみなのでクラスタリング非発動 → 完全一致
        assert no_as == singleton_as

    def test_single_device_with_as_no_op(self):
        """device が 1 台だけの場合はクラスタリング非発動。"""
        pos = compute_positions(_data_with_as({"r1": 65000}))
        assert set(pos.keys()) == {"r1"}

    def test_all_as_none_single_group_not_triggered(self):
        """AS が全て None の場合、クラスタリング非発動。"""
        no_as = compute_positions(_data(["a", "b", "c"]))
        all_none = compute_positions(_data_with_as({"a": None, "b": None, "c": None}))
        assert no_as == all_none


# ---------------------------------------------------------------------------
# AS クラスタリング: 発動ケース
# ---------------------------------------------------------------------------

class TestAsClusteringActive:
    """同一 AS に 2 台以上存在する場合にクラスタリングが発動し近接効果を持つこと。"""

    def _four_dev_two_as_data(self):
        """4 device を 2 AS に 2 台ずつ配置した基本 fixture。
        a1,a2: AS65001 / b1,b2: AS65002
        全ノードにリンクを張って孤立ノードによる発散を防ぐ。
        """
        return _data_with_as(
            {"a1": 65001, "a2": 65001, "b1": 65002, "b2": 65002},
            links=[
                {"a": "a1", "b": "a2"},  # 同 AS 内リンク
                {"a": "b1", "b": "b2"},  # 同 AS 内リンク
                {"a": "a1", "b": "b1"},  # 異 AS 間のリンク（引力を張る）
            ],
        )

    def test_same_as_pair_closer_than_cross_as_pair(self):
        """クラスタリング発動時、同一 AS ペアが異 AS ペアより近くなること（クラスタ近接効果）。

        fixture: a1=AS65001, a2=AS65002, b1=AS65002, b2=AS65001
          sorted 順: [a1, a2, b1, b2]    ← 隣接: a1-a2(異AS), b1-b2(異AS)
          cluster 順: [a1, b2, a2, b1]   ← 隣接: a1-b2(同AS65001), a2-b1(同AS65002)

        links=[] でリンク引力を排除し、初期配置（円周上の隣接関係）の差のみで検証する。
        pure 斥力下では初期配置の隣接関係が概ね保持される。

        stub（cluster_order を sorted に戻す）で検証:
          dist(a1,b2) = dist(a1,a2) → assert False → RED（stub を確実に弾く）
        実装（cluster_order 有効）で検証:
          dist(a1,b2) < dist(a1,a2) → assert True → GREEN
        """
        # Arrange: sorted 順 != cluster 順になる fixture、リンクなし（引力排除）
        data = _data_with_as(
            {"a1": 65001, "a2": 65002, "b1": 65002, "b2": 65001},
            links=[],
        )

        # Act
        pos = compute_positions(data)

        # Assert: cluster 発動時は a1-b2（同 AS65001）が a1-a2（異 AS）より近い
        # sorted 順では両者は等距離（円周上で同じ隣接距離）→ stub は FAIL
        assert _dist(pos, "a1", "b2") < _dist(pos, "a1", "a2"), (
            f"クラスタリング未発動の疑い: "
            f"dist(a1,b2)={_dist(pos, 'a1', 'b2'):.1f} >= dist(a1,a2)={_dist(pos, 'a1', 'a2'):.1f} "
            f"（同 AS65001 の a1-b2 が異 AS の a1-a2 より遠い）"
        )

    def test_deterministic_two_runs_with_as(self):
        """AS 付き input で 2 回呼んで同一 POS（決定性）。"""
        data = self._four_dev_two_as_data()
        assert compute_positions(data) == compute_positions(data)

    def test_deterministic_independent_of_dict_insert_order(self):
        """device dict の挿入順を入れ替えても同一 POS（dict 順序非依存）。"""
        # Arrange: 挿入順 a1,a2,b1,b2
        data_ab = _data_with_as(
            {"a1": 65001, "a2": 65001, "b1": 65002, "b2": 65002},
            links=[
                {"a": "a1", "b": "a2"},
                {"a": "b1", "b": "b2"},
                {"a": "a1", "b": "b1"},
            ],
        )
        # 挿入順 b1,b2,a1,a2（逆）
        data_ba = _data_with_as(
            {"b1": 65002, "b2": 65002, "a1": 65001, "a2": 65001},
            links=[
                {"a": "a1", "b": "a2"},
                {"a": "b1", "b": "b2"},
                {"a": "a1", "b": "b1"},
            ],
        )

        # Act & Assert
        assert compute_positions(data_ab) == compute_positions(data_ba)

    def test_clustering_initial_order_differs_from_sorted_via_cluster_order(self):
        """cluster_order(): 2台以上の同一 AS がある場合に AS グループ順序を返すこと。
        sorted(node_ids) とは異なる順序になるケースで確認する。
        （実装前は cluster_order が存在しないため ImportError → FAIL）
        """
        # sorted では: a1, a2, b1, b2
        # クラスタ順では: AS65001: a1, b2 → AS65002: a2, b1 （AS昇順、同 AS 内 id 昇順）
        devices = {"a1": {"as": 65001}, "a2": {"as": 65002}, "b1": {"as": 65002}, "b2": {"as": 65001}}
        dev_ids = list(devices.keys())
        seg_ids = []
        ext_ids = []

        order = cluster_order(dev_ids, devices, seg_ids, ext_ids)

        # AS65001 グループ: a1, b2（id昇順）
        # AS65002 グループ: a2, b1（id昇順）
        # segments/ext はその後
        assert order == ["a1", "b2", "a2", "b1"]

    def test_cluster_order_numeric_ascending_multi_digit_as(self):
        """cluster_order(): 多桁混在 AS（AS9/AS100/AS65001）がグループ順を数値昇順で返すこと。

        float('inf') sentinel を使う実装では 9 < 100 < 65001 が整数比較で保証されるが、
        None last の実装方式（lambda asn: (asn is None, asn)）でも同様に保証されること。
        """
        # AS9 < AS100 < AS65001 の数値昇順でグループが並ぶことを確認
        devices = {
            "r3": {"as": 65001},
            "r1": {"as": 9},
            "r4": {"as": 65001},
            "r2": {"as": 100},
        }
        order = cluster_order(list(devices.keys()), devices, [], [])
        # AS9: r1, AS100: r2, AS65001: r3,r4 の順
        assert order == ["r1", "r2", "r3", "r4"], (
            f"AS 数値昇順グループ順でない: {order}"
        )

    def test_cluster_order_none_as_at_end(self):
        """cluster_order(): AS=None の device は AS 付きグループの後ろに来ること。"""
        devices = {"a1": {"as": 65001}, "a2": {"as": 65001}, "z1": {}}
        order = cluster_order(list(devices.keys()), devices, [], [])
        # AS65001: a1, a2 → None: z1
        assert order == ["a1", "a2", "z1"]

    def test_cluster_order_with_segments_and_ext(self):
        """cluster_order(): device グループの後に seg(id昇順)・ext(id昇順)が続くこと。"""
        devices = {"r1": {"as": 65001}, "r2": {"as": 65001}}
        seg_ids = ["seg-b", "seg-a"]
        ext_ids = ["ext:z", "ext:a"]
        order = cluster_order(list(devices.keys()), devices, seg_ids, ext_ids)
        assert order == ["r1", "r2", "seg-a", "seg-b", "ext:a", "ext:z"]

    def test_cluster_order_no_op_when_singleton_only(self):
        """cluster_order(): 全 AS が singleton の場合は sorted(node_ids) と同じ順序。"""
        devices = {"r1": {"as": 65001}, "r2": {"as": 65002}}
        order = cluster_order(list(devices.keys()), devices, [], [])
        assert order == sorted(["r1", "r2"])

    def test_cluster_order_no_op_when_no_as(self):
        """cluster_order(): AS 情報なしの場合は sorted(node_ids) と同じ順序。"""
        devices = {"r1": {}, "r2": {}, "r3": {}}
        order = cluster_order(list(devices.keys()), devices, [], [])
        assert order == sorted(["r1", "r2", "r3"])

    def test_clustering_initial_order_differs_from_sorted(self):
        """クラスタリング発動時、初期配置順序が sorted(node_ids) と異なることを特定ペア距離で確認。

        fixture: a1=AS65001, a2=AS65002, b1=AS65002, b2=AS65001
          sorted 順: [a1, a2, b1, b2]    ← a1 と a2 が隣接（index 0,1）
          cluster 順: [a1, b2, a2, b1]   ← a1 と b2 が隣接（index 0,1）

        links=[] でリンク引力を排除し、クラスタリングによる初期配置の差のみを検証する。
        sorted 順とクラスタ順で a1-b2 と a1-a2 の大小関係が逆転する:
          sorted 後: dist(a1,b2) = dist(a1,a2) （どちらも隣接）
          cluster 後: dist(a1,b2) < dist(a1,a2) （a1-b2 が隣接, a1-a2 は対角）

        stub（cluster_order を sorted に戻す）で検証 → dist(a1,b2) = dist(a1,a2) → FAIL
        実装（cluster_order 有効）で検証 → dist(a1,b2) < dist(a1,a2) → PASS
        """
        # Arrange: sorted 順 != cluster 順になる fixture、リンクなし（引力排除）
        #   sorted 順: [a1, a2, b1, b2]
        #   cluster 順: AS65001=[a1,b2], AS65002=[a2,b1] → [a1, b2, a2, b1]
        data = _data_with_as(
            {"a1": 65001, "a2": 65002, "b1": 65002, "b2": 65001},
            links=[],
        )

        # Act
        pos = compute_positions(data)

        # Assert: cluster 発動時は a1-b2（同 AS65001, 隣接 index 0-1）が
        #         a1-a2（異 AS, 対角 index 0-2）より近い
        # stub では dist(a1,b2) == dist(a1,a2) → < が False → FAIL（stub を確実に弾く）
        assert _dist(pos, "a1", "b2") < _dist(pos, "a1", "a2"), (
            f"クラスタリング初期配置が sorted 順と同一の疑い: "
            f"dist(a1,b2)={_dist(pos, 'a1', 'b2'):.1f} >= dist(a1,a2)={_dist(pos, 'a1', 'a2'):.1f} "
            f"（cluster 順では a1-b2 が隣接で dist(a1,a2) より短いはず）"
        )

    def test_bounded_with_as_clustering(self):
        """AS クラスタリング発動時でも座標が妥当範囲内（< 3000）に収まること。"""
        data = self._four_dev_two_as_data()
        pos = compute_positions(data)
        for nid, p in pos.items():
            assert abs(p["x"]) < 3000 and abs(p["y"]) < 3000, (nid, p)

    def test_all_node_ids_present_with_as(self):
        """AS 付き topology でも全ノード ID が POS に含まれること。"""
        data = _data_with_as(
            {"a1": 65001, "a2": 65001, "b1": 65002},
            seg_ids=["seg-x"],
            ext_ids=["ext:y"],
        )
        pos = compute_positions(data)
        assert set(pos.keys()) == {"a1", "a2", "b1", "seg-x", "ext:y"}

    def test_none_as_devices_placed_last_group(self):
        """AS=None の device がある場合もクラスタリング発動で例外なく処理できること。
        （AS 付きが 2 台以上あれば、None device は後続グループに配置）
        全ノードにリンクを張って孤立による発散を防ぐ。
        """
        data = _data_with_as(
            {"a1": 65001, "a2": 65001, "z1": None},
            links=[
                {"a": "a1", "b": "a2"},  # 同 AS 内
                {"a": "a1", "b": "z1"},  # AS=None 接続
                {"a": "a2", "b": "z1"},  # AS=None 接続
            ],
        )
        pos = compute_positions(data)
        assert set(pos.keys()) == {"a1", "a2", "z1"}
        for p in pos.values():
            assert abs(p["x"]) < 3000 and abs(p["y"]) < 3000


# ---------------------------------------------------------------------------
# 後方互換: "as" キーが無い device でも例外なし
# ---------------------------------------------------------------------------

class TestAsKeyBackwardCompat:
    """data["devices"][id] に "as" キーが無くても例外なく動くこと。"""

    def test_device_without_as_key_no_exception(self):
        """"as" キーが存在しない device 辞書でも KeyError なし。"""
        data = {
            "devices": {"r1": {"hostname": "R1"}, "r2": {}},
            "segments": [],
            "extPeers": [],
            "links": [{"a": "r1", "b": "r2"}],
            "bgpEdges": [],
        }
        pos = compute_positions(data)
        assert set(pos.keys()) == {"r1", "r2"}

    def test_mixed_as_key_present_and_absent(self):
        """一部の device に "as" キーがあり、一部にない場合でも動くこと。"""
        data = {
            "devices": {
                "r1": {"as": 65001},
                "r2": {"as": 65001},
                "r3": {"hostname": "R3"},  # "as" キーなし
            },
            "segments": [],
            "extPeers": [],
            "links": [{"a": "r1", "b": "r3"}],
            "bgpEdges": [],
        }
        pos = compute_positions(data)
        assert set(pos.keys()) == {"r1", "r2", "r3"}


def test_all_node_ids_present():
    pos = compute_positions(_data(["r1", "r2", "r3"], seg_ids=["seg-a"], ext_ids=["ext:x"]))
    assert set(pos) == {"r1", "r2", "r3", "seg-a", "ext:x"}
    for p in pos.values():
        assert set(p) == {"x", "y"} and isinstance(p["x"], float) and isinstance(p["y"], float)


def test_deterministic_two_runs():
    d = _data(["r1", "r2", "r3", "r4"], seg_ids=["s1"], ext_ids=["e1"])
    assert compute_positions(d) == compute_positions(d)


def test_coords_rounded_one_decimal():
    pos = compute_positions(_data(["r1", "r2"]))
    for p in pos.values():
        assert round(p["x"], 1) == p["x"] and round(p["y"], 1) == p["y"]


def test_independent_of_dict_input_order():
    a = compute_positions(_data(["r1", "r2", "r3"]))
    b = compute_positions(_data(["r3", "r1", "r2"]))
    assert a == b


def test_empty_data():
    assert compute_positions(_data([])) == {}


def test_segment_and_ext_nodes_stay_bounded():
    # link(d1-d2) + segment(members d1,d2) + extPeer(from d1)
    data = {
        "devices": {"d1": {}, "d2": {}},
        "links": [{"a": "d1", "b": "d2"}],
        "segments": [{"id": "seg-a", "members": [{"dev": "d1"}, {"dev": "d2"}]}],
        "extPeers": [{"id": "ext:203.0.113.7", "from": "d1"}],
        "bgpEdges": [],
    }
    pos = compute_positions(data)
    # 修正前は |座標| ~16000 で発散 → 全ノードが妥当範囲に収まること
    for nid, p in pos.items():
        assert abs(p["x"]) < 3000 and abs(p["y"]) < 3000, (nid, p)

    def dist(a, b):
        return ((pos[a]["x"] - pos[b]["x"]) ** 2 + (pos[a]["y"] - pos[b]["y"]) ** 2) ** 0.5

    # セグメントはいずれかのメンバーデバイス近傍、外部ピアは接続元近傍
    assert min(dist("seg-a", "d1"), dist("seg-a", "d2")) < 2000
    assert dist("ext:203.0.113.7", "d1") < 2000


def test_segment_bbox_does_not_explode_with_many_segments():
    devs = ["d%d" % i for i in range(6)]
    data = {
        "devices": {d: {} for d in devs},
        "links": [{"a": devs[i], "b": devs[i + 1]} for i in range(5)],
        "segments": [
            {"id": "seg-%d" % g,
             "members": [{"dev": devs[g]}, {"dev": devs[g + 1]}, {"dev": devs[(g + 2) % 6]}]}
            for g in range(3)
        ],
        "extPeers": [],
        "bgpEdges": [],
    }
    pos = compute_positions(data)
    xs = [p["x"] for p in pos.values()]
    ys = [p["y"] for p in pos.values()]
    diag = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
    assert diag < 6000, diag      # 発散していない（修正前は数万 px）


def test_ext_peer_anchored_to_all_source_devices():
    # 同一外部ピア ext:E へ d1,d2 の両方から external エッジ
    data = {
        "devices": {"d1": {}, "d2": {}},
        "links": [{"a": "d1", "b": "d2"}],
        "segments": [],
        "extPeers": [{"id": "ext:E"}],
        "bgpEdges": [
            {"id": "be:ext:d1:E", "kind": "external", "a": "d1", "ext": "ext:E"},
            {"id": "be:ext:d2:E", "kind": "external", "a": "d2", "ext": "ext:E"},
        ],
    }
    pos = compute_positions(data)
    def dist(a, b):
        return ((pos[a]["x"]-pos[b]["x"])**2 + (pos[a]["y"]-pos[b]["y"])**2)**0.5
    # ext ノードは d1・d2 の双方から妥当距離内（片側偏りしない）
    assert dist("ext:E", "d1") < 2000
    assert dist("ext:E", "d2") < 2000
    assert abs(dist("ext:E", "d1") - dist("ext:E", "d2")) < 200   # 両接続元の中間に配置
