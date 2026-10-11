"""Comandos de línea: flask --app run init-db | crear-admin | datos-demo."""
import os
import random
from datetime import timedelta
from decimal import Decimal

import click
from flask import current_app

from . import db
from .models import (
    ROL_ADMIN,
    ROL_MECANICO,
    Cliente,
    DetalleOrdenServicio,
    HistorialEstado,
    OrdenTrabajo,
    Rol,
    Servicio,
    Usuario,
    Vehiculo,
)
from .utils import ahora

VENDOR_ARCHIVOS = [
    ("https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css", ("bootstrap", "bootstrap.min.css")),
    ("https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js", ("bootstrap", "bootstrap.bundle.min.js")),
    ("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css", ("bootstrap-icons", "bootstrap-icons.min.css")),
    ("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2", ("bootstrap-icons", "fonts", "bootstrap-icons.woff2")),
    ("https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff", ("bootstrap-icons", "fonts", "bootstrap-icons.woff")),
]

SCHEMA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


def _asegurar_roles():
    for nombre in (ROL_ADMIN, ROL_MECANICO):
        if Rol.query.filter_by(nombre=nombre).first() is None:
            db.session.add(Rol(nombre=nombre))
    db.session.commit()


def _crear_usuario(nombre, username, password, rol, comision=None, correo=None):
    rol_obj = Rol.query.filter_by(nombre=rol).one()
    usuario = Usuario(
        nombre_completo=nombre,
        username=username.lower().strip(),
        correo=correo.lower().strip() if correo else None,
        id_rol=rol_obj.id_rol,
        porcentaje_comision_defecto=Decimal(str(comision if comision is not None else 15)),
        activo=True,
    )
    usuario.set_password(password)
    db.session.add(usuario)
    return usuario


