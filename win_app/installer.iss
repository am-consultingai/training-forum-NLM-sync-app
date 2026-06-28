; Inno Setup script for sHaRe sync.
; Compile on Windows with:  iscc win_app\installer.iss
; Expects the PyInstaller one-dir output at dist\sHaRe-sync\ (see build.ps1).
;
; Per-user install into %LOCALAPPDATA%\Programs so there is no UAC/admin prompt -
; friendlier for a non-technical user. Runtime state (model, CUDA libs, token, data)
; lives separately under %LOCALAPPDATA%\sHaRe-sync; on uninstall the user is
; asked whether to delete it too. The shared VC++ runtime is intentionally NOT
; removed on uninstall (other applications depend on it).

; "sHaRe sync" is the display name shown to users (window/shortcut/uninstall
; entry). The internal identifiers below (AppExe, install dir, data dir, output
; filename) use the filesystem-safe form "sHaRe-sync".
#define AppName "sHaRe sync"
#define AppVersion "1.1.2"
#define AppExe "sHaRe-sync.exe"

[Setup]
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AM Consulting
AppPublisherURL=https://www.amconsultingai.com
AppSupportURL=https://www.amconsultingai.com
DefaultDirName={localappdata}\Programs\sHaRe-sync
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=sHaRe-sync-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Branding: cloud-sync app/setup icon + wizard banner bitmaps. The AM Consulting
; wordmark is placed at the bottom (footer) of every wizard page in [Code]
; (see InitializeWizard) rather than in the icon.
SetupIconFile=app.ico
WizardImageFile=branding\wizard-large.bmp
WizardSmallImageFile=branding\wizard-small.bmp
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Let the (un)installer close the running tray app so its files aren't locked.
CloseApplications=yes
CloseApplicationsFilter=*.exe

[Messages]
; Branded welcome wording (AM Consulting only).
WelcomeLabel1=Welcome to the {#AppName} Setup
WelcomeLabel2=This will install {#AppName} on your computer — a Google Drive → NotebookLM sync tool by AM Consulting.%n%nIt installs for the current user only, so no administrator approval is needed. Click Next to continue.

[Files]
; The entire PyInstaller one-dir output.
Source: "..\dist\sHaRe-sync\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Microsoft Visual C++ runtime - required by the native ML libraries (ctranslate2,
; onnxruntime). Only extracted/run when it isn't already installed (see [Code]).
Source: "vendor\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: VCRedistNeeded
; AM Consulting wordmark, shown at the bottom of every wizard page (see [Code]).
; Not installed - extracted to {tmp} at runtime via ExtractTemporaryFile.
Source: "branding\footer-logo.bmp"; Flags: dontcopy

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{userdesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Run]
; Install the VC++ runtime first, silently, and only if missing (this is the one
; step that may show a UAC prompt - but only on a machine that lacks the runtime).
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; \
  StatusMsg: "Installing Microsoft Visual C++ runtime..."; Flags: waituntilterminated; Check: VCRedistNeeded
; Launch after install finishes.
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Place the AM Consulting wordmark at the bottom-left of every wizard page,
// vertically aligned with the navigation buttons. The bitmap is pre-composited
// onto the standard button-face colour (make_assets.py) so it blends in and
// reads as a transparent footer logo.
procedure InitializeWizard();
var
  FooterLogo: TBitmapImage;
begin
  ExtractTemporaryFile('footer-logo.bmp');
  FooterLogo := TBitmapImage.Create(WizardForm);
  FooterLogo.Parent := WizardForm;
  FooterLogo.Bitmap.LoadFromFile(ExpandConstant('{tmp}\footer-logo.bmp'));
  FooterLogo.Stretch := True;
  FooterLogo.Width := ScaleX(116);
  FooterLogo.Height := ScaleY(29);
  FooterLogo.Left := ScaleX(18);
  FooterLogo.Top := WizardForm.CancelButton.Top +
    (WizardForm.CancelButton.Height - FooterLogo.Height) div 2;
end;

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

// On uninstall, offer to delete the app's own downloaded data (model ~3 GB, CUDA
// libs, OAuth token, synced data). This is app-private (under %LOCALAPPDATA%\
// sHaRe-sync) so removing it can't affect other software. The shared VC++
// runtime is deliberately left in place. Kept by default in a silent uninstall.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  dataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    dataDir := ExpandConstant('{localappdata}\sHaRe-sync');
    if DirExists(dataDir) and (not UninstallSilent) then
    begin
      if MsgBox('Also delete downloaded data for {#AppName}?' + #13#10#13#10 +
                'This includes the ~3 GB transcription model, GPU libraries, your ' +
                'Google sign-in, and locally synced data at:' + #13#10 + dataDir + #13#10#13#10 +
                'Choose No to keep it (e.g. if you plan to reinstall).',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(dataDir, True, True, True);
    end;
  end;
end;
