# build_release.ps1
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (!(Test-Path $VenvPython)) {
  throw "找不到 venv python：$VenvPython。请先创建/激活 .venv。"
}

# 桌面输出目录（每次构建一个新的时间戳目录，避免覆盖）
$Desktop = [Environment]::GetFolderPath("Desktop")
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutDir = Join-Path $Desktop ("AI织梦直播助手_Release_" + $Stamp)

# 临时构建目录（不会污染项目目录）
$TempRoot = Join-Path $env:TEMP ("zhimo_build_" + $Stamp)
$WorkPath = Join-Path $TempRoot "pyi_work"
$DistPath = Join-Path $TempRoot "pyi_dist"
$SpecPath = Join-Path $TempRoot "pyi_spec"

New-Item -ItemType Directory -Force -Path $WorkPath, $DistPath, $SpecPath | Out-Null

Write-Host "== 1) 安装/更新编译依赖 =="
& $VenvPython -m pip install -U pip setuptools wheel cython pyinstaller

Write-Host "== 2) 编译核心为 .pyd（生成 protected_src） =="
Push-Location $ProjectRoot
& $VenvPython ".\build_cython.py"
Pop-Location

$Protected = Join-Path $ProjectRoot "protected_src"
if (!(Test-Path $Protected)) { throw "protected_src 不存在，编译失败？" }

Write-Host "== 3) PyInstaller 打包（所有 build/dist/spec 输出到临时目录） =="
Push-Location $Protected

# 你的资源目录要求：img/ 和 ffmpeg/ 要跟 exe 同级存在（onedir）
& $VenvPython -m PyInstaller -w ".\app.py" `
  --name "AI织梦直播助手" `
  --icon ".\logo.ico" `
  --add-data "logo.ico;." `
  --add-data "ui;ui" `
  --add-data "img;img" `
  --add-data "ffmpeg;ffmpeg" `
  --add-data "audio;audio" `
  --add-data "$env:LOCALAPPDATA\ms-playwright;ms-playwright" `
  --hidden-import PySide6.QtSvg `
  --hidden-import PySide6.QtNetwork `
  --hidden-import playwright.sync_api `
  --clean `
  --noconfirm `
  --distpath "$DistPath" `
  --workpath "$WorkPath" `
  --specpath "$SpecPath"

Pop-Location

Write-Host "== 4) 把成品复制到桌面输出目录 =="
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$BuiltDir = Join-Path $DistPath "AI织梦直播助手"
if (!(Test-Path $BuiltDir)) { throw "找不到打包输出：$BuiltDir" }

Copy-Item -Recurse -Force $BuiltDir (Join-Path $OutDir "AI织梦直播助手")

Write-Host ""
Write-Host "✅ 完成！桌面输出：" $OutDir
Write-Host "📦 程序目录：" (Join-Path $OutDir "AI织梦直播助手")
Write-Host "🧹 临时构建目录（你可手动删除）：" $TempRoot
