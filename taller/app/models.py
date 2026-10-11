"""Modelos SQLAlchemy que reflejan las tablas de PostgreSQL (ver schema.sql)."""
from decimal import Decimal

from flask_login import UserMixin
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

ROL_ADMIN = "Administrador"
ROL_MECANICO = "Mecanico"

ESTADOS = ["Pendiente", "En Proceso", "Completado", "Entregado", "Cancelado"]
ESTADOS_ACTIVOS = ("Pendiente", "En Proceso")
ESTADOS_COBRABLES = ("Completado", "Entregado")


class Rol(db.Model):
    __tablename__ = "roles"

    id_rol = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(30), unique=True, nullable=False)

    usuarios = db.relationship("Usuario", backref="rol", lazy="dynamic")

    def __repr__(self):
        return f"<Rol {self.nombre}>"


class Usuario(UserMixin, db.Model):
    __tablename__ = "usuarios"

    id_usuario = db.Column(db.Integer, primary_key=True)
    id_rol = db.Column(db.Integer, db.ForeignKey("roles.id_rol"), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    nombre_completo = db.Column(db.String(120), nullable=False)
    correo = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    porcentaje_comision_defecto = db.Column(db.Numeric(5, 2), default=Decimal("15.00"))
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime(timezone=True), server_default=func.now())

    # Órdenes asignadas al mecánico (backref: OrdenTrabajo.mecanico)
    ordenes_asignadas = db.relationship(
        "OrdenTrabajo", backref="mecanico", lazy="dynamic",
        foreign_keys="OrdenTrabajo.id_mecanico",
    )
    # Cortes de comisiones del mecánico (backref: CorteSemanal.mecanico)
    cortes = db.relationship(
        "CorteSemanal", backref="mecanico", lazy="dynamic",
        foreign_keys="CorteSemanal.id_mecanico",
    )
    # Cortes cerrados por el administrador (backref: CorteSemanal.admin_cierre)
    cortes_cerrados = db.relationship(
        "CorteSemanal", backref="admin_cierre", lazy="dynamic",
        foreign_keys="CorteSemanal.cerrado_por_admin",
    )

    # --- Flask-Login -----------------------------------------------------
    def get_id(self):
        return str(self.id_usuario)

    @property
    def is_active(self):  # noqa: D401 - propiedad requerida por Flask-Login
        return bool(self.activo)

    # --- Utilidades ------------------------------------------------------
    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def es_admin(self):
        return self.rol is not None and self.rol.nombre == ROL_ADMIN

    @property
    def es_mecanico(self):
        return self.rol is not None and self.rol.nombre == ROL_MECANICO

    @property
    def iniciales(self):
        partes = [p for p in (self.nombre_completo or "").split() if p]
        return "".join(p[0] for p in partes[:2]).upper() or "?"

    def __repr__(self):
        return f"<Usuario {self.username}>"


class Cliente(db.Model):
    __tablename__ = "clientes"

    id_cliente = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(20), nullable=False)
    correo = db.Column(db.String(100))
    direccion = db.Column(db.Text)
    creado_en = db.Column(db.DateTime(timezone=True), server_default=func.now())

    vehiculos = db.relationship(
        "Vehiculo", backref="cliente", lazy="dynamic",
        cascade="all, delete-orphan", passive_deletes=True,
    )

    def to_dict(self, con_vehiculos=False):
        datos = {
            "id": self.id_cliente,
            "nombre": self.nombre_completo,
            "telefono": self.telefono,
            "correo": self.correo or "",
        }
        if con_vehiculos:
            datos["vehiculos"] = [v.to_dict() for v in self.vehiculos.order_by(Vehiculo.id_vehiculo)]
        return datos

    def __repr__(self):
        return f"<Cliente {self.nombre_completo}>"


class Vehiculo(db.Model):
    __tablename__ = "vehiculos"

    id_vehiculo = db.Column(db.Integer, primary_key=True)
    id_cliente = db.Column(
        db.Integer, db.ForeignKey("clientes.id_cliente", ondelete="CASCADE"), nullable=False
    )
    marca = db.Column(db.String(50), nullable=False)
    modelo = db.Column(db.String(50), nullable=False)
    anio = db.Column(db.Integer, nullable=False)
    placas = db.Column(db.String(20), unique=True, nullable=False)
    numero_serie_vin = db.Column(db.String(50))
    color = db.Column(db.String(30))
    creado_en = db.Column(db.DateTime(timezone=True), server_default=func.now())

    ordenes = db.relationship("OrdenTrabajo", backref="vehiculo", lazy="dynamic")
    anomalias = db.relationship(
        "VehiculoAnomalia", backref="vehiculo", cascade="all, delete-orphan",
        passive_deletes=True, order_by="VehiculoAnomalia.id_anomalia.desc()",
    )

    @property
    def descripcion(self):
        return f"{self.marca} {self.modelo} {self.anio}"

    def to_dict(self):
        return {
            "id": self.id_vehiculo,
            "marca": self.marca,
            "modelo": self.modelo,
            "anio": self.anio,
            "placas": self.placas,
            "color": self.color or "",
            "descripcion": f"{self.descripcion} · {self.placas}",
        }

    def __repr__(self):
        return f"<Vehiculo {self.placas}>"


