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
  --hidden-import memory_service `
  server.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed. Check the output above.' }

$ExePath = Join-Path $DistPath 'ozzy-backend.exe'
if (!(Test-Path $ExePath)) { throw "Build finished but $ExePath was not created." }
Write-Host "Backend executable created: $ExePath"
