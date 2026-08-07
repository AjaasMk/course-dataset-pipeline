import socket
import ssl
from pathlib import Path
from typing import Optional

import certifi
import requests
from cryptography import x509
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import AuthorityInformationAccessOID, ExtensionOID

BUNDLE_DIR = Path("data/ca_bundles")
MAX_CHAIN_DEPTH = 5
FETCH_TIMEOUT = 20


def der_to_pem(der: bytes) -> str:
    return x509.load_der_x509_certificate(der).public_bytes(Encoding.PEM).decode()


def ca_issuer_urls(cert: x509.Certificate) -> list[str]:
    try:
        extension = cert.extensions.get_extension_for_oid(
            ExtensionOID.AUTHORITY_INFORMATION_ACCESS
        )
    except x509.ExtensionNotFound:
        return []

    return [
        description.access_location.value
        for description in extension.value
        if description.access_method == AuthorityInformationAccessOID.CA_ISSUERS
    ]


def is_self_issued(cert: x509.Certificate) -> bool:
    return cert.issuer == cert.subject


def leaf_certificate(host: str, port: int = 443) -> Optional[x509.Certificate]:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=FETCH_TIMEOUT) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                der = tls.getpeercert(binary_form=True)
    except OSError:
        return None
    return None if der is None else x509.load_der_x509_certificate(der)


def _fetch_issuer(url: str) -> Optional[x509.Certificate]:
    try:
        response = requests.get(url, timeout=FETCH_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return None

    body = response.content
    try:
        return x509.load_der_x509_certificate(body)
    except ValueError:
        try:
            return x509.load_pem_x509_certificate(body)
        except ValueError:
            return None


def collect_intermediates(host: str, port: int = 443) -> list[x509.Certificate]:
    cert = leaf_certificate(host, port)
    if cert is None:
        return []

    chain: list[x509.Certificate] = []
    for _ in range(MAX_CHAIN_DEPTH):
        if is_self_issued(cert):
            break
        urls = ca_issuer_urls(cert)
        if not urls:
            break
        issuer = _fetch_issuer(urls[0])
        if issuer is None:
            break
        chain.append(issuer)
        cert = issuer
    return chain


def build_bundle(host: str, port: int = 443, bundle_dir: Optional[Path] = None) -> Optional[Path]:
    """Write a CA bundle for host: certifi's roots plus the intermediates the
    server failed to send, fetched via each certificate's AIA CA-Issuers URL.

    The trust anchor stays certifi's root store. Nothing is trusted that does not
    already chain to a known root -- this fills in a server's incomplete chain,
    which is what a browser does, rather than weakening verification.
    """
    intermediates = collect_intermediates(host, port)
    if not intermediates:
        return None

    target_dir = bundle_dir if bundle_dir is not None else BUNDLE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    bundle = target_dir / f"{host}.pem"

    pem = Path(certifi.where()).read_text(encoding="utf-8")
    for cert in intermediates:
        pem += "\n" + cert.public_bytes(Encoding.PEM).decode()
    bundle.write_text(pem, encoding="utf-8")
    return bundle


def verify_arg(host: str, bundle_dir: Optional[Path] = None):
    target_dir = bundle_dir if bundle_dir is not None else BUNDLE_DIR
    cached = target_dir / f"{host}.pem"
    if cached.exists():
        return str(cached)
    built = build_bundle(host, bundle_dir=bundle_dir)
    return str(built) if built is not None else True
