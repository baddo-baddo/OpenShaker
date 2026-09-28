; OpenShaker installer (Inno Setup 6). build.bat compiles it with /DAppVersion=... /DBuildDir=...
; Per-user install: no administrator prompt, installs to %LOCALAPPDATA%\Programs\OpenShaker.

#define AppName "OpenShaker"
#define AppExe "OpenShaker.exe"
#define AppId "6F1E2C3B-8A47-4C5E-9D2B-3E7A1F0C5B84"
; the version lives only in openshaker/__init__.py; build.ps1 passes it in
#ifndef AppVersion
  #error Build with build.bat, which passes /DAppVersion from openshaker/__init__.py
#endif
#ifndef BuildDir
  #define BuildDir "..\build\dist\OpenShaker"
#endif

[Setup]
AppId={{{#AppId}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=baddo & Claude
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; one screen: the two tasks and an Install button (without the Ready page, the Tasks page's Next becomes
; Install), then setup closes and starts the app - no Welcome, folder, group, Ready or Finished pages
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename={#AppName}-Setup-{#AppVersion}
SetupIconFile=..\openshaker.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; the running app holds this mutex, so setup and the uninstaller ask the user to quit it first. Before
; that check, InitializeSetup / InitializeUninstall ask an installed copy to quit by itself (--quit).
AppMutex=OpenShakerRunning
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; both ticked: this page is the only question setup asks, and ticking is the user's consent to each
Name: "startup"; Description: "Start {#AppName} with &Windows (it waits in the notification area)"
Name: "desktopicon"; Description: "Create a &desktop shortcut"

[Files]
Source: "{#BuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; the startup entry the app itself reads and writes (same name, same command)
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --hidden"; Flags: uninsdeletevalue; Tasks: startup
; the entry an earlier version registered under its old name, so Windows never starts two copies
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "ButtKicker Haptics"; Flags: deletevalue dontcreatekey

[Run]
; starts the app as soon as the files are in (there is no Finished page to tick it on); a silent update
; (/SILENT, /VERYSILENT) puts back the tray app it stopped, in the tray, and starts nothing it did not stop
Filename: "{app}\{#AppExe}"; Flags: nowait skipifsilent
Filename: "{app}\{#AppExe}"; Parameters: "--hidden"; Flags: nowait; Check: RelaunchAfterSilentUpdate

[Code]
var
  WasRunning: Boolean;

function InstalledExe(): String;
var
  Dir: String;
begin
  Result := '';
  if RegQueryStringValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#AppId}' + '}_is1',
                         'Inno Setup: App Path', Dir) then
    Result := AddBackslash(Dir) + '{#AppExe}';
end;

procedure QuitRunningCopy(Exe: String);
var
  ResultCode: Integer;
begin
  { waits until the running copy has gone (at most ~10 s); nothing happens when none is running }
  if (Exe <> '') and FileExists(Exe) then
    Exec(Exe, '--quit', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

{ Both run before Inno Setup's AppMutex check (verified), so an update or uninstall does not stop at
  "OpenShaker is running". A copy run from source is not quit; the AppMutex message covers it. }
function InitializeSetup(): Boolean;
begin
  { the running app holds this mutex (the same name as AppMutex): note it before quitting that copy }
  WasRunning := CheckForMutexes('OpenShakerRunning');
  QuitRunningCopy(InstalledExe());
  Result := True;
end;

function RelaunchAfterSilentUpdate(): Boolean;
begin
  Result := WizardSilent and WasRunning;
end;

function InitializeUninstall(): Boolean;
begin
  QuitRunningCopy(ExpandConstant('{app}\{#AppExe}'));
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Settings: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { the app can register itself too, without the installer knowing }
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', '{#AppName}');
    Settings := ExpandConstant('{userappdata}\{#AppName}');
    if DirExists(Settings) and not UninstallSilent then
      if MsgBox('Also delete your {#AppName} settings (presets, strengths and logs)?' + #13#10#13#10 + Settings,
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Settings, True, True, True);
  end;
end;
