"""HTML 組立（要件書 §8.1）。CSS/BODY/JS アセット + 埋め込み DATA/POS/VIEWS で自己完結 HTML を生成。"""
import json
import re

from .assets import _CSS, _BODY, _JS
from .data_transform import build_data
from .layout import compute_positions
from .tabs import build_tabs


def _json(obj):
    # </script> を <\/script> にエスケープし、埋め込み JSON が script ブロックを早期終了させないようにする
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _tabs_nav(tabs):
    btns = "".join(
        '<button data-view="%s">%s<span class="k">%d</span></button>'
        % (t["view"], t["label"], t["key"]) for t in tabs)
    return '<nav class="tabs" id="tabs">%s</nav>' % btns


def _inject_tabs(body, nav_html):
    """_BODY 中の <nav … id="tabs"> … </nav> を生成 nav に差し替える（§8.2）。"""
    # _BODY の実際のマークアップ: <nav class="tabs" id="tabs"> ... </nav>
    pattern = re.compile(r"<nav[^>]*\bid=\"tabs\"[^>]*>.*?</nav>", re.DOTALL)
    new_body, n = pattern.subn(nav_html, body, count=1)
    if n == 0:
        # 既存 nav が見つからなければ body 先頭に挿入（フォールバック）
        new_body = nav_html + body
    return new_body


def render_html(topo):
    """topology dict → 自己完結 HTML 文字列（決定的）。"""
    data = build_data(topo)
    pos = compute_positions(data)
    tabs = build_tabs(topo["routing"])
    views = [t["view"] for t in tabs]

    body = _inject_tabs(_BODY, _tabs_nav(tabs))

    # _BODY は <body> タグを含まない（<header> から始まる本文コンテンツのみ）
    head = ('<!doctype html>\n<html lang="ja"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Network Topology</title><style>%s</style></head><body>' % _CSS)
    # DATA / POS / VIEWS をそれぞれ独立した <script> タグに分け、
    # _embedded() の正規表現 `const NAME\s*=\s*(.*?);</script>` が正しく抽出できるようにする
    data_script = ('<script>const DATA=%s;</script>'
                   '<script>const POS=%s;</script>'
                   '<script>const VIEWS=%s;</script>'
                   % (_json(data), _json(pos), _json(views)))
    js = '<script>%s</script>' % _JS
    return head + body + data_script + js + '</body></html>'
