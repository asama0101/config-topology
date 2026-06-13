"""topology dict ⇄ 層別 YAML（要件書 §3.2 書出 / §5.6 読込・参照整合）。"""
import os

import yaml


def _dump_file(out_dir, name, data):
    path = os.path.join(out_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=True, default_flow_style=False,
                       allow_unicode=True, indent=2)


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


def _load_file(in_dir, name):
    with open(os.path.join(in_dir, name), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topology(in_dir):
    """層別 YAML を読み込み topology dict を返す。参照整合違反は ValueError（§5.6）。"""
    meta = _load_file(in_dir, "_meta.yaml")
    devs = _load_file(in_dir, "devices.yaml")
    phys = _load_file(in_dir, "physical.yaml")
    routing = {}
    for proto in ("bgp", "ospf", "static"):
        try:
            data = _load_file(in_dir, "routing.%s.yaml" % proto)
        except FileNotFoundError:
            routing[proto] = []
            continue
        routing[proto] = (data or {}).get(proto) or []
    devs = devs or {}
    phys = phys or {}
    topo = {
        "meta": meta or {},
        "devices": devs.get("devices") or [],
        "interfaces": devs.get("interfaces") or [],
        "links": phys.get("links") or [],
        "segments": phys.get("segments") or [],
        "routing": routing,
    }
    _validate_refs(topo)
    return topo


def _validate_refs(topo):
    """device/interface ID の dangling 参照を検証（§5.6）。違反はファイル名・フィールド・値付き ValueError。"""
    dev_ids = {d["id"] for d in topo["devices"]}
    if_names_by_dev = {}
    if_ids = set()
    for itf in topo["interfaces"]:
        if itf["device"] not in dev_ids:
            raise ValueError(
                "devices.yaml: interfaces[].device '%s' (interface id=%s) は未知の device を参照"
                % (itf["device"], itf["id"]))
        if_names_by_dev.setdefault(itf["device"], set()).add(itf["name"])
        if_ids.add(itf["id"])
    for ln in topo["links"]:
        for side in ("a", "b"):
            dev = ln["%s_device" % side]
            ifn = ln["%s_if" % side]
            if dev not in dev_ids:
                raise ValueError(
                    "physical.yaml: links[].%s_device '%s' は未知の device を参照" % (side, dev))
            if ifn not in if_names_by_dev.get(dev, set()):
                raise ValueError(
                    "physical.yaml: links[].%s_if '%s' は device '%s' に存在しない" % (side, ifn, dev))
    for seg in topo["segments"]:
        for m in seg["members"]:
            if m not in if_ids:
                raise ValueError(
                    "physical.yaml: segments[].members '%s' (segment %s) は未知の interface を参照"
                    % (m, seg["id"]))
    for proto, entries in topo["routing"].items():
        for e in entries:
            if e["device"] not in dev_ids:
                raise ValueError(
                    "routing.%s.yaml: %s[].device '%s' は未知の device を参照" % (proto, proto, e["device"]))
