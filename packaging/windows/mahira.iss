; Inno Setup script for MAHIRA (Windows 10/11)
; Builds a per-user installer from the PyInstaller onedir output (dist\MAHIRA).
;
; The executable is installed per-user. Learner state is stored separately at
; %LOCALAPPDATA%\MAHIRA so replacement, upgrade, and uninstall are data-safe.
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

; Learner data is deliberately not listed in [UninstallDelete]. It lives under
; %LOCALAPPDATA%\MAHIRA and survives application upgrades and uninstall.
