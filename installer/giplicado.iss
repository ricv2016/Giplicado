; Instalador de Giplicado — Inno Setup 6 (gratuito, https://jrsoftware.org/isinfo.php)
; Compilar:  "ISCC.exe" installer\giplicado.iss
; Antes hay que generar dist\Giplicado con:  python -m PyInstaller giplicado.spec --noconfirm

#define AppName "Giplicado"
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppExe "Giplicado.exe"

[Setup]
AppId={{6F1C2B7E-4A3D-4E9B-9C51-6A2E8D0B7F41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Permite instalar sin ser administrador (solo para el usuario actual) o para todos
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Giplicado-{#AppVersion}-instalador
SetupIconFile=..\assets\giplicado.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el &escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "..\dist\Giplicado\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName} ahora"; Flags: nowait postinstall skipifsilent
; Tras una actualización automática (modo silencioso) se vuelve a abrir la app
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent
