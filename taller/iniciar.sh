#!/usr/bin/env bash
# Arranque con Docker (recomendado): levanta PostgreSQL y Gunicorn aislados con reinicio automático.
set -e
cd "$(dirname "$0")"

DOCKER_BIN="$(which docker 2>/dev/null || echo "/Users/gr/.docker/bin/docker")"

if command -v "$DOCKER_BIN" >/dev/null 2>&1; then
    echo ">> Iniciando SGT-Mecánico en Docker (PostgreSQL + Gunicorn)..."
    "$DOCKER_BIN" compose up -d
    echo ">> Contenedores activos. Servidor disponible en http://localhost:5000"
    echo ">> Dirección en la red local:"
    (hostname -I 2>/dev/null || ipconfig getifaddr en0 2>/dev/null || true)
    exit 0
fi

# Modo alternativo sin Docker (desarrollo local)
if [ ! -d venv ]; then
  echo ">> Creando entorno virtual..."
  python3 -m venv venv
fi
source venv/bin/activate
pip install -q -r requirements.txt
python run.py
