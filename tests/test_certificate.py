"""Certificate reading against a real local TLS server with a self-signed certificate."""

import shutil
import ssl
import subprocess
import threading
from datetime import UTC, datetime

import pytest

from egisops.server import read_certificate

pytestmark = pytest.mark.skipif(
    not shutil.which("openssl"), reason="openssl CLI needed to make a test certificate"
)


@pytest.fixture
def tls_server(tmp_path):
    key, crt = tmp_path / "k.pem", tmp_path / "c.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(crt),
            "-days",
            "45",
            "-subj",
            "/CN=localhost",
        ],
        check=True,
        capture_output=True,
    )
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    import socket

    srv = socket.create_server(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    stop = threading.Event()

    def serve():
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            try:
                with ctx.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(1)
            except (ssl.SSLError, OSError):
                pass

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield port
    stop.set()
    t.join(timeout=2)
    srv.close()


def test_self_signed_certificate_is_read_and_untrusted(tls_server):
    c = read_certificate(f"https://localhost:{tls_server}/arcgis")
    assert c is not None and not c.trusted
    assert "CN=localhost" in c.subject and c.subject == c.issuer
    days = (c.not_after - datetime.now(UTC)).days
    assert 43 <= days <= 45


def test_plain_http_has_no_certificate():
    assert read_certificate("http://localhost/arcgis") is None
