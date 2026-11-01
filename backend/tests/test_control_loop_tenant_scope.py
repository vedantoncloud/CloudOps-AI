from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from autonomy import control_loop_api
from autonomy.audit import AuditTrail


def _app() -> TestClient:
    app = FastAPI()
    app.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"tenant-token": Principal("operator-a", "operator", "tenant-a")},
    )
    app.include_router(control_loop_api.router)
    return TestClient(app)


def _pipeline_with_tags(tags):
    governance = type(
        "Governance",
        (),
        {
            "allowed": False,
            "blocked": False,
            "requires_human_review": True,
            "decision": type("Decision", (), {"value": "review"})(),
            "evidence": {"governance_gate": "review"},
            "resource": type(
                "Resource", (), {"policy": type("Policy", (), {"reasons": ["review"]})()}
            )(),
        },
    )()
    context = type(
        "Context",
        (),
        {
            "provider": "aws",
            "resource_id": "i-12345678",
            "resource_type": "ec2",
            "observation": {
                "provider": "aws",
                "resource_id": "i-12345678",
                "resource_type": "ec2",
                "tags": tags,
            },
        },
    )()
    return type(
        "Pipeline",
        (),
        {
            "build": lambda self, **kwargs: type(
                "Result",
                (),
                {
                    "allowed_for_decision": False,
                    "blocked": False,
                    "requires_human_review": True,
                    "governance": governance,
                    "resource_context": context,
                    "evidence": {"pipeline_outcome": "review"},
                },
            )(),
        },
    )()


def _payload():
    return {
        "action_id": "tenant-scope-action",
        "action_type": "inspect",
        "resource_type": "ec2",
        "resource_id": "i-12345678",
        "reason": "Check capacity",
        "risk": "low",
        "field": "state",
        "desired_value": "running",
    }


def test_control_loop_allows_tenant_owned_resource(monkeypatch):
    monkeypatch.setattr(
        control_loop_api,
        "provider_registry",
        type("Registry", (), {"get": lambda self, name: type("Provider", (), {"provider_name": "aws"})()})(),
    )
    monkeypatch.setattr(
        control_loop_api,
        "resource_context_pipeline",
        _pipeline_with_tags({"CloudOpsTenantId": "tenant-a"}),
    )
    trail = AuditTrail()
    monkeypatch.setattr(control_loop_api, "audit_trail", trail)

    response = _app().post(
        "/autonomy/control-loop/evaluate",
        json=_payload(),
        headers={"Authorization": "Bearer tenant-token"},
    )

    assert response.status_code == 200
    assert response.json()["recommendation"] == "review"
    events = trail.get_events("tenant-scope-action")
    assert events
    assert all(event.actor_id == "operator-a" for event in events)
    assert all(event.details.get("tenant_id") == "tenant-a" for event in events)


def test_control_loop_hides_foreign_and_unowned_resources(monkeypatch):
    monkeypatch.setattr(
        control_loop_api,
        "provider_registry",
        type("Registry", (), {"get": lambda self, name: type("Provider", (), {"provider_name": "aws"})()})(),
    )
    trail = AuditTrail()
    monkeypatch.setattr(control_loop_api, "audit_trail", trail)

    for tags in ({"CloudOpsTenantId": "tenant-b"}, {}, None):
        monkeypatch.setattr(
            control_loop_api,
            "resource_context_pipeline",
            _pipeline_with_tags(tags),
        )
        response = _app().post(
            "/autonomy/control-loop/evaluate",
            json=_payload(),
            headers={"Authorization": "Bearer tenant-token"},
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Resource not found"

    assert trail.get_events("tenant-scope-action") == []
