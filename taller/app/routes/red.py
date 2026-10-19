"""Conexión desde otros dispositivos: enlace de la red local y código QR."""
import ipaddress
import json
import os

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy import text

from .. import csrf, db
from ..red import ips_lan, nombre_equipo, qr_svg
from ..utils import staff_required

bp = Blueprint("red", __name__)

# Dentro de Docker las IPs que ve el sistema son internas (172.x) y no sirven al celular.
EN_DOCKER = os.path.exists("/.dockerenv")
_DOCKER_INTERNA = ipaddress.ip_network("172.16.0.0/12")
_recordada = {"cargada": False, "ip": None, "puerto": None}


def _ip_lan(texto):
    try:
        ip = ipaddress.ip_address(texto)
    except ValueError:
        return False
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_link_local:
        return False
    return not (EN_DOCKER and ip in _DOCKER_INTERNA)


def _host_y_puerto():
    """Dirección y puerto con los que el navegador abrió la página (cabecera Host)."""
    host = request.host or ""
    if host.count(":") == 1:
        nombre, puerto = host.split(":")
        return nombre, (puerto if puerto.isdigit() else "80")
    return host, "80"


# ---------------------------------------------------------------------------
# Dirección real recordada: la última IP:puerto de red con la que alguien entró.
# ---------------------------------------------------------------------------
def _archivo_recordada():
    return os.path.join(current_app.config["UPLOAD_FOLDER"], ".direccion_red.json")


def _leer_recordada():
    if not _recordada["cargada"]:
        _recordada["cargada"] = True
        try:
            with open(_archivo_recordada(), encoding="utf-8") as f:
                datos = json.load(f)
            if _ip_lan(datos.get("ip", "")):
                _recordada.update(ip=datos["ip"], puerto=str(datos.get("puerto") or "80"))
        except (OSError, ValueError):
            pass
    return _recordada["ip"], _recordada["puerto"]


@bp.before_app_request
def _recordar_direccion():
    nombre, puerto = _host_y_puerto()
    if not _ip_lan(nombre) or _leer_recordada() == (nombre, puerto):
        return
    _recordada.update(ip=nombre, puerto=puerto)
    try:
        os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
        temporal = _archivo_recordada() + ".tmp"
        with open(temporal, "w", encoding="utf-8") as f:
            json.dump({"ip": nombre, "puerto": puerto}, f)
        os.replace(temporal, _archivo_recordada())
    except OSError:
        pass


def _direcciones():
    """Pares (ip, puerto) para el QR, del más confiable al menos:
    1) la IP:puerto con que se abrió esta página (si fue por la red),
    2) IP_SERVIDOR (la escribe iniciar.sh) con el puerto publicado,
    3) la última IP:puerto real con la que alguien entró,
    4) las IPs que detecta el equipo (no en Docker)."""
    puerto_publico = (str(current_app.config.get("PUERTO_PUBLICO") or "")
                      or str(request.environ.get("SERVER_PORT") or "5000"))
    pares = []

    def agregar(ip, puerto):
        if ip and _ip_lan(ip) and ip not in [p[0] for p in pares]:
            pares.append((ip, puerto))

    nombre, puerto = _host_y_puerto()
    agregar(nombre, puerto)
    agregar(current_app.config.get("IP_SERVIDOR"), puerto_publico)
    _recordada["cargada"] = False  # releer: otro proceso del servidor pudo actualizarla
    ip_rec, puerto_rec = _leer_recordada()
    agregar(ip_rec, puerto_rec)
    if not EN_DOCKER:
        for ip in ips_lan():
            agregar(ip, puerto_publico)
    return pares


def _url(ip, puerto):
    return f"http://{ip}" + ("" if puerto == "80" else f":{puerto}")


@bp.route("/conectar")
@login_required
@staff_required
def conectar():
    pares = _direcciones()
    elegida = request.args.get("ip")
    par = next((p for p in pares if p[0] == elegida), pares[0] if pares else None)
    url = _url(*par) if par else None
    url_login = f"{url}/login" if url else None
    equipo = nombre_equipo()
    puerto = "" if not par or par[1] == "80" else f":{par[1]}"
    return render_template(
        "red/conectar.html",
        ips=[p[0] for p in pares], alternativas=[(p[0], _url(*p)) for p in pares],
        ip=par[0] if par else None, url=url, url_login=url_login,
        qr=qr_svg(url_login) if url_login else None,
        puerto=puerto, en_docker=EN_DOCKER,
        url_nombre=None if EN_DOCKER or not equipo else f"http://{equipo.lower()}{puerto}",
    )


@bp.route("/salud")
@csrf.exempt
def salud():
    """Comprobación ligera usada por el lanzador de Windows (sin sesión)."""
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"ok": True, "bd": True})
    except Exception:  # noqa: BLE001
        db.session.rollback()
        return jsonify({"ok": False, "bd": False}), 503
