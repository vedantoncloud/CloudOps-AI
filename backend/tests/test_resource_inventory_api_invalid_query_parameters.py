import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autonomy.resource_inventory_api import router


@pytest.mark.parametrize(
    ("query", "expected_detail"),
    [
        ("provider=&resource_type=ec2", "provider cannot be empty"),
        ("provider=%20%20&resource_type=ec2", "provider cannot be empty"),
        ("provider=aws&resource_type=", "resource_type cannot be empty"),
        ("provider=aws&resource_type=%20%20", "resource_type cannot be empty"),
    ],
)
def test_inventory_api_rejects_blank_query_parameters(
    query,
    expected_detail,
):
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get(
        f"/autonomy/resources?{query}"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail
