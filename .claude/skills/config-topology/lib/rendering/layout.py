"""決定的 force-directed レイアウト（要件書 §8.3）。乱数・時刻不使用。"""
import math

NODE_W, NODE_H = 148.0, 56.0
_ITER = 200
_AREA = 1_000_000.0


def _initial_circle_ordered(ordered_ids):
    """指定された順序リストで円周上に決定的初期配置する（AS クラスタリング用）。

    入力リストの index が配置順を決める。半径・角度計算式はこの関数が正本。

    _initial_circle_ordered は private のまま（外部 API は compute_positions のみ）。
    """
    n = max(len(ordered_ids), 1)
    radius = 60.0 * math.sqrt(n) + 120.0
    pos = {}
    for i, nid in enumerate(ordered_ids):
        ang = 2.0 * math.pi * i / n
        pos[nid] = [radius * math.cos(ang), radius * math.sin(ang)]
    return pos


def _initial_circle(node_ids):
    """機器 ID 昇順で円周上に決定的初期配置（§8.3）。

    _initial_circle_ordered(sorted(node_ids)) の薄いラッパー。
    半径・角度式は _initial_circle_ordered に一本化してあるため、
    式を変更する際は _initial_circle_ordered のみ修正すれば良い。
    """
    return _initial_circle_ordered(sorted(node_ids))


def cluster_order(dev_ids, devices, seg_ids, ext_ids):
    """AS クラスタリングを考慮した決定的ノード順序リストを返す。

    発動条件: いずれかの AS グループが 2 台以上の device を含む場合のみクラスタリングを発動。
    非発動時: sorted(dev_ids + seg_ids + ext_ids) と等価な順序。

    発動時の順序:
      1. device: (as_key, id) で安定ソート。as_key は (asn is None, asn) のタプル。
         → None は末尾・非 None は asn 数値昇順・int 同士の比較で決定的。
         同一 AS 内は id 昇順。→ 同一 AS の device が隣接。
      2. segment: id 昇順（device ブロックの後）。
      3. ext: id 昇順（最後）。

    非発動時の順序:
      device(id昇順) + segment(id昇順) + ext(id昇順)
      ← sorted(node_ids) と等価（_initial_circle_ordered が順序そのまま処理）。

    # A1b: area クラスタリングはこの関数を拡張して対応する余地がある。

    Args:
        dev_ids: device ID のリスト。
        devices: data["devices"] の辞書（{id: {..}} 形式）。
        seg_ids: segment ID のリスト。
        ext_ids: ext ID のリスト。

    Returns:
        全ノード ID を決定的順序で並べたリスト。
    """
    # AS グループの構築（.get("as") で安全に読む）
    as_groups: dict = {}
    for did in dev_ids:
        asn = devices.get(did, {}).get("as")
        as_groups.setdefault(asn, []).append(did)

    # 発動ガード: 2台以上の device を含む AS グループが存在するか
    has_cluster = any(
        len(members) >= 2
        for asn, members in as_groups.items()
        if asn is not None
    )

    if not has_cluster:
        # 非発動: sorted(node_ids) と同じ順序を返す
        all_ids = sorted(dev_ids + seg_ids + ext_ids)
        return all_ids

    # 発動: AS グループ順序でソート
    # None を末尾に、非 None を asn 数値昇順に並べる
    # (asn is None, asn) タプル: False < True なので非 None が先、同値は asn 昇順で決定的
    sorted_asns = sorted(as_groups.keys(), key=lambda asn: (asn is None, asn))

    ordered_devs = []
    for asn in sorted_asns:
        # 同一 AS 内は id 昇順
        ordered_devs.extend(sorted(as_groups[asn]))

    return ordered_devs + sorted(seg_ids) + sorted(ext_ids)


def compute_positions(data):
    """全ノード（device + segment + ext）の決定的 POS を返す（座標は round(.,1)）。

    AS クラスタリング初期配置（2台以上の AS グループがある時のみ発動・非該当時は現行円周 no-op・決定的）:
    いずれかの AS グループが 2 台以上の device を含む場合、同一 AS の device が円周上で隣接するよう
    初期配置順序を決定する。それ以外の場合は従来の sorted(node_ids) による円周配置（no-op）。

    引力エッジは物理リンクに加えセグメント↔メンバー・iBGP ループバックからも張る。
    外部ピアは extPeers[].from ではなく external bgpEdges の全接続元から引力を張ることで、
    複数デバイスが同一ピアへ接続する場合も偏らず中間に配置される。
    （孤立ノードが斥力のみで発散するのを防ぐため）
    """
    dev_ids = list(data["devices"].keys())
    seg_ids = [s["id"] for s in data.get("segments", [])]
    ext_ids = [e["id"] for e in data.get("extPeers", [])]
    node_ids = dev_ids + seg_ids + ext_ids
    if not node_ids:
        return {}

    # AS クラスタリング対応初期配置
    # cluster_order() が発動ガードを判定し、適切な順序を返す
    ordered = cluster_order(dev_ids, data["devices"], seg_ids, ext_ids)
    pos = _initial_circle_ordered(ordered)

    k = math.sqrt(_AREA / len(node_ids))

    edges = []
    seen = set()

    def _add_edge(a, b):
        if a in pos and b in pos and a != b:
            key = (a, b) if a <= b else (b, a)
            if key not in seen:
                seen.add(key)
                edges.append((a, b))

    for ln in data.get("links", []):
        _add_edge(ln.get("a"), ln.get("b"))
    for s in data.get("segments", []):
        for m in s.get("members", []):
            _add_edge(s["id"], m.get("dev"))
    # 外部ピアの引力: external bgpEdges の全接続元を優先し、
    # bgpEdges が空の場合は extPeers[].from にフォールバック（後方互換）。
    # 複数デバイスが同一ピアへ接続する場合も全方向に引力を張る。
    ext_anchored = set()
    for be in data.get("bgpEdges", []):
        if be.get("kind") == "external":
            _add_edge(be.get("a"), be.get("ext"))
            ext_anchored.add(be.get("ext"))
        elif be.get("kind") == "loopback":
            _add_edge(be.get("a"), be.get("b"))
    for e in data.get("extPeers", []):
        if e["id"] not in ext_anchored:
            _add_edge(e["id"], e.get("from"))

    ids_sorted = sorted(node_ids)
    for it in range(_ITER):
        disp = {nid: [0.0, 0.0] for nid in ids_sorted}
        for i in range(len(ids_sorted)):
            for j in range(i + 1, len(ids_sorted)):
                a, b = ids_sorted[i], ids_sorted[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                dist = math.hypot(dx, dy) or 0.01
                rep = k * k / dist
                ux, uy = dx / dist, dy / dist
                disp[a][0] += ux * rep; disp[a][1] += uy * rep
                disp[b][0] -= ux * rep; disp[b][1] -= uy * rep
        for a, b in edges:
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            dist = math.hypot(dx, dy) or 0.01
            att = dist * dist / k
            ux, uy = dx / dist, dy / dist
            disp[a][0] -= ux * att; disp[a][1] -= uy * att
            disp[b][0] += ux * att; disp[b][1] += uy * att
        temp = k * (1.0 - it / _ITER)
        for nid in ids_sorted:
            d = disp[nid]
            dl = math.hypot(d[0], d[1]) or 0.01
            step = min(dl, temp)
            pos[nid][0] += d[0] / dl * step
            pos[nid][1] += d[1] / dl * step

    return {nid: {"x": round(p[0], 1), "y": round(p[1], 1)} for nid, p in pos.items()}
