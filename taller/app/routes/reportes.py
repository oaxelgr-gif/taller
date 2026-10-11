"""Reportes financieros y análisis de servicios más realizados."""
from datetime import date, timedelta
from decimal import Decimal

from flask import Blueprint, render_template, request
from flask_login import login_required

from ..models import Usuario
from ..services import mecanicos_activos, reporte_financiero
from ..utils import admin_required, hoy, parse_fecha, parse_entero, rango_mes

bp = Blueprint("reportes", __name__)


def _calcular_rango(periodo, str_desde, str_hasta):
    """Calcula las fechas de inicio y fin según el periodo seleccionado."""
    actual = hoy()
    if periodo == "mes_anterior":
        if actual.month == 1:
            anio_ant, mes_ant = actual.year - 1, 12
        else:
            anio_ant, mes_ant = actual.year, actual.month - 1
        return rango_mes(anio_ant, mes_ant), "mes_anterior"
    elif periodo == "ultimos_30":
        return (actual - timedelta(days=30), actual), "ultimos_30"
    elif periodo == "anio_actual":
        return (date(actual.year, 1, 1), actual), "anio_actual"
    elif periodo == "personalizado":
        try:
            d_ini = parse_fecha(str_desde) if str_desde else None
            d_fin = parse_fecha(str_hasta) if str_hasta else None
            if d_ini and d_fin:
                if d_fin < d_ini:
                    d_ini, d_fin = d_fin, d_ini
                return (d_ini, d_fin), "personalizado"
        except (ValueError, TypeError):
            pass
    # Por defecto: este mes
    return rango_mes(actual.year, actual.month), "este_mes"


@bp.route("/financiero")
@login_required
@admin_required
def financiero():
    periodo_req = request.args.get("periodo", "este_mes")
    str_desde = request.args.get("desde")
    str_hasta = request.args.get("hasta")

    (inicio, fin), periodo = _calcular_rango(periodo_req, str_desde, str_hasta)

    id_mecanico = None
    mec_raw = request.args.get("mecanico", "").strip()
    if mec_raw.isdigit():
        id_mecanico = int(mec_raw)

    datos = reporte_financiero(inicio, fin, id_mecanico=id_mecanico)

    return render_template(
        "reportes/financiero.html",
        rep=datos,
        periodo=periodo,
        desde=inicio,
        hasta=fin,
        id_mecanico=id_mecanico,
        mecanicos=mecanicos_activos(),
    )
