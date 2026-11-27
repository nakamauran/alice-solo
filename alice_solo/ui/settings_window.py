"""設定ウィンドウ。仕様書 v2.0 §9.3。

原型クライアントの settings_window.py と同じ作りにしてある。
縦に伸びるのでスクロール領域に入れ、変更は即時反映・即時保存する
（OK/キャンセルを持たない）。

Solo 版で変えたところ:
  - 主役2人ぶんのサイズ -> 1キャラぶん（キャラ切り替え廃止）
  - シノのサイズ -> 削除
  - 左手デバイスのショートカット -> 削除
  - 表示名・一人称・キャラクターパック・天気の地域を追加
"""
from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .. import __version__
from .. import autostart
from .. import backup
from .. import config as C
from .. import locations
from .theme import (
    DEFAULT_THEME, PRESETS, THEME_LABELS, apply_preset, build_stylesheet,
    load_theme, save_theme,
)


class _ColorSwatchButton(QtWidgets.QPushButton):
    """クリックで QColorDialog を開く色見本ボタン。"""

    color_changed = QtCore.Signal(str)

    def __init__(self, color_hex: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self._set_color(color_hex)
        self.clicked.connect(self._on_click)

    def _set_color(self, color_hex: str) -> None:
        self._color = color_hex
        self.setStyleSheet(
            f"background-color: {color_hex}; border: 1px solid #888; border-radius: 4px;"
        )

    def _on_click(self) -> None:
        chosen = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(self._color), self, "色を選択"
        )
        if chosen.isValid():
            self._set_color(chosen.name())
            self.color_changed.emit(chosen.name())


