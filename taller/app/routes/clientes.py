"""Clientes y vehículos: CRUD, búsqueda AJAX y alta rápida."""
import os

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from .. import db
from ..models import Cliente, OrdenTrabajo, Vehiculo, VehiculoAnomalia
from ..utils import (
    Paginacion,
    admin_required,
    eliminar_foto_vehiculo,
    guardar_foto_vehiculo,
    limpiar,
    normalizar_placas,
    pagina_actual,
    parse_entero,
    responder,
    staff_required,
    validar_correo,
)

bp = Blueprint("clientes", __name__)


def _like(texto):
    return f"%{texto.replace('%', '').replace('_', '')}%"


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------
@bp.route("/")
@login_required
@staff_required
def index():
    q = limpiar(request.args.get("q"))
    consulta = Cliente.query
    if q:
        patron = _like(q)
        consulta = consulta.filter(or_(
            Cliente.nombre_completo.ilike(patron),
            Cliente.telefono.ilike(patron),
            Cliente.correo.ilike(patron),
            Cliente.id_cliente.in_(
                db.session.query(Vehiculo.id_cliente).filter(Vehiculo.placas.ilike(patron))
            ),
        ))
    consulta = consulta.order_by(Cliente.nombre_completo)
    pag = Paginacion(consulta, pagina_actual(), current_app.config["POR_PAGINA"])

    conteo = {}
    if pag.items:
        ids = [c.id_cliente for c in pag.items]
        conteo = dict(
            db.session.query(Vehiculo.id_cliente, func.count(Vehiculo.id_vehiculo))
            .filter(Vehiculo.id_cliente.in_(ids)).group_by(Vehiculo.id_cliente).all()
        )
    plantilla = "clientes/_tabla.html" if request.args.get("partial") else "clientes/index.html"
    return render_template(plantilla, pag=pag, q=q, conteo=conteo)


@bp.route("/buscar")
@login_required
@staff_required
def buscar():
    """Búsqueda en tiempo real (AJAX) de clientes con sus vehículos."""
    q = limpiar(request.args.get("q"))
    if len(q) < 2:
        return jsonify({"resultados": []})
    patron = _like(q)
    clientes = (
        Cliente.query.filter(or_(
            Cliente.nombre_completo.ilike(patron),
            Cliente.telefono.ilike(patron),
            Cliente.id_cliente.in_(
                db.session.query(Vehiculo.id_cliente).filter(Vehiculo.placas.ilike(patron))
            ),
        ))
        .order_by(Cliente.nombre_completo).limit(8).all()
    )
    return jsonify({"resultados": [c.to_dict(con_vehiculos=True) for c in clientes]})


def _leer_cliente(datos):
    nombre = limpiar(datos.get("nombre_completo"), 120)
    telefono = limpiar(datos.get("telefono"), 20)
    correo = limpiar(datos.get("correo"), 100) or None
    direccion = limpiar(datos.get("direccion")) or None
    if not nombre:
        raise ValueError("El nombre del cliente es obligatorio.")
    if not telefono:
        raise ValueError("El teléfono es obligatorio.")
    if correo and not validar_correo(correo):
        raise ValueError("El correo del cliente no es válido.")
    return nombre, telefono, correo, direccion


@bp.route("/guardar", methods=["POST"])
@login_required
@staff_required
def guardar():
    """Crea un cliente (mecánico o admin). Edita sólo si es administrador."""
    id_cliente = request.form.get("id_cliente")
    try:
        nombre, telefono, correo, direccion = _leer_cliente(request.form)
        if id_cliente:
            if not current_user.es_admin:
                return responder(False, "Sólo un administrador puede editar clientes.", status=403)
            cliente = db.session.get(Cliente, int(id_cliente))
            if cliente is None:
                return responder(False, "Cliente no encontrado.", status=404)
            mensaje = "Cliente actualizado correctamente."
        else:
            cliente = Cliente()
            db.session.add(cliente)
            mensaje = "Cliente registrado correctamente."
        cliente.nombre_completo, cliente.telefono = nombre, telefono
        cliente.correo, cliente.direccion = correo, direccion
        db.session.commit()
        return responder(True, mensaje, url_for("clientes.detalle", id_cliente=cliente.id_cliente),
                         cliente=cliente.to_dict(con_vehiculos=True))
    except ValueError as e:
        db.session.rollback()
        return responder(False, str(e))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al guardar cliente")
        return responder(False, "No se pudo guardar el cliente.", status=500)


