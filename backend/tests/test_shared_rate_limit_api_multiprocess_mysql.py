"""Verify MySQL-backed request limits are shared across independent API workers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

import pytest
from alembic import command
from alembic.config import Config


MYSQL_URL = os.environ.get("CLOUDOPS_MYSQL_TEST_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="MySQL CI service is not configured")


@pytest.fixture(scope="module")
def database_url():
    assert MYSQL_URL
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", MYSQL_URL.replace("%", "%%"))
    command.upgrade(config, "head")
    yield MYSQL_URL


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(base_url: str, token: str, path: str = "/operations/failures") -> tuple[int, dict]:
    request = Request(
        f"{base_url}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _wait_for_worker(process: subprocess.Popen, base_url: str) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            detail = stderr.strip() or "<worker produced no stderr output>"
            raise RuntimeError(
                f"API worker exited during startup with code {process.returncode}:\\n{detail}"
            )
        try:
            status, _body = _request(base_url, "unused", path="/health")
            if status == 200:
                return
        except (OSError, URLError, TimeoutError, ValueError):
            pass
        time.sleep(0.2)
    raise TimeoutError("API worker did not become healthy within 30 seconds")


def test_mysql_rate_limit_budget_is_shared_across_api_workers(database_url):
    """Requests through separate Uvicorn processes consume one tenant-principal budget."""
    subject = f"mysql-rate-limit-{uuid.uuid4().hex}"
    token = "rate-limit-admin"
    tokens = {
        token: {"subject": subject, "role": "admin", "tenant_id": "rate-limit-tenant"},
    }
    environment = os.environ.copy()
    environment.update({
        "CLOUDOPS_DATABASE_URL": database_url,
        "CLOUDOPS_AUTH_MODE": "token",
        "CLOUDOPS_ENV": "staging",
        "CLOUDOPS_API_TOKENS": json.dumps(tokens),
        "CLOUDOPS_RATE_LIMIT_REQUESTS": "2",
        "CLOUDOPS_RATE_LIMIT_WINDOW_SECONDS": "60",
    })

    backend_dir = Path(__file__).resolve().parents[1]
    ports = [_free_port(), _free_port()]
    base_urls = [f"http://127.0.0.1:{port}" for port in ports]
    workers: list[subprocess.Popen] = []
    try:
        for port in ports:
            workers.append(subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn", "main:app",
                    "--host", "127.0.0.1", "--port", str(port),
                    "--log-level", "warning",
                ],
                cwd=backend_dir,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            ))

        for worker, base_url in zip(workers, base_urls):
            _wait_for_worker(worker, base_url)

        first_status, _ = _request(base_urls[0], token)
        second_status, _ = _request(base_urls[1], token)
        limited_status, limited_body = _request(base_urls[0], token)

        assert first_status == 200
        assert second_status == 200
        assert limited_status == 429
        assert limited_body == {"detail": "Request rate limit exceeded"}
    finally:
        for worker in workers:
            if worker.poll() is None:
                worker.terminate()
        for worker in workers:
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait(timeout=5)
