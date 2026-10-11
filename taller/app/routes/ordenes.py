"""Órdenes de trabajo: alta, listado (lista/kanban), detalle, servicios y estados."""
from flask import Blueprint, current_app, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from sqlalchemy.exc import DBAPIError

from .. import db
from ..models import (
    ESTADOS,
    Cliente,
    DetalleOrdenPieza,
    DetalleOrdenServicio,
    HistorialEstado,
    OrdenTrabajo,
    Servicio,
    Usuario,
    Vehiculo,
)
from ..services import (
    ReglaNegocioError,
    cambiar_estado,
    estados_permitidos,
    mecanicos_activos,
    puede_editar_orden,
    puede_ver_orden,
)
from ..utils import (
    Paginacion,
    admin_required,
    ahora,
    limpiar,
    limites_dias,
    pagina_actual,
    parse_decimal,
    parse_entero,
    parse_fecha,
    parse_fecha_hora_local,
    responder,
    staff_required,
)

bp = Blueprint("ordenes", __name__)

MAX_KANBAN = 30


def _like(texto):
    return f"%{texto.replace('%', '').replace('_', '')}%"


def _base_query():
    """Órdenes visibles para el usuario (los mecánicos sólo ven las suyas)."""
    consulta = (
        OrdenTrabajo.query
        .join(Vehiculo, Vehiculo.id_vehiculo == OrdenTrabajo.id_vehiculo)
        .join(Cliente, Cliente.id_cliente == Vehiculo.id_cliente)
    )
    if not current_user.es_admin:
        consulta = consulta.filter(OrdenTrabajo.id_mecanico == current_user.id_usuario)
    return consulta


def aplicar_filtros(consulta, args):
    q = limpiar(args.get("q"))
    if q:
        patron = _like(q)
        condiciones = [
            Vehiculo.placas.ilike(patron), Vehiculo.marca.ilike(patron),
            Vehiculo.modelo.ilike(patron), Cliente.nombre_completo.ilike(patron),
        ]
        digitos = q.upper().replace("OT-", "").lstrip("0")
        if digitos.isdigit():
            condiciones.append(OrdenTrabajo.id_orden == int(digitos))
        consulta = consulta.filter(or_(*condiciones))
    estado = args.get("estado")
    if estado in ESTADOS:
        consulta = consulta.filter(OrdenTrabajo.estado == estado)
    if current_user.es_admin and args.get("mecanico", "").isdigit():
        consulta = consulta.filter(OrdenTrabajo.id_mecanico == int(args["mecanico"]))
    try:
        desde, hasta = parse_fecha(args.get("desde")), parse_fecha(args.get("hasta"))
    except ValueError:
        desde = hasta = None
    if desde:
        consulta = consulta.filter(OrdenTrabajo.fecha_ingreso >= limites_dias(desde, desde)[0])
    if hasta:
        consulta = consulta.filter(OrdenTrabajo.fecha_ingreso < limites_dias(hasta, hasta)[1])
    return consulta


@bp.route("/")
@login_required
@staff_required
def index():
    vista = request.args.get("vista", "lista")
    consulta = aplicar_filtros(_base_query(), request.args)

    if vista == "kanban" and not request.args.get("partial"):
        columnas = []
        for estado in ("Pendiente", "En Proceso", "Completado", "Entregado"):
            q_estado = consulta.filter(OrdenTrabajo.estado == estado)
            total = q_estado.order_by(None).count()
            items = q_estado.order_by(OrdenTrabajo.fecha_ingreso.desc()).limit(MAX_KANBAN).all()
            columnas.append({"estado": estado, "items": items, "total": total})
        return render_template(
            "ordenes/index.html", vista="kanban", columnas=columnas, pag=None,
            mecanicos=mecanicos_activos(), args=request.args,
            permitidos=lambda o: estados_permitidos(o, current_user),
        )

    consulta = consulta.order_by(OrdenTrabajo.id_orden.desc())
    pag = Paginacion(consulta, pagina_actual(), current_app.config["POR_PAGINA"])
    plantilla = "ordenes/_tabla.html" if request.args.get("partial") else "ordenes/index.html"
    return render_template(
        plantilla, vista="lista", pag=pag, columnas=None,
        mecanicos=mecanicos_activos(), args=request.args,
        permitidos=lambda o: estados_permitidos(o, current_user),
    )


