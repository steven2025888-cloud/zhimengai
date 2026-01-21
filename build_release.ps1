# build_release.ps1 (zero project pollution)
$ErrorActionPreference = "Stop"

$ProjectRoot = $PSScriptRoot
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (!(Test-Path $VenvPython)) { throw "Cannot find venv python: $VenvPython" }

$Desktop = [Environment]::GetFolderPath('Desktop')
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$OutDir = Join-Path $Desktop ("ZhimoAI_Release_" + $Stamp)

# Everything in TEMP
$TempRoot = Join-Path $env:TEMP ("zhimo_build_" + $Stamp)
$WorkPath = Join-Path $TempRoot "pyi_work"
$DistPath = Join-Path $TempRoot "pyi_dist"
$SpecPath = Join-Path $TempRoot "pyi_spec"
$Protected = Join-Path $TempRoot "protected_src"

New-Item -ItemType Directory -Force -Path $TempRoot, $WorkPath, $DistPath, $SpecPath, $Protected | Out-Null

Write-Host "== 1) Install deps =="
& $VenvPython -m pip install -U pip setuptools wheel cython pyinstaller

Write-Host "== 2) Build Cython -> TEMP protected_src =="
Push-Location $ProjectRoot
& $VenvPython ".\build_cython.py" --outdir "$Protected"
Pop-Location

$IconAbs = Join-Path $Protected "logo.ico"
if (!(Test-Path $IconAbs)) { throw "logo.ico not found in TEMP protected_src: $IconAbs" }

$UiAbs  = Join-Path $Protected "ui"
$ImgAbs = Join-Path $Protected "img"
$FfmAbs = Join-Path $Protected "ffmpeg"
$AudAbs = Join-Path $Protected "audio"

Write-Host "== 3) PyInstaller build (TEMP output) =="
Push-Location $Protected

$AsciiName = "AI_Assistant"
& $VenvPython -m PyInstaller -w ".\app.py" `
  --name $AsciiName `
  --icon "$IconAbs" `
  --add-data "$IconAbs;." `
  --add-data "$UiAbs;ui" `
  --add-data "$ImgAbs;img" `
  --add-data "$FfmAbs;ffmpeg" `
  --add-data "$AudAbs;audio" `
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

Write-Host "== 4) Copy to Desktop =="
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$BuiltDir = Join-Path $DistPath $AsciiName
if (!(Test-Path $BuiltDir)) { throw "Cannot find PyInstaller output folder: $BuiltDir" }

$FinalDir = Join-Path $OutDir "AI织梦直播助手"
Copy-Item -Recurse -Force $BuiltDir $FinalDir

# Optional: rename exe to Chinese
$ExeOld = Join-Path $FinalDir "AI_Assistant.exe"
$ExeNew = Join-Path $FinalDir "AI织梦直播助手.exe"
if (Test-Path $ExeOld) { Rename-Item -Force $ExeOld $ExeNew }

Write-Host ""
Write-Host "DONE. Desktop output:"
Write-Host $FinalDir
Write-Host "TEMP build folder (safe to delete):"
Write-Host $TempRoot
