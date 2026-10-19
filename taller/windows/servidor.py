"""Servidor de producción del SGT para Windows.

- Usa waitress (servidor WSGI puro Python, ligero y estable en Windows).
- Escucha en 0.0.0.0 para que celulares y PCs de la red local puedan entrar.
- Escribe su PID y un log rotativo en datos\\logs.
- Hace un respaldo de la base de datos al día (pg_dump) y conserva los últimos 30.

Normalmente lo arranca lanzador.pyw con pythonw.exe (sin ventana).
"""
import datetime
import glob
import logging
import os
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from windows.comun import (  # noqa: E402
    ARCHIVO_LOG,
    ARCHIVO_PID,
    DB_HOST,
    DB_PORT,
    ES_WINDOWS,
    LOGS,
    PG_BIN,
    PUERTO,
    RAIZ_APP,
    RESPALDOS,
    cfg,
    ejecutar,
    puerto_abierto,
)

RESPALDOS_A_CONSERVAR = 30
HILOS = int(cfg("SGT_HILOS", "6"))

log = logging.getLogger("sgt")


class _Escritor:
    """Envía print()/errores sueltos al log (pythonw no tiene consola)."""

    def __init__(self, nivel):
        self.nivel = nivel

    def write(self, texto):
        texto = texto.rstrip()
        if texto:
            log.log(self.nivel, texto)

    def flush(self):
        pass


def configurar_log():
    os.makedirs(LOGS, exist_ok=True)
    manejador = RotatingFileHandler(ARCHIVO_LOG, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8")
    manejador.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    raiz.addHandler(manejador)
    if sys.stdout is None or not sys.stdout.isatty():
        sys.stdout = _Escritor(logging.INFO)
        sys.stderr = _Escritor(logging.ERROR)


# ---------------------------------------------------------------------------
# Respaldos automáticos
# ---------------------------------------------------------------------------
def _pg_dump():
    nombre = "pg_dump.exe" if ES_WINDOWS else "pg_dump"
    ruta = os.path.join(PG_BIN, nombre)
    return ruta if os.path.exists(ruta) else None


def respaldar(nombre=None):
    """Respaldo comprimido (formato custom) de la base de datos. Devuelve la ruta o None.

    Sin `nombre` hace el respaldo diario (sgt_AAAA-MM-DD.backup, uno por día).
    """
    pg_dump = _pg_dump()
    if pg_dump is None:
        log.warning("No se encontró pg_dump en %s; respaldo omitido.", PG_BIN)
        return None
    os.makedirs(RESPALDOS, exist_ok=True)
    diario = nombre is None
    if diario:
        nombre = f"sgt_{datetime.date.today().isoformat()}.backup"
    destino = os.path.join(RESPALDOS, nombre)
    if diario and os.path.exists(destino):
        return destino
    temporal = destino + ".parcial"
    entorno = dict(os.environ, PGPASSWORD=cfg("DB_PASSWORD", ""))
    r = ejecutar(
        [pg_dump, "-h", DB_HOST, "-p", str(DB_PORT), "-U", cfg("DB_USER", "sgt_app"),
         "-F", "c", "-f", temporal, cfg("DB_NAME", "taller_mecanico")],
        env=entorno, timeout=900,
    )
    if r.returncode != 0:
        log.error("Respaldo fallido: %s", (r.stderr or "").strip())
        if os.path.exists(temporal):
            os.remove(temporal)
        return None
    os.replace(temporal, destino)
    log.info("Respaldo creado: %s", destino)
    antiguos = sorted(glob.glob(os.path.join(RESPALDOS, "sgt_*.backup")))[:-RESPALDOS_A_CONSERVAR]
    for archivo in antiguos:
        try:
            os.remove(archivo)
        except OSError:
            pass
    return destino


def _bucle_respaldos():
    time.sleep(45)  # deja que el sistema termine de arrancar
    while True:
        try:
            respaldar()
        except Exception:  # noqa: BLE001
            log.exception("Error inesperado en el respaldo automático")
        time.sleep(3 * 60 * 60)  # revisa cada 3 h (el respaldo es uno por día)


# ---------------------------------------------------------------------------
def main():
    configurar_log()
    if puerto_abierto(PUERTO):
        log.info("El puerto %s ya está en uso; el servidor ya está corriendo.", PUERTO)
        return 0

    os.chdir(RAIZ_APP)
    with open(ARCHIVO_PID, "w", encoding="ascii") as f:
        f.write(str(os.getpid()))

    try:
        from waitress import serve

        from app import create_app

        app = create_app()
        threading.Thread(target=_bucle_respaldos, name="respaldos", daemon=True).start()
        log.info("SGT iniciado en http://0.0.0.0:%s (PID %s, %s hilos)", PUERTO, os.getpid(), HILOS)
        serve(
            app, host="0.0.0.0", port=PUERTO, threads=HILOS,
            connection_limit=100, channel_timeout=120, cleanup_interval=30, ident="SGT",
        )
    except Exception:  # noqa: BLE001
        log.exception("El servidor se detuvo por un error")
        return 1
    finally:
        try:
            with open(ARCHIVO_PID, encoding="ascii") as f:
                es_mio = f.read().strip() == str(os.getpid())
            if es_mio:  # se borra fuera del with: Windows no borra archivos abiertos
                os.remove(ARCHIVO_PID)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
