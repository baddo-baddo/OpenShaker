<#
Builds dist\OpenShaker-Setup-<version>.exe:
  1. a clean virtual environment with requirements.txt and PyInstaller
  2. a one-folder app build from installer\OpenShaker.spec
  3. the installer from installer\OpenShaker.iss with Inno Setup 6
Needs 64-bit Python 3.13 (the py launcher, python on PATH or the standard install folders) and Inno
Setup 6 (https://jrsoftware.org/isdl.php). Running from source works with Python 3.10+ (requirements.txt).
Build files go to %TEMP%\OpenShaker-build (or -BuildDir), so a synced project folder stays small.
#>
param(
    [string]$BuildDir = (Join-Path $env:TEMP "OpenShaker-build"),
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
# the Python the pins in installer\constraints.txt were made with (numpy 2.5.3 alone needs 3.12+)
$ReleasePython = "3.13"

function Find-Python {
    $major, $minor = $ReleasePython.Split(".")
    $check = "import sys; sys.exit(0 if sys.version_info[:2] == ($major, $minor) and sys.maxsize > 2**32 else 1)"
    $candidates = @(
        @{ Exe = "py"; Args = @("-$ReleasePython") },
        @{ Exe = "python"; Args = @() },
        @{ Exe = "$env:ProgramFiles\Python$major$minor\python.exe"; Args = @() },
        @{ Exe = "$env:LOCALAPPDATA\Programs\Python\Python$major$minor\python.exe"; Args = @() }
    )
    foreach ($c in $candidates) {
        if (Get-Command $c.Exe -ErrorAction SilentlyContinue) {
            $pyArgs = $c.Args + @("-c", $check)
            # a missing version makes py.exe write to stderr, which "Stop" would turn into a throw
            try { & $c.Exe @pyArgs 2>$null; $ok = $LASTEXITCODE -eq 0 } catch { $ok = $false }
            if ($ok) { return $c }
        }
    }
    throw ("Release builds need 64-bit Python $ReleasePython, the version the pinned packages in " +
        "installer\constraints.txt were tested with (numpy 2.5.3 needs 3.12 or newer), and it was not found. " +
        "Install Python $ReleasePython from https://www.python.org/downloads/ and run installer\build.bat again. " +
        "Running from source works with Python 3.10 or newer.")
}

function Find-ISCC {
    $cmd = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $keys = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Inno Setup 6_is1"
    )
    foreach ($key in $keys) {
        $location = (Get-ItemProperty $key -ErrorAction SilentlyContinue).InstallLocation
        if ($location -and (Test-Path (Join-Path $location "ISCC.exe"))) { return (Join-Path $location "ISCC.exe") }
    }
    foreach ($dir in "$env:LOCALAPPDATA\Programs\Inno Setup 6", "${env:ProgramFiles(x86)}\Inno Setup 6", "$env:ProgramFiles\Inno Setup 6") {
        $exe = Join-Path $dir "ISCC.exe"
        if (Test-Path $exe) { return $exe }
    }
    throw "Inno Setup 6 (ISCC.exe) was not found. Install it from https://jrsoftware.org/isdl.php."
}

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}

