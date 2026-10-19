"""Utilidades: decoradores RBAC, formateadores de moneda/fecha, paginación y PDF."""
import io
import re
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import wraps
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from flask import abort, current_app, flash, jsonify, redirect, request
from flask_login import current_user

from .models import ROL_ADMIN, ROL_MECANICO

CENTAVOS = Decimal("0.01")


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def roles_required(*roles):
    """Restringe una vista a los roles indicados (403 si no corresponde)."""
    def decorador(vista):
        @wraps(vista)
        def envoltura(*args, **kwargs):
            if not current_user.is_authenticated:
                from . import login_manager
                return login_manager.unauthorized()
            if current_user.rol is None or current_user.rol.nombre not in roles:
                abort(403)
            return vista(*args, **kwargs)
        return envoltura
    return decorador


admin_required = roles_required(ROL_ADMIN)
staff_required = roles_required(ROL_ADMIN, ROL_MECANICO)


# ---------------------------------------------------------------------------
# Peticiones AJAX / respuestas duales (JSON o flash + redirect)
# ---------------------------------------------------------------------------
def es_ajax():
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.is_json
        or request.accept_mimetypes.best == "application/json"
    )


def responder(ok, mensaje, destino=None, status=None, **extra):
    """Devuelve JSON si la petición es AJAX; si no, flash + redirect."""
    if es_ajax():
        cuerpo = {"ok": ok, "mensaje": mensaje}
        cuerpo.update(extra)
        if destino:
            cuerpo["redirect"] = destino
        return jsonify(cuerpo), (status or (200 if ok else 400))
    flash(mensaje, "success" if ok else "danger")
    return redirect(destino or request.referrer or "/")


def url_segura(destino):
    """Evita open-redirects: sólo acepta URLs del mismo host."""
    if not destino:
        return False
    base = urlparse(request.host_url)
    objetivo = urlparse(urljoin(request.host_url, destino))
    return objetivo.scheme in ("http", "https") and base.netloc == objetivo.netloc


# ---------------------------------------------------------------------------
# Zona horaria y fechas
# ---------------------------------------------------------------------------
def zona():
    return ZoneInfo(current_app.config["APP_TIMEZONE"])


def ahora():
    return datetime.now(zona())


def hoy():
    return ahora().date()


def a_local(valor):
    if valor is None:
        return None
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=ZoneInfo("UTC"))
        return valor.astimezone(zona())
    return valor


def formato_fecha(valor):
    if not valor:
        return "—"
    valor = a_local(valor)
    return valor.strftime("%d/%m/%Y")


def formato_fecha_hora(valor):
    if not valor:
        return "—"
    return a_local(valor).strftime("%d/%m/%Y %H:%M")


def formato_input_datetime(valor):
    """Valor para <input type="datetime-local"> en hora local del taller."""
    if not valor:
        return ""
    return a_local(valor).strftime("%Y-%m-%dT%H:%M")


def formato_moneda(valor):
    try:
        valor = Decimal(valor if valor is not None else 0)
    except (InvalidOperation, TypeError, ValueError):
        valor = Decimal(0)
    signo = "-" if valor < 0 else ""
    return f"{signo}${abs(valor):,.2f}"


def formato_porcentaje(valor):
    try:
        return f"{Decimal(valor):.2f}%".replace(".00%", "%")
    except (InvalidOperation, TypeError, ValueError):
        return "0%"


def parse_fecha_hora_local(texto, campo="Fecha"):
    """'YYYY-MM-DDTHH:MM' (hora local del taller) -> datetime con zona. None si vacío."""
    texto = (texto or "").strip()
    if not texto:
        return None
    for patron in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, patron).replace(tzinfo=zona())
        except ValueError:
            continue
    raise ValueError(f"{campo}: formato de fecha inválido.")


def parse_fecha(texto, campo="Fecha"):
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"{campo}: formato de fecha inválido.")


