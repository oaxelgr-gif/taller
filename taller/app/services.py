"""Lógica de negocio: cambios de estado, comisiones, cortes semanales y KPIs."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import current_app
from sqlalchemy import Date, cast, func

from . import db
from .models import (
    ROL_MECANICO,
    ESTADOS,
    ESTADOS_ACTIVOS,
    ESTADOS_COBRABLES,
    CorteSemanal,
    DetalleOrdenPieza,
    DetalleOrdenServicio,
    HistorialEstado,
    OrdenTrabajo,
    Rol,
    Servicio,
    Usuario,
)
from .utils import ahora, hoy, limites_dias, rango_mes, rango_semana

CENTAVOS = Decimal("0.01")

# Transiciones permitidas para un mecánico (sólo hacia adelante)
TRANSICIONES_MECANICO = {
    "Pendiente": ["En Proceso"],
    "En Proceso": ["Completado"],
}


class ReglaNegocioError(Exception):
    """Error de validación de negocio; el mensaje es apto para mostrarse al usuario."""


# ---------------------------------------------------------------------------
# Estados de las órdenes
# ---------------------------------------------------------------------------
def estados_permitidos(orden, usuario):
    """Estados a los que `usuario` puede mover la `orden`."""
    if orden.liquidado_en_corte:
        return []
    if usuario.es_admin:
        return [e for e in ESTADOS if e != orden.estado]
    if orden.id_mecanico != usuario.id_usuario:
        return []
    return TRANSICIONES_MECANICO.get(orden.estado, [])


def cambiar_estado(orden, nuevo_estado, usuario):
    if nuevo_estado not in ESTADOS:
        raise ReglaNegocioError("Estado inválido.")
    if orden.liquidado_en_corte:
        raise ReglaNegocioError("La orden ya fue liquidada en un corte semanal y no puede modificarse.")
    if nuevo_estado == orden.estado:
        raise ReglaNegocioError("La orden ya se encuentra en ese estado.")
    if nuevo_estado not in estados_permitidos(orden, usuario):
        raise ReglaNegocioError(
            f"No tienes permiso para mover la orden de «{orden.estado}» a «{nuevo_estado}»."
        )
    if nuevo_estado in ESTADOS_COBRABLES and not orden.detalles:
        raise ReglaNegocioError("Agrega al menos un servicio a la orden antes de completarla.")

    anterior = orden.estado
    orden.estado = nuevo_estado
    if nuevo_estado in ESTADOS_COBRABLES:
        if orden.fecha_finalizacion is None:
            orden.fecha_finalizacion = ahora()
    else:
        orden.fecha_finalizacion = None

    db.session.add(HistorialEstado(
        orden=orden, estado_anterior=anterior, estado_nuevo=nuevo_estado,
        id_usuario=usuario.id_usuario,
    ))
    return orden


def puede_editar_orden(orden, usuario):
    """¿Puede el usuario modificar servicios/datos de la orden?"""
    if orden.liquidado_en_corte:
        return False
    if usuario.es_admin:
        return True
    return (
        orden.id_mecanico == usuario.id_usuario
        and orden.estado in ESTADOS_ACTIVOS
    )


def puede_ver_orden(orden, usuario):
    return usuario.es_admin or orden.id_mecanico == usuario.id_usuario


# ---------------------------------------------------------------------------
# Comisiones y cortes
# ---------------------------------------------------------------------------
def _fecha_efectiva():
    """Fecha que ubica una orden dentro de un periodo: finalización o, en su defecto, ingreso."""
    return func.coalesce(OrdenTrabajo.fecha_finalizacion, OrdenTrabajo.fecha_ingreso)


def calcular_comision(total, porcentaje):
    return (Decimal(total) * Decimal(porcentaje) / Decimal(100)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def _query_ordenes_corte(id_mecanico, inicio, fin):
    desde, hasta = limites_dias(inicio, fin)
    return (
        OrdenTrabajo.query
        .filter(
            OrdenTrabajo.id_mecanico == id_mecanico,
            OrdenTrabajo.estado.in_(ESTADOS_COBRABLES),
            OrdenTrabajo.liquidado_en_corte.is_(False),
            _fecha_efectiva() >= desde,
            _fecha_efectiva() < hasta,
        )
    )


def calcular_pre_corte(id_mecanico, inicio, fin, porcentaje=None):
    """Simula un corte sin guardar nada. Devuelve un dict serializable."""
    mecanico = db.session.get(Usuario, id_mecanico)
    if mecanico is None or not mecanico.es_mecanico:
        raise ReglaNegocioError("Selecciona un mecánico válido.")
    if fin < inicio:
        raise ReglaNegocioError("La fecha final no puede ser anterior a la inicial.")

    if porcentaje is None:
        porcentaje = mecanico.porcentaje_comision_defecto
        if porcentaje is None:
            porcentaje = Decimal("15.00")
    porcentaje = Decimal(porcentaje)
    if porcentaje < 0 or porcentaje > 100:
        raise ReglaNegocioError("El porcentaje debe estar entre 0 y 100.")

    ordenes = (
        _query_ordenes_corte(id_mecanico, inicio, fin)
        .order_by(_fecha_efectiva(), OrdenTrabajo.id_orden)
        .all()
    )
    total = sum((Decimal(str(o.total_costo or 0)) for o in ordenes), Decimal("0.00")).quantize(CENTAVOS)
    total_servicios = sum((Decimal(str(o.subtotal_servicios or 0)) for o in ordenes), Decimal("0.00")).quantize(CENTAVOS)
    total_piezas = sum((Decimal(str(o.subtotal_piezas or 0)) for o in ordenes), Decimal("0.00")).quantize(CENTAVOS)
    base_comision = total_servicios if (total_servicios > 0 or total_piezas > 0) else total

    desde, hasta = limites_dias(inicio, fin)
    en_curso = (
        OrdenTrabajo.query
        .filter(
            OrdenTrabajo.id_mecanico == id_mecanico,
            OrdenTrabajo.estado.in_(ESTADOS_ACTIVOS),
            OrdenTrabajo.fecha_ingreso < hasta,
        )
        .count()
    )
    return {
        "mecanico": mecanico,
        "ordenes": ordenes,
        "total": total,
        "total_servicios": total_servicios,
        "total_piezas": total_piezas,
        "base_comision": base_comision,
        "porcentaje": porcentaje,
        "comision": calcular_comision(base_comision, porcentaje),
        "cantidad": len(ordenes),
        "en_curso": en_curso,
    }


def cerrar_corte(id_mecanico, inicio, fin, porcentaje, admin):
    """Congela el corte: crea el registro inalterable y liquida las órdenes.

    El cálculo se repite en el servidor bajo bloqueo de filas (FOR UPDATE), de modo
    que dos cierres simultáneos no puedan liquidar dos veces la misma orden.
    """
    mecanico = db.session.get(Usuario, id_mecanico)
    if mecanico is None or not mecanico.es_mecanico:
        raise ReglaNegocioError("Selecciona un mecánico válido.")
    if fin < inicio:
        raise ReglaNegocioError("La fecha final no puede ser anterior a la inicial.")
    porcentaje = Decimal(porcentaje)
    if porcentaje < 0 or porcentaje > 100:
        raise ReglaNegocioError("El porcentaje debe estar entre 0 y 100.")

    ordenes = (
        _query_ordenes_corte(id_mecanico, inicio, fin)
        .order_by(OrdenTrabajo.id_orden)
        .with_for_update()
        .all()
    )
    if not ordenes:
        raise ReglaNegocioError(
            "No hay órdenes completadas o entregadas pendientes de liquidar en ese periodo."
        )

    total = sum((Decimal(str(o.total_costo or 0)) for o in ordenes), Decimal("0.00")).quantize(CENTAVOS)
    total_servicios = sum((Decimal(str(o.subtotal_servicios or 0)) for o in ordenes), Decimal("0.00")).quantize(CENTAVOS)
    base_comision = total_servicios if (total_servicios > 0 or sum((Decimal(str(o.subtotal_piezas or 0)) for o in ordenes), Decimal("0.00")) > 0) else total

    corte = CorteSemanal(
        id_mecanico=id_mecanico,
        fecha_inicio=inicio,
        fecha_fin=fin,
        total_reparaciones_monto=total,
        porcentaje_aplicado=porcentaje,
        monto_comision_pagar=calcular_comision(base_comision, porcentaje),
        estatus_pago="Pendiente",
        cerrado_por_admin=admin.id_usuario,
        cantidad_ordenes=len(ordenes),
    )
    db.session.add(corte)
    db.session.flush()
    for orden in ordenes:
        orden.liquidado_en_corte = True
        orden.id_corte = corte.id_corte
    return corte


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
def _fila_pct():
    """Porcentaje efectivo por orden: el del corte si ya se liquidó; si no, el vigente del mecánico."""
    return func.coalesce(CorteSemanal.porcentaje_aplicado, Usuario.porcentaje_comision_defecto, 0)


def kpis_admin(anio, mes):
    inicio, fin = rango_mes(anio, mes)
    desde, hasta = limites_dias(inicio, fin)
    fecha = _fecha_efectiva()
    base = (
        db.session.query(OrdenTrabajo)
        .filter(OrdenTrabajo.estado.in_(ESTADOS_COBRABLES), fecha >= desde, fecha < hasta)
    )

    ingresos, concluidas = (
        base.with_entities(
            func.coalesce(func.sum(OrdenTrabajo.total_costo), 0), func.count(OrdenTrabajo.id_orden)
        ).one()
    )
    comisiones = (
        base.join(Usuario, Usuario.id_usuario == OrdenTrabajo.id_mecanico)
        .outerjoin(CorteSemanal, CorteSemanal.id_corte == OrdenTrabajo.id_corte)
        .with_entities(func.coalesce(func.sum(OrdenTrabajo.total_costo * _fila_pct() / 100), 0))
        .scalar()
    )
    ingresos = Decimal(ingresos).quantize(CENTAVOS)
    comisiones = Decimal(comisiones).quantize(CENTAVOS, rounding=ROUND_HALF_UP)

    ranking = (
        base.join(Usuario, Usuario.id_usuario == OrdenTrabajo.id_mecanico)
        .with_entities(
            Usuario.nombre_completo,
            func.count(OrdenTrabajo.id_orden),
            func.coalesce(func.sum(OrdenTrabajo.total_costo), 0),
        )
        .group_by(Usuario.id_usuario, Usuario.nombre_completo)
        .order_by(func.sum(OrdenTrabajo.total_costo).desc())
        .limit(5)
        .all()
    )

    # Serie diaria de los últimos 14 días (ingresos de órdenes concluidas)
    fin_serie = hoy()
    ini_serie = fin_serie - timedelta(days=13)
    d1, d2 = limites_dias(ini_serie, fin_serie)
    dia = cast(func.timezone(current_app.config["APP_TIMEZONE"], fecha), Date)
    filas = (
        db.session.query(dia, func.coalesce(func.sum(OrdenTrabajo.total_costo), 0))
        .filter(OrdenTrabajo.estado.in_(ESTADOS_COBRABLES), fecha >= d1, fecha < d2)
        .group_by(dia)
        .all()
    )
    por_dia = {f[0]: Decimal(f[1]) for f in filas}
    serie = []
    for i in range(14):
        d = ini_serie + timedelta(days=i)
        serie.append({"fecha": d.strftime("%d/%m"), "valor": float(por_dia.get(d, 0))})

    por_estado = dict(
        db.session.query(OrdenTrabajo.estado, func.count(OrdenTrabajo.id_orden))
        .group_by(OrdenTrabajo.estado).all()
    )
    comisiones_por_pagar = (
        db.session.query(func.coalesce(func.sum(CorteSemanal.monto_comision_pagar), 0))
        .filter(CorteSemanal.estatus_pago == "Pendiente").scalar()
    )
    pendiente_liquidar = (
        db.session.query(func.count(OrdenTrabajo.id_orden))
        .filter(OrdenTrabajo.estado.in_(ESTADOS_COBRABLES), OrdenTrabajo.liquidado_en_corte.is_(False))
        .scalar()
    )
    recientes = (
        OrdenTrabajo.query.order_by(OrdenTrabajo.id_orden.desc()).limit(6).all()
    )
    return {
        "inicio": inicio,
        "ingresos": ingresos,
        "concluidas": concluidas,
        "comisiones": comisiones,
        "ganancia_neta": ingresos - comisiones,
        "top": ranking[0] if ranking else None,
        "ranking": ranking,
        "serie": serie,
        "por_estado": por_estado,
        "activas": sum(por_estado.get(e, 0) for e in ESTADOS_ACTIVOS),
        "comisiones_por_pagar": Decimal(comisiones_por_pagar),
        "pendiente_liquidar": pendiente_liquidar,
        "recientes": recientes,
    }


def kpis_mecanico(usuario):
    lunes, domingo = rango_semana()
    desde, hasta = limites_dias(lunes, domingo)
    fecha = _fecha_efectiva()
    porcentaje = usuario.porcentaje_comision_defecto
    if porcentaje is None:
        porcentaje = Decimal("15.00")

    activos = (
        OrdenTrabajo.query
        .filter(OrdenTrabajo.id_mecanico == usuario.id_usuario, OrdenTrabajo.estado.in_(ESTADOS_ACTIVOS))
        .count()
    )
    semana = OrdenTrabajo.query.filter(
        OrdenTrabajo.id_mecanico == usuario.id_usuario,
        OrdenTrabajo.estado.in_(ESTADOS_COBRABLES),
        fecha >= desde, fecha < hasta,
    )
    ingresos_semana = semana.with_entities(
        func.coalesce(func.sum(OrdenTrabajo.total_costo), 0)
    ).scalar()
    sin_liquidar_semana = semana.filter(OrdenTrabajo.liquidado_en_corte.is_(False)).with_entities(
        func.coalesce(func.sum(OrdenTrabajo.total_costo), 0)
    ).scalar()
    sin_liquidar_total = (
        OrdenTrabajo.query
        .filter(
            OrdenTrabajo.id_mecanico == usuario.id_usuario,
            OrdenTrabajo.estado.in_(ESTADOS_COBRABLES),
            OrdenTrabajo.liquidado_en_corte.is_(False),
        )
        .with_entities(func.coalesce(func.sum(OrdenTrabajo.total_costo), 0))
        .scalar()
    )
    concluidas_semana = semana.count()
    return {
        "lunes": lunes,
        "domingo": domingo,
        "activos": activos,
        "concluidas_semana": concluidas_semana,
        "ingresos_semana": Decimal(ingresos_semana).quantize(CENTAVOS),
        "comision_semana": calcular_comision(sin_liquidar_semana, porcentaje),
        "comision_pendiente_total": calcular_comision(sin_liquidar_total, porcentaje),
        "porcentaje": porcentaje,
    }


def mecanicos_activos():
    return (
        Usuario.query.join(Rol, Rol.id_rol == Usuario.id_rol)
        .filter(Usuario.activo.is_(True), Rol.nombre == ROL_MECANICO)
        .order_by(Usuario.nombre_completo)
        .all()
    )


def reporte_financiero(inicio, fin, id_mecanico=None):
    """Genera reporte financiero completo en un periodo [inicio, fin].

    - Filtro por fecha efectiva (finalización o ingreso)
    - Filtro opcional por id_mecanico
    - Ingresos totales, mano de obra (servicios) y refacciones (piezas)
    - Comisiones estimadas / aplicadas y ganancia neta para el taller
    - Ranking de trabajos / servicios más realizados (cantidad y monto)
    - Top piezas/refacciones más facturadas
    - Desglose financiero por mecánico
    - Listado de órdenes detalladas
    """
    desde, hasta = limites_dias(inicio, fin)
    fecha = _fecha_efectiva()

    consulta_ordenes = (
        OrdenTrabajo.query
        .filter(
            OrdenTrabajo.estado.in_(ESTADOS_COBRABLES),
            fecha >= desde,
            fecha < hasta,
        )
    )
    if id_mecanico:
        consulta_ordenes = consulta_ordenes.filter(OrdenTrabajo.id_mecanico == id_mecanico)

    ordenes = consulta_ordenes.order_by(fecha.desc(), OrdenTrabajo.id_orden.desc()).all()
    orden_ids = [o.id_orden for o in ordenes]

    total_facturado = sum((Decimal(str(o.total_costo or 0)) for o in ordenes), Decimal("0.00")).quantize(CENTAVOS)
    total_servicios = sum((Decimal(str(o.subtotal_servicios or 0)) for o in ordenes), Decimal("0.00")).quantize(CENTAVOS)
    total_piezas = sum((Decimal(str(o.subtotal_piezas or 0)) for o in ordenes), Decimal("0.00")).quantize(CENTAVOS)

    if total_servicios == Decimal("0.00") and total_piezas == Decimal("0.00") and total_facturado > Decimal("0.00"):
        total_servicios = total_facturado

    total_comisiones = Decimal("0.00")
    for o in ordenes:
        pct = o.corte.porcentaje_aplicado if o.corte else (o.mecanico.porcentaje_comision_defecto or Decimal("15.00"))
        base = o.subtotal_servicios if (o.subtotal_servicios > 0 or o.subtotal_piezas > 0) else o.total_costo
        total_comisiones += (Decimal(str(base or 0)) * Decimal(str(pct)) / Decimal(100)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)

    ganancia_neta = (total_facturado - total_comisiones).quantize(CENTAVOS)
    cantidad_ordenes = len(ordenes)
    ticket_promedio = (total_facturado / cantidad_ordenes).quantize(CENTAVOS) if cantidad_ordenes else Decimal("0.00")

    # Ranking de servicios más realizados
    ranking_servicios = []
    if orden_ids:
        filas_servicios = (
            db.session.query(
                Servicio.id_servicio,
                Servicio.nombre,
                func.sum(DetalleOrdenServicio.cantidad).label("veces"),
                func.sum(DetalleOrdenServicio.subtotal).label("monto_total"),
                func.avg(DetalleOrdenServicio.costo_aplicado).label("costo_promedio"),
            )
            .join(DetalleOrdenServicio, DetalleOrdenServicio.id_servicio == Servicio.id_servicio)
            .filter(DetalleOrdenServicio.id_orden.in_(orden_ids))
            .group_by(Servicio.id_servicio, Servicio.nombre)
            .order_by(func.sum(DetalleOrdenServicio.cantidad).desc(), func.sum(DetalleOrdenServicio.subtotal).desc())
            .all()
        )
        total_veces = sum(f.veces for f in filas_servicios) or 1
        for row in filas_servicios:
            pct_freq = round((row.veces / total_veces) * 100, 1)
            pct_ing = round(float(Decimal(str(row.monto_total)) / (total_servicios or Decimal("1.00")) * 100), 1) if total_servicios else 0
            ranking_servicios.append({
                "id_servicio": row.id_servicio,
                "nombre": row.nombre,
                "veces": row.veces,
                "monto_total": Decimal(str(row.monto_total)).quantize(CENTAVOS),
                "costo_promedio": Decimal(str(row.costo_promedio)).quantize(CENTAVOS),
                "pct_frecuencia": pct_freq,
                "pct_ingresos": pct_ing,
            })

    # Ranking de piezas más utilizadas
    ranking_piezas = []
    if orden_ids:
        filas_piezas = (
            db.session.query(
                DetalleOrdenPieza.descripcion,
                func.sum(DetalleOrdenPieza.cantidad).label("cantidad_total"),
                func.sum(DetalleOrdenPieza.subtotal).label("monto_total"),
            )
            .filter(DetalleOrdenPieza.id_orden.in_(orden_ids))
            .group_by(DetalleOrdenPieza.descripcion)
            .order_by(func.sum(DetalleOrdenPieza.subtotal).desc())
            .limit(10)
            .all()
        )
        for row in filas_piezas:
            ranking_piezas.append({
                "descripcion": row.descripcion,
                "cantidad": row.cantidad_total,
                "monto_total": Decimal(str(row.monto_total)).quantize(CENTAVOS),
            })

    # Desglose por mecánico
    por_mecanico = {}
    for o in ordenes:
        mec = o.mecanico
        if mec.id_usuario not in por_mecanico:
            por_mecanico[mec.id_usuario] = {
                "mecanico": mec,
                "cantidad_ordenes": 0,
                "total_servicios": Decimal("0.00"),
                "total_piezas": Decimal("0.00"),
                "total_facturado": Decimal("0.00"),
                "comision_generada": Decimal("0.00"),
            }
        item = por_mecanico[mec.id_usuario]
        item["cantidad_ordenes"] += 1
        item["total_servicios"] += o.subtotal_servicios
        item["total_piezas"] += o.subtotal_piezas
        item["total_facturado"] += Decimal(str(o.total_costo or 0))
        pct = o.corte.porcentaje_aplicado if o.corte else (mec.porcentaje_comision_defecto or Decimal("15.00"))
        base = o.subtotal_servicios if (o.subtotal_servicios > 0 or o.subtotal_piezas > 0) else o.total_costo
        item["comision_generada"] += (Decimal(str(base or 0)) * Decimal(str(pct)) / Decimal(100)).quantize(CENTAVOS, rounding=ROUND_HALF_UP)

    desglose_mecanicos = sorted(por_mecanico.values(), key=lambda x: x["total_facturado"], reverse=True)

    return {
        "inicio": inicio,
        "fin": fin,
        "id_mecanico": id_mecanico,
        "cantidad_ordenes": cantidad_ordenes,
        "total_facturado": total_facturado,
        "total_servicios": total_servicios,
        "total_piezas": total_piezas,
        "total_comisiones": total_comisiones,
        "ganancia_neta": ganancia_neta,
        "ticket_promedio": ticket_promedio,
        "ranking_servicios": ranking_servicios,
        "ranking_piezas": ranking_piezas,
        "desglose_mecanicos": desglose_mecanicos,
        "ordenes": ordenes,
    }

