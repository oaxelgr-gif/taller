"""Arma el ZIP de instalación para Windows a partir de este proyecto.

Uso (desde la raíz del proyecto, en cualquier sistema operativo):
    python despliegue_windows/construir_zip.py

Genera dist/SGT-Taller-Windows-AAAA-MM-DD.zip con esta estructura:
    SGT-Taller-Windows/
        INSTALAR_O_ACTUALIZAR.bat   <- doble clic para instalar o actualizar
        LEEME.txt
        instalador/instalar.ps1
        instaladores/               <- opcional: instaladores sin internet
        sistema/                    <- código del sistema
"""
import datetime
import os
import sys
import zipfile

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESPLIEGUE = os.path.join(RAIZ, "despliegue_windows")
CARPETA_ZIP = "SGT-Taller-Windows"

# Lo que NO viaja a la computadora del taller.
EXCLUIR_DIRS = {
    ".git", "venv", ".venv", "__pycache__", ".ruff_cache", ".pytest_cache", "uploads",
    "dist", "despliegue_windows", "node_modules", ".idea", ".vscode",
}
EXCLUIR_ARCHIVOS = {
    ".env", ".DS_Store", "Dockerfile", "docker-compose.yml", "entrypoint.sh", ".dockerignore",
    "iniciar.sh", "iniciar.bat", "Thumbs.db",
}


def _windows(texto, bom=False):
    """Finales de línea CRLF (y BOM opcional) para que Windows lo lea bien."""
    datos = texto.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
    return (b"\xef\xbb\xbf" + datos) if bom else datos


def _leer(ruta):
    with open(ruta, encoding="utf-8-sig") as f:
        return f.read()


def archivos_sistema():
    for carpeta, dirs, archivos in os.walk(RAIZ):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUIR_DIRS and not d.startswith("_respaldo"))
        for nombre in sorted(archivos):
            if nombre in EXCLUIR_ARCHIVOS or nombre.endswith((".pyc", ".pyo", ".log")):
                continue
            ruta = os.path.join(carpeta, nombre)
            yield ruta, os.path.relpath(ruta, RAIZ).replace(os.sep, "/")


def construir():
    os.makedirs(os.path.join(RAIZ, "dist"), exist_ok=True)
    destino = os.path.join(RAIZ, "dist", f"{CARPETA_ZIP}-{datetime.date.today().isoformat()}.zip")
    bat = _leer(os.path.join(DESPLIEGUE, "INSTALAR_O_ACTUALIZAR.bat"))
    if not bat.isascii():
        sys.exit("ERROR: INSTALAR_O_ACTUALIZAR.bat debe contener sólo caracteres ASCII.")

    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(f"{CARPETA_ZIP}/INSTALAR_O_ACTUALIZAR.bat", _windows(bat))
        z.writestr(f"{CARPETA_ZIP}/LEEME.txt", _windows(_leer(os.path.join(DESPLIEGUE, "LEEME.txt")), bom=True))
        # PowerShell 5.1 necesita BOM para leer acentos en UTF-8.
        z.writestr(f"{CARPETA_ZIP}/instalador/instalar.ps1",
                   _windows(_leer(os.path.join(DESPLIEGUE, "instalador", "instalar.ps1")), bom=True))
        z.writestr(f"{CARPETA_ZIP}/instaladores/LEEME.txt",
                   _windows(_leer(os.path.join(DESPLIEGUE, "instaladores", "LEEME.txt")), bom=True))
        total = 0
        for ruta, relativa in archivos_sistema():
            z.write(ruta, f"{CARPETA_ZIP}/sistema/{relativa}")
            total += 1
    for obligatorio in ("run.py", "windows/lanzador.pyw", "windows/sgt.ico", "app/static/vendor/bootstrap/bootstrap.min.css"):
        if not os.path.exists(os.path.join(RAIZ, obligatorio)):
            sys.exit(f"ERROR: falta {obligatorio} en el proyecto.")
    print(f"ZIP creado: {destino}  ({total} archivos del sistema, {os.path.getsize(destino) / 1024 / 1024:.1f} MB)")
    return destino


if __name__ == "__main__":
    construir()
