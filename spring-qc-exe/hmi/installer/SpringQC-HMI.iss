; Inno Setup script for the Spring QC HMI kiosk shell.
; Build with: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" SpringQC-HMI.iss

#define MyAppName "Spring QC HMI"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Spring QC"
#define DistDir "..\..\..\..\SpringQC-Build-HMI\dist\SpringQCHMI"

[Setup]
AppId={{9A2B3C4D-5E6F-4A7B-8C9D-0E1F2A3B4C5D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\SpringQC\HMI
DisableProgramGroupPage=yes
OutputBaseFilename=SpringQC-HMI-Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern

[Tasks]
Name: "autostart"; Description: "Launch automatically when this panel starts (recommended for a kiosk touchscreen)"; GroupDescription: "Startup:"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Spring QC HMI"; Filename: "{app}\SpringQCHMI.exe"
Name: "{group}\Uninstall Spring QC HMI"; Filename: "{uninstallexe}"
Name: "{commondesktop}\Spring QC HMI"; Filename: "{app}\SpringQCHMI.exe"; Tasks: desktopicon
Name: "{commonstartup}\Spring QC HMI"; Filename: "{app}\SpringQCHMI.exe"; Tasks: autostart

[Run]
Filename: "{app}\SpringQCHMI.exe"; Description: "Launch Spring QC HMI now"; Flags: nowait postinstall skipifsilent
