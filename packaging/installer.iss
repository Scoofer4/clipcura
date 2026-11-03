; Clipcura installer (Inno Setup 6). Built by tools/build_installer.py after PyInstaller has filled
; packaging\dist\Clipcura; compile by hand with: ISCC /DAppVersion=0.1.0 /Opackaging\dist packaging\installer.iss
;
; Installs per user without administrator rights by default (into %LOCALAPPDATA%\Programs\Clipcura); the
; wizard offers an all-users install for people who have them. Settings in %APPDATA%\Clipcura stay on uninstall.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Clipcura"
#define AppExe "Clipcura.exe"
#define AppUrl "https://github.com/Scoofer4/clipcura"

[Setup]
; Never change AppId: Windows recognises upgrades and the uninstaller by it.
AppId={{876AEE58-7887-43CD-9F7B-478432269429}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Metaverse Media s.r.o.
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
LicenseFile=..\LICENSE
SetupIconFile=build\clipcura.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputBaseFilename=Clipcura-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Restart Manager closes a running Clipcura before files are replaced or removed.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "czech"; MessagesFile: "compiler:Languages\Czech.isl"

[CustomMessages]
english.DesktopIcon=Create a desktop shortcut
czech.DesktopIcon=Vytvořit zástupce na ploše
english.LaunchApp=Start Clipcura
czech.LaunchApp=Spustit Clipcuru
english.NoWebView2=Clipcura shows its window with Microsoft Edge WebView2 Runtime, which is not installed on this computer.%n%nInstall it from https://developer.microsoft.com/microsoft-edge/webview2/ (the "Evergreen" runtime), then start Clipcura. Continue with the installation?
czech.NoWebView2=Clipcura zobrazuje okno přes Microsoft Edge WebView2 Runtime, který na tomto počítači není.%n%nNainstalujte ho z https://developer.microsoft.com/microsoft-edge/webview2/ (runtime „Evergreen“) a pak Clipcuru spusťte. Pokračovat v instalaci?
english.Licences=Licences of included software
czech.Licences=Licence přibaleného softwaru

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; Flags: unchecked

[Files]
Source: "dist\Clipcura\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} - {cm:Licences}"; Filename: "{app}\THIRD-PARTY-NOTICES.txt"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent

[Code]
// WebView2 ships with Windows 11 and current Windows 10; a clean older Windows 10 may lack it.
function WebView2Installed(): Boolean;
var
  Version: String;
begin
  Result :=
    RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version) or
    RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', Version);
  Result := Result and (Version <> '') and (Version <> '0.0.0.0');
end;

function ProcessRunning(Image: String): Boolean;
var
  ResultCode: Integer;
begin
  // find exits with 0 when tasklist lists the image name.
  Result := Exec(ExpandConstant('{cmd}'), '/C tasklist /FI "IMAGENAME eq ' + Image + '" /NH | find /I "' + Image + '"',
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

// A running Clipcura keeps its files open. Closing its window only hides it to the notification area, so ask
// it to quit through its notification-area window (WM_APP + 4, see clipcura/desktop/tray.py) and wait (#18).
procedure StopClipcura();
var
  Wnd: HWND;
  Waited, ResultCode: Integer;
begin
  Wnd := FindWindowByClassName('ClipcuraTray');
  if Wnd <> 0 then
  begin
    PostMessage(Wnd, $8004, 0, 0);
    Waited := 0;
    while (FindWindowByClassName('ClipcuraTray') <> 0) and (Waited < 30000) do
    begin
      Sleep(250);
      Waited := Waited + 250;
    end;
  end;
  // The window goes last, but the process still needs a moment to let go of its files.
  Waited := 0;
  while ProcessRunning('Clipcura.exe') and (Waited < 10000) do
  begin
    Sleep(250);
    Waited := Waited + 250;
  end;
  if ProcessRunning('Clipcura.exe') then
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM Clipcura.exe', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
  // A service without a window (started by an AI assistant through MCP) holds the same files.
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM clipcura-cli.exe', '', SW_HIDE, ewWaitUntilTerminated,
       ResultCode);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  StopClipcura();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  StopClipcura();
  Result := True;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  if not WebView2Installed() then
    Result := SuppressibleMsgBox(CustomMessage('NoWebView2'), mbConfirmation, MB_YESNO, IDYES) = IDYES;
end;
