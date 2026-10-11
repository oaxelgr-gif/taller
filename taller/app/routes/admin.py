"""Administración: dashboard, usuarios, catálogo de servicios y cortes de comisiones."""
from decimal import Decimal

from flask import Blueprint, current_app, jsonify, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.exc import DBAPIError, IntegrityError

from .. import db
from ..models import (
    ROL_ADMIN,
    ROL_MECANICO,
    CorteSemanal,
    DetalleOrdenServicio,
    OrdenTrabajo,
    Rol,
    Servicio,
    Usuario,
)
from ..services import ReglaNegocioError, calcular_pre_corte, cerrar_corte, kpis_admin, mecanicos_activos
from ..utils import (
    Paginacion,
    admin_required,
    ahora,
    formato_fecha,
    generar_pdf_corte,
    hoy,
    limpiar,
    pagina_actual,
    parse_decimal,
    parse_fecha,
    rango_semana,
    responder,
    validar_correo,
    validar_password,
    validar_username,
)

bp = Blueprint("admin", __name__)

MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


def _like(texto):
    return f"%{texto.replace('%', '').replace('_', '')}%"


def _marcado(nombre, defecto=True):
    """Checkbox con campo oculto previo (0): el último valor enviado es el vigente."""
    valores = request.form.getlist(nombre)
    if not valores:
        return defecto
    return valores[-1] in ("on", "1", "true")


def _mensaje_db(error):
    original = getattr(error, "orig", None)
    texto = str(original).splitlines()[0] if original else ""
    if "liquidad" in texto or "inalterable" in texto or "pagado" in texto:
        return texto.replace("ERROR:  ", "")
    return "La operación no fue permitida por la base de datos."


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@admin_required
def dashboard():
    actual = hoy()
    try:
        anio = int(request.args.get("anio", actual.year))
        mes = int(request.args.get("mes", actual.month))
        if not (1 <= mes <= 12 and 2000 <= anio <= 2100):
            raise ValueError
    except ValueError:
        anio, mes = actual.year, actual.month
    datos = kpis_admin(anio, mes)
    anios = list(range(actual.year - 3, actual.year + 1))
    if anio not in anios:
        anios.append(anio)
        anios.sort()
    return render_template(
        "admin/dashboard.html", k=datos, anio=anio, mes=mes, meses=MESES, anios=anios,
        nombre_mes=MESES[mes - 1],
    )


# ---------------------------------------------------------------------------
# Usuarios
# ---------------------------------------------------------------------------
@bp.route("/usuarios")
@login_required
@admin_required
def usuarios():
    q = limpiar(request.args.get("q"))
    rol = request.args.get("rol")
    consulta = Usuario.query.join(Rol, Rol.id_rol == Usuario.id_rol)
    if q:
        patron = _like(q)
        consulta = consulta.filter(or_(
            Usuario.nombre_completo.ilike(patron),
            Usuario.username.ilike(patron),
            Usuario.correo.ilike(patron)
        ))
    if rol in (ROL_ADMIN, ROL_MECANICO):
        consulta = consulta.filter(Rol.nombre == rol)
    consulta = consulta.order_by(Usuario.activo.desc(), Usuario.nombre_completo)
    pag = Paginacion(consulta, pagina_actual(), current_app.config["POR_PAGINA"])

    ids = [u.id_usuario for u in pag.items]
    conteo = {}
    if ids:
        conteo = dict(
            db.session.query(OrdenTrabajo.id_mecanico, func.count(OrdenTrabajo.id_orden))
            .filter(OrdenTrabajo.id_mecanico.in_(ids)).group_by(OrdenTrabajo.id_mecanico).all()
        )
    plantilla = "admin/_tabla_usuarios.html" if request.args.get("partial") else "admin/usuarios.html"
    return render_template(plantilla, pag=pag, q=q, rol=rol, conteo=conteo,
                           roles=Rol.query.order_by(Rol.id_rol).all())


def _admins_activos_restantes(excluir_id):
    return (
        Usuario.query.join(Rol, Rol.id_rol == Usuario.id_rol)
        .filter(Rol.nombre == ROL_ADMIN, Usuario.activo.is_(True), Usuario.id_usuario != excluir_id)
        .count()
    )


