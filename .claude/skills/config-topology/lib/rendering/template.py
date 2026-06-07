"""
rendering/template.py — HTML テンプレート（静的 CSS/JS 定数 + build_html）
"""
from __future__ import annotations

from lib.rendering.svg import _esc

# ---------------------------------------------------------------------------
# 静的 CSS 定数（f-string 内では {{ }} でエスケープされていた箇所を { } に戻す）
# ---------------------------------------------------------------------------

_CSS = """\
    /* CSS 変数によるカラースキーム（拡張用） */
    :root {
      /* --- 意味色（アクセント: 両テーマで判別性を保つ） --- */
      --color-node-fill: #dbeafe;
      --color-node-stroke: #3b82f6;
      --color-node-text: #1e3a5f;
      --color-node-fill-hover: #bfdbfe;   /* ノードホバー/ハイライト塗りつぶし（ライト） */
      --color-node-fill-selected: #fef08a; /* ノード選択時塗りつぶし（ライト） */
      --color-node-fill-dimmed: #f3f4f6;  /* dimmed ノード塗りつぶし（ライト）*/
      --color-node-stroke-dimmed: #d1d5db; /* dimmed ノード枠線（ライト）*/
      --color-seg-fill: #fef3c7;
      --color-seg-stroke: #d97706;
      --color-seg-label: #92400e;          /* セグメントラベル文字色（ライト: seg-fill上でコントラスト確保）*/
      --color-link: #6b7280;
      --color-bgp-ebgp: #2563eb;
      --color-bgp-ibgp: #d97706;
      --color-bgp-highlight: #dc2626;  /* BGPセッション選択時の共通ハイライト色（赤系）: iBGPアンバー・eBGP青と判別可能 */
      --color-bgp-unknown: #9ca3af;
      --color-highlight: #f59e0b;
      --color-selected: #ef4444;
      --color-card-bg: #f9fafb;
      /* --color-card-border は --border-color に統一（二重定義解消）。参照箇所は var(--border-color) を使用 */
      --color-ospf: #059669;  /* OSPFラベル・テーマ色（緑系）*/
      --font-main: 'Segoe UI', Arial, sans-serif;
      --font-mono: 'Consolas', 'Courier New', monospace;
      /* --- 構造色（ライトテーマ既定値）--- */
      --bg-page: #f3f4f6;
      --bg-surface: #fff;
      --bg-elevated: #e5e7eb;
      --text-main: #111827;
      --text-muted: #6b7280;
      --text-heading: #1e3a5f;
      --header-bg: #1e3a5f;
      --header-text: #fff;
      --tab-underline: #3b82f6;
      --border-color: #e5e7eb;
      --stripe-bg: #f3f4f6;
      --kbd-bg: #e5e7eb;
      --kbd-border: #9ca3af;
      /* --- UI コンポーネント色 --- */
      --btn-bg: rgba(255, 255, 255, 0.92);  /* zoom-btn 背景（ライト）*/
      --btn-fg: var(--text-main);            /* zoom-btn 文字色 */
      --btn-hover-bg: #e0e7ff;               /* zoom-btn ホバー背景（ライト）*/
      --btn-hover-border: #6366f1;           /* zoom-btn ホバー枠線（ライト）*/
      --btn-hover-fg: #3730a3;               /* zoom-btn ホバー文字色（ライト）*/
      --overlay-bg: rgba(255, 255, 255, 0.88); /* ミニマップ等の不透明オーバーレイ背景（ライト）*/
      /* --- テーブルハイライト（意味色: ライト固定値→ダークで上書き）--- */
      --color-row-selected-bg: #fef08a;      /* 選択行の背景（ライト: 黄）*/
      --color-row-highlighted-bg: #fef3c7;   /* ハイライト行の背景（ライト: 薄黄）*/
      --color-row-unused-bg: #fff7ed;        /* 未使用候補行の背景（ライト: 薄橙）*/
      --color-row-unused-fg: #92400e;        /* 未使用候補行の文字色（ライト）*/
      --color-row-route-bg: #d1fae5;         /* ルート選択行の背景（ライト: 薄緑）*/
      --color-row-search-bg: #fef3c7;        /* 検索マッチ行の背景（ライト: 薄黄）*/
      /* --- バッジ（カード内: ライト固定値→ダークで上書き）--- */
      --badge-vendor-bg: #e0e7ff;
      --badge-vendor-fg: #3730a3;
      --badge-as-bg: #d1fae5;
      --badge-as-fg: #065f46;
      --badge-rid-ospf-bg: #d1fae5;
      --badge-rid-ospf-fg: #065f46;
      --badge-rid-bgp-bg: #dbeafe;
      --badge-rid-bgp-fg: #1e3a8a;
      /* --- external ピアノード（BGPビュー）--- */
      --color-external-fill: #f9fafb;        /* BGP 外部ピアノード塗りつぶし（ライト）*/
      --color-external-fill-hover: #f3f4f6;  /* BGP 外部ピアノードホバー（ライト）*/
      --color-external-stroke: #9ca3af;      /* BGP 外部ピアノード枠線（ライト）*/
      /* --- ミニマップ --- */
      --minimap-vp-fill: rgba(59, 130, 246, 0.15); /* ビューポート矩形塗りつぶし（ライト: 青半透明）*/
    }

    /* ダークテーマ上書き
       NOTE: localStorage が file:// スキームやプライベートブラウズ環境では保持されない場合がある。
             その場合は既定（ライト）テーマで表示される。
       NOTE: AS枠の fill_rgba（svg.py _AS_COLOR_PALETTE 出力）はPythonインライン style のため
             ここでは上書きできない。stroke で識別可能なため許容（別バックログ）。
       NOTE: 意味色（--color-bgp-ebgp/--color-ospf/--color-highlight/--color-selected）は
             両テーマで視認可能なため上書きしない（誤上書き退行防止）。 */
    [data-theme="dark"] {
      /* --- 構造色 --- */
      --bg-page: #0f172a;
      --bg-surface: #1e293b;
      --bg-elevated: #334155;
      --text-main: #e2e8f0;
      --text-muted: #94a3b8;
      --text-heading: #93c5fd;
      --header-bg: #0f172a;
      --header-text: #e2e8f0;
      --tab-underline: #60a5fa;
      --border-color: #334155;
      --stripe-bg: #1e293b;
      --kbd-bg: #334155;
      --kbd-border: #475569;
      /* --- 意味色: ダーク用に明度確保（色覚配慮: 青/橙/緑/赤の判別を維持） --- */
      --color-node-fill: #1e3a8a;
      --color-node-stroke: #60a5fa;          /* ダーク背景での視認性向上（ライト #3b82f6 → 明るい青）*/
      --color-node-text: #dbeafe;
      --color-node-fill-hover: #2d4fa0;      /* ダーク: ホバー塗りつぶしを濃色に（白ジャンプ防止）*/
      --color-node-fill-selected: #78350f;   /* ダーク: 選択ノードは橙系暗色（黄 #fef08a との差別化）*/
      --color-node-fill-dimmed: #1e293b;     /* ダーク: dimmed はページ背景相当（意図: 目立たない）*/
      --color-node-stroke-dimmed: #334155;   /* ダーク: dimmed 枠線 */
      --color-seg-fill: #78350f;
      --color-seg-label: #fed7aa;            /* ダーク: seg-fill(#78350f)上でコントラスト確保（明橙系）*/
      --color-card-bg: #1e293b;
      --color-link: #94a3b8;
      --color-bgp-ebgp: #60a5fa;             /* ダーク背景 #1e293b 上で WCAG 3:1 確保（コントラスト比 約4.5:1）*/
      /* --- UI コンポーネント色 (ダーク) --- */
      --btn-bg: #334155;                     /* zoom-btn 背景（ダーク: 暗青系）*/
      --btn-fg: #e2e8f0;                     /* zoom-btn 文字色（ダーク: 明色）*/
      --btn-hover-bg: #1e40af;               /* zoom-btn ホバー背景（ダーク: 中青）*/
      --btn-hover-border: #60a5fa;           /* zoom-btn ホバー枠線（ダーク）*/
      --btn-hover-fg: #bfdbfe;               /* zoom-btn ホバー文字色（ダーク）*/
      --overlay-bg: rgba(15, 23, 42, 0.92);  /* ミニマップ等オーバーレイ背景（ダーク: --bg-page 相当）*/
      /* --- テーブルハイライト (ダーク: 暗色で意味の色相を維持) --- */
      --color-row-selected-bg: #713f12;      /* ダーク: 選択行 黄→暗橙（色相維持）*/
      --color-row-highlighted-bg: #451a03;   /* ダーク: ハイライト行 薄黄→極暗橙 */
      --color-row-unused-bg: #431407;        /* ダーク: 未使用候補行 薄橙→暗赤橙 */
      --color-row-unused-fg: #fed7aa;        /* ダーク: 未使用候補行文字 → 明橙 */
      --color-row-route-bg: #064e3b;         /* ダーク: ルート選択行 薄緑→暗緑 */
      --color-row-search-bg: #451a03;        /* ダーク: 検索マッチ行 薄黄→暗橙 */
      /* --- バッジ (ダーク) --- */
      --badge-vendor-bg: #1e3a8a;
      --badge-vendor-fg: #bfdbfe;
      --badge-as-bg: #064e3b;
      --badge-as-fg: #a7f3d0;
      --badge-rid-ospf-bg: #064e3b;
      --badge-rid-ospf-fg: #a7f3d0;
      --badge-rid-bgp-bg: #1e3a8a;
      --badge-rid-bgp-fg: #bfdbfe;
      /* --- external ピアノード (ダーク) --- */
      --color-external-fill: #1e293b;        /* ダーク: BGP外部ピア塗りつぶし（暗系）*/
      --color-external-fill-hover: #334155;  /* ダーク: BGP外部ピアホバー */
      --color-external-stroke: #64748b;      /* ダーク: BGP外部ピア枠線 */
      /* --- ミニマップ (ダーク) --- */
      --minimap-vp-fill: rgba(96, 165, 250, 0.25); /* ダーク: ビューポート矩形（明青半透明、暗背景で視認可能）*/
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    html, body {
      height: 100%;
    }

    body {
      font-family: var(--font-main);
      background: var(--bg-page);
      color: var(--text-main);
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }

    header {
      background: var(--header-bg);
      color: var(--header-text);
      padding: 12px 20px;
      display: flex;
      align-items: center;
      gap: 16px;
    }

    header h1 {
      font-size: 1.1rem;
      font-weight: 600;
    }

    /* ビュー切替タブ */
    .view-tabs {
      background: var(--bg-surface);
      border-bottom: 2px solid var(--border-color);
      padding: 0 20px;
      display: flex;
      gap: 0;
    }

    .view-tab {
      padding: 8px 16px;
      font-size: 0.85rem;
      font-weight: 600;
      border: none;
      background: transparent;
      color: var(--text-muted);
      cursor: pointer;
      border-bottom: 3px solid transparent;
      margin-bottom: -2px;
      transition: color 0.15s, border-color 0.15s;
    }

    .view-tab:hover {
      color: var(--text-heading);
    }

    .view-tab.active {
      color: var(--text-heading);
      border-bottom-color: var(--tab-underline);
    }

    .controls {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border-color);
      padding: 8px 20px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
    }

    .controls-label {
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .layer-toggle {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 0.85rem;
      cursor: pointer;
      padding: 3px 8px;
      border-radius: 4px;
      border: 1px solid var(--border-color);
      background: var(--color-card-bg);
      user-select: none;
    }

    .layer-toggle:hover {
      background: var(--bg-elevated);
    }

    /* 検索ボックス */
    #search-input {
      padding: 4px 10px;
      font-size: 0.85rem;
      border: 1px solid var(--border-color);
      border-radius: 4px;
      min-width: 200px;
    }

    kbd {
      font-family: var(--font-mono);
      background: var(--kbd-bg);
      border: 1px solid var(--kbd-border);
      border-radius: 3px;
      padding: 1px 5px;
      font-size: 0.75rem;
    }

    /* 上下スプリットペインコンテナ（ヘッダ等固定UI の下に残り高さを分割） */
    #split-pane-container {
      display: flex;
      flex-direction: column;
      flex: 1;
      min-height: 0;
    }

    #svg-container {
      /* transform モデル: SVG は width=100% でコンテナを覆うため溢れない。
         overflow:hidden でスクロールバーの誤表示を防ぐ（overflow:auto は scroll(px)モデルの遺産）。
         flex: 2 1 0（flex-basis:0）で内容サイズ非依存の比率配分にする。
         cards-section 内容の高さ変化が svg-container の clientHeight に波及しなくなり
         ResizeObserver が不要な再計算（図のパン）を起こさなくなる。[G3修正] */
      overflow: hidden;
      flex: 2 1 0;
      min-height: 120px;
      background: var(--bg-surface);
      cursor: grab;
      position: relative;
    }

    /* 上下ペイン境界バー（ドラッグで高さ可変） */
    #split-divider {
      height: 6px;
      background: var(--bg-elevated);
      border-top: 1px solid var(--border-color);
      border-bottom: 1px solid var(--border-color);
      cursor: row-resize;
      flex-shrink: 0;
      user-select: none;
    }

    #split-divider:hover {
      background: var(--tab-underline);
    }

    #svg-container:active {
      cursor: grabbing;
    }

    #topology-svg {
      display: block;
    }

    /* ノード */
    .node-rect {
      fill: var(--color-node-fill);
      stroke: var(--color-node-stroke);
      stroke-width: 2;
      transition: fill 0.15s, stroke-width 0.15s;
    }

    .device-node:hover .node-rect,
    .device-node.highlighted .node-rect {
      fill: var(--color-node-fill-hover);
      stroke-width: 3;
    }

    .device-node.selected .node-rect {
      fill: var(--color-node-fill-selected);
      stroke: var(--color-selected);
      stroke-width: 3;
    }

    .device-node.dimmed .node-rect {
      fill: var(--color-node-fill-dimmed);
      stroke: var(--color-node-stroke-dimmed);
      opacity: 0.4;
    }

    .device-node.dimmed text {
      opacity: 0.4;
    }

    .device-node.search-match .node-rect {
      stroke: #f59e0b;
      stroke-width: 3;
    }

    .node-label {
      font-size: 13px;
      font-weight: 700;
      fill: var(--color-node-text);
      pointer-events: none;
    }

    .node-sublabel {
      font-size: 10px;
      fill: var(--text-muted);
      pointer-events: none;
    }

    .node-rid {
      font-size: 9px;
      fill: var(--text-muted);
      font-family: var(--font-mono);
      pointer-events: none;
    }

    /* BGP 外部ピアノード（B4: topology 外のピア。BGP ビューのみ表示） */
    .external-rect {
      fill: var(--color-external-fill);
      stroke: var(--color-external-stroke);
      stroke-width: 1.5;
      stroke-dasharray: 5 3;
    }

    .device-node.external-node:hover .external-rect,
    .device-node.external-node.highlighted .external-rect {
      fill: var(--color-external-fill-hover);
      stroke-width: 2.5;
    }

    .external-label {
      fill: var(--text-muted);
      font-weight: 600;
    }

    /* セグメントノード */
    .seg-ellipse {
      fill: var(--color-seg-fill);
      stroke: var(--area-stroke, var(--color-seg-stroke));
      stroke-width: 2;
    }

    .seg-label {
      font-size: 10px;
      fill: var(--color-seg-label);
      pointer-events: none;
    }

    .seg-edge {
      stroke: var(--area-stroke, var(--color-seg-stroke));
      stroke-width: 1.5;
      stroke-dasharray: 6 3;
    }

    .seg-edge.highlighted {
      stroke: var(--color-highlight);
      stroke-width: 3.5;
      stroke-dasharray: none;
    }

    .segment-node.highlighted .seg-ellipse {
      stroke: var(--color-highlight);
      stroke-width: 3.5;
    }

    /* リンク */
    .link-line {
      stroke: var(--area-stroke, var(--color-link));
      stroke-width: 2;
      transition: stroke 0.15s, stroke-width 0.15s;
    }

    .link-edge:hover .link-line,
    .link-edge.highlighted .link-line {
      stroke: var(--color-highlight);
      stroke-width: 4;
    }

    /* BGP エッジ */
    .bgp-edge {
      stroke-width: 2;
      stroke-dasharray: 8 4;
      opacity: 0.8;
    }

    .bgp-ebgp { stroke: var(--color-bgp-ebgp); }
    .bgp-ibgp { stroke: var(--color-bgp-ibgp); }
    .bgp-unknown { stroke: var(--color-bgp-unknown); }

    .bgp-badge {
      font-size: 10px;
      fill: var(--color-bgp-ebgp);
      pointer-events: none;
      font-family: var(--font-mono);
    }

    /* OSPF リンクラベル（A2/A3: bgp-badge と同一フォントサイズ・OSPFテーマ色） */
    .link-label {
      font-size: 10px;
      fill: var(--color-ospf);
      pointer-events: none;
      font-family: var(--font-mono);
    }

    /* エッジラベルは既定非表示。対応エッジが highlighted の時だけ表示（重なり回避） */
    .bgp-badge-group, .link-label-group { display: none; }
    .bgp-badge-group.label-shown, .link-label-group.label-shown { display: inline; }

    /* カード */
    #cards-section {
      /* flex: 1 1 0（flex-basis:0）で内容サイズ非依存の比率配分にする。
         svg-container:cards-section = 2:1 の比率固定となり、カード内容の増減は
         overflow:auto でスクロール吸収されるため svg-container の高さは不変。[G3修正] */
      flex: 1 1 0;
      padding: 0 20px 20px;
      overflow: auto;
      min-height: 80px;
    }

    /* sticky ヘッダ: LAYERS トグル + Device Details 見出し を上端に固定
       background: var(--bg-surface) でスクロール時にカードがヘッダ下に潜らないよう不透明に覆う。
       margin: 0 -20px / padding: 0 20px で #cards-section の左右パディング分を打ち消し、
       横幅いっぱいの背景でカードがヘッダ脇から覗かないようにする。 */
    #cards-header {
      position: sticky;
      top: 0;
      z-index: 5;
      background: var(--bg-surface);
      margin: 0 -20px;
      padding: 12px 20px 0;
    }

    #cards-section h2 {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 12px;
      color: var(--text-main);
    }

    .cards-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 16px;
    }

    .device-card {
      background: var(--color-card-bg);
      border: 1px solid var(--border-color);
      border-radius: 8px;
      padding: 16px;
    }

    .device-card h3 {
      font-size: 1rem;
      font-weight: 700;
      margin-bottom: 10px;
      display: flex;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
    }

    .device-card h4 {
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin: 10px 0 4px;
    }

    .badge-vendor {
      font-size: 0.7rem;
      background: var(--badge-vendor-bg);
      color: var(--badge-vendor-fg);
      padding: 2px 6px;
      border-radius: 10px;
      font-weight: 500;
    }

    .badge-as {
      font-size: 0.7rem;
      background: var(--badge-as-bg);
      color: var(--badge-as-fg);
      padding: 2px 6px;
      border-radius: 10px;
      font-weight: 500;
    }

    .badge-rid {
      font-size: 0.7rem;
      padding: 2px 6px;
      border-radius: 10px;
      font-weight: 500;
    }

    .badge-rid-ospf {
      background: var(--badge-rid-ospf-bg);
      color: var(--badge-rid-ospf-fg);
    }

    .badge-rid-bgp {
      background: var(--badge-rid-bgp-bg);
      color: var(--badge-rid-bgp-fg);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 0.8rem;
    }

    th {
      text-align: left;
      padding: 3px 6px;
      background: var(--stripe-bg);
      color: var(--text-muted);
      font-weight: 600;
    }

    td {
      padding: 3px 6px;
      border-bottom: 1px solid var(--stripe-bg);
      font-family: var(--font-mono);
      word-break: break-all;
    }

    tr:last-child td { border-bottom: none; }

    .section-table { margin-top: 4px; }

    /* カード選択スタイル */
    .device-card.selected {
      border: 2px solid var(--color-selected);
      box-shadow: 0 0 6px rgba(239,68,68,0.4);
    }

    tr.selected td {
      background: var(--color-row-selected-bg);
    }

    tr.highlighted td {
      background: var(--color-row-highlighted-bg);
      font-weight: 600;
    }

    /* ノードフィルタ（非表示クラス: display:none 強制） */
    .node-filtered {
      display: none !important;
    }

    /* ノードフィルタ UI パネル */
    .node-filter-panel {
      background: var(--bg-surface);
      border-bottom: 1px solid var(--border-color);
      padding: 6px 20px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .node-filter-label {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 0.82rem;
      cursor: pointer;
      padding: 2px 6px;
      border-radius: 4px;
      border: 1px solid var(--border-color);
      background: var(--color-card-bg);
      user-select: none;
    }

    .node-filter-label:hover {
      background: var(--bg-elevated);
    }

    .node-filter-btn {
      padding: 3px 10px;
      font-size: 0.82rem;
      border: 1px solid var(--border-color);
      border-radius: 4px;
      background: var(--badge-vendor-bg);
      color: var(--badge-vendor-fg);
      cursor: pointer;
      font-weight: 600;
    }

    .node-filter-btn:hover {
      background: var(--btn-hover-bg);
      border-color: var(--btn-hover-border);
      color: var(--btn-hover-fg);
    }

    /* IF チップ（Physical ビュー ノード内の接続IF/Loopback 表示、iteration-3 #2） */
    .if-chip circle {
      fill: var(--color-node-fill-hover);
      stroke: var(--color-node-stroke);
      stroke-width: 1.5;
      transition: fill 0.1s;
    }

    .if-chip:hover circle {
      fill: var(--tab-underline);
    }

    .if-chip-shutdown circle {
      fill: var(--color-node-fill-dimmed);
      stroke: var(--color-node-stroke-dimmed);
      opacity: 0.5;
    }

    /* #7: Loopback チップ識別（緑系: 通常チップの青と区別）*/
    .if-chip-loopback circle {
      fill: #bbf7d0;
      stroke: #16a34a;
      stroke-width: 1.5;
    }

    .if-chip-loopback:hover circle {
      fill: #86efac;
    }

    /* #7: Loopback かつ shutdown の複合状態（緑系薄表示） */
    .if-chip-loopback.if-chip-shutdown circle {
      fill: #d1fae5;
      stroke: var(--text-muted);
      opacity: 0.5;
    }

    /* P2 #1: IF チップ強調（クリックで .highlighted トグル） */
    .if-chip.highlighted circle {
      fill: var(--color-node-fill-selected);
      stroke: var(--color-highlight);
      stroke-width: 2.5;
    }

    /* #16: 旧 IF チップ凡例オーバーレイ(#chip-legend)の CSS は撤去。
       IF チップ凡例は統合凡例パネル(#legend-panel)に統合済み。
       overlay 背景変数 var(--overlay-bg) はミニマップが引き続き使用するため残存。 */

    /* HC2: static 経路 next-hop ノードのハイライト（手動選択 .selected と独立） */
    .device-node.route-target .node-rect {
      fill: var(--color-row-route-bg);
      stroke: var(--color-ospf);
      stroke-width: 3;
    }

    .device-card.route-target {
      border: 2px solid var(--color-ospf);
      box-shadow: 0 0 6px rgba(5,150,105,0.4);
    }

    /* ズーム操作ボタン群（図ペイン右上に重ねる） */
    #zoom-controls {
      position: absolute;
      top: 8px;
      right: 8px;
      display: flex;
      gap: 4px;
      z-index: 10;
    }

    .zoom-btn {
      padding: 4px 8px;
      font-size: 0.8rem;
      font-weight: 600;
      border: 1px solid var(--border-color);
      border-radius: 4px;
      background: var(--btn-bg);
      color: var(--btn-fg);
      cursor: pointer;
      line-height: 1;
    }

    .zoom-btn:hover {
      background: var(--btn-hover-bg);
      border-color: var(--btn-hover-border);
      color: var(--btn-hover-fg);
    }

    .zoom-btn.active {
      background: var(--btn-hover-bg);
      border-color: var(--btn-hover-border);
      color: var(--btn-hover-fg);
    }

    /* Cards pane collapse: #split-pane-container.cards-collapsed */
    #split-pane-container.cards-collapsed #cards-section,
    #split-pane-container.cards-collapsed #split-divider { display: none; }
    #split-pane-container.cards-collapsed #svg-container { flex: 1; height: auto !important; }

    /* 統合凡例パネル（右上 zoom-controls の下、絶対配置） */
    #legend-panel {
      position: absolute;
      top: 44px;
      right: 8px;
      background: var(--bg-surface);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      padding: 10px 14px;
      z-index: 20;
      min-width: 180px;
      max-height: 60vh;
      overflow-y: auto;
      font-size: 0.8rem;
      color: var(--text-main);
      box-shadow: 0 4px 12px rgba(0,0,0,0.12);
    }

    #legend-panel .legend-section-title {
      font-weight: 700;
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-top: 8px;
      margin-bottom: 4px;
      padding-bottom: 2px;
      border-bottom: 1px solid var(--border-color);
    }

    #legend-panel .legend-row {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 2px 0;
    }

    /* ヘッダ内ボタン共通クラス（凡例トグル・テーマ切替）
       header 背景（--header-bg）の上に配置されるため rgba 透明度ベースで統一 */
    .header-btn {
      padding: 4px 10px;
      font-size: 0.8rem;
      font-weight: 600;
      border: 1px solid rgba(255,255,255,0.4);
      border-radius: 4px;
      background: rgba(255,255,255,0.15);
      color: var(--header-text);
      cursor: pointer;
      line-height: 1.4;
    }

    .header-btn:hover {
      background: rgba(255,255,255,0.25);
    }

    /* BGP ビュー AS グルーピング枠（iteration-3 Batch2 #4: 視認性改善）
       色（fill/stroke）は svg のインライン style で AS 別に付与するためここでは省略 */
    .as-group {
      stroke-width: 2;
      stroke-dasharray: none;
    }

    .as-group-label {
      font-size: 15px;
      font-weight: 700;
      pointer-events: none;
      font-family: var(--font-mono);
    }

    .as-group-label-bg {
      opacity: 0.85;
    }

    .edge-label-bg {
      fill: var(--bg-surface);
      opacity: 0.8;
      pointer-events: none;
    }

    /* #3: Static 行クリック時の行マーキング */
    tr.route-row-selected td {
      background: var(--color-row-route-bg);
      outline: 2px solid var(--color-ospf);
      outline-offset: -2px;
      font-weight: 600;
    }

    /* #5: BGP セッションハイライト（iBGP/eBGP 共通: 既定アンバー・eBGP青と判別可能な赤系） */
    .bgp-session.highlighted .bgp-edge {
      stroke: var(--color-bgp-highlight);  /* 共通変数で赤系を使用: eBGP青・iBGPアンバーと明確に判別 */
      stroke-width: 5;  /* 基本線幅(2)より太くして視認性を確保（#4 レビュー指摘対応）*/
      opacity: 1;
    }

    /* 多ノードC: カード絞り込み（選択外カードを非表示） */
    .card-unselected {
      display: none;
    }

    /* B-pass1b: グローバル検索フォーカスノード（「次へ」で巡回中の対象） */
    .device-node.search-focus .node-rect {
      stroke: #dc2626;
      stroke-width: 4;
      filter: drop-shadow(0 0 6px rgba(220,38,38,0.6));
    }

    /* グローバル検索マッチ行強調 */
    tr.search-match td {
      background: var(--color-row-search-bg);
    }

    /* ミニマップ（Round D: 大規模対策） */
    /* NOTE: left 配置（右から左下へ移動）— legend-panel は right:8px/z-index:20 のため
             右側に置くと凡例パネルが縦伸びしたとき覆われるバグを回避する。
             bottom:44px は旧 #chip-legend（撤去済み）との重なり回避の名残だが、
             位置は据え置く（左下の安定した参照位置）。
             z-index:21 は legend-panel(20) より高く将来の重なりでも前面を維持する。 */
    .minimap {
      position: absolute;
      bottom: 44px;
      left: 8px;
      width: 180px;
      height: 130px;
      border: 1px solid var(--border-color);
      border-radius: 4px;
      background: var(--overlay-bg);
      z-index: 21;
      overflow: hidden;
      cursor: crosshair;
    }

    .minimap-viewport {
      fill: var(--minimap-vp-fill);  /* テーマ追従: :root(ライト)/[data-theme="dark"](ダーク)で定義 */
      stroke: var(--color-highlight);
      stroke-width: 1.5;
      vector-effect: non-scaling-stroke;
      pointer-events: none;
    }\
"""

