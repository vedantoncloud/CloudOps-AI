from fastapi.testclient import TestClient

from main import app


def test_console_can_download_actor_scoped_audit_export_with_current_filter():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="exportAudit"' in html
    assert "addEventListener('click',exportAudit)" in html
    assert "/autonomy/audit/events/export" in html
    assert "query.set('resource_id',resource)" in html
    assert "Authorization:'Bearer '+bearer" in html
    assert "link.download='audit-events.jsonl'" in html
