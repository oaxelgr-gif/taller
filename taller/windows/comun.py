"""Rutas y utilidades compartidas por servidor.py, lanzador.pyw y detener.pyw.

Estructura instalada (por defecto C:\\SGT-Taller):
    app\\            código del sistema (este proyecto) + .env
    python\\         Python embebido
    pgsql\\          PostgreSQL
    datos\\          pgdata, uploads (fotos), logs, respaldos
"""
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request

from dotenv import dotenv_values

ES_WINDOWS = os.name == "nt"
RAIZ_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAIZ_INSTALACION = os.path.dirname(RAIZ_APP)
_ENV = dotenv_values(os.path.join(RAIZ_APP, ".env"))


def cfg(clave, defecto=None):
    return os.environ.get(clave) or _ENV.get(clave) or defecto


PUERTO = int(cfg("PORT", "5000"))
DATOS = os.path.join(RAIZ_INSTALACION, "datos")
LOGS = cfg("SGT_LOGS", os.path.join(DATOS, "logs"))
RESPALDOS = cfg("SGT_RESPALDOS", os.path.join(DATOS, "respaldos"))
PG_BIN = cfg("PG_BIN", os.path.join(RAIZ_INSTALACION, "pgsql", "bin"))
PG_SERVICIO = cfg("PG_SERVICIO", "SGT-PostgreSQL")
DB_HOST = cfg("DB_HOST", "127.0.0.1")
DB_PORT = int(cfg("DB_PORT", "5433"))
ARCHIVO_PID = os.path.join(LOGS, "servidor.pid")
ARCHIVO_LOG = os.path.join(LOGS, "servidor.log")

# Evita que se abran ventanas de consola al lanzar procesos desde pythonw.
SIN_VENTANA = 0x08000000 if ES_WINDOWS else 0          # CREATE_NO_WINDOW
DESACOPLADO = 0x00000008 | 0x00000200 if ES_WINDOWS else 0  # DETACHED_PROCESS | NEW_PROCESS_GROUP


def mensaje(texto, titulo="SGT Taller", error=False):
    """Cuadro de diálogo nativo de Windows (no requiere tkinter)."""
    if ES_WINDOWS:
        import ctypes
        icono = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(None, texto, titulo, icono | 0x40000)  # MB_TOPMOST
    else:
        print(f"[{titulo}] {texto}", file=sys.stderr)


def puerto_abierto(puerto, host="127.0.0.1", espera=1.0):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(espera)
        return s.connect_ex((host, puerto)) == 0


def estado_servidor():
    """'ok' si el sistema responde, 'bd' si responde pero sin base de datos, None si está apagado."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO}/salud", timeout=4) as r:
            return "ok" if r.status == 200 else "bd"
    except urllib.error.HTTPError as e:
        return "bd" if e.code == 503 else None
    except (urllib.error.URLError, OSError):
        return None


def ejecutar(args, **kwargs):
    """subprocess.run sin ventana de consola y con salida de texto."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    if ES_WINDOWS:
        kwargs.setdefault("creationflags", SIN_VENTANA)
    return subprocess.run(args, **kwargs)


def nombre_proceso(pid):
    """Nombre del ejecutable de un PID en Windows (minúsculas) o '' si no existe."""
    if not ES_WINDOWS:
        return ""
    r = ejecutar(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"])
    linea = (r.stdout or "").strip().splitlines()
    if not linea or not linea[0].startswith('"'):
        return ""
    return linea[0].split('","')[0].strip('"').lower()


def leer_pid():
    try:
        with open(ARCHIVO_PID, encoding="ascii") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None
