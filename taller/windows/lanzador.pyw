"""Acceso directo del escritorio: enciende el sistema (si hace falta) y abre el inicio de sesión.

Uso:
    pythonw.exe lanzador.pyw                 # arranca y abre el navegador
    pythonw.exe lanzador.pyw --sin-navegador # sólo arranca (inicio de Windows)
    pythonw.exe lanzador.pyw --ruta /conectar # abre otra página del sistema
"""
import os
import subprocess
import sys
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from windows.comun import (  # noqa: E402
    ARCHIVO_LOG,
    DB_PORT,
    DESACOPLADO,
    ES_WINDOWS,
    LOGS,
    PG_SERVICIO,
    PUERTO,
    RAIZ_APP,
    ejecutar,
    estado_servidor,
    mensaje,
    puerto_abierto,
)

ESPERA_BD = 40        # segundos máximos para que PostgreSQL acepte conexiones
ESPERA_SERVIDOR = 60  # segundos máximos para que el sistema responda


def _esperar(condicion, segundos):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(0.5)
    return condicion()


def asegurar_postgresql():
    """PostgreSQL es un servicio automático; si está detenido se intenta iniciar."""
    if puerto_abierto(DB_PORT):
        return True
    if not ES_WINDOWS:
        return False
    r = ejecutar(["sc", "start", PG_SERVICIO])
    if r.returncode != 0 and not _esperar(lambda: puerto_abierto(DB_PORT), 3):
        # Sin permisos de administrador: se pide elevación sólo para iniciar el servicio.
        import ctypes
        ctypes.windll.shell32.ShellExecuteW(None, "runas", "sc.exe", f"start {PG_SERVICIO}", None, 0)
    return _esperar(lambda: puerto_abierto(DB_PORT), ESPERA_BD)


def iniciar_servidor():
    os.makedirs(LOGS, exist_ok=True)
    ejecutable = sys.executable
    if ES_WINDOWS and ejecutable.lower().endswith("python.exe"):
        ejecutable = ejecutable[:-len("python.exe")] + "pythonw.exe"
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "servidor.py")
    subprocess.Popen(
        [ejecutable, script], cwd=RAIZ_APP, close_fds=True,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=DESACOPLADO,
    )


def _ruta():
    if "--ruta" in sys.argv:
        i = sys.argv.index("--ruta")
        if i + 1 < len(sys.argv) and sys.argv[i + 1].startswith("/"):
            return sys.argv[i + 1]
    return "/login"


def main():
    abrir = "--sin-navegador" not in sys.argv
    estado = estado_servidor()

    if estado != "ok":
        if not asegurar_postgresql():
            mensaje(
                "No se pudo iniciar la base de datos (PostgreSQL).\n\n"
                f"Abre «Servicios» de Windows, busca «{PG_SERVICIO}» e inícialo, "
                "o vuelve a ejecutar el instalador.",
                error=True,
            )
            return 1
        if estado is None and not puerto_abierto(PUERTO):
            iniciar_servidor()
        if not _esperar(lambda: estado_servidor() == "ok", ESPERA_SERVIDOR):
            mensaje(
                "El sistema no respondió a tiempo.\n\n"
                f"Revisa el registro de errores:\n{ARCHIVO_LOG}",
                error=True,
            )
            return 1

    if abrir:
        webbrowser.open(f"http://localhost:{PUERTO}{_ruta()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
