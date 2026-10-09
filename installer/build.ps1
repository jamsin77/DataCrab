# DataCrab Windows 安装包构建脚本
#
# 用法（在仓库根目录）:
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
# 可选开关:
#   -SkipFrontend   跳过前端构建（复用 frontend\dist）
#   -SkipDeps       跳过 pip 依赖安装（复用 installer\cache 下的包缓存）
#   -SkipInstaller  只组装 staging，不调 Inno Setup
#   -PyEmbedVersion 指定 embeddable Python 版本（默认 3.12.14，须与 backend\.venv 主版本一致）
#
# 产物:
#   installer\build\DataCrab\     完整安装目录布局（可直接跑起来冒烟测试）
#   installer\dist\DataCrab-Setup-<版本>.exe   安装包（需 Inno Setup 6）
#
# 前置要求:
#   - backend\.venv 已存在（用它解析依赖 + 生成图标 + 算版本号）
#   - Node.js（构建前端）
#   - Inno Setup 6（winget install JRSoftware.InnoSetup），或加 -SkipInstaller 跳过

param(
    [string]$PyEmbedVersion = "3.12.10",
    [string]$PipIndexUrl = "https://pypi.tuna.tsinghua.edu.cn/simple",
    [switch]$SkipFrontend,
    [switch]$SkipDeps,
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

# --- 路径与常量 ---
$InstallerDir = $PSScriptRoot
$Root = Split-Path $InstallerDir -Parent
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$VenvPython = Join-Path $Backend ".venv\Scripts\python.exe"
$Staging = Join-Path $InstallerDir "build\DataCrab"
$Cache = Join-Path $InstallerDir "cache"
$IconDir = Join-Path $InstallerDir "icon"
$Dist = Join-Path $InstallerDir "dist"

# 3.12.14 -> python312
$PyBase = "python" + (($PyEmbedVersion.Split(".")[0..1]) -join "")

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

function Copy-Tree($src, $dst) {
    robocopy $src $dst /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy 失败: $src -> $dst (code $LASTEXITCODE)" }
}

# --- 前置检查 ---
if (!(Test-Path $VenvPython)) { throw "缺少 $VenvPython —— 先在 backend 下创建 .venv 并装好依赖" }

# --- 0. 清理 staging ---
Write-Step "清理构建目录"
if (Test-Path $Staging) { Remove-Item $Staging -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Staging, $Cache, $IconDir | Out-Null

# --- 1. 前端构建 ---
if (-not $SkipFrontend) {
    Write-Step "构建前端 (npm install + npm run build)"
    Push-Location $Frontend
    try {
        if (!(Test-Path "node_modules")) {
            npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install 失败" }
        }
        # 注意：不跑 vue-tsc（repo 中 vue-tsc 1.8 与 typescript 5.9 不兼容，类型检查是开发期关注点）
        npx vite build
        if ($LASTEXITCODE -ne 0) { throw "vite build 失败" }
    } finally { Pop-Location }
}
$FrontendDist = Join-Path $Frontend "dist"
if (!(Test-Path (Join-Path $FrontendDist "index.html"))) { throw "前端产物不存在: $FrontendDist\index.html" }
Write-Step "复制前端产物"
Copy-Tree $FrontendDist (Join-Path $Staging "frontend\dist")

# --- 2. Embeddable Python ---
Write-Step "准备 Embeddable Python $PyEmbedVersion"
$Zip = Join-Path $Cache "python-$PyEmbedVersion-embed-amd64.zip"
if (!(Test-Path $Zip)) {
    $Url = "https://www.python.org/ftp/python/$PyEmbedVersion/python-$PyEmbedVersion-embed-amd64.zip"
    Write-Host "下载 $Url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Zip
}
Expand-Archive -Path $Zip -DestinationPath (Join-Path $Staging "runtime") -Force

# ._pth：sys.path = 标准库 zip + runtime 本地 + 核心依赖 + 可选依赖 + 后端源码
$PthContent = @"
$PyBase.zip
.
Lib\site-packages
Lib\extra-packages
..\backend

import site
"@
Set-Content -Path (Join-Path $Staging "runtime\$PyBase._pth") -Value $PthContent -Encoding ASCII

# --- 3. Python 依赖（两遍 pip --target，装到缓存再复制；缓存有效则跳过）---
$CorePkg = Join-Path $Cache "site-packages"
$ExtraPkg = Join-Path $Cache "extra-packages"

function Test-PkgCache($dir, $marker) {
    return (Test-Path (Join-Path $dir $marker))
}

if (-not $SkipDeps -and -not (Test-PkgCache $CorePkg "pandas")) {
    # 用 venv 的 pip freeze 做版本约束 —— 安装包与开发环境完全同版本（已测试组合）
    $Constraints = Join-Path $Cache "constraints.txt"
    & $VenvPython -m pip freeze --exclude-editable | Set-Content -Path $Constraints -Encoding ASCII
    Write-Step "安装核心依赖 -> site-packages（按 venv 版本锁定）"
    if (Test-Path $CorePkg) { Remove-Item $CorePkg -Recurse -Force }
    & $VenvPython -m pip install --no-compile --no-warn-script-location --timeout 60 --retries 5 -i $PipIndexUrl -c $Constraints --target $CorePkg `
        -r (Join-Path $Backend "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "核心依赖安装失败" }
} else {
    Write-Step "核心依赖缓存有效，跳过安装"
}
if (-not $SkipDeps -and -not (Test-PkgCache $ExtraPkg "chromadb")) {
    $Constraints = Join-Path $Cache "constraints.txt"
    & $VenvPython -m pip freeze --exclude-editable | Set-Content -Path $Constraints -Encoding ASCII
    Write-Step "安装可选依赖 (ChromaDB/MinIO) -> extra-packages（按 venv 版本锁定）"
    if (Test-Path $ExtraPkg) { Remove-Item $ExtraPkg -Recurse -Force }
    & $VenvPython -m pip install --no-compile --no-warn-script-location --timeout 60 --retries 5 -i $PipIndexUrl -c $Constraints --target $ExtraPkg `
        -r (Join-Path $Backend "requirements-optional.txt")
    if ($LASTEXITCODE -ne 0) { throw "可选依赖安装失败" }
} else {
    Write-Step "可选依赖缓存有效，跳过安装"
}
if (!(Test-PkgCache $CorePkg "pandas")) { throw "缺少核心依赖缓存 $CorePkg（重跑去掉 -SkipDeps）" }
if (!(Test-PkgCache $ExtraPkg "chromadb")) { throw "缺少可选依赖缓存 $ExtraPkg（重跑去掉 -SkipDeps）" }

Write-Step "复制依赖包到 staging"
Copy-Tree $CorePkg (Join-Path $Staging "runtime\Lib\site-packages")
Copy-Tree $ExtraPkg (Join-Path $Staging "runtime\Lib\extra-packages")

# --- 4. 后端源码（只带运行必需：app + 种子技能 + 规则文档）---
Write-Step "复制后端源码"
# app：排除 __pycache__/.pytest_cache/测试缓存；排除 data（仓库里 backend\app\data 是旧版路径逻辑
# 遗留的用户上传脏目录，正式上传目录在 backend\data\uploads 且不随包分发）
robocopy (Join-Path $Backend "app") (Join-Path $Staging "backend\app") /MIR /XD __pycache__ .pytest_cache data /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 app 失败" }
# 依赖包同样清一遍 __pycache__（--no-compile 已避免 .pyc，兜底）
Get-ChildItem (Join-Path $Staging "runtime\Lib") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force
# 种子技能：排除 __pycache__ + 开发期积累的经验/报错文件（新机器从零开始积累）
robocopy (Join-Path $Backend "data\skills") (Join-Path $Staging "backend\data\skills") /MIR /XD __pycache__ /XF experience.json error_log.json /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 skills 失败" }
Copy-Tree (Join-Path $Backend "data\standards") (Join-Path $Staging "backend\data\standards")
Copy-Item (Join-Path $Backend ".env.example") (Join-Path $Staging "backend") -Force

# --- 5. 启动器 ---
Write-Step "复制启动器"
Copy-Item (Join-Path $InstallerDir "launcher.py") $Staging -Force
Copy-Item (Join-Path $InstallerDir "DataCrab.bat") $Staging -Force
Copy-Item (Join-Path $InstallerDir "安装说明.txt") $Staging -Force

# --- 6. 图标（PIL 生成，无现成品牌资源时用简约风格）---
$Ico = Join-Path $IconDir "datacrab.ico"
if (!(Test-Path $Ico)) {
    Write-Step "生成应用图标"
    $IconScript = @"
from PIL import Image, ImageDraw, ImageFont

def make(sz):
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, sz - 1, sz - 1], radius=max(2, sz // 5), fill=(32, 110, 235, 255))
    font = None
    for name in ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf"):
        try:
            font = ImageFont.truetype(name, int(sz * 0.5))
            break
        except Exception:
            pass
    if font is None:
        font = ImageFont.load_default()
    b = d.textbbox((0, 0), "DC", font=font)
    d.text(((sz - (b[2] - b[0])) / 2 - b[0], (sz - (b[3] - b[1])) / 2 - b[1]), "DC",
           font=font, fill=(255, 255, 255, 255))
    return img

make(256).save(r"$Ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon generated")
"@
    $TmpScript = Join-Path $env:TEMP "dc_icon_gen.py"
    Set-Content -Path $TmpScript -Value $IconScript -Encoding UTF8
    & $VenvPython $TmpScript
    if ($LASTEXITCODE -ne 0) { throw "图标生成失败" }
}
Copy-Item $Ico $Staging -Force

# --- 7. 版本号 ---
Write-Step "计算版本号"
$Version = (& $VenvPython -c "import sys; sys.path.insert(0, r'$Backend'); from app.core.version import get_version; print(get_version())") | Select-Object -Last 1
$Version = "$Version".Trim()
if (-not $Version) { $Version = "0.0.0" }
Set-Content -Path (Join-Path $Staging "VERSION.txt") -Value $Version -Encoding ASCII
Write-Host "版本: $Version"

# --- 8. Inno Setup 打包 ---
if (-not $SkipInstaller) {
    # 简中语言包（Inno Setup 官方不随包发行，来自社区翻译 kira-96/Inno-Setup-Chinese-Simplified-Translation）
    $Isl = Join-Path $InstallerDir "inno\ChineseSimplified.isl"
    if (!(Test-Path $Isl)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $Isl) | Out-Null
        Write-Host "下载 ChineseSimplified.isl ..."
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri "https://raw.githubusercontent.com/kira-96/Inno-Setup-Chinese-Simplified-Translation/main/ChineseSimplified.isl" -OutFile $Isl
    }

    $Iscc = $null
    foreach ($c in @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )) {
        if ($c -and (Test-Path $c)) { $Iscc = $c; break }
    }
    if (-not $Iscc) { try { $Iscc = (Get-Command ISCC.exe -ErrorAction Stop).Source } catch {} }
    if ($Iscc) {
        Write-Step "生成安装包 (Inno Setup)"
        New-Item -ItemType Directory -Force -Path $Dist | Out-Null
        & $Iscc "/DAppVersion=$Version" "/DStagingRoot=$Staging" (Join-Path $InstallerDir "datacrab.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup 编译失败" }
        Get-ChildItem $Dist | ForEach-Object { Write-Host ("产物: {0}  ({1:N1} MB)" -f $_.FullName, ($_.Length / 1MB)) -ForegroundColor Green }
    } else {
        Write-Warning "未找到 Inno Setup (ISCC.exe)。安装后重跑，或本次先跳过: winget install JRSoftware.InnoSetup"
    }
}

# --- 9. 汇总 ---
$SizeMB = (Get-ChildItem $Staging -Recurse -File | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ""
Write-Host ("=== 构建完成: {0}  ({1:N0} MB) ===" -f $Staging, $SizeMB) -ForegroundColor Green
Write-Host "冒烟测试（不起浏览器、用 8765 端口）:"
Write-Host "  cd $Staging"
Write-Host '  $env:DATACRAB_PORT=8765; $env:DATACRAB_NO_BROWSER=1; .\runtime\python.exe .\launcher.py'
