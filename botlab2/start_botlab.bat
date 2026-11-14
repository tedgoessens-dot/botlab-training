@echo off
chcp 65001 >nul
title Botlab
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 botlab.py
) else (
  python botlab.py
)
if errorlevel 1 (
  echo.
  echo Python niet gevonden of fout bij starten.
  echo Installeer Python via https://www.python.org/downloads/ en vink "Add python.exe to PATH" aan.
)
pause
