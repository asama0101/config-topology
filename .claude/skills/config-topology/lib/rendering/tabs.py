"""タブ（ビュー）生成（要件書 §8.2）。図ビューは routing から動的・常設表ビュー（STATS/CHECKS/ADDRESSES/INTERFACES）・static 除外。DIFF は has_diff=True 時のみの条件付き表ビュー。"""

_LABELS = {"physical": "PHYSICAL", "bgp": "BGP", "ospf": "OSPF",
           "diff": "DIFF",
           "stats": "STATS", "checks": "CHECKS", "addr": "ADDRESSES", "ifs": "INTERFACES"}


def build_tabs(routing, has_diff=False):
    """[{view, label, key}] を返す。図ビュー（physical→bgp?→ospf?）→ 表ビュー（diff?,stats,checks,addr,ifs）。

    has_diff=True のとき DIFF タブを表ビュー群の先頭（stats の前）に追加する。
    has_diff=False（既定）のときは DIFF タブなし（既存挙動を維持）。
    """
    views = ["physical"]
    if routing.get("bgp"):
        views.append("bgp")
    if routing.get("ospf"):
        views.append("ospf")
    # generic proto（bgp/ospf/static 以外）は v1 ではスキップ（§9.3 拡張余地）
    # diff は --diff-against 指定時のみ（stats の前に配置）
    table_views = []
    if has_diff:
        table_views.append("diff")
    table_views += ["stats", "checks", "addr", "ifs"]
    views += table_views
    return [{"view": v, "label": _LABELS.get(v, v.upper()), "key": i + 1}
            for i, v in enumerate(views)]
