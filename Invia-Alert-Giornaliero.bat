@echo off
REM InvestEdge - invio alert "Cosa fare oggi" su Telegram.
REM Eseguito a mano o da un'attivita pianificata di Windows.
setlocal
set "DIR=%~dp0"
if not exist "%DIR%data" mkdir "%DIR%data"
"%DIR%backend\.venv\Scripts\python.exe" "%DIR%scripts\send_daily_alert.py" >> "%DIR%data\alert.log" 2>&1
endlocal
