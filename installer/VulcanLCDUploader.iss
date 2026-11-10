; 火神智屏图传工具 —— Inno Setup 安装脚本
; 编译：ISCC.exe installer\VulcanLCDUploader.iss
; 产物：dist\installer\VulcanLCDUploader-Setup-<版本>.exe

#define AppName "火神智屏图传工具"
#define AppNameEn "Vulcan LCD Uploader"
#define AppVersion "1.0.0"
#define AppPublisher "本地工具（非官方，与七彩虹无隶属关系）"
#define AppExeName "VulcanLCDUploader.exe"
#define SourceDir "..\dist\VulcanLCDUploader"

[Setup]
; AppId 必须固定，后续升级才能覆盖安装而不是并存
AppId={{8F3B2C41-7D6A-4B8E-9E54-2A1C0D6F5B77}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} 安装程序
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}

; 装到当前用户目录：程序会在自己目录里写日志与配置，避免 Program Files 的权限问题
DefaultDirName={autopf}\VulcanLCDUploader
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; 主体
AppMutex=VulcanLCDUploaderSingleInstance
CloseApplications=yes
RestartApplications=no
OutputDir=..\dist\installer
OutputBaseFilename=VulcanLCDUploader-Setup-{#AppVersion}
SetupIconFile=..\build_assets\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVersion}
LicenseFile=..\LICENSE

; 压缩（100 MB 的 onedir 产物压到 ~35 MB）
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; 界面
WizardStyle=modern
DisableWelcomePage=no
ShowLanguageDialog=auto
; 现代向导的深色配色（与软件一致）
WizardSizePercent=110

; 系统要求
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "cn"; MessagesFile: "compiler:Default.isl,ChineseOverrides.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务："; Flags: checkedonce
Name: "autostart"; Description: "开机自动启动（之后可在软件的「文件」菜单里关闭）"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\卸载 {#AppName}"; Filename: "{uninstallexe}"

[Registry]
; 与软件自身的「开机自启动」写同一个值，卸载时一并清掉
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueType: string; ValueName: "VulcanLCDUploader"; \
    ValueData: """{app}\{#AppExeName}"""; \
    Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExeName}"; Description: "立即运行 {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 运行时产生的日志与状态文件，卸载时一并清理（不影响设备上的东西）
Type: filesandordirs; Name: "{app}\logs"
Type: files; Name: "{app}\ui_prefs.json"
Type: files; Name: "{app}\recent_files.json"
Type: files; Name: "{app}\device_state.json"
Type: filesandordirs; Name: "{app}\config"

[Code]
{ 安装前提示：官方软件若正在占用串口，本工具上传会失败 }
function InitializeSetup(): Boolean;
var
  Msg: String;
begin
  Result := True;
  Msg := '安装前提示：' + #13#10#13#10 +
         '1) 本工具通过 USB 虚拟串口与智屏通信，串口是独占的；' + #13#10 +
         '2) 如果 iGame Center 正在运行，上传时本工具会自动停掉它的服务；' + #13#10 +
         '3) 不需要官方软件的机器，可在「文件」菜单勾选「独立模式」。' + #13#10#13#10 +
         '是否继续安装？';
  if SuppressibleMsgBox(Msg, mbConfirmation, MB_YESNO, IDYES) = IDNO then
    Result := False;
end;

{ 卸载前把正在运行的实例关掉，避免文件占用 }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    Exec('taskkill.exe', '/F /IM {#AppExeName}', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  end;
end;
