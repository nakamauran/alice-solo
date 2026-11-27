"""Alice Solo エントリポイント。仕様書 v2.0。

動くもの:
  - 透過ウィンドウに立ち絵を表示、ドラッグで移動
  - 表示倍率は user_config.json の "scale"（設定画面から変更可）
  - 右クリックメニュー（チャット・設定・設定ファイルを開く・終了）
  - チャット入力 -> 意図判定 -> 枕/本題/尾ひれ -> 立ち絵切替と吹き出し
  - 好感度の増減と層（guard / accept / empathy）の切り替え
  - 30秒ごとの state tick、3分ごとの自発発話の抽選
  - 自我エンジン（likes / mood / topics）による気分・話題の反映
  - 外部連携（天気・新聞・PC監視・再生中の曲）
  - 周辺ウィンドウ（日記・メモ・タイマー・郵便受け・HUD・設定・デバッグ）
  - バックアップの書き出し・復元（設定画面から）
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import yaml
from PySide6.QtCore import QLockFile, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import config as C
from . import logging_setup
from .engine.affinity import Affinity
from .engine.dialogue_engine import DialogueEngine
from .engine.phrase_pool import PhrasePool
from .engine.self_engine import calendar_ja as cal
from .engine.self_engine import store
from .engine.self_engine.likes import Likes
from .engine.self_engine.mood import Mood
from .engine.self_engine.topics import Topics
from .engine.state_manager import StateManager
from .services.media_watcher import MediaWatcher
from .services.news_service import NewsService
from .services.pc_monitor import PCMonitor
from .services.weather_service import WeatherService
from .services.worker import run_async
from .db.local_store import LocalStore
from .ui.chat_window import ChatWindow
from .ui.debug_window import DebugWindow
from .ui.diary_window import DiaryWindow
from .ui.hud_window import HUDWindow
from .ui.mailbox_window import MailboxIcon, MailboxWindow
from .ui.notes_window import NotesWindow
from .ui.timer_window import TimerWindow
from .ui.settings_window import SettingsWindow
from .ui.theme import apply_theme
from .ui.vpet_window import VPetWindow
from .user_config import UserConfig


def resolve_pack_dir(pack_name: str) -> Path:
    """ユーザ追加パックを優先し、無ければ同梱パックを使う。"""
    user = C.USER_CHARACTERS_DIR / pack_name
    if (user / "sprites" / "layout.yaml").exists():
        return user
    return C.BUNDLED_CHARACTERS_DIR / pack_name


def load_character(pack_dir: Path, cfg: UserConfig) -> dict:
    """character.yaml を読み、user_config.json の上書きを当てる。"""
    data: dict = {}
    path = pack_dir / "character.yaml"
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, ValueError, yaml.YAMLError):
            data = {}
        if not isinstance(data, dict):
            data = {}
    data.setdefault("display_name", "こゆき")
    data.setdefault("first_person", "わたし")
    if cfg.get("display_name"):
        data["display_name"] = cfg.get("display_name")
    if cfg.get("first_person"):
        data["first_person"] = cfg.get("first_person")
    return data


class AliceSolo:
    def __init__(self, app: QApplication):
        self.app = app
        # ログは自我エンジンの初期化より前から取りたいので最初に作る
        self.debug = DebugWindow()
        self.debug.sink = self._log_to_file
        self.cfg = UserConfig()
        self.state = StateManager()
        self.state.tick()

        pack_dir = resolve_pack_dir(self.cfg.character_pack)
        self.character = load_character(pack_dir, self.cfg)

        self.pool = PhrasePool(pack_dir / "phrases.yaml")
        warn = self.pool.validate()
        if warn:
            print("[phrases.yaml 警告]\n" + warn.report(), file=sys.stderr)

        self.db = LocalStore()

        self.affinity = Affinity()
        launch = self.affinity.on_launch()
        try:
            self._launch_gap = int(launch.get("gap_days", 0) or 0)
        except (TypeError, ValueError):
            self._launch_gap = 0

        app_cfg = C.load_app_config()
        self.weather = WeatherService(self.cfg.get("weather"))
        # 前回見た天気キー。起動時は今のキーで初期化し、変わったときだけ
        # idle_phrase() に weather_changed=True を渡す（§5.3 ステップ2）。
        self._prev_weather_key = self.weather.today_key()
        self.news = NewsService((app_cfg.get("news") or {}).get("feeds") or [])
        self.pc = PCMonitor((app_cfg.get("monitor") or {}).get("thresholds"))
        self.media = MediaWatcher(
            bool((app_cfg.get("media") or {}).get("enabled", True))
        )

        self.likes = Likes(born=self.character.get("likes_base") or {})
        self.mood = Mood()
        self.topics = Topics(self.pool, pc_monitor=self.pc,
                             media_watcher=self.media, local_store=self.db)
        self._refresh_self_engine(launch_gap=launch.get("gap_days", 0))

        self.dialogue = DialogueEngine(
            self.pool, self.affinity, self.state, character=self.character,
            weather_provider=self.weather, mood=self.mood,
        )
        self.dialogue.memory_store = self.db      # 「覚えている」会話（§3.4）

        self.vpet = VPetWindow(pack_dir, user_scale=self.cfg.scale)
        self.chat = ChatWindow(self.character["display_name"])

        self.settings = SettingsWindow(self.cfg)
        self.settings.scale_changed.connect(self.vpet.apply_scale)
        self.settings.character_changed.connect(self._on_character_changed)
        self.settings.weather_changed.connect(self._on_weather_location_changed)

        self.hud = HUDWindow(self.pc, self.media, affinity=self.affinity,
                             mood=self.mood, likes=self.likes)
        self.mailbox = MailboxWindow(self.db)
        self.mailbox_icon = MailboxIcon(
            pack_dir, self.cfg.mailbox_scale
        )
        self.mailbox_icon.clicked.connect(self.open_mailbox)
        self.mailbox.read_changed.connect(self._refresh_mailbox_icon)
        self.settings.mailbox_scale_changed.connect(self.mailbox_icon.apply_scale)
        self.settings.hud_visibility_changed.connect(self._set_hud_visible)
        self.settings.mailbox_mode_changed.connect(
            lambda _m: self._refresh_mailbox_icon())
        self.settings.theme_changed.connect(lambda _t: self.hud.refresh_theme())

        self.diary = DiaryWindow(self.db)
        self.notes = NotesWindow(self.db)
        self.timer = TimerWindow(self.db)
        self.timer.finished.connect(self._on_timer_finished)

        self.vpet.on_open_debug = lambda: self._show(self.debug)
        self.vpet.on_toggle_hud = self.toggle_hud
        self.vpet.hud_is_visible = lambda: self.hud.isVisible()
        self.vpet.on_open_mailbox = self.open_mailbox
        self.vpet.on_open_diary = lambda: self._show(self.diary)
        self.vpet.on_open_notes = lambda: self._show(self.notes)
        self.vpet.on_open_timer = lambda: self._show(self.timer)
        self.vpet.on_open_chat = self.open_chat
        self.vpet.on_open_settings = self.open_settings
        self.vpet.on_open_config = self.open_config
        self.vpet.on_quit = self.quit
        self.chat.message_sent.connect(self.handle_message)

        self._restore_chat_log()
        self._first_run_setup()

        self._late_skip_counter = 0   # 深夜は2回に1回だけ抽選（§3.2）
        self._day_key = store.today_key()

        self.tick_timer = QTimer()
        self.tick_timer.timeout.connect(self.on_tick)
        self.tick_timer.start(C.STATE_TICK_MS)

        self.idle_timer = QTimer()
        self.idle_timer.timeout.connect(self.on_idle_check)
        self.idle_timer.start(C.IDLE_TALK_CHECK_MS)

        self.weather_timer = QTimer()
        self.weather_timer.timeout.connect(self.refresh_weather)
        self.weather_timer.start(C.WEATHER_REFRESH_INTERVAL_MS)

        self.metrics_timer = QTimer()
        self.metrics_timer.timeout.connect(self.refresh_metrics)
        self.metrics_timer.start(C.METRICS_INTERVAL_MS)

        self.media_timer = QTimer()
        self.media_timer.timeout.connect(self.refresh_media)
        if self.media.available:
            self.media_timer.start(C.MEDIA_INTERVAL_MS)

        self.news_timer = QTimer()
        self.news_timer.timeout.connect(self._news_check)
        self.news_timer.start(600_000)        # 10分ごとに時刻だけ見る

        self.talk_reset = QTimer()
        self.talk_reset.setSingleShot(True)
        self.talk_reset.timeout.connect(self._stop_talking)

        self.vpet.show()
        if self.mailbox_icon.available:
            self.mailbox_icon.show()
        self._refresh_mailbox_icon()
        if self.cfg.get("hud_visible", True):
            self.hud.show()

        # 起動直後の取得。UIを出してから走らせる
        QTimer.singleShot(200, self.refresh_weather)
        QTimer.singleShot(400, self.refresh_metrics)
        QTimer.singleShot(600, self._news_check)

        # 天気の地域がまだ選ばれていなければ、設定を開いてそこを示す。
        # 黙って東京の天気を答え続けるより、一度だけ尋ねるほうがよい。
        if not self.cfg.get("weather_configured"):
            QTimer.singleShot(800, lambda: self.open_settings(focus_weather=True))

        # 層が上がった日は、その日の最初の一言をそれにする
        # 初回だけ、使い方を一言だけ出す（§8）
        if not self.cfg.get("first_run_done"):
            QTimer.singleShot(2500, self._say_first_guide)

        if launch.get("tier_up"):
            QTimer.singleShot(1500, self._say_tier_up)

    def _restore_chat_log(self) -> None:
        """当日分の履歴をチャット窓に戻す（§5）。前日分は消す。"""
        try:
            self.db.purge_chat_log()
            for row in self.db.get_chat_log():
                self.chat.append_log_row(row.get("role", ""),
                                         row.get("text", ""),
                                         row.get("created_at", ""))
        except Exception:
            pass

    def _say_first_guide(self) -> None:
        """何を話せばいいか分からない初回の戸惑いを減らす。1回だけ。"""
        text = self.pool.pick(
            "first_guide", self.affinity.tier,
            name=self.character["display_name"],
            me=self.character["first_person"],
        )
        if text:
            self.vpet.say(text)
            self.debug.log("info", f"初回ガイド: {text}")
        self.cfg.set("first_run_done", True)

    # ------------------------------------------------------------ 初回起動

    def _first_run_setup(self) -> None:
        """初めて起動したときだけ通る。2回目以降は何もしない。"""
        if self.cfg.get("installed_at"):
            return
        self.cfg.data["installed_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.cfg.save()

        self.db.put_inbox(
            "system", "welcome", "はじめまして",
            "右クリックメニューから、チャット・日記・メモ・タイマー・設定が開けます。\n"
            "天気の地域は設定から選んでください。\n"
            f"データの保存先: {C.DATA_DIR}",
        )
        self.debug.log("info", f"初回起動。保存先を作りました: {C.DATA_DIR}")

    # ------------------------------------------------------------ ログ

    @staticmethod
    def _log_to_file(category: str, text: str) -> None:
        """デバッグ窓に出した行をログファイルにも残す。

        窓を開いていなくても、あとから落ちた原因をたどれるようにする。
        """
        logging_setup.get_logger().info("[%s] %s", category, text)

    # ------------------------------------------------------------ 画面

    def open_chat(self) -> None:
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()
        self.chat.focus_input()

    def open_settings(self, focus_weather: bool = False) -> None:
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()
        if focus_weather:
            self.settings.focus_weather()

    def _on_weather_location_changed(self, data: dict) -> None:
        self.weather.set_location(data)
        self.refresh_weather()

    def _on_character_changed(self, data: dict) -> None:
        """表示名・一人称の変更を即時反映する。"""
        pack_dir = resolve_pack_dir(self.cfg.character_pack)
        self.character = load_character(pack_dir, self.cfg)
        self.dialogue.character = self.character
        self.chat.set_display_name(self.character["display_name"])

    def _show(self, w) -> None:
        w.show()
        w.raise_()
        w.activateWindow()

    def toggle_hud(self, on: bool | None = None) -> None:
        """HUD の表示を切り替える。設定と右クリックメニューの両方から呼ばれる。

        状態は user_config.json に残すので、次の起動でも同じ状態で出る。
        """
        if on is None:
            on = not self.hud.isVisible()
        on = bool(on)
        if on:
            self.hud.refresh()
            self.hud.show()
            self.hud.raise_()
        else:
            self.hud.hide()

        if bool(self.cfg.get("hud_visible", True)) != on:
            self.cfg.set("hud_visible", on)
        # 設定ウィンドウのチェックと食い違わないようにする
        box = getattr(self.settings, "hud_check", None)
        if box is not None and box.isChecked() != on:
            box.blockSignals(True)
            box.setChecked(on)
            box.blockSignals(False)

    # 旧名。設定ウィンドウのシグナルから呼ばれる
    def _set_hud_visible(self, on: bool) -> None:
        self.toggle_hud(on)

    def open_hud(self) -> None:
        self.toggle_hud(True)

    def open_mailbox(self) -> None:
        self.mailbox.reload()
        self._show(self.mailbox)
        self._refresh_mailbox_icon()

    def _refresh_mailbox_icon(self) -> None:
        """未読の有無をアイコンに反映する。表示モードもここで見る（§8）。"""
        unread = self.db.unread_count() > 0
        self.mailbox_icon.set_unread(unread)
        if not self.mailbox_icon.available:
            return
        if self.cfg.get("mailbox_icon_mode", "always") == "unread_only":
            self.mailbox_icon.setVisible(unread)
        else:
            self.mailbox_icon.show()

    def _on_timer_finished(self, title: str, body: str) -> None:
        self._refresh_mailbox_icon()
        self.vpet.say(f"{title}：{body}")

    def open_config(self) -> None:
        """設定画面が出来るまでの暫定。user_config.json を既定アプリで開く。"""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.cfg.path)))

    def quit(self) -> None:
        """右クリックメニューから呼ばれる終了。

        QMenu.exec() は入れ子のイベントループを回しているので、その中から
        app.quit() を呼ぶと終了要求がメニューのループに吸われ、メインループ
        まで届かない（1回目はメニューが閉じるだけ、2回目でようやく終了する）。
        singleShot(0) でメニューが畳まれた直後まで遅らせる。
        """
        if getattr(self, "_quitting", False):
            return
        self._quitting = True
        QTimer.singleShot(0, self._shutdown)

    def _shutdown(self) -> None:
        """終了処理。保存・クローズで例外が出ても app.quit() には到達する。"""
        try:
            for timer in (self.tick_timer, self.idle_timer, self.talk_reset,
                          getattr(self, "weather_timer", None),
                          getattr(self, "news_timer", None),
                          getattr(self, "metrics_timer", None),
                          getattr(self, "media_timer", None)):
                if timer is not None:
                    try:
                        timer.stop()
                    except Exception:
                        pass

            for save in (self.state.save_if_dirty, self.diary.save,
                         self.notes.save):
                try:
                    save()
                except Exception:
                    pass
            try:
                self.db.close()
            except Exception:
                pass

            # closeEvent を握りつぶす窓があるので、閉じずに隠してから抜ける
            for w in (self.vpet, self.vpet.bubble, self.chat, self.settings,
                      self.hud, self.mailbox, self.mailbox_icon,
                      self.diary, self.notes, self.timer, self.debug):
                try:
                    w.hide()
                except Exception:
                    pass
        finally:
            try:
                QThreadPool.globalInstance().waitForDone()
            except Exception:
                pass
            self.app.quit()

    # ------------------------------------------------------------ 対話

    def handle_message(self, text: str) -> None:
        self.vpet.set_status("thinking")
        result = self.dialogue.handle_user_message(text)
        self.vpet.set_status(None)

        self.vpet.set_category(result["category"], talking=True)
        self.vpet.say(result["reply"])
        self.chat.append_reply(result["reply"])
        try:
            self.db.save_chat("user", text)
            self.db.save_chat("alice", result["reply"])
        except Exception:
            pass      # 履歴が残らなくても会話は続ける
        self.debug.log(
            "chat",
            f"\u300c{text}\u300d -> score={result['score']:+.2f} "
            f"category={result['category']} tier={result['tier']} "
            f"affinity={self.affinity.value:.1f} "
            f"satiety={self.state.state.satiety:.0f} "
            f"tension={self.state.state.tension:.0f} "
            f"boredom={self.state.state.boredom:.2f}"
        )
        self.talk_reset.start(C.utterance_display_ms(result["reply"]))
        self.state.save()

    def _stop_talking(self) -> None:
        self.vpet.set_category(self.vpet.category, talking=False)

    def _mark_tier_up_day(self) -> None:
        """層が上がった日だけ吹き出しの枠色を変える（§4）。翌日は戻す。"""
        self._tier_up_date = store.today_key()
        self.vpet.bubble.set_border_color(C.TIER_UP_BUBBLE_BORDER_COLOR)
        notify = getattr(self.dialogue, "notify_tier_up", None)
        if callable(notify):
            notify()

    def _clear_tier_up_mark_if_needed(self) -> None:
        if getattr(self, "_tier_up_date", None) \
                and self._tier_up_date != store.today_key():
            self._tier_up_date = None
            self.vpet.bubble.set_border_color(None)

    def _say_tier_up(self) -> None:
        text = self.pool.pick(
            "tier_up", self.affinity.tier,
            name=self.character["display_name"],
            me=self.character["first_person"],
        )
        if text:
            self.vpet.say(text)
        self._mark_tier_up_day()

    # ------------------------------------------------------------ 自我

    def _refresh_self_engine(self, launch_gap: int = 0) -> None:
        """日付が変わったときと起動時に、好き嫌いと気分を更新する。"""
        now = datetime.now()
        today = store.today_key(now)

        season = cal.season_key(now)
        events = cal.event_keys(now)
        weather = self._weather_key()

        touched = [k for k in ([weather, season] + events) if k]
        moved = self.likes.daily_update(touched, today)

        # 動きが大きかったものは「言うこと」として溜める
        for key in moved[:2]:
            text = self.pool.pick(
                "likes_changed", self.affinity.tier,
                thing=cal.label_of(key),
                me=self.character["first_person"],
                name=self.character["display_name"],
            )
            if text:
                self.likes.push_remark(key, text, today)

        like = self.likes.today_value(weather, season, events)
        self.mood.today(like=like, gap_days=launch_gap, now=now)

        # 溜めがあれば尾ひれに回す
        remark = self.likes.pop_remark(today) if self.likes.pending else None
        if remark:
            self.dialogue.push_remark(remark)

        self.debug.log(
            "self",
            f"mood={self.mood.label} bias={self.mood.talk_bias():+.2f} "
            f"like={like:+.3f} weather={weather} season={season} "
            f"events={events} moved={moved}"
        )

    def _weather_key(self) -> str | None:
        """likes に渡す天気キー。取得できていなければ None。"""
        return self.weather.today_key()

    # ------------------------------------------------------------ 外部取得

    def refresh_weather(self) -> None:
        """通信はワーカーに逃がす。失敗しても黙って前日の控えを使う。"""
        run_async(self.weather.fetch, on_done=self._on_weather_done,
                  on_fail=lambda _e: None)

    def _on_weather_done(self, ok: object) -> None:
        self.debug.log("net", f"天気の取得: {'成功' if ok else '失敗（控えを使う）'}"
                              f" key={self.weather.today_key()}")
        if ok:
            self._refresh_self_engine()      # 天気キーが変わると好き嫌いも動く

    def refresh_news(self) -> None:
        if self.news.is_fresh():
            return
        run_async(self.news.build, on_done=self._on_news_done,
                  on_fail=lambda _e: None)

    def _on_news_done(self, ok: object) -> None:
        """届いたら郵便受けに積む。失敗したときは黙る（仕様書 §6.2）。"""
        self.debug.log("net", f"新聞の生成: {'成功' if ok else '失敗'}")
        if not ok:
            return
        self.db.put_inbox(
            "news", store.today_key(), "新聞が届きました",
            "右クリックメニューの郵便受けから開けます。",
        )
        self._refresh_mailbox_icon()

    def refresh_metrics(self) -> None:
        self.pc.measure()
        self.hud.refresh()

    def refresh_media(self) -> None:
        """再生中の曲はワーカーで取る。終わったら HUD を更新する。"""
        started = self.media.poll_async(
            on_done=lambda _info: self.hud.refresh())
        if started is None:
            # 取得できない・取得中のときは手元の控えで HUD を更新するだけ
            self.hud.refresh()

    # ------------------------------------------------------------ 定期処理

    def on_tick(self) -> None:
        self.state.tick()
        self.state.save_if_dirty()
        self._check_day_rollover()

    def _check_day_rollover(self) -> None:
        today = store.today_key()
        if today == self._day_key:
            return
        self._day_key = today
        self._clear_tier_up_mark_if_needed()
        self.db.purge_inbox()
        self._refresh_self_engine()
        if self.affinity.on_day_rollover():
            self._say_tier_up()

    def _news_check(self) -> None:
        """朝9時を過ぎていて今日ぶんが無ければ作る。"""
        if datetime.now().hour >= C.NEWS_HOUR:
            self.refresh_news()

    def on_idle_check(self) -> None:
        """自発発話。mood と topics の材料で話題を選ぶ。"""
        now = datetime.now()

        # 深夜は声かけを間引く（§3.2）。起きている＝作業中のことが多く、
        # 3分おきに話しかけられると邪魔になる。
        is_late = cal.slot_of(now) == "late"
        if is_late:
            self._late_skip_counter += 1
            if self._late_skip_counter % C.IDLE_TALK_LATE_SKIP:
                self.debug.log("idle", "深夜のため今回は見送り")
                return

        # 深夜は talk_* の話題を出さず、挨拶と気分だけに絞る（§3.2）
        topic = None if is_late else self.topics.pick(
            self.affinity.tier, now,
            me=self.character["first_person"],
            name=self.character["display_name"],
        )
        # 天気変化の判定：前回見たキーと今のキーが違えば「変わった」。
        # 初回（前回キーなし）や取得失敗時は False。
        cur_key = self._weather_key()
        weather_changed = (
            self._prev_weather_key is not None
            and cur_key is not None
            and cur_key != self._prev_weather_key
        )
        if cur_key is not None:
            self._prev_weather_key = cur_key
        text = self.dialogue.idle_phrase(
            now,
            mood_label=self.mood.label,
            talk_bias=self.mood.talk_bias(),
            topic=topic,
            weather_changed=weather_changed,
            launch_gap=self._launch_gap,
        )
        if text:
            self.debug.log("idle", f"自発発話: {text}")
            self.vpet.set_category("neutral", talking=True)
            self.vpet.say(text)
            self.talk_reset.start(C.utterance_display_ms(text))
            # Now Playing の話題がそのまま発話として採用された場合のみ、
            # 「言った」記録を付ける。Topics.mark_said はエンジン担当が
            # 新設予定のため、無ければ何もしない（hasattr で確認する）。
            if topic is not None and text == topic:
                mark_said = getattr(self.topics, "mark_said", None)
                if callable(mark_said):
                    mark_said("talk_now_playing", now)
        else:
            self.debug.log("idle", f"黙った（topic={'あり' if topic else 'なし'}）")


# 単一インスタンス化のロック。main() で取得し、終了まで保持する。
_single_instance_lock: QLockFile | None = None


def main() -> int:
    global _single_instance_lock
    C.ensure_dirs()
    logging_setup.setup()
    logging_setup.purge_old()
    app = QApplication(sys.argv)
    app.setApplicationName("Alice Solo")
    app.setQuitOnLastWindowClosed(False)   # 主窓は Tool なので明示的に終了する
    apply_theme(app)                       # 配色は theme.json から

    icon_path = C.ASSETS_DIR / "ui" / "app_icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # 単一インスタンス化。ロックはアプリの生存期間中保持する。
    # Windows では %APPDATA%/Alice/alice.lock、Linux では DATA_DIR/alice.lock。
    lock = QLockFile(str(C.DATA_DIR / "alice.lock"))
    # PySide6 の tryLock は C++ と違って引数に既定値が無い。省くと TypeError。
    # 0 は「待たずに即判定」。
    if not lock.tryLock(0):
        # 強制終了などでロックが残っていることがある。持ち主のプロセスが
        # もういなければ掃除して、もう一度だけ試す。
        lock.setStaleLockTime(0)
        if lock.removeStaleLockFile() and lock.tryLock(0):
            logging_setup.get_logger().warning("古いロックを掃除して起動しました。")
        else:
            print("Alice Solo はすでに起動しています。", file=sys.stderr)
            QMessageBox.warning(
                None, "Alice Solo", "Alice Solo はすでに起動しています。")
            return 1
    _single_instance_lock = lock

    _alice = AliceSolo(app)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
