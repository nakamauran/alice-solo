"""フェーズ4の検証: weather / news / pc_monitor / media_watcher。通信はしない。"""
import os, sys, json, tempfile
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["APPDATA"] = tempfile.mkdtemp()
from pathlib import Path

# リポジトリの場所はこのファイルからたどる。絶対パスを書くと
# 別の環境で動かない。
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from datetime import datetime
import importlib
import alice_solo.config as C; importlib.reload(C)

from alice_solo.services.weather_service import WeatherService, SLOTS
from alice_solo.services.news_service import NewsService, parse_feed, render_html
from alice_solo.services.pc_monitor import PCMonitor
from alice_solo.services.media_watcher import MediaWatcher

ok = fail = 0
def check(label, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  OK   {label} {extra}")
    else:    fail += 1; print(f"  FAIL {label} {extra}")

tmp = lambda n: Path(tempfile.mkdtemp()) / n

print("== weather: 応答の解釈 ==")
NOW = datetime(2026, 11, 27, 9, 0)
day = "2026-11-27"
times, temps, codes = [], [], []
for h in range(24):
    times.append(f"{day}T{h:02d}:00")
    temps.append(5.0 + h * 0.5)
    # 朝=晴れ, 昼=くもり, 夕=雨, 夜=雨
    codes.append(0 if h < 11 else 3 if h < 17 else 61)
raw = {
    "hourly": {"time": times, "temperature_2m": temps, "weather_code": codes},
    "current": {"temperature_2m": 9.0, "weather_code": 0},
}
parsed = WeatherService._parse(raw, NOW)
check("4区分すべて取れる", set(parsed["slots"]) == {"morning","daytime","evening","night"},
      sorted(parsed["slots"]))
check("朝は晴れ", parsed["slots"]["morning"]["key"] == "weather.sunny")
check("昼はくもり", parsed["slots"]["daytime"]["key"] == "weather.cloudy")
check("夕方は雨", parsed["slots"]["evening"]["key"] == "weather.rain")
check("日本語ラベル", parsed["slots"]["evening"]["text"] == "雨")
check("気温は平均して整数", isinstance(parsed["slots"]["morning"]["temp"], int))
check("現在天気", parsed["current"]["key"] == "weather.sunny")
check("空の応答は None", WeatherService._parse({"hourly": {}}, NOW) is None)
check("夜は24時で切る", [s for s in SLOTS if s[0]=="night"][0][3] == 24)

print("== weather: 参照と失敗時 ==")
w = WeatherService({"label":"福島県","latitude":37.75,"longitude":140.47}, path=tmp("w.json"))
check("控えが無ければ current は None", w.current() is None)
check("控えが無ければ forecast も None", w.forecast() is None)
check("天気キーも None", w.today_key() is None)
w.data = dict(parsed); w.data["date"] = "2026-11-27"
check("current が返る", w.current()["key"] == "weather.sunny")
f = w.forecast(NOW)   # 9時 -> 次は昼(11時)
check("このあとの天気は昼", f["key"] == "weather.cloudy", f.get("slot_label"))
f2 = w.forecast(datetime(2026,11,27,23,0))
check("夜遅くは夜の区分", f2["key"] == "weather.rain")
check("likes に渡す天気キー", w.today_key() == "weather.sunny")
w.set_location({"label":"東京都","latitude":35.68,"longitude":139.69})
check("地点を変えたら控えを捨てる", w.data == {})

print("== news: RSS/Atom の解釈 ==")
rss = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>記事A</title><link>https://example.com/a</link></item>
<item><title>記事B</title><link>https://example.com/b</link></item>
<item><title>記事C</title><link>https://example.com/c</link></item>
</channel></rss>"""
got = parse_feed(rss, 2)
check("RSS を読める", len(got) == 2 and got[0]["title"] == "記事A", got)
atom = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Atom記事</title><link href="https://example.com/x"/></entry>
</feed>"""
got = parse_feed(atom, 5)
check("Atom も読める", got and got[0]["link"] == "https://example.com/x", got)
check("壊れたXMLは空", parse_feed("<<<not xml", 5) == [])
check("タイトル無しは捨てる",
      parse_feed('<rss><channel><item><link>u</link></item></channel></rss>', 5) == [])

print("== news: HTML 生成 ==")
html_out = render_html([("NHK 主要", [{"title":"<危険>な記事","link":"https://e.com/1"}])], NOW)
check("DOCTYPE がある", html_out.startswith("<!DOCTYPE html>"))
check("HTMLエスケープされる", "&lt;危険&gt;" in html_out)
check("リンクが張られる", 'href="https://e.com/1"' in html_out)
check("日付が入る", "2026年11月27日" in html_out)

print("== news: 鮮度判定 ==")
out = tmp("news.html")
n = NewsService([], out_path=out)
check("未生成なら fresh でない", not n.is_fresh(datetime.now()))
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("x", encoding="utf-8")
check("今日書いたら fresh", n.is_fresh(datetime.now()))
check("別の日なら fresh でない", not n.is_fresh(datetime(2026, 1, 1)))
check("フィード0件なら build は False", n.build(NOW) is False)

print("== pc_monitor ==")
m = PCMonitor({"cpu_warn": 85, "mem_warn": 85, "disk_warn": 90})
snap = m.measure()
if m.available:
    check("3項目そろう", {"cpu","mem","disk"} <= set(snap), sorted(snap))
    check("診断は真偽3つ", set(snap["diagnostics"]) == {"cpu","mem","disk"})
    check("値は0-100", all(0 <= snap[k] <= 100 for k in ("cpu","mem","disk")),
          {k: snap[k] for k in ("cpu","mem","disk")})
else:
    check("psutil 不在でも空辞書を返すだけ", snap == {})
low = PCMonitor({"cpu_warn": 0, "mem_warn": 0, "disk_warn": 0})
low.measure()
check("しきい値0なら異常と判定", not low.is_healthy() or not low.available)
check("snapshot は測り直さず最後の値", m.snapshot() == snap or not m.available)

print("== media_watcher ==")
mw = MediaWatcher(enabled=True)
check("Windows以外では無効", (sys.platform == "win32") or (mw.available is False))
check("無効でも poll は空辞書", mw.poll() == {})
check("now_playing も空", mw.now_playing() == {})
check("HUD用の文字列も空", mw.display_text() == "")
mw2 = MediaWatcher(enabled=False)
check("設定で切れる", mw2.available is False)
mw2._last = {"title": "夜に駆ける", "artist": "YOASOBI"}
check("表示文字列の組み立て", mw2.display_text() == "YOASOBI - 夜に駆ける")

print(f"\n{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
