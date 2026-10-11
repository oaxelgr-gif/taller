"""Vista simplificada para mecánicos: panel personal, comisión estimada y sus cortes."""
from flask import Blueprint, abort, current_app, redirect, render_template, send_file, url_for
from flask_login import current_user, login_required

from .. import db
from ..models import ESTADOS_ACTIVOS, ESTADOS_COBRABLES, ROL_MECANICO, CorteSemanal, OrdenTrabajo
from ..services import estados_permitidos, kpis_mecanico
from ..utils import ahora, generar_pdf_corte, roles_required

bp = Blueprint("mecanico", __name__)

mecanico_required = roles_required(ROL_MECANICO)


@bp.route("/")
@login_required
def dashboard():
    if current_user.es_admin:
        return redirect(url_for("admin.dashboard"))
    datos = kpis_mecanico(current_user)
    activas = (
        OrdenTrabajo.query
        .filter(OrdenTrabajo.id_mecanico == current_user.id_usuario, OrdenTrabajo.estado.in_(ESTADOS_ACTIVOS))
        .order_by(OrdenTrabajo.fecha_ingreso.asc())
        .all()
    )
    recientes = (
        OrdenTrabajo.query
        .filter(OrdenTrabajo.id_mecanico == current_user.id_usuario, OrdenTrabajo.estado.in_(ESTADOS_COBRABLES))
        .order_by(OrdenTrabajo.fecha_finalizacion.desc().nullslast(), OrdenTrabajo.id_orden.desc())
        .limit(8).all()
    )
    ultimos_cortes = (
        CorteSemanal.query.filter_by(id_mecanico=current_user.id_usuario)
        .order_by(CorteSemanal.id_corte.desc()).limit(4).all()
    )
    return render_template(
        "mecanico/dashboard.html", k=datos, activas=activas, recientes=recientes,
        ultimos_cortes=ultimos_cortes, permitidos=lambda o: estados_permitidos(o, current_user),
    )


@bp.route("/cortes")
@login_required
@mecanico_required
def cortes():
    lista = (
        CorteSemanal.query.filter_by(id_mecanico=current_user.id_usuario)
        .order_by(CorteSemanal.id_corte.desc()).all()
    )
    return render_template("mecanico/cortes.html", cortes=lista)


def _corte_propio_o_404(id_corte):
    corte = db.get_or_404(CorteSemanal, id_corte)
    if corte.id_mecanico != current_user.id_usuario:
        abort(403)
    return corte


@bp.route("/cortes/<int:id_corte>")
@login_required
@mecanico_required
def detalle_corte(id_corte):
    corte = _corte_propio_o_404(id_corte)
    ordenes = corte.ordenes.order_by(OrdenTrabajo.id_orden).all()
    return render_template("admin/corte_detalle.html", corte=corte, ordenes=ordenes,
                           vista_admin=False, ahora=ahora())


@bp.route("/cortes/<int:id_corte>/pdf")
@login_required
@mecanico_required
def pdf_corte(id_corte):
    corte = _corte_propio_o_404(id_corte)
    ordenes = corte.ordenes.order_by(OrdenTrabajo.id_orden).all()
    buffer = generar_pdf_corte(corte, ordenes, current_app.config["TALLER_NOMBRE"])
    return send_file(buffer, mimetype="application/pdf", download_name=f"corte-{corte.folio}.pdf")