@bp.route("/<int:id_cliente>")
@login_required
@staff_required
def detalle(id_cliente):
    cliente = db.get_or_404(Cliente, id_cliente)
    vehiculos = cliente.vehiculos.order_by(Vehiculo.id_vehiculo).all()
    ordenes = (
        OrdenTrabajo.query.join(Vehiculo).filter(Vehiculo.id_cliente == id_cliente)
        .order_by(OrdenTrabajo.fecha_ingreso.desc()).limit(25).all()
    )
    if not current_user.es_admin:
        ordenes = [o for o in ordenes if o.id_mecanico == current_user.id_usuario]
    return render_template("clientes/detalle.html", cliente=cliente, vehiculos=vehiculos, ordenes=ordenes)


@bp.route("/<int:id_cliente>/eliminar", methods=["POST"])
@login_required
@admin_required
def eliminar(id_cliente):
    cliente = db.get_or_404(Cliente, id_cliente)
    tiene_ordenes = (
        db.session.query(OrdenTrabajo.id_orden).join(Vehiculo)
        .filter(Vehiculo.id_cliente == id_cliente).first()
    )
    if tiene_ordenes:
        return responder(False, "No se puede eliminar: el cliente tiene órdenes de trabajo registradas.")
    try:
        db.session.delete(cliente)
        db.session.commit()
        return responder(True, "Cliente eliminado.", url_for("clientes.index"))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al eliminar cliente")
        return responder(False, "No se pudo eliminar el cliente.", status=500)


# ---------------------------------------------------------------------------
# Vehículos
# ---------------------------------------------------------------------------
@bp.route("/vehiculos")
@login_required
@staff_required
def vehiculos():
    q = limpiar(request.args.get("q"))
    consulta = Vehiculo.query.join(Cliente)
    if q:
        patron = _like(q)
        consulta = consulta.filter(or_(
            Vehiculo.placas.ilike(patron), Vehiculo.marca.ilike(patron),
            Vehiculo.modelo.ilike(patron), Vehiculo.numero_serie_vin.ilike(patron),
            Cliente.nombre_completo.ilike(patron),
        ))
    consulta = consulta.order_by(Vehiculo.id_vehiculo.desc())
    pag = Paginacion(consulta, pagina_actual(), current_app.config["POR_PAGINA"])
    plantilla = "clientes/_tabla_vehiculos.html" if request.args.get("partial") else "clientes/vehiculos.html"
    return render_template(plantilla, pag=pag, q=q)


def _leer_vehiculo(datos):
    marca = limpiar(datos.get("marca"), 50)
    modelo = limpiar(datos.get("modelo"), 50)
    placas = normalizar_placas(datos.get("placas"))[:20]
    vin = limpiar(datos.get("numero_serie_vin"), 50).upper() or None
    color = limpiar(datos.get("color"), 30) or None
    if not marca or not modelo:
        raise ValueError("Marca y modelo son obligatorios.")
    if not placas:
        raise ValueError("Las placas son obligatorias.")
    anio = parse_entero(datos.get("anio"), "El año", 1900, 2100)
    return marca, modelo, anio, placas, vin, color


def _asignar_vehiculo(vehiculo, datos):
    (vehiculo.marca, vehiculo.modelo, vehiculo.anio, vehiculo.placas,
     vehiculo.numero_serie_vin, vehiculo.color) = datos


