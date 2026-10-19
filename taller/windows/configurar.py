"""Paso de configuración del instalador de Windows (lo llama instalar.ps1).

Hace, de forma idempotente (sirve para instalar y para actualizar):
  1. Crea o completa el archivo .env (nunca cambia valores existentes).
  2. Crea el usuario y la base de datos de PostgreSQL y ajusta la memoria.
  3. Si ya hay datos, hace un respaldo antes de actualizar.
  4. Aplica schema.sql (tablas, índices y triggers).
  5. Si no hay usuarios, crea el administrador (pregunta usuario y contraseña).
"""
import argparse
import datetime
import getpass
import os
import secrets
import string
import subprocess
import sys

RAIZ_APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ_APP)

ARCHIVO_ENV = os.path.join(RAIZ_APP, ".env")
NOMBRE_DEFECTO = "Ramírez Servicio Automotriz"

# Ajustes de PostgreSQL para una PC de 4 GB de RAM que también se usa para otras cosas.
AJUSTES_PG = {
    "listen_addresses": "localhost",   # la BD nunca se expone a la red
    "max_connections": "30",
    "shared_buffers": "128MB",
    "effective_cache_size": "512MB",
    "work_mem": "4MB",
    "maintenance_work_mem": "64MB",
    "lc_messages": "C",                # mensajes en inglés: evita errores de codificación en Windows
}


def titulo(texto):
    print(f"\n  >> {texto}", flush=True)


def clave_aleatoria(n=24):
    alfabeto = string.ascii_letters + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(n))


# ---------------------------------------------------------------------------
# 1. Archivo .env
# ---------------------------------------------------------------------------
def leer_env():
    valores = {}
    if os.path.exists(ARCHIVO_ENV):
        with open(ARCHIVO_ENV, encoding="utf-8-sig") as f:
            for linea in f:
                linea = linea.strip()
                if linea and not linea.startswith("#") and "=" in linea:
                    k, v = linea.split("=", 1)
                    valores[k.strip()] = v.strip()
    return valores


def preparar_env(args):
    titulo("Configuración del sistema (.env)")
    actuales = leer_env()
    nuevo = not actuales
    datos = os.path.join(args.raiz, "datos")
    nombre = actuales.get("TALLER_NOMBRE")
    if not nombre:
        respuesta = preguntar(f"Nombre del taller [{NOMBRE_DEFECTO}]: ")
        nombre = respuesta or NOMBRE_DEFECTO

    requeridos = {
        "SECRET_KEY": secrets.token_hex(32),
        "FLASK_DEBUG": "0",
        "DB_HOST": "127.0.0.1",
        "DB_PORT": str(args.pg_puerto),
        "DB_NAME": "taller_mecanico",
        "DB_USER": "sgt_app",
        "DB_PASSWORD": clave_aleatoria(),
        "APP_TIMEZONE": "America/Mexico_City",
        "TALLER_NOMBRE": nombre,
        "PORT": str(args.puerto_web),
        "SESSION_COOKIE_SECURE": "0",
        "UPLOAD_FOLDER": os.path.join(datos, "uploads"),
        "SGT_LOGS": os.path.join(datos, "logs"),
        "SGT_RESPALDOS": os.path.join(datos, "respaldos"),
        "PG_BIN": os.path.join(args.raiz, "pgsql", "bin"),
        "PG_SERVICIO": args.pg_servicio,
    }
    faltantes = {k: v for k, v in requeridos.items() if not actuales.get(k)}
    if faltantes:
        with open(ARCHIVO_ENV, "a", encoding="utf-8", newline="\n") as f:
            if nuevo:
                f.write("# SGT Taller - configuración generada por el instalador.\n"
                        "# No compartas este archivo: contiene contraseñas.\n")
            for k, v in faltantes.items():
                f.write(f"{k}={v}\n")
    for carpeta in ("uploads", "logs", "respaldos"):
        os.makedirs(os.path.join(datos, carpeta), exist_ok=True)
    print("     " + ("Archivo .env creado." if nuevo else
                     f"Archivo .env actualizado ({len(faltantes)} valores nuevos)." if faltantes
                     else "Archivo .env sin cambios."))
    return leer_env()


