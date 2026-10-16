from fastapi.testclient import TestClient

from main import app


def test_console_exposes_inventory_search_and_ec2_state_filter():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="inventorySearch"' in html
    assert 'id="instanceState"' in html
    assert "encodeURIComponent($('instanceState').value)" in html
    assert "toLocaleLowerCase().includes(search)" in html

