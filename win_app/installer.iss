; Inno Setup script for Drive Sync Manager.
; Compile on Windows with:  iscc win_app\installer.iss
; Expects the PyInstaller one-dir output at dist\DriveSyncManager\ (see build.ps1).
;
; Per-user install into %LOCALAPPDATA%\Programs so there is no UAC/admin prompt —
; friendlier for a non-technical user. All runtime state (model, token, data) lives
; separately under %LOCALAPPDATA%\DriveSyncManager and is left intact on uninstall.

#define AppName "Drive Sync Manager"
#define AppVersion "1.0.0"
#define AppExe "DriveSyncManager.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Drive Sync Manager
DefaultDirName={localappdata}\Programs\DriveSyncManager
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=DriveSyncManager-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
; The entire PyInstaller one-dir output.
Source: "..\dist\DriveSyncManager\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Microsoft Visual C++ runtime — required by the native ML libraries (ctranslate2,
; onnxruntime). Only extracted/run when it isn't already installed (see [Code]).
Source: "vendor\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: VCRedistNeeded

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
; Install the VC++ runtime first, silently, and only if missing (this is the one
; step that may show a UAC prompt — but only on a machine that lacks the runtime).
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \
  StatusMsg: "Installing Microsoft Visual C++ runtime..."; Flags: waituntilterminated; Check: VCRedistNeeded
; Launch after install finishes.
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function VCRedistInstalled(): Boolean;
var
  installed: Cardinal;
begin
  // The VC++ 2015-2022 x64 redistributable records this when present.
  Result := RegQueryDWordValue(HKLM64,
    'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64', 'Installed', installed)
    and (installed = 1);
end;

function VCRedistNeeded(): Boolean;
begin
  Result := not VCRedistInstalled();
end;
