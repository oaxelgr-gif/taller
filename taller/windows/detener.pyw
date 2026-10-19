"""Detiene el servidor del SGT (la base de datos sigue como servicio de Windows).

Uso:
    pythonw.exe detener.pyw              # con aviso al terminar
    python.exe  detener.pyw --silencioso # para el instalador
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from windows.comun import (  # noqa: E402
    ARCHIVO_PID,
    PUERTO,
    ejecutar,
    leer_pid,
    mensaje,
    nombre_proceso,
    puerto_abierto,
)


def _pids_en_puerto():
    """PIDs que escuchan en el puerto del sistema (netstat funciona en cualquier idioma)."""
    r = ejecutar(["netstat", "-ano", "-p", "TCP"])
    pids = set()
    for linea in (r.stdout or "").splitlines():
        partes = linea.split()
        if len(partes) >= 5 and re.search(rf":{PUERTO}$", partes[1]) and partes[-1].isdigit():
            pids.add(int(partes[-1]))
    return pids


def detener():
    candidatos = set(_pids_en_puerto())
    pid = leer_pid()
    if pid:
        candidatos.add(pid)
    detenidos = 0
    for p in candidatos:
        if nombre_proceso(p) in ("pythonw.exe", "python.exe"):
            ejecutar(["taskkill", "/PID", str(p), "/F"])
            detenidos += 1
    for _ in range(20):
        if not puerto_abierto(PUERTO):
            break
        time.sleep(0.25)
    try:
        os.remove(ARCHIVO_PID)
    except OSError:
        pass
    return detenidos


def main():
    silencioso = "--silencioso" in sys.argv
    n = detener()
    if not silencioso:
        if puerto_abierto(PUERTO):
            mensaje("No se pudo detener el servidor. Reinicia la computadora.", error=True)
            return 1
        mensaje("Servidor detenido." if n else "El servidor no estaba encendido.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
