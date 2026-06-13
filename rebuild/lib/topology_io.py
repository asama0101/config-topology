"""topology dict ⇄ 層別 YAML（要件書 §3.2 書出 / §5.6 読込・参照整合）。"""
import os

import yaml


def _dump_file(out_dir, name, data):
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True, default_flow_style=False,
                       allow_unicode=True)


def dump_topology(topo, out_dir):
    """topology dict を層別 YAML として out_dir に書き出す（§3.2）。

    _meta / devices / physical は常時生成。routing.* は非空のときのみ。
    """
    os.makedirs(out_dir, exist_ok=True)
    _dump_file(out_dir, "_meta.yaml", topo["meta"])
    _dump_file(out_dir, "devices.yaml",
               {"devices": topo["devices"], "interfaces": topo["interfaces"]})
    _dump_file(out_dir, "physical.yaml",
               {"links": topo["links"], "segments": topo["segments"]})
    routing = topo.get("routing", {})
    for proto in ("bgp", "ospf", "static"):
        entries = routing.get(proto) or []
        if entries:
            _dump_file(out_dir, "routing.%s.yaml" % proto, {proto: entries})
