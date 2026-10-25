"""Local-network helpers: LAN address discovery + a tiny QR SVG renderer.

Used by /api/app/download so a phone on the same Wi-Fi can scan a QR
code and load the app without typing an IP address.
"""
from __future__ import annotations

import socket
from urllib.parse import urlparse

import qrcode


def lan_addresses() -> list[str]:
    """The machine's LAN IPv4 addresses.

    The UDP-connect trick picks the route to an external address without
    sending any packet, so it works even on isolated networks.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
    except OSError:
        return []
    return [ip] if not ip.startswith("127.") else []


def is_own_address(host: str) -> bool:
    """True if host names this machine (loopback or a LAN address)."""
    return host in ("localhost", "127.0.0.1", "::1") or host in lan_addresses()


def qr_svg(data: str) -> str:
    """Render data as a compact SVG QR code (one path of module squares)."""
    qr = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    size = len(matrix)
    squares = "".join(
        f"M{x} {y}h1v1h-1z"
        for y, row in enumerate(matrix)
        for x, dark in enumerate(row)
        if dark
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'shape-rendering="crispEdges"><rect width="{size}" height="{size}" '
        f'fill="#ffffff"/><path d="{squares}" fill="#2b2a28"/></svg>'
    )
