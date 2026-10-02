"""Exercise Host and Origin checks through the actual MCP HTTP application."""

import importlib
import sys

import pytest
from starlette.testclient import TestClient

from abs_librarian.config import Config


@pytest.fixture()
def client(monkeypatch, request):
    monkeypatch.setenv("ABS_URL", "http://abs.local")
    monkeypatch.setenv("ABS_TOKEN", "test-token")
    monkeypatch.setenv("MCP_TOKEN", "")
    monkeypatch.setenv("PORT", "8000")
    monkeypatch.setenv(
        "MCP_ALLOWED_HOSTS",
        getattr(request, "param", "192.168.1.100:9000,librarian.lan:8000,[fd00::1]:8000"),
    )
    modules = ("abs_librarian.__main__", "abs_librarian.server")
    for name in modules:
        monkeypatch.delitem(sys.modules, name, raising=False)
    main = importlib.import_module("abs_librarian.__main__")
    with TestClient(main.app) as http:
        yield http
    for name in modules:
        sys.modules.pop(name, None)


def request(client, host, origin=None):
    headers = {"host": host, "accept": "application/json, text/event-stream"}
    if origin is not None:
        headers["origin"] = origin
    return client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )


@pytest.mark.parametrize("host", [
    "attacker.example:8000", "localhost.attacker.example:8000",
    "127.0.0.1.attacker.example:8000", "192.168.1.101:9000",
    "192.168.1.100:8000", "librarian.lan:9000", "localhost:9000", "",
])
def test_untrusted_host_rejected(client, host):
    response = request(client, host)
    assert response.status_code == 421
    assert response.text == "Invalid Host header"


@pytest.mark.parametrize("host", [
    "localhost", "localhost:8000", "127.0.0.1", "127.0.0.1:8000",
    "[::1]", "[::1]:8000", "192.168.1.100:9000", "librarian.lan:8000", "[fd00::1]:8000",
])
def test_trusted_host_accepted(client, host):
    response = request(client, host)
    assert response.status_code == 200
    assert '"tools"' in response.text


@pytest.mark.parametrize("host", ["localhost:8000", "192.168.1.100:9000"])
@pytest.mark.parametrize("origin", ["http://attacker.example:8000", "http://192.168.1.100:9000"])
def test_host_trust_does_not_bypass_origin_checks(client, host, origin):
    response = request(client, host, origin)
    assert response.status_code == 403
    assert response.text == "Invalid Origin header"


def test_sdk_localhost_origin_still_accepted(client):
    assert request(client, "localhost:8000", "http://localhost:8000").status_code == 200


def test_localhost_health_preserved(client):
    response = client.get("/health", headers={"host": "localhost:8000"})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.parametrize("client", [""], indirect=True)
def test_default_transport_rejects_lan_but_accepts_localhost(client):
    assert request(client, "192.168.1.100:8000").status_code == 421
    assert request(client, "localhost:8000").status_code == 200


def test_missing_host_rejected(client):
    message = client.build_request("GET", "/mcp")
    del message.headers["host"]
    assert client.send(message).status_code == 421


def test_get_transport_rejects_untrusted_host(client):
    assert client.get("/mcp", headers={"host": "attacker.example:8000"}).status_code == 421


async def test_wrapper_preserves_original_scope_and_headers(client, monkeypatch):
    main = sys.modules["abs_librarian.__main__"]
    scope = {
        "type": "http",
        "path": "/mcp",
        "headers": [(b"host", b"attacker.example:8000"), (b"origin", b"http://attacker.example")],
    }
    forwarded = []

    async def capture(incoming, receive, send):
        forwarded.append(incoming)

    with monkeypatch.context() as patch:
        patch.setattr(main, "_mcp_app", capture)
        await main.app(scope, None, None)
    assert forwarded[0] is scope


@pytest.fixture()
def config_env(monkeypatch):
    monkeypatch.setenv("ABS_URL", "http://abs.local")
    monkeypatch.setenv("ABS_TOKEN", "test-token")
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.delenv("MCP_ALLOWED_HOSTS", raising=False)


def test_default_hosts_are_only_loopback(config_env):
    cfg = Config.from_env()
    assert cfg.mcp_allowed_hosts == []
    assert set(cfg.trusted_hosts) == {
        "localhost", "127.0.0.1", "[::1]", "localhost:8123", "127.0.0.1:8123", "[::1]:8123",
    }


def test_explicit_hosts_are_trimmed_and_deduplicated(config_env, monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", " librarian.lan:9000,192.168.1.100,librarian.lan:9000 ")
    assert Config.from_env().mcp_allowed_hosts == ["librarian.lan:9000", "192.168.1.100"]


@pytest.mark.parametrize("value", [
    "*", "*:8000", "*.lan:8000", "librarian.lan:*", "http://librarian.lan:8000",
    "librarian.lan/path", "user@librarian.lan", "librarian.lan:0", "librarian.lan:65536",
    "librarian.lan,", "[:::]:8000", "librarian.lan:8000:9000", "librarian .lan",
])
def test_invalid_host_configuration_fails_closed(config_env, monkeypatch, value):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", value)
    with pytest.raises(ValueError):
        Config.from_env()
