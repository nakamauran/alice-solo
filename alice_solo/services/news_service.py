"""新聞。RSS を取って HTML を1枚作る。仕様書 v2.0 §6.2。

外部ライブラリ（feedparser 等）は使わず、標準の xml.etree で読む。
RSS 2.0 と Atom の両方を最小限だけ扱う。
失敗したら黙る。郵便受けに「届かなかった」とは積まない。
"""
from __future__ import annotations

import html
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import requests

from .. import config as C

_ATOM = "{http://www.w3.org/2005/Atom}"


def _text(node, *names) -> str:
    for n in names:
        found = node.find(n)
        if found is not None and (found.text or "").strip():
            return (found.text or "").strip()
    return ""


def _link(node) -> str:
    found = node.find("link")
    if found is not None:
        if (found.text or "").strip():
            return (found.text or "").strip()
        href = found.get("href")
        if href:
            return href
    found = node.find(f"{_ATOM}link")
    if found is not None and found.get("href"):
        return found.get("href")
    return ""


def parse_feed(xml_text: str, limit: int) -> list[dict]:
    """RSS/Atom から [{title, link}] を取り出す。壊れていたら空。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = root.findall(".//item")
    if not items:
        items = root.findall(f".//{_ATOM}entry")

    out: list[dict] = []
    for it in items[:limit]:
        title = _text(it, "title", f"{_ATOM}title")
        if not title:
            continue
        out.append({"title": title, "link": _link(it)})
    return out


class NewsService:
    def __init__(self, feeds: list[dict] | None = None,
                 out_path: Path | None = None):
        self.feeds = feeds or []
        self.out_path = Path(out_path) if out_path else C.NEWS_HTML

    # ------------------------------------------------------------ 判定

    def is_fresh(self, now: datetime | None = None) -> bool:
        """今日ぶんが既に生成済みか。"""
        now = now or datetime.now()
        if not self.out_path.exists():
            return False
        try:
            mtime = datetime.fromtimestamp(self.out_path.stat().st_mtime)
        except OSError:
            return False
        return mtime.date() == now.date()

    # ------------------------------------------------------------ 取得

    def build(self, now: datetime | None = None) -> bool:
        """通信する。UIスレッドから直接呼ばないこと。1件も取れなければ False。"""
        now = now or datetime.now()
        sections: list[tuple[str, list[dict]]] = []
        max_items = int(C.app_value("news.max_items", C.NEWS_MAX_ITEMS))
        timeout = C.app_value("news.timeout_sec", C.NEWS_TIMEOUT_SEC)
        per_feed = max(1, max_items // max(1, len(self.feeds)))

        for feed in self.feeds:
            url = feed.get("url")
            if not url:
                continue
            try:
                r = requests.get(url, timeout=timeout)
                r.raise_for_status()
                if not r.encoding:
                    r.encoding = r.apparent_encoding
                entries = parse_feed(r.text, per_feed)
            except Exception:
                entries = []
            if entries:
                sections.append((feed.get("label", ""), entries))

        if not sections:
            return False

        try:
            self.out_path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                dir=str(self.out_path.parent), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(render_html(sections, now))
                os.replace(tmp, self.out_path)
            except OSError:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                return False
        except OSError:
            return False
        return True


def render_html(sections: list[tuple[str, list[dict]]], now: datetime) -> str:
    """単純な表組み。スタイルはインラインで最低限。"""
    rows = []
    for label, entries in sections:
        rows.append(
            f'<tr><th colspan="2" style="text-align:left;padding:10px 8px 4px;'
            f'border-bottom:1px solid #f1b7a8;color:#5f4d45;">'
            f"{html.escape(label)}</th></tr>"
        )
        for i, e in enumerate(entries, 1):
            title = html.escape(e["title"])
            link = html.escape(e.get("link") or "")
            cell = f'<a href="{link}" style="color:#5f4d45;">{title}</a>' if link else title
            rows.append(
                f'<tr><td style="padding:4px 8px;color:#a08a80;width:2em;">{i}</td>'
                f'<td style="padding:4px 8px;">{cell}</td></tr>'
            )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja"><head><meta charset="utf-8">'
        f"<title>今日の新聞 {now:%Y-%m-%d}</title></head>"
        '<body style="background:#fffaf7;color:#5f4d45;'
        'font-family:\'Yu Gothic UI\',Meiryo,sans-serif;margin:24px;">'
        f'<h1 style="font-size:18px;">今日の新聞</h1>'
        f'<p style="color:#a08a80;font-size:12px;">{now:%Y年%m月%d日 %H:%M} 取得</p>'
        '<table style="border-collapse:collapse;max-width:720px;">'
        + "".join(rows)
        + "</table></body></html>"
    )
