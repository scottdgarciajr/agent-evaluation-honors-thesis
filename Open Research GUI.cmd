@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\run-evaluation.ps1" -Mode GUI
set "evaluationExit=%ERRORLEVEL%"
if not "%evaluationExit%"=="0" pause
exit /b %evaluationExit%
