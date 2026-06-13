"""
rendering/template.py — HTML テンプレート（静的 CSS/JS 定数 + build_html）
"""
from __future__ import annotations

from lib.rendering.svg import _esc

# ---------------------------------------------------------------------------
# 静的 CSS/JS 定数（assets.py から再 export）
# ---------------------------------------------------------------------------
from lib.rendering.assets import _CSS, _JS  # noqa: F401


def _node_filter_ui(devices: list[dict]) -> str:
    """ノード表示フィルタ チェックリスト UI を生成して返す。

    デバイスを hostname 昇順にソートし、各チェックボックスは ``data-node-filter="{device_id}"``
    でデフォルト checked。「全選択」「全解除」ボタンも生成する。
    デバイスが0件の場合は空文字列を返す。

    Args:
        devices: topology の devices リスト（各要素は id/hostname を持つ）
    """
    if not devices:
        return ""

    sorted_devs = sorted(devices, key=lambda d: d.get("hostname", d["id"]))

    checkboxes = []
    for dev in sorted_devs:
        dev_id = _esc(dev["id"])
        hostname = _esc(dev.get("hostname", dev["id"]))
        checkboxes.append(
            f'<label class="node-filter-label">'
            f'<input type="checkbox" class="node-filter-cb" '
            f'data-node-filter="{dev_id}" checked> {hostname}'
            f'</label>'
        )

    checkboxes_html = "\n    ".join(checkboxes)
    return (
        f'<div class="node-filter-panel">'
        f'<span class="controls-label">Nodes:</span>\n    '
        f'{checkboxes_html}\n    '
        f'<button class="node-filter-btn" onclick="selectAllNodes()">全選択</button>'
        f'<button class="node-filter-btn" onclick="clearAllNodes()">全解除</button>'
        f'</div>'
    )


def _layer_toggles(active_keys: list[str]) -> str:
    """レイヤートグルチェックボックスを生成して返す。

    Args:
        active_keys: データが1件以上ある routing キーの昇順リスト（呼び出し側で計算済み）。
                     physical トグルは常に先頭に生成する。
    """
    layers = [("physical", "Physical", True)]
    for key in active_keys:
        layers.append((key, key.upper(), True))

    toggles = []
    for layer_id, label, checked in layers:
        checked_attr = "checked" if checked else ""
        toggles.append(
            f'<label class="layer-toggle">'
            f'<input type="checkbox" id="toggle-{_esc(layer_id)}" '
            f'data-layer="{_esc(layer_id)}" {checked_attr} '
            f'onchange="handleLayerToggle(this)"> {_esc(label)}'
            f'</label>'
        )
    return "\n".join(toggles)


def build_html(
    *,
    title: str,
    layer_hide_css: str,
    tabs_html: str,
    toggles_html: str,
    node_filter_html: str,
    svg_height: int,
    vb_min_x: float,
    vb_min_y: float,
    svg_width: int,
    all_views_svg: str,
    cards_html: str,
    topology_json_safe: str,
    legend_panel_inner: str = "",
) -> str:
    """HTML シェルを組み立てて返す。

    Args:
        legend_panel_inner: 凡例パネル（#legend-panel）の内側 HTML断片。
            ``_build_legend_panel_inner()`` の戻り値を渡す。
            ビュー存在に応じて BGP/OSPF 節の表示が制御される。
    """
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
{_CSS}

    /* レイヤー表示制御（routing キーから動的生成） */
{layer_hide_css}
  </style>
