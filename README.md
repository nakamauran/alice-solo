# Alice Solo

Windows PC 単体で完結するデスクトップマスコット。ルールベース対話で、LLM は使わない。

> **名前について**：「Alice」は製品名、「こゆき」は既定のキャラクター名です。
> キャラクターパックを差し替えれば、別のキャラクターで動かせます。

## 導入

### インストーラ版（配布物を使う）

[Releases](https://github.com/nakamauran/alice-solo/releases) の
`AliceSolo-x.y.z-setup.exe` を実行してください。管理者権限は不要です。
アンインストール時に、保存データを残すか消すかを尋ねます。

### ソースから動かす

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

- Python 3.10 以上、Windows 10/11 を想定しています。
- 必須の依存は `requirements.txt` の4つだけです。
- 再生中の曲（Now Playing）を出したい場合のみ、
  `pip install -r requirements-optional.txt` を追加で実行してください。
  入れなくても本体は動き、HUD の Now Playing 欄が消えるだけです。

## 使い方

- 起動するとデスクトップにキャラクターが常駐します。右クリックメニューからチャット・設定・日記・メモ・タイマー・郵便受け・HUD を開けます。
- チャットに話しかけると、キーワードとその日の気分・好感度に応じて返事します。
- 自分から話しかけることもあります（時間帯の挨拶、天気の変化、久しぶりの挨拶、その日の気分、手元の話題など）。
- 設定画面で表示名・一人称・表示倍率・天気の地点・配色を変えられます。

## データの保存場所

すべての状態は `%APPDATA%\Alice\` 以下に保存されます（Linux では `~/.local/share/Alice/`）。

| ファイル | 内容 |
| --- | --- |
| `state.json` | 満腹度・テンション・退屈度・感情・挨拶の記録 |
| `user_config.json` | 表示名・一人称・倍率・天気の地点など |
| `theme.json` | 配色 |
| `window_pos.json` | 各窓の位置 |
| `local_store.db` | 郵便受け（新聞など） |
| `self/` | 好き嫌い・気分・天気の控え・好感度 |
| `news/today_news.html` | その日の新聞 |

同梱の `assets/` は読み取り専用です。実行時に書き換えません。

## バックアップ

設定画面の「データ」からバックアップの書き出し・復元ができます。

- 書き出し：保存フォルダの中身を zip にまとめます。
- 復元：zip に含まれるファイルを**上書き**します（zip に無いファイルは残ります。「置き換え」ではなく「上書き」です）。
- 復元前には自動で safety copy（復元直前の状態の zip）を作ります。

## 自動起動

設定画面の「データ」タブにある「Windows の起動時に開く」で切り替えます。
スタートアップフォルダ
（`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`）に
ショートカットを置く方式です。レジストリは触りません。
手で消したいときは、そのフォルダの `Alice Solo.lnk` を削除してください。

## バージョンの確認

設定画面の「データ」タブの先頭に出ます。
値の正本は `alice_solo/__init__.py` の `__version__` です。

## ビルド（配布物を作る）

```bat
python tools\sync_version.py
pyinstaller alice-solo.spec
ISCC alice-solo.iss
```

1. `sync_version.py` が `__init__.py` のバージョンを `alice-solo.iss` に書き写します。
2. `pyinstaller` が `dist\AliceSolo\` に onedir 形式で吐きます。
3. `ISCC`（Inno Setup）が `installer_output\` にインストーラを作ります。

アイコンを作り直したいときは `python tools\make_icon.py --preview` を実行してください。
`assets\characters\koyuki\sprites\normal.png` から `assets\ui\app_icon.ico` を生成します。

## キャラクターパック

`assets/characters/<パック名>/` が1つの単位です。設定画面の「キャラクター」
タブで切り替えます。

```
assets/characters/koyuki/
├── character.yaml      人格・生まれつきの好き嫌い
├── phrases.yaml        発話プール（3層ぶん）
└── sprites/
    ├── layout.yaml     どの感情にどの画像を使うか
    └── *.png           立ち絵
```

`%APPDATA%\Alice\characters\<パック名>\` に置いたものが優先されます。
同梱の `assets/` を書き換える必要はありません。

### 人格の3層

好感度によって口調が切り替わります。`phrases.yaml` の `tiers` がこれです。

| 層 | 好感度 | 口調 |
| --- | --- | --- |
| `guard` | 0–39 | 短文、素っ気ない |
| `accept` | 40–74 | 肯定から入る、柔らかい |
| `empathy` | 75–100 | 踏み込む、本音を見せる |

探索順は「いまの層 → `accept` → `shared`」です。`accept` だけ全キーを
埋めれば動きます。各キー5件以上にしてください（3件だと抽選の順番が
読めてしまいます）。

### 立ち絵

`sprites/layout.yaml` に、感情カテゴリとファイル名の対応を書きます。
登録していないカテゴリは `base` に落ちるので、全部そろえる必要はありません。

- 全差分を**同じキャンバスサイズ**にそろえてください。ずれるとキャラが跳ねます
- `base_content_height` には **base 1枚の中身の高さ**を書きます。差分ごとに
  測ると、感情が変わるたびに伸び縮みします

### 台詞を増やす

`phrases.yaml` を直接編集してください。差分ファイルからまとめて足したい
場合は `tools/merge_phrases.py` が使えます（既存の行は消さず、重複は
飛ばすので、何度実行しても増えません）。

## テスト

```bat
python tools\run_tests.py
```

`tests/` 以下をまとめて走らせます。pytest は使っていません。
各ファイルは単体でも実行できます。

## ライセンス

- **ソースコード**: MIT License（`LICENSE`）
- **`assets/` の素材**（立ち絵・アイコン・台詞・キャラクター設定）:
  再配布不可・個人利用のみ（`assets/LICENSE`）

コードは自由に参考にしてもらって構いませんが、立ち絵と台詞の転載はご遠慮ください。
自分のキャラクターで動かしたい場合は、`assets/characters/` に別のパックを
追加してください。作ったパックの権利は作成者のものです。
