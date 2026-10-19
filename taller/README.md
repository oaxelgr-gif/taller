# SGT-Mecánico · Sistema Integral de Gestión de Taller Mecánico

Aplicación web (Flask + PostgreSQL) para controlar el flujo del taller: clientes y vehículos, órdenes de trabajo
con diagnóstico y servicios, catálogo de precios, usuarios con roles y el **corte semanal de comisiones** por mecánico.
Diseño *Liquid Glass* (estilo Apple), responsivo y accesible desde PCs, tablets y celulares de la red local.

## Características

- **Roles (RBAC):** Administrador (todo) y Mecánico (clientes/vehículos, crear órdenes, avanzar el estado de *sus* trabajos, ver su historial y su comisión estimada).
- **Órdenes de trabajo:** lista y tablero Kanban, filtros en vivo, servicios múltiples del catálogo con costo ajustable, total recalculado por **trigger de BD** y por el ORM, historial de estados, hoja de trabajo imprimible.
- **Fechas validadas:** el ingreso toma la fecha/hora actual, admite fechas pasadas y **rechaza fechas futuras** (frontend y backend).
- **Clientes y vehículos:** búsqueda AJAX en tiempo real, alta rápida (cliente + vehículo) desde la propia orden, placas únicas.
- **Comisiones:** pre-corte con porcentaje ajustable, cierre que genera un registro **inalterable** (`cortes_semanales`) y marca las órdenes como liquidadas (protegidas por triggers), estatus de pago, **PDF** y vista de impresión.
- **Dashboard:** total ingresado, reparaciones concluidas, ganancia neta (ingresos − comisiones), mecánico más productivo, gráfica de 14 días; panel propio para cada mecánico.
- **Seguridad:** contraseñas con hash, CSRF en todos los formularios, límite de intentos de login, cabeceras de seguridad, protección contra *open redirect*, reglas de negocio también en la base de datos.

## Requisitos

- Python 3.10 o superior
- PostgreSQL 13 o superior
- Navegador moderno (Chrome, Edge, Safari, Firefox)

## Instalación paso a paso

### 1. Entorno virtual e instalación de dependencias

```bash
cd taller_mecanico
python -m venv venv

# macOS / Linux
source venv/bin/activate
# Windows (PowerShell)
venv\Scripts\Activate.ps1
# Windows (CMD)
venv\Scripts\activate.bat

pip install -r requirements.txt
```

### 2. Crear la base de datos PostgreSQL

Edita la contraseña en `scripts/crear_base_datos.sql` y ejecútalo como superusuario:

```bash
psql -U postgres -f scripts/crear_base_datos.sql
```

(o, manualmente: `CREATE USER taller_user WITH PASSWORD '...'; CREATE DATABASE taller_mecanico OWNER taller_user;`)

