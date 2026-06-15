"""タブ（ビュー）生成（要件書 §8.2）。図ビューは routing から動的（physical→[static]→[bgp]→[ospf]）・常設表ビュー（ADDRESSES/INTERFACES/CHECKS）。CONFIG/DIFF は条件付き表ビュー。STATIC は routing.static 非空時のスタティック経路フォワーディング・シミュレーション図ビュー。"""

_LABELS = {"physical": "PHYSICAL", "static": "STATIC", "bgp": "BGP", "ospf": "OSPF",
           "diff": "DIFF",
           "checks": "CHECKS", "addr": "ADDRESSES", "ifs": "INTERFACES",
           "config": "CONFIG"}


def build_tabs(routing, has_diff=False, has_config=False):
    """[{view, label, key}] を返す。図ビュー（physical→static?→bgp?→ospf?）→ 表ビュー。

    表ビュー順序: ADDRESSES → INTERFACES → [CONFIG] → [DIFF] → CHECKS
      - ADDRESSES / INTERFACES … 常設（先頭）
      - CONFIG … has_config=True（raw_configs 保持時）のみ
      - DIFF   … has_diff=True（--diff-against 指定時）のみ
      - CHECKS … 常設（末尾）

    has_config / has_diff が False（既定）のときは該当タブなし（条件付き）。
    """
    views = ["physical"]
    if routing.get("static"):      # STATIC（スタティック経路の図解析・転送シミュレーション）
        views.append("static")
    if routing.get("bgp"):
        views.append("bgp")
    if routing.get("ospf"):
        views.append("ospf")
    # generic proto（bgp/ospf/static 以外）は v1 ではスキップ（§9.3 拡張余地）
    table_views = ["addr", "ifs"]
    if has_config:                 # CONFIG（生 running-config ワークベンチ）
        table_views.append("config")
    if has_diff:                   # DIFF（--diff-against 指定時のみ）
        table_views.append("diff")
    table_views.append("checks")
    views += table_views
    return [{"view": v, "label": _LABELS.get(v, v.upper()), "key": i + 1}
            for i, v in enumerate(views)]
