-- =====================================================================
-- SGT-Mecánico · Esquema PostgreSQL (3FN)
-- Ejecutar con:  flask --app run init-db      (o)   psql -f schema.sql
-- Es idempotente para tablas (IF NOT EXISTS) y reemplaza funciones/triggers.
-- =====================================================================

CREATE TABLE IF NOT EXISTS roles (
    id_rol SERIAL PRIMARY KEY,
    nombre VARCHAR(30) UNIQUE NOT NULL            -- 'Administrador', 'Mecanico'
);

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario SERIAL PRIMARY KEY,
    id_rol INT NOT NULL REFERENCES roles(id_rol),
    username VARCHAR(50) UNIQUE NOT NULL,
    nombre_completo VARCHAR(120) NOT NULL,
    correo VARCHAR(100),
    password_hash VARCHAR(255) NOT NULL,
    porcentaje_comision_defecto NUMERIC(5, 2) DEFAULT 15.00
        CHECK (porcentaje_comision_defecto >= 0 AND porcentaje_comision_defecto <= 100),
    activo BOOLEAN DEFAULT TRUE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clientes (
    id_cliente SERIAL PRIMARY KEY,
    nombre_completo VARCHAR(120) NOT NULL,
    telefono VARCHAR(20) NOT NULL,
    correo VARCHAR(100),
    direccion TEXT,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vehiculos (
    id_vehiculo SERIAL PRIMARY KEY,
    id_cliente INT NOT NULL REFERENCES clientes(id_cliente) ON DELETE CASCADE,
    marca VARCHAR(50) NOT NULL,
    modelo VARCHAR(50) NOT NULL,
    anio INT NOT NULL CHECK (anio BETWEEN 1900 AND 2100),
    placas VARCHAR(20) UNIQUE NOT NULL,
    numero_serie_vin VARCHAR(50),
    color VARCHAR(30),
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Catálogo general de reparaciones y costos base
CREATE TABLE IF NOT EXISTS servicios (
    id_servicio SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    costo_base NUMERIC(10, 2) NOT NULL CHECK (costo_base >= 0),
    activo BOOLEAN DEFAULT TRUE
);

-- Histórico de liquidación de comisiones (se crea antes de ordenes_trabajo
-- porque las órdenes liquidadas apuntan al corte que las incluyó).
CREATE TABLE IF NOT EXISTS cortes_semanales (
    id_corte SERIAL PRIMARY KEY,
    id_mecanico INT NOT NULL REFERENCES usuarios(id_usuario),
    fecha_inicio DATE NOT NULL,
    fecha_fin DATE NOT NULL,
    total_reparaciones_monto NUMERIC(10, 2) NOT NULL,
    porcentaje_aplicado NUMERIC(5, 2) NOT NULL,
    monto_comision_pagar NUMERIC(10, 2) NOT NULL,
    estatus_pago VARCHAR(20) DEFAULT 'Pendiente' CHECK (estatus_pago IN ('Pendiente', 'Pagado')),
    cerrado_por_admin INT NOT NULL REFERENCES usuarios(id_usuario),
    fecha_cierre TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- Extras de trazabilidad
    cantidad_ordenes INT NOT NULL DEFAULT 0,
    fecha_pago TIMESTAMP WITH TIME ZONE,
    CHECK (fecha_fin >= fecha_inicio)
);

-- Entidad principal de reparación / ingreso
CREATE TABLE IF NOT EXISTS ordenes_trabajo (
    id_orden SERIAL PRIMARY KEY,
    id_vehiculo INT NOT NULL REFERENCES vehiculos(id_vehiculo),
    id_mecanico INT NOT NULL REFERENCES usuarios(id_usuario),
    fecha_ingreso TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_entrega_estimada TIMESTAMP WITH TIME ZONE,
    fecha_finalizacion TIMESTAMP WITH TIME ZONE,
    estado VARCHAR(20) NOT NULL DEFAULT 'Pendiente'
        CHECK (estado IN ('Pendiente', 'En Proceso', 'Completado', 'Entregado', 'Cancelado')),
    diagnostico_inicial TEXT,
    observaciones_finales TEXT,
    total_costo NUMERIC(10, 2) DEFAULT 0.00,
    liquidado_en_corte BOOLEAN DEFAULT FALSE,
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    -- Extras
    kilometraje INT CHECK (kilometraje IS NULL OR kilometraje >= 0),
    id_corte INT REFERENCES cortes_semanales(id_corte)
);

-- Servicios aplicados por orden
CREATE TABLE IF NOT EXISTS detalle_orden_servicios (
    id_detalle SERIAL PRIMARY KEY,
    id_orden INT NOT NULL REFERENCES ordenes_trabajo(id_orden) ON DELETE CASCADE,
    id_servicio INT NOT NULL REFERENCES servicios(id_servicio),
    costo_aplicado NUMERIC(10, 2) NOT NULL CHECK (costo_aplicado >= 0),
    cantidad INT NOT NULL DEFAULT 1 CHECK (cantidad > 0),
    subtotal NUMERIC(10, 2) GENERATED ALWAYS AS (costo_aplicado * cantidad) STORED
);

-- Piezas y refacciones aplicadas por orden (suman a la factura/orden de trabajo)
CREATE TABLE IF NOT EXISTS detalle_orden_piezas (
    id_pieza SERIAL PRIMARY KEY,
    id_orden INT NOT NULL REFERENCES ordenes_trabajo(id_orden) ON DELETE CASCADE,
    descripcion VARCHAR(150) NOT NULL,
    numero_parte VARCHAR(50),
    costo_unitario NUMERIC(10, 2) NOT NULL CHECK (costo_unitario >= 0),
    cantidad INT NOT NULL DEFAULT 1 CHECK (cantidad > 0),
    subtotal NUMERIC(10, 2) GENERATED ALWAYS AS (costo_unitario * cantidad) STORED
);

-- Anomalías, detalles y notas de inspección visual de vehículos (con foto opcional)
CREATE TABLE IF NOT EXISTS vehiculo_anomalias (
    id_anomalia SERIAL PRIMARY KEY,
    id_vehiculo INT NOT NULL REFERENCES vehiculos(id_vehiculo) ON DELETE CASCADE,
    id_orden INT REFERENCES ordenes_trabajo(id_orden) ON DELETE SET NULL,
    id_usuario INT REFERENCES usuarios(id_usuario),
    tipo_anomalia VARCHAR(50) DEFAULT 'Detalle externo',
    descripcion TEXT NOT NULL,
    foto_path VARCHAR(255),
    creado_en TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Bitácora de cambios de estado (seguimiento / auditoría)
CREATE TABLE IF NOT EXISTS historial_estados (
    id_historial SERIAL PRIMARY KEY,
    id_orden INT NOT NULL REFERENCES ordenes_trabajo(id_orden) ON DELETE CASCADE,
    estado_anterior VARCHAR(20),
    estado_nuevo VARCHAR(20) NOT NULL,
    id_usuario INT REFERENCES usuarios(id_usuario),
    fecha TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------
-- Índices de rendimiento
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_usuarios_rol ON usuarios(id_rol);
CREATE INDEX IF NOT EXISTS idx_usuarios_username ON usuarios(LOWER(username));
CREATE INDEX IF NOT EXISTS idx_clientes_nombre ON clientes(LOWER(nombre_completo));
CREATE INDEX IF NOT EXISTS idx_clientes_telefono ON clientes(telefono);
CREATE INDEX IF NOT EXISTS idx_vehiculos_cliente ON vehiculos(id_cliente);
CREATE INDEX IF NOT EXISTS idx_ordenes_vehiculo ON ordenes_trabajo(id_vehiculo);
CREATE INDEX IF NOT EXISTS idx_ordenes_mecanico_estado ON ordenes_trabajo(id_mecanico, estado);
CREATE INDEX IF NOT EXISTS idx_ordenes_estado ON ordenes_trabajo(estado);
CREATE INDEX IF NOT EXISTS idx_ordenes_ingreso ON ordenes_trabajo(fecha_ingreso);
CREATE INDEX IF NOT EXISTS idx_ordenes_finalizacion ON ordenes_trabajo(fecha_finalizacion);
CREATE INDEX IF NOT EXISTS idx_ordenes_pendientes_corte
    ON ordenes_trabajo(id_mecanico, estado) WHERE liquidado_en_corte = FALSE;
CREATE INDEX IF NOT EXISTS idx_ordenes_corte ON ordenes_trabajo(id_corte);
CREATE INDEX IF NOT EXISTS idx_detalle_orden ON detalle_orden_servicios(id_orden);
CREATE INDEX IF NOT EXISTS idx_detalle_servicio ON detalle_orden_servicios(id_servicio);
CREATE INDEX IF NOT EXISTS idx_detalle_piezas_orden ON detalle_orden_piezas(id_orden);
CREATE INDEX IF NOT EXISTS idx_anomalias_vehiculo ON vehiculo_anomalias(id_vehiculo);
CREATE INDEX IF NOT EXISTS idx_anomalias_orden ON vehiculo_anomalias(id_orden);
CREATE INDEX IF NOT EXISTS idx_cortes_mecanico ON cortes_semanales(id_mecanico, fecha_inicio);
CREATE INDEX IF NOT EXISTS idx_historial_orden ON historial_estados(id_orden);

-- ---------------------------------------------------------------------
-- Disparadores
-- ---------------------------------------------------------------------

-- 1) Recalcula ordenes_trabajo.total_costo cuando cambian servicios o piezas.
CREATE OR REPLACE FUNCTION fn_recalcular_total_orden() RETURNS TRIGGER AS $$
DECLARE
    v_orden INT;
    v_servicios NUMERIC(10, 2);
    v_piezas NUMERIC(10, 2);
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_orden := OLD.id_orden;
    ELSE
        v_orden := NEW.id_orden;
    END IF;

    SELECT COALESCE(SUM(subtotal), 0) INTO v_servicios
      FROM detalle_orden_servicios WHERE id_orden = v_orden;

    SELECT COALESCE(SUM(subtotal), 0) INTO v_piezas
      FROM detalle_orden_piezas WHERE id_orden = v_orden;

    UPDATE ordenes_trabajo
       SET total_costo = v_servicios + v_piezas
     WHERE id_orden = v_orden;

    IF TG_OP = 'UPDATE' AND OLD.id_orden IS DISTINCT FROM NEW.id_orden THEN
        SELECT COALESCE(SUM(subtotal), 0) INTO v_servicios
          FROM detalle_orden_servicios WHERE id_orden = OLD.id_orden;

        SELECT COALESCE(SUM(subtotal), 0) INTO v_piezas
          FROM detalle_orden_piezas WHERE id_orden = OLD.id_orden;

        UPDATE ordenes_trabajo
           SET total_costo = v_servicios + v_piezas
         WHERE id_orden = OLD.id_orden;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_recalcular_total_orden ON detalle_orden_servicios;
CREATE TRIGGER trg_recalcular_total_orden
    AFTER INSERT OR UPDATE OR DELETE ON detalle_orden_servicios
    FOR EACH ROW EXECUTE FUNCTION fn_recalcular_total_orden();

DROP TRIGGER IF EXISTS trg_recalcular_total_orden_piezas ON detalle_orden_piezas;
CREATE TRIGGER trg_recalcular_total_orden_piezas
    AFTER INSERT OR UPDATE OR DELETE ON detalle_orden_piezas
    FOR EACH ROW EXECUTE FUNCTION fn_recalcular_total_orden();

-- 2) Una orden ya liquidada en un corte no admite cambios en su detalle (servicios ni piezas).
CREATE OR REPLACE FUNCTION fn_bloquear_detalle_liquidado() RETURNS TRIGGER AS $$
DECLARE
    v_liquidado BOOLEAN;
    v_orden INT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        v_orden := OLD.id_orden;
    ELSE
        v_orden := NEW.id_orden;
    END IF;

    SELECT liquidado_en_corte INTO v_liquidado
      FROM ordenes_trabajo WHERE id_orden = v_orden;

    IF COALESCE(v_liquidado, FALSE) THEN
        RAISE EXCEPTION 'La orden % ya fue liquidada en un corte semanal y no puede modificarse.', v_orden;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_bloquear_detalle_liquidado ON detalle_orden_servicios;
CREATE TRIGGER trg_bloquear_detalle_liquidado
    BEFORE INSERT OR UPDATE OR DELETE ON detalle_orden_servicios
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_detalle_liquidado();

DROP TRIGGER IF EXISTS trg_bloquear_detalle_liquidado_piezas ON detalle_orden_piezas;
CREATE TRIGGER trg_bloquear_detalle_liquidado_piezas
    BEFORE INSERT OR UPDATE OR DELETE ON detalle_orden_piezas
    FOR EACH ROW EXECUTE FUNCTION fn_bloquear_detalle_liquidado();

-- 3) Una orden liquidada no puede cambiar de estado, mecánico ni total, ni borrarse.
CREATE OR REPLACE FUNCTION fn_proteger_orden_liquidada() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF COALESCE(OLD.liquidado_en_corte, FALSE) THEN
            RAISE EXCEPTION 'La orden % ya fue liquidada y no puede eliminarse.', OLD.id_orden;
        END IF;
        RETURN OLD;
    END IF;

    IF COALESCE(OLD.liquidado_en_corte, FALSE) AND COALESCE(NEW.liquidado_en_corte, FALSE) THEN
        IF NEW.estado IS DISTINCT FROM OLD.estado
           OR NEW.id_mecanico IS DISTINCT FROM OLD.id_mecanico
           OR NEW.total_costo IS DISTINCT FROM OLD.total_costo THEN
            RAISE EXCEPTION 'La orden % ya fue liquidada en un corte semanal y no puede modificarse.', OLD.id_orden;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_proteger_orden_liquidada ON ordenes_trabajo;
CREATE TRIGGER trg_proteger_orden_liquidada
    BEFORE UPDATE OR DELETE ON ordenes_trabajo
    FOR EACH ROW EXECUTE FUNCTION fn_proteger_orden_liquidada();

-- 4) Los cortes son inalterables: sólo puede cambiar estatus_pago / fecha_pago.
CREATE OR REPLACE FUNCTION fn_cortes_inalterables() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Los cortes semanales son inalterables y no pueden eliminarse.';
    END IF;

    IF NEW.id_corte IS DISTINCT FROM OLD.id_corte
       OR NEW.id_mecanico IS DISTINCT FROM OLD.id_mecanico
       OR NEW.fecha_inicio IS DISTINCT FROM OLD.fecha_inicio
       OR NEW.fecha_fin IS DISTINCT FROM OLD.fecha_fin
       OR NEW.total_reparaciones_monto IS DISTINCT FROM OLD.total_reparaciones_monto
       OR NEW.porcentaje_aplicado IS DISTINCT FROM OLD.porcentaje_aplicado
       OR NEW.monto_comision_pagar IS DISTINCT FROM OLD.monto_comision_pagar
       OR NEW.cerrado_por_admin IS DISTINCT FROM OLD.cerrado_por_admin
       OR NEW.fecha_cierre IS DISTINCT FROM OLD.fecha_cierre
       OR NEW.cantidad_ordenes IS DISTINCT FROM OLD.cantidad_ordenes THEN
        RAISE EXCEPTION 'Los cortes semanales son inalterables (sólo se puede marcar como pagado).';
    END IF;

    IF OLD.estatus_pago = 'Pagado' AND NEW.estatus_pago <> 'Pagado' THEN
        RAISE EXCEPTION 'Un corte pagado no puede volver a estado pendiente.';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cortes_inalterables ON cortes_semanales;
CREATE TRIGGER trg_cortes_inalterables
    BEFORE UPDATE OR DELETE ON cortes_semanales
    FOR EACH ROW EXECUTE FUNCTION fn_cortes_inalterables();

-- ---------------------------------------------------------------------
-- Datos base
-- ---------------------------------------------------------------------
INSERT INTO roles (nombre) VALUES ('Administrador'), ('Mecanico')
ON CONFLICT (nombre) DO NOTHING;
