import pytest
from pydantic import ValidationError

from app.config import BACKEND_DIR, Settings
from app.marketo.governor import RateGovernor
from app.marketo.mcp_client import MarketoMcpClient


def test_rest_url_is_built_from_munchkin_id():
    s = Settings(_env_file=None, marketo_munchkin_id=" 123-abc-456 ")
    assert s.marketo_munchkin_id == "123-ABC-456"
    assert s.marketo_rest_url == "https://123-ABC-456.mktorest.com"


def test_bad_munchkin_id_is_rejected():
    with pytest.raises(ValidationError, match="123-ABC-456"):
        Settings(_env_file=None, marketo_munchkin_id="https://123-ABC-456.mktorest.com")


def test_marketo_configured_needs_all_three_credentials():
    base = {"_env_file": None, "marketo_munchkin_id": "123-ABC-456", "marketo_client_id": "id"}
    assert not Settings(**base).marketo_configured
    assert Settings(**base, marketo_client_secret="secret").marketo_configured


def test_mcp_defaults_to_adobe_endpoint():
    assert Settings(_env_file=None).marketo_mcp_url == "https://marketo-mcp.adobe.io/mcp"


def test_env_example_parses_with_inline_comments(monkeypatch):
    for var in ("MARKETO_MUNCHKIN_ID", "MARKETO_MCP_URL", "MARKETO_MODE"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=BACKEND_DIR.parent / ".env.example")
    assert s.marketo_munchkin_id == ""  # "# e.g. 123-ABC-456" is a comment, not the value
    assert s.marketo_mode == "demo"


def test_mcp_sends_launchpoint_credentials_as_headers():
    client = MarketoMcpClient("https://marketo-mcp.adobe.io/mcp", "123-ABC-456", "cid", "csecret",
                              RateGovernor())
    conn = client._client.connections["marketo"]
    assert conn["url"] == "https://marketo-mcp.adobe.io/mcp"
    assert conn["headers"] == {
        "X-Marketo-Client-Id": "cid",
        "X-Marketo-Client-Secret": "csecret",
        "X-Marketo-Munchkin-Id": "123-ABC-456",
    }


def test_bad_environment_value_does_not_block_startup(monkeypatch, caplog):
    from app.config import load_tolerant

    monkeypatch.setenv("MARKETO_MUNCHKIN_ID", "3cbdaaa9-da9d-462b-8f76-910578999946")
    s = load_tolerant({})
    assert s.marketo_munchkin_id == ""
    assert "Ignoring invalid MARKETO_MUNCHKIN_ID" in caplog.text
    assert "3cbdaaa9" not in caplog.text  # values never logged


def test_database_url_normalisation():
    s = Settings(_env_file=None, database_url="postgres://u:p@h:5432/db")
    assert s.sqlalchemy_url == "postgresql+psycopg://u:p@h:5432/db"
    assert s.libpq_url == "postgresql://u:p@h:5432/db" and s.is_postgres
    assert Settings(_env_file=None).sqlalchemy_url.startswith("sqlite:///")


def test_password_hash_and_sessions(env):
    import base64
    import json

    from app import security

    h = security.hash_password("a strong passphrase")
    assert h.startswith("scrypt$") and "a strong passphrase" not in h
    assert security.verify_password("a strong passphrase", h)
    assert not security.verify_password("wrong", h)

    token = security.make_session(h)
    assert security.session_valid(token, h)
    assert not security.session_valid(token, security.hash_password("rotated password"))
    payload, sig = token.rsplit(".", 1)
    forged = base64.urlsafe_b64encode(json.dumps({"exp": 9e12, "fp": "x"}).encode()).decode()
    assert not security.session_valid(f"{forged}.{sig}", h)
    assert not security.session_valid(None, h)


def test_secret_key_file_is_private(env, tmp_path):
    import stat

    from app import security

    token = security.encrypt("hello")
    assert security.decrypt(token) == "hello" and "hello" not in token
    mode = stat.S_IMODE((tmp_path / "secret.key").stat().st_mode)
    assert mode == 0o600
