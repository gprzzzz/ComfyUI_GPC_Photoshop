@echo off
rem Installs the GPC ComfyUI panel for Photoshop without Creative Cloud.
rem It links this folder into your CEP extensions folder (so a git pull updates it)
rem and allows unsigned extensions, which a self-built panel needs.

set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"
set "EXT=%APPDATA%\Adobe\CEP\extensions"
set "TARGET=%EXT%\com.gpc.comfyui.photoshop"

if not exist "%HERE%\CSXS\manifest.xml" (
  echo Run this from the photoshop folder of ComfyUI_GPC_Photoshop: CSXS\manifest.xml is missing here.
  pause
  exit /b 1
)

if not exist "%EXT%" mkdir "%EXT%"
if exist "%TARGET%" rmdir "%TARGET%"
if exist "%TARGET%" (
  echo "%TARGET%" exists and is not a link from an earlier install. Delete it, then run this again.
  pause
  exit /b 1
)
mklink /J "%TARGET%" "%HERE%"
if errorlevel 1 (
  echo Could not link the panel folder. Copy this folder to "%TARGET%" by hand instead.
  pause
  exit /b 1
)

rem Photoshop versions read this setting for different CEP versions; set them all.
rem LogLevel 6 writes CEP logs to %TEMP%, for when the panel doesn't load.
for %%V in (9 10 11 12) do (
  reg add "HKCU\Software\Adobe\CSXS.%%V" /v PlayerDebugMode /t REG_SZ /d 1 /f >nul
  reg add "HKCU\Software\Adobe\CSXS.%%V" /v LogLevel /t REG_SZ /d 6 /f >nul
)

echo.
if exist "%TARGET%\CSXS\manifest.xml" (
  echo Installed: %TARGET%
  echo        -^> "%HERE%"
) else (
  echo The link was made but Photoshop won't see the panel through it: %TARGET%\CSXS\manifest.xml is missing.
)
echo.
echo Restart Photoshop, then open Window ^> Extensions (legacy) ^> GPC ComfyUI.
pause
