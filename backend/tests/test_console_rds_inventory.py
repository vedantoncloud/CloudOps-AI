from fastapi.testclient import TestClient

import main


def test_console_exposes_regional_paginated_rds_inventory_and_csv_export():
    html = TestClient(main.app).get("/console").text
    assert 'id="loadRdsInstances"' in html
    assert 'id="rdsRows"' in html
    assert 'id="moreRdsInstances"' in html
    assert 'id="exportRdsInstances"' in html
    assert 'api("/cloud/aws/rds/instances?"+params)' in html
    assert 'params.set("region",region)' in html
    assert 'params.set("marker",requested)' in html
    assert 'rdsSeenMarkers.has(next)' in html
    assert 'row.map(csvCell)' in html
    assert 'rds-instances.csv' in html
    assert 'no RDS instances found.' in html
    assert 'RDS inventory response is incomplete.' in html
