$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (!(Test-Path (Join-Path $Root 'server.py'))) {
  throw "server.py was not found in $Root"
}

$VenvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path $VenvPython) {
  $Python = $VenvPython
} else {
  $Python = 'python'
}

Write-Host 'Installing Python backend dependencies and PyInstaller...'
& $Python -m pip install -r requirements.txt
& $Python -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Could not install Python build dependencies.' }

$DistPath = Join-Path $Root 'backend-dist'
$WorkPath = Join-Path $Root 'build\pyinstaller'
$SpecPath = Join-Path $Root 'build\spec'
New-Item -ItemType Directory -Force -Path $DistPath, $WorkPath, $SpecPath | Out-Null

$AddData = "$(Join-Path $Root 'index.html');."
Write-Host 'Building one-file Ozzy backend. This may take several minutes on the first run.'
& $Python -m PyInstaller `
  --noconfirm `
  --clean `
  --onefile `
  --name ozzy-backend `
  --distpath $DistPath `
  --workpath $WorkPath `
  --specpath $SpecPath `
  --add-data $AddData `
  --collect-all google.genai `
  --collect-all websockets `
  --collect-all dotenv `
  --collect-all pyautogui `
  --collect-all pygetwindow `
  --collect-all PIL `
  --collect-all playwright `
  --collect-all pywinauto `
  --collect-all comtypes `
  --hidden-import pythoncom `
  --hidden-import pywintypes `
  --hidden-import win32api `
  --hidden-import win32gui `
  --hidden-import win32process `
  --hidden-import win32con `
  --hidden-import win32com.client `
  --hidden-import browser_control `
  --hidden-import windows_automation `
  --hidden-import windows_workflows `
  --hidden-import safe_file_actions `
  --hidden-import memory_service `
  --hidden-import computer_control `
  server.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed. Check the output above.' }

$ExePath = Join-Path $DistPath 'ozzy-backend.exe'
if (!(Test-Path $ExePath)) { throw "Build finished but $ExePath was not created." }
Write-Host "Backend executable created: $ExePath"