@bp.route("/usuarios/guardar", methods=["POST"])
@login_required
@admin_required
def guardar_usuario():
    id_usuario = request.form.get("id_usuario")
    try:
        nombre = limpiar(request.form.get("nombre_completo"), 120)
        username = limpiar(request.form.get("username"), 50).lower()
        correo = limpiar(request.form.get("correo"), 100).lower() or None
        rol_nombre = request.form.get("rol")
        password = request.form.get("password") or ""
        activo = _marcado("activo")
        comision = parse_decimal(request.form.get("porcentaje_comision_defecto") or "0",
                                 "El porcentaje de comisión", Decimal("0"), Decimal("100"))

        if not nombre:
            raise ValueError("El nombre completo es obligatorio.")
        err_user = validar_username(username)
        if err_user:
            raise ValueError(err_user)
        if correo and not validar_correo(correo):
            raise ValueError("Captura un correo válido o déjalo en blanco.")
        rol = Rol.query.filter_by(nombre=rol_nombre).first()
        if rol is None:
            raise ValueError("Selecciona un rol válido.")

        if id_usuario:
            usuario = db.session.get(Usuario, int(id_usuario))
            if usuario is None:
                return responder(False, "Usuario no encontrado.", status=404)
            if usuario.id_usuario == current_user.id_usuario:
                if rol.nombre != ROL_ADMIN:
                    raise ValueError("No puedes quitarte a ti mismo el rol de administrador.")
                if not activo:
                    raise ValueError("No puedes desactivar tu propia cuenta.")
            elif usuario.es_admin and (rol.nombre != ROL_ADMIN or not activo):
                if _admins_activos_restantes(usuario.id_usuario) == 0:
                    raise ValueError("Debe quedar al menos un administrador activo.")
            mensaje = "Usuario actualizado correctamente."
        else:
            if not password:
                raise ValueError("La contraseña es obligatoria para un usuario nuevo.")
            usuario = Usuario()
            mensaje = "Usuario creado correctamente."

        dup_username = Usuario.query.filter(func.lower(Usuario.username) == username).first()
        if dup_username and dup_username is not usuario:
            raise ValueError("Ya existe otro usuario con ese nombre de usuario.")
        if correo:
            dup_correo = Usuario.query.filter(func.lower(Usuario.correo) == correo).first()
            if dup_correo and dup_correo is not usuario:
                raise ValueError("Ya existe otro usuario con ese correo.")

        if password:
            error = validar_password(password)
            if error:
                raise ValueError(error)
            usuario.set_password(password)

        usuario.nombre_completo = nombre
        usuario.username = username
        usuario.correo = correo
        usuario.id_rol = rol.id_rol
        usuario.porcentaje_comision_defecto = comision
        usuario.activo = activo
        if usuario.id_usuario is None:
            db.session.add(usuario)
        db.session.commit()
        return responder(True, mensaje, url_for("admin.usuarios"))
    except ValueError as e:
        db.session.rollback()
        return responder(False, str(e))
    except IntegrityError:
        db.session.rollback()
        return responder(False, "El nombre de usuario o correo ya está en uso.")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al guardar usuario")
        return responder(False, "No se pudo guardar el usuario.", status=500)


@bp.route("/usuarios/<int:id_usuario>/activo", methods=["POST"])
@login_required
@admin_required
def alternar_usuario(id_usuario):
    usuario = db.get_or_404(Usuario, id_usuario)
    if usuario.id_usuario == current_user.id_usuario:
        return responder(False, "No puedes desactivar tu propia cuenta.")
    if usuario.activo and usuario.es_admin and _admins_activos_restantes(usuario.id_usuario) == 0:
        return responder(False, "Debe quedar al menos un administrador activo.")
    try:
        usuario.activo = not usuario.activo
        db.session.commit()
        return responder(True, f"Usuario {'activado' if usuario.activo else 'desactivado'}.",
                         url_for("admin.usuarios"), activo=usuario.activo)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al alternar usuario")
        return responder(False, "No se pudo cambiar el estado del usuario.", status=500)


# ---------------------------------------------------------------------------
# Catálogo de servicios
# ---------------------------------------------------------------------------
@bp.route("/servicios")
@login_required
@admin_required
def servicios():
    q = limpiar(request.args.get("q"))
    estado = request.args.get("estado")
    consulta = Servicio.query
    if q:
        patron = _like(q)
        consulta = consulta.filter(or_(Servicio.nombre.ilike(patron), Servicio.descripcion.ilike(patron)))
    if estado == "activos":
        consulta = consulta.filter(Servicio.activo.is_(True))
    elif estado == "inactivos":
        consulta = consulta.filter(Servicio.activo.is_(False))
    consulta = consulta.order_by(Servicio.activo.desc(), Servicio.nombre)
    pag = Paginacion(consulta, pagina_actual(), current_app.config["POR_PAGINA"])

    ids = [s.id_servicio for s in pag.items]
    usos = {}
    if ids:
        usos = dict(
            db.session.query(DetalleOrdenServicio.id_servicio, func.count(DetalleOrdenServicio.id_detalle))
            .filter(DetalleOrdenServicio.id_servicio.in_(ids))
            .group_by(DetalleOrdenServicio.id_servicio).all()
        )
    plantilla = "admin/_tabla_servicios.html" if request.args.get("partial") else "admin/servicios.html"
    return render_template(plantilla, pag=pag, q=q, estado=estado, usos=usos)


