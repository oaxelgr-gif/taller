"""Fábrica de la aplicación Flask (SGT-Mecánico)."""
import os

from flask import Flask, jsonify, render_template, request, url_for
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFError, CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

login_manager.login_view = "auth.login"
login_manager.login_message = "Inicia sesión para continuar."
login_manager.login_message_category = "warning"
login_manager.session_protection = "basic"  # "strong" cierra sesión si cambia la IP (DHCP/WiFi)


def create_app(config_object="config.Config"):
    app = Flask(__name__)
    app.config.from_object(config_object)

    if app.config.get("SECRET_KEY") in (None, "", "clave-de-desarrollo-cambiala",
                                        "cambia-esto-por-una-cadena-larga-y-aleatoria"):
        if os.getenv("FLASK_DEBUG", "0") == "1" or app.config.get("TESTING"):
            app.logger.warning("SECRET_KEY por defecto: sólo aceptable en desarrollo.")
        else:
            raise RuntimeError(
                "Falta SECRET_KEY en el archivo .env. Genera una con: "
                "python -c \"import secrets; print(secrets.token_hex(32))\""
            )

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from . import models  # noqa: F401  (registra los modelos)
    from .cli import registrar_comandos
    from .routes import registrar_blueprints
    from .utils import (
        formato_fecha,
        formato_fecha_hora,
        formato_input_datetime,
        formato_moneda,
        formato_porcentaje,
    )

    @login_manager.user_loader
    def cargar_usuario(user_id):
        try:
            return db.session.get(models.Usuario, int(user_id))
        except (TypeError, ValueError):
            return None

    # --- Filtros Jinja --------------------------------------------------
    app.jinja_env.filters["moneda"] = formato_moneda
    app.jinja_env.filters["fecha"] = formato_fecha
    app.jinja_env.filters["fechahora"] = formato_fecha_hora
    app.jinja_env.filters["inputdt"] = formato_input_datetime
    app.jinja_env.filters["porcentaje"] = formato_porcentaje
    app.jinja_env.filters["foto_url"] = lambda ruta: (
        url_for("clientes.foto_vehiculo", nombre=os.path.basename(ruta)) if ruta else ""
    )
    app.jinja_env.filters["estado_slug"] = lambda e: (
        (e or "").lower().replace(" ", "-").replace("á", "a").replace("é", "e")
    )

    # Si existen los archivos locales (flask --app run descargar-vendor) la app no
    # depende de internet; en caso contrario se usan los CDN de Bootstrap.
    vendor_local = all(
        os.path.exists(os.path.join(app.static_folder, "vendor", *ruta))
        for ruta in (
            ("bootstrap", "bootstrap.min.css"),
            ("bootstrap", "bootstrap.bundle.min.js"),
            ("bootstrap-icons", "bootstrap-icons.min.css"),
            ("bootstrap-icons", "fonts", "bootstrap-icons.woff2"),
        )
    )

    @app.context_processor
    def inyectar_globales():
        return {
            "TALLER_NOMBRE": app.config["TALLER_NOMBRE"],
            "VENDOR_LOCAL": vendor_local,
            "ESTADOS": models.ESTADOS,
        }

    registrar_blueprints(app)
    registrar_comandos(app)

    # --- Cabeceras de seguridad -------------------------------------------
    @app.after_request
    def cabeceras(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        if request.endpoint != "static":
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    # --- Manejo de errores ------------------------------------------------
    def _es_json():
        return request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json

    def _error(codigo, titulo, mensaje):
        if _es_json():
            return jsonify({"ok": False, "mensaje": mensaje}), codigo
        return render_template("errors/error.html", codigo=codigo, titulo=titulo, mensaje=mensaje), codigo

    @app.errorhandler(403)
    def error_403(_e):
        return _error(403, "Acceso restringido", "No tienes permisos para ver esta sección.")

    @app.errorhandler(404)
    def error_404(_e):
        return _error(404, "Página no encontrada", "El recurso que buscas no existe o fue movido.")

    @app.errorhandler(413)
    def error_413(_e):
        return _error(413, "Archivo demasiado grande", "La petición excede el tamaño permitido.")

    @app.errorhandler(CSRFError)
    def error_csrf(_e):
        return _error(400, "Sesión expirada", "El formulario expiró. Recarga la página e inténtalo de nuevo.")

    @app.errorhandler(500)
    def error_500(_e):
        db.session.rollback()
        return _error(500, "Error interno", "Ocurrió un problema inesperado. Intenta de nuevo.")

    return app
