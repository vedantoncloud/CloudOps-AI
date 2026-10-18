import json
import re
import shutil
import subprocess

import pytest

from fastapi.testclient import TestClient

from main import app


def test_console_exposes_inventory_search_and_ec2_state_filter():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="inventorySearch"' in html
    assert 'id="instanceState"' in html
    assert 'id="instanceTag"' in html
    assert 'id="instanceName"' in html
    assert 'aria-label="Filter EC2 instances by Name tag"' in html
    assert 'aria-label="Filter EC2 instances by tag"' in html
    assert "params.set('state',$('instanceState').value)" in html
    assert "params.set('tag',$('instanceTag').value.trim())" in html
    assert "params.set('name',$('instanceName').value.trim())" in html
    assert "$('instanceName').addEventListener('change',loadInventory)" in html
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


def test_console_can_export_all_filtered_inventory_pages_without_partial_downloads():
    response = TestClient(app).get("/console")

    assert response.status_code == 200
    html = response.text
    assert 'id="exportAllInventory"' in html
    assert "async function exportAllInventory()" in html
    assert "params.set('max_results','1000')" in html
    assert "params.set('max_buckets','1000')" in html
    assert "params.set('next_token',token)" in html
    assert "params.set('continuation_token',token)" in html
    assert "if(data.is_truncated&&!next)throw new Error" in html
    assert "if(seen.has(next))throw new Error" in html
    assert "Inventory pagination repeated a cursor" in html
    assert "const visible=items.filter(item=>!search" in html
    assert "catch(e){message(e.message,true)}finally{button.disabled=false}" in html
    assert "matching resources exported as CSV" in html
    assert "$('exportAllInventory').addEventListener('click',exportAllInventory)" in html


def test_console_exports_all_filtered_action_plan_pages_as_safe_csv():
    response = TestClient(app).get("/console")
    assert response.status_code == 200
    html = response.text
    assert 'id="exportPlans"' in html
    assert "async function exportPlans()" in html
    assert "limit:'200',offset:'0'" in html
    assert "filters.set('search',$('planSearch').value.trim())" in html
    assert "['planStatus','status'],['planRisk','risk'],['planResourceType','resource_type']" in html
    assert "while(plans.length<total)" in html
    assert "row.map(csvCell)" in html
    assert "link.download='action-plans.csv'" in html
    assert "$('exportPlans').addEventListener('click',exportPlans)" in html

def test_full_inventory_export_paginates_filters_and_fails_closed():
    if not shutil.which("node"):
        pytest.skip("Node.js is needed to run the console JavaScript behavior check")
    html = TestClient(app).get("/console").text
    match = re.search(r"async function exportAllInventory\(\).*?(?=function rows\()", html, re.S)
    assert match
    script = r"""
const assert = require('node:assert/strict');
const source = JSON.parse(process.argv[1]);
const elements = {exportAllInventory:{disabled:false},kind:{value:'ec2'},inventorySearch:{value:'second'},instanceState:{value:'running'},instanceTag:{value:'Owner:ops'},instanceName:{value:'web'}};
let downloads=[],messages=[],blobs=[],calls=[];
const document={body:{append(link){downloads.push(link)}},createElement(){return {click(){},remove(){}}}};
const URL={createObjectURL(blob){blobs.push(blob);return 'blob:test'},revokeObjectURL(){}};
const csvCell=value=>'"'+String(value??'').replaceAll('"','""')+'"';
const make=new Function('$','api','message','csvCell','URL','Blob','document',source+';return exportAllInventory');
async function scenario(apiImpl,count,errorText){downloads=[];messages=[];blobs=[];calls=[];elements.exportAllInventory.disabled=false;const api=async path=>{calls.push(path);return apiImpl(path,calls.length)};await make(id=>elements[id],api,(text,error)=>messages.push([text,error]),csvCell,URL,Blob,document)();assert.equal(downloads.length,count);assert.equal(elements.exportAllInventory.disabled,false);if(errorText)assert(messages.some(([text,error])=>error&&text.includes(errorText)));return {calls,downloads,blobs};}
(async()=>{
 let out=await scenario((path,n)=>n===1?{instances:[{instance_id:'i-first',state:'stopped'}],is_truncated:true,next_token:'cursor'}:{instances:[{instance_id:'i-second',state:'running',name:'web'}],is_truncated:false},1);
 assert.equal(out.calls.length,2);assert(out.calls[0].includes('state=running'));assert(out.calls[1].includes('next_token=cursor'));const csv=await out.blobs[0].text();assert(csv.includes('i-second'));assert(!csv.includes('i-first'));
 out=await scenario((path,n)=>n===1?{instances:[],is_truncated:true,next_token:'cursor'}:Promise.reject(new Error('AWS unavailable')),0,'AWS unavailable');assert.equal(out.calls.length,2);
 out=await scenario(()=>({instances:[],is_truncated:true,next_token:'same'}),0,'repeated a cursor');assert.equal(out.calls.length,2);
 out=await scenario(()=>({instances:[{instance_id:'i-x'}],is_truncated:true}),0,'no continuation cursor');assert.equal(out.calls.length,1);
 await scenario(()=>({instances:[],is_truncated:false}),0,'No inventory resources match');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(["node", "-e", script, json.dumps(match.group(0))], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
