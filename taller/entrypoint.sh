#!/usr/bin/env bash
set -e

echo ">> Esperando a que PostgreSQL esté listo..."
until python -c "
import os, psycopg2
try:
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'db'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'taller_mecanico'),
        user=os.getenv('DB_USER', 'taller_user'),
        password=os.getenv('DB_PASSWORD', 'taller_pass'),
        connect_timeout=2
    )
    conn.close()
    exit(0)
except Exception:
    exit(1)
" 2>/dev/null; do
    echo ">> Base de datos no disponible aún, esperando 1 segundo..."
    sleep 1
done

echo ">> Conexión a PostgreSQL confirmada."

echo ">> Inicializando base de datos (schema, triggers, índices y roles)..."
flask --app run init-db

echo ">> Asegurando recursos estáticos..."
if [ ! -f "app/static/vendor/bootstrap/bootstrap.min.css" ]; then
    flask --app run descargar-vendor || true
fi

# Cargar datos de demostración si la base está vacía
python -c "
from app import create_app, db
from app.models import Usuario
app = create_app()
with app.app_context():
    if Usuario.query.first() is None:
        print('>> Base vacía detectada. Cargando datos iniciales demo...')
        from app.cli import _crear_usuario, _asegurar_roles, ROL_ADMIN, ROL_MECANICO, Servicio
        from decimal import Decimal
        _asegurar_roles()
        _crear_usuario('Administrador Principal', 'admin', 'Admin1234', ROL_ADMIN, 0, correo='admin@taller.local')
        _crear_usuario('Carlos Ramírez', 'carlos', 'Mecanico123', ROL_MECANICO, 15, correo='carlos@taller.local')
        _crear_usuario('Luis Hernández', 'luis', 'Mecanico123', ROL_MECANICO, 18, correo='luis@taller.local')
        catalogo = [
            ('Cambio de aceite y filtro', 'Aceite sintético 5W-30 y filtro', 650),
            ('Afinación mayor', 'Bujías, filtros, limpieza de inyectores', 1850),
            ('Cambio de balatas delanteras', 'Incluye rectificado de discos', 950),
            ('Alineación y balanceo', '4 ruedas', 700),
            ('Diagnóstico con escáner', 'Lectura y borrado de códigos', 400),
            ('Cambio de batería', 'Mano de obra (batería aparte)', 250),
            ('Cambio de banda de distribución', 'Incluye tensor y bomba de agua', 3200),
            ('Revisión de suspensión', 'Amortiguadores, rótulas y terminales', 800),
            ('Servicio de A/C', 'Carga de gas y revisión de fugas', 1100),
            ('Cambio de embrague', 'Kit completo', 4200),
        ]
        for n, d, c in catalogo:
            db.session.add(Servicio(nombre=n, descripcion=d, costo_base=Decimal(c), activo=True))
        db.session.commit()
        print('>> Usuarios base creados: admin / Admin1234, carlos / Mecanico123, luis / Mecanico123')
"

echo ">> Arrancando servidor de producción Gunicorn (alta concurrencia y fluidez)..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 3 \
    --threads 4 \
    --worker-class gthread \
    --worker-tmp-dir /dev/shm \
    --timeout 120 \
    --keep-alive 5 \
    --access-logfile - \
    --error-logfile - \
    run:app