$version = (Select-String -Path (Join-Path $Root "openshaker\__init__.py") -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "== OpenShaker $version"
if (-not (Test-Path (Join-Path $Root "LICENSE"))) { throw "LICENSE is missing: a release must never ship without it." }
$constraints = Join-Path $Root "installer\constraints.txt"

if ((Split-Path $BuildDir -Leaf) -notlike "*OpenShaker*") { throw "Refusing to clean ${BuildDir}: the build folder's name must contain 'OpenShaker'." }
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
New-Item -ItemType Directory -Force $BuildDir | Out-Null

Write-Host "== Build environment in $BuildDir"
$python = Find-Python
$venv = Join-Path $BuildDir "venv"
Invoke-Checked $python.Exe ($python.Args + @("-m", "venv", $venv))
$py = Join-Path $venv "Scripts\python.exe"
Invoke-Checked $py @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--upgrade", "pip", "-c", $constraints)
Invoke-Checked $py @("-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", (Join-Path $Root "requirements.txt"), "pyinstaller", "-c", $constraints)
# every package in the build environment must be pinned, so a rebuild bundles exactly the same versions
$pinned = @{}
foreach ($line in Get-Content $constraints) {
    if ($line -match '^\s*([A-Za-z0-9_.-]+)==(\S+)') { $pinned[($Matches[1].ToLower() -replace '[_.]', '-')] = $Matches[2] }
}
foreach ($line in (& $py -m pip freeze --all --disable-pip-version-check)) {
    if ($line -match '^([A-Za-z0-9_.-]+)==(\S+)$') {
        $name, $ver = ($Matches[1].ToLower() -replace '[_.]', '-'), $Matches[2]
        if (-not $pinned.ContainsKey($name)) { throw "$name $ver is not pinned in installer\constraints.txt" }
        if ($pinned[$name] -ne $ver) { throw "$name is $ver but installer\constraints.txt pins $($pinned[$name])" }
    }
}

Write-Host "== Third-party notices"
Invoke-Checked $py @((Join-Path $Root "installer\third_party_notices.py"), "--out", (Join-Path $Root "installer\THIRD-PARTY-NOTICES.txt"))

# A Windows venv has no Tcl/Tk of its own, so PyInstaller would decide tkinter is broken and leave it
# out of the bundle (the window then cannot open). Point it at the base Python's copy.
$basePrefix = (& $py -c "import sys; print(sys.base_prefix)").Trim()
$tcl = Get-ChildItem (Join-Path $basePrefix "tcl") -Directory -Filter "tcl8.*" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
$tk = Get-ChildItem (Join-Path $basePrefix "tcl") -Directory -Filter "tk8.*" -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
if (-not $tcl -or -not $tk) { throw "Tcl/Tk was not found under $basePrefix\tcl. Reinstall Python with 'tcl/tk and IDLE' ticked." }
$env:TCL_LIBRARY = $tcl.FullName
$env:TK_LIBRARY = $tk.FullName

Write-Host "== PyInstaller"
$dist = Join-Path $BuildDir "dist"
Invoke-Checked $py @("-m", "PyInstaller", "--noconfirm", "--clean", "--log-level", "WARN",
    "--distpath", $dist, "--workpath", (Join-Path $BuildDir "work"), (Join-Path $Root "installer\OpenShaker.spec"))
$app = Join-Path $dist "OpenShaker"
# _ssl and OpenSSL: the update check's HTTPS request needs them (openshaker/updater.py)
foreach ($part in "_internal\_tcl_data", "_internal\_tk_data", "_internal\profiles", "_internal\openshaker\openshaker.ico",
                  "_internal\_ssl.pyd", "_internal\libssl-3.dll", "_internal\libcrypto-3.dll") {
    if (-not (Test-Path (Join-Path $app $part))) { throw "The build is missing $part." }
}
# The optional local packages (the spec's PRIVATE, see openshaker/outputs.py) must never reach the
# installer: not in the bundled modules (PYZ table of contents) and not as a file next to the exe.
$work = Join-Path $BuildDir "work\OpenShaker"
if (-not (Test-Path (Join-Path $work "PYZ-00.toc"))) { throw "Cannot check the build: PYZ-00.toc is missing in $work." }
# what was bundled (Analysis-00.toc also lists the excludes, so it would always match)
foreach ($name in "PYZ-00.toc", "PKG-00.toc", "COLLECT-00.toc", "EXE-00.toc") {
    $toc = Join-Path $work $name
    if ((Test-Path $toc) -and (Select-String -Path $toc -Pattern "openshaker[\\/.]wheel" -Quiet)) {
        throw "An optional local package got into the build ($name)."
    }
}
$leak = Get-ChildItem $app -Recurse | Where-Object { $_.FullName -match "openshaker[\\/]wheel" }
if ($leak) { throw "An optional local package got into the build: $($leak[0].FullName)" }
$appSize = (Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("   {0}  ({1:N1} MB in {2} files)" -f $app, ($appSize / 1MB), (Get-ChildItem $app -Recurse -File).Count)

if ($SkipInstaller) { return }
Write-Host "== Inno Setup"
$iscc = Find-ISCC
$out = Join-Path $Root "dist"
Invoke-Checked $iscc @("/Q", "/DAppVersion=$version", "/DBuildDir=$app", "/O$out", (Join-Path $Root "installer\OpenShaker.iss"))
$setup = Join-Path $out "OpenShaker-Setup-$version.exe"
# the checksum asset the app's Update now verifies against: ASCII, no BOM, "<lowercase hash>  <name>\n"
# (a release needs both files; openshaker/updater.py offers no update without the .sha256)
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$setup.sha256", "$hash  OpenShaker-Setup-$version.exe`n", [Text.Encoding]::ASCII)
Write-Host ("== Done: {0}  ({1:N1} MB)" -f $setup, ((Get-Item $setup).Length / 1MB))
Write-Host "   and $setup.sha256  ($hash)"