@bp.route("/servicios/guardar", methods=["POST"])
@login_required
@admin_required
def guardar_servicio():
    id_servicio = request.form.get("id_servicio")
    try:
        nombre = limpiar(request.form.get("nombre"), 100)
        descripcion = limpiar(request.form.get("descripcion")) or None
        costo = parse_decimal(request.form.get("costo_base"), "El costo base", Decimal("0"), Decimal("99999999.99"))
        activo = _marcado("activo")
        if not nombre:
            raise ValueError("El nombre del servicio es obligatorio.")
        if id_servicio:
            servicio = db.session.get(Servicio, int(id_servicio))
            if servicio is None:
                return responder(False, "Servicio no encontrado.", status=404)
            mensaje = "Servicio actualizado. Los cambios de precio no afectan órdenes ya registradas."
        else:
            servicio = Servicio()
            db.session.add(servicio)
            mensaje = "Servicio agregado al catálogo."
        servicio.nombre, servicio.descripcion = nombre, descripcion
        servicio.costo_base, servicio.activo = costo, activo
        db.session.commit()
        return responder(True, mensaje, url_for("admin.servicios"))
    except ValueError as e:
        db.session.rollback()
        return responder(False, str(e))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al guardar servicio")
        return responder(False, "No se pudo guardar el servicio.", status=500)


@bp.route("/servicios/<int:id_servicio>/activo", methods=["POST"])
@login_required
@admin_required
def alternar_servicio(id_servicio):
    servicio = db.get_or_404(Servicio, id_servicio)
    try:
        servicio.activo = not servicio.activo
        db.session.commit()
        return responder(True, f"Servicio {'activado' if servicio.activo else 'desactivado'}.",
                         url_for("admin.servicios"), activo=servicio.activo)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al alternar servicio")
        return responder(False, "No se pudo cambiar el estado del servicio.", status=500)


@bp.route("/servicios/<int:id_servicio>/eliminar", methods=["POST"])
@login_required
@admin_required
def eliminar_servicio(id_servicio):
    servicio = db.get_or_404(Servicio, id_servicio)
    if servicio.detalles.first():
        return responder(False, "El servicio ya se usó en órdenes; desactívalo en lugar de eliminarlo.")
    try:
        db.session.delete(servicio)
        db.session.commit()
        return responder(True, "Servicio eliminado del catálogo.", url_for("admin.servicios"))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al eliminar servicio")
        return responder(False, "No se pudo eliminar el servicio.", status=500)


# ---------------------------------------------------------------------------
# Cortes semanales y comisiones
# ---------------------------------------------------------------------------
def _leer_parametros_corte(datos):
    id_mecanico = datos.get("id_mecanico")
    if not str(id_mecanico or "").isdigit():
        raise ValueError("Selecciona un mecánico.")
    inicio = parse_fecha(datos.get("fecha_inicio"), "La fecha inicial")
    fin = parse_fecha(datos.get("fecha_fin"), "La fecha final")
    if not inicio or not fin:
        raise ValueError("Indica el periodo del corte (fecha inicial y final).")
    if fin < inicio:
        raise ValueError("La fecha final no puede ser anterior a la inicial.")
    porcentaje = None
    if str(datos.get("porcentaje") or "").strip() != "":
        porcentaje = parse_decimal(datos.get("porcentaje"), "El porcentaje", Decimal("0"), Decimal("100"))
    return int(id_mecanico), inicio, fin, porcentaje


def _serializar_pre_corte(pre):
    return {
        "ok": True,
        "mecanico": pre["mecanico"].nombre_completo,
        "porcentaje": str(pre["porcentaje"]),
        "porcentaje_defecto": str(pre["mecanico"].porcentaje_comision_defecto or 0),
        "total": str(pre["total"]),
        "comision": str(pre["comision"]),
        "cantidad": pre["cantidad"],
        "en_curso": pre["en_curso"],
        "ordenes": [
            {
                "id": o.id_orden,
                "folio": o.folio,
                "fecha": formato_fecha(o.fecha_finalizacion or o.fecha_ingreso),
                "vehiculo": f"{o.vehiculo.descripcion} · {o.vehiculo.placas}",
                "cliente": o.vehiculo.cliente.nombre_completo,
                "estado": o.estado,
                "total": str(o.total_costo or 0),
                "url": url_for("ordenes.detalle", id_orden=o.id_orden),
            }
            for o in pre["ordenes"]
        ],
    }


