import React,{useEffect,useRef,useState} from 'react';
import {request} from './api';

export type SearchCitation={document_id:string;document_revision:number;filename:string;sha256:string;parser:string;page:number;start:number;end:number;quote:string;score:number};
type SearchResult={hits:SearchCitation[];abstained:boolean;truncated:boolean;answer:null};

export function DocumentSearch({onOpenCitation}:{onOpenCitation:(citation:SearchCitation)=>Promise<void>}){
  const [query,setQuery]=useState(''),[result,setResult]=useState<SearchResult|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const epoch=useRef(0);
  useEffect(()=>()=>{epoch.current+=1;},[]);
  async function search(event:React.FormEvent){
    event.preventDefault();const current=++epoch.current;setBusy(true);setError('');setResult(null);
    try{const found=await request('/search',{query:query.trim()});if(current===epoch.current)setResult(found);}
    catch(reason){if(current===epoch.current){let message=reason instanceof Error?reason.message:String(reason);try{message=JSON.parse(message).message||message;}catch{}setError(message);}}
    finally{if(current===epoch.current)setBusy(false);}
  }
  return <section className="panel document-search" aria-labelledby="document-search-heading">
    <p className="evidence-eyebrow">FIND SOURCE EVIDENCE</p><h2 id="document-search-heading">Search document evidence</h2>
    <p>Search permitted, readable documents. Every search word must appear in one quoted passage. Results are source text, not verified facts or generated answers.</p>
    <form onSubmit={search}><label>Search words or identifiers<input value={query} minLength={2} maxLength={500} required disabled={busy} placeholder="For example: PIPE DN50 or ASTM A106" onChange={event=>{setQuery(event.target.value);setResult(null);setError('');}}/></label><button disabled={busy||query.trim().length<2}>{busy?'Searching…':'Search evidence'}</button></form>
    {error&&<p role="alert" className="error">{error}</p>}
    {result&&<div className="document-search-results" aria-live="polite">
      {result.abstained?<div className="evidence-empty"><h3>No matching evidence found</h3><p>No permitted passage matches all your search terms. Try a specific SKU, grade or phrase. This does not establish that a fact is true or false.</p></div>:<><p>{result.hits.length} {result.hits.length===1?'cited passage':'cited passages'}{result.truncated?' shown; additional matches exist. Narrow your search.':'.'} No generated answer or approval is provided.</p><ol>{result.hits.map(hit=><li key={hit.document_id+':'+hit.page+':'+hit.start}>
        <div className="document-search-result-heading"><h3>{hit.filename}</h3><span>Page {hit.page} · revision {hit.document_revision}</span></div>
        <blockquote>{hit.quote}</blockquote><div className="document-search-reference"><code title={hit.sha256}>SHA-256 {hit.sha256.slice(0,16)}…</code><span>Text reference {hit.start}–{hit.end} · {hit.parser}</span></div>
        <button type="button" className="quiet" onClick={()=>onOpenCitation(hit)}>Open cited passage</button>
      </li>)}</ol></>}
    </div>}
  </section>;
}
