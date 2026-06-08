@echo off
REM InvestEdge - avvio one-click
REM Esegue il launcher PowerShell con policy permissiva solo per questa sessione.

setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\launcher.ps1" %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo Launcher uscito con codice %EXITCODE%.
    pause
)
endlocal & exit /b %EXITCODE%
