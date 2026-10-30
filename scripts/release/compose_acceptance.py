#!/usr/bin/env python3
"""TC-03-002 runtime acceptance, restricted to disposable GitHub-hosted runners.

No dependencies beyond Python and Docker Compose. Never reads an operator's env
file or repairs ownership. A failed image pull/startup is an acceptance failure.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import signal
import ssl
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "artifacts/acceptance/TC-03-002/runtime-ci"
USERS = {
    "caddy": "10001:10001",
    "web": "1000:1000",
    "api": "10001:10001",
    "worker": "10001:10001",
    "postgres": "999:999",
    "minio": "1000:1000",
}
PROJECT = re.compile(r"tc03002-[0-9]+-[0-9]+-[a-f0-9]{12}-(dev|prod)\Z")


def sanitize(text: str, secret_values: list[str]) -> str:
    for value in sorted(secret_values, key=len, reverse=True):
        if value:
            text = text.replace(value, "[REDACTED]")
    return re.sub(r"(https?|postgresql)://[^\s/@]+:[^\s/@]+@", r"\1://[REDACTED]@", text)


def isolate(model: dict, project: str, mode: str, caddyfile: Path) -> dict:
    """Change only resource identity, published proxy port and test TLS hostname."""
    if not PROJECT.fullmatch(project):
        raise ValueError("invalid acceptance project identity")
    if mode == "dev":
        model["services"] = {"web": model["services"]["web"]}
        model["volumes"] = {"web_node_modules": model["volumes"]["web_node_modules"]}
        model["networks"] = {"trustnet": model["networks"]["trustnet"]}
    model["name"] = project
    for kind in ("volumes", "networks"):
        for name, resource in model[kind].items():
            if resource.get("external") or resource.get("driver_opts"):
                raise ValueError(f"refusing external/custom {kind}: {name}")
            # Compose config derives names from this unique project. Refuse a
            # future explicit shared name instead of silently touching it.
            if resource.get("name") != f"{project}_{name}":
                raise ValueError(f"refusing shared {kind}: {name}")
    for name, service in model["services"].items():
        if service.get("user") != USERS[name] or service.get("read_only") is not True:
            raise ValueError(f"missing committed hardening: {name}")
        if service.get("cap_drop") != ["ALL"]:
            raise ValueError(f"missing capability drop: {name}")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            raise ValueError(f"missing no-new-privileges: {name}")
        service["container_name"] = f"{project}-{name}"
        if name == "caddy":
            service["ports"] = [{"target": 443, "published": "0", "host_ip": "127.0.0.1"}]
            for mount in service["volumes"]:
                if mount["target"] == "/etc/caddy/Caddyfile":
                    mount["source"] = str(caddyfile)
        elif mode == "prod" and service.get("ports"):
            raise ValueError(f"unexpected published production service: {name}")
    return model


def owned(resource: dict, project: str) -> bool:
    """Docker inspect label check before deletion, never a prefix-only match."""
    labels = resource.get("Labels") or resource.get("Config", {}).get("Labels") or {}
    return bool(PROJECT.fullmatch(project)) and labels.get("com.docker.compose.project") == project


class Acceptance:
    def __init__(self, temp: Path):
        run = os.environ["GITHUB_RUN_ID"]
        attempt = os.environ["GITHUB_RUN_ATTEMPT"]
        self.prefix = f"tc03002-{run}-{attempt}-{secrets.token_hex(6)}"
        self.temp = temp
        self.deadline = time.monotonic() + 1800
        self.projects: dict[str, tuple[Path, dict]] = {}
        self.secret_values: list[str] = []
        self.report: dict = {
            "commit": os.environ.get("GITHUB_SHA"),
            "checks": dict.fromkeys(
                (
                    "dev_fresh_dependencies",
                    "dev_populated_dependencies_restart",
                    "production_startup_and_write",
                    "full_stack_restart_persistence",
                    "full_stack_recreation_persistence",
                ),
                "pending",
            ),
            "cleanup": {},
        }

    def run(self, args: list[str], timeout: int = 60) -> str:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("acceptance deadline exceeded")
        try:
            result = subprocess.run(
                args,
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=min(timeout, remaining),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"command timed out after {timeout}s: {args[:3]}") from exc
        if result.returncode:
            output = sanitize(result.stdout + result.stderr, self.secret_values)
            raise RuntimeError(
                f"command failed ({result.returncode}): {args[:3]}\n{output[-6000:]}"
            )
        return result.stdout

    def compose(self, mode: str, *args: str, timeout: int = 60) -> str:
        path, _ = self.projects[mode]
        return self.run(
            ["docker", "compose", "-p", f"{self.prefix}-{mode}", "-f", str(path), *args], timeout
        )

    def prepare(self, mode: str) -> None:
        project = f"{self.prefix}-{mode}"
        password, storage_key, session, model_key = [secrets.token_hex(32) for _ in range(4)]
        self.secret_values += [password, storage_key, session, model_key]
        env = {
            "APP_ENV": "production" if mode == "prod" else "development",
            "POSTGRES_USER": "tc_acceptance",
            "POSTGRES_PASSWORD": password,
            "DATABASE_URL": f"postgresql://tc_acceptance:{password}@postgres:5432/trustcopilot",
            "MINIO_ROOT_USER": "tc_acceptance",
            "MINIO_ROOT_PASSWORD": storage_key,
            "S3_ACCESS_KEY": "tc_acceptance",
            "S3_SECRET_KEY": storage_key,
            "S3_ENDPOINT": "http://minio:9000",
            "SESSION_SECRET": session,
            # Synthetic non-provider value: no model jobs/calls are exercised.
            "OPENAI_API_KEY": model_key,
            "EMAIL_DELIVERY_ENABLED": "false",
            "APP_BASE_URL": "https://trustcopilot.app",
            "FRONTEND_URL": "https://trustcopilot.app",
            "NEXT_TELEMETRY_DISABLED": "1",
        }
        env_path = self.temp / f"{mode}.env"
        env_path.write_text("".join(f"{key}={value}\n" for key, value in env.items()))
        env_path.chmod(0o600)
        source = ROOT / ("docker-compose.prod.yml" if mode == "prod" else "docker-compose.yml")
        # Compose resolves env_file before emitting JSON; redirect its single
        # known env_file reference without creating/overwriting a checkout file.
        text = source.read_text().replace(
            "      - .env.production\n" if mode == "prod" else "      - .env\n",
            f"      - {env_path}\n",
        )
        staged = self.temp / f"{mode}.source.yml"
        staged.write_text(text)
        model = json.loads(
            self.run(
                [
                    "docker",
                    "compose",
                    "--project-directory",
                    str(ROOT),
                    "--env-file",
                    str(env_path),
                    "-p",
                    project,
                    "-f",
                    str(staged),
                    "config",
                    "--format",
                    "json",
                ]
            )
        )
        caddy = self.temp / "Caddyfile"
        production = (ROOT / "infra/caddy/Caddyfile.production").read_text()
        first_line = "trustcopilot.app, www.trustcopilot.app {\n"
        if not production.startswith(first_line):
            raise RuntimeError("production Caddy hostname changed; review isolated TLS fixture")
        caddy.write_text(
            production.replace(first_line, "https://localhost {\n    tls internal\n", 1)
        )
        model = isolate(model, project, mode, caddy)
        path = self.temp / f"{mode}.json"
        path.write_text(json.dumps(model))
        path.chmod(0o600)
        self.projects[mode] = (path, model)

    def inspect(self, mode: str, service: str) -> dict:
        return json.loads(self.run(["docker", "inspect", f"{self.prefix}-{mode}-{service}"]))[0]

    def healthy(self, mode: str) -> None:
        expires = time.monotonic() + 240
        services = self.projects[mode][1]["services"]
        while time.monotonic() < expires:
            pending = []
            for service in services:
                state = self.inspect(mode, service)["State"]
                if state["Status"] in {"exited", "dead"}:
                    raise RuntimeError(f"{mode}/{service} exited during startup")
                if (
                    not state["Running"]
                    or state.get("Health", {}).get("Status", "healthy") != "healthy"
                ):
                    pending.append(service)
            if not pending:
                self.security(mode)
                if mode == "prod":
                    # /healthz intentionally excludes DB/S3; require the actual
                    # dependency probe before writing persistence fixtures.
                    self.compose(
                        mode,
                        "exec",
                        "-T",
                        "api",
                        "python",
                        "-c",
                        "import urllib.request; "
                        "urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=15)",
                    )
                return
            time.sleep(3)
        raise RuntimeError(f"{mode} readiness timed out: {', '.join(pending)}")

    def security(self, mode: str) -> None:
        runtime = self.report.setdefault("runtime", {}).setdefault(mode, {})
        for service in self.projects[mode][1]["services"]:
            container = self.inspect(mode, service)
            host = container["HostConfig"]
            assert container["Config"]["User"] == USERS[service], service
            assert host["ReadonlyRootfs"] and host["CapDrop"] == ["ALL"], service
            assert "no-new-privileges:true" in host["SecurityOpt"], service
            assert set(host.get("CapAdd") or []) == (
                {"NET_BIND_SERVICE"} if service == "caddy" else set()
            ), service
            assert "/tmp" in host["Tmpfs"], service
            if service in {"postgres", "minio"}:
                assert not host["PortBindings"], service
                assert set(container["NetworkSettings"]["Networks"]) == {
                    f"{self.prefix}-{mode}_datanet"
                }, service
            for mount in container["Mounts"]:
                if mount["Type"] == "volume":
                    assert mount["Name"].startswith(f"{self.prefix}-{mode}_"), service
            runtime[service] = {
                "image_id": container["Image"],
                "user": container["Config"]["User"],
                "read_only": host["ReadonlyRootfs"],
                "cap_drop": host["CapDrop"],
                "cap_add": host.get("CapAdd") or [],
                "security_opt": host["SecurityOpt"],
                "volumes": {
                    mount["Destination"]: mount["Name"]
                    for mount in container["Mounts"]
                    if mount["Type"] == "volume"
                },
            }
        if mode == "prod":
            network = json.loads(
                self.run(["docker", "network", "inspect", f"{self.prefix}-prod_datanet"])
            )[0]
            assert network["Internal"], "database/storage network is not internal"

    def dev(self) -> None:
        self.prepare("dev")
        self.compose("dev", "build", "web", timeout=600)
        self.compose("dev", "up", "-d", "--no-build", "web", timeout=60)
        self.healthy("dev")
        self.compose(
            "dev",
            "exec",
            "-T",
            "web",
            "sh",
            "-ec",
            'test "$(id -u)" = 1000; test -w /app/node_modules; '
            "test -w /tmp/npm-cache; test -d /app/node_modules/next",
        )
        self.report["checks"]["dev_fresh_dependencies"] = "passed"
        self.compose("dev", "restart", "web", timeout=60)
        self.healthy("dev")
        self.compose(
            "dev",
            "exec",
            "-T",
            "web",
            "sh",
            "-ec",
            "test -d /app/node_modules/next; test -w /app/node_modules; test -w /tmp/npm-cache",
        )
        self.report["checks"]["dev_populated_dependencies_restart"] = "passed"

    def state(self, write: bool = False) -> None:
        # Use the real app image's installed DB/S3 clients and configured network.
        program = """
