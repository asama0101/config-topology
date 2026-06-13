"""決定的 force-directed レイアウト（要件書 §8.3）。乱数・時刻不使用。"""
import math

NODE_W, NODE_H = 148.0, 56.0
_ITER = 200
_AREA = 1_000_000.0


def _initial_circle(node_ids):
    """機器 ID 昇順で円周上に決定的初期配置（§8.3）。"""
    n = max(len(node_ids), 1)
    radius = 60.0 * math.sqrt(n) + 120.0
    pos = {}
    for i, nid in enumerate(sorted(node_ids)):
        ang = 2.0 * math.pi * i / n
        pos[nid] = [radius * math.cos(ang), radius * math.sin(ang)]
    return pos


def compute_positions(data):
    """全ノード（device + segment + ext）の決定的 POS を返す（座標は round(.,1)）。"""
    dev_ids = list(data["devices"].keys())
    seg_ids = [s["id"] for s in data.get("segments", [])]
    ext_ids = [e["id"] for e in data.get("extPeers", [])]
    node_ids = dev_ids + seg_ids + ext_ids
    if not node_ids:
        return {}

    pos = _initial_circle(node_ids)
    k = math.sqrt(_AREA / len(node_ids))

    edges = []
    seen = set()

    def _add(a, b):
        if a in pos and b in pos and a != b:
            key = (a, b) if a <= b else (b, a)
            if key not in seen:
                seen.add(key)
                edges.append((a, b))

    for ln in data.get("links", []):
        _add(ln.get("a"), ln.get("b"))
    for s in data.get("segments", []):
        for m in s.get("members", []):
            _add(s["id"], m.get("dev"))
    for e in data.get("extPeers", []):
        _add(e["id"], e.get("from"))
    for be in data.get("bgpEdges", []):
        if be.get("kind") == "loopback":
            _add(be.get("a"), be.get("b"))

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
