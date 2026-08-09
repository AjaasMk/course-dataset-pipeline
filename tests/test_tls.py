import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from src.retrieve.tls import build_bundle, ca_issuer_urls, der_to_pem, is_self_issued, verify_arg


def _self_signed() -> x509.Certificate:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-root")])
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )


def test_der_to_pem_round_trips():
    cert = _self_signed()
    der = cert.public_bytes(serialization.Encoding.DER)
    assert der_to_pem(der).startswith("-----BEGIN CERTIFICATE-----")


def test_self_issued_certificate_is_detected():
    assert is_self_issued(_self_signed())


def test_certificate_without_aia_extension_has_no_issuer_urls():
    assert ca_issuer_urls(_self_signed()) == []


def test_build_bundle_returns_none_when_no_intermediates_are_found(tmp_path):
    assert build_bundle("localhost.invalid", bundle_dir=tmp_path) is None


def test_verify_arg_falls_back_to_default_verification(tmp_path):
    assert verify_arg("localhost.invalid", bundle_dir=tmp_path) is True


def test_verify_arg_uses_a_cached_bundle_when_present(tmp_path):
    cached = tmp_path / "example.test.pem"
    cached.write_text("cert", encoding="utf-8")
    assert verify_arg("example.test", bundle_dir=tmp_path) == str(cached)