@bp.route("/comisiones")
@login_required
@admin_required
def comisiones():
    lunes, domingo = rango_semana()
    filtro_mec = request.args.get("mecanico", "")
    filtro_estatus = request.args.get("estatus")
    consulta = CorteSemanal.query
    if filtro_mec.isdigit():
        consulta = consulta.filter(CorteSemanal.id_mecanico == int(filtro_mec))
    if filtro_estatus in ("Pendiente", "Pagado"):
        consulta = consulta.filter(CorteSemanal.estatus_pago == filtro_estatus)
    consulta = consulta.order_by(CorteSemanal.id_corte.desc())
    pag = Paginacion(consulta, pagina_actual(), current_app.config["POR_PAGINA"])
    por_pagar = (
        db.session.query(func.coalesce(func.sum(CorteSemanal.monto_comision_pagar), 0))
        .filter(CorteSemanal.estatus_pago == "Pendiente").scalar()
    )
    return render_template(
        "admin/comisiones.html", mecanicos=mecanicos_activos(), pag=pag,
        inicio=lunes, fin=domingo, filtro_mec=filtro_mec, filtro_estatus=filtro_estatus,
        por_pagar=Decimal(por_pagar),
    )


@bp.route("/comisiones/calcular", methods=["POST"])
@login_required
@admin_required
def calcular_comisiones():
    """Pre-corte: calcula sin guardar (el porcentaje puede ajustarse temporalmente)."""
    datos = request.get_json(silent=True) or request.form
    try:
        id_mecanico, inicio, fin, porcentaje = _leer_parametros_corte(datos)
        pre = calcular_pre_corte(id_mecanico, inicio, fin, porcentaje)
        return jsonify(_serializar_pre_corte(pre))
    except (ValueError, ReglaNegocioError) as e:
        return jsonify({"ok": False, "mensaje": str(e)}), 400
    except Exception:
        current_app.logger.exception("Error al calcular pre-corte")
        return jsonify({"ok": False, "mensaje": "No se pudo calcular el corte."}), 500


@bp.route("/comisiones/cerrar", methods=["POST"])
@login_required
@admin_required
def cerrar_corte_ruta():
    datos = request.get_json(silent=True) or request.form
    try:
        id_mecanico, inicio, fin, porcentaje = _leer_parametros_corte(datos)
        if porcentaje is None:
            mecanico = db.session.get(Usuario, id_mecanico)
            porcentaje = mecanico.porcentaje_comision_defecto if mecanico else None
            if porcentaje is None:
                porcentaje = Decimal("15.00")
        corte = cerrar_corte(id_mecanico, inicio, fin, porcentaje, current_user)

        # Si el usuario vio un total en pantalla, debe coincidir con el que se congela.
        confirmado = str(datos.get("total_confirmado") or "").strip()
        if confirmado:
            if parse_decimal(confirmado, "El total confirmado") != corte.total_reparaciones_monto:
                raise ReglaNegocioError(
                    "Las órdenes del periodo cambiaron desde que calculaste el corte. "
                    "Vuelve a calcular antes de cerrar."
                )
        db.session.commit()
        return responder(True, f"Corte {corte.folio} cerrado correctamente.",
                         url_for("admin.detalle_corte", id_corte=corte.id_corte), id_corte=corte.id_corte)
    except (ValueError, ReglaNegocioError) as e:
        db.session.rollback()
        return responder(False, str(e), url_for("admin.comisiones"))
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e), url_for("admin.comisiones"))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al cerrar corte")
        return responder(False, "No se pudo cerrar el corte.", url_for("admin.comisiones"), status=500)


@bp.route("/cortes/<int:id_corte>")
@login_required
@admin_required
def detalle_corte(id_corte):
    corte = db.get_or_404(CorteSemanal, id_corte)
    ordenes = corte.ordenes.order_by(OrdenTrabajo.id_orden).all()
    return render_template("admin/corte_detalle.html", corte=corte, ordenes=ordenes,
                           vista_admin=True, ahora=ahora())


@bp.route("/cortes/<int:id_corte>/pdf")
@login_required
@admin_required
def pdf_corte(id_corte):
    corte = db.get_or_404(CorteSemanal, id_corte)
    ordenes = corte.ordenes.order_by(OrdenTrabajo.id_orden).all()
    buffer = generar_pdf_corte(corte, ordenes, current_app.config["TALLER_NOMBRE"])
    return send_file(buffer, mimetype="application/pdf", download_name=f"corte-{corte.folio}.pdf")


@bp.route("/cortes/<int:id_corte>/pagar", methods=["POST"])
@login_required
@admin_required
def pagar_corte(id_corte):
    corte = db.get_or_404(CorteSemanal, id_corte)
    destino = url_for("admin.detalle_corte", id_corte=id_corte)
    if corte.estatus_pago == "Pagado":
        return responder(False, "Este corte ya fue marcado como pagado.", destino)
    try:
        corte.estatus_pago = "Pagado"
        corte.fecha_pago = ahora()
        db.session.commit()
        return responder(True, f"Corte {corte.folio} marcado como pagado.", destino)
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e), destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al marcar corte como pagado")
        return responder(False, "No se pudo marcar el corte como pagado.", destino, status=500)