### 3. Configurar el archivo `.env`

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Edita `.env`: pon una `SECRET_KEY` larga y aleatoria (`python -c "import secrets; print(secrets.token_hex(32))"`)
y los datos de conexión (`DB_HOST`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`) o una `DATABASE_URL` completa.

### 4. Crear tablas, índices y triggers

```bash
flask --app run init-db
```

Ejecuta `schema.sql`: tablas en 3FN, índices, triggers (total automático, bloqueo de órdenes liquidadas, cortes inalterables) y roles base. Es seguro repetirlo.

### 5. Crear el primer administrador

```bash
flask --app run crear-admin
```

*(Opcional, para probar)* `flask --app run datos-demo` carga catálogo, clientes y órdenes de ejemplo con estos accesos:
`admin@taller.local / Admin1234` · `carlos@taller.local` y `luis@taller.local / Mecanico123`. **No lo uses en producción.**

### 6. (Recomendado) Recursos locales para funcionar sin internet

Por defecto Bootstrap 5 se carga desde CDN. Si la red del taller **no tiene internet**, descárgalo una vez (en una máquina con conexión) y se servirá localmente:

```bash
flask --app run descargar-vendor
```

### 7. Ejecutar el servidor

```bash
python run.py
```

Escucha en `0.0.0.0:5000`. En el equipo servidor abre <http://localhost:5000>.
Atajo: `./iniciar.sh` (macOS/Linux) o `iniciar.bat` (Windows) hacen los pasos 1 y 7 automáticamente.

## Instalación en Windows (computadora servidor del taller)

Para dejar una PC con Windows 10/11 (64 bits, desde 4 GB de RAM) como servidor del taller:

1. En la PC de desarrollo: `python despliegue_windows/construir_zip.py` → genera `dist/SGT-Taller-Windows-AAAA-MM-DD.zip`.
2. En la PC del taller: extraer el ZIP y ejecutar **`INSTALAR_O_ACTUALIZAR.bat`** (pide permisos de administrador).

El instalador (`despliegue_windows/instalador/instalar.ps1`) deja todo en `C:\SGT-Taller` sin Docker:
Python 3.12 portátil, PostgreSQL 16 como servicio (puerto 5433, sólo local, memoria ajustada), librerías,
`.env` con claves aleatorias, base de datos y administrador, regla de firewall para la red local,
equipo sin suspensión con corriente, ícono **SGT Taller** en el escritorio con el logo y arranque automático al iniciar Windows.
El servidor es `waitress` (`windows/servidor.py`), corre sin ventana y hace un respaldo diario con `pg_dump` (conserva 30).
Para actualizar se ejecuta el mismo `.bat` con un ZIP nuevo: conserva datos, fotos y `.env`, y respalda antes de cambiar nada.

## Acceso desde otros dispositivos (PCs, tablets, celulares)

1. Conecta todos los dispositivos a la misma red WiFi/Ethernet del taller.
2. Averigua la IP del equipo servidor: `ipconfig` (Windows), `ipconfig getifaddr en0` (macOS) o `hostname -I` (Linux). Ej.: `192.168.1.50`.
3. Desde cualquier dispositivo abre `http://192.168.1.50:5000`.
   En el sistema, el menú **Conectar dispositivos** muestra la dirección correcta y un **código QR** (con cartel imprimible).
4. Si no conecta, permite el puerto **5000** en el firewall del servidor (Windows: *Firewall de Windows Defender → Reglas de entrada → Nueva regla → Puerto 5000*).
5. Recomendado: asigna una **IP fija** (o reserva DHCP en el router) al equipo servidor para que la dirección no cambie.

## Uso rápido

| Rol | Qué puede hacer |
| --- | --- |
| Administrador | Dashboard, usuarios (crear/editar/desactivar), catálogo y precios, todas las órdenes, clientes/vehículos (CRUD), cortes de comisiones (calcular, cerrar, marcar pagado, PDF). |
| Mecánico | Crear clientes/vehículos y órdenes, mover **sus** órdenes Pendiente → En Proceso → Completado, agregar/ajustar servicios mientras la orden está activa, ver su historial, su comisión estimada de la semana y sus cortes. |

**Corte semanal:** *Comisiones y cortes* → elige mecánico y periodo → *Calcular pre-corte* → (opcional) ajusta el porcentaje → *Cerrar y congelar corte*.
`Comisión = Σ total de órdenes «Completado»/«Entregado» aún no liquidadas × (porcentaje ÷ 100)`.
Una vez cerrado, el corte no puede modificarse y sus órdenes quedan bloqueadas (también a nivel de base de datos).
La fecha que ubica a una orden dentro de un periodo es la de **finalización** (o la de ingreso si aún no tiene).

## Estructura

```
taller_mecanico/
├── run.py · config.py · schema.sql · requirements.txt · .env.example
├── uploads/      (fotos de anomalías, privadas) · tests/ (pytest)
├── iniciar.sh · iniciar.bat · scripts/crear_base_datos.sql
└── app/
    ├── __init__.py   (fábrica Flask, filtros Jinja, errores)   models.py   services.py (comisiones/KPIs)
    ├── utils.py      (RBAC, formatos, paginación, PDF)         cli.py      (init-db, crear-admin, datos-demo, descargar-vendor)
    ├── routes/       auth · admin · clientes · ordenes · mecanico
    ├── static/       css/{glassmorphic,main}.css · js/{main,ordenes,comisiones}.js · img/
    └── templates/    base · auth · admin · clientes · ordenes · mecanico · errors
```

## Producción y mantenimiento

- **Servidor WSGI:** `python run.py` usa el servidor de desarrollo de Flask (multihilo), suficiente para un taller. Para mayor robustez: `pip install waitress` y `waitress-serve --host=0.0.0.0 --port=5000 run:app` (Windows) o `gunicorn -w 3 -b 0.0.0.0:5000 run:app` (Linux/macOS).
- **Respaldos:** `pg_dump -U taller_user -h localhost taller_mecanico > respaldo_$(date +%F).sql` (prográmalo a diario). Restaurar: `psql -U taller_user -d taller_mecanico -f respaldo.sql`.
- **Zona horaria:** variable `APP_TIMEZONE` (por defecto `America/Mexico_City`). En Windows es necesario el paquete `tzdata` (incluido en `requirements.txt`).
- **HTTPS:** si lo pones detrás de HTTPS, define `SESSION_COOKIE_SECURE=1`.
- **Fotos de anomalías:** se guardan en la carpeta `uploads/` (fuera de `static/`) y sólo se muestran a usuarios con sesión iniciada. Inclúyela en tus respaldos junto con el `pg_dump`. Con Docker se monta como volumen, así que no se pierde al reconstruir el contenedor.
- **Comisiones:** se calculan sólo sobre mano de obra (servicios); las piezas no generan comisión. La misma regla aplica en el corte, el dashboard, el panel del mecánico y el reporte financiero (`services.base_comision`).
- **Docker, primer arranque:** `SECRET_KEY` es obligatoria en `.env` (la app no arranca sin ella). Si la base está vacía se crea sólo el usuario `admin` con la contraseña de `ADMIN_PASSWORD`, o una temporal que aparece en `docker compose logs web`. Los datos de demostración se cargan únicamente con `CARGAR_DEMO=1`. PostgreSQL sólo escucha en `127.0.0.1` (no en la red del taller).
- **Pruebas:** `pip install pytest && pytest -q` ejecuta las pruebas de la regla de comisiones (`tests/`).

## Solución de problemas

- *`connection refused` / `password authentication failed`:* revisa `DB_*` en `.env` y que PostgreSQL esté activo.
- *`relation "usuarios" does not exist`:* falta `flask --app run init-db`.
- *La página se ve sin estilos ni iconos:* el equipo no tiene internet → ejecuta `flask --app run descargar-vendor`.
- *No abre desde el celular:* misma red, IP correcta y puerto 5000 permitido en el firewall.
- *«El formulario expiró»:* recarga la página (la sesión venció o cambió la `SECRET_KEY`).
