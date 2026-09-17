from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.control_loop_api import (
    governance_gate,
    resource_context_pipeline,
    router,
)
from autonomy.resource_context_pipeline import ResourceContextPipeline


@dataclass
class FakeProvider:
    provider_name: str = "aws"

    def get_resource(self, resource_type: str, resource_id: str):
        return {
            "provider": "aws",
            "resource_type": resource_type,
            "resource_id": resource_id,
            "read_only": True,
            "state": "running",
            "health": "healthy",
            "tags": {"Environment": "test"},
            "metadata": {"owner": "cloudops"},
        }

    def get_ec2_instances(self):
        return {
            "instances": [
                {
                    "instance_id": "i-123",
                    "state": "running",
                }
            ]
        }

    def get_s3_buckets(self):
        return {"buckets": []}


@pytest.fixture(autouse=True)
def restore_pipeline_dependencies():
    original_gate = resource_context_pipeline.governance_gate
    original_discovery = resource_context_pipeline.discovery
    original_shared_gate = governance_gate.governance

    yield

    resource_context_pipeline.governance_gate = original_gate
    resource_context_pipeline.discovery = original_discovery
    governance_gate.governance = original_shared_gate


def make_client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_pipeline_object_is_shared_by_control_loop_api():
    assert isinstance(resource_context_pipeline, ResourceContextPipeline)
    assert resource_context_pipeline.governance_gate is governance_gate


