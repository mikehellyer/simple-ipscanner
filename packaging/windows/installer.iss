; Inno Setup script for Simple-IPScanner.
; Built with: iscc packaging\windows\installer.iss
; Expects dist\Simple-IPScanner\ (PyInstaller onedir output) to already
; exist, and the version passed in via /DAppVersion=x.y.z (the release
; workflow does this so the .iss file never has to be hand-edited per
; release).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "Simple-IPScanner"
#define RepoRoot AddBackslash(SourcePath) + "..\.."

[Setup]
AppId={{F80A52C2-FEED-4AC2-A41A-2D4CA81B086E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Mike Hellyer
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\Simple-IPScanner.exe
OutputDir={#RepoRoot}\dist
OutputBaseFilename=Simple-IPScanner-{#AppVersion}-Windows-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#RepoRoot}\packaging\icons\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#RepoRoot}\dist\Simple-IPScanner\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Simple-IPScanner.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Simple-IPScanner.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Simple-IPScanner.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
