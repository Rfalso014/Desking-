; Instalador de Gestor de Descargas (Inno Setup 6).
; Lo compila scripts\empaquetar.ps1 a partir de dist\GestorDescargas:
;   ISCC.exe /DVersion=1.0.0 instalador\GestorDescargas.iss
; Se instala solo para el usuario actual (sin administrador), igual que la conexión con el navegador (HKCU).

#ifndef Version
  #define Version "0.0.0"
#endif
#define Nombre "Gestor de Descargas"
#define Exe "GestorDescargas.exe"

[Setup]
AppId={{6F3C2A51-8B7E-4D2F-9A14-5C0E7B3D9E21}
AppName={#Nombre}
AppVersion={#Version}
AppVerName={#Nombre} {#Version}
AppPublisher=Desking
AppPublisherURL=https://github.com/Rfalso014/Desking-
AppSupportURL=https://github.com/Rfalso014/Desking-/issues
AppUpdatesURL=https://github.com/Rfalso014/Desking-/releases
VersionInfoVersion={#Version}
DefaultDirName={autopf}\GestorDescargas
DefaultGroupName={#Nombre}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=GestorDescargas-{#Version}-instalador
SetupIconFile=..\build\recursos\icono.ico
UninstallDisplayIcon={app}\{#Exe}
UninstallDisplayName={#Nombre}
; lzma2/max: ultra64 con varios hilos agota la memoria del compilador (32 bits) con ~400 MB de archivos.
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Cierra la aplicación (puede estar oculta en la bandeja) antes de reemplazar sus archivos.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "autoinicio"; Description: "Encender el gestor con Windows (en segundo plano: la página y la extensión funcionan siempre)"; GroupDescription: "Sistema:"; Flags: unchecked

[Files]
Source: "..\dist\GestorDescargas\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#Nombre} (encender o apagar)"; Filename: "{app}\{#Exe}"
Name: "{group}\Abrir la página del gestor"; Filename: "{app}\{#Exe}"; Parameters: "--abrir"
Name: "{group}\Carpeta de la extensión del navegador"; Filename: "{app}\extension"
Name: "{group}\Guía de instalación"; Filename: "{app}\LEEME_INSTALACION.txt"
Name: "{group}\Desinstalar {#Nombre}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#Nombre}"; Filename: "{app}\{#Exe}"; Tasks: escritorio

[Registry]
; Mismo valor que escribe la casilla «Encender con Windows» del gestor (src/gestor/nativo/autoinicio.py).
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "GestorDescargas"; ValueData: """{app}\{#Exe}"" --servidor"; Flags: uninsdeletevalue; Tasks: autoinicio

[Run]
; Al terminar: enciende el servidor y abre la página del gestor en el navegador.
Filename: "{app}\{#Exe}"; Parameters: "--abrir"; Description: "Encender {#Nombre} y abrir su página"; Flags: postinstall nowait skipifsilent
; Actualización desde el gestor («Actualizar», instalación silenciosa): se vuelve a encender solo.
Filename: "{app}\{#Exe}"; Parameters: "--encender"; Flags: nowait; Check: WizardSilent
Filename: "{app}\LEEME_INSTALACION.txt"; Description: "Ver cómo conectar la extensión del navegador"; Flags: postinstall shellexec skipifsilent unchecked

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#Exe}"; Flags: runhidden; RunOnceId: "CerrarApp"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Code]
// Al desinstalar se deshace lo que el gestor escribió fuera de {app} (equivale a «--limpiar-sistema»,
// pero sin ejecutar el .exe: así el desinstalador no espera al antivirus). Los datos del usuario se conservan.
// Debe coincidir con src/gestor/nativo/comun.py (restos de la versión de escritorio 1.x) y autoinicio.py.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Datos: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'GestorDescargas');
    RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, 'Software\Google\Chrome\NativeMessagingHosts\com.gestor.descargas');
    RegDeleteKeyIncludingSubkeys(HKEY_CURRENT_USER, 'Software\Microsoft\Edge\NativeMessagingHosts\com.gestor.descargas');
    Datos := ExpandConstant('{%USERPROFILE}\.gestor-descargas');
    DelTree(Datos + '\nativo', True, True, True);
    DeleteFile(Datos + '\host.json');
    DeleteFile(Datos + '\servidor.json');
  end;
end;