# ---------------------------------------------------------------------------
# Alta de orden
# ---------------------------------------------------------------------------
def _leer_lineas(form):
    ids = form.getlist("servicio_id[]")
    costos = form.getlist("costo[]")
    cantidades = form.getlist("cantidad[]")
    lineas = []
    for i, sid in enumerate(ids):
        if not str(sid).strip():
            continue
        id_servicio = parse_entero(sid, "Servicio", 1)
        servicio = db.session.get(Servicio, id_servicio)
        if servicio is None or not servicio.activo:
            raise ValueError("Uno de los servicios seleccionados ya no está disponible.")
        costo = parse_decimal(costos[i] if i < len(costos) else servicio.costo_base,
                              f"Costo de «{servicio.nombre}»")
        cantidad = parse_entero(cantidades[i] if i < len(cantidades) else 1,
                                f"Cantidad de «{servicio.nombre}»", 1, 999)
        lineas.append((servicio, costo, cantidad))
    return lineas


@bp.route("/nueva", methods=["GET", "POST"])
@login_required
@staff_required
def nueva():
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.nombre).all()
    if request.method == "GET":
        vehiculo = None
        if request.args.get("vehiculo", "").isdigit():
            vehiculo = db.session.get(Vehiculo, int(request.args["vehiculo"]))
        return render_template(
            "ordenes/crear.html", servicios=servicios, mecanicos=mecanicos_activos(),
            vehiculo_preseleccionado=vehiculo, ahora=ahora(),
        )

    try:
        id_vehiculo = parse_entero(request.form.get("id_vehiculo"), "El vehículo")
        vehiculo = db.session.get(Vehiculo, id_vehiculo)
        if vehiculo is None:
            raise ValueError("Selecciona un vehículo válido.")

        if current_user.es_admin:
            id_mecanico = parse_entero(request.form.get("id_mecanico"), "El mecánico responsable")
            mecanico = db.session.get(Usuario, id_mecanico)
            if mecanico is None or not mecanico.es_mecanico or not mecanico.activo:
                raise ValueError("Selecciona un mecánico activo como responsable.")
        else:
            mecanico = current_user

        ahora_dt = ahora()
        fecha_ingreso = parse_fecha_hora_local(request.form.get("fecha_ingreso"), "La fecha de ingreso") or ahora_dt
        if fecha_ingreso > ahora_dt:
            raise ValueError("La fecha de ingreso no puede ser futura.")
        entrega = parse_fecha_hora_local(request.form.get("fecha_entrega_estimada"), "La fecha de entrega estimada")
        if entrega and entrega < fecha_ingreso:
            raise ValueError("La entrega estimada no puede ser anterior a la fecha de ingreso.")

        kilometraje = parse_entero(request.form.get("kilometraje"), "El kilometraje", 0, 3_000_000,
                                   obligatorio=False)
        diagnostico = limpiar(request.form.get("diagnostico_inicial"))
        if not diagnostico:
            raise ValueError("Captura el diagnóstico inicial del vehículo.")
        lineas = _leer_lineas(request.form)

        orden = OrdenTrabajo(
            id_vehiculo=vehiculo.id_vehiculo, id_mecanico=mecanico.id_usuario,
            fecha_ingreso=fecha_ingreso, fecha_entrega_estimada=entrega,
            estado="Pendiente", diagnostico_inicial=diagnostico, kilometraje=kilometraje,
        )
        db.session.add(orden)
        db.session.flush()
        for servicio, costo, cantidad in lineas:
            db.session.add(DetalleOrdenServicio(
                id_orden=orden.id_orden, id_servicio=servicio.id_servicio,
                costo_aplicado=costo, cantidad=cantidad,
            ))
        db.session.add(HistorialEstado(
            id_orden=orden.id_orden, estado_anterior=None, estado_nuevo="Pendiente",
            id_usuario=current_user.id_usuario,
        ))
        orden.recalcular_total()
        db.session.commit()
        return responder(True, f"Orden {orden.folio} registrada correctamente.",
                         url_for("ordenes.detalle", id_orden=orden.id_orden))
    except ValueError as e:
        db.session.rollback()
        return responder(False, str(e))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al crear orden")
        return responder(False, "No se pudo registrar la orden de trabajo.", status=500)


