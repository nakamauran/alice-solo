; Inno Setup スクリプト。仕様書 §10。
;
;   1) pyinstaller alice-solo.spec
;   2) ISCC alice-solo.iss
;
; バージョンは tools/sync_version.py が alice_solo/__init__.py から
; ここへ書き写す。手で直さないこと（§10 の一元管理）。

#define AppName      "Alice Solo"
#define AppVersion   "1.0.1"
#define AppPublisher "nakamauran"
#define AppExeName   "AliceSolo.exe"
#define AppURL       "https://github.com/nakamauran/alice-solo"

[Setup]
AppId={{9C2F1C4E-7A3B-4C6D-9F1A-3D5E8B2A7C41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=AliceSolo-{#AppVersion}-setup
SetupIconFile=assets\ui\app_icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; 既定はユーザー単位のインストール。管理者権限を求めない。
;
; lowest にしないと既定が admin になり、{autopf} が Program Files、
; {userstartup} が「管理者アカウントの」スタートアップを指す。すると
; 自動起動のショートカットを作った本人と消す相手が食い違い、
; アンインストールで消し残す（ISCC も警告を出す）。
;
; PrivilegesRequiredOverridesAllowed は付けない。付けると「管理者モードで
; 走りうる」とみなされ、ISCC の UsedUserAreasWarning が消えない。
; このアプリは保存先も %APPDATA% でユーザー単位に閉じているので、
; 管理者インストールを許す意味がない。
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

; 起動したままインストール／アンインストールされることが多い。
; Restart Manager に掴んでいるプロセスを閉じさせる。
; 閉じたあと勝手に起こし直さない（常駐アプリなので利用者に任せる）。
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll
RestartApplications=no
; 二重起動の防止
SetupMutex=AliceSoloSetupMutex

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; Description: "デスクトップにショートカットを作る"; \
    GroupDescription: "追加のショートカット:"; Flags: unchecked

[Files]
; PyInstaller の onedir 出力を丸ごと入れる
Source: "dist\AliceSolo\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\AliceSolo\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; \
    Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; \
    Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 自動起動のショートカットは設定画面が作るもの。インストーラは知らないので
; ここで明示的に消す。
Type: files; Name: "{userstartup}\Alice Solo.lnk"
; PyInstaller の出力に加え、実行中にできた一時ファイルが残ることがある。
; フォルダごと片付ける。
Type: filesandordirs; Name: "{app}"

[Code]
// アンインストール時に、保存データを消すか尋ねる。
// 既定は「残す」。入れ直したときに好感度や日記が消えると困るため。
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{userappdata}\Alice');
    if DirExists(DataDir) then
    begin
      if MsgBox('保存データ（好感度・日記・メモ・設定）も削除しますか？'
                + #13#10 + DataDir + #13#10#13#10
                + '「いいえ」を選ぶと残ります。入れ直したときに続きから使えます。',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
