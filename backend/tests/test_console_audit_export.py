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
    assert 'id="auditStart" type="datetime-local"' in html
    assert 'id="auditEnd" type="datetime-local"' in html
    assert "function auditFilters()" in html
    assert "query.set(param,timestamp.toISOString())" in html
    assert "query.set('start_time'" not in html  # filters are shared by list and export
    assert "query=auditFilters();query.set('limit'" in html
    assert "const query=auditFilters();const response=await fetch" in html
    assert "Start time must be at or before end time." in html
    assert "$('auditStart').addEventListener('change',()=>loadAudit())" in html
    assert "$('auditEnd').addEventListener('change',()=>loadAudit())" in html


def test_console_audit_actor_filter_is_shared_by_listing_and_export():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="auditActor"' in html
    assert "actor=$('auditActor').value.trim()" in html
    assert "if(actor)query.set('actor_id',actor)" in html
    assert "$('auditActor').addEventListener('keydown'" in html
    assert "const query=auditFilters();const response=await fetch" in html

def test_console_audit_event_type_filter_is_shared_by_listing_and_export():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="auditEvent"' in html
    assert "event=$('auditEvent').value.trim()" in html
    assert "if(event)query.set('event',event)" in html
    assert "$('auditEvent').addEventListener('keydown'" in html
    assert "query=auditFilters();query.set('limit'" in html
    assert "const query=auditFilters();const response=await fetch" in html
