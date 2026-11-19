"""Exercise tenant-scoped action-plan API reads across independent MySQL workers."""

from __future__ import annotations

from http.client import HTTPResponse
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

from autonomy.action_models import ActionPlan, ActionStatus, ActionTarget, RiskLevel
from autonomy.action_plan_store import ActionPlanStore


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


def test_mysql_tenant_scoped_plan_api_reads_are_isolated_across_workers(database_url):
    """Two separately booted API processes must read only their tenant's plans."""
    identity = f"mysql-api-worker-{uuid.uuid4().hex}"
    plan = ActionPlan(
        action_id=identity,
        action_type="review_instance_state",
        target=ActionTarget("ec2_instance", "i-api-worker-isolation"),
        reason="Read-only multi-worker tenant isolation integration test.",
        risk=RiskLevel.MEDIUM,
        status=ActionStatus.PENDING_APPROVAL,
    )

    tokens = {
        "tenant-a-reader": {"subject": "api-worker-a", "role": "reader", "tenant_id": "tenant-a"},
        "tenant-b-reader": {"subject": "api-worker-b", "role": "reader", "tenant_id": "tenant-b"},
    }
    environment = os.environ.copy()
    environment.update({
        "CLOUDOPS_DATABASE_URL": database_url,
        "CLOUDOPS_AUTH_MODE": "token",
        "CLOUDOPS_ENV": "staging",
        "CLOUDOPS_API_TOKENS": json.dumps(tokens),
    })

    store = ActionPlanStore(database_url=database_url)
    workers: list[subprocess.Popen] = []
    try:
        store.save_many([plan], "tenant-a")

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

        query = "/autonomy/plans?" + urlencode({"search": identity})
        status_a, body_a = _request_json(base_urls[0], query, "tenant-a-reader")
        status_b, body_b = _request_json(base_urls[1], query, "tenant-b-reader")
        detail_status_b, _detail_b = _request_json(
            base_urls[1], f"/autonomy/plans/{identity}", "tenant-b-reader"
        )

        assert status_a == 200
        assert body_a["total"] == 1
        assert [item["action_id"] for item in body_a["plans"]] == [identity]
        assert status_b == 200
        assert body_b["total"] == 0
        assert detail_status_b == 404

        # Re-read through the first worker after the foreign-tenant request.
        # Its tenant-scoped view must remain correct and must not depend on
        # whichever worker most recently accessed the shared database.
        status_a_again, body_a_again = _request_json(
            base_urls[0], query, "tenant-a-reader"
        )
        assert status_a_again == 200
        assert body_a_again["total"] == 1
        assert [item["action_id"] for item in body_a_again["plans"]] == [identity]
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
        store.close()
