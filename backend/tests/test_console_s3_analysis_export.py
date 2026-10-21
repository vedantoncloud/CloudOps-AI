import json
import re
import shutil
import subprocess

from fastapi.testclient import TestClient

from main import app


def _script_function(html, name, next_name):
    if next_name == "billingData":
        return re.search(r"async function analyzeBucket\(.*?(?=let billingData=)", html, re.S)
    return re.search(
        rf"(?:async )?function {name}\(.*?(?=\nfunction {next_name}\(|\nasync function {next_name}\()",
        html,
        re.S,
    )


def test_console_exposes_s3_analysis_export_disabled_until_analysis_finishes():
    html = TestClient(app).get("/console").text
    assert 'id="exportBucketAnalysis" disabled' in html
    assert "$('exportBucketAnalysis').disabled=false" in html
    assert "$('exportBucketAnalysis').disabled=true" in html
    assert "$('exportBucketAnalysis').addEventListener('click',exportBucketAnalysis)" in html


def test_s3_analysis_export_flattens_results_and_marks_scan_coverage_safely():
    if not shutil.which("node"):
        return
    html = TestClient(app).get("/console").text
    match = _script_function(html, "exportBucketAnalysis", "analyzeBucket")
    assert match
    script = r"""
const assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]);
let downloads=[],blobs=[];
const document={body:{append(link){downloads.push(link)}},createElement(){return {click(){},remove(){}}}};
const URL={createObjectURL(blob){blobs.push(blob);return 'blob:test'},revokeObjectURL(){}};
const csvCell=value=>{let text=String(value??'');if(/^[\t\r ]*[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"'};
const report={bucket:'bucket',prefix:'logs/',checks:[{name:'Object statistics',status:'success',data:{scan_complete:false,scan_limit:1000,summary:{count:4},note:'=SUM(A1:A2)'}},{name:'Security',status:'failed',error:'service unavailable'}]};
const make=new Function('$','message','csvCell','URL','Blob','document','initial',"let bucketAnalysisReport=initial;"+source+';return exportBucketAnalysis');
(async()=>{const run=make(()=>{},()=>{},csvCell,URL,Blob,document,report);run();assert.equal(downloads.length,1);assert.equal(downloads[0].download,'bucket-analysis.csv');const csv=await blobs[0].text();assert(csv.includes('"bucket","logs/","Object statistics","success","summary.count","4","false","1000"'));assert(csv.includes("'=SUM(A1:A2)"));assert(csv.includes('"bucket","logs/","Security","failed","error","service unavailable"'));assert.equal(csv.split('\r\n').length,7);const empty=make(()=>{},()=>{},csvCell,URL,Blob,document,null);empty();assert.equal(downloads.length,1)})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", script, json.dumps(match.group(0))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_s3_analysis_retains_partial_failures_for_export_and_clears_stale_report():
    if not shutil.which("node"):
        return
    html = TestClient(app).get("/console").text
    match = _script_function(html, "analyzeBucket", "billingData")
    assert match
    script = r"""
const assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]);
const elements={exportBucketAnalysis:{disabled:false},analysisPrefix:{value:'logs/'},bucketAnalysisResults:{replaceChildren(){},append(){}},bucketAnalysisStatus:{textContent:'',className:''}};
const document={createElement(){return {className:'',append(){}}}};
let calls=0;
const api=async()=>{calls++;if(calls===2)throw new Error('check unavailable');return {status:'healthy',scan_complete:false,scan_limit:1000}};
const make=new Function('$','api','document',"let activeBucket='old',bucketAnalysisReport={old:true};"+source+';return {analyzeBucket,get:()=>bucketAnalysisReport}');
(async()=>{const run=make(id=>elements[id],api,document);await run.analyzeBucket('new-bucket');const report=run.get();assert.equal(report.bucket,'new-bucket');assert.equal(report.prefix,'logs/');assert.equal(report.checks.length,9);assert.equal(report.checks[1].status,'failed');assert.equal(report.checks[1].error,'check unavailable');assert.equal(report.checks[0].data.scan_complete,false);assert.equal(elements.exportBucketAnalysis.disabled,false);assert.match(elements.bucketAnalysisStatus.textContent,/8 of 9 checks loaded; 1 failed/);assert.equal(calls,9)})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(
        ["node", "-e", script, json.dumps(match.group(0))],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