def parse_decimal(texto, campo="Valor", minimo=Decimal("0"), maximo=None):
    texto = str(texto if texto is not None else "").strip().replace(",", "").replace("$", "")
    if texto == "":
        raise ValueError(f"{campo} es obligatorio.")
    try:
        valor = Decimal(texto).quantize(CENTAVOS, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{campo} debe ser un número válido.")
    if minimo is not None and valor < minimo:
        raise ValueError(f"{campo} no puede ser menor a {minimo}.")
    if maximo is not None and valor > maximo:
        raise ValueError(f"{campo} no puede ser mayor a {maximo}.")
    return valor


def parse_entero(texto, campo="Valor", minimo=None, maximo=None, obligatorio=True):
    texto = str(texto if texto is not None else "").strip()
    if texto == "":
        if obligatorio:
            raise ValueError(f"{campo} es obligatorio.")
        return None
    try:
        valor = int(texto)
    except ValueError:
        raise ValueError(f"{campo} debe ser un número entero.")
    if minimo is not None and valor < minimo:
        raise ValueError(f"{campo} no puede ser menor a {minimo}.")
    if maximo is not None and valor > maximo:
        raise ValueError(f"{campo} no puede ser mayor a {maximo}.")
    return valor


def limites_dias(inicio, fin):
    """(inicio_incl, fin_excl) como datetimes con zona para un rango de fechas."""
    tz = zona()
    desde = datetime.combine(inicio, time.min, tzinfo=tz)
    hasta = datetime.combine(fin + timedelta(days=1), time.min, tzinfo=tz)
    return desde, hasta


def rango_semana(referencia=None):
    """Lunes y domingo de la semana de `referencia` (por defecto hoy)."""
    referencia = referencia or hoy()
    lunes = referencia - timedelta(days=referencia.weekday())
    return lunes, lunes + timedelta(days=6)


def rango_mes(anio, mes):
    inicio = date(anio, mes, 1)
    siguiente = date(anio + (mes == 12), 1 if mes == 12 else mes + 1, 1)
    return inicio, siguiente - timedelta(days=1)


# ---------------------------------------------------------------------------
# Validaciones varias
# ---------------------------------------------------------------------------
def normalizar_placas(placas):
    return re.sub(r"\s+", "", (placas or "")).upper()


def limpiar(texto, maximo=None):
    texto = (texto or "").strip()
    texto = re.sub(r"[ \t]+", " ", texto)
    if maximo:
        texto = texto[:maximo]
    return texto


def validar_username(username):
    if not username:
        return "El nombre de usuario es obligatorio."
    username = username.strip()
    if len(username) < 3 or len(username) > 30:
        return "El nombre de usuario debe tener entre 3 y 30 caracteres."
    if not re.fullmatch(r"[a-zA-Z0-9_\-\.]+", username):
        return "El nombre de usuario sólo puede contener letras, números, puntos, guiones y guiones bajos."
    return None


def validar_correo(correo):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo or ""))


def validar_password(password):
    if len(password or "") < 8:
        return "La contraseña debe tener al menos 8 caracteres."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "La contraseña debe incluir letras y números."
    return None


