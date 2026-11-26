const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const ts=require('typescript');
const code=ts.transpileModule(fs.readFileSync(path.join(__dirname,'../src/evidence-model.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const context={exports:{}};vm.runInNewContext(code,context);
const anchor=context.exports.candidateAnchor;
let checks=0;
const pages=['SKU: PIPE-DN50\nQuantity: 30','Second page'];
const candidate={page:1,start:5,end:14,raw:'PIPE-DN50'};
assert.equal(JSON.stringify(anchor(candidate,pages,[...pages])),JSON.stringify({page:1,start:5,end:14}));checks++;
for(const change of [{page:0},{page:3},{page:1.5},{start:-1},{start:5.5},{end:99},{end:5},{raw:'wrong'},{start:'5'}, {raw:null}]){
  assert.equal(anchor({...candidate,...change},pages,[...pages]),null);checks++;
}
for(const snapshot of [undefined,[],['different','Second page'],[pages[0]], [pages[0],null]]){
  assert.equal(anchor(candidate,pages,snapshot),null);checks++;
}
const unicode=['📦\nSKU: PIPE-DN50'];
const result=anchor({page:1,start:7,end:16,raw:'PIPE-DN50'},unicode,[...unicode]);
assert.equal(unicode[0].slice(result.start,result.end),'PIPE-DN50');checks++;
const repeated=['PIPE-DN50 / PIPE-DN50'];
assert.equal(anchor({page:1,start:1,end:10,raw:'PIPE-DN50'},repeated,[...repeated]),null);checks++;
assert.equal(JSON.stringify(anchor({page:1,start:12,end:21,raw:'PIPE-DN50'},repeated,[...repeated])),JSON.stringify({page:1,start:12,end:21}));checks++;
const current=context.exports.currentFieldReview;
const binding={jobId:'job-a',jobRevision:1,documentRevision:2,sha256:'abc'};
const complete={...candidate,field:'sku',normalized:'PIPE-DN50'};
const event={id:'one',created_at:'2026-11-26T10:00:00Z',data:{job_id:'job-a',job_revision:1,document_revision:2,source_sha256:'abc',candidate_index:0,candidate_snapshot:complete,decision:'accepted'}};
assert.equal(current([event],binding,0,complete).id,'one');checks++;
for(const change of [{job_id:'other'},{job_revision:2},{document_revision:3},{source_sha256:'changed'},{candidate_index:1},{candidate_snapshot:{...complete,raw:'changed'}},{candidate_snapshot:{...complete,start:6}}]){
 assert.equal(current([{...event,data:{...event.data,...change}}],binding,0,complete),null);checks++;
}
const newer={...event,id:'two',created_at:'2026-11-26T11:00:00Z',data:{...event.data,decision:'corrected'}};
assert.equal(current([event,newer],binding,0,complete).id,'two');checks++;
assert.equal(current([newer,event],binding,0,complete).id,'two');checks++;
const reordered=Object.fromEntries(Object.entries(complete).reverse());
assert.equal(current([event],binding,0,reordered).id,'one');checks++;
console.log('EVIDENCE CONTRACT CHECKS PASSED: '+checks);
