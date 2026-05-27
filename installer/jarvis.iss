; ================================================================
;  J.A.R.V.I.S — Inno Setup Script
;  Gera JARVIS_Setup_v{X.Y.Z}.exe em installer/output/
;
;  Compilar:
;      iscc installer\jarvis.iss
;  ou definir versão dinamicamente:
;      iscc /DAppVer=2.0.1 installer\jarvis.iss
; ================================================================

#ifndef AppVer
  #define AppVer "2.0.0"
#endif

#define AppName       "J.A.R.V.I.S"
#define AppPublisher  "NinjaZinS2"
#define AppExeName    "JARVIS.exe"
#define AppURL        "https://github.com/NinjaZinS2/jarvis-releases"
#define SrcRoot       "..\"

[Setup]
AppId={{9F6C2C5E-8B4D-47A2-9F1A-7E2D9A2C8B40}
AppName={#AppName}
AppVersion={#AppVer}
AppVerName={#AppName} {#AppVer}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\JARVIS
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes
LicenseFile=
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=output
OutputBaseFilename=JARVIS_Setup_v{#AppVer}
SetupIconFile={#SrcRoot}jarvis_icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\dist\JARVIS\{#AppExeName}
UninstallDisplayName={#AppName} {#AppVer}
VersionInfoVersion={#AppVer}.0
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
; Caminho NÃO hard-coded — usuário escolhe DefaultDirName ou outro durante setup.
; A app detecta seu próprio path em runtime (sys.executable / __file__).

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon";   Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "startmenuicon"; Description: "Criar atalho no menu Iniciar";       GroupDescription: "Atalhos:"
Name: "startup";       Description: "Inicializar JARVIS com o Windows (aparece no Gerenciador de Tarefas → Inicialização)"; GroupDescription: "Inicialização:"; Flags: unchecked

[Files]
; ── Executável compilado (dist/JARVIS/* da pasta do PyInstaller) ────────────
; Coloca dist\JARVIS\ DENTRO do {app} para que o launcher consiga subir 2 níveis
; e encontrar main.py em {app}\main.py (live-source pattern).
Source: "{#SrcRoot}dist\JARVIS\*"; DestDir: "{app}\dist\JARVIS"; Flags: ignoreversion recursesubdirs createallsubdirs

; ── Código-fonte (live-source) ──────────────────────────────────────────────
; main.py, config.py, launcher.py, version.py, VERSION na raiz {app}
Source: "{#SrcRoot}main.py";          DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}config.py";        DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}launcher.py";      DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}version.py";       DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}VERSION";          DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}modelos.py";       DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

; ── Pacotes Python (apenas .py — NUNCA __pycache__, .pyc, dados pessoais) ──
Source: "{#SrcRoot}comandos\*";        DestDir: "{app}\comandos";        Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "{#SrcRoot}core\*";            DestDir: "{app}\core";            Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo,dev_mode\__pycache__\*"
Source: "{#SrcRoot}classifiers\*";     DestDir: "{app}\classifiers";     Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "{#SrcRoot}entity\*";          DestDir: "{app}\entity";          Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "{#SrcRoot}security\*";        DestDir: "{app}\security";        Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "{#SrcRoot}documents\*";       DestDir: "{app}\documents";       Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "{#SrcRoot}dashboard\*";       DestDir: "{app}\dashboard";       Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo,*.pyc"
Source: "{#SrcRoot}updater\*";         DestDir: "{app}\updater";         Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "{#SrcRoot}jarvis\*";          DestDir: "{app}\jarvis";          Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"
Source: "{#SrcRoot}VozIa\*";           DestDir: "{app}\VozIa";           Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo,kokoro_cache\*"
Source: "{#SrcRoot}gesture_interface\*"; DestDir: "{app}\gesture_interface"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo,gesture_data\*"
Source: "{#SrcRoot}ide\*";              DestDir: "{app}\ide";              Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__\*,*.pyc,*.pyo"

; ── Assets ──────────────────────────────────────────────────────────────────
Source: "{#SrcRoot}ui\*";              DestDir: "{app}\ui";              Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SrcRoot}config\*";          DestDir: "{app}\config";          Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.cache.json"

; ── Templates de credenciais (somente templates! nunca .env real) ──────────
Source: "{#SrcRoot}credentials\.env.example"; DestDir: "{app}\credentials"; Flags: ignoreversion onlyifdoesntexist
Source: "{#SrcRoot}credentials\README.md";    DestDir: "{app}\credentials"; Flags: ignoreversion onlyifdoesntexist

; ── Ícone ──────────────────────────────────────────────────────────────────
Source: "{#SrcRoot}jarvis_icon.ico";   DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Registry]
; Inicialização automática com Windows — só se o usuário marcou a tarefa "startup"
; Aparece no Gerenciador de Tarefas → guia Inicialização como "J.A.R.V.I.S"
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\dist\JARVIS\{#AppExeName}"""; Flags: uninsdeletevalue; Tasks: startup

[Icons]
Name: "{group}\{#AppName}";         Filename: "{app}\dist\JARVIS\{#AppExeName}"; IconFilename: "{app}\jarvis_icon.ico"; Tasks: startmenuicon
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}";              Tasks: startmenuicon
Name: "{autodesktop}\{#AppName}";   Filename: "{app}\dist\JARVIS\{#AppExeName}"; IconFilename: "{app}\jarvis_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\dist\JARVIS\{#AppExeName}"; Description: "Iniciar {#AppName} agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Limpa __pycache__ gerados em runtime (mas NÃO toca em credentials, data, temp).
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\comandos\__pycache__"
Type: filesandordirs; Name: "{app}\core\__pycache__"
Type: filesandordirs; Name: "{app}\jarvis\__pycache__"
Type: filesandordirs; Name: "{app}\documents\__pycache__"
Type: filesandordirs; Name: "{app}\updater\__pycache__"
Type: filesandordirs; Name: "{app}\ide\__pycache__"

[Code]
{ Detecta se o usuário tem .env existente e avisa para não sobrescrever.
  Nota: Python NÃO é necessário — o executável inclui o runtime Python embutido
  (gerado via PyInstaller). Qualquer versão do Windows 10/11 funciona. }
procedure CurStepChanged(CurStep: TSetupStep);
var
  EnvPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    EnvPath := ExpandConstant('{app}\credentials\.env');
    if not FileExists(EnvPath) then
    begin
      MsgBox(
        'Instalação concluída!' + #13#10 + #13#10 +
        'Próximo passo: edite o arquivo credentials\.env com suas chaves de API.' + #13#10 +
        '(Use credentials\.env.example como referência.)' + #13#10 + #13#10 +
        'Dica: clique no botão ? dentro do JARVIS para o Guia de Setup com links para cada chave.' + #13#10 + #13#10 +
        'Python NÃO é necessário — o JARVIS já inclui tudo embutido.',
        mbInformation, MB_OK);
    end;
  end;
end;
