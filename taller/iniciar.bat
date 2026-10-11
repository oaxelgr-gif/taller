@echo off
REM Arranque rápido (Windows): crea el venv si falta, instala dependencias y lanza el servidor.
cd /d "%~dp0"

if not exist venv (
  echo ^>^> Creando entorno virtual...
  python -m venv venv
)
call venv\Scripts\activate.bat

if not exist .env (
  copy .env.example .env >nul
  echo Se creo .env a partir de .env.example. Editalo ^(SECRET_KEY y datos de PostgreSQL^) y vuelve a ejecutar.
  pause
  exit /b 0
)

pip install -q -r requirements.txt
echo Servidor disponible en la red local. Busca tu direccion IPv4 con: ipconfig
python run.py
pause