# ---------------------------------------------------------------------------
# Detalle y edición
# ---------------------------------------------------------------------------
def _orden_o_404(id_orden):
    orden = db.get_or_404(OrdenTrabajo, id_orden)
    if not puede_ver_orden(orden, current_user):
        from flask import abort
        abort(403)
    return orden


@bp.route("/<int:id_orden>")
@login_required
@staff_required
def detalle(id_orden):
    orden = _orden_o_404(id_orden)
    servicios = Servicio.query.filter_by(activo=True).order_by(Servicio.nombre).all()
    return render_template(
        "ordenes/detalle.html", orden=orden, servicios=servicios,
        permitidos=estados_permitidos(orden, current_user),
        puede_editar=puede_editar_orden(orden, current_user),
        puede_datos=(not orden.liquidado_en_corte),
        mecanicos=mecanicos_activos() if current_user.es_admin else [],
        ahora=ahora(),
    )


@bp.route("/<int:id_orden>/datos", methods=["POST"])
@login_required
@staff_required
def actualizar_datos(id_orden):
    orden = _orden_o_404(id_orden)
    if orden.liquidado_en_corte:
        return responder(False, "La orden ya fue liquidada y no puede modificarse.")
    try:
        orden.diagnostico_inicial = limpiar(request.form.get("diagnostico_inicial")) or orden.diagnostico_inicial
        orden.observaciones_finales = limpiar(request.form.get("observaciones_finales")) or None
        orden.kilometraje = parse_entero(request.form.get("kilometraje"), "El kilometraje", 0, 3_000_000,
                                         obligatorio=False)
        entrega = parse_fecha_hora_local(request.form.get("fecha_entrega_estimada"), "La entrega estimada")
        if entrega and entrega < orden.fecha_ingreso:
            raise ValueError("La entrega estimada no puede ser anterior a la fecha de ingreso.")
        orden.fecha_entrega_estimada = entrega

        if current_user.es_admin:
            nueva_fecha = parse_fecha_hora_local(request.form.get("fecha_ingreso"), "La fecha de ingreso")
            if nueva_fecha is not None:
                if nueva_fecha > ahora():
                    raise ValueError("La fecha de ingreso no puede ser futura.")
                orden.fecha_ingreso = nueva_fecha
            if request.form.get("id_mecanico"):
                mecanico = db.session.get(Usuario, parse_entero(request.form["id_mecanico"], "El mecánico"))
                if mecanico is None or not mecanico.es_mecanico:
                    raise ValueError("Selecciona un mecánico válido.")
                orden.id_mecanico = mecanico.id_usuario
        db.session.commit()
        return responder(True, "Datos de la orden actualizados.", url_for("ordenes.detalle", id_orden=id_orden))
    except ValueError as e:
        db.session.rollback()
        return responder(False, str(e))
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al actualizar orden")
        return responder(False, "No se pudo actualizar la orden.", status=500)


def _mensaje_db(error):
    """Extrae el mensaje legible de una excepción RAISE de PostgreSQL."""
    original = getattr(error, "orig", None)
    texto = str(original).splitlines()[0] if original else ""
    if "liquidad" in texto or "inalterable" in texto:
        return texto.replace("ERROR:  ", "")
    return "La operación no fue permitida por la base de datos."


@bp.route("/<int:id_orden>/estado", methods=["POST"])
@login_required
@staff_required
def cambiar_estado_orden(id_orden):
    orden = _orden_o_404(id_orden)
    nuevo = request.form.get("estado") or (request.get_json(silent=True) or {}).get("estado")
    try:
        cambiar_estado(orden, nuevo, current_user)
        db.session.commit()
        return responder(
            True, f"{orden.folio} ahora está «{orden.estado}».",
            request.form.get("next") or url_for("ordenes.detalle", id_orden=id_orden),
            estado=orden.estado, id_orden=orden.id_orden,
        )
    except ReglaNegocioError as e:
        db.session.rollback()
        return responder(False, str(e), request.form.get("next") or url_for("ordenes.detalle", id_orden=id_orden))
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al cambiar estado")
        return responder(False, "No se pudo cambiar el estado.", status=500)