# ---------------------------------------------------------------------------
# 2. PostgreSQL: usuario, base de datos y memoria
# ---------------------------------------------------------------------------
def preparar_postgresql(args, env):
    import psycopg2
    from psycopg2 import sql

    titulo("Base de datos PostgreSQL")
    with open(args.pg_super_archivo, encoding="utf-8-sig") as f:
        super_clave = f.read().strip()
    con = psycopg2.connect(
        host="127.0.0.1", port=args.pg_puerto, user="postgres", password=super_clave,
        dbname="postgres", client_encoding="UTF8", connect_timeout=10,
    )
    con.autocommit = True
    cur = con.cursor()
    usuario, clave, base = env["DB_USER"], env["DB_PASSWORD"], env["DB_NAME"]

    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (usuario,))
    if cur.fetchone():
        cur.execute(sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s").format(sql.Identifier(usuario)), (clave,))
        print(f"     Usuario «{usuario}» verificado.")
    else:
        cur.execute(sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(sql.Identifier(usuario)), (clave,))
        print(f"     Usuario «{usuario}» creado.")

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (base,))
    if cur.fetchone():
        print(f"     Base de datos «{base}» existente (se conservan los datos).")
    else:
        crear = sql.SQL("CREATE DATABASE {} OWNER {} ENCODING 'UTF8' TEMPLATE template0").format(
            sql.Identifier(base), sql.Identifier(usuario))
        try:
            cur.execute(crear)
        except psycopg2.Error:
            # Algunas configuraciones regionales no aceptan UTF8: se usa la intercalación neutra.
            cur.execute(sql.SQL(
                "CREATE DATABASE {} OWNER {} ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0"
            ).format(sql.Identifier(base), sql.Identifier(usuario)))
        print(f"     Base de datos «{base}» creada.")

    for parametro, valor in AJUSTES_PG.items():
        cur.execute(sql.SQL("ALTER SYSTEM SET {} = %s").format(sql.Identifier(parametro)), (valor,))
    cur.execute("SELECT pg_reload_conf()")
    print("     Memoria ajustada para equipos de 4 GB (se aplica al reiniciar el servicio).")
    con.close()


# ---------------------------------------------------------------------------
# 3-5. Respaldo, esquema y administrador
# ---------------------------------------------------------------------------
def hay_datos(env):
    import psycopg2
    con = psycopg2.connect(host=env["DB_HOST"], port=env["DB_PORT"], user=env["DB_USER"],
                           password=env["DB_PASSWORD"], dbname=env["DB_NAME"], connect_timeout=10)
    try:
        cur = con.cursor()
        cur.execute("SELECT to_regclass('public.usuarios') IS NOT NULL")
        existe = cur.fetchone()[0]
        if not existe:
            return False
        cur.execute("SELECT EXISTS (SELECT 1 FROM usuarios)")
        return cur.fetchone()[0]
    finally:
        con.close()


def respaldo_previo(env):
    if not hay_datos(env):
        return
    titulo("Respaldo de seguridad antes de actualizar")
    from windows.servidor import respaldar
    marca = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    ruta = respaldar(nombre=f"pre-actualizacion_{marca}.backup")
    if ruta:
        print(f"     Respaldo guardado en {ruta}")
    else:
        print("     AVISO: no se pudo crear el respaldo (revisa datos\\logs\\servidor.log).")


def aplicar_esquema():
    titulo("Tablas, índices y reglas de la base de datos")
    r = subprocess.run([sys.executable, "-m", "flask", "--app", "run", "init-db"], cwd=RAIZ_APP)
    if r.returncode != 0:
        raise SystemExit("ERROR: no se pudo aplicar schema.sql.")


def preguntar(texto, oculto=False):
    if not sys.stdin or not sys.stdin.isatty():
        return ""
    try:
        return (getpass.getpass(texto) if oculto else input(texto)).strip()
    except EOFError:
        return ""


def crear_administrador(args):
    from app import create_app, db
    from app.cli import _asegurar_roles, _crear_usuario
    from app.models import ROL_ADMIN, Usuario
    from app.utils import validar_password, validar_username

    app = create_app()
    with app.app_context():
        if Usuario.query.first() is not None:
            print("\n  >> Usuarios: ya existen, no se crea ninguno nuevo.")
            return
        titulo("Crear el usuario administrador")
        _asegurar_roles()
        interactivo = sys.stdin is not None and sys.stdin.isatty()
        nombre = preguntar("Nombre completo del administrador [Administrador]: ") or "Administrador"
        while True:
            usuario = (preguntar("Nombre de usuario para entrar [admin]: ") or "admin").lower()
            error = validar_username(usuario)
            if not error:
                break
            print(f"     {error}")
        if interactivo:
            print("     La contraseña debe tener al menos 8 caracteres, con letras y números.")
            while True:
                clave = preguntar("Contraseña: ", oculto=True)
                error = validar_password(clave)
                if error:
                    print(f"     {error}")
                    continue
                if clave != preguntar("Repite la contraseña: ", oculto=True):
                    print("     Las contraseñas no coinciden.")
                    continue
                break
        else:
            clave = clave_aleatoria(10) + "7a"
            ruta = os.path.join(args.raiz, "datos", "CONTRASENA_ADMIN_INICIAL.txt")
            with open(ruta, "w", encoding="utf-8") as f:
                f.write(f"Usuario: {usuario}\nContraseña temporal: {clave}\n"
                        "Cámbiala al entrar y borra este archivo.\n")
            print(f"     Contraseña temporal guardada en {ruta}")
        _crear_usuario(nombre, usuario, clave, ROL_ADMIN, comision=0)
        db.session.commit()
        print(f"     Administrador «{usuario}» creado.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--raiz", required=True)
    p.add_argument("--pg-puerto", type=int, default=5433)
    p.add_argument("--pg-servicio", default="SGT-PostgreSQL")
    p.add_argument("--pg-super-archivo", required=True)
    p.add_argument("--puerto-web", type=int, default=5000)
    args = p.parse_args()

    env = preparar_env(args)
    preparar_postgresql(args, env)
    os.environ.update({k: v for k, v in env.items() if v})
    respaldo_previo(env)
    aplicar_esquema()
    crear_administrador(args)
    print("\n  >> Configuración terminada.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
