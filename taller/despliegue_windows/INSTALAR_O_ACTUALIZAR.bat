@echo off
setlocal
title SGT Taller - Instalador
cd /d "%~dp0"

if not exist "%~dp0instalador\instalar.ps1" goto :sin_extraer
if not exist "%~dp0sistema\run.py" goto :sin_extraer

rem --- Pedir permisos de administrador si no los tiene (un solo intento) ---
fltmc >nul 2>&1
if errorlevel 1 if /i not "%~1"=="elevado" (
  echo.
  echo  Se necesitan permisos de administrador. Acepta la ventana de Windows...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -ArgumentList 'elevado' -Verb RunAs"
  exit /b
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalador\instalar.ps1"
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%

:sin_extraer
echo.
echo  =============================================================
echo   Primero extrae TODO el archivo ZIP:
echo   clic derecho sobre el ZIP ^> "Extraer todo..." ^> Extraer.
echo   Despues abre la carpeta extraida y ejecuta este archivo.
echo  =============================================================
echo.
pause
exit /b 1
