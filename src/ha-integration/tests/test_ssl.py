"""The private-CA trust store the coordinator hands to aiohttp."""
import ssl

from homeassistant.core import HomeAssistant

from custom_components.kio.coordinator import _ssl_context, ca_cert_path

def _write_ca(tmp_path):
    """Throwaway self-signed CA, only used to prove the PEM gets loaded."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    import datetime

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-private-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now).not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path = tmp_path / "ca.crt"
    path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return path


def test_no_ca_configured_means_default_trust() -> None:
    assert _ssl_context("") is None


def test_missing_file_falls_back_to_system_trust(tmp_path, caplog) -> None:
    assert _ssl_context(str(tmp_path / "nope.crt")) is None
    assert "not found" in caplog.text


def test_pem_is_loaded_into_context(tmp_path) -> None:
    ctx = _ssl_context(str(_write_ca(tmp_path)))
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert any(c["subject"][0][0][1] == "test-private-ca" for c in ctx.get_ca_certs())


def test_relative_ca_path_is_under_config_dir(hass: HomeAssistant) -> None:
    assert ca_cert_path(hass, "certs/x.crt") == hass.config.path("certs/x.crt")
    assert ca_cert_path(hass, "/abs/x.crt") == "/abs/x.crt"
    assert ca_cert_path(hass, "  ") == ""
