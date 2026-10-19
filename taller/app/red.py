"""Utilidades de red local: IPs del servidor y códigos QR para conectar dispositivos."""
import ipaddress
import socket

import qrcode
import qrcode.image.svg

# Rangos típicos de adaptadores virtuales (VirtualBox, Hyper-V, WSL, Docker) que un
# celular del taller nunca puede alcanzar: se muestran al final.
_VIRTUALES = (
    ipaddress.ip_network("192.168.56.0/24"),   # VirtualBox host-only
    ipaddress.ip_network("172.16.0.0/12"),     # Hyper-V / WSL / Docker suelen usarlo
)


def _es_lan(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return (
        addr.version == 4 and addr.is_private
        and not addr.is_loopback and not addr.is_link_local
    )


def _ip_principal():
    """IP de la interfaz con la que el equipo sale a la red (no envía paquetes)."""
    for destino in ("8.8.8.8", "192.168.1.1", "10.0.0.1"):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((destino, 80))
            ip = s.getsockname()[0]
            if _es_lan(ip):
                return ip
        except OSError:
            continue
        finally:
            s.close()
    return None


def ips_lan():
    """Lista de IPv4 privadas del servidor; la primera es la recomendada."""
    encontradas = []
    principal = _ip_principal()
    if principal:
        encontradas.append(principal)
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if _es_lan(ip) and ip not in encontradas:
                encontradas.append(ip)
    except OSError:
        pass

    def prioridad(ip):
        if ip == principal:
            return 0
        addr = ipaddress.ip_address(ip)
        return 2 if any(addr in red for red in _VIRTUALES) else 1

    return sorted(encontradas, key=prioridad)


def nombre_equipo():
    try:
        return socket.gethostname()
    except OSError:
        return ""


def qr_svg(texto):
    """Código QR como SVG en línea (escalable, sin archivos ni dependencias de imagen)."""
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10, border=2, image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data(texto)
    qr.make(fit=True)
    svg = qr.make_image().to_string(encoding="unicode")
    # Quitar declaración XML y medidas fijas en mm: el tamaño lo controla el CSS.
    if svg.startswith("<?xml"):
        svg = svg[svg.index("?>") + 2:]
    svg = svg.replace("<svg ", '<svg role="img" aria-label="Código QR" ', 1)
    for atributo in ("width", "height"):
        inicio = svg.find(f'{atributo}="')
        if 0 <= inicio < svg.find(">"):
            fin = svg.index('"', inicio + len(atributo) + 2)
            svg = svg[:inicio] + svg[fin + 1:]
    return svg.strip()