# ---------------------------------------------------------------------------
# 静的 JS 定数
# ---------------------------------------------------------------------------

_JS = """\
    // ============================================================
    // テーマ切替（ライト / ダーク）
    // ============================================================
    var _THEME_KEY = 'ct-theme';

    function toggleTheme() {
      var root = document.documentElement;
      var current = root.getAttribute('data-theme') || 'light';
      var next = current === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem(_THEME_KEY, next); } catch(e) {}
      var btn = document.getElementById('theme-toggle');
      if (btn) { btn.textContent = next === 'dark' ? '☀' : '🌙'; }
    }

    // DOMContentLoaded でテーマを復元（localStorage から）
    document.addEventListener('DOMContentLoaded', function() {
      try {
        var saved = localStorage.getItem(_THEME_KEY);
        if (saved === 'dark' || saved === 'light') {
          document.documentElement.setAttribute('data-theme', saved);
          var btn = document.getElementById('theme-toggle');
          if (btn) { btn.textContent = saved === 'dark' ? '☀' : '🌙'; }
        }
      } catch(e) {}
    });

    // ============================================================
    // 統合凡例パネル トグル
    // ============================================================
    function toggleLegend() {
      var panel = document.getElementById('legend-panel');
      if (!panel) return;
      // getComputedStyle を使うことで CSS 由来の display:none も正しく検出する
      var isHidden = window.getComputedStyle(panel).display === 'none';
      panel.style.display = isHidden ? 'block' : 'none';
    }

    // ============================================================
    // Cards ペイントグル（表の表示/最小化）
    // ============================================================
    var _cardsCollapsedSavedHeight = null;
    var _cardsCollapsedSavedFlex = null;
    function toggleCardsPane() {
      var container = document.getElementById('split-pane-container');
      var svgContainer = document.getElementById('svg-container');
      var btn = document.getElementById('cards-toggle');
      if (!container || !svgContainer) return;
      var isCollapsed = container.classList.contains('cards-collapsed');
      if (!isCollapsed) {
        // 折りたたみ: height/flex を退避してから解除
        _cardsCollapsedSavedHeight = svgContainer.style.height || null;
        _cardsCollapsedSavedFlex = svgContainer.style.flex || null;
        svgContainer.style.height = '';
        svgContainer.style.flex = '';
        container.classList.add('cards-collapsed');
        if (btn) btn.classList.add('active');
      } else {
        // 復元: 退避した height/flex を戻す
        container.classList.remove('cards-collapsed');
        if (_cardsCollapsedSavedHeight) {
          svgContainer.style.height = _cardsCollapsedSavedHeight;
          svgContainer.style.flex = 'none';
        } else {
          svgContainer.style.height = '';
          svgContainer.style.flex = _cardsCollapsedSavedFlex || '';
        }
        _cardsCollapsedSavedHeight = null;
        _cardsCollapsedSavedFlex = null;
        if (btn) btn.classList.remove('active');
      }
      // F5: 表ペイン最小化トグルはレイアウトを変える。reflow 完了後（rAF）に
      // ミニマップを同期する（同期呼び出しは reflow 前で clientHeight が旧値のため不正確）。
      // ResizeObserver もサイズ変化で発火するが、確定寸法での最終同期を念押しする。
      if (window.requestAnimationFrame) {
        window.requestAnimationFrame(function() {
          if (window._updateMinimap) { window._updateMinimap(); }
        });
      } else if (window._updateMinimap) {
        window._updateMinimap();
      }
    }

    // ============================================================
    // 接続フィルタ
    // ============================================================
    function filterConnected() {
      // 選択ノードが空なら no-op
      if (_selectedNodes.size === 0) return;

      // 表示中の全デバイスノードを収集
      var allDeviceIds = new Set();
      document.querySelectorAll('.device-node[data-device]').forEach(function(n) {
        allDeviceIds.add(n.getAttribute('data-device'));
      });

      // 隣接集合を現在のビュー別に計算
      var adjacent = new Set(_selectedNodes);

      // physical/bgp は selector の違いのみで同型 → ローカルヘルパで重複排除
      function _addAdjacentByEdge(selector) {
        document.querySelectorAll(selector).forEach(function(edge) {
          var a = edge.getAttribute('data-a');
          var b = edge.getAttribute('data-b');
          if (_selectedNodes.has(a) || _selectedNodes.has(b)) {
            adjacent.add(a);
            adjacent.add(b);
          }
        });
      }

      if (_currentView === 'physical') {
        _addAdjacentByEdge('.view-physical .link-edge[data-a][data-b]');
      } else if (_currentView === 'bgp') {
        _addAdjacentByEdge('.view-bgp .bgp-session[data-a][data-b]');
      } else if (_currentView === 'ospf') {
        // p2p リンク: physical/bgp と同型のヘルパーで隣接解決
        _addAdjacentByEdge('.view-ospf .link-edge[data-a][data-b]');
        // multi-access セグメント: seg-edge を data-seg-id でグルーピングし、
        // 選択ノードが属するセグメントの全 device を隣接に追加
        var segToDevs = {};
        document.querySelectorAll('.view-ospf .seg-edge[data-seg-id][data-device]').forEach(function(edge) {
          var segId = edge.getAttribute('data-seg-id');
          var dev = edge.getAttribute('data-device');
          if (!segToDevs[segId]) segToDevs[segId] = [];
          segToDevs[segId].push(dev);
        });
        Object.keys(segToDevs).forEach(function(segId) {
          var devs = segToDevs[segId];
          var hasSelected = devs.some(function(d) { return _selectedNodes.has(d); });
          if (hasSelected) {
            devs.forEach(function(d) { adjacent.add(d); });
          }
        });
      }

      // チェックボックス連動: devId → cb の Map を事前構築（O(N)クエリ削減）
      var cbMap = new Map();
      document.querySelectorAll('.node-filter-cb[data-node-filter]').forEach(function(cb) {
        cbMap.set(cb.getAttribute('data-node-filter'), cb);
      });

      // 表示集合 = adjacent、それ以外を隠す
      allDeviceIds.forEach(function(devId) {
        var visible = adjacent.has(devId);
        setNodeVisibility(devId, visible);
        var cb = cbMap.get(devId);
        if (cb) cb.checked = visible;
      });
    }

    function invertSelection() {
      // 2パス構造: physical/bgp/ospf 各ビューに同一 devId のノードが存在するため、
      // pass1 で反転後の選択 devId 集合を先に確定し、
      // pass2 で全ノード/カードに classList を一括適用する（逆転バグ防止）

      // pass1: 表示中の devId を収集し、反転後の newSelected 集合を確定（DOM操作なし）
      var newSelected = new Set();
      document.querySelectorAll('.device-node[data-device]').forEach(function(node) {
        var devId = node.getAttribute('data-device');
        if (_hiddenNodes.has(devId)) return;  // 非表示ノードはスキップ
        if (!_selectedNodes.has(devId)) {
          newSelected.add(devId);
        }
      });

      // pass2: 全 .device-node に newSelected に基づいて classList を一括適用
      document.querySelectorAll('.device-node[data-device]').forEach(function(node) {
        var devId = node.getAttribute('data-device');
        if (_hiddenNodes.has(devId)) return;
        if (newSelected.has(devId)) {
          node.classList.add('selected');
        } else {
          node.classList.remove('selected');
        }
      });

      // カードも同期（newSelected 確定後に適用）
      document.querySelectorAll('.device-card[data-device]').forEach(function(card) {
        var devId = card.getAttribute('data-device');
        if (_hiddenNodes.has(devId)) return;
        if (newSelected.has(devId)) {
          card.classList.add('selected');
        } else {
          card.classList.remove('selected');
        }
      });
      _selectedNodes.clear();
      newSelected.forEach(function(d) { _selectedNodes.add(d); });
      _updateEdgeHighlightForSelection();
      _updateCardFilter();
    }

    // ============================================================
    // ビュー切替
    // ============================================================
    // NOTE: _selectedNodes / _hiddenNodes は selectView('physical') のトップレベル呼び出し
    // より前に初期化する必要がある（var 宣言は巻き上げられるが代入は巻き上げられないため、
    // 後置だと _selectedNodes.size で TypeError になりリスナー登録が全て失われる）。
    var _selectedNodes = new Set();
    var _hiddenNodes = new Set();
    var _currentView = 'physical';

    function selectView(viewId) {
      _currentView = viewId;

      // SVG ビュー（physical/bgp/ospf 等）
      // ビュー <g> の表示切替
      var views = document.querySelectorAll('.view');
      views.forEach(function(v) {
        if (v.classList.contains('view-' + viewId)) {
          v.style.display = '';
        } else {
          v.style.display = 'none';
        }
      });

      // viewBox を選択ビューの data-bbox にセット（SVG はコンテナ 100% 固定）
      var activeView = document.querySelector('.view-' + viewId);
      if (activeView) {
        var bbox = activeView.getAttribute('data-bbox');
        if (bbox) {
          var svg = document.getElementById('topology-svg');
          svg.setAttribute('viewBox', bbox);
        }
      }

      // ビュー切替時に等倍1:1中央（naturalZoom）
      if (window._naturalZoom) { window._naturalZoom(); }

      // タブのアクティブ状態更新
      var tabs = document.querySelectorAll('.view-tab');
      tabs.forEach(function(tab) {
        if (tab.dataset.view === viewId) {
          tab.classList.add('active');
        } else {
          tab.classList.remove('active');
        }
      });

      // 検索状態をリセット
      var searchInput = document.getElementById('search-input');
      if (searchInput && searchInput.value) {
        filterNodes(searchInput.value);
      }

      // F1: ビュー切替時に複数選択エッジハイライトを現ビューに合わせて再適用
      if (typeof _updateEdgeHighlightForSelection === 'function') {
        _updateEdgeHighlightForSelection();
      }

      // Round D: ビュー切替時にミニマップを更新
      if (window._updateMinimap) { window._updateMinimap(); }
    }

    // ズーム関数の役割分担:
    //   naturalZoom  — 初期表示・ビュー切替・Esc・1:1ボタン → 等倍1:1中央
    //   zoomFit      — 手動 fit（F キー・⛶ ボタン）→ 図全体がコンテナに収まる最大倍率
    // 初期ビューを naturalZoom 基準で設定（selectView 内で window._naturalZoom() を呼ぶ）
    selectView('physical');
    // A5: DOMContentLoaded でも再実行（IIFE 内の即時 naturalZoom() の保険）
    // clientWidth が確定した後に再適用されるため冪等で安全。
    if (typeof window !== 'undefined') {
      document.addEventListener('DOMContentLoaded', function() {
        if (window._naturalZoom) { window._naturalZoom(); }
      });
    }

    // ============================================================
    // 検索 / フィルタ
    // ============================================================

    // ---- CIDR ユーティリティ ----
    function _parseCidrV4(cidr) {
      // "10.0.0.0/24" → {netInt, prefix} or null
      var slash = cidr.indexOf('/');
      if (slash === -1) return null;
      var ipPart = cidr.slice(0, slash);
      var prefixStr = cidr.slice(slash + 1);
      var prefix = parseInt(prefixStr, 10);
      if (isNaN(prefix) || prefix < 0 || prefix > 32) return null;
      var octets = ipPart.split('.');
      if (octets.length !== 4) return null;
      var netInt = 0;
      for (var i = 0; i < 4; i++) {
        var o = parseInt(octets[i], 10);
        if (isNaN(o) || o < 0 || o > 255) return null;
        netInt = (netInt * 256 + o) >>> 0;
      }
      return {netInt: netInt, prefix: prefix};
    }

    function _ipv4ToInt(ip) {
      var octets = ip.split('.');
      if (octets.length !== 4) return null;
      var val = 0;
      for (var i = 0; i < 4; i++) {
        var o = parseInt(octets[i], 10);
        if (isNaN(o) || o < 0 || o > 255) return null;
        val = (val * 256 + o) >>> 0;
      }
      return val;
    }

    function _inCidrV4(ipCidr, networkCidr) {
      // ipCidr: "10.0.0.1/30" (address部のみ使用), networkCidr: {netInt, prefix}
      var slash = ipCidr.indexOf('/');
      var ip = slash !== -1 ? ipCidr.slice(0, slash) : ipCidr;
      var ipInt = _ipv4ToInt(ip);
      if (ipInt === null) return false;
      if (networkCidr.prefix === 0) return true;
      var mask = (~((1 << (32 - networkCidr.prefix)) - 1)) >>> 0;
      return ((ipInt & mask) >>> 0) === ((networkCidr.netInt & mask) >>> 0);
    }

    function _expandV6(ip) {
      // IPv6 短縮形を展開して 8グループの数値配列を返す。失敗時 null
      ip = ip.toLowerCase();
      // :: を展開
      var dcolon = ip.indexOf('::');
      var left, right;
      if (dcolon !== -1) {
        left = ip.slice(0, dcolon).split(':').filter(function(s) { return s !== ''; });
        right = ip.slice(dcolon + 2).split(':').filter(function(s) { return s !== ''; });
        var fill = 8 - left.length - right.length;
        if (fill < 0) return null;
        var mid = [];
        for (var i = 0; i < fill; i++) mid.push('0');
        var groups = left.concat(mid).concat(right);
      } else {
        var groups = ip.split(':');
      }
      if (groups.length !== 8) return null;
      var nums = [];
      for (var j = 0; j < 8; j++) {
        var v = parseInt(groups[j], 16);
        if (isNaN(v)) return null;
        nums.push(v);
      }
      return nums;
    }

    function _v6ToBigInt(nums) {
      var val = BigInt(0);
      for (var i = 0; i < 8; i++) {
        val = (val << BigInt(16)) | BigInt(nums[i]);
      }
      return val;
    }

    function _parseCidrV6(cidr) {
      // "2001:db8::/32" → {netBig, prefix} or null
      var slash = cidr.indexOf('/');
      if (slash === -1) return null;
      var ipPart = cidr.slice(0, slash);
      var prefix = parseInt(cidr.slice(slash + 1), 10);
      if (isNaN(prefix) || prefix < 0 || prefix > 128) return null;
      var nums = _expandV6(ipPart);
      if (!nums) return null;
      return {netBig: _v6ToBigInt(nums), prefix: prefix};
    }

    function _inCidrV6(ipCidr, networkCidr) {
      // ipCidr: "2001:db8::1/64" のアドレス部
      var slash = ipCidr.indexOf('/');
      var ip = slash !== -1 ? ipCidr.slice(0, slash) : ipCidr;
      var nums = _expandV6(ip);
      if (!nums) return false;
      var ipBig = _v6ToBigInt(nums);
      if (networkCidr.prefix === 0) return true;
      var shift = BigInt(128 - networkCidr.prefix);
      var mask = ((BigInt(1) << BigInt(networkCidr.prefix)) - BigInt(1)) << shift;
      return (ipBig & mask) === (networkCidr.netBig & mask);
    }

    function _isV4Cidr(s) {
      return /^(\\d{1,3}\\.){3}\\d{1,3}\\/\\d+$/.test(s);
    }

    function _isV6Cidr(s) {
      return s.indexOf('/') !== -1 && (s.indexOf(':') !== -1);
    }

    // 共通ヘルパー: ips 配列（空白区切り文字列 or 配列）が cidrQuery に内包される IP を持つか
    // _nodeMatchesCidr から再利用する（v4/v6 ループを DRY 化）。
    function _ipsMatchCidr(ipsAttr, cidrQuery) {
      var ipsStr = (ipsAttr || '').trim();
      if (!ipsStr) return false;
      var ips = ipsStr.split(/\\s+/);
      if (_isV4Cidr(cidrQuery)) {
        var net4 = _parseCidrV4(cidrQuery);
        if (!net4) return false;
        for (var i = 0; i < ips.length; i++) {
          if (ips[i].indexOf(':') === -1 && _inCidrV4(ips[i], net4)) return true;
        }
        return false;
      } else {
        var net6 = _parseCidrV6(cidrQuery);
        if (!net6) return false;
        for (var i = 0; i < ips.length; i++) {
          if (ips[i].indexOf(':') !== -1 && _inCidrV6(ips[i], net6)) return true;
        }
        return false;
      }
    }

    function _nodeMatchesCidr(node, cidrQuery) {
      var ipsAttr = node.getAttribute('data-ips') || '';
      return _ipsMatchCidr(ipsAttr, cidrQuery);
    }

    // 検索ナビゲーション状態（全ビュー横断・タブ自動切替用）
    var _searchMatches = [];     // マッチした機器ID の決定的リスト（id 昇順）
    var _searchFocusIndex = -1;  // 現在フォーカス中のインデックス（-1=未選択）
    var _isNavigating = false;   // navigateSearchNext 実行中フラグ（filterNodes のインデックスリセットをガード）

    function filterNodes(query) {
      var q = (query || '').toLowerCase().trim();

      // CIDR モード判定: '/' を含み v4/v6 CIDR として解釈できる場合
      var isCidrMode = q.indexOf('/') !== -1 && (_isV4Cidr(q) || _isV6Cidr(q));

      // 全グラフビュー（physical/bgp/ospf）を横断してノードにマッチ適用
      var allGraphViews = document.querySelectorAll('.view');
      // マッチした機器IDを収集（ビュー間重複除去）
      var matchedDevices = new Set();

      allGraphViews.forEach(function(viewEl) {
        var nodes = viewEl.querySelectorAll('.device-node');
        nodes.forEach(function(node) {
          if (!q) {
            node.classList.remove('dimmed');
            node.classList.remove('search-match');
            node.classList.remove('search-focus');
          } else {
            var matched;
            if (isCidrMode) {
              matched = _nodeMatchesCidr(node, q);
            } else {
              var searchVal = (node.getAttribute('data-search') || '').toLowerCase();
              matched = searchVal.indexOf(q) !== -1;
            }
            if (matched) {
              node.classList.remove('dimmed');
              node.classList.add('search-match');
              var devId = node.getAttribute('data-device');
              if (devId) matchedDevices.add(devId);
            } else {
              node.classList.add('dimmed');
              node.classList.remove('search-match');
              node.classList.remove('search-focus');
            }
          }
        });

        // エッジも淡色化（両端が dimmed のとき）
        var links = viewEl.querySelectorAll('.link-edge');
        links.forEach(function(link) {
          if (!q) {
            link.style.opacity = '';
            return;
          }
          var aNode = viewEl.querySelector('.device-node[data-device="' + CSS.escape(link.dataset.a) + '"]');
          var bNode = viewEl.querySelector('.device-node[data-device="' + CSS.escape(link.dataset.b) + '"]');
          var aDimmed = aNode && aNode.classList.contains('dimmed');
          var bDimmed = bNode && bNode.classList.contains('dimmed');
          link.style.opacity = (aDimmed && bDimmed) ? '0.15' : '';
        });
      });

      // マッチ機器リストを id 昇順の決定的リストに変換（ナビゲーション用）
      _searchMatches = Array.from(matchedDevices).sort();
      // _isNavigating 中（navigateSearchNext から selectView 経由で再呼び出しの場合）は
      // インデックスをリセットしない（クロスタブ「次へ」で i/N 表示が維持される）
      if (!_isNavigating) {
        _searchFocusIndex = -1;
        // フォーカスクラス解除（ユーザー入力起動のときのみリセット）
        document.querySelectorAll('.device-node.search-focus').forEach(function(n) {
          n.classList.remove('search-focus');
        });
      }

      // 件数表示（未ナビゲーション時は件数のみ）
      _updateSearchCount();
    }

    // 件数表示更新ヘルパー
    function _updateSearchCount() {
      var countEl = document.getElementById('search-count');
      if (!countEl) return;
      var searchInput = document.getElementById('search-input');
      var q = searchInput ? searchInput.value.trim() : '';
      if (!q) {
        countEl.textContent = '';
        return;
      }
      var total = _searchMatches.length;
      if (total === 0) {
        countEl.textContent = '0件';
        return;
      }
      if (_searchFocusIndex >= 0) {
        countEl.textContent = (_searchFocusIndex + 1) + '/' + total + '件';
      } else {
        countEl.textContent = total + '件';
      }
    }

    // 「次へ」ナビゲーション — マッチ機器を id 昇順で巡回
    // 各ステップで対象機器をグラフビューに表示（タブ自動切替）し中央寄せ
    function navigateSearchNext() {
      if (_searchMatches.length === 0) return;

      // 旧フォーカス解除
      document.querySelectorAll('.device-node.search-focus').forEach(function(n) {
        n.classList.remove('search-focus');
      });

      // 次のインデックスへ進む（巡回）
      _searchFocusIndex = (_searchFocusIndex + 1) % _searchMatches.length;
      var targetDevId = _searchMatches[_searchFocusIndex];

      // 対象ノードが現ビューに存在するか確認（なければ Physical タブへ自動切替）
      var targetInCurrentView = false;
      var currentViewEl = document.querySelector('.view-' + _currentView);
      if (currentViewEl) {
        var nodeInCurrent = currentViewEl.querySelector(
          '.device-node[data-device="' + CSS.escape(targetDevId) + '"]'
        );
        if (nodeInCurrent) targetInCurrentView = true;
      }
      // 現ビューにない → Physical タブへ自動切替
      // _isNavigating フラグで filterNodes 内の _searchFocusIndex リセットを抑止する
      if (!targetInCurrentView) {
        _isNavigating = true;
        selectView('physical');
        _isNavigating = false;
      }

      // フォーカスノードに .search-focus クラスを付与（全ビュー）
      document.querySelectorAll(
        '.device-node[data-device="' + CSS.escape(targetDevId) + '"]'
      ).forEach(function(n) {
        n.classList.add('search-focus');
      });

      // 中央寄せ: 現ビューのノード座標を使い、viewport の translateX/Y を更新
      _centerOnDevice(targetDevId);

      // 件数表示を i/N件 に更新
      _updateSearchCount();
    }

    // ノード中央寄せヘルパー（ズーム closure の _zoomState 共有オブジェクト経由で更新）
    // ------------------------------------------------------------
    // _panToContentPoint(cx, cy)
    // コンテンツ座標 (cx, cy) が画面中央に来るようにパンする共通ヘルパー。
    // 中央寄せ算: translateX = cw/2 - cx*scale
    //   → スクリーン座標 cw/2（中央）= cx*scale + translateX を解くと上式が得られる。
    // _mmPanTo（ミニマップクリック）と _centerOnDevice（検索ジャンプ）の両方から呼ばれる。
    // _zoomState / _applyTransform は zoom IIFE が window に露出する（Round D より前に評価される）。
    // ------------------------------------------------------------
    function _panToContentPoint(cx, cy) {
      if (!window._zoomState || !window._applyTransform) return;
      var c = document.getElementById('svg-container');
      if (!c) return;
      var cw = c.clientWidth || 800;
      var ch = c.clientHeight || 600;
      var s = window._zoomState.scale;
      // cw/2 - cx*s: スクリーン原点をコンテンツ座標 cx が中央(cw/2)に来るよう平行移動する
      window._zoomState.translateX = cw / 2 - cx * s;
      window._zoomState.translateY = ch / 2 - cy * s;
      window._applyTransform();
    }

    function _centerOnDevice(deviceId) {
      var currentViewEl = document.querySelector('.view-' + _currentView);
      if (!currentViewEl) return;
      var node = currentViewEl.querySelector(
        '.device-node[data-device="' + CSS.escape(deviceId) + '"]'
      );
      if (!node) return;
      // 実座標は子 .node-rect の x/y/width/height 属性から取得する
      // g の transform="translate(0,0)" は常に原点のため使用しない
      var rect = node.querySelector('.node-rect');
      if (!rect) return;  // セグメント等 .node-rect を持たない要素は安全に return
      var rx = parseFloat(rect.getAttribute('x') || '0');
      var ry = parseFloat(rect.getAttribute('y') || '0');
      var rw = parseFloat(rect.getAttribute('width') || '0');
      var rh = parseFloat(rect.getAttribute('height') || '0');
      // ノード中心座標（rect の中心）
      var nx = rx + rw / 2;
      var ny = ry + rh / 2;
      // _panToContentPoint で中央寄せ（算法は共通ヘルパーに集約）
      _panToContentPoint(nx, ny);
    }

    // search-next ボタン・Enter キーのイベント登録
    (function() {
      var nextBtn = document.getElementById('search-next');
      if (nextBtn) {
        nextBtn.addEventListener('click', function(e) {
          e.stopPropagation();
          navigateSearchNext();
        });
      }
      var searchInput = document.getElementById('search-input');
      if (searchInput) {
        searchInput.addEventListener('keydown', function(e) {
          if (e.key === 'Enter') {
            e.preventDefault();
            navigateSearchNext();
          }
        });
      }
    })();

    // ============================================================
    // ズーム / パン
    // ============================================================
    (function() {
      const container = document.getElementById('svg-container');
      const svg = document.getElementById('topology-svg');
      const vp = document.getElementById('viewport');

      // ズーム定数（重複排除: wheel/ボタン/zoomFit のクランプをここで一元管理）
      var ZOOM_STEP = 1.2;
      var ZOOM_MIN = 0.2;
      var ZOOM_MAX = 5.0;

      let scale = 1.0;
      let translateX = 0;
      let translateY = 0;
      let isDragging = false;
      let dragStart = { x: 0, y: 0 };
      let translateStart = { x: 0, y: 0 };

      function applyTransform() {
        vp.setAttribute('transform',
          'translate(' + translateX + ',' + translateY + ') scale(' + scale + ')');
        if (window._updateMinimap) { window._updateMinimap(); }
      }

      // ズーム（マウスホイール）
      container.addEventListener('wheel', function(e) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? (1 / ZOOM_STEP) : ZOOM_STEP;
        scale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, scale * delta));
        applyTransform();
      }, { passive: false });

      // パン（マウスドラッグ）
      container.addEventListener('mousedown', function(e) {
        // ノード/リンク/ズームボタン上のクリックは pan を発火させない
        if (e.target.closest('.device-node') || e.target.closest('.link-edge')) return;
        if (e.target.closest('#zoom-controls')) return;
        // ミニマップ内のクリックは主SVGのpanと競合させない（ミニマップ側のpointerdownで処理）
        if (e.target.closest('#minimap')) return;
        isDragging = true;
        dragStart = { x: e.clientX, y: e.clientY };
        translateStart = { x: translateX, y: translateY };
        e.preventDefault();
      });

      document.addEventListener('mousemove', function(e) {
        if (!isDragging) return;
        translateX = translateStart.x + (e.clientX - dragStart.x);
        translateY = translateStart.y + (e.clientY - dragStart.y);
        applyTransform();
      });

      document.addEventListener('mouseup', function() {
        isDragging = false;
      });

      // ズームボタン群のクリックハンドラ
      var zoomFitBtn = document.getElementById('zoom-fit');
      var zoomInBtn = document.getElementById('zoom-in');
      var zoomOutBtn = document.getElementById('zoom-out');
      var zoomResetBtn = document.getElementById('zoom-reset');

      function zoomFit() {
        // コンテナ寸法0ガード: レイアウト前やテスト環境では 0 になる場合がある
        var cw = container.clientWidth;
        var ch = container.clientHeight;
        if (cw === 0 || ch === 0) {
          scale = 1.0; translateX = 0; translateY = 0;
          applyTransform();
          return;
        }
        // viewBox の全4要素（minX minY W H）を parse して centering を補正
        var vb = svg.getAttribute('viewBox');
        if (vb) {
          var parts = vb.split(' ');
          if (parts.length === 4) {
            var vbX = parseFloat(parts[0]);  // min-x（0 以外になりうる）
            var vbY = parseFloat(parts[1]);  // min-y（0 以外になりうる）
            var vbW = parseFloat(parts[2]);
            var vbH = parseFloat(parts[3]);
            if (vbW > 0 && vbH > 0) {
              var fitScale = Math.min(cw / vbW, ch / vbH, ZOOM_MAX);
              scale = Math.max(ZOOM_MIN, fitScale);
              // vbX/vbY を考慮した centering（min-x/min-y が 0 でも安全）
              translateX = (cw - vbW * scale) / 2 - vbX * scale;
              translateY = (ch - vbH * scale) / 2 - vbY * scale;
              applyTransform();
              return;
            }
          }
        }
        // フォールバック: リセット
        scale = 1.0; translateX = 0; translateY = 0;
        applyTransform();
      }

      // naturalZoom: 等倍1:1中央ビュー
      //   用途: 初期表示・ビュー切替（selectView）・Esc キー・1:1（reset）ボタン
      //   zoomFit との違い: zoomFit=図全体収まる最大倍率（手動 F/⛶ 専用）
      //                   naturalZoom=1 viewBox 単位 ≈ 1 CSS px になる等倍
      function naturalZoom() {
        // コンテナ寸法0ガード: レイアウト前（IIFE 即時実行時）やテスト環境では 0 になる場合がある
        var cw = container.clientWidth;
        var ch = container.clientHeight;
        if (cw === 0 || ch === 0) {
          scale = 1.0; translateX = 0; translateY = 0;
          applyTransform();
          return;
        }
        // viewBox の全4要素（minX minY W H）を parse して centering を補正
        var vb = svg.getAttribute('viewBox');
        if (vb) {
          var parts = vb.split(' ');
          if (parts.length === 4) {
            var vbX = parseFloat(parts[0]);  // min-x（0 以外になりうる）
            var vbY = parseFloat(parts[1]);  // min-y（0 以外になりうる）
            var vbW = parseFloat(parts[2]);
            var vbH = parseFloat(parts[3]);
            if (vbW > 0 && vbH > 0) {
              // 自然 scale (等倍1:1):
              //   fitScale = min(cw/vbW, ch/vbH)  → 図全体がコンテナに収まる最大倍率
              //   naturalScale = 1/fitScale の最大値 = Math.max(vbW/cw, vbH/ch)
              //   → 画面px/単位 = scale × fitScale ≈ 1 (等倍)
              //   図がコンテナより小さければ naturalScale < 1 (実寸・余白あり)
              //   図がコンテナより大きければ naturalScale > 1 (コンテナを超えるが ZOOM_MIN/MAX でクランプ)
              var naturalScale = Math.max(vbW / cw, vbH / ch);
              scale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, naturalScale));
              // centering: SVG 中心とコンテナ中心を合わせる（vbX/vbY で min-x/min-y を補正）
              //   translateX = (コンテナ幅 - 図幅×scale) / 2 - min-x×scale
              translateX = (cw - vbW * scale) / 2 - vbX * scale;
              translateY = (ch - vbH * scale) / 2 - vbY * scale;
              applyTransform();
              return;
            }
          }
        }
        // フォールバック: scale=1 リセット
        scale = 1.0; translateX = 0; translateY = 0;
        applyTransform();
      }
      window._naturalZoom = naturalZoom;
      // 即時初期化: DOM 構築済みなら cw/ch ガードで安全に実行。
      // DOMContentLoaded より前に評価されても clientWidth=0 ガードがフォールバックするため冪等。
      // ミニマップ IIFE の即時 _updateMinimap() と同じパターン。
      naturalZoom();

      // キーボード
      document.addEventListener('keydown', function(e) {
        // 入力中ガード: INPUT/TEXTAREA/SELECT または contentEditable にフォーカス中は
        // f/数字/'/` キーを横取りしない（Escape は例外で blur を優先）
        var isEditing = (
          e.target.tagName === 'INPUT' ||
          e.target.tagName === 'TEXTAREA' ||
          e.target.tagName === 'SELECT' ||
          e.target.contentEditable === 'true'
        );

        if (e.key === 'Escape') {
          // Escape は常にハンドル: 入力欄にいれば blur してから clearSelection 等を実行
          if (isEditing) { e.target.blur(); }
          clearSelection(); naturalZoom();
          return;
        }

        // 入力中はここ以降を処理しない
        if (isEditing) return;

        if (e.key === 'f' || e.key === 'F') {
          // F = 全体表示（zoomFit）
          zoomFit();
        } else if (e.key === '/') {
          // '/' = 検索欄フォーカス（'/' が入力されないよう preventDefault）
          e.preventDefault();
          var searchInput = document.getElementById('search-input');
          if (searchInput) searchInput.focus();
        } else if (e.key >= '1' && e.key <= '9') {
          // 数字キー 1〜9 でビュー切替（タブの N 番目、0-indexed = 数字-1）
          var tabs = document.querySelectorAll('.view-tab');
          var idx = parseInt(e.key, 10) - 1;
          if (idx >= 0 && idx < tabs.length) {
            selectView(tabs[idx].dataset.view);
          }
        }
      });

      applyTransform();

      if (zoomFitBtn) zoomFitBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        zoomFit();
      });
      if (zoomInBtn) zoomInBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        scale = Math.min(ZOOM_MAX, scale * ZOOM_STEP);
        applyTransform();
      });
      if (zoomOutBtn) zoomOutBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        scale = Math.max(ZOOM_MIN, scale / ZOOM_STEP);
        applyTransform();
      });
      if (zoomResetBtn) zoomResetBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        naturalZoom();
      });

      // ズーム状態を共有オブジェクトとして window に露出（_centerOnDevice から利用）
      // _zoomState 経由で scale/translateX/translateY を読み書きし applyTransform を呼ぶ。
      window._zoomState = {
        get scale() { return scale; },
        set scale(v) { scale = v; },
        get translateX() { return translateX; },
        set translateX(v) { translateX = v; },
        get translateY() { return translateY; },
        set translateY(v) { translateY = v; },
      };
      window._applyTransform = applyTransform;
      window._zoomFit = zoomFit;
      window._zoomReset = function() { naturalZoom(); };

      // ============================================================
      // ResizeObserver: コンテナリサイズ時に倍率・中心を保持する
      //
      // 倍率保持の根拠:
      //   SVG は viewBox + preserveAspectRatio="xMidYMid meet" で
      //   基底スケール base = min(cw/vbW, ch/vbH) を適用する。
      //   #viewport の transform scale s が乗り、見た目の倍率 = base × s。
      //   コンテナ寸法変化後に同じ見た目を保つには:
      //     base_old × s_old = base_new × s_new
      //     → s_new = s_old × (base_old / base_new)
      //   中心点保持: 旧コンテナ中心に写っていた content 座標を
      //     centerX = (prevCW/2 - translateX_old) / scale_old
      //     centerY = (prevCH/2 - translateY_old) / scale_old  で求め、
      //   新寸法で同じ content 点がコンテナ中心になるよう translate を再設定:
      //     translateX_new = cw/2 - centerX × scale_new
      //     translateY_new = ch/2 - centerY × scale_new
      // ============================================================
      if (typeof ResizeObserver !== 'undefined') {
        // 前回コンテナ寸法（初期は 0：初回コールバックで prevCW/prevCH を確定し補正しない）
        var prevCW = 0;
        var prevCH = 0;

        var _ro = new ResizeObserver(function() {
          if (!container || !window._zoomState || !window._applyTransform) return;

          var cw = container.clientWidth;
          var ch = container.clientHeight;

          // 初回 or サイズ変化なし: prev を更新して補正しない
          if (prevCW === 0 || prevCH === 0 || (cw === prevCW && ch === prevCH)) {
            prevCW = cw;
            prevCH = ch;
            return;
          }

          // viewBox parse（naturalZoom と同じ方式）
          var vb = svg.getAttribute('viewBox');
          if (!vb) {
            prevCW = cw;
            prevCH = ch;
            return;
          }
          var parts = vb.split(' ');
          if (parts.length !== 4) {
            prevCW = cw;
            prevCH = ch;
            return;
          }
          var vbW = parseFloat(parts[2]);
          var vbH = parseFloat(parts[3]);
          if (!(vbW > 0 && vbH > 0)) {
            prevCW = cw;
            prevCH = ch;
            return;
          }

          // 基底スケール（min による meet ロジック）
          var baseOld = Math.min(prevCW / vbW, prevCH / vbH);
          var baseNew = Math.min(cw / vbW, ch / vbH);
          if (!(baseNew > 0)) {
            prevCW = cw;
            prevCH = ch;
            return;
          }

          var z = window._zoomState;

          // 旧コンテナ中心に写っていた content 座標を算出
          var centerX = (prevCW / 2 - z.translateX) / z.scale;
          var centerY = (prevCH / 2 - z.translateY) / z.scale;

          // 見た目の倍率保持: s_new = s_old × (baseOld / baseNew)
          var scaleNew = z.scale * (baseOld / baseNew);
          z.scale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, scaleNew));

          // 新寸法で同じ content 点がコンテナ中心になるよう translate 再設定
          z.translateX = cw / 2 - centerX * z.scale;
          z.translateY = ch / 2 - centerY * z.scale;

          window._applyTransform();

          prevCW = cw;
          prevCH = ch;

          if (window._updateMinimap) { window._updateMinimap(); }
        });

        _ro.observe(container);
      }
    })();

    // ============================================================
    // 上下スプリットディバイダ ドラッグリサイズ
    // ============================================================
    (function() {
      var divider = document.getElementById('split-divider');
      var svgContainer = document.getElementById('svg-container');
      if (!divider || !svgContainer) return;

      var isDraggingDivider = false;
      var dragStartY = 0;
      var startHeight = 0;

      divider.addEventListener('mousedown', function(e) {
        isDraggingDivider = true;
        dragStartY = e.clientY;
        startHeight = svgContainer.offsetHeight;
        e.preventDefault();
        e.stopPropagation();
      });

      document.addEventListener('mousemove', function(e) {
        if (!isDraggingDivider) return;
        var delta = e.clientY - dragStartY;
        var newHeight = startHeight + delta;
        // minH: 図ペインの最小高（SVG が潰れないよう 120px を確保）
        var minH = 120;
        // maxH: ヘッダ(~50px) + タブ(~38px) + サーチ(~40px) + フィルタ(~36px) ≈ 200px を
        //        下ペインに残し、上ペインが window 全高を超えないよう制限。
        //        さらに maxH >= minH+1 を保証し、上ペインが 0 になるのを防ぐ。
        var maxH = Math.max(minH + 1, window.innerHeight - 200);
        newHeight = Math.max(minH, Math.min(maxH, newHeight));
        svgContainer.style.flex = 'none';
        svgContainer.style.height = newHeight + 'px';
      });

      document.addEventListener('mouseup', function() {
        if (!isDraggingDivider) return;
        isDraggingDivider = false;
        // F5: ペイン高さ確定後、レイアウト reflow 完了後（rAF）にミニマップを最終同期する。
        // ResizeObserver はドラッグ中に発火するが、確定時の最終寸法（clientWidth/Height）で
        // ビューポート矩形を確実に再計算し、リサイズ後のミニマップ精度ズレを防ぐ。
        if (window.requestAnimationFrame) {
          window.requestAnimationFrame(function() {
            if (window._updateMinimap) { window._updateMinimap(); }
          });
        } else if (window._updateMinimap) {
          window._updateMinimap();
        }
      });
    })();

    // ============================================================
    // ホバー & 選択ハイライト
    // ============================================================
    (function() {
      const allNodes = document.querySelectorAll('.device-node');
      const allLinks = document.querySelectorAll('.link-edge');
      const allBgpSessions = document.querySelectorAll('.bgp-session');
      const allSegEdges = document.querySelectorAll('.seg-edge');
      const allSegmentNodes = document.querySelectorAll('.segment-node');
      // ⑮(perf): ホバーで一時点灯した IF チップを追跡する配列。
      // clearHighlight でこの配列だけを走査して解除する（毎 mouseleave の
      // document.querySelectorAll('.if-chip.hover-chip-hl') 全 DOM スキャンを回避。
      // 大規模 topology でチップが数千あってもホバー解除コストが O(点灯数) に収まる）。
      var _hoverChipHl = [];

      function highlight(deviceId) {
        // G2: ホバー中ノードに接続する IF チップを一時点灯する共通ヘルパー。
        // すでに点灯済み（クリック固定 or 選択ピン）のチップには hover-chip-hl を付けず触らない
        // ＝clearHighlight でホバー由来のみ安全に消える（固定/ピンを保護）。
        // IIFE スコープの _hoverChipHl をクロージャ参照するため highlight 内に定義している
        // （highlight の外に出すと _hoverChipHl を参照できない）。
        function _hoverLitChip(ifaceId) {
          if (!ifaceId) return;
          document.querySelectorAll('.if-chip[data-iface-id="' + CSS.escape(ifaceId) + '"]').forEach(function(chip) {
            if (!chip.classList.contains('highlighted')) {
              chip.classList.add('highlighted');
              chip.classList.add('hover-chip-hl');
              _hoverChipHl.push(chip);  // perf: clearHighlight でこの配列のみ走査
            }
          });
        }
        allNodes.forEach(function(n) {
          if (n.dataset.device === deviceId) {
            n.classList.add('highlighted');
          }
        });
        allLinks.forEach(function(l) {
          var aMatch = l.dataset.a === deviceId;
          var bMatch = l.dataset.b === deviceId;
          if (aMatch || bMatch) {
            l.classList.add('highlighted');
            // G2: link-edge 端点 IF チップもホバー点灯する（Physical/OSPF p2p 統一）
            if (aMatch) { _hoverLitChip(l.getAttribute('data-a-iface')); }
            if (bMatch) { _hoverLitChip(l.getAttribute('data-b-iface')); }
          }
        });
        // BGP セッション: 両端ノードいずれかが deviceId に一致するセッションを点灯
        allBgpSessions.forEach(function(s) {
          var aMatch = s.dataset.a === deviceId;
          var bMatch = s.dataset.b === deviceId;
          if (aMatch || bMatch) {
            s.classList.add('highlighted');
            // G2: bgp-session 端点 IF チップもホバー点灯する（BGP ビュー統一）
            if (aMatch) { _hoverLitChip(s.getAttribute('data-a-iface')); }
            if (bMatch) { _hoverLitChip(s.getAttribute('data-b-iface')); }
          }
        });
        // 共有 NW (seg-edge / segment-node): deviceId が接続する seg-edge を点灯し、
        // そのセグメントノードも一緒に点灯する
        var litSegIds = [];
        allSegEdges.forEach(function(s) {
          if (s.dataset.device === deviceId) {
            s.classList.add('highlighted');
            if (s.dataset.segId) { litSegIds.push(s.dataset.segId); }
            // ⑮: ホバー時、seg-edge のメンバー IF チップも一時点灯する（G2: ヘルパー統一）。
            _hoverLitChip(s.getAttribute('data-member-iface'));
          }
        });
        allSegmentNodes.forEach(function(sn) {
          if (litSegIds.indexOf(sn.dataset.segId) !== -1) {
            sn.classList.add('highlighted');
          }
        });
        _syncEdgeLabels();
      }

      function clearHighlight() {
        allNodes.forEach(function(n) { n.classList.remove('highlighted'); });
        // リンクの highlighted 除去:
        // _selectedLinks（IF行クリック固定）と _selectedStaticEdges（static経路固定）は保持
        // selection-edge-hl: ノードクリック選択由来の highlighted も保持（BGP/seg と対称化）
        allLinks.forEach(function(l) {
          var lid = l.getAttribute('data-link-id');
          if (!_selectedLinks.has(lid) && !_selectedStaticEdges.has(lid) && !l.classList.contains('selection-edge-hl')) {
            l.classList.remove('highlighted');
          }
        });
        // BGP セッション: クリック選択由来の selection-edge-hl を持つ要素は解除しない
        allBgpSessions.forEach(function(s) {
          if (!s.classList.contains('selection-edge-hl')) {
            s.classList.remove('highlighted');
          }
        });
        // 共有 NW の seg-edge / segment-node: 同様に selection-edge-hl 保護
        allSegEdges.forEach(function(s) {
          if (!s.classList.contains('selection-edge-hl')) {
            s.classList.remove('highlighted');
          }
        });
        allSegmentNodes.forEach(function(sn) {
          if (!sn.classList.contains('selection-edge-hl')) {
            sn.classList.remove('highlighted');
          }
        });
        // ⑮: ホバーで一時点灯した IF チップ（hover-chip-hl）のみ解除。
        // hover-chip-hl はホバー時に「未点灯だったチップ」にだけ付くため、
        // クリック固定チップ・選択ピン（selection-edge-hl）チップは保護される。
        // perf: 追跡配列 _hoverChipHl のみ走査（全 .if-chip の DOM スキャンを回避）。
        if (_hoverChipHl.length) {
          _hoverChipHl.forEach(function(chip) {
            // G1: クリック選択でピン留め（selection-edge-hl）されたチップは highlighted を保護。
            // hover-chip-hl マーカーのみ除去する（ホバー解除で選択ピンが誤って消える off-by-one を防止）。
            if (!chip.classList.contains('selection-edge-hl')) {
              chip.classList.remove('highlighted');
            }
            chip.classList.remove('hover-chip-hl');
          });
          _hoverChipHl = [];
        }
        _syncEdgeLabels();
      }

      // ノードホバー
      allNodes.forEach(function(node) {
        node.addEventListener('mouseover', function(e) {
          e.stopPropagation();
          clearHighlight();
          highlight(node.dataset.device);
        });
        node.addEventListener('mouseenter', function() {
          highlight(node.dataset.device);
        });
        node.addEventListener('mouseleave', function() {
          clearHighlight();
        });
      });

      // リンクホバー
      allLinks.forEach(function(link) {
        link.addEventListener('mouseover', function(e) {
          e.stopPropagation();
          clearHighlight();
          link.classList.add('highlighted');
          if (link.dataset.a) highlight(link.dataset.a);
          if (link.dataset.b) highlight(link.dataset.b);
        });
        link.addEventListener('mouseleave', function() {
          clearHighlight();
        });
      });

      // ノードクリックで選択強調（累積トグル対応・即時実行）
      allNodes.forEach(function(node) {
        node.addEventListener('click', function(e) {
          e.stopPropagation();
          var deviceId = node.dataset.device;
          var wasSelected = node.classList.contains('selected');
          if (wasSelected) {
            // トグル: 解除
            node.classList.remove('selected');
            var card = document.querySelector('.device-card[data-device="' + CSS.escape(deviceId) + '"]');
            if (card) card.classList.remove('selected');
            _selectedNodes.delete(deviceId);
          } else {
            // 累積選択
            node.classList.add('selected');
            var card = document.querySelector('.device-card[data-device="' + CSS.escape(deviceId) + '"]');
            if (card) {
              card.classList.add('selected');
              // F3: ノード選択でカードへ scrollIntoView しない（ページ/ペインのスクロールが
              // ResizeObserver 経由で図をパンさせ「選択すると図が動く」原因になっていた）。
              // 選択カードは _updateCardFilter() の絞り込みで表示されるため scroll は不要。
            }
            _selectedNodes.add(deviceId);
          }
          _updateCardFilter();
          // P2 #5: 複数ノード選択時にノード間エッジをハイライト
          _updateEdgeHighlightForSelection();
        });
      });

      // F6: 図の余白の選択解除はダブルクリックで行う。単クリック/ドラッグは
      // パン（container mousedown ドラッグ）に専有させ、誤解除を防ぐ。
      // ノード/エッジ/チップ等の上の dblclick はバブリングで到達しても解除しない
      // （ノードの click は stopPropagation 済みだが dblclick は伝播するため明示ガード）。
      document.getElementById('topology-svg').addEventListener('dblclick', function(e) {
        if (e.target.closest('.device-node, .if-chip, .bgp-session, .link-edge, .seg-edge, .segment-node')) return;
        clearSelection();
      });

      // _syncEdgeLabels: エッジラベル(bgp-badge/link-label)を、対応エッジが highlighted の
      // 時だけ label-shown で表示する（既定は CSS で非表示）。highlight/clear/選択 変化の末尾で呼ぶ。
      function _syncEdgeLabels() {
        document.querySelectorAll('.bgp-badge-group.label-shown, .link-label-group.label-shown')
          .forEach(function(g){ g.classList.remove('label-shown'); });
        document.querySelectorAll('.bgp-session.highlighted').forEach(function(e){
          var id = e.getAttribute('data-bgp-id');
          if (!id) return;
          var sel = '.bgp-badge-group[data-bgp-id=' + CSS.escape(id) + ']';
          document.querySelectorAll(sel)
            .forEach(function(g){ g.classList.add('label-shown'); });
        });
        document.querySelectorAll('.link-edge.highlighted').forEach(function(e){
          var lid = e.getAttribute('data-link-id');
          if (lid) {
            var sel = '.link-label-group[data-link-id=' + CSS.escape(lid) + ']';
            document.querySelectorAll(sel)
              .forEach(function(g){ g.classList.add('label-shown'); });
          } else {
            // data-link-id 無いエッジは data-a+data-b でフォールバック照合
            var a = e.getAttribute('data-a'); var b = e.getAttribute('data-b');
            if (a && b) {
              var sel2 = '.link-label-group[data-a=' + CSS.escape(a) + '][data-b=' + CSS.escape(b) + ']';
              document.querySelectorAll(sel2)
                .forEach(function(g){ g.classList.add('label-shown'); });
            }
          }
        });
      }
      // window に公開（_updateEdgeHighlightForSelection 等 IIFE 外からも呼べるように）
      window._syncEdgeLabels = _syncEdgeLabels;
    })();

    // ============================================================
    // レイヤートグル
    // ============================================================
    function handleLayerToggle(checkbox) {
      const layer = checkbox.dataset.layer;
      if (checkbox.checked) {
        document.body.classList.remove('hide-' + layer);
      } else {
        document.body.classList.add('hide-' + layer);
      }
    }

    // ============================================================
    // カード↔ノード双方向選択・複数累積トグル / IF行↔リンク連動
    // ============================================================
    // （_selectedNodes は先頭で初期化済み）
    var _selectedLinks = new Set();
    var _selectedStaticRows = new Set();    // #2: static 行 data-route-id 集合（行ごと独立累積）
    var _selectedStaticEdges = new Set();   // HC1: static 経路で固定中のエッジ link-id / seg-id 集合
    var _selectedStaticNodes = new Set();   // HC2: static 経路 next-hop 機器（手動選択と独立）
    var _selectedSegs = new Set();          // #7: seg-id set
    var _selectedBgp = new Set();           // #5: bgp-id set
    var _selectedOspf = new Set();          // #1B: ospf-id set

    // clearSelection: ノード選択(.selected)解除 + clearLinkHighlight() + _updateCardFilter()
    function clearSelection() {
      document.querySelectorAll('.device-node.selected').forEach(function(n) {
        n.classList.remove('selected');
      });
      document.querySelectorAll('.device-card.selected').forEach(function(c) {
        c.classList.remove('selected');
      });
      _selectedNodes.clear();
      // リンク・IF 行・static・セグメント・BGP ハイライトも同時解除
      clearLinkHighlight();
      // 多ノードC: カード絞り込みを同期
      _updateCardFilter();
      // MED-1: selection-edge-hl を確実クリア（_selectedNodes 空なので冒頭の全解除→early return）
      _updateEdgeHighlightForSelection();
    }

    // clearLinkHighlight: リンク/IF行/static経路/セグメント/BGP ハイライトを解除する。
    function clearLinkHighlight() {
      document.querySelectorAll('.link-edge.highlighted').forEach(function(l) {
        l.classList.remove('highlighted');
      });
      document.querySelectorAll('tr.highlighted').forEach(function(r) {
        r.classList.remove('highlighted');
      });
      _selectedLinks.clear();
      // #6: static ルート経路ハイライト解除
      document.querySelectorAll('[data-route-edge].highlighted').forEach(function(el) {
        el.classList.remove('highlighted');
      });
      // #2/#3: static 行マーキング解除（_selectedStaticRows + route-row-selected）
      document.querySelectorAll('tr.route-row-selected').forEach(function(r) {
        r.classList.remove('route-row-selected');
      });
      _selectedStaticRows.clear();
      _selectedStaticEdges.clear();
      // HC2: static 経路 next-hop ノードも解除
      document.querySelectorAll('.device-node.route-target').forEach(function(n) {
        n.classList.remove('route-target');
      });
      document.querySelectorAll('.device-card.route-target').forEach(function(c) {
        c.classList.remove('route-target');
      });
      _selectedStaticNodes.clear();
      // #7: セグメントハイライト解除
      document.querySelectorAll('[data-seg-id].highlighted').forEach(function(el) {
        el.classList.remove('highlighted');
      });
      _selectedSegs.clear();
      // #5: BGP ハイライト解除
      document.querySelectorAll('[data-bgp-id].highlighted').forEach(function(el) {
        el.classList.remove('highlighted');
      });
      _selectedBgp.clear();
      // #1B: OSPF ハイライト解除
      document.querySelectorAll('[data-ospf-id].highlighted').forEach(function(el) {
        el.classList.remove('highlighted');
      });
      _selectedOspf.clear();
    }

    // ============================================================
    // P2 #5: 複数ノード選択 → ノード間エッジ + BGP/OSPF 表行ハイライト（ビュー対応）
    // ============================================================
    // _updateEdgeHighlightForSelection: _selectedNodes に基づいて
    // 現ビュー（_currentView）に応じたエッジと関連表行を highlighted にする。
    // 選択ノードが1以下の場合はエッジハイライトを解除する。
    function _updateEdgeHighlightForSelection() {
      // まず既存の「選択由来」エッジハイライトをクリア（全ビュー共通）
      // （_selectedLinks・_selectedBgp の保持分は除外して選択由来分だけ解除）
      document.querySelectorAll('.bgp-session.selection-edge-hl').forEach(function(el) {
        el.classList.remove('highlighted');
        el.classList.remove('selection-edge-hl');
      });
      document.querySelectorAll('.link-edge.selection-edge-hl').forEach(function(el) {
        el.classList.remove('highlighted');
        el.classList.remove('selection-edge-hl');
      });
      document.querySelectorAll('tr.selection-edge-hl').forEach(function(row) {
        row.classList.remove('highlighted');
        row.classList.remove('selection-edge-hl');
      });
      // (2a) seg-edge / segment-node の選択由来ハイライトもクリア
      document.querySelectorAll('.seg-edge.selection-edge-hl, .segment-node.selection-edge-hl').forEach(function(el) {
        el.classList.remove('highlighted');
        el.classList.remove('selection-edge-hl');
      });
      // (2a-2) IF チップ（if-chip）の選択由来ハイライトをクリア
      document.querySelectorAll('.if-chip.selection-edge-hl').forEach(function(el) {
        el.classList.remove('highlighted');
        el.classList.remove('selection-edge-hl');
      });

      if (_selectedNodes.size <= 1) {
        if (typeof window._syncEdgeLabels === 'function') { window._syncEdgeLabels(); }
        return;
      }

      // (2b) 共有ネットワーク（multi-access セグメント）: 選択ノードが2つ以上属する
      // セグメントの seg-edge / segment-node / 関連表行を点灯する。
      // filterConnected の seg グルーピングと同型（data-seg-id でグルーピング）。
      function _highlightSharedSegments(scope) {
        var segToDevs = {};
        document.querySelectorAll(scope + ' .seg-edge[data-seg-id][data-device]').forEach(function(edge) {
          var segId = edge.getAttribute('data-seg-id');
          var dev = edge.getAttribute('data-device');
          if (!segToDevs[segId]) segToDevs[segId] = [];
          segToDevs[segId].push(dev);
        });
        Object.keys(segToDevs).forEach(function(segId) {
          var uniqueDevs = Array.from(new Set(segToDevs[segId]));
          var selCount = uniqueDevs.filter(function(d) { return _selectedNodes.has(d); }).length;
          if (selCount < 2) return;
          var esc = CSS.escape(segId);
          // セグメント配下の seg-edge / segment-node をまとめて取得し点灯
          var matched = document.querySelectorAll(scope + ' .seg-edge[data-seg-id="' + esc + '"], ' + scope + ' .segment-node[data-seg-id="' + esc + '"]');
          matched.forEach(function(el) {
            el.classList.add('highlighted');
            el.classList.add('selection-edge-hl');
            // ⑮/F2: seg-edge のメンバー IF チップ点灯は「選択ノードのメンバー」のみに限定する。
            // セグメント線/ノードは共有NW構造として全メンバー点灯のままだが、チップは
            // 選択した機器(data-device ∈ _selectedNodes)の IF だけ点灯する（非選択メンバーの
            // チップが点く誤動作の解消）。segment-node は data-member-iface を持たない。
            var memberIface = el.getAttribute('data-member-iface');
            var memberDev = el.getAttribute('data-device');
            if (memberIface && memberDev && _selectedNodes.has(memberDev)) {
              document.querySelectorAll('.if-chip[data-iface-id="' + CSS.escape(memberIface) + '"]').forEach(function(chip) {
                chip.classList.add('highlighted');
                chip.classList.add('selection-edge-hl');
              });
            }
          });
          // OSPF Networks 表行: matched から segment-node をフィルタして再利用（再クエリ不要）
          matched.forEach(function(sn) {
            if (!sn.classList.contains('segment-node')) return;
            var ospfId = sn.getAttribute('data-ospf-id');
            if (!ospfId) return;
            ospfId.split(' ').forEach(function(token) {
              if (!token) return;
              document.querySelectorAll('tr[data-ospf-id~="' + CSS.escape(token) + '"]').forEach(function(row) {
                row.classList.add('highlighted');
                row.classList.add('selection-edge-hl');
              });
            });
          });
          // Interfaces 表行: tr[data-seg-id=segId]（セグメントメンバーIF行）
          document.querySelectorAll('tr[data-seg-id="' + esc + '"]').forEach(function(row) {
            row.classList.add('highlighted');
            row.classList.add('selection-edge-hl');
          });
        });
      }

      if (_currentView === 'physical') {
        // physical ビュー: .view-physical スコープの .link-edge のみハイライト
        // BGP 表・OSPF 表には触らない。Interfaces 表行（data-link-id）も連動。
        document.querySelectorAll('.view-physical .link-edge[data-a][data-b]').forEach(function(el) {
          var a = el.getAttribute('data-a');
          var b = el.getAttribute('data-b');
          if (_selectedNodes.has(a) && _selectedNodes.has(b)) {
            el.classList.add('highlighted');
            el.classList.add('selection-edge-hl');
            // 対応する Interfaces 表行もハイライト（data-link-id）
            var linkId = el.getAttribute('data-link-id');
            if (linkId) {
              document.querySelectorAll('tr[data-link-id="' + CSS.escape(linkId) + '"]').forEach(function(row) {
                row.classList.add('highlighted');
                row.classList.add('selection-edge-hl');
              });
            }
            // 選択由来チップは selection-edge-hl を付与し _hoverChipHl には積まない（ホバー経路 _hoverLitChip とは
            // 付与クラス・解除機構が異なるため分離）。ホバー側のみ _hoverLitChip に集約済み。
            // 端点 IF チップ（if-chip）を点灯（data-a-iface / data-b-iface）
            var aIface = el.getAttribute('data-a-iface');
            var bIface = el.getAttribute('data-b-iface');
            if (aIface) {
              document.querySelectorAll('.if-chip[data-iface-id="' + CSS.escape(aIface) + '"]').forEach(function(chip) {
                chip.classList.add('highlighted');
                chip.classList.add('selection-edge-hl');
              });
            }
            if (bIface) {
              document.querySelectorAll('.if-chip[data-iface-id="' + CSS.escape(bIface) + '"]').forEach(function(chip) {
                chip.classList.add('highlighted');
                chip.classList.add('selection-edge-hl');
              });
            }
          }
        });
        // (2c) 共有セグメント点灯（physical）
        _highlightSharedSegments('.view-physical');

      } else if (_currentView === 'bgp') {
        // bgp ビュー: .view-bgp スコープの .bgp-session をハイライト + BGP 表行連動
        document.querySelectorAll('.view-bgp .bgp-session[data-a][data-b]').forEach(function(el) {
          var a = el.getAttribute('data-a');
          var b = el.getAttribute('data-b');
          if (_selectedNodes.has(a) && _selectedNodes.has(b)) {
            el.classList.add('highlighted');
            el.classList.add('selection-edge-hl');
            // 対応する BGP 表行もハイライト（data-bgp-id）
            var bgpId = el.getAttribute('data-bgp-id');
            if (bgpId) {
              var bgpAttr = 'data-bgp-id';
              document.querySelectorAll('tr[' + bgpAttr + '="' + CSS.escape(bgpId) + '"]').forEach(function(row) {
                row.classList.add('highlighted');
                row.classList.add('selection-edge-hl');
              });
            }
            // F1: セッション線端点の IF チップ（if-chip）を点灯（data-a-iface / data-b-iface）。
            // physical/ospf 分岐と同型。クリアは冒頭の .if-chip.selection-edge-hl 解除で対応。
            var aIface = el.getAttribute('data-a-iface');
            var bIface = el.getAttribute('data-b-iface');
            if (aIface) {
              document.querySelectorAll('.if-chip[data-iface-id="' + CSS.escape(aIface) + '"]').forEach(function(chip) {
                chip.classList.add('highlighted');
                chip.classList.add('selection-edge-hl');
              });
            }
            if (bIface) {
              document.querySelectorAll('.if-chip[data-iface-id="' + CSS.escape(bIface) + '"]').forEach(function(chip) {
                chip.classList.add('highlighted');
                chip.classList.add('selection-edge-hl');
              });
            }
          }
        });

      } else if (_currentView === 'ospf') {
        // ospf ビュー: .view-ospf スコープの .link-edge をハイライト + OSPF 表行連動
        // Interfaces 表行（data-link-id）も連動。
        document.querySelectorAll('.view-ospf .link-edge[data-a][data-b]').forEach(function(el) {
          var a = el.getAttribute('data-a');
          var b = el.getAttribute('data-b');
          if (_selectedNodes.has(a) && _selectedNodes.has(b)) {
            el.classList.add('highlighted');
            el.classList.add('selection-edge-hl');
            // 対応する OSPF 表行もハイライト（data-ospf-id トークンマッチ）
            var ospfId = el.getAttribute('data-ospf-id');
            if (ospfId) {
              ospfId.split(' ').forEach(function(token) {
                if (!token) return;
                document.querySelectorAll('tr[data-ospf-id~="' + CSS.escape(token) + '"]').forEach(function(row) {
                  row.classList.add('highlighted');
                  row.classList.add('selection-edge-hl');
                });
              });
            }
            // 対応する Interfaces 表行もハイライト（data-link-id）
            var linkId = el.getAttribute('data-link-id');
            if (linkId) {
              document.querySelectorAll('tr[data-link-id="' + CSS.escape(linkId) + '"]').forEach(function(row) {
                row.classList.add('highlighted');
                row.classList.add('selection-edge-hl');
              });
            }
            // ⑬: 端点 IF チップ（if-chip）を点灯（data-a-iface / data-b-iface）。
            // physical 分岐と同型。クリアは冒頭の .if-chip.selection-edge-hl 解除で対応。
            var aIface = el.getAttribute('data-a-iface');
            var bIface = el.getAttribute('data-b-iface');
            if (aIface) {
              document.querySelectorAll('.if-chip[data-iface-id="' + CSS.escape(aIface) + '"]').forEach(function(chip) {
                chip.classList.add('highlighted');
                chip.classList.add('selection-edge-hl');
              });
            }
            if (bIface) {
              document.querySelectorAll('.if-chip[data-iface-id="' + CSS.escape(bIface) + '"]').forEach(function(chip) {
                chip.classList.add('highlighted');
                chip.classList.add('selection-edge-hl');
              });
            }
          }
        });
        // (2d) 共有セグメント点灯（ospf）
        _highlightSharedSegments('.view-ospf');
      }
      // エッジラベル表示を highlighted 状態に同期する
      if (typeof window._syncEdgeLabels === 'function') { window._syncEdgeLabels(); }
    }

    // カード→ノード選択（カードクリックで対応ノードを selected 強調・累積トグル）
    (function() {
      document.querySelectorAll('.device-card').forEach(function(card) {
        card.addEventListener('click', function(e) {
          // IF 行クリックは別ハンドラが処理するので tr 上のクリックは除外
          if (e.target.closest('tr')) return;
          var deviceId = card.dataset.device;
          var wasCardSelected = card.classList.contains('selected');
          if (wasCardSelected) {
            // トグル: 選択解除
            card.classList.remove('selected');
            _selectedNodes.delete(deviceId);
            document.querySelectorAll('.device-node[data-device="' + CSS.escape(deviceId) + '"]')
              .forEach(function(n) { n.classList.remove('selected'); });
          } else {
            // 累積選択
            card.classList.add('selected');
            _selectedNodes.add(deviceId);
            document.querySelectorAll('.device-node[data-device="' + CSS.escape(deviceId) + '"]')
              .forEach(function(n) { n.classList.add('selected'); });
          }
          // 多ノードC: 選択変化をカード絞り込みに反映
          _updateCardFilter();
          // P2 #5: カードクリック時も複数選択エッジハイライトを更新
          _updateEdgeHighlightForSelection();
        });
      });
    })();

    // ============================================================
    // 修正8: toggle*Highlight の共通ヘルパー
    // ============================================================
    // _toggleSelection(id, selectedSet, dataAttr): CSS.escape 込みで data-{attr} 要素を
    // highlighted クラスでトグルし、selectedSet を更新する（挙動・クラス(.highlighted)不変）
    function _toggleSelection(id, selectedSet, dataAttr) {
      if (!id) return;
      var isHighlighted = selectedSet.has(id);
      var selector = '[' + dataAttr + '="' + CSS.escape(id) + '"]';
      if (isHighlighted) {
        selectedSet.delete(id);
        document.querySelectorAll(selector).forEach(function(el) {
          el.classList.remove('highlighted');
        });
      } else {
        selectedSet.add(id);
        document.querySelectorAll(selector).forEach(function(el) {
          el.classList.add('highlighted');
        });
      }
      // エッジラベル（bgp-badge / link-label）の表示を highlighted 状態と同期
      if (typeof window._syncEdgeLabels === 'function') { window._syncEdgeLabels(); }
    }

    // IF行↔リンク双方向ハイライト（トグル: 2回目クリックで解除）
    function toggleIfRowHighlight(linkId) {
      _toggleSelection(linkId, _selectedLinks, 'data-link-id');
    }

    // IF 行・リンクエッジ クリックイベントの登録
    (function() {
      document.querySelectorAll('tr[data-link-id]').forEach(function(row) {
        var linkId = row.getAttribute('data-link-id');
        if (!linkId) return;
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleIfRowHighlight(linkId);
        });
      });

      // リンクエッジクリックで対応 IF 行ハイライト
      document.querySelectorAll('.link-edge[data-link-id]').forEach(function(edge) {
        var linkId = edge.getAttribute('data-link-id');
        if (!linkId) return;
        edge.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleIfRowHighlight(linkId);
        });
      });
    })();

    // ============================================================
    // ノード表示フィルタ
    // ============================================================
    // （_hiddenNodes は先頭で初期化済み）

    // ④⑤ asToDevs / segToDevs2: DOM 構造は不変（クラスのみトグル）のため
    // setNodeVisibility 最初の呼び出し時に一度だけ構築してキャッシュする。
    // N 機器の selectAllNodes/clearAllNodes で O(N²) querySelectorAll を O(N) に削減。
    var _asToDevsCache = null;    // { asStr -> Set<deviceId> }
    var _segToDevs2Cache = null;  // { segId  -> Set<deviceId> }

    function _buildAsSegCaches() {
      _asToDevsCache = {};
      document.querySelectorAll('.device-node[data-as]').forEach(function(n) {
        var as = n.dataset.as; var dev = n.dataset.device;
        if (!as || !dev) return;
        if (!_asToDevsCache[as]) _asToDevsCache[as] = new Set();
        _asToDevsCache[as].add(dev);
      });
      _segToDevs2Cache = {};
      document.querySelectorAll('.seg-edge[data-seg-id][data-device]').forEach(function(e) {
        var seg = e.dataset.segId; var dev = e.dataset.device;
        if (!seg || !dev) return;
        if (!_segToDevs2Cache[seg]) _segToDevs2Cache[seg] = new Set();
        _segToDevs2Cache[seg].add(dev);
      });
    }

    function setNodeVisibility(deviceId, visible) {
      // 非表示デバイス集合を更新
      if (visible) {
        _hiddenNodes.delete(deviceId);
      } else {
        _hiddenNodes.add(deviceId);
      }

      // 全ビューのノードを制御（CSS.escape でセレクタインジェクション防御）
      document.querySelectorAll('.device-node[data-device="' + CSS.escape(deviceId) + '"]')
        .forEach(function(node) {
          node.classList.toggle('node-filtered', !visible);
        });

      // エッジの制御（全種別: link-edge / bgp-session / seg-edge）
      // link-edge: data-a / data-b 両端判定
      document.querySelectorAll('.link-edge').forEach(function(edge) {
        var a = edge.dataset.a;
        var b = edge.dataset.b;
        if (a === deviceId || b === deviceId) {
          var aHidden = _hiddenNodes.has(a);
          var bHidden = _hiddenNodes.has(b);
          // いずれかの端点が非表示なら隠す。両端が表示のときのみ表示に戻す
          edge.classList.toggle('node-filtered', aHidden || bHidden);
        }
      });

      // bgp-session: data-a / data-b 両端判定（svg.py で付与）
      document.querySelectorAll('.bgp-session').forEach(function(edge) {
        var a = edge.dataset.a;
        var b = edge.dataset.b;
        if (!a || !b) return;
        if (a === deviceId || b === deviceId) {
          var aHidden = _hiddenNodes.has(a);
          var bHidden = _hiddenNodes.has(b);
          edge.classList.toggle('node-filtered', aHidden || bHidden);
        }
      });

      // seg-edge: data-device で単端点デバイスに対応
      document.querySelectorAll('.seg-edge').forEach(function(edge) {
        var dev = edge.dataset.device;
        if (dev === deviceId) {
          edge.classList.toggle('node-filtered', !visible);
        }
      });

      // 分離ラベル群（z-order修正で別レイヤー化）: link-label-group / bgp-badge-group
      // 両端いずれかが非表示なら隠す（link-edge / bgp-session と同じロジック）
      document.querySelectorAll('.link-label-group[data-a][data-b], .bgp-badge-group[data-a][data-b]')
        .forEach(function(g) {
          var a = g.dataset.a;
          var b = g.dataset.b;
          if (a === deviceId || b === deviceId) {
            var aHidden = _hiddenNodes.has(a);
            var bHidden = _hiddenNodes.has(b);
            g.classList.toggle('node-filtered', aHidden || bHidden);
          }
        });

      // カードの制御
      var card = document.querySelector('.device-card[data-device="' + CSS.escape(deviceId) + '"]');
      if (card) {
        card.classList.toggle('node-filtered', !visible);
      }

      // ④ AS枠: AS の全メンバー device が非表示なら as-group-container と AS番号ラベルを隠す
      // キャッシュ未構築なら初回のみ構築（DOM 構造は不変）
      if (_asToDevsCache === null) { _buildAsSegCaches(); }
      Object.keys(_asToDevsCache).forEach(function(as) {
        var allHidden = Array.from(_asToDevsCache[as]).every(function(d) { return _hiddenNodes.has(d); });
        var esc = CSS.escape(as);
        document.querySelectorAll('.as-group-container[data-as="' + esc + '"], .as-group-label-group[data-as="' + esc + '"]').forEach(function(g) {
          g.classList.toggle('node-filtered', allHidden);
        });
      });

      // ⑤ Shared Network: セグメントの全メンバー device が非表示なら segment-node を隠す
      Object.keys(_segToDevs2Cache).forEach(function(seg) {
        var allHidden = Array.from(_segToDevs2Cache[seg]).every(function(d) { return _hiddenNodes.has(d); });
        var esc = CSS.escape(seg);
        document.querySelectorAll('.segment-node[data-seg-id="' + esc + '"]').forEach(function(sn) {
          sn.classList.toggle('node-filtered', allHidden);
        });
      });

    }

    function selectAllNodes() {
      document.querySelectorAll('.node-filter-cb').forEach(function(cb) {
        cb.checked = true;
        setNodeVisibility(cb.dataset.nodeFilter, true);
      });
    }

    function clearAllNodes() {
      document.querySelectorAll('.node-filter-cb').forEach(function(cb) {
        cb.checked = false;
        setNodeVisibility(cb.dataset.nodeFilter, false);
      });
    }

    // ノードフィルタ checkbox のイベントリスナー登録（DC5: onchange インライン不使用）
    (function() {
      document.querySelectorAll('.node-filter-cb').forEach(function(cb) {
        cb.addEventListener('change', function() {
          setNodeVisibility(cb.dataset.nodeFilter, cb.checked);
        });
      });
    })();

    // ============================================================
    // #2: Static Route 行クリック -> 行ごと独立・複数累積マーク
    // ============================================================
    // 設計:
    //   - _selectedStaticRows: data-route-id の集合（行ごと独立）
    //   - 行クリックで data-route-id をトグル（1行のみ route-row-selected を付け外し）
    //   - エッジ/next-hop ハイライトは _selectedStaticRows の和から再計算
    //   - 旧: data-route-edge 全行巻き込みは廃止

    // _applyStaticRowHighlights: _selectedStaticRows の現状から
    // エッジ highlighted + next-hop route-target を一括再計算する。
    function _applyStaticRowHighlights() {
      // まず全ての経路エッジ/next-hop ハイライトをクリア
      document.querySelectorAll('[data-link-id].highlighted').forEach(function(el) {
        if (_selectedStaticEdges.has(el.getAttribute('data-link-id'))) {
          el.classList.remove('highlighted');
        }
      });
      document.querySelectorAll('[data-seg-id].highlighted').forEach(function(el) {
        if (_selectedStaticEdges.has(el.getAttribute('data-seg-id'))) {
          el.classList.remove('highlighted');
        }
      });
      _selectedStaticEdges.clear();
      document.querySelectorAll('.device-node.route-target').forEach(function(n) {
        n.classList.remove('route-target');
      });
      document.querySelectorAll('.device-card.route-target').forEach(function(c) {
        c.classList.remove('route-target');
      });
      _selectedStaticNodes.clear();

      // 選択中の全行から route-edge / nexthop-device を収集して再点灯
      _selectedStaticRows.forEach(function(rowId) {
        var row = document.querySelector('tr[data-route-id="' + CSS.escape(rowId) + '"]');
        if (!row) return;
        var routeEdgeId = row.getAttribute('data-route-edge') || '';
        var nexthopDeviceId = row.getAttribute('data-route-nexthop-device') || '';
        if (routeEdgeId) {
          _selectedStaticEdges.add(routeEdgeId);
          document.querySelectorAll('[data-link-id="' + CSS.escape(routeEdgeId) + '"]').forEach(function(el) {
            el.classList.add('highlighted');
          });
          document.querySelectorAll('[data-seg-id="' + CSS.escape(routeEdgeId) + '"]').forEach(function(el) {
            el.classList.add('highlighted');
          });
        }
        if (nexthopDeviceId) {
          _selectedStaticNodes.add(nexthopDeviceId);
          document.querySelectorAll('.device-node[data-device="' + CSS.escape(nexthopDeviceId) + '"]').forEach(function(n) {
            n.classList.add('route-target');
          });
          var card = document.querySelector('.device-card[data-device="' + CSS.escape(nexthopDeviceId) + '"]');
          if (card) card.classList.add('route-target');
        }
      });
    }

    function toggleStaticRouteHighlight(routeId) {
      // routeId = data-route-id（例 "r1::0.0.0.0/0"）
      if (!routeId) return;
      var row = document.querySelector('tr[data-route-id="' + CSS.escape(routeId) + '"]');
      if (!row) return;
      var isSelected = _selectedStaticRows.has(routeId);
      if (isSelected) {
        _selectedStaticRows.delete(routeId);
        row.classList.remove('route-row-selected');
      } else {
        _selectedStaticRows.add(routeId);
        row.classList.add('route-row-selected');
        row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
      // エッジ/next-hop ハイライトを _selectedStaticRows の和から再計算
      _applyStaticRowHighlights();
    }

    // Static route 行クリックイベント登録（#2: data-route-id で1行特定）
    (function() {
      document.querySelectorAll('tr[data-route-id]').forEach(function(row) {
        var routeId = row.getAttribute('data-route-id');
        if (!routeId) return;
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleStaticRouteHighlight(routeId);
        });
      });
    })();

    // ============================================================
    // #7: セグメントノード / IF 行双方向ハイライト
    // ============================================================
    function toggleSegHighlight(segId) {
      if (!segId) return;
      var isHighlighted = _selectedSegs.has(segId);
      if (isHighlighted) {
        _selectedSegs.delete(segId);
        document.querySelectorAll('[data-seg-id="' + CSS.escape(segId) + '"]').forEach(function(el) {
          el.classList.remove('highlighted');
        });
      } else {
        _selectedSegs.add(segId);
        document.querySelectorAll('[data-seg-id="' + CSS.escape(segId) + '"]').forEach(function(el) {
          el.classList.add('highlighted');
        });
      }
      if (typeof window._syncEdgeLabels === 'function') { window._syncEdgeLabels(); }
    }

    // セグメントノード / seg-edge クリックイベント登録
    (function() {
      // segment-node <g> クリック
      document.querySelectorAll('.segment-node[data-seg-id]').forEach(function(node) {
        var segId = node.getAttribute('data-seg-id');
        if (!segId) return;
        node.style.cursor = 'pointer';
        node.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleSegHighlight(segId);
        });
      });

      // seg-edge <line> クリック
      document.querySelectorAll('.seg-edge[data-seg-id]').forEach(function(edge) {
        var segId = edge.getAttribute('data-seg-id');
        if (!segId) return;
        edge.style.cursor = 'pointer';
        edge.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleSegHighlight(segId);
        });
      });

      // IF 行クリック（data-seg-id を持つ行）
      document.querySelectorAll('tr[data-seg-id]').forEach(function(row) {
        var segId = row.getAttribute('data-seg-id');
        if (!segId) return;
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleSegHighlight(segId);
        });
      });
    })();

    // ============================================================
    // #5: BGP Session ↔ 表の双方向ハイライト
    // ============================================================
    function toggleBgpHighlight(bgpId) {
      _toggleSelection(bgpId, _selectedBgp, 'data-bgp-id');
    }

    // BGP セッション <g> クリック + BGP 行 <tr> クリックイベント登録
    (function() {
      // bgp-session SVG 要素クリック
      document.querySelectorAll('.bgp-session[data-bgp-id]').forEach(function(el) {
        var bgpId = el.getAttribute('data-bgp-id');
        if (!bgpId) return;
        el.style.cursor = 'pointer';
        el.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleBgpHighlight(bgpId);
        });
      });

      // BGP 行 <tr> クリック
      document.querySelectorAll('tr[data-bgp-id]').forEach(function(row) {
        var bgpId = row.getAttribute('data-bgp-id');
        if (!bgpId) return;
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleBgpHighlight(bgpId);
        });
      });
    })();

    // ============================================================
    // #1B: OSPF リンク/セグメント ↔ OSPF Networks 表の双方向ハイライト
    // ============================================================
    // Phase 3H: dual-stack 対応 token セレクタ版
    // - 統合エッジ data-ospf-id は空白区切り複数 token（例: "10.0.0.0/30 2001:db8:1::/127"）
    // - OSPF Networks 行は単一 token（例: "10.0.0.0/30" または "2001:db8:1::/127"）
    //
    // 双方向連動ルール:
    // - 行（単一 id）クリック → [data-ospf-id~="id"] で token 照合し統合エッジをハイライト
    // - 統合エッジ（複数 token）クリック → token を split して各行/要素を全ハイライト
    // - single-stack（単一 token）は ~= でも完全一致と同等に動作するため非回帰

    // _ospfHighlightToken: 単一 token id に対して [data-ospf-id~="id"] セレクタで
    // ハイライト/解除を実行し、_selectedOspf Set を更新する。
    // BGP/seg の _toggleSelection と独立した OSPF 専用実装。
    function _ospfHighlightToken(id, on) {
      if (!id) return;
      var selector = '[data-ospf-id~="' + CSS.escape(id) + '"]';
      document.querySelectorAll(selector).forEach(function(el) {
        if (on) {
          el.classList.add('highlighted');
        } else {
          el.classList.remove('highlighted');
        }
      });
    }

    // toggleOspfHighlight: ospfIdStr（空白区切り 1 or 複数 token）をトグルする。
    // - 行クリック時は単一 token（ospfId = "10.0.0.0/30"）
    // - エッジクリック時は複数 token（ospfId = "10.0.0.0/30 2001:db8:1::/127"）
    // どちらの場合も token 単位で _selectedOspf を更新し ~= で双方向連動する。
    function toggleOspfHighlight(ospfIdStr) {
      if (!ospfIdStr) return;
      var tokens = ospfIdStr.split(' ').filter(function(t) { return t.length > 0; });
      if (tokens.length === 0) return;

      // 全 token がハイライト済みかどうかを確認
      var allHighlighted = tokens.every(function(t) { return _selectedOspf.has(t); });

      if (allHighlighted) {
        // トグル: 全 token を解除
        tokens.forEach(function(t) {
          _selectedOspf.delete(t);
          _ospfHighlightToken(t, false);
        });
      } else {
        // ハイライト: 全 token を追加
        tokens.forEach(function(t) {
          _selectedOspf.add(t);
          _ospfHighlightToken(t, true);
        });
      }
      if (typeof window._syncEdgeLabels === 'function') { window._syncEdgeLabels(); }
    }

    // OSPF リンク・セグメント・OSPF Networks 行 クリックイベント登録
    (function() {
      // OSPF ビューの link-edge[data-ospf-id] クリック
      // Phase 3H: data-ospf-id は複数 token になりうる（統合エッジ）
      document.querySelectorAll('.link-edge[data-ospf-id]').forEach(function(el) {
        var ospfIdStr = el.getAttribute('data-ospf-id');
        if (!ospfIdStr) return;
        el.style.cursor = 'pointer';
        el.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleOspfHighlight(ospfIdStr);
        });
      });

      // OSPF セグメントノード クリック（セグメントは単一 token）
      document.querySelectorAll('.segment-node[data-ospf-id]').forEach(function(el) {
        var ospfIdStr = el.getAttribute('data-ospf-id');
        if (!ospfIdStr) return;
        el.style.cursor = 'pointer';
        el.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleOspfHighlight(ospfIdStr);
        });
      });

      // OSPF セグメントエッジ クリック（セグメントは単一 token）
      document.querySelectorAll('.seg-edge[data-ospf-id]').forEach(function(el) {
        var ospfIdStr = el.getAttribute('data-ospf-id');
        if (!ospfIdStr) return;
        el.style.cursor = 'pointer';
        el.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleOspfHighlight(ospfIdStr);
        });
      });

      // OSPF Networks 行 <tr>[data-ospf-id] クリック（行は単一 token）
      document.querySelectorAll('tr[data-ospf-id]').forEach(function(row) {
        var ospfIdStr = row.getAttribute('data-ospf-id');
        if (!ospfIdStr) return;
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleOspfHighlight(ospfIdStr);
        });
      });
    })();

    // ============================================================
    // 多ノードC: カード選択連動絞り込みトグル
    // ============================================================
    // _updateCardFilter: card-filter-toggle ON 時に _selectedNodes に基づいてカードを絞り込む。
    // _selectedNodes 変更・clearSelection 等の選択変化から呼び出す。
    function _updateCardFilter() {
      var cb = document.getElementById('card-filter-toggle');
      if (!cb || !cb.checked) {
        // OFF: 全カードを表示（card-unselected を除去）
        document.querySelectorAll('.device-card.card-unselected').forEach(function(c) {
          c.classList.remove('card-unselected');
        });
        return;
      }
      // ON: _selectedNodes の機器のカードのみ表示
      var visibleDevices = new Set(_selectedNodes);

      document.querySelectorAll('.device-card').forEach(function(card) {
        var dev = card.dataset.device || card.getAttribute('data-device');
        if (!dev) return;
        if (visibleDevices.size === 0 || visibleDevices.has(dev)) {
          card.classList.remove('card-unselected');
        } else {
          card.classList.add('card-unselected');
        }
      });
    }

    (function() {
      var cb = document.getElementById('card-filter-toggle');
      if (cb) {
        cb.addEventListener('change', _updateCardFilter);
        _updateCardFilter();
      }
    })();


    // ============================================================
    // P2 #1: IF チップ強調（toggleIfChipHighlight）
    // ============================================================
    // toggleIfChipHighlight(ifaceId): 全ビューの if-chip[data-iface-id] を
    // .highlighted でトグルする。iBGP/static 行の data-loopback-iface-id 連動も本関数が担う。
    function toggleIfChipHighlight(ifaceId) {
      if (!ifaceId) return;
      var escaped = CSS.escape(ifaceId);
      var chips = document.querySelectorAll('[data-iface-id="' + escaped + '"]');
      // A4: 非表示要素が先頭でも正しくトグルできるよう some() ベースに変更
      var isHighlighted = Array.from(chips).some(function(el) {
        return el.classList.contains('highlighted');
      });
      chips.forEach(function(el) {
        if (isHighlighted) {
          el.classList.remove('highlighted');
        } else {
          el.classList.add('highlighted');
        }
      });
    }

    // IF チップ（SVG <g class="if-chip">）クリック登録
    (function() {
      document.querySelectorAll('.if-chip[data-iface-id]').forEach(function(chip) {
        var ifaceId = chip.getAttribute('data-iface-id');
        if (!ifaceId) return;
        chip.style.cursor = 'pointer';
        chip.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleIfChipHighlight(ifaceId);
        });
      });

      // BGP/static 行（data-loopback-iface-id のみ持つ行）のクリック登録
      document.querySelectorAll('tr[data-loopback-iface-id]:not([data-iface-id])').forEach(function(row) {
        var loopbackIfaceId = row.getAttribute('data-loopback-iface-id');
        if (!loopbackIfaceId) return;
        row.style.cursor = 'pointer';
        row.addEventListener('click', function(e) {
          e.stopPropagation();
          toggleIfChipHighlight(loopbackIfaceId);
        });
      });
    })();

    // ============================================================
    // Round D: ミニマップ
    // ============================================================
    (function() {
      var minimap = document.getElementById('minimap');
      var minimapUse = document.getElementById('minimap-use');
      var minimapVp = document.getElementById('minimap-viewport');
      var minimapToggle = document.getElementById('minimap-toggle');

      // トグル非表示状態フラグ。true のとき #minimap-toggle で隠した状態を維持する。
      // _updateMinimap 内で参照し、applyTransform/selectView からの再呼び出しでも尊重する。
      var _mmHidden = false;

      // _updateMinimap: ミニマップの viewBox / <use> href / ビューポート矩形を最新状態に更新する。
      // 呼出タイミング: applyTransform()（ズーム/パン時）, selectView()（ビュー切替時）,
      //                 ページロード直後（window._updateMinimap = ... の直後）。
      // ミニマップ IIFE は zoom IIFE より後に評価されるため、applyTransform/selectView から
      // window._updateMinimap を存在チェックして呼ぶ（if (window._updateMinimap)）。
      function _updateMinimap() {
        try {
          if (!minimap || !minimapUse || !minimapVp) return;

          var viewEl = document.querySelector('.view-' + _currentView);
          if (!viewEl) {
            minimap.style.display = 'none';
            return;
          }

          // _mmHidden フラグを尊重: トグルで非表示にしていれば再表示しない
          minimap.style.display = _mmHidden ? 'none' : '';

          // ミニマップの viewBox を active ビューの data-bbox にセット
          var bbox = viewEl.getAttribute('data-bbox');
          if (bbox) {
            minimap.setAttribute('viewBox', bbox);
          }

          // <use> で active ビューグループを参照
          minimapUse.setAttribute('href', '#view-' + _currentView);
          minimapUse.setAttribute('xlink:href', '#view-' + _currentView);

          // ビューポート矩形: コンテンツ座標での可視領域を計算
          // 逆変換の根拠: スクリーン原点(0,0)はコンテンツ座標 -translateX/scale に対応する。
          // コンテンツ座標 x = (スクリーン座標 - translateX) / scale → x_origin = -translateX/scale
          // 可視幅 visW = コンテナ幅 cw / scale（スクリーン幅をコンテンツ座標スケールで割る）
          if (window._zoomState) {
            var z = window._zoomState;
            var c = document.getElementById('svg-container');
            if (!c) return;
            var cw = c.clientWidth || 800;
            var ch = c.clientHeight || 600;
            var visX = -z.translateX / z.scale;
            var visY = -z.translateY / z.scale;
            var visW = cw / z.scale;
            var visH = ch / z.scale;
            minimapVp.setAttribute('x', visX);
            minimapVp.setAttribute('y', visY);
            minimapVp.setAttribute('width', visW);
            minimapVp.setAttribute('height', visH);
          }
        } catch (err) {
          // ミニマップ更新エラーは無視（本体の動作を妨げない）
        }
      }

      // ミニマップ クリック/ドラッグで主ビューをパン
      if (minimap) {
        var _mmDragging = false;

        function _mmPanTo(e) {
          try {
            // getScreenCTM().inverse() でスクリーン座標→SVG内部コンテンツ座標へ変換する。
            // getScreenCTM(): SVG 要素のスクリーン CTM（カレント変換行列）を返す。
            // inverse() の逆行列を作り、createSVGPoint().matrixTransform() でスクリーン座標を
            // コンテンツ座標（ミニマップの viewBox 空間）に変換する。
            if (!minimap.getScreenCTM) return;
            var ctm = minimap.getScreenCTM();
            if (!ctm) return;
            var pt = minimap.createSVGPoint();
            pt.x = e.clientX;
            pt.y = e.clientY;
            var cpt = pt.matrixTransform(ctm.inverse());
            // クリック点(cpt)が画面中央に来るよう _panToContentPoint に委譲（中央寄せ算は共通ヘルパーに集約）
            _panToContentPoint(cpt.x, cpt.y);
          } catch (err) {
            // ガード: getScreenCTM 等が無い環境でもクラッシュしない
          }
        }

        minimap.addEventListener('pointerdown', function(e) {
          _mmDragging = true;
          _mmPanTo(e);
          e.preventDefault();
        });

        minimap.addEventListener('pointermove', function(e) {
          if (_mmDragging) { _mmPanTo(e); }
        });

        document.addEventListener('pointerup', function() {
          _mmDragging = false;
        });
      }

      // ミニマップ 表示/非表示トグル
      // _mmHidden フラグを更新して _updateMinimap を呼ぶことで状態を一元管理する
      if (minimapToggle) {
        minimapToggle.addEventListener('click', function(e) {
          e.stopPropagation();
          if (!minimap) return;
          _mmHidden = !_mmHidden;
          _updateMinimap();
        });
      }

      // window に公開（applyTransform / selectView IIFE から呼べるように）
      // ミニマップ IIFE は zoom IIFE より後に評価されるため、zoom IIFE 内の呼び出し元は
      // if (window._updateMinimap) で存在チェックしている（IIFE 評価順の依存を回避）。
      window._updateMinimap = _updateMinimap;

      // 即時初期化: DOM 構築済みなら DOMContentLoaded を待たずに初回更新を実行する。
      // 内部 try/catch により DOM 未準備でも安全（エラーは無視される）。
      _updateMinimap();

      // DOMContentLoaded 後にも再更新（二重呼び出しは冪等なため問題なし）
      document.addEventListener('DOMContentLoaded', function() {
        if (window._updateMinimap) { window._updateMinimap(); }
      });
    })();\
"""


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
