import json
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from main import app


def test_console_exposes_complete_prefix_object_export():
    html = TestClient(app).get("/console").text
    assert 'id="exportAllObjects"' in html
    assert "async function exportAllObjects()" in html
    assert "query.set('continuation_token',token)" in html
    assert "link.download=`${bucket}-objects.csv`" in html
    assert "Object pagination repeated a cursor" in html
    assert "objects exported as CSV" in html


def test_complete_object_export_paginates_and_fails_closed():
    if not shutil.which("node"):
        pytest.skip("Node.js is needed to run the console JavaScript behavior check")
    html = TestClient(app).get("/console").text
    match = re.search(r"async function exportAllObjects\(\).*?(?=async function analyzeBucket)", html, re.S)
    assert match
    script = r"""
const assert = require('node:assert/strict');
const source = JSON.parse(process.argv[1]);
const elements = {exportAllObjects:{disabled:false},objectPrefix:{value:'reports/'}};
let downloads=[],messages=[],blobs=[],calls=[];
const document={body:{append(link){downloads.push(link)}},createElement(){return {click(){},remove(){}}}};
const URL={createObjectURL(blob){blobs.push(blob);return 'blob:test'},revokeObjectURL(){}};
const csvCell=value=>{let text=String(value??'');if(/^[\t\r ]*[=+\-@]/.test(text))text="'"+text;return '"'+text.replaceAll('"','""')+'"'};
const make=new Function('$','api','message','csvCell','URL','Blob','document','URLSearchParams',"let activeBucket='logs';"+source+';return exportAllObjects');
async function scenario(apiImpl,count,errorText){downloads=[];messages=[];blobs=[];calls=[];elements.exportAllObjects.disabled=false;const api=async path=>{calls.push(path);return apiImpl(path,calls.length)};await make(id=>elements[id],api,(text,error)=>messages.push([text,error]),csvCell,URL,Blob,document,URLSearchParams)();assert.equal(downloads.length,count);assert.equal(elements.exportAllObjects.disabled,false);if(errorText)assert(messages.some(([text,error])=>error&&text.includes(errorText)));return {calls,downloads,blobs};}
(async()=>{
 let out=await scenario((path,n)=>n===1?{objects:[{key:'reports/one',size:3}],is_truncated:true,next_continuation_token:'cursor'}:{objects:[{key:'reports/two',size:'=SUM(A1)'}],is_truncated:false},1);
 assert.equal(out.calls.length,2);assert(out.calls.every(path=>path.includes('prefix=reports%2F')));assert(out.calls[1].includes('continuation_token=cursor'));const csv=await out.blobs[0].text();assert(csv.includes('reports/one'));assert(csv.includes("'=SUM(A1)"));
 await scenario((path,n)=>n===1?{objects:[],is_truncated:true,next_continuation_token:'cursor'}:Promise.reject(new Error('AWS unavailable')),0,'AWS unavailable');
 out=await scenario(()=>({objects:[],is_truncated:true,next_continuation_token:'same'}),0,'repeated a cursor');assert.equal(out.calls.length,2);
 await scenario(()=>({objects:[],is_truncated:true}),0,'no continuation cursor');
 await scenario(()=>({objects:[],is_truncated:false}),0,'No objects match');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
    result = subprocess.run(["node", "-e", script, json.dumps(match.group(0))], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