class Servicio(db.Model):
    __tablename__ = "servicios"

    id_servicio = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    descripcion = db.Column(db.Text)
    costo_base = db.Column(db.Numeric(10, 2), nullable=False)
    activo = db.Column(db.Boolean, default=True)

    detalles = db.relationship("DetalleOrdenServicio", backref="servicio", lazy="dynamic")

    def __repr__(self):
        return f"<Servicio {self.nombre}>"


class CorteSemanal(db.Model):
    __tablename__ = "cortes_semanales"

    id_corte = db.Column(db.Integer, primary_key=True)
    id_mecanico = db.Column(db.Integer, db.ForeignKey("usuarios.id_usuario"), nullable=False)
    fecha_inicio = db.Column(db.Date, nullable=False)
    fecha_fin = db.Column(db.Date, nullable=False)
    total_reparaciones_monto = db.Column(db.Numeric(10, 2), nullable=False)
    porcentaje_aplicado = db.Column(db.Numeric(5, 2), nullable=False)
    monto_comision_pagar = db.Column(db.Numeric(10, 2), nullable=False)
    estatus_pago = db.Column(db.String(20), default="Pendiente")
    cerrado_por_admin = db.Column(db.Integer, db.ForeignKey("usuarios.id_usuario"), nullable=False)
    fecha_cierre = db.Column(db.DateTime(timezone=True), server_default=func.now())
    cantidad_ordenes = db.Column(db.Integer, nullable=False, default=0)
    fecha_pago = db.Column(db.DateTime(timezone=True))

    ordenes = db.relationship("OrdenTrabajo", backref="corte", lazy="dynamic")

    @property
    def folio(self):
        return f"CS-{self.id_corte:05d}"

    def __repr__(self):
        return f"<Corte {self.folio}>"


class OrdenTrabajo(db.Model):
    __tablename__ = "ordenes_trabajo"

    id_orden = db.Column(db.Integer, primary_key=True)
    id_vehiculo = db.Column(db.Integer, db.ForeignKey("vehiculos.id_vehiculo"), nullable=False)
    id_mecanico = db.Column(db.Integer, db.ForeignKey("usuarios.id_usuario"), nullable=False)
    fecha_ingreso = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())
    fecha_entrega_estimada = db.Column(db.DateTime(timezone=True))
    fecha_finalizacion = db.Column(db.DateTime(timezone=True))
    estado = db.Column(db.String(20), nullable=False, default="Pendiente")
    diagnostico_inicial = db.Column(db.Text)
    observaciones_finales = db.Column(db.Text)
    total_costo = db.Column(db.Numeric(10, 2), default=Decimal("0.00"))
    liquidado_en_corte = db.Column(db.Boolean, default=False)
    creado_en = db.Column(db.DateTime(timezone=True), server_default=func.now())
    kilometraje = db.Column(db.Integer)
    id_corte = db.Column(db.Integer, db.ForeignKey("cortes_semanales.id_corte"))

    detalles = db.relationship(
        "DetalleOrdenServicio", backref="orden", cascade="all, delete-orphan",
        passive_deletes=True, order_by="DetalleOrdenServicio.id_detalle",
    )
    piezas = db.relationship(
        "DetalleOrdenPieza", backref="orden", cascade="all, delete-orphan",
        passive_deletes=True, order_by="DetalleOrdenPieza.id_pieza",
    )
    historial = db.relationship(
        "HistorialEstado", backref="orden", cascade="all, delete-orphan",
        passive_deletes=True, order_by="HistorialEstado.id_historial",
    )
    anomalias = db.relationship(
        "VehiculoAnomalia", backref="orden", lazy="dynamic",
    )

    @property
    def folio(self):
        return f"OT-{self.id_orden:05d}"

    @property
    def es_cobrable(self):
        return self.estado in ESTADOS_COBRABLES

    @property
    def esta_bloqueada(self):
        """Una orden liquidada en un corte no se puede modificar."""
        return bool(self.liquidado_en_corte)

    @property
    def subtotal_servicios(self):
        """Suma de servicios/mano de obra en la orden."""
        return sum(
            (Decimal(str(d.costo_aplicado or 0)) * int(d.cantidad or 1) for d in self.detalles),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))

    @property
    def subtotal_piezas(self):
        """Suma de refacciones/piezas agregadas a la orden."""
        return sum(
            (Decimal(str(p.costo_unitario or 0)) * int(p.cantidad or 1) for p in self.piezas),
            Decimal("0.00"),
        ).quantize(Decimal("0.01"))

    def recalcular_total(self):
        """Hook del ORM: recalcula total_costo desde servicios + piezas.

        El disparador de PostgreSQL hace lo mismo a nivel de BD; esto mantiene
        sincronizado el objeto en memoria y funciona aunque no existan triggers.
        """
        db.session.flush()
        servicios = (
            db.session.query(func.coalesce(func.sum(DetalleOrdenServicio.subtotal), 0))
            .filter(DetalleOrdenServicio.id_orden == self.id_orden)
            .scalar()
        )
        piezas = (
            db.session.query(func.coalesce(func.sum(DetalleOrdenPieza.subtotal), 0))
            .filter(DetalleOrdenPieza.id_orden == self.id_orden)
            .scalar()
        )
        self.total_costo = (Decimal(str(servicios)) + Decimal(str(piezas))).quantize(Decimal("0.01"))
        return self.total_costo

    def __repr__(self):
        return f"<Orden {self.folio} {self.estado}>"