@bp.route("/vehiculos/guardar", methods=["POST"])
@login_required
@staff_required
def guardar_vehiculo():
    id_vehiculo = request.form.get("id_vehiculo")
    try:
        datos = _leer_vehiculo(request.form)
        if id_vehiculo:
            if not current_user.es_admin:
                return responder(False, "Sólo un administrador puede editar vehículos.", status=403)
            vehiculo = db.session.get(Vehiculo, int(id_vehiculo))
            if vehiculo is None:
                return responder(False, "Vehículo no encontrado.", status=404)
            mensaje = "Vehículo actualizado correctamente."
        else:
            id_cliente = parse_entero(request.form.get("id_cliente"), "El cliente")
            if db.session.get(Cliente, id_cliente) is None:
                return responder(False, "Cliente no encontrado.", status=404)
            vehiculo = Vehiculo(id_cliente=id_cliente)
            db.session.add(vehiculo)
            mensaje = "Vehículo registrado correctamente."
        existente = Vehiculo.query.filter(Vehiculo.placas == datos[3]).first()
        if existente and existente is not vehiculo:
            return responder(False, f"Las placas {datos[3]} ya están registradas en el sistema.")
        _asignar_vehiculo(vehiculo, datos)
        db.session.commit()
        return responder(True, mensaje, request.form.get("next") or url_for("clientes.vehiculos"),
                         vehiculo=vehiculo.to_dict())
    except ValueError as e:
        db.session.rollback()
        return responder(False, str(e))
    except IntegrityError:
        db.session.rollback()
        return responder(False, "Las placas ya están registradas en el sistema.")
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al guardar vehículo")
        return responder(False, "No se pudo guardar el vehículo.", status=500)


@bp.route("/vehiculos/<int:id_vehiculo>/eliminar", methods=["POST"])
@login_required
@admin_required
def eliminar_vehiculo(id_vehiculo):
    vehiculo = db.get_or_404(Vehiculo, id_vehiculo)
    if vehiculo.ordenes.first():
        return responder(False, "No se puede eliminar: el vehículo tiene órdenes de trabajo.")
    try:
        db.session.delete(vehiculo)
        db.session.commit()
        return responder(True, "Vehículo eliminado.", request.form.get("next") or url_for("clientes.vehiculos"))
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al eliminar vehículo")
@bp.route("/vehiculos/<int:id_vehiculo>")
@login_required
@staff_required
def detalle_vehiculo(id_vehiculo):
    vehiculo = db.get_or_404(Vehiculo, id_vehiculo)
    ordenes = (
        OrdenTrabajo.query.filter(OrdenTrabajo.id_vehiculo == id_vehiculo)
        .order_by(OrdenTrabajo.fecha_ingreso.desc()).limit(20).all()
    )
    if not current_user.es_admin:
        ordenes = [o for o in ordenes if o.id_mecanico == current_user.id_usuario]
    anomalias = vehiculo.anomalias if isinstance(vehiculo.anomalias, list) else vehiculo.anomalias.all()
    return render_template(
        "clientes/vehiculo_detalle.html",
        vehiculo=vehiculo,
        ordenes=ordenes,
        anomalias=anomalias,
    )