# ---------------------------------------------------------------------------
# Servicios de la orden
# ---------------------------------------------------------------------------
def _validar_edicion(orden):
    if not puede_editar_orden(orden, current_user):
        if orden.liquidado_en_corte:
            raise ReglaNegocioError("La orden ya fue liquidada y no puede modificarse.")
        raise ReglaNegocioError("No puedes modificar los servicios de esta orden en su estado actual.")


@bp.route("/<int:id_orden>/servicios", methods=["POST"])
@login_required
@staff_required
def agregar_servicio(id_orden):
    orden = _orden_o_404(id_orden)
    destino = url_for("ordenes.detalle", id_orden=id_orden)
    try:
        _validar_edicion(orden)
        servicio = db.session.get(Servicio, parse_entero(request.form.get("id_servicio"), "Servicio", 1))
        if servicio is None or not servicio.activo:
            raise ValueError("El servicio seleccionado no está disponible.")
        costo_txt = request.form.get("costo")
        costo = parse_decimal(costo_txt if costo_txt not in (None, "") else servicio.costo_base, "El costo")
        cantidad = parse_entero(request.form.get("cantidad") or 1, "La cantidad", 1, 999)
        db.session.add(DetalleOrdenServicio(
            id_orden=orden.id_orden, id_servicio=servicio.id_servicio,
            costo_aplicado=costo, cantidad=cantidad,
        ))
        orden.recalcular_total()
        db.session.commit()
        return responder(True, f"Servicio «{servicio.nombre}» agregado.", destino)
    except (ValueError, ReglaNegocioError) as e:
        db.session.rollback()
        return responder(False, str(e), destino)
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e), destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al agregar servicio")
        return responder(False, "No se pudo agregar el servicio.", destino, status=500)


@bp.route("/<int:id_orden>/servicios/<int:id_detalle>/actualizar", methods=["POST"])
@login_required
@staff_required
def actualizar_servicio(id_orden, id_detalle):
    orden = _orden_o_404(id_orden)
    destino = url_for("ordenes.detalle", id_orden=id_orden)
    try:
        _validar_edicion(orden)
        detalle = db.session.get(DetalleOrdenServicio, id_detalle)
        if detalle is None or detalle.id_orden != orden.id_orden:
            raise ValueError("Servicio no encontrado en la orden.")
        detalle.costo_aplicado = parse_decimal(request.form.get("costo"), "El costo")
        detalle.cantidad = parse_entero(request.form.get("cantidad"), "La cantidad", 1, 999)
        orden.recalcular_total()
        db.session.commit()
        return responder(True, "Servicio actualizado.", destino)
    except (ValueError, ReglaNegocioError) as e:
        db.session.rollback()
        return responder(False, str(e), destino)
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e), destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al actualizar servicio")
        return responder(False, "No se pudo actualizar el servicio.", destino, status=500)


@bp.route("/<int:id_orden>/servicios/<int:id_detalle>/eliminar", methods=["POST"])
@login_required
@staff_required
def quitar_servicio(id_orden, id_detalle):
    orden = _orden_o_404(id_orden)
    destino = url_for("ordenes.detalle", id_orden=id_orden)
    try:
        _validar_edicion(orden)
        detalle = db.session.get(DetalleOrdenServicio, id_detalle)
        if detalle is None or detalle.id_orden != orden.id_orden:
            raise ValueError("Servicio no encontrado en la orden.")
        if orden.es_cobrable and len(orden.detalles) <= 1:
            raise ValueError("Una orden completada debe conservar al menos un servicio.")
        db.session.delete(detalle)
        db.session.flush()
        db.session.expire(orden, ["detalles"])
        orden.recalcular_total()
        db.session.commit()
        return responder(True, "Servicio eliminado de la orden.", destino)
    except (ValueError, ReglaNegocioError) as e:
        db.session.rollback()
        return responder(False, str(e), destino)
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e), destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al quitar servicio")
        return responder(False, "No se pudo eliminar el servicio.", destino, status=500)


