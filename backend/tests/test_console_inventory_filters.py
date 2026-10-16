from fastapi.testclient import TestClient

from main import app


def test_console_exposes_inventory_search_and_ec2_state_filter():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="inventorySearch"' in html
    assert 'id="instanceState"' in html
    assert 'id="instanceTag"' in html
    assert 'aria-label="Filter EC2 instances by tag"' in html
    assert "params.set('state',$('instanceState').value)" in html
    assert "params.set('tag',$('instanceTag').value.trim())" in html
    assert "$('instanceTag').addEventListener('change',loadInventory)" in html
    assert "$('instanceTag').addEventListener('keydown'" in html
    assert 'placeholder="Search loaded resources"' in html
    assert 'aria-label="Search loaded inventory"' in html
    assert "function filterInventoryRows()" in html
    assert "filterInventoryRows();message(`${normalized.length} resources loaded.`)" in html
    assert "$('inventorySearch').addEventListener('input',filterInventoryRows)" in html


def test_console_exposes_resumable_s3_bucket_inventory():
    response = TestClient(app).get("/console")
    assert response.status_code == 200
    html = response.text
    assert 'id="bucketPageSize"' in html
    assert 'id="moreBuckets"' in html
    assert "next_continuation_token" in html
    assert "continuation_token" in html


def test_console_exposes_tenant_scoped_ec2_fleet_insights():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="aggregateInsights"' in html
    assert 'id="insightType"' in html
    assert 'value="efficiency"' in html
    assert 'value="cost"' in html
    assert 'value="rightsizing"' in html
    assert 'value="security"' in html
    assert 'id="loadAggregateInsights"' in html
    assert '/cloud/aws/ec2/${category}-insights' in html
    assert "Analyzing your tenant-scoped EC2 fleet" in html
    assert "classList.toggle('hidden',!aws)" in html


def test_console_can_download_s3_objects_from_the_object_browser():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert "objects/download?${query}" in html
    assert "download.textContent='Download'" in html
    assert "The link expires in ${data.expires_in} seconds." in html


def test_console_exports_loaded_inventory_as_search_aware_csv():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="exportInventory" disabled' in html
    assert "function csvCell(value)" in html
    assert "text.replaceAll('\"','\"\"')" in html
    assert "loadedInventory.filter(item=>!search" in html
    assert "item.id,item.type,item.state,item.details" in html
    assert "text=\"'\"+text" in html
    assert "link.download=($('kind').value==='ec2'?'ec2-inventory':'s3-bucket-inventory')+'.csv'" in html
    assert "loadedInventory.push(...normalized)" in html
    assert "$('exportInventory').addEventListener('click',exportInventory)" in html
