$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Get-Command flutter -ErrorAction SilentlyContinue)) {
  throw 'Flutter was not found. Install Flutter, add flutter/bin to PATH, then rerun this script.'
}

$TempRoot = Join-Path $env:TEMP ('ozzy_flutter_bootstrap_' + [guid]::NewGuid().ToString('N'))
$LibBackup = Join-Path $TempRoot 'lib'
$PubspecBackup = Join-Path $TempRoot 'pubspec.yaml'
New-Item -ItemType Directory -Force -Path $TempRoot | Out-Null
Copy-Item -Recurse (Join-Path $ProjectRoot 'lib') $LibBackup
Copy-Item (Join-Path $ProjectRoot 'pubspec.yaml') $PubspecBackup

try {
  Write-Host 'Generating Android and iOS Flutter platform scaffolding...' -ForegroundColor Cyan
  flutter create --platforms=android,ios --org com.yasindu --project-name ozzy_mobile --empty .
  if ($LASTEXITCODE -ne 0) { throw 'flutter create failed.' }

  # flutter create generates platform folders and may refresh the starter files.
  # Restore Ozzy's app source and dependency list after generating those folders.
  Remove-Item -Recurse -Force (Join-Path $ProjectRoot 'lib')
  Copy-Item -Recurse $LibBackup (Join-Path $ProjectRoot 'lib')
  Copy-Item -Force $PubspecBackup (Join-Path $ProjectRoot 'pubspec.yaml')

  $ManifestPath = Join-Path $ProjectRoot 'android/app/src/main/AndroidManifest.xml'
  if (Test-Path $ManifestPath) {
    $xml = Get-Content $ManifestPath -Raw
    foreach ($permission in @('android.permission.INTERNET','android.permission.RECORD_AUDIO','android.permission.CAMERA')) {
      if ($xml -notmatch [regex]::Escape("android:name=`"$permission`"")) {
        $xml = $xml -replace '<application', "<uses-permission android:name=`"$permission`" />`r`n    <application"
      }
    }
    Set-Content -Path $ManifestPath -Value $xml -Encoding UTF8
  }

  $GradleKts = Join-Path $ProjectRoot 'android/app/build.gradle.kts'
  if (Test-Path $GradleKts) {
    $gradle = Get-Content $GradleKts -Raw
    $gradle = $gradle -replace 'minSdk\s*=\s*flutter\.minSdkVersion', 'minSdk = 24'
    Set-Content -Path $GradleKts -Value $gradle -Encoding UTF8
  }
  $GradleGroovy = Join-Path $ProjectRoot 'android/app/build.gradle'
  if (Test-Path $GradleGroovy) {
    $gradle = Get-Content $GradleGroovy -Raw
    $gradle = $gradle -replace 'minSdkVersion\s+flutter\.minSdkVersion', 'minSdkVersion 24'
    Set-Content -Path $GradleGroovy -Value $gradle -Encoding UTF8
  }

  $PodfilePath = Join-Path $ProjectRoot 'ios/Podfile'
  if (Test-Path $PodfilePath) {
    $podfile = Get-Content $PodfilePath -Raw
    $podfile = $podfile -replace "platform :ios, '[0-9.]+'", "platform :ios, '13.0'"
    Set-Content -Path $PodfilePath -Value $podfile -Encoding UTF8
  }

  $InfoPlistPath = Join-Path $ProjectRoot 'ios/Runner/Info.plist'
  if (Test-Path $InfoPlistPath) {
    $plist = Get-Content $InfoPlistPath -Raw
    $permissions = @(
      @('NSCameraUsageDescription','Ozzy uses the camera only when you turn on live visual awareness.'),
      @('NSMicrophoneUsageDescription','Ozzy uses the microphone for real-time voice conversations.'),
      @('NSPhotoLibraryUsageDescription','Choose an image to share with Ozzy for visual questions.')
    )
    foreach ($item in $permissions) {
      $key = $item[0]
      if ($plist -notmatch "<key>$key</key>") {
        $entry = "  <key>$key</key>`r`n  <string>$($item[1])</string>`r`n"
        $plist = $plist -replace '</dict>\s*$', ($entry + '</dict>')
      }
    }
    Set-Content -Path $InfoPlistPath -Value $plist -Encoding UTF8
  }

  Write-Host 'Fetching Flutter dependencies...' -ForegroundColor Cyan
  flutter pub get
  if ($LASTEXITCODE -ne 0) { throw 'flutter pub get failed. Read the dependency error above.' }
  Write-Host ''
  Write-Host 'Ozzy mobile platforms are ready.' -ForegroundColor Green
  Write-Host 'Next: flutter devices, then flutter run -d <device-id>' -ForegroundColor Green
}
finally {
  if (Test-Path $TempRoot) { Remove-Item -Recurse -Force $TempRoot }
}