class SettingsWindow(QtWidgets.QWidget):
    scale_changed = QtCore.Signal(float)
    mailbox_scale_changed = QtCore.Signal(float)
    character_changed = QtCore.Signal(dict)     # display_name / first_person
    pack_changed = QtCore.Signal(str)
    weather_changed = QtCore.Signal(dict)
    hud_visibility_changed = QtCore.Signal(bool)
    theme_changed = QtCore.Signal(dict)      # 配色が変わったとき（HUD の再読込用）
    mailbox_mode_changed = QtCore.Signal(str)

    def __init__(self, user_config, parent=None):
        super().__init__(None)
        self.cfg = user_config
        self.theme = load_theme()

        # 緯度経度スピンの変更を 500ms デバウンスしてから確定する
        self._coord_timer = QtCore.QTimer(self)
        self._coord_timer.setSingleShot(True)
        self._coord_timer.setInterval(500)
        self._coord_timer.timeout.connect(self._commit_weather_from_coords)

        self.setWindowTitle("設定")
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowStaysOnTopHint)
        self.resize(400, 560)
        self.setMinimumSize(360, 320)

        # 縦1枚だと天気の地域が埋もれるのでタブに分ける（§7.1）
        self.tabs = QtWidgets.QTabWidget(self)
        self.tabs.addTab(self._make_tab(self._build_character), "キャラクター")
        self.tabs.addTab(self._make_tab(self._build_size,
                                        self._build_display,
                                        self._build_palette), "表示")
        self.tabs.addTab(self._make_tab(self._build_weather), "天気")
        self.tabs.addTab(self._make_tab(self._build_data), "データ")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(self.tabs)

    def _make_tab(self, *builders) -> QtWidgets.QWidget:
        """区画を縦に積んだタブを1枚作る。中身はスクロールできる。"""
        inner = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(inner)
        layout.setSpacing(6)
        for i, build in enumerate(builders):
            if i:
                layout.addSpacing(10)
            build(layout)
        layout.addStretch(1)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        scroll.setWidget(inner)
        return scroll

    # ------------------------------------------------------------ キャラクター

    def _build_character(self, layout: QtWidgets.QVBoxLayout) -> None:
        note = QtWidgets.QLabel(
            "Alice＝製品名、こゆき＝既定キャラクターです。", self
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(6)
        layout.addWidget(QtWidgets.QLabel("👤 キャラクター", self))

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft)

        self.pack_combo = QtWidgets.QComboBox(self)
        for name in self._available_packs():
            self.pack_combo.addItem(name)
        cur = self.cfg.character_pack
        idx = self.pack_combo.findText(cur)
        if idx >= 0:
            self.pack_combo.setCurrentIndex(idx)
        self.pack_combo.currentTextChanged.connect(self._on_pack_changed)
        form.addRow("パック", self.pack_combo)

        self.name_edit = QtWidgets.QLineEdit(self)
        self.name_edit.setPlaceholderText("パックの既定を使う")
        self.name_edit.setText(self.cfg.get("display_name") or "")
        self.name_edit.editingFinished.connect(self._on_character_edited)
        form.addRow("表示名", self.name_edit)

        self.first_person_edit = QtWidgets.QLineEdit(self)
        self.first_person_edit.setPlaceholderText("パックの既定を使う")
        self.first_person_edit.setText(self.cfg.get("first_person") or "")
        self.first_person_edit.editingFinished.connect(self._on_character_edited)
        form.addRow("一人称", self.first_person_edit)

        layout.addLayout(form)

        note = QtWidgets.QLabel(
            "空欄にするとパックの既定値に戻ります。\n"
            "パックを変えたときは再起動してください。", self
        )
        note.setWordWrap(True)
        layout.addWidget(note)

    def _available_packs(self) -> list[str]:
        names: list[str] = []
        for base in (C.BUNDLED_CHARACTERS_DIR, C.USER_CHARACTERS_DIR):
            if not base.is_dir():
                continue
            for d in sorted(base.iterdir()):
                if (d / "sprites" / "layout.yaml").exists() and d.name not in names:
                    names.append(d.name)
        return names or ["koyuki"]

    def _on_pack_changed(self, name: str) -> None:
        self.cfg.set("character_pack", name)
        self.pack_changed.emit(name)

    def _on_character_edited(self) -> None:
        name = self.name_edit.text().strip() or None
        me = self.first_person_edit.text().strip() or None
        self.cfg.set("display_name", name)
        self.cfg.set("first_person", me)
        self.character_changed.emit({"display_name": name, "first_person": me})

    # ------------------------------------------------------------ サイズ

    def _build_size(self, layout: QtWidgets.QVBoxLayout) -> None:
        layout.addWidget(QtWidgets.QLabel("🔧 立ち絵のサイズ", self))

        self.scale_label = QtWidgets.QLabel(self)
        self._update_scale_label(self.cfg.scale)
        layout.addWidget(self.scale_label)

        self.scale_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.scale_slider.setRange(int(C.SCALE_MIN * 100), int(C.SCALE_MAX * 100))
        self.scale_slider.setSingleStep(int(C.SCALE_STEP * 100))
        self.scale_slider.setPageStep(int(C.SCALE_STEP * 100) * 2)
        self.scale_slider.setValue(int(self.cfg.scale * 100))
        self.scale_slider.valueChanged.connect(self._on_scale_changed)
        layout.addWidget(self.scale_slider)

        btn = QtWidgets.QPushButton("リセット（100%）", self)
        btn.clicked.connect(lambda: self.scale_slider.setValue(100))
        layout.addWidget(btn)

        layout.addSpacing(8)
        layout.addWidget(QtWidgets.QLabel("📮 郵便受けのサイズ", self))

        try:
            mb = float(self.cfg.get("mailbox_scale", 1.0) or 1.0)
        except (TypeError, ValueError):
            mb = 1.0
        self.mailbox_label = QtWidgets.QLabel(self)
        self._update_mailbox_label(mb)
        layout.addWidget(self.mailbox_label)

        self.mailbox_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.mailbox_slider.setRange(60, 300)   # 66px を下回ると封筒が見分けにくい
        self.mailbox_slider.setSingleStep(10)
        self.mailbox_slider.setValue(int(mb * 100))
        self.mailbox_slider.valueChanged.connect(self._on_mailbox_scale_changed)
        layout.addWidget(self.mailbox_slider)

        btn2 = QtWidgets.QPushButton("リセット（100%）", self)
        btn2.clicked.connect(lambda: self.mailbox_slider.setValue(100))
        layout.addWidget(btn2)

    def _update_scale_label(self, scale: float) -> None:
        self.scale_label.setText(f"サイズ: {int(scale * 100)}%")

    def _on_scale_changed(self, value: int) -> None:
        scale = value / 100.0
        self._update_scale_label(scale)
        self.cfg.set("scale", scale)
        self.scale_changed.emit(scale)

    def _update_mailbox_label(self, scale: float) -> None:
        self.mailbox_label.setText(f"サイズ: {int(scale * 100)}%")

    def _on_mailbox_scale_changed(self, value: int) -> None:
        scale = value / 100.0
        self._update_mailbox_label(scale)
        self.cfg.set("mailbox_scale", scale)
        self.mailbox_scale_changed.emit(scale)

    # ------------------------------------------------------------ 天気

    def _build_weather(self, layout: QtWidgets.QVBoxLayout) -> None:
        self.weather_header = QtWidgets.QLabel("🌤 天気の地域", self)
        layout.addWidget(self.weather_header)

        cur = self.cfg.get("weather") or {}
        self.location_combo = QtWidgets.QComboBox(self)
        for label, _lat, _lon in locations.PREFECTURES:
            self.location_combo.addItem(label)
        self.location_combo.addItem(locations.CUSTOM_LABEL)
        if cur.get("label") == locations.CUSTOM_LABEL:
            self.location_combo.setCurrentIndex(len(locations.PREFECTURES))
        else:
            self.location_combo.setCurrentIndex(
                locations.index_of(cur.get("label", locations.DEFAULT_LABEL))
            )
        self.location_combo.currentIndexChanged.connect(self._on_location_changed)
        layout.addWidget(self.location_combo)

        # 県庁所在地から離れている場合に備えて、緯度経度も直接入れられるようにする
        self.coord_row = QtWidgets.QWidget(self)
        coord = QtWidgets.QFormLayout(self.coord_row)
        coord.setContentsMargins(0, 0, 0, 0)
        self.lat_spin = QtWidgets.QDoubleSpinBox(self)
        self.lat_spin.setRange(-90.0, 90.0)
        self.lat_spin.setDecimals(4)
        try:
            lat = float(cur.get("latitude", 35.6895))
        except (TypeError, ValueError):
            lat = 35.6895
        self.lat_spin.setValue(lat)
        self.lon_spin = QtWidgets.QDoubleSpinBox(self)
        self.lon_spin.setRange(-180.0, 180.0)
        self.lon_spin.setDecimals(4)
        try:
            lon = float(cur.get("longitude", 139.6917))
        except (TypeError, ValueError):
            lon = 139.6917
        self.lon_spin.setValue(lon)
        self.lat_spin.valueChanged.connect(self._on_coord_changed)
        self.lon_spin.valueChanged.connect(self._on_coord_changed)
        coord.addRow("緯度", self.lat_spin)
        coord.addRow("経度", self.lon_spin)
        layout.addWidget(self.coord_row)
        self.coord_row.setVisible(cur.get("label") == locations.CUSTOM_LABEL)

        self.weather_note = QtWidgets.QLabel("", self)
        self.weather_note.setWordWrap(True)
        layout.addWidget(self.weather_note)
        self._update_weather_note()

    def _update_weather_note(self) -> None:
        """まだ選ばれていないときだけ、選んでほしいことを出す。"""
        if self.cfg.get("weather_configured"):
            self.weather_note.setVisible(False)
            self.weather_header.setText("🌤 天気の地域")
            return
        self.weather_note.setVisible(True)
        self.weather_note.setText(
            "まだ選ばれていません。初期値の東京のままだと、"
            "お住まいの地域と違う天気を答えます。"
        )
        self.weather_note.setStyleSheet("color: #b4453c;")
        self.weather_header.setText("🌤 天気の地域  ← 未設定")

    def _on_location_changed(self, index: int) -> None:
        custom = index == len(locations.PREFECTURES)
        self.coord_row.setVisible(custom)
        if custom:
            data = {
                "label": locations.CUSTOM_LABEL,
                "latitude": float(self.lat_spin.value()),
                "longitude": float(self.lon_spin.value()),
            }
        elif 0 <= index < len(locations.PREFECTURES):
            label, lat, lon = locations.PREFECTURES[index]
            data = {"label": label, "latitude": lat, "longitude": lon}
            self.lat_spin.blockSignals(True)
            self.lon_spin.blockSignals(True)
            self.lat_spin.setValue(lat)
            self.lon_spin.setValue(lon)
            self.lat_spin.blockSignals(False)
            self.lon_spin.blockSignals(False)
        else:
            return
        self._commit_weather(data)

    def _on_coord_changed(self, _value: float) -> None:
        if not self.coord_row.isVisible():
            return
        # 500ms デバウンスしてから確定する（連打で _commit_weather が
        # 何度も走って保存と weather_changed が連発するのを防ぐ）
        self._coord_timer.start()

    def _commit_weather_from_coords(self) -> None:
        self._commit_weather({
            "label": locations.CUSTOM_LABEL,
            "latitude": float(self.lat_spin.value()),
            "longitude": float(self.lon_spin.value()),
        })

    def _commit_weather(self, data: dict) -> None:
        self.cfg.data["weather"] = data
        self.cfg.data["weather_configured"] = True
        self.cfg.save()
        self._update_weather_note()
        self.weather_changed.emit(data)

    def focus_weather(self) -> None:
        """初回起動時に地域を選んでもらうため、そこへスクロールする。"""
        tabs = getattr(self, "tabs", None)
        if tabs is not None:
            for i in range(tabs.count()):
                if tabs.tabText(i) == "天気":
                    tabs.setCurrentIndex(i)
                    break
        self.location_combo.setFocus(QtCore.Qt.OtherFocusReason)

    # ------------------------------------------------------------ 表示

    def _build_display(self, layout: QtWidgets.QVBoxLayout) -> None:
        layout.addWidget(QtWidgets.QLabel("🖥 表示", self))

        self.mailbox_mode = QtWidgets.QComboBox(self)
        self.mailbox_mode.addItem("常に表示", "always")
        self.mailbox_mode.addItem("未読があるときだけ", "unread_only")
        cur = self.cfg.get("mailbox_icon_mode", "always")
        self.mailbox_mode.setCurrentIndex(0 if cur == "always" else 1)
        self.mailbox_mode.currentIndexChanged.connect(self._on_mailbox_mode)

        form = QtWidgets.QFormLayout()
        form.addRow("郵便受けアイコン", self.mailbox_mode)
        layout.addLayout(form)

        self.hud_check = QtWidgets.QCheckBox("HUD を表示する", self)
        self.hud_check.setChecked(bool(self.cfg.get("hud_visible", True)))
        self.hud_check.toggled.connect(self._on_hud_toggled)
        layout.addWidget(self.hud_check)

    def _on_mailbox_mode(self, _index: int) -> None:
        mode = self.mailbox_mode.currentData() or "always"
        self.cfg.set("mailbox_icon_mode", mode)
        self.mailbox_mode_changed.emit(mode)

    def _on_hud_toggled(self, on: bool) -> None:
        self.cfg.set("hud_visible", bool(on))
        self.hud_visibility_changed.emit(bool(on))

    # ------------------------------------------------------------ 配色

    def _build_palette(self, layout: QtWidgets.QVBoxLayout) -> None:
        layout.addWidget(QtWidgets.QLabel("🎨 カラーパレット", self))

        # プリセット（§6.1）。押すと個別指定は上書きされる。
        preset_row = QtWidgets.QHBoxLayout()
        self.preset_buttons = {}
        for key, data in PRESETS.items():
            btn = QtWidgets.QPushButton(data["label"], self)
            btn.clicked.connect(lambda _=False, k=key: self._on_preset(k))
            self.preset_buttons[key] = btn
            preset_row.addWidget(btn)
        layout.addLayout(preset_row)

        self._swatches: dict[str, _ColorSwatchButton] = {}
        for key, label_text in THEME_LABELS.items():
            row = QtWidgets.QHBoxLayout()
            row.addWidget(QtWidgets.QLabel(label_text, self))
            row.addStretch(1)
            swatch = _ColorSwatchButton(self.theme.get(key, "#ffffff"), self)
            swatch.color_changed.connect(
                lambda color, k=key: self._on_color_changed(k, color)
            )
            self._swatches[key] = swatch
            row.addWidget(swatch)
            layout.addLayout(row)

        btn = QtWidgets.QPushButton("配色をリセット", self)
        btn.clicked.connect(self._on_reset_theme)
        layout.addWidget(btn)

    def _on_preset(self, name: str) -> None:
        self.theme = apply_preset(name)
        for key, swatch in getattr(self, "_swatches", {}).items():
            swatch._set_color(self.theme.get(key, "#ffffff"))
        self._apply_theme_live()
        self.theme_changed.emit(self.theme)

    def _on_color_changed(self, key: str, color_hex: str) -> None:
        self.theme[key] = color_hex
        save_theme(self.theme)
        self._apply_theme_live()
        self.theme_changed.emit(self.theme)

    def _on_reset_theme(self) -> None:
        self.theme = dict(DEFAULT_THEME)
        for key, swatch in self._swatches.items():
            swatch._set_color(self.theme[key])
        save_theme(self.theme)
        self._apply_theme_live()

    def _apply_theme_live(self) -> None:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(self.theme))
        self.theme_changed.emit(dict(self.theme))

    # ------------------------------------------------------------ データ

    def _build_data(self, layout: QtWidgets.QVBoxLayout) -> None:
        ver = QtWidgets.QLabel(f"Alice Solo {__version__}", self)
        ver.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(ver)

        self.autostart_check = QtWidgets.QCheckBox("Windows の起動時に開く", self)
        self.autostart_check.setChecked(
            bool(self.cfg.get("autostart", False)) or autostart.is_enabled()
        )
        self.autostart_check.toggled.connect(self._on_autostart)
        layout.addWidget(self.autostart_check)

        self.autostart_note = QtWidgets.QLabel("", self)
        self.autostart_note.setWordWrap(True)
        layout.addWidget(self.autostart_note)

        layout.addSpacing(10)
        layout.addWidget(QtWidgets.QLabel("💾 データ", self))

        path_label = QtWidgets.QLabel(str(C.DATA_DIR), self)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(path_label)

        btn_open = QtWidgets.QPushButton("保存フォルダを開く", self)
        btn_open.clicked.connect(self._open_data_dir)
        layout.addWidget(btn_open)

        btn_export = QtWidgets.QPushButton("バックアップを書き出す", self)
        btn_export.clicked.connect(self._export_backup)
        layout.addWidget(btn_export)

        btn_import = QtWidgets.QPushButton("バックアップから復元", self)
        btn_import.clicked.connect(self._import_backup)
        layout.addWidget(btn_import)

        btn_logs = QtWidgets.QPushButton("ログを開く", self)
        btn_logs.clicked.connect(self._open_logs)
        layout.addWidget(btn_logs)

    def _on_autostart(self, on: bool) -> None:
        """スタートアップのショートカットを作る／消す（§10）。

        作れなかった場合も設定値だけは残し、その旨を出す。
        """
        self.cfg.set("autostart", bool(on))
        ok = autostart.apply(bool(on))
        if ok:
            self.autostart_note.setText("")
            return
        self.autostart_note.setText(
            "ショートカットを作れませんでした。設定だけ保存しています。"
        )
        self.autostart_note.setStyleSheet(
            f"color: {load_theme().get('warn', '#b4453c')};"
        )

    def _open_data_dir(self) -> None:
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(C.DATA_DIR))
        )

    def _open_logs(self) -> None:
        from ..logging_setup import LOG_DIR
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(LOG_DIR)))

    def _export_backup(self) -> None:
        default = str(Path.home() / backup.default_name())
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "バックアップの保存先", default, "Alice backup (*.zip)"
        )
        if not path:
            return
        try:
            n = backup.export_to(Path(path))
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "書き出しに失敗", str(e))
            return
        QtWidgets.QMessageBox.information(
            self, "バックアップ", f"{n} 個のファイルを書き出しました。"
        )

    def _import_backup(self) -> None:
        """いまのデータを上書きする。戻せるよう、先に現状を控える。"""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "復元するバックアップ", str(Path.home()),
            "Alice backup (*.zip)"
        )
        if not path:
            return

        info = backup.inspect(Path(path))
        if not info["ok"]:
            QtWidgets.QMessageBox.warning(self, "復元できません", info["reason"])
            return

        answer = QtWidgets.QMessageBox.question(
            self, "バックアップから復元",
            f"{info['files']} 個のファイルで現在のデータを上書きします。\n"
            "バックアップに無いファイルはそのまま残ります。\n"
            "いまの状態は復元の前に控えを取りますが、\n"
            "好感度・日記・メモは上書きされます。続けますか。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return

        result = backup.restore_from(Path(path))
        if not result["ok"]:
            QtWidgets.QMessageBox.warning(self, "復元に失敗", result["reason"])
            return

        where = result["safety_copy"]
        note = f"\n\n復元前の控え:\n{where}" if where else ""
        QtWidgets.QMessageBox.information(
            self, "復元しました",
            f"{result['restored']} 個のファイルを戻しました。\n"
            f"読み込み済みの状態があるので、Alice を再起動してください。{note}"
        )

    # ------------------------------------------------------------ 閉じる

    def closeEvent(self, event) -> None:
        """常駐アプリなので閉じずに隠す。原型と同じ挙動。

        編集中の表示名・一人称はここで確定する（editingFinished 相当）。
        フォーカスが残ったまま閉じると editingFinished が来ないため。
        """
        name = self.name_edit.text().strip() or None
        me = self.first_person_edit.text().strip() or None
        if (name != self.cfg.get("display_name")
                or me != self.cfg.get("first_person")):
            self._on_character_edited()
        event.ignore()
        self.hide()