def registrar_comandos(app):
    @app.cli.command("init-db")
    def init_db():
        """Crea tablas, índices, triggers y roles base ejecutando schema.sql."""
        with open(SCHEMA, encoding="utf-8") as f:
            sql = f.read()
        conexion = db.engine.raw_connection()
        try:
            cursor = conexion.cursor()
            cursor.execute(sql)
            conexion.commit()
        finally:
            conexion.close()
        click.echo("✔ Base de datos inicializada (tablas, índices, triggers y roles).")

    @app.cli.command("descargar-vendor")
    def descargar_vendor():
        """Descarga Bootstrap y Bootstrap Icons a static/vendor (uso sin internet)."""
        import urllib.request

        base = os.path.join(current_app.static_folder, "vendor")
        for url, ruta in VENDOR_ARCHIVOS:
            destino = os.path.join(base, *ruta)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            try:
                with urllib.request.urlopen(url, timeout=30) as resp:
                    contenido = resp.read()
            except Exception as e:  # noqa: BLE001
                raise click.ClickException(f"No se pudo descargar {url}: {e}")
            if not contenido:
                raise click.ClickException(f"Descarga vacía: {url}")
            with open(destino, "wb") as f:
                f.write(contenido)
            click.echo(f"  ✔ {'/'.join(ruta)} ({len(contenido) // 1024} KB)")
        click.echo("✔ Recursos guardados en app/static/vendor. Reinicia el servidor para usarlos.")

    @app.cli.command("crear-admin")
    @click.option("--nombre", prompt="Nombre completo")
    @click.option("--username", prompt="Nombre de usuario (ej. admin)")
    @click.password_option("--password", prompt="Contraseña", confirmation_prompt=True)
    def crear_admin(nombre, username, password):
        """Crea un usuario Administrador."""
        from .utils import validar_password, validar_username
        err_user = validar_username(username)
        if err_user:
            raise click.ClickException(err_user)
        error = validar_password(password)
        if error:
            raise click.ClickException(error)
        _asegurar_roles()
        if Usuario.query.filter_by(username=username.lower().strip()).first():
            raise click.ClickException("Ya existe un usuario con ese nombre de usuario.")
        _crear_usuario(nombre, username, password, ROL_ADMIN, comision=0)
        db.session.commit()
        click.echo(f"✔ Administrador «{username}» creado exitosamente.")

    @app.cli.command("datos-demo")
    def datos_demo():
        """Carga un catálogo de servicios y datos de ejemplo (para probar)."""
        _asegurar_roles()
        if Usuario.query.first() is not None:
            raise click.ClickException("La base ya tiene usuarios; no se cargan datos demo.")

        admin = _crear_usuario("Administrador Demo", "admin", "Admin1234", ROL_ADMIN, 0, correo="admin@taller.local")
        m1 = _crear_usuario("Carlos Ramírez", "carlos", "Mecanico123", ROL_MECANICO, 15, correo="carlos@taller.local")
        m2 = _crear_usuario("Luis Hernández", "luis", "Mecanico123", ROL_MECANICO, 18, correo="luis@taller.local")

        catalogo = [
            ("Cambio de aceite y filtro", "Aceite sintético 5W-30 y filtro", 650),
            ("Afinación mayor", "Bujías, filtros, limpieza de inyectores", 1850),
            ("Cambio de balatas delanteras", "Incluye rectificado de discos", 950),
            ("Alineación y balanceo", "4 ruedas", 700),
            ("Diagnóstico con escáner", "Lectura y borrado de códigos", 400),
            ("Cambio de batería", "Mano de obra (batería aparte)", 250),
            ("Cambio de banda de distribución", "Incluye tensor y bomba de agua", 3200),
            ("Revisión de suspensión", "Amortiguadores, rótulas y terminales", 800),
            ("Servicio de A/C", "Carga de gas y revisión de fugas", 1100),
            ("Cambio de embrague", "Kit completo", 4200),
        ]
        servicios = []
        for nombre, desc, costo in catalogo:
            s = Servicio(nombre=nombre, descripcion=desc, costo_base=Decimal(costo), activo=True)
            db.session.add(s)
            servicios.append(s)

        clientes = [
            ("Juan Pérez López", "5512345678", "juan@correo.com", [("Nissan", "Versa", 2018, "ABC-123-A", "Gris")]),
            ("María González", "5587654321", None, [("Volkswagen", "Jetta", 2015, "XYZ-987-B", "Blanco")]),
            ("Roberto Sánchez", "5544332211", "roberto@correo.com",
             [("Toyota", "Corolla", 2020, "TOY-456-C", "Rojo"), ("Ford", "Ranger", 2017, "FRD-321-D", "Negro")]),
            ("Ana Martínez", "5599887766", None, [("Chevrolet", "Aveo", 2014, "CHV-654-E", "Azul")]),
        ]
        vehiculos = []
        for nombre, tel, correo, autos in clientes:
            c = Cliente(nombre_completo=nombre, telefono=tel, correo=correo)
            db.session.add(c)
            for marca, modelo, anio, placas, color in autos:
                v = Vehiculo(cliente=c, marca=marca, modelo=modelo, anio=anio, placas=placas, color=color)
                db.session.add(v)
                vehiculos.append(v)
        db.session.flush()

        rnd = random.Random(7)
        estados = ["Completado", "Completado", "Entregado", "En Proceso", "Pendiente", "Completado"]
        for i in range(14):
            estado = estados[i % len(estados)]
            ingreso = ahora() - timedelta(days=rnd.randint(0, 10), hours=rnd.randint(0, 6))
            orden = OrdenTrabajo(
                vehiculo=rnd.choice(vehiculos), mecanico=rnd.choice([m1, m2]),
                fecha_ingreso=ingreso, estado=estado,
                diagnostico_inicial="Revisión general solicitada por el cliente.",
                fecha_finalizacion=ingreso + timedelta(hours=rnd.randint(2, 30))
                if estado in ("Completado", "Entregado") else None,
            )
            db.session.add(orden)
            db.session.flush()
            for s in rnd.sample(servicios, rnd.randint(1, 3)):
                db.session.add(DetalleOrdenServicio(
                    id_orden=orden.id_orden, id_servicio=s.id_servicio,
                    costo_aplicado=s.costo_base, cantidad=1,
                ))
            orden.recalcular_total()
            db.session.add(HistorialEstado(orden=orden, estado_anterior=None, estado_nuevo="Pendiente",
                                           id_usuario=admin.id_usuario))
            if estado != "Pendiente":
                db.session.add(HistorialEstado(orden=orden, estado_anterior="Pendiente", estado_nuevo=estado,
                                               id_usuario=orden.id_mecanico))
        db.session.commit()
        click.echo("✔ Datos demo cargados.")
        click.echo("   admin@taller.local / Admin1234")
        click.echo("   carlos@taller.local y luis@taller.local / Mecanico123")
