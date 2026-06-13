"""タブ（ビュー）生成（要件書 §8.2）。図ビューは routing から動的・表ビューは常設・static 除外。"""

_LABELS = {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
           "stats": "STATS", "addr": "ADDRESSES", "ifs": "INTERFACES"}


def build_tabs(routing):
    """[{view, label, key}] を返す。図ビュー（physical→bgp?→ospf?）→ 表ビュー（stats,addr,ifs）。"""
    views = ["physical"]
    if routing.get("bgp"):
        views.append("bgp")
    if routing.get("ospf"):
        views.append("ospf")
    # generic proto（bgp/ospf/static 以外）は v1 ではスキップ（§9.3 拡張余地）
    # stats は routing 有無に関係なく常設
    views += ["stats", "addr", "ifs"]
    return [{"view": v, "label": _LABELS.get(v, v.upper()), "key": i + 1}
            for i, v in enumerate(views)]
