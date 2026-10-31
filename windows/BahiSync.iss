; Bahi Sync installer: puts BahiSync.exe and the sync files in Program Files\Bahi Sync.
; Built by .github/workflows/windows.yml (Inno Setup 6). The version comes from the build number.
#define AppVer GetEnv("BAHI_VERSION")
#if AppVer == ""
  #define AppVer "1.0"
#endif

[Setup]
AppId={{6F0B2C1E-7A4D-4F3B-9B8E-BA41C0DE5A11}
AppName=Bahi Sync
AppVersion={#AppVer}
AppVerName=Bahi Sync {#AppVer}
AppPublisher=Bahi
AppPublisherURL=https://github.com/bdlnaredi/bahi
VersionInfoVersion={#AppVer}
DefaultDirName={autopf}\Bahi Sync
DefaultGroupName=Bahi Sync
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\out
OutputBaseFilename=BahiSync-Setup
SetupIconFile=bahi.ico
UninstallDisplayIcon={app}\BahiSync.exe
UninstallDisplayName=Bahi Sync
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put a Bahi Sync shortcut on the desktop"

[Dirs]
; the sync writes its log and settings here and keeps its own files up to date from the Bahi server,
; so Windows users of this PC may change files in this folder
Name: "{app}"; Permissions: users-modify

[Files]
Source: "..\BahiSync.exe"; DestDir: "{app}"; Flags: ignoreversion
; the sync files: installed when missing; BahiSync.exe puts newer ones in place itself, and the sync
; updates them from the server, so a copy already there may be newer than this one
Source: "..\agent\TallySync.ps1"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\agent\Diagnose.ps1"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\agent\Save-Voucher.ps1"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\agent\Save-Stock.ps1"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\docs\BahiSync.txt"; DestDir: "{app}"; DestName: "Read me.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\Bahi Sync"; Filename: "{app}\BahiSync.exe"
Name: "{group}\Bahi Sync folder"; Filename: "{app}"
Name: "{group}\Uninstall Bahi Sync"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Bahi Sync"; Filename: "{app}\BahiSync.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\BahiSync.exe"; Description: "Start Bahi Sync now"; Flags: nowait postinstall

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM BahiSync.exe"; Flags: runhidden; RunOnceId: "StopBahiSync"
; "Start with Windows" is set by the app itself (for the user who runs it); taken off again here
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v BahiSync /f"; Flags: runhidden; RunOnceId: "NoAutostart"

[Code]
// A running Bahi Sync (this one, or a copy started from another folder) is closed first, so its files can
// be replaced and only the installed copy runs afterwards. A sync already under way carries on by itself.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM BahiSync.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;
