"""TC-03-002: Compose services keep data and run with least privilege.

Static checks over the compose files, Dockerfiles, the API entrypoint and the
production Caddyfile. No credentials are read or printed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[4]
SERVICES = ("caddy", "web", "api", "worker", "postgres", "minio")
DATA_VOLUMES = ("postgres_data", "minio_data", "caddy_data", "caddy_config")
# Official images need one capability the rest of the stack does not.
# Caddy binds 80/443. Nothing else may add capabilities.
ALLOWED_CAPS = {"caddy": {"NET_BIND_SERVICE"}}
NON_ROOT = {
    "caddy": "10001:10001",
    "web": "1000:1000",
    "api": "10001:10001",
    "worker": "10001:10001",
    "postgres": "999:999",
    "minio": "1000:1000",
}


def _compose(name: str) -> dict:
    return yaml.safe_load((REPO_ROOT / name).read_text())


def _ports(service: dict) -> list[str]:
    return [str(item) for item in (service.get("ports") or [])]


def _volume_names(service: dict) -> list[str]:
    names = []
    for item in service.get("volumes") or []:
        text = item if isinstance(item, str) else ""
        if text and not text.startswith(".") and not text.startswith("/"):
            names.append(text.split(":", 1)[0])
    return names


@pytest.mark.parametrize("filename", ["docker-compose.yml", "docker-compose.prod.yml"])
def test_each_service_is_least_privilege_with_named_volumes(filename: str) -> None:
    doc = _compose(filename)
    assert set(DATA_VOLUMES).issubset(doc["volumes"])
    for name in SERVICES:
        service = doc["services"][name]
        assert "ALL" in service["cap_drop"]
        assert "no-new-privileges:true" in service["security_opt"]
        assert service["read_only"] is True
        assert str(service["user"]) == NON_ROOT[name]
        extra = set(service.get("cap_add") or [])
        assert extra <= ALLOWED_CAPS.get(name, set())
        if filename.endswith("prod.yml") and name == "caddy":
            assert extra == {"NET_BIND_SERVICE"}
    assert "postgres_data" in _volume_names(doc["services"]["postgres"])
    assert "minio_data" in _volume_names(doc["services"]["minio"])
    assert "caddy_data" in _volume_names(doc["services"]["caddy"])
    assert "caddy_config" in _volume_names(doc["services"]["caddy"])
    assert doc["networks"]["datanet"]["internal"] is True
    if filename == "docker-compose.yml":
        assert "web_node_modules" in doc["volumes"]
        assert "web_node_modules" in _volume_names(doc["services"]["web"])


def test_prod_database_and_storage_are_not_published() -> None:
    doc = _compose("docker-compose.prod.yml")
    for name in ("postgres", "minio"):
        service = doc["services"][name]
        assert not service.get("ports"), name
        assert service["networks"] == ["datanet"]
    for name in ("api", "worker"):
        assert "datanet" in doc["services"][name]["networks"]
        assert "trustnet" in doc["services"][name]["networks"]


def test_dev_database_and_storage_bind_localhost_only() -> None:
    doc = _compose("docker-compose.yml")
    published = _ports(doc["services"]["postgres"]) + _ports(doc["services"]["minio"])
    assert published
    for item in published:
        assert item.startswith("127.0.0.1:"), item
        assert "0.0.0.0" not in item


def test_entrypoint_only_applies_additive_migrations() -> None:
    text = (REPO_ROOT / "apps/api/docker-entrypoint.sh").read_text()
    assert "alembic upgrade head" in text
    lowered = text.lower()
    for forbidden in ("alembic downgrade", "drop database", "dropdb", "rm -rf", "initdb"):
        assert forbidden not in lowered


def test_images_do_not_bake_secrets() -> None:
    for relative in ("apps/api/Dockerfile", "apps/web/Dockerfile", "infra/caddy/Dockerfile"):
        text = (REPO_ROOT / relative).read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("COPY ") and ".env" in stripped:
                raise AssertionError(stripped)
            if not stripped.startswith("ENV "):
                continue
            if any(marker in stripped for marker in ("PASSWORD", "SECRET", "ACCESS_KEY")):
                assert '=""' in stripped
    api = (REPO_ROOT / "apps/api/Dockerfile").read_text()
    web = (REPO_ROOT / "apps/web/Dockerfile").read_text()
    assert "useradd" in api
    assert "USER app" in api
    assert "USER node" in web
    assert "USER caddy" in (REPO_ROOT / "infra/caddy/Dockerfile").read_text()


def test_production_caddyfile_serves_tls_and_not_data_ports() -> None:
    text = (REPO_ROOT / "infra/caddy/Caddyfile.production").read_text()
    assert "trustcopilot.app" in text
    assert "reverse_proxy api:8000" in text
    assert "reverse_proxy web:3000" in text
    for forbidden in (":5432", ":9000", ":9001"):
        assert forbidden not in text
