"""タブ（ビュー）生成（要件書 §8.2）。図ビューは routing から動的・表ビューは常設・static 除外。"""

_LABELS = {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
           "addr": "ADDRESSES", "ifs": "INTERFACES"}


def build_tabs(routing):
    """[{view, label, key}] を返す。図ビュー（physical→bgp?→ospf?）→ 表ビュー（addr,ifs）。"""
    views = ["physical"]
    if routing.get("bgp"):
        views.append("bgp")
    if routing.get("ospf"):
        views.append("ospf")
    # generic proto（bgp/ospf/static 以外）は v1 ではスキップ（§9.3 拡張余地）
    views += ["addr", "ifs"]
    return [{"view": v, "label": _LABELS.get(v, v.upper()), "key": i + 1}
            for i, v in enumerate(views)]
