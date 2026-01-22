; installer.iss

#define MyAppName      GetEnv("ZHIMO_APP_NAME")
#define MyAppVersion   GetEnv("ZHIMO_APP_VER")
#define MyExeName      GetEnv("ZHIMO_APP_EXE")
#define MyAppPublisher "ZhimoAI"
#define MyAppSrc       GetEnv("ZHIMO_APP_SRC")

[Setup]
AppId={{8D6D38A0-2AF3-4B6D-9B6B-3D8F86F1C123}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputBaseFilename={#MyAppName}_Setup_{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyExeName}

[Files]
Source: "{#MyAppSrc}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{commondesktop}\{#MyAppName}"; Filename: "{app}\{#MyExeName}"
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyExeName}"

[Run]
Filename: "{app}\{#MyExeName}"; Description: "运行 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function KillProcessByName(const ExeName: string): Boolean;
var
  ResultCode: Integer;
begin
  // /T 结束子进程，/F 强制；SW_HIDE 隐藏窗口
  Exec('taskkill', '/T /F /IM "' + ExeName + '"', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := True;
end;

function InitializeSetup(): Boolean;
begin
  // 覆盖安装时：强制关闭旧进程（避免文件占用导致覆盖失败）
  // 兼容你旧名字 AI_Assistant.exe
  KillProcessByName('{#MyExeName}');
  KillProcessByName('AI_Assistant.exe');
  Result := True;
end;
