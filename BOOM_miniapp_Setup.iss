; BOOM miniapp - Inno Setup 6
; Dat file nay canh "BOOM miniapp.exe" trong thu muc ban build da giai nen.
; Hoac dat tai goc repository co build\netshort_studio.dist.
; Mo bang Inno Setup, bam F9. Gui khach file EXE trong thu muc installer.

#ifndef SourceDir
  #if FileExists(SourcePath + "build\netshort_studio.dist\BOOM miniapp.exe")
    #define SourceDir SourcePath + "build\netshort_studio.dist"
  #else
    #define SourceDir SourcePath
  #endif
#endif
#if !FileExists(SourceDir + "\BOOM miniapp.exe")
  #error Khong tim thay BOOM miniapp.exe. Hay giai nen ZIP ban build va dat file ISS canh EXE.
#endif
#if !FileExists(SourceDir + "\boom-release.json")
  #error Thieu boom-release.json. Can dung toan bo thu muc ban build, khong chi rieng EXE.
#endif
#if !FileExists(SourceDir + "\ffmpeg.exe")
  #error Thieu ffmpeg.exe trong bo build.
#endif
#ifndef AppVersion
  #define AppVersion GetFileVersion(SourceDir + "\BOOM miniapp.exe")
#endif
#if AppVersion == ""
  #error EXE khong co version. Hay build bang build_standalone.py.
#endif

[Setup]
AppId=BOOM-miniapp-windows-x64
AppName=BOOM miniapp
AppVersion={#AppVersion}
AppPublisher=BOOM
DefaultDirName={localappdata}\Programs\BOOM miniapp
DisableDirPage=yes
DefaultGroupName=BOOM miniapp
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=installer
OutputBaseFilename=BOOM-miniapp-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\BOOM miniapp.exe
CloseApplications=yes
CloseApplicationsFilter=BOOM miniapp.exe
RestartApplications=no
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Excludes: "*.iss,*.private.*,*.pdb,__pycache__\*,poster_cache\*,installer\*,boom_history.json,login.dat,*.boom-update-new,unins*"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\BOOM miniapp"; Filename: "{app}\BOOM miniapp.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\BOOM miniapp"; Filename: "{app}\BOOM miniapp.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\BOOM miniapp.exe"; WorkingDir: "{app}"; Description: "Open BOOM miniapp"; Flags: nowait postinstall skipifsilent
