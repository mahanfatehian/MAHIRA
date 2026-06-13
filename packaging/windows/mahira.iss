; Inno Setup script for MAHIRA (Windows 10/11)
; Builds a per-user installer from the PyInstaller onedir output (dist\MAHIRA).
;
; Why per-user (PrivilegesRequired=lowest) + LocalAppData:
;   MAHIRA keeps ALL of its runtime data (SQLite DB, ML models, logs) inside a
;   `.mahira` folder NEXT TO the executable. Installing into a user-writable
;   location means that data folder is writable without admin rights and the
;   whole app stays self-contained — nothing is written to %APPDATA%\Roaming or
;   any other per-user/OS metadata location.
;
; Compile:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\mahira.iss
; (optionally override the version: ISCC.exe /DMyAppVersion=1.2.3 ...)

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif

#define MyAppName "MAHIRA"
#define MyAppPublisher "MAHIRA"
#define MyAppExeName "MAHIRA.exe"

[Setup]
AppId={{B7E4C9A2-7F3D-4E51-9C2A-MAHIRADE0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist\installer
OutputBaseFilename=MAHIRA-Setup-{#MyAppVersion}-win64
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile=..\..\assets\logo.ico
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Ship the entire PyInstaller onedir build.
Source: "..\..\dist\MAHIRA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove the self-contained runtime data folder on uninstall.
Type: filesandordirs; Name: "{app}\.mahira"
