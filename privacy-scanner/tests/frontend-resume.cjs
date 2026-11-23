'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/deep.js'),'utf8');
const job='aabbccdd-1234-5678-abcd-123456789012',key='shards_privacy_deep_job_v1';
function el(){return {textContent:'',value:'',disabled:false,hidden:true,checked:false,children:[],style:{},addEventListener(t,f){(this.events||={})[t]=f},appendChild(x){this.children.push(x)},replaceChildren(){this.children=[]}};}
function create(stored){
 const elements={};for(const n of ['scanForm','start','status','led','output','stats','results','filter','export','username','consent'])elements[n]=el();
 const urls=[],memory=new Map(stored?[[key,JSON.stringify(stored)]]:[]);
 const storage={getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};
 const fetch=async url=>{urls.push(url);if(!url.startsWith('/api/identity/deep/status?id='))throw Error('Unexpected request '+url);
 return {ok:true,json:async()=>({state:'complete',summary:{attempted:118,found:9,unknown:23,no_public_match:65,not_applicable:21},results:[]})};};
 vm.runInNewContext(source,{document:{getElementById:n=>elements[n],createElement:()=>el()},sessionStorage:storage,fetch,URL,Date,Math,JSON,Error,Promise,RegExp,Blob,setTimeout:cb=>queueMicrotask(cb),console},{timeout:1500});
 return {elements,urls,memory};
}
async function settle(){for(let i=0;i<16;i++)await new Promise(resolve=>setImmediate(resolve));}
(async()=>{
 let x=create({id:job,created:Date.now()});await settle();
 assert.equal(x.urls.length,1);assert.ok(x.urls[0].includes(job));
 assert.match(x.elements.status.textContent,/Recovered: 9 candidates from 118 results/);
 assert.equal(x.elements.start.disabled,false);assert.equal(x.elements.output.hidden,false);
 x=create({id:job,created:Date.now()-1900000});await settle();
 assert.equal(x.urls.length,0);assert.equal(x.memory.has(key),false);
 x=create(null);await settle();assert.equal(x.urls.length,0);
 console.log('PASS: refresh resumes old job without a new scan; expired and fresh tabs do not scan');
})().catch(err=>{console.error(err);process.exitCode=1});