# ---------------------------------------------------------------------------
# Piezas y Refacciones de la orden (Facturación)
# ---------------------------------------------------------------------------
@bp.route("/<int:id_orden>/piezas", methods=["POST"])
@login_required
@staff_required
def agregar_pieza(id_orden):
    orden = _orden_o_404(id_orden)
    destino = url_for("ordenes.detalle", id_orden=id_orden)
    try:
        _validar_edicion(orden)
        descripcion = limpiar(request.form.get("descripcion"), 150)
        if not descripcion:
            raise ValueError("Captura el nombre o descripción de la pieza/refacción.")
        numero_parte = limpiar(request.form.get("numero_parte"), 50) or None
        costo_txt = request.form.get("costo_unitario") or request.form.get("costo")
        costo = parse_decimal(costo_txt, "El costo de la pieza")
        cantidad = parse_entero(request.form.get("cantidad") or 1, "La cantidad", 1, 999)

        db.session.add(DetalleOrdenPieza(
            id_orden=orden.id_orden, descripcion=descripcion,
            numero_parte=numero_parte, costo_unitario=costo, cantidad=cantidad,
        ))
        orden.recalcular_total()
        db.session.commit()
        return responder(True, f"Pieza «{descripcion}» agregada a la factura.", destino)
    except (ValueError, ReglaNegocioError) as e:
        db.session.rollback()
        return responder(False, str(e), destino)
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e), destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al agregar pieza")
        return responder(False, "No se pudo agregar la pieza.", destino, status=500)


@bp.route("/<int:id_orden>/piezas/<int:id_pieza>/actualizar", methods=["POST"])
@login_required
@staff_required
def actualizar_pieza(id_orden, id_pieza):
    orden = _orden_o_404(id_orden)
    destino = url_for("ordenes.detalle", id_orden=id_orden)
    try:
        _validar_edicion(orden)
        pieza = db.session.get(DetalleOrdenPieza, id_pieza)
        if pieza is None or pieza.id_orden != orden.id_orden:
            raise ValueError("Pieza no encontrada en la orden.")
        desc = limpiar(request.form.get("descripcion"), 150)
        if desc:
            pieza.descripcion = desc
        if request.form.get("numero_parte") is not None:
            pieza.numero_parte = limpiar(request.form.get("numero_parte"), 50) or None
        costo_txt = request.form.get("costo_unitario") or request.form.get("costo")
        if costo_txt not in (None, ""):
            pieza.costo_unitario = parse_decimal(costo_txt, "El costo de la pieza")
        if request.form.get("cantidad"):
            pieza.cantidad = parse_entero(request.form.get("cantidad"), "La cantidad", 1, 999)
        orden.recalcular_total()
        db.session.commit()
        return responder(True, "Pieza actualizada.", destino)
    except (ValueError, ReglaNegocioError) as e:
        db.session.rollback()
        return responder(False, str(e), destino)
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e), destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al actualizar pieza")
        return responder(False, "No se pudo actualizar la pieza.", destino, status=500)


@bp.route("/<int:id_orden>/piezas/<int:id_pieza>/eliminar", methods=["POST"])
@login_required
@staff_required
def quitar_pieza(id_orden, id_pieza):
    orden = _orden_o_404(id_orden)
    destino = url_for("ordenes.detalle", id_orden=id_orden)
    try:
        _validar_edicion(orden)
        pieza = db.session.get(DetalleOrdenPieza, id_pieza)
        if pieza is None or pieza.id_orden != orden.id_orden:
            raise ValueError("Pieza no encontrada en la orden.")
        db.session.delete(pieza)
        db.session.flush()
        db.session.expire(orden, ["piezas"])
        orden.recalcular_total()
        db.session.commit()
        return responder(True, "Pieza eliminada de la orden.", destino)
    except (ValueError, ReglaNegocioError) as e:
        db.session.rollback()
        return responder(False, str(e), destino)
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e), destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al quitar pieza")
        return responder(False, "No se pudo eliminar la pieza.", destino, status=500)


@bp.route("/<int:id_orden>/eliminar", methods=["POST"])
@login_required
@admin_required
def eliminar(id_orden):
    orden = db.get_or_404(OrdenTrabajo, id_orden)
    if orden.liquidado_en_corte:
        return responder(False, "La orden ya fue liquidada y no puede eliminarse.")
    try:
        db.session.delete(orden)
        db.session.commit()
        return responder(True, "Orden eliminada.", url_for("ordenes.index"))
    except DBAPIError as e:
        db.session.rollback()
        return responder(False, _mensaje_db(e))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al eliminar orden")
        return responder(False, "No se pudo eliminar la orden.", status=500)
