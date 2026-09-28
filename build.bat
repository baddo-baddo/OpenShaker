@echo off
rem Builds dist\OpenShaker-Setup-<version>.exe - see installer\build.ps1.
rem Needs 64-bit Python 3.13 (the version the pinned packages were made with; running from source works
rem with 3.10+) and Inno Setup 6 (https://jrsoftware.org/isdl.php).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\build.ps1" %*
set "CODE=%ERRORLEVEL%"
if not "%OPENSHAKER_NO_PAUSE%"=="1" pause
exit /b %CODE%
