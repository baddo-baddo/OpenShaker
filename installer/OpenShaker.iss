; OpenShaker installer (Inno Setup 6). installer\build.bat compiles it with /DAppVersion=... /DBuildDir=...
; Per-user install: no administrator prompt, installs to %LOCALAPPDATA%\Programs\OpenShaker.

#define AppName "OpenShaker"
#define AppExe "OpenShaker.exe"
#define AppId "6F1E2C3B-8A47-4C5E-9D2B-3E7A1F0C5B84"
; the version lives only in openshaker/__init__.py; build.ps1 passes it in
#ifndef AppVersion
  #error Build with installer\build.bat, which passes /DAppVersion from openshaker/__init__.py
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
SetupIconFile=..\openshaker\openshaker.ico
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
; one setup at a time (the app's Update now could otherwise start a second one)
SetupMutex=OpenShakerSetup
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
; build.ps1 writes the notices next to this script; they are installed as {app}\THIRD-PARTY-NOTICES.txt
Source: "THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
; a silent update keeps the user's current choice: no shortcut comes back that was deleted since
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon; Check: KeepDesktopIcon

[Registry]
; the startup entry the app itself reads and writes (same name, same command); a silent update keeps the
; user's current choice, so Start with Windows switched off in the app stays off
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --hidden"; Flags: uninsdeletevalue; Tasks: startup; Check: KeepStartup
; the entry an earlier version registered under its old name, so Windows never starts two copies
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "ButtKicker Haptics"; Flags: deletevalue dontcreatekey

[Run]
; starts the app as soon as the files are in (there is no Finished page to tick it on); a silent update
; (/SILENT, /VERYSILENT) puts back the app it stopped - in the tray, or with its window when the app's own
; Update now button asked for that (/SHOWWINDOW=1) - and starts nothing it did not stop
Filename: "{app}\{#AppExe}"; Flags: nowait skipifsilent
Filename: "{app}\{#AppExe}"; Parameters: "--hidden"; Flags: nowait; Check: RelaunchAfterSilentUpdate(False)
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: RelaunchAfterSilentUpdate(True)

[Code]
const
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  WasRunning: Boolean;        { the app held its mutex when setup started (and setup quit it) }
  FilesStarted: Boolean;      { setup began replacing files (ssInstall) }
  UpdateInstalled: Boolean;   { ... and finished them (ssPostInstall) }
  TasksFromNow: Boolean;      { the Tasks page's ticks were set from the current state once }

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
  "OpenShaker is running". The installed exe's --quit asks whichever copy holds the app's local port to
  quit, so a copy run from source quits too; without an installed exe the AppMutex message covers it. }
function InitializeSetup(): Boolean;
begin
  { the running app holds this mutex (the same name as AppMutex): note it before quitting that copy }
  WasRunning := CheckForMutexes('OpenShakerRunning');
  QuitRunningCopy(InstalledExe());
  Result := True;
end;

{ The app's Update now runs this setup with /VERYSILENT and keeps running (holding the mutex) until
  InitializeSetup has noted it and asked it to quit, so WasRunning is true for an update it started. }
function RelaunchAfterSilentUpdate(WithWindow: Boolean): Boolean;
begin
  Result := WizardSilent and WasRunning and ((ExpandConstant('{param:SHOWWINDOW|0}') = '1') = WithWindow);
end;

function DesktopLink(): String;
begin
  Result := ExpandConstant('{autodesktop}\{#AppName}.lnk');
end;

{ A silent update (the app's Update now) keeps what the user has now: Start with Windows and the desktop
  shortcut are written only if they are there already. An interactive install follows the ticks, and a
  first install ticks both. }
function IsSilentUpdate(): Boolean;
begin
  Result := WizardSilent and (InstalledExe() <> '');
end;

function KeepStartup(): Boolean;
begin
  Result := (not IsSilentUpdate()) or RegValueExists(HKEY_CURRENT_USER, RunKey, '{#AppName}');
end;

function KeepDesktopIcon(): Boolean;
begin
  Result := (not IsSilentUpdate()) or FileExists(DesktopLink());
end;

{ An interactive install over an installed copy starts its two ticks from how things are now - not from
  the previous install's choices, which the app's own Start with Windows switch may have changed since -
  and an unticked box removes its entry (CurStepChanged). }
procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpSelectTasks) and (not TasksFromNow) and (InstalledExe() <> '') then
  begin
    TasksFromNow := True;
    if RegValueExists(HKEY_CURRENT_USER, RunKey, '{#AppName}') then
      WizardSelectTasks('startup')
    else
      WizardSelectTasks('!startup');
    if FileExists(DesktopLink()) then
      WizardSelectTasks('desktopicon')
    else
      WizardSelectTasks('!desktopicon');
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    FilesStarted := True;
  if CurStep = ssPostInstall then
  begin
    UpdateInstalled := True;
    if not WizardSilent then
    begin
      if not WizardIsTaskSelected('startup') then
        RegDeleteValue(HKEY_CURRENT_USER, RunKey, '{#AppName}');
      if not WizardIsTaskSelected('desktopicon') then
        DeleteFile(DesktopLink());
    end;
  end;
end;

{ Setup quit the running app (InitializeSetup) and then stopped without finishing: cancelled, or a silent
  update that failed - the app closed too slowly for the AppMutex check, a file was locked, the disk was
  full. Wait up to 30 s for that app to be gone, then start the installed copy again, so nobody is left
  with nothing running. After a silent update it says why in its bar: --update-failed when no file was
  replaced yet, --update-incomplete when setup stopped partway through its files (Inno keeps no copy of
  what it overwrote, so the folder may then mix old and new files and needs the installer run again).
  If the app never lets go of its mutex, it is still running, and its installer watch reports it. }
procedure DeinitializeSetup();
var
  Exe, Params: String;
  Waited, ResultCode: Integer;
begin
  if (not WasRunning) or UpdateInstalled then
    Exit;
  Exe := InstalledExe();
  if (Exe = '') or (not FileExists(Exe)) then
    Exit;
  Waited := 0;
  while CheckForMutexes('OpenShakerRunning') and (Waited < 30000) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
  if CheckForMutexes('OpenShakerRunning') then
    Exit;
  Params := '';
  if WizardSilent then
  begin
    if FilesStarted then
      Params := '--update-incomplete={#AppVersion}'
    else
      Params := '--update-failed={#AppVersion}';
  end;
  if (not WizardSilent) or (ExpandConstant('{param:SHOWWINDOW|0}') <> '1') then
    Params := Trim('--hidden ' + Params);
  Exec(Exe, Params, '', SW_SHOWNORMAL, ewNoWait, ResultCode);
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
