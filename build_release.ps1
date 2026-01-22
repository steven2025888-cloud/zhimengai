$ErrorActionPreference = "Stop"

# Avoid garbled output
chcp 65001 | Out-Null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$ProjectRoot = $PSScriptRoot
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (!(Test-Path $VenvPython)) { throw "Cannot find venv python: $VenvPython" }

$Desktop = [Environment]::GetFolderPath('Desktop')
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutDir = Join-Path $Desktop ("ZhimoAI_Release_" + $Stamp)

# Everything in TEMP (keep project directory clean)
$TempRoot  = Join-Path $env:TEMP ("zhimo_build_" + $Stamp)
$WorkPath  = Join-Path $TempRoot "pyi_work"
$DistPath  = Join-Path $TempRoot "pyi_dist"
$SpecPath  = Join-Path $TempRoot "pyi_spec"
$Protected = Join-Path $TempRoot "protected_src"

New-Item -ItemType Directory -Force -Path $TempRoot, $WorkPath, $DistPath, $SpecPath, $Protected | Out-Null

Write-Host "== 1) Install deps =="
& $VenvPython -m pip install -U pip setuptools wheel cython pyinstaller

# Playwright browsers folder
$MsPw = Join-Path $env:LOCALAPPDATA "ms-playwright"
if (!(Test-Path $MsPw)) {
  throw "ms-playwright not found: $MsPw . Run: python -m playwright install chromium"
}

Write-Host "== 2) Build Cython (.pyd) -> TEMP protected_src =="
Push-Location $ProjectRoot
& $VenvPython ".\build_cython.py" --outdir "$Protected"
Pop-Location

# Required resources in protected_src
$IconAbs = Join-Path $Protected "logo.ico"
$ImgAbs  = Join-Path $Protected "img"
$FfmAbs  = Join-Path $Protected "ffmpeg"
if (!(Test-Path $IconAbs)) { throw "logo.ico missing: $IconAbs" }
if (!(Test-Path $ImgAbs))  { Write-Host "WARN: img folder not found: $ImgAbs" }
if (!(Test-Path $FfmAbs))  { Write-Host "WARN: ffmpeg folder not found: $FfmAbs" }

# Optional resource: style.qss (UI styling)
$QssAbs  = Join-Path $Protected "ui\style.qss"

# Optional audio resource dirs (if you want them next to exe)
$ZhHubo  = Join-Path $Protected "zhubo_audio"
$ZhZhuli = Join-Path $Protected "zhuli_audio"

Write-Host "== 3) PyInstaller build (NO _internal; put files next to exe) =="
Push-Location $Protected

# Use ASCII name for stable paths; later rename on Desktop
$AsciiName = "AI_Assistant"

$args = @(
  "-m","PyInstaller",
  "-w",".\app.py",
  "--name",$AsciiName,
  "--icon",$IconAbs,

  # PyInstaller 6+: place contents next to exe (avoid _internal)
  "--contents-directory",".",

  # Only pack REAL resources (DO NOT add ui/audio code folders, or you'll leak .py)
  "--add-data","$IconAbs;.",
  "--add-data","$MsPw;ms-playwright",

  "--hidden-import","PySide6.QtSvg",
  "--hidden-import","PySide6.QtNetwork",
  "--hidden-import","playwright.sync_api",

  "--clean",
  "--noconfirm",
  "--distpath",$DistPath,
  "--workpath",$WorkPath,
  "--specpath",$SpecPath
)

if (Test-Path $ImgAbs) { $args += @("--add-data", "$ImgAbs;img") }
if (Test-Path $FfmAbs) { $args += @("--add-data", "$FfmAbs;ffmpeg") }

# If you NEED QSS on disk next to exe (recommended)
if (Test-Path $QssAbs) { $args += @("--add-data", "$QssAbs;ui") }

# If you NEED audio resource dirs next to exe
if (Test-Path $ZhHubo) { $args += @("--add-data", "$ZhHubo;zhubo_audio") }
if (Test-Path $ZhZhuli) { $args += @("--add-data", "$ZhZhuli;zhuli_audio") }

& $VenvPython @args

Pop-Location

Write-Host "== 4) Copy to Desktop =="
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$BuiltDir = Join-Path $DistPath $AsciiName
if (!(Test-Path $BuiltDir)) { throw "Cannot find output folder: $BuiltDir" }

$FinalDir = Join-Path $OutDir "AI织梦直播助手"
Copy-Item -Recurse -Force $BuiltDir $FinalDir

# Rename exe to Chinese (optional)
$ExeOld = Join-Path $FinalDir "AI_Assistant.exe"
$ExeNew = Join-Path $FinalDir "AI织梦直播助手.exe"
if (Test-Path $ExeOld) { Rename-Item -Force $ExeOld $ExeNew }

Write-Host ""
Write-Host "DONE. Desktop output:"
Write-Host $FinalDir
Write-Host "TEMP build folder (safe to delete):"
Write-Host $TempRoot