class DetalleOrdenServicio(db.Model):
    __tablename__ = "detalle_orden_servicios"

    id_detalle = db.Column(db.Integer, primary_key=True)
    id_orden = db.Column(
        db.Integer, db.ForeignKey("ordenes_trabajo.id_orden", ondelete="CASCADE"), nullable=False
    )
    id_servicio = db.Column(db.Integer, db.ForeignKey("servicios.id_servicio"), nullable=False)
    costo_aplicado = db.Column(db.Numeric(10, 2), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    # Columna generada por PostgreSQL: costo_aplicado * cantidad
    subtotal = db.Column(db.Numeric(10, 2), db.Computed("costo_aplicado * cantidad", persisted=True))

    def __repr__(self):
        return f"<Detalle orden={self.id_orden} servicio={self.id_servicio}>"


class DetalleOrdenPieza(db.Model):
    __tablename__ = "detalle_orden_piezas"

    id_pieza = db.Column(db.Integer, primary_key=True)
    id_orden = db.Column(
        db.Integer, db.ForeignKey("ordenes_trabajo.id_orden", ondelete="CASCADE"), nullable=False
    )
    descripcion = db.Column(db.String(150), nullable=False)
    numero_parte = db.Column(db.String(50))
    costo_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    # Columna generada por PostgreSQL: costo_unitario * cantidad
    subtotal = db.Column(db.Numeric(10, 2), db.Computed("costo_unitario * cantidad", persisted=True))

    def __repr__(self):
        return f"<Pieza orden={self.id_orden} desc={self.descripcion}>"


class VehiculoAnomalia(db.Model):
    __tablename__ = "vehiculo_anomalias"

    id_anomalia = db.Column(db.Integer, primary_key=True)
    id_vehiculo = db.Column(
        db.Integer, db.ForeignKey("vehiculos.id_vehiculo", ondelete="CASCADE"), nullable=False
    )
    id_orden = db.Column(db.Integer, db.ForeignKey("ordenes_trabajo.id_orden", ondelete="SET NULL"))
    id_usuario = db.Column(db.Integer, db.ForeignKey("usuarios.id_usuario"))
    tipo_anomalia = db.Column(db.String(50), default="Detalle externo")
    descripcion = db.Column(db.Text, nullable=False)
    foto_path = db.Column(db.String(255))
    creado_en = db.Column(db.DateTime(timezone=True), server_default=func.now())

    usuario = db.relationship("Usuario", lazy="joined")

    @property
    def tiene_foto(self):
        return bool(self.foto_path)

    def __repr__(self):
        return f"<Anomalia vehiculo={self.id_vehiculo} tipo={self.tipo_anomalia}>"


class HistorialEstado(db.Model):
    __tablename__ = "historial_estados"

    id_historial = db.Column(db.Integer, primary_key=True)
    id_orden = db.Column(
        db.Integer, db.ForeignKey("ordenes_trabajo.id_orden", ondelete="CASCADE"), nullable=False
    )
    estado_anterior = db.Column(db.String(20))
    estado_nuevo = db.Column(db.String(20), nullable=False)
    id_usuario = db.Column(db.Integer, db.ForeignKey("usuarios.id_usuario"))
    fecha = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())

    usuario = db.relationship("Usuario", lazy="joined")