# ---------------------------------------------------------------------------
# Paginación (sobre db.session.query / Model.query)
# ---------------------------------------------------------------------------
class Paginacion:
    def __init__(self, query, pagina, por_pagina):
        self.por_pagina = por_pagina
        self.total = query.order_by(None).count()
        self.paginas = max(1, -(-self.total // por_pagina))
        self.pagina = min(max(1, pagina), self.paginas)
        self.items = query.limit(por_pagina).offset((self.pagina - 1) * por_pagina).all()

    @property
    def tiene_anterior(self):
        return self.pagina > 1

    @property
    def tiene_siguiente(self):
        return self.pagina < self.paginas

    @property
    def desde(self):
        return 0 if self.total == 0 else (self.pagina - 1) * self.por_pagina + 1

    @property
    def hasta(self):
        return min(self.total, self.pagina * self.por_pagina)

    def paginas_visibles(self, alrededor=2):
        visibles = []
        ultimo = 0
        for n in range(1, self.paginas + 1):
            if n == 1 or n == self.paginas or abs(n - self.pagina) <= alrededor:
                if ultimo and n - ultimo > 1:
                    visibles.append(None)
                visibles.append(n)
                ultimo = n
        return visibles


def pagina_actual():
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1


# ---------------------------------------------------------------------------
# PDF del corte semanal (ReportLab)
# ---------------------------------------------------------------------------
def generar_pdf_corte(corte, ordenes, nombre_taller):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=letter, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title=f"Corte {corte.folio}", author=nombre_taller,
    )
    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("titulo", parent=estilos["Title"], fontSize=20, textColor=colors.HexColor("#0f172a"))
    sub = ParagraphStyle("sub", parent=estilos["Normal"], fontSize=10, textColor=colors.HexColor("#475569"))
    normal = ParagraphStyle("normal", parent=estilos["Normal"], fontSize=9)
    azul = colors.HexColor("#1d4ed8")

    contenido = [
        Paragraph(nombre_taller, titulo),
        Paragraph(f"Reporte de pago de comisiones · {corte.folio}", sub),
        Spacer(1, 0.5 * cm),
    ]

    datos = [
        ["Mecánico", corte.mecanico.nombre_completo, "Periodo",
         f"{corte.fecha_inicio.strftime('%d/%m/%Y')} al {corte.fecha_fin.strftime('%d/%m/%Y')}"],
        ["Cerrado por", corte.admin_cierre.nombre_completo, "Fecha de cierre", formato_fecha_hora(corte.fecha_cierre)],
        ["Órdenes incluidas", str(corte.cantidad_ordenes), "Estatus de pago", corte.estatus_pago],
    ]
    tabla_datos = Table(datos, colWidths=[3.2 * cm, 5.6 * cm, 3.2 * cm, 5.4 * cm])
    tabla_datos.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#475569")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    contenido += [tabla_datos, Spacer(1, 0.6 * cm)]

    filas = [["Folio", "Ingreso", "Vehículo", "Placas", "Total"]]
    for o in ordenes:
        filas.append([
            o.folio, formato_fecha(o.fecha_ingreso),
            Paragraph(o.vehiculo.descripcion, normal), o.vehiculo.placas,
            formato_moneda(o.total_costo),
        ])
    tabla = Table(filas, colWidths=[2.4 * cm, 2.6 * cm, 6.2 * cm, 3 * cm, 3.2 * cm], repeatRows=1)
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), azul),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    contenido += [tabla, Spacer(1, 0.6 * cm)]

    resumen = [
        ["Total de reparaciones", formato_moneda(corte.total_reparaciones_monto)],
        ["Porcentaje de comisión", formato_porcentaje(corte.porcentaje_aplicado)],
        ["COMISIÓN A PAGAR", formato_moneda(corte.monto_comision_pagar)],
    ]
    tabla_res = Table(resumen, colWidths=[5 * cm, 4 * cm], hAlign="RIGHT")
    tabla_res.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
        ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#dbeafe")),
        ("LINEABOVE", (0, 2), (-1, 2), 0.8, azul),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    contenido += [tabla_res, Spacer(1, 2.2 * cm)]

    firmas = Table(
        [["______________________________", "______________________________"],
         ["Firma del mecánico", "Firma de la administración"]],
        colWidths=[8.5 * cm, 8.5 * cm],
    )
    firmas.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#475569")),
    ]))
    contenido.append(firmas)

    doc.build(contenido)
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Gestión de fotos e imágenes
# ---------------------------------------------------------------------------
def guardar_foto_vehiculo(archivo):
    """Procesa y guarda una foto de inspección de vehículo.

    - Valida extensión permitida.
    - Corrige orientación EXIF (cámaras de celulares).
    - Redimensiona a un máximo de 1600x1600 px manteniendo proporción.
    - Guarda en formato JPEG optimizado.
    - Retorna la ruta relativa: 'uploads/vehiculos/<uuid>.jpg'
    """
    import os
    import uuid
    from PIL import Image, ImageOps

    if not archivo or not getattr(archivo, "filename", None):
        return None

    nombre_orig = archivo.filename
    if "." not in nombre_orig:
        raise ValueError("El archivo no tiene extensión válida.")

    ext = nombre_orig.rsplit(".", 1)[1].lower()
    permitidas = current_app.config.get("ALLOWED_IMAGE_EXTENSIONS", {"jpg", "jpeg", "png", "webp"})
    if ext not in permitidas:
        raise ValueError(f"Formato no permitido. Usa {', '.join(sorted(permitidas))}.")

    carpeta_destino = os.path.join(current_app.config["UPLOAD_FOLDER"], "vehiculos")
    os.makedirs(carpeta_destino, exist_ok=True)

    nombre_archivo = f"{uuid.uuid4().hex}.jpg"
    ruta_absoluta = os.path.join(carpeta_destino, nombre_archivo)

    try:
        img = Image.open(archivo.stream)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        img.save(ruta_absoluta, format="JPEG", quality=85, optimize=True)
    except Exception as e:
        current_app.logger.exception("Error al procesar la imagen")
        raise ValueError("No se pudo procesar la imagen enviada.") from e

    return f"uploads/vehiculos/{nombre_archivo}"


def ruta_foto_vehiculo(foto_path):
    """Ruta absoluta en disco de una foto ('uploads/vehiculos/<archivo>.jpg') o None si no es válida."""
    import os
    nombre = os.path.basename(foto_path or "")
    if not nombre or not (foto_path or "").replace("\\", "/").startswith("uploads/vehiculos/"):
        return None
    return os.path.join(current_app.config["UPLOAD_FOLDER"], "vehiculos", nombre)


def eliminar_foto_vehiculo(foto_path):
    """Elimina físicamente una foto del disco si existe."""
    import os
    if not foto_path:
        return
    ruta_absoluta = ruta_foto_vehiculo(foto_path)
    if ruta_absoluta is None:
        return
    if os.path.exists(ruta_absoluta):
        try:
            os.remove(ruta_absoluta)
        except OSError:
            current_app.logger.warning(f"No se pudo eliminar el archivo {ruta_absoluta}")

