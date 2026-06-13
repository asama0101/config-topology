# rebuild/lib/run_summary.py
"""§10.4 実行サマリー（build_topology.py 用）。stderr へ出す行リストを生成する。"""


def build_summary_lines(verdicts, warnings, topo):
    """サマリー行リストを返す（§10.4）。

    verdicts: [(basename, vendor_or_None)] を入力順に。vendor=None はスキップ扱い。
    warnings: パース警告メッセージのリスト。
    topo: build_topology が返す topology dict。
    """
    lines = ["[SUMMARY] 入力ファイル判定:"]
    skipped = 0
    for name, vendor in verdicts:
        if vendor is None:
            skipped += 1
            label = "skipped (unknown vendor)"
        else:
            label = vendor
        lines.append("  - %s: %s" % (name, label))

    lines.append("[SUMMARY] 警告: %d 件" % len(warnings))
    if warnings:
        lines.append("  例: %s" % warnings[0])

    devices = topo.get("devices") or []
    interfaces = topo.get("interfaces") or []
    links = topo.get("links") or []
    segments = topo.get("segments") or []
    lines.append("[SUMMARY] 生成数: devices=%d interfaces=%d links=%d segments=%d"
                 % (len(devices), len(interfaces), len(links), len(segments)))
    routing = topo.get("routing") or {}
    for proto in sorted(routing.keys()):
        lines.append("  routing.%s=%d" % (proto, len(routing.get(proto) or [])))

    if skipped or warnings:
        lines.append("[SUMMARY] 注意: スキップまたは警告があり、結果が不完全な可能性があります。")
    return lines