</head>
<body>
  <header>
    <h1 id="topo-title">{title}</h1>
    <span style="font-size:0.75rem;opacity:0.7;">
      <kbd>F</kbd> 全体表示　<kbd>Esc</kbd> リセット　<kbd>1</kbd>〜<kbd>5</kbd> ビュー切替　<kbd>/</kbd> 検索　ホイール=ズーム　ドラッグ=パン　クリック=ノード選択
    </span>
    <button id="theme-toggle" class="header-btn" onclick="toggleTheme()" title="ダーク/ライトテーマ切替">🌙</button>
  </header>

  <!-- ビュー切替タブ -->
  <div class="view-tabs" id="view-tabs">
    {tabs_html}
  </div>

  <div class="controls">
    <span class="controls-label" style="margin-left:0;">Search:</span>
    <input type="search" id="search-input" placeholder="hostname / IP / CIDR..." oninput="filterNodes(this.value)">
    <button id="search-next" class="zoom-btn" title="次のマッチへ（Enter）" style="margin-left:4px;">次へ</button>
    <span id="search-count" style="margin-left:8px;font-size:0.8rem;color:var(--text-muted);"></span>
    <button id="filter-connected" class="zoom-btn" onclick="filterConnected()" style="margin-left:12px;" title="選択ノードと接続先のみ表示">接続先のみ</button>
    <button id="invert-selection" class="zoom-btn" onclick="invertSelection()" style="margin-left:4px;" title="選択反転">選択反転</button>
  </div>

  {node_filter_html}

  <!-- 上下スプリットペインコンテナ -->
  <div id="split-pane-container">
    <!-- 上ペイン: 図 -->
    <div id="svg-container">
      <svg id="topology-svg"
           width="100%" height="100%"
           viewBox="{vb_min_x:.1f} {vb_min_y:.1f} {svg_width} {svg_height}"
           xmlns="http://www.w3.org/2000/svg">
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8"
                  refX="6" refY="3" orient="auto">
            <path d="M0,0 L0,6 L8,3 z" fill="#6b7280"/>
          </marker>
        </defs>
        <!-- ズーム/パン用グループ -->
        <g id="viewport">
          {all_views_svg}
        </g>
      </svg>
      <!-- ズーム操作ボタン群（図ペイン右上） -->
      <div id="zoom-controls">
        <button id="zoom-fit" class="zoom-btn" title="全体表示">⛶ fit</button>
        <button id="zoom-in" class="zoom-btn" title="拡大">+</button>
        <button id="zoom-out" class="zoom-btn" title="縮小">−</button>
        <button id="zoom-reset" class="zoom-btn" title="等倍リセット">1:1</button>
        <button id="minimap-toggle" class="zoom-btn" title="ミニマップ表示/非表示">⊞</button>
        <button id="legend-toggle" class="zoom-btn" onclick="toggleLegend()" title="凡例を表示/非表示">凡例</button>
        <button id="cards-toggle" class="zoom-btn" onclick="toggleCardsPane()" title="表の表示/最小化（図のみ）">表</button>
      </div>
      <!-- Round D: ミニマップ（右下オーバーレイ） -->
      <svg id="minimap" class="minimap" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
        <use id="minimap-use" href=""/>
        <rect id="minimap-viewport" class="minimap-viewport"/>
      </svg>
      <!-- #16: 旧 IF チップ凡例オーバーレイ(#chip-legend)は撤去。
           IF チップ凡例は統合凡例パネル(#legend-panel)の「IF チップ」節に統合済み（重複排除）。 -->
      <!-- 統合凡例パネル（右上 zoom-controls の下、初期表示） -->
      <div id="legend-panel">
{legend_panel_inner}
      </div>
    </div>

    <!-- 境界ディバイダ（ドラッグで上下ペイン高を可変） -->
    <div id="split-divider"></div>

    <!-- 下ペイン: Device Details -->
    <div id="cards-section">
      <!-- sticky ヘッダ: LAYERS トグル + Device Details 見出し（スクロール時に上端固定） -->
      <div id="cards-header">
        <!-- LAYERS トグル（Device Details 見出し付近） -->
        <div class="controls" id="layers-controls" style="padding:6px 0 10px;border:none;">
          <span class="controls-label">Layers:</span>
          {toggles_html}
        </div>
        <h2>Device Details
          <label style="font-size:0.8rem;font-weight:400;margin-left:16px;cursor:pointer;">
            <input type="checkbox" id="card-filter-toggle" style="vertical-align:middle;" checked>
            選択中の機器のみ表示
          </label>
        </h2>
      </div>
      <div class="cards-grid">
        {cards_html}
      </div>
    </div>
  </div>

  <!-- 埋め込み topology データ -->
  <script type="application/json" id="topology-data">
{topology_json_safe}
  </script>

  <script>
{_JS}
  </script>
</body>
</html>"""