@bp.route("/vehiculos/<int:id_vehiculo>/anomalias", methods=["POST"])
@login_required
@staff_required
def guardar_anomalia(id_vehiculo):
    vehiculo = db.get_or_404(Vehiculo, id_vehiculo)
    destino = request.form.get("next") or url_for("clientes.detalle_vehiculo", id_vehiculo=id_vehiculo)
    try:
        descripcion = limpiar(request.form.get("descripcion"))
        if not descripcion:
            raise ValueError("La descripción del detalle o anomalía externa es obligatoria.")
        tipo = limpiar(request.form.get("tipo_anomalia"), 50) or "Detalle externo"
        id_orden = parse_entero(request.form.get("id_orden"), "La orden", obligatorio=False)

        foto_file = request.files.get("foto")
        foto_path = None
        if foto_file and foto_file.filename:
            foto_path = guardar_foto_vehiculo(foto_file)

        anomalia = VehiculoAnomalia(
            id_vehiculo=vehiculo.id_vehiculo,
            id_orden=id_orden,
            id_usuario=current_user.id_usuario,
            tipo_anomalia=tipo,
            descripcion=descripcion,
            foto_path=foto_path,
        )
        db.session.add(anomalia)
        db.session.commit()
        return responder(True, "Detalle / anomalía externa registrada correctamente.", destino)
    except ValueError as e:
        db.session.rollback()
        return responder(False, str(e), destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al guardar anomalia")
        return responder(False, "No se pudo registrar la anomalía.", destino, status=500)


@bp.route("/vehiculos/<int:id_vehiculo>/anomalias/<int:id_anomalia>/eliminar", methods=["POST"])
@login_required
@staff_required
def eliminar_anomalia(id_vehiculo, id_anomalia):
    anomalia = db.get_or_404(VehiculoAnomalia, id_anomalia)
    if anomalia.id_vehiculo != id_vehiculo:
        from flask import abort
        abort(404)
    destino = request.form.get("next") or url_for("clientes.detalle_vehiculo", id_vehiculo=id_vehiculo)
    try:
        if anomalia.foto_path:
            eliminar_foto_vehiculo(anomalia.foto_path)
        db.session.delete(anomalia)
        db.session.commit()
        return responder(True, "Detalle o anomalía eliminada.", destino)
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error al eliminar anomalia")
        return responder(False, "No se pudo eliminar el registro.", destino, status=500)



@bp.route("/fotos/vehiculos/<nombre>")
@login_required
@staff_required
def foto_vehiculo(nombre):
    """Sirve fotos de anomalías sólo a usuarios con sesión iniciada."""
    carpeta = os.path.join(current_app.config["UPLOAD_FOLDER"], "vehiculos")
    respuesta = send_from_directory(carpeta, os.path.basename(nombre), max_age=3600)
    respuesta.headers["Cache-Control"] = "private, max-age=3600"
    return respuesta


@bp.route("/api/rapido", methods=["POST"])
@login_required
@staff_required
def alta_rapida():
    """Alta rápida desde el modal de nueva orden.

    - Con `id_cliente`: agrega un vehículo a un cliente existente.
    - Sin `id_cliente`: crea cliente + vehículo en un solo paso.
    """
    datos = request.get_json(silent=True) or request.form
    try:
        vehiculo_datos = _leer_vehiculo(datos)
        if Vehiculo.query.filter_by(placas=vehiculo_datos[3]).first():
            raise ValueError(f"Las placas {vehiculo_datos[3]} ya están registradas en el sistema.")
        if datos.get("id_cliente"):
            cliente = db.session.get(Cliente, parse_entero(datos.get("id_cliente"), "El cliente"))
            if cliente is None:
                raise ValueError("Cliente no encontrado.")
        else:
            nombre, telefono, correo, direccion = _leer_cliente(datos)
            cliente = Cliente(nombre_completo=nombre, telefono=telefono, correo=correo, direccion=direccion)
            db.session.add(cliente)
        vehiculo = Vehiculo(cliente=cliente)
        _asignar_vehiculo(vehiculo, vehiculo_datos)
        db.session.add(vehiculo)
        db.session.commit()
        return jsonify({
            "ok": True, "mensaje": "Registro creado correctamente.",
            "cliente": cliente.to_dict(con_vehiculos=True), "vehiculo": vehiculo.to_dict(),
        })
    except ValueError as e:
        db.session.rollback()
        return jsonify({"ok": False, "mensaje": str(e)}), 400
    except IntegrityError:
        db.session.rollback()
        return jsonify({"ok": False, "mensaje": "Las placas ya están registradas."}), 400
    except Exception:
        db.session.rollback()
        current_app.logger.exception("Error en alta rápida")
        return jsonify({"ok": False, "mensaje": "No se pudo completar el registro."}), 500
