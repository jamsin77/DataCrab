; DataCrab Windows 安装包脚本（Inno Setup 6）
;
; 通常由 installer\build.ps1 调用（自动传版本号和 staging 路径）：
;   ISCC.exe /DAppVersion=2026.10.04.500 /DStagingRoot=build\DataCrab datacrab.iss
;
; 布局（staging）:
;   DataCrab\
;     runtime\              embeddable Python + Lib\site-packages + Lib\extra-packages
;     backend\              后端源码 + data\skills + data\standards
;     frontend\dist\        前端构建产物（FastAPI 托管）
;     launcher.py + DataCrab.bat + datacrab.ico

#ifndef StagingRoot
#define StagingRoot "build\DataCrab"
#endif
#ifndef AppVersion
#define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B7A4F3C2-9D58-4E81-A3F6-2C5D8E0B1A94}
AppName=DataCrab
AppVersion={#AppVersion}
AppPublisher=DataCrab
DefaultDirName={localappdata}\Programs\DataCrab
; 每用户安装：不需要管理员权限，安装目录可写（SQLite/技能/日志都写在安装目录下）
PrivilegesRequired=lowest
DefaultGroupName=DataCrab
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=DataCrab-Setup-{#AppVersion}
SetupIconFile=icon\datacrab.ico
UninstallDisplayIcon={app}\datacrab.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "chs"; MessagesFile: "inno\ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Components]
Name: "core"; Description: "DataCrab 主程序（必需）"; Types: full compact custom; Flags: fixed
Name: "vector"; Description: "向量检索组件 ChromaDB + MinIO（知识库 / 语义匹配，约 300MB）"; Types: full custom; Flags: checkablealone

[Files]
; --- 启动器与根文件 ---
Source: "{#StagingRoot}\launcher.py"; DestDir: "{app}"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\DataCrab.bat"; DestDir: "{app}"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\datacrab.ico"; DestDir: "{app}"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\VERSION.txt"; DestDir: "{app}"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\安装说明.txt"; DestDir: "{app}"; Components: core; Flags: ignoreversion skipifsourcedoesntexist

; --- Python 运行时（embeddable，顶层只有文件）---
Source: "{#StagingRoot}\runtime\*.exe"; DestDir: "{app}\runtime"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\runtime\*.dll"; DestDir: "{app}\runtime"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\runtime\*.pyd"; DestDir: "{app}\runtime"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\runtime\*.zip"; DestDir: "{app}\runtime"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\runtime\*._pth"; DestDir: "{app}\runtime"; Components: core; Flags: ignoreversion
Source: "{#StagingRoot}\runtime\LICENSE.txt"; DestDir: "{app}\runtime"; Components: core; Flags: skipifsourcedoesntexist

; --- 核心依赖包 ---
Source: "{#StagingRoot}\runtime\Lib\site-packages\*"; DestDir: "{app}\runtime\Lib\site-packages"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs

; --- 可选依赖包（向量检索组件）---
Source: "{#StagingRoot}\runtime\Lib\extra-packages\*"; DestDir: "{app}\runtime\Lib\extra-packages"; Components: vector; Flags: ignoreversion recursesubdirs createallsubdirs

; --- 后端源码 + 种子数据 ---
Source: "{#StagingRoot}\backend\app\*"; DestDir: "{app}\backend\app"; Components: core; Excludes: "*.db,*.db-journal,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StagingRoot}\backend\data\skills\*"; DestDir: "{app}\backend\data\skills"; Components: core; Excludes: "*.db,*.log"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StagingRoot}\backend\data\standards\*"; DestDir: "{app}\backend\data\standards"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StagingRoot}\backend\.env.example"; DestDir: "{app}\backend"; Components: core; Flags: ignoreversion skipifsourcedoesntexist

; --- 前端构建产物 ---
Source: "{#StagingRoot}\frontend\dist\*"; DestDir: "{app}\frontend\dist"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs

[Dirs]
; 运行时数据目录（代码按需创建，这里显式建好避免首次写入的边界情况）
Name: "{app}\backend\data\uploads"; Components: core
Name: "{app}\backend\data\kb_docs"; Components: core
Name: "{app}\backend\data\operator_experiences"; Components: core
Name: "{app}\backend\data\pipeline_experiences"; Components: core
Name: "{app}\backend\data\chroma"; Components: vector
Name: "{app}\backend\data\kb_chroma"; Components: vector
Name: "{app}\backend\data\match_chroma"; Components: vector

[Icons]
Name: "{group}\DataCrab"; Filename: "{app}\DataCrab.bat"; WorkingDir: "{app}"; IconFilename: "{app}\datacrab.ico"
Name: "{group}\卸载 DataCrab"; Filename: "{uninstallexe}"
Name: "{autodesktop}\DataCrab"; Filename: "{app}\DataCrab.bat"; WorkingDir: "{app}"; IconFilename: "{app}\datacrab.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\DataCrab.bat"; WorkingDir: "{app}"; Description: "启动 DataCrab"; Flags: nowait postinstall skipifsilent
