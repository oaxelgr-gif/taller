"""Configuración de Flask y conexión a PostgreSQL (SQLAlchemy)."""
import os
from datetime import timedelta
from urllib.parse import quote_plus

from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(valor, defecto=False):
    if valor is None:
        return defecto
    return str(valor).strip().lower() in ("1", "true", "t", "yes", "si", "sí", "on")


def _database_uri():
    url = os.getenv("DATABASE_URL")
    if url:
        # Heroku/Render usan "postgres://"; SQLAlchemy 2 requiere "postgresql://"
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        return url
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    name = os.getenv("DB_NAME", "taller_mecanico")
    user = quote_plus(os.getenv("DB_USER", "taller_user"))
    password = quote_plus(os.getenv("DB_PASSWORD", "taller_pass"))
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "clave-de-desarrollo-cambiala")
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 1800}

    APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Mexico_City")
    TALLER_NOMBRE = os.getenv("TALLER_NOMBRE", "Taller Mecánico")

    # Sesión / seguridad
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool(os.getenv("SESSION_COOKIE_SECURE"), False)
    WTF_CSRF_TIME_LIMIT = None  # el token vive lo que dure la sesión
    REMEMBER_COOKIE_DURATION = timedelta(days=7)

    # Paginación
    POR_PAGINA = 15

    # Reglas de negocio
    COMISION_DEFECTO = 15.00
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB para permitir fotos de cámaras móviles
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "app", "static", "uploads")
    ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