def test_api_exposes_resource_pipeline_and_context(monkeypatch):
    provider = FakeProvider()

    class FakeRegistry:
        def get(self, name):
            return provider

    monkeypatch.setattr(
        "autonomy.control_loop_api.provider_registry",
        FakeRegistry(),
    )

    class FakePipeline:
        def build(self, *, provider, resource_type, resource_id):
            class FakeGovernance:
                allowed = True
                blocked = False
                requires_human_review = False
                decision = type("Decision", (), {"value": "allow"})()
                evidence = {"governance_gate": "allow"}
                resource = type(
                    "Resource",
                    (),
                    {
                        "policy": type(
                            "Policy",
                            (),
                            {"reasons": []},
                        )()
                    },
                )()

            return type(
                "PipelineResult",
                (),
                {
                    "allowed_for_decision": True,
                    "blocked": False,
                    "requires_human_review": False,
                    "governance": FakeGovernance(),
                    "resource_context": type(
                        "Context",
                        (),
                        {
                            # These fields are required by
                            # DecisionIntelligenceEngine.
                            "provider": "aws",
                            "resource_id": resource_id,
                            "resource_type": resource_type,
                            "observation": {
                                "provider": "aws",
                                "resource_type": resource_type,
                                "resource_id": resource_id,
                                "read_only": True,
                                "state": "running",
                            },
                        },
                    )(),
                    "evidence": {
                        "discovered": True,
                        "pipeline_outcome": "allowed",
                    },
                },
            )()

    monkeypatch.setattr(
        "autonomy.control_loop_api.resource_context_pipeline",
        FakePipeline(),
    )

    response = make_client().post(
        "/autonomy/control-loop/evaluate",
        json={
            "provider": "aws",
            "action_id": "pipeline-api-1",
            "action_type": "scale",
            "resource_type": "ec2",
            "resource_id": "i-123",
            "reason": "test pipeline",
            "risk": "medium",
            "requires_approval": True,
            "field": "desired_state",
            "desired_value": "running",
            "current_value": "running",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["provider"] == "aws"
    assert body["resource_id"] == "i-123"

    assert body["evidence"]["resource_pipeline"]["discovered"] is True
    assert (
        body["evidence"]["resource_pipeline"]["pipeline_outcome"]
        == "allowed"
    )

    assert (
        body["evidence"]["resource_context"]["resource_id"]
        == "i-123"
    )
    assert (
        body["evidence"]["resource_context"]["provider"]
        == "aws"
    )


def test_governance_review_still_stops_before_decision_flow(monkeypatch):
    provider = FakeProvider()

    class FakeRegistry:
        def get(self, name):
            return provider

    monkeypatch.setattr(
        "autonomy.control_loop_api.provider_registry",
        FakeRegistry(),
    )

    class ReviewPipeline:
        def build(self, **kwargs):
            governance = type(
                "Governance",
                (),
                {
                    "allowed": False,
                    "blocked": False,
                    "requires_human_review": True,
                    "decision": type(
                        "Decision",
                        (),
                        {"value": "review"},
                    )(),
                    "evidence": {
                        "governance_gate": "review",
                    },
                    "resource": type(
                        "Resource",
                        (),
                        {
                            "policy": type(
                                "Policy",
                                (),
                                {
                                    "reasons": [
                                        "manual review"
                                    ]
                                },
                            )()
                        },
                    )(),
                },
            )()

            context = type(
                "Context",
                (),
                {
                    "provider": "aws",
                    "resource_id": "i-review",
                    "resource_type": "ec2",
                    "observation": {
                        "provider": "aws",
                        "resource_type": "ec2",
                        "resource_id": "i-review",
                        "read_only": True,
                    },
                },
            )()

            return type(
                "PipelineResult",
                (),
                {
                    "allowed_for_decision": False,
                    "blocked": False,
                    "requires_human_review": True,
                    "governance": governance,
                    "resource_context": context,
                    "evidence": {
                        "discovered": True,
                        "pipeline_outcome": "review",
                    },
                },
            )()

    monkeypatch.setattr(
        "autonomy.control_loop_api.resource_context_pipeline",
        ReviewPipeline(),
    )

    response = make_client().post(
        "/autonomy/control-loop/evaluate",
        json={
            "provider": "aws",
            "action_id": "pipeline-review-1",
            "action_type": "scale",
            "resource_type": "ec2",
            "resource_id": "i-review",
            "reason": "review test",
            "field": "desired_state",
            "desired_value": "running",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["recommendation"] == "review"
    assert body["requires_human_review"] is True
    assert body["blocked"] is False
    assert body["gitops_created"] is False

    assert (
        body["evidence"]["resource_pipeline"]["pipeline_outcome"]
        == "review"
    )


def test_governance_deny_stops_before_decision_flow(monkeypatch):
    provider = FakeProvider()

    class FakeRegistry:
        def get(self, name):
            return provider

    monkeypatch.setattr(
        "autonomy.control_loop_api.provider_registry",
        FakeRegistry(),
    )

    class DenyPipeline:
        def build(self, **kwargs):
            governance = type(
                "Governance",
                (),
                {
                    "allowed": False,
                    "blocked": True,
                    "requires_human_review": False,
                    "decision": type(
                        "Decision",
                        (),
                        {"value": "deny"},
                    )(),
                    "evidence": {
                        "governance_gate": "deny",
                        "policy_decision": "deny",
                    },
                    "resource": type(
                        "Resource",
                        (),
                        {
                            "policy": type(
                                "Policy",
                                (),
                                {
                                    "reasons": [
                                        "resource type denied"
                                    ]
                                },
                            )()
                        },
                    )(),
                },
            )()

            context = type(
                "Context",
                (),
                {
                    "provider": "aws",
                    "resource_id": "i-deny",
                    "resource_type": "ec2",
                    "observation": {
                        "provider": "aws",
                        "resource_type": "ec2",
                        "resource_id": "i-deny",
                        "read_only": True,
                    },
                },
            )()

            return type(
                "PipelineResult",
                (),
                {
                    "allowed_for_decision": False,
                    "blocked": True,
                    "requires_human_review": False,
                    "governance": governance,
                    "resource_context": context,
                    "evidence": {
                        "discovered": True,
                        "pipeline_outcome": "blocked",
                    },
                },
            )()

    monkeypatch.setattr(
        "autonomy.control_loop_api.resource_context_pipeline",
        DenyPipeline(),
    )

    response = make_client().post(
        "/autonomy/control-loop/evaluate",
        json={
            "provider": "aws",
            "action_id": "pipeline-deny-1",
            "action_type": "scale",
            "resource_type": "ec2",
            "resource_id": "i-deny",
            "reason": "deny test",
            "field": "desired_state",
            "desired_value": "stopped",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["recommendation"] == "deny"
    assert body["blocked"] is True
    assert body["requires_human_review"] is False
    assert body["gitops_created"] is False

    assert (
        body["evidence"]["resource_pipeline"]["pipeline_outcome"]
        == "blocked"
    )
    assert (
        body["evidence"]["governance"]["policy_decision"]
        == "deny"
    )
