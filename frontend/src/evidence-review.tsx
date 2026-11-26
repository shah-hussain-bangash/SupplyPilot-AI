import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Row} from './api';
import {candidateAnchor} from './evidence-model';
import './evidence-review.css';

export type EvidenceSnapshot={document:Row; source:{document_id:string;sha256:string;parser:string;pages:string[]}; job:Row|null};
const label=(value:unknown,fallback='')=>typeof value==='string'?value:fallback;

export function EvidenceReview({snapshot,onClose}:{snapshot:EvidenceSnapshot;onClose:()=>void}) {
  const {document,source,job}=snapshot;
  const result=job?.data.result;
  const allCandidates=Array.isArray(result?.candidates)?result.candidates:[];
  const candidates=allCandidates.slice(0,200);
  const anchors=useMemo(()=>allCandidates.slice(0,200).map((candidate:any)=>candidateAnchor(candidate,source.pages,result?.pages)),[result,source]);
  const [selected,setSelected]=useState(0),[page,setPage]=useState(1);
  const heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{heading.current?.focus({preventScroll:true});heading.current?.scrollIntoView({block:'start',behavior:'instant'});},[]);
  const current=candidates[selected];
  const anchor=anchors[selected];
  const text=source.pages[page-1]||'';
  const highlight=anchor?.page===page?anchor:null;
  function choose(index:number){
    setSelected(index);
    const candidate=candidates[index];
    if(Number.isInteger(candidate?.page)&&candidate.page>=1&&candidate.page<=source.pages.length)setPage(candidate.page);
  }
  return <section className="panel evidence-review" aria-labelledby="evidence-review-heading">
    <div className="heading-row"><div><p className="evidence-eyebrow">SOURCE COMPARISON</p><h2 id="evidence-review-heading" ref={heading} tabIndex={-1}>Evidence workspace</h2></div><button className="quiet" onClick={onClose}>Close evidence workspace</button></div>
    <p className="evidence-description">Read-only comparison. Confirm the original source before a separate technical review or procurement decision.</p>
    <div className="evidence-summary"><div><span>Source document</span><strong>{label(document.data.filename,'Source document')}</strong></div><div><span>Extraction</span><strong>{document.data.ocr?'Local OCR · human review required':'Extracted text · human review required'}</strong></div><div><span>Source status</span><strong>{label(document.data.status).replaceAll('_',' ')}</strong></div></div>
    {document.data.status==='quarantined'&&<p className="evidence-warning">Quarantined source: extracted text may be incomplete. Manual source handling is required.</p>}
    {document.data.ocr&&<p className="evidence-warning">OCR can contain recognition errors. Highlights refer to extracted text, not positions in the original scan.</p>}
    <div className="evidence-columns">
      <section className="evidence-fields" aria-label="Extracted candidate fields"><div className="evidence-column-heading"><h3>Extracted fields</h3><span>{allCandidates.length} candidates</span></div>
        <p>Select a field to see its text reference.</p>
        {candidates.length?<ul>{candidates.map((candidate:any,index:number)=>{
          const valid=anchors[index];
          const field=candidate?.field==='sku'?'SKU':label(candidate?.field,'Field');const value=label(candidate?.normalized,label(candidate?.value,label(candidate?.raw)));
          return <li key={index}><button type="button" className="evidence-candidate" aria-pressed={selected===index} onClick={()=>choose(index)}>
            <span className="evidence-field-name">{field}</span><strong>{value||'No extracted value'}</strong>
            <span className="evidence-field-meta"><span>{valid?'Page '+valid.page:'Source anchor unavailable'}</span><span className="evidence-review-state">{candidate?.reviewed===true?'Recorded as reviewed':'Unreviewed'}</span></span>
          </button></li>;
        })}</ul>:<div className="evidence-empty">No extraction result is available in this view. You can still read the permitted source text.</div>}
        {allCandidates.length>200&&<p>Showing the first 200 candidates. The complete result remains available under processing record details.</p>}
      </section>
      <section className="evidence-source" aria-label="Extracted source text"><div className="evidence-column-heading"><h3>Extracted source text</h3><label>Source page<select aria-label="Source page" value={page} disabled={!source.pages.length} onChange={e=>setPage(Number(e.target.value))}>{source.pages.map((_,index)=><option key={index} value={index+1}>Page {index+1} of {source.pages.length}</option>)}</select></label></div>
        <p role="status" className="evidence-anchor-status">{highlight?'Showing the exact text reference for '+label(current?.field,'this field')+'.':current?'Source anchor unavailable. Compare this field with the original source.':'Read the extracted source text below.'}</p>
        <pre className="evidence-source-text" tabIndex={0} aria-label={'Source text page '+page}>{highlight?<>{text.slice(0,highlight.start)}<mark>{text.slice(highlight.start,highlight.end)}</mark>{text.slice(highlight.end)}</>:text||'No extracted text is available for this page.'}</pre>
      </section>
    </div>
    <details className="evidence-provenance"><summary>Source provenance</summary><dl><dt>Document ID</dt><dd>{source.document_id}</dd><dt>SHA-256</dt><dd>{source.sha256}</dd><dt>Parser</dt><dd>{source.parser}</dd>{job&&<><dt>Processing record</dt><dd>{job.id} · revision {job.revision}</dd></>}</dl><p>Viewing these fields records no review decision. Formal approval remains in its existing workflow.</p></details>
  </section>;
}
