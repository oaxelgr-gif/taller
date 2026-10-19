#!/usr/bin/env bash
# Arranque con Docker (recomendado): levanta PostgreSQL y Gunicorn aislados con reinicio automático.
set -e
cd "$(dirname "$0")"

DOCKER_BIN="$(which docker 2>/dev/null || echo "/Users/gr/.docker/bin/docker")"

# IP de esta computadora en la red local (WiFi o cable), para los celulares.
detectar_ip() {
    local iface ip
    iface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')"
    for i in $iface en0 en1 en2 en3; do
        ip="$(ipconfig getifaddr "$i" 2>/dev/null || true)"
        if [ -n "$ip" ]; then echo "$ip"; return; fi
    done
    hostname -I 2>/dev/null | awk '{print $1}'
}
export IP_SERVIDOR="${IP_SERVIDOR:-$(detectar_ip)}"
# Se guarda en .env para que también funcione con "docker compose up" directo.
if [ -n "$IP_SERVIDOR" ] && [ -f .env ]; then
    grep -v '^IP_SERVIDOR=' .env > .env.tmp && printf 'IP_SERVIDOR=%s\n' "$IP_SERVIDOR" >> .env.tmp && cat .env.tmp > .env
    rm -f .env.tmp
fi
# Puerto en esta computadora (cámbialo en .env con PUERTO_WEB=8080 si el 5000 está ocupado)
PUERTO_WEB="$(grep -E '^PUERTO_WEB=' .env 2>/dev/null | cut -d= -f2)"
export PUERTO_WEB="${PUERTO_WEB:-5000}"

if command -v "$DOCKER_BIN" >/dev/null 2>&1; then
    echo ">> Iniciando SGT-Mecánico en Docker (PostgreSQL + Gunicorn)..."
    "$DOCKER_BIN" compose up -d --build
    echo ""
    echo ">> Listo. En esta computadora:  http://localhost:$PUERTO_WEB"
    if [ -n "$IP_SERVIDOR" ]; then
        echo ">> Desde celulares (mismo WiFi): http://$IP_SERVIDOR:$PUERTO_WEB"
        echo ">> O escanea el QR en el menú «Conectar dispositivos»."
    else
        echo ">> No se detectó red local: conecta esta computadora al WiFi del taller."
    fi
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
