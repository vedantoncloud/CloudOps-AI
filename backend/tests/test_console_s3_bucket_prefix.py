from fastapi.testclient import TestClient

from main import app


def test_console_s3_bucket_prefix_filter_is_preserved_across_pages_and_exports():
    html = TestClient(app).get("/console").text

    assert 'id="bucketPrefix"' in html
    assert 'aria-label="Filter S3 buckets by name prefix"' in html
    assert "params.set('prefix',$('bucketPrefix').value.trim())" in html
    assert html.count("params.set('prefix',$('bucketPrefix').value.trim())") == 2
    assert "$('bucketPrefix').addEventListener('change',loadInventory)" in html
    assert "$('bucketPrefix').addEventListener('keydown'" in html
    assert "$('bucketPrefix').classList.toggle('hidden',aws)" in html
