; Inno Setup script for the Spring QC Server.
; Build with: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" SpringQC-Server.iss
; (or run installer\build_installer.bat)
;
; Installs to C:\SpringQC\Server rather than Program Files on purpose: the
; app writes to its own config.yaml and to uploads\/Output\ next to the exe
; (unchanged from spring-qc-app's design), and Program Files' UAC
; virtualization makes that needlessly fragile for a service running as
; LocalSystem. C:\SpringQC is a plain, fully-writable folder.

#define MyAppName "Spring QC Server"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Spring QC"
#define DistDir "..\..\..\..\SpringQC-Build\dist\SpringQCServer"

[Setup]
AppId={{6B6E6C1E-6E6B-4B7B-9C6E-5C7B6E6B6C1E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName=C:\SpringQC\Server
DisableProgramGroupPage=yes
OutputBaseFilename=SpringQC-Server-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=admin
WizardStyle=modern

[Tasks]
Name: "installservice"; Description: "Install and start the Spring QC Server Windows Service (recommended for unattended operation)"; GroupDescription: "Service:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Spring QC Server (foreground)"; Filename: "{app}\SpringQCServer.exe"
Name: "{group}\Uninstall Spring QC Server"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Spring QC Server"; Filename: "{app}\SpringQCServer.exe"; Tasks: desktopicon

[Run]
; Register + start the service only if the operator opted in; otherwise
; they get the plain foreground exe via the Start Menu shortcut.
Filename: "{app}\SpringQCService.exe"; Parameters: "install"; Flags: runhidden waituntilterminated; Tasks: installservice; StatusMsg: "Registering Spring QC Server service..."
Filename: "{app}\SpringQCService.exe"; Parameters: "start"; Flags: runhidden waituntilterminated; Tasks: installservice; StatusMsg: "Starting Spring QC Server service..."

[UninstallRun]
Filename: "{app}\SpringQCService.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopSvc"
Filename: "{app}\SpringQCService.exe"; Parameters: "remove"; Flags: runhidden waituntilterminated; RunOnceId: "RemoveSvc"

[UninstallDelete]
; Deliberately NOT removing C:\ProgramData\SpringQC (database + logs) on
; uninstall - that's operational data, not part of the install. Remove it
; by hand if a clean wipe is actually wanted.
Type: filesandordirs; Name: "{app}"
