from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import AccessControlMiddleware, Principal
from main import app, console


def test_console_is_served_to_authenticated_reader():
    client = TestClient(app)
    response = client.get("/console")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "CloudOps AI" in response.text
    assert "Pending approvals" in response.text
    assert "Your autonomous run history" in response.text
    assert "governance" in response.text
    assert "Action plans" in response.text
    assert "Browse objects" in response.text
    assert "Object key prefix" in response.text
    assert "Next page" in response.text
    assert 'id="morePlans"' in response.text
    assert 'id="moreInstances"' in response.text
    assert 'id="instancePageSize"' in response.text
    assert "params.set('next_token',instanceToken)" in response.text
    assert "loadInventory(true)" in response.text
    assert 'id="planPageStatus"' in response.text
    assert 'id="planDetails"' in response.text
    assert 'data-tab="audit"' in response.text
    assert 'id="auditRows"' in response.text
    assert 'id="moreAudit"' in response.text


def test_console_uses_tenant_api_contracts_and_does_not_persist_bearer_token():
    response = TestClient(app).get("/console")

    assert "/autonomy/resources/" in response.text
    assert "/autonomy/approvals?limit=50" in response.text
    assert "/autonomy/runs?limit=50" in response.text
    assert "new URLSearchParams({limit:String(planPageSize),offset:String(planOffset)})" in response.text
    assert "loadPlans(true)" in response.text
    assert "$('morePlans').disabled=planOffset>=data.total" in response.text
    assert "api(`/autonomy/plans/${encodeURIComponent(actionId)}`)" in response.text
    assert "JSON.stringify(data.action,null,2)" in response.text
    assert "inspect.addEventListener('click',()=>inspectPlan(p.action_id))" in response.text
    assert "if(!append)planOffset=0" in response.text
    assert 'id="planRisk"' in response.text
    assert 'id="planResourceType"' in response.text
    assert "[['planStatus','status'],['planRisk','risk'],['planResourceType','resource_type']]" in response.text
    assert "$('planRisk').addEventListener('change',()=>loadPlans())" in response.text
    assert "/autonomy/ec2/instances/${encodeURIComponent(resource.id)}/plans" in response.text
    assert "/autonomy/s3/buckets/${encodeURIComponent(resource.id)}/plans" in response.text
    assert "api(path,{method:'POST'})" in response.text
    assert "`/autonomy/audit/events?${query}`" in response.text
    assert "query.set('resource_id',resource)" in response.text
    assert "$('moreAudit').disabled=events.length<auditPageSize" in response.text
    assert "Dry run" in response.text
    assert "localStorage" not in response.text
    assert "sessionStorage" not in response.text


def test_console_s3_object_browser_uses_bounded_resumable_listing_contract():
    response = TestClient(app).get("/console")

    assert "max_keys:$('objectPageSize').value" in response.text
    assert "query.set('prefix',prefix)" in response.text
    assert "query.set('continuation_token',token)" in response.text
    assert "data.next_continuation_token" in response.text
    assert "encodeURIComponent(activeBucket)" in response.text
    assert 'id="objectMetadata"' in response.text
    assert "objects/metadata?${query}" in response.text
    assert "button.textContent='Inspect'" in response.text
    assert "async function fetchObjects(token='',append=false)" in response.text
    assert "fetchObjects(nextObjectToken,true)" in response.text
    assert "if(append){for(const row of mapped)" in response.text
    assert "${$('objectRows').rows.length} objects loaded" in response.text
    assert "if(!append)$('objectRows').replaceChildren()" in response.text


def test_console_is_protected_by_token_authentication():
    secured = FastAPI()
    secured.add_middleware(
        AccessControlMiddleware,
        mode="token",
        tokens={"valid": Principal("operator", "operator", "tenant-a")},
    )
    secured.add_api_route("/console", console)
    client = TestClient(secured)

    assert client.get("/console").status_code == 401
    response = client.get("/console", headers={"Authorization": "Bearer valid"})
    assert response.status_code == 200


def test_console_exposes_ec2_and_s3_resource_details_and_metrics():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    assert 'id="resourceDetails"' in response.text
    assert "details.textContent='Details'" in response.text
    assert "inspectDetails(x,aws?'ec2':'s3')" in response.text
    assert "['Metrics',root+'/metrics?lookback_hours='+metricsWindow.value]" in response.text
    assert "['Insights',root+'/insights']" in response.text
    assert "Promise.allSettled(paths.map(([,path])=>api(path)))" in response.text


def test_console_exposes_bounded_s3_bucket_analysis_with_independent_results():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="bucketAnalysis"' in html
    assert 'id="analysisPrefix"' in html
    assert 'id="loadBucketAnalysis"' in html
    assert "new URLSearchParams({max_keys:'1000'})" in html
    assert "query.set('prefix',prefix)" in html
    assert "${base}/statistics?${query}" in html
    assert "${base}/health?${query}" in html
    assert "${base}/security-insights" in html
    assert "${base}/cost-insights?${query}" in html
    assert "${base}/largest-objects?${query}&top_n=10" in html
    assert "Promise.allSettled(checks.map(([,path])=>api(path)))" in html
    assert "outcome.reason.message" in html
    assert "Results cover at most 1,000 matching objects." in html
