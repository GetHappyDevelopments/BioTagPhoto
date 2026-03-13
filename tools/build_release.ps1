param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\\Scripts\\python.exe"
$SpecFile = Join-Path $ProjectRoot "packaging\\biotagphoto.spec"
$ReleaseDir = Join-Path $ProjectRoot "release"
$DistDir = Join-Path $ProjectRoot "dist"
$BuildDir = Join-Path $ProjectRoot "build"
$InnoScript = Join-Path $ProjectRoot "packaging\\BioTagPhoto.iss"
if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment not found: $VenvPython"
}

Write-Host "Using Python:" $VenvPython

& $VenvPython -m pip install --upgrade pip pyinstaller | Out-Host

if (Test-Path $ReleaseDir) {
    Remove-Item $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Path $ReleaseDir | Out-Null

Write-Host "Building PyInstaller bundle..."
& $VenvPython -m PyInstaller --noconfirm --clean $SpecFile | Out-Host

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed."
}

$BundleExe = Join-Path $DistDir "BioTagPhoto\\BioTagPhoto.exe"
if (-not (Test-Path $BundleExe)) {
    throw "Expected bundle not found: $BundleExe"
}

if ($SkipInstaller) {
    Write-Host "Bundle created at:" $BundleExe
    exit 0
}

$ISCC = "${env:ProgramFiles(x86)}\\Inno Setup 6\\ISCC.exe"
if (-not (Test-Path $ISCC)) {
    throw "Inno Setup compiler not found: $ISCC"
}

Write-Host "Building installer..."
& $ISCC $InnoScript | Out-Host

if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup build failed."
}

Write-Host "Release artifacts available in:" $ReleaseDir
