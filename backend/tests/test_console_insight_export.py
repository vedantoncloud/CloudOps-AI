import json
import re
import shutil
import subprocess

from fastapi.testclient import TestClient

from main import app


def test_console_enables_insight_export_only_for_loaded_fleet_results():
    html = TestClient(app).get("/console").text
    assert 'id="exportInsights" disabled' in html
    assert "function exportAggregateInsights()" in html
    assert "$('exportInsights').disabled=false" in html
    assert "aggregateInsightData=null" in html


def test_fleet_insight_csv_flattens_nested_values_and_escapes_formulas():
    if not shutil.which("node"):
        return
    html = TestClient(app).get("/console").text
    match = re.search(r"function exportAggregateInsights\(\).*?(?=async function loadAggregateInsights)", html, re.S)
    assert match
    script = r"""
const assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]);
const elements={insightType:{value:'security'},instanceRegion:{value:'us-west-2'}};
let downloads=[],blobs=[],messages=[];
const document={body:{append(link){downloads.push(link)}},createElement(){return {click(){},remove(){}}}};
const URL={createObjectURL(blob){blobs.push(blob);return 'blob:test'},revokeObjectURL(){}};
const csvCell=value=>{let text=String(value??'');if(/^[\t\r ]*[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"'};
const make=new Function('$','message','csvCell','URL','Blob','document','initial',"let aggregateInsightData=initial;"+source+';return exportAggregateInsights');
const exportInsights=make(id=>elements[id],(text,error)=>messages.push([text,error]),csvCell,URL,Blob,document,JSON.parse(process.argv[2]));
(async()=>{
 exportInsights();assert.equal(downloads.length,1);assert.equal(downloads[0].download,'ec2-security-insights.csv');let csv=await blobs[0].text();assert(csv.includes(`\"security\",\"us-west-2\",\"findings[0].resource_id\",\"'=cmd\"`));assert(csv.includes(`\"findings[0].tags[0]\",\"a,b\"`));assert.equal(messages.length,1);
 const empty=make(id=>elements[id],()=>{},csvCell,URL,Blob,document,null);empty();assert.equal(downloads.length,1);
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(["node", "-e", script, json.dumps(match.group(0)), json.dumps({"findings": [{"resource_id": "=cmd", "tags": ["a,b"]}]})], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_insight_provider_failure_disables_export_and_shows_error():
    if not shutil.which("node"):
        return
    html = TestClient(app).get("/console").text
    match = re.search(r"async function loadAggregateInsights\(\).*?(?=function metricChart)", html, re.S)
    assert match
    script = r"""
const assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]);
const elements={aggregateInsightResults:{textContent:'',className:''},insightType:{value:'efficiency'},billingReport:{classList:{add(){}}},exportBilling:{disabled:false},exportInsights:{disabled:false},instanceRegion:{value:''}};
const make=new Function('$','api',"let billingData={old:true},aggregateInsightData={old:true};"+source+';return {loadAggregateInsights,getState:()=>aggregateInsightData}');
(async()=>{const app=make(id=>elements[id],async()=>{throw new Error('AWS unavailable')});await app.loadAggregateInsights();assert.equal(elements.aggregateInsightResults.textContent,'AWS unavailable');assert.equal(elements.aggregateInsightResults.className,'notice error');assert.equal(elements.exportInsights.disabled,true);assert.equal(app.getState(),null)})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(["node", "-e", script, json.dumps(match.group(0))], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