import os
import psycopg2
from app.services.storage import StorageClient
value = "tc03002-synthetic-persistence"
with psycopg2.connect(os.environ["DATABASE_URL"]) as connection:
    with connection.cursor() as cursor:
        if WRITE:
            cursor.execute("CREATE TABLE compose_acceptance (value text NOT NULL)")
            cursor.execute("INSERT INTO compose_acceptance VALUES (%s)", (value,))
        cursor.execute("SELECT value FROM compose_acceptance")
        assert cursor.fetchall() == [(value,)]
storage = StorageClient()
if WRITE:
    storage.ensure_buckets()
    storage.upload(storage.bucket_raw, "compose-acceptance", value.encode())
assert storage.download(storage.bucket_raw, "compose-acceptance") == value.encode()
""".replace("WRITE", repr(write))
        self.compose("prod", "exec", "-T", "api", "python", "-c", program)

    def tls_state(self) -> dict[str, str]:
        root = self.compose(
            "prod", "exec", "-T", "caddy", "cat", "/data/caddy/pki/authorities/local/root.crt"
        )
        config = self.compose("prod", "exec", "-T", "caddy", "cat", "/config/caddy/autosave.json")
        port = self.compose("prod", "port", "caddy", "443").strip()
        if not re.fullmatch(r"127\.0\.0\.1:[0-9]+", port):
            raise RuntimeError("proxy port is not isolated on loopback")
        context = ssl.create_default_context(cadata=root)
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context)
        )
        with opener.open(f"https://localhost:{port.split(':')[1]}/readyz", timeout=15) as response:
            assert response.status == 200
        return {
            "ca": hashlib.sha256(root.encode()).hexdigest(),
            "config": hashlib.sha256(config.encode()).hexdigest(),
        }

    def prod(self) -> None:
        self.prepare("prod")
        # Pull exact committed image references. A registry denial is a failure;
        # no login, image substitution or use of an operator's cached data.
        self.compose("prod", "pull", "postgres", "minio", timeout=300)
        self.compose("prod", "build", timeout=900)
        self.compose("prod", "up", "-d", "--no-build", timeout=240)
        self.healthy("prod")
        self.state(write=True)
        original = self.tls_state()
        self.report["checks"]["production_startup_and_write"] = "passed"
        self.report["caddy_state_sha256"] = original
        self.compose("prod", "restart", timeout=120)
        self.healthy("prod")
        self.state()
        assert self.tls_state() == original, "Caddy state changed after restart"
        self.report["checks"]["full_stack_restart_persistence"] = "passed"
        self.compose("prod", "up", "-d", "--force-recreate", "--no-build", timeout=240)
        self.healthy("prod")
        self.state()
        assert self.tls_state() == original, "Caddy state changed after recreation"
        self.report["checks"]["full_stack_recreation_persistence"] = "passed"

    def cleanup(self, mode: str) -> None:
        project = f"{self.prefix}-{mode}"
        # Resolve by exact project label, inspect ownership again, then remove
        # individual IDs/names. Never prune, down -v or remove shared resources.
        for kind, listing in (("container", "ps"), ("network", "network"), ("volume", "volume")):
            args = ["docker", listing] + (["-aq"] if kind == "container" else ["ls", "-q"])
            ids = self.run(
                args + ["--filter", f"label=com.docker.compose.project={project}"]
            ).split()
            for resource_id in ids:
                resource = json.loads(self.run(["docker", kind, "inspect", resource_id]))[0]
                if not owned(resource, project):
                    raise RuntimeError(f"refusing cleanup of unowned {kind}")
                self.run(
                    ["docker", kind, "rm", *(["-f"] if kind == "container" else []), resource_id]
                )
        self.report["cleanup"][mode] = "passed"

    def execute(self) -> int:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        self.report["scope"] = (
            "Isolated localhost/internal TLS; public ACME and real providers unqualified"
        )
        self.report["status"] = "running"
        self.report["checkout_web_uid"] = (ROOT / "apps/web").stat().st_uid
        (EVIDENCE / "result.json").write_text(json.dumps(self.report, indent=2) + "\n")
        failed = False
        for mode, exercise in (("dev", self.dev), ("prod", self.prod)):
            interrupted = False
            print(f"TC-03-002: exercising {mode}", flush=True)
            try:
                exercise()
            except (Exception, KeyboardInterrupt) as exc:
                failed = True
                interrupted = isinstance(exc, KeyboardInterrupt)
                self.report["checks"][mode] = {"failed": sanitize(str(exc), self.secret_values)}
                print(f"TC-03-002: {mode} FAILED (see sanitized evidence)", flush=True)
                if mode in self.projects:
                    try:
                        logs = self.compose(mode, "logs", "--no-color", "--tail", "80")
                        (EVIDENCE / f"{mode}.log").write_text(sanitize(logs, self.secret_values))
                    except Exception:
                        pass  # Original failure remains authoritative.
            finally:
                if mode in self.projects:
                    # Cleanup has its own short allowance even after the test deadline.
                    prior = self.deadline
                    self.deadline = time.monotonic() + 120
                    try:
                        self.cleanup(mode)
                    except Exception as exc:
                        failed = True
                        self.report["cleanup"][mode] = {
                            "failed": sanitize(str(exc), self.secret_values)
                        }
                    self.deadline = prior
                self.report["status"] = "failed" if failed else "running"
                (EVIDENCE / "result.json").write_text(json.dumps(self.report, indent=2) + "\n")
            if interrupted:
                break
        failed = failed or any(value != "passed" for value in self.report["checks"].values())
        self.report["status"] = "failed" if failed else "passed"
        (EVIDENCE / "result.json").write_text(json.dumps(self.report, indent=2) + "\n")
        return int(failed)


def main() -> int:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
    ):
        raise SystemExit("Only disposable GitHub-hosted runners may execute this acceptance test")
    for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"):
        if not os.environ.get(name, "").isdigit():
            raise SystemExit(f"Missing numeric {name}")

    def interrupted(signum, _frame):
        raise KeyboardInterrupt(f"acceptance interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    with tempfile.TemporaryDirectory(prefix="tc03002-") as temp:
        return Acceptance(Path(temp)).execute()


if __name__ == "__main__":
    raise SystemExit(main())
