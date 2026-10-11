"""Autenticación: login, logout y cambio de contraseña."""
import threading
import time

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .. import db
from ..models import Usuario
from ..utils import url_segura, validar_password

bp = Blueprint("auth", __name__)

# --- Límite de intentos fallidos (en memoria; por IP + username) -------------
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 300
_intentos = {}
_candado = threading.Lock()


def _clave(username):
    return f"{request.remote_addr}|{username}"


def _segundos_bloqueado(clave):
    with _candado:
        registro = _intentos.get(clave)
        if not registro:
            return 0
        restante = registro["hasta"] - time.time()
        if restante <= 0 and registro["hasta"]:
            _intentos.pop(clave, None)
            return 0
        return max(0, int(restante))


def _registrar_fallo(clave):
    with _candado:
        registro = _intentos.setdefault(clave, {"n": 0, "hasta": 0})
        registro["n"] += 1
        if registro["n"] >= MAX_INTENTOS:
            registro["hasta"] = time.time() + BLOQUEO_SEGUNDOS
            registro["n"] = 0


def _limpiar_fallos(clave):
    with _candado:
        _intentos.pop(clave, None)


def _inicio_segun_rol():
    if current_user.es_admin:
        return url_for("admin.dashboard")
    return url_for("mecanico.dashboard")


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(_inicio_segun_rol())
    return redirect(url_for("auth.login"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(_inicio_segun_rol())

    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        recordar = request.form.get("recordar") == "on"

        clave = _clave(username)
        espera = _segundos_bloqueado(clave)
        usuario = Usuario.query.filter(db.func.lower(Usuario.username) == username).first()
        if espera:
            flash(f"Demasiados intentos fallidos. Espera {-(-espera // 60)} min e inténtalo de nuevo.", "warning")
        elif usuario is None or not usuario.check_password(password):
            _registrar_fallo(clave)
            flash("Usuario o contraseña incorrectos.", "danger")
        elif not usuario.activo:
            flash("Tu cuenta está desactivada. Contacta al administrador.", "warning")
        else:
            _limpiar_fallos(clave)
            login_user(usuario, remember=recordar)
            flash(f"¡Bienvenido, {usuario.nombre_completo.split()[0]}!", "success")
            destino = request.args.get("next")
            if destino and url_segura(destino):
                return redirect(destino)
            return redirect(_inicio_segun_rol())

    return render_template("auth/login.html")


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada correctamente.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/cambiar-password", methods=["GET", "POST"])
@login_required
def cambiar_password():
    if request.method == "POST":
        actual = request.form.get("actual") or ""
        nueva = request.form.get("nueva") or ""
        confirmar = request.form.get("confirmar") or ""

        if not current_user.check_password(actual):
            flash("La contraseña actual no es correcta.", "danger")
        elif nueva != confirmar:
            flash("La confirmación no coincide con la nueva contraseña.", "danger")
        elif nueva == actual:
            flash("La nueva contraseña debe ser distinta a la actual.", "warning")
        else:
            error = validar_password(nueva)
            if error:
                flash(error, "danger")
            else:
                try:
                    current_user.set_password(nueva)
                    db.session.commit()
                    flash("Contraseña actualizada correctamente.", "success")
                    return redirect(_inicio_segun_rol())
                except Exception:
                    db.session.rollback()
                    flash("No se pudo actualizar la contraseña. Intenta de nuevo.", "danger")
    return render_template("auth/cambiar_password.html")
