"""Exercise tenant-scoped GitOps API reads across independent MySQL workers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import uuid

import pytest
from alembic import command
from alembic.config import Config

from autonomy.gitops import GitOpsChange, GitOpsEngine
from autonomy.gitops_registry import GitOpsChangeSetRegistry


MYSQL_URL = os.environ.get("CLOUDOPS_MYSQL_TEST_URL")
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="MySQL CI service is not configured")


@pytest.fixture(scope="module")
def database_url():
    assert MYSQL_URL
    os.environ["CLOUDOPS_DATABASE_URL"] = MYSQL_URL
    config = Config("backend/alembic.ini")
    config.set_section_option("alembic", "sqlalchemy.url", MYSQL_URL.replace("%", "%%"))
    command.upgrade(config, "head")
    yield MYSQL_URL


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request_json(base_url: str, path: str, token: str) -> tuple[int, dict]:
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
            raise RuntimeError(f"API worker exited during startup with code {process.returncode}")
        try:
            status, _body = _request_json(base_url, "/health", "unused")
            if status == 200:
                return
        except (OSError, URLError, TimeoutError, ValueError):
            pass
        time.sleep(0.2)
    raise TimeoutError("API worker did not become healthy within 30 seconds")


def _change_set(change_id: str, tenant_id: str):
    change_set = GitOpsEngine().create_change_set(
        source_action_id=f"action-{change_id}",
        changes=[
            GitOpsChange(
                resource_type="ec2",
                resource_id=f"i-{change_id}",
                field="instance_type",
                desired_value="t3.large",
                current_value="t3.medium",
                reason="Read-only multi-worker tenant isolation integration test.",
            )
        ],
    )
    change_set.change_id = change_id
    change_set.metadata["tenant_id"] = tenant_id
    return change_set


def test_mysql_tenant_scoped_gitops_api_reads_are_isolated_across_workers(database_url):
    """Two separately booted API processes must expose only their tenant's GitOps changes."""
    identity = f"mysql-gitops-api-worker-{uuid.uuid4().hex}"
    change_a = f"{identity}-tenant-a"
    change_b = f"{identity}-tenant-b"

    tokens = {
        "tenant-a-reader": {"subject": "gitops-api-worker-a", "role": "reader", "tenant_id": "tenant-a"},
        "tenant-b-reader": {"subject": "gitops-api-worker-b", "role": "reader", "tenant_id": "tenant-b"},
    }
    environment = os.environ.copy()
    environment.update({
        "CLOUDOPS_DATABASE_URL": database_url,
        "CLOUDOPS_AUTH_MODE": "token",
        "CLOUDOPS_ENV": "staging",
        "CLOUDOPS_API_TOKENS": json.dumps(tokens),
    })

    registry = GitOpsChangeSetRegistry(database_url=database_url)
    workers: list[subprocess.Popen] = []
    try:
        registry.register(_change_set(change_a, "tenant-a"))
        registry.register(_change_set(change_b, "tenant-b"))

        backend_dir = Path(__file__).resolve().parents[1]
        ports = [_free_port(), _free_port()]
        base_urls = [f"http://127.0.0.1:{port}" for port in ports]
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
                stderr=subprocess.DEVNULL,
            ))

        for worker, base_url in zip(workers, base_urls):
            _wait_for_worker(worker, base_url)

        query = "/autonomy/gitops/changes?" + urlencode({"search": identity})
        status_a, body_a = _request_json(base_urls[0], query, "tenant-a-reader")
        status_b, body_b = _request_json(base_urls[1], query, "tenant-b-reader")
        pending_a, pending_body_a = _request_json(
            base_urls[0], "/autonomy/gitops/changes/pending", "tenant-a-reader"
        )
        pending_b, pending_body_b = _request_json(
            base_urls[1], "/autonomy/gitops/changes/pending", "tenant-b-reader"
        )
        detail_a, _ = _request_json(
            base_urls[0], f"/autonomy/gitops/changes/{change_b}", "tenant-a-reader"
        )
        detail_b, _ = _request_json(
            base_urls[1], f"/autonomy/gitops/changes/{change_a}", "tenant-b-reader"
        )

        assert status_a == 200
        assert body_a["total"] == 1
        assert [item["change_id"] for item in body_a["changes"]] == [change_a]
        assert status_b == 200
        assert body_b["total"] == 1
        assert [item["change_id"] for item in body_b["changes"]] == [change_b]
        assert pending_a == 200
        assert [item["change_id"] for item in pending_body_a] == [change_a]
        assert pending_b == 200
        assert [item["change_id"] for item in pending_body_b] == [change_b]
        assert detail_a == 404
        assert detail_b == 404

        # A second request through the first process confirms that the other
        # worker's tenant-scoped read did not contaminate its visible snapshot.
        status_a_again, body_a_again = _request_json(
            base_urls[0], query, "tenant-a-reader"
        )
        assert status_a_again == 200
        assert body_a_again["total"] == 1
        assert [item["change_id"] for item in body_a_again["changes"]] == [change_a]

        # A fresh API process must recover the same durable GitOps state from MySQL.
        workers[0].terminate()
        workers[0].wait(timeout=5)
        workers[0] = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "main:app",
                "--host", "127.0.0.1", "--port", str(ports[0]),
                "--log-level": "warning",
            ],
            cwd=backend_dir,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _wait_for_worker(workers[0], base_urls[0])
        status_after_restart, body_after_restart = _request_json(
            base_urls[0], query, "tenant-a-reader"
        )
        assert status_after_restart == 200
        assert body_after_restart["total"] == 1
        assert [item["change_id"] for item in body_after_restart["changes"]] == [change_a]
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
        registry.close()
