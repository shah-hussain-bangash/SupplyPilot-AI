import React,{useEffect,useMemo,useRef,useState} from 'react';
import {Row} from './api';
import {candidateAnchor,currentFieldReview,citationAnchor} from './evidence-model';
import './evidence-review.css';
import type {SearchCitation} from './document-search';

export type EvidenceSnapshot={document:Row; source:{document_id:string;sha256:string;parser:string;pages:string[]}; job:Row|null;citation?:SearchCitation};
export type FieldReviewInput={expected_job_revision:number;expected_document_revision:number;source_sha256:string;candidate_index:number;decision:'accepted'|'rejected'|'corrected';corrected_value?:string;reason:string;key:string};
const label=(value:unknown,fallback='')=>typeof value==='string'?value:fallback;
const decisionLabel=(value:string)=>({accepted:'Accepted extraction',rejected:'Rejected extraction',corrected:'Corrected extraction'}[value]||'Unreviewed');

export function EvidenceReview({snapshot,reviews,canReview,onRecordReview,onClose}:{snapshot:EvidenceSnapshot;reviews:Row[];canReview:boolean;onRecordReview:(input:FieldReviewInput)=>Promise<unknown>;onClose:()=>void}) {
  const {document,source,job}=snapshot;
  const result=job?.data.result;
  const allCandidates=Array.isArray(result?.candidates)?result.candidates:[];
  const candidates=allCandidates.slice(0,200);
  const anchors=useMemo(()=>allCandidates.slice(0,200).map((candidate:any)=>candidateAnchor(candidate,source.pages,result?.pages)),[result,source]);
  const [selected,setSelected]=useState(snapshot.citation?-1:0),[page,setPage]=useState(snapshot.citation?.page||1);
  const [citationActive,setCitationActive]=useState(!!snapshot.citation);
  const [decision,setDecision]=useState<FieldReviewInput['decision']>('accepted'),[reason,setReason]=useState(''),[correction,setCorrection]=useState('');
  const [saving,setSaving]=useState(false),[reviewMessage,setReviewMessage]=useState(''),[reviewError,setReviewError]=useState('');
  const requestIdentity=useRef<{signature:string;key:string}|null>(null);
  const heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{heading.current?.focus({preventScroll:true});heading.current?.scrollIntoView({block:'start',behavior:'instant'});},[]);
  const current=candidates[selected];
  const anchor=anchors[selected];
  const text=source.pages[page-1]||'';
  const cited=citationActive?citationAnchor(snapshot.citation,document,source):null;
  const activeAnchor=citationActive?cited:anchor;
  const highlight=activeAnchor?.page===page?activeAnchor:null;
  const binding={jobId:job?.id||'',jobRevision:job?.revision||0,documentRevision:document.revision,sha256:source.sha256};
  const currentReview=currentFieldReview(reviews,binding,selected,current);
  const history=reviews.filter(review=>review.data.job_id===job?.id);
  useEffect(()=>{setReason('');setCorrection('');setDecision('accepted');setReviewMessage('');setReviewError('');requestIdentity.current=null;},[selected]);
  async function recordReview(event:React.FormEvent){
    event.preventDefault();if(!job||!anchor||!canReview)return;
    const payload={expected_job_revision:job.revision,expected_document_revision:document.revision,source_sha256:source.sha256,candidate_index:selected,decision,reason:reason.trim(),...(decision==='corrected'?{corrected_value:correction.trim()}:{} )};
    const signature=JSON.stringify(payload);
    if(requestIdentity.current?.signature!==signature)requestIdentity.current={signature,key:crypto.randomUUID()};
    setSaving(true);setReviewError('');setReviewMessage('');
    try{await onRecordReview({...payload,key:requestIdentity.current.key});setReviewMessage('Field review recorded. Procurement approvals are unchanged.');setReason('');requestIdentity.current=null;}
    catch(error){setReviewError(error instanceof Error?error.message:String(error));}finally{setSaving(false);}
  }
  function choose(index:number){
    setCitationActive(false);setSelected(index);
    const candidate=candidates[index];
    if(Number.isInteger(candidate?.page)&&candidate.page>=1&&candidate.page<=source.pages.length)setPage(candidate.page);
  }
  return <section className="panel evidence-review" aria-labelledby="evidence-review-heading">
    <div className="heading-row"><div><p className="evidence-eyebrow">SOURCE COMPARISON</p><h2 id="evidence-review-heading" ref={heading} tabIndex={-1}>Evidence workspace</h2></div><button className="quiet" onClick={onClose}>Close evidence workspace</button></div>
    <p className="evidence-description">{canReview?'Compare the original source and record a field-review decision. Certificate and procurement approvals remain separate.':'Read-only comparison. Confirm the original source before a separate technical review or procurement decision.'}</p>
    <div className="evidence-summary"><div><span>Source document</span><strong>{label(document.data.filename,'Source document')}</strong></div><div><span>Extraction</span><strong>{document.data.status==='quarantined'?'Manual source handling required':document.data.ocr?'Local OCR · human review required':'Extracted text · human review required'}</strong></div><div><span>Source status</span><strong>{label(document.data.status).replaceAll('_',' ')}</strong></div></div>
    {document.data.status==='quarantined'&&<p className="evidence-warning">Quarantined source: extracted text may be incomplete. Manual source handling is required.</p>}
    {document.data.ocr&&<p className="evidence-warning">OCR can contain recognition errors. Highlights refer to extracted text, not positions in the original scan.</p>}
    <div className="evidence-columns">
      <section className="evidence-fields" aria-label="Extracted candidate fields"><div className="evidence-column-heading"><h3>Extracted fields</h3><span>{allCandidates.length} candidates</span></div>
        {candidates.length>0&&<p>Select a field to see its text reference.</p>}
        {candidates.length?<ul>{candidates.map((candidate:any,index:number)=>{
          const valid=anchors[index];
          const field=candidate?.field==='sku'?'SKU':label(candidate?.field,'Field');const value=label(candidate?.normalized,label(candidate?.value,label(candidate?.raw)));
          const review=currentFieldReview(reviews,binding,index,candidate);
          return <li key={index}><button type="button" className="evidence-candidate" disabled={saving} aria-pressed={selected===index} onClick={()=>choose(index)}>
            <span className="evidence-field-name">{field}</span><strong>{value||'No extracted value'}</strong>
            {review?.data.decision==='corrected'&&<span className="evidence-correction">Reviewed value: {review.data.reviewed_value}</span>}
            <span className="evidence-field-meta"><span>{valid?'Page '+valid.page:'Source anchor unavailable'}</span><span className="evidence-review-state">{review?decisionLabel(review.data.decision):candidate?.reviewed===true?'Recorded as reviewed':'Unreviewed'}</span></span>
          </button></li>;
        })}</ul>:<div className="evidence-empty">No extraction result is available in this view. You can still read the permitted source text.</div>}
        {allCandidates.length>200&&<p>Showing the first 200 candidates. The complete result remains available under processing record details.</p>}
      </section>
      <section className="evidence-source" aria-label="Extracted source text"><div className="evidence-column-heading"><h3>Extracted source text</h3><label>Source page<select aria-label="Source page" value={page} disabled={!source.pages.length} onChange={e=>setPage(Number(e.target.value))}>{source.pages.map((_,index)=><option key={index} value={index+1}>Page {index+1} of {source.pages.length}</option>)}</select></label></div>
        <p role="status" className="evidence-anchor-status">{highlight&&citationActive?'Showing the exact cited search passage.':highlight?'Showing the exact text reference for '+label(current?.field,'this field')+'.':current?'Source anchor unavailable. Compare this field with the original source.':'Read the extracted source text below.'}</p>
        <pre className="evidence-source-text" tabIndex={0} aria-label={'Source text page '+page}>{highlight?<>{text.slice(0,highlight.start)}<mark>{text.slice(highlight.start,highlight.end)}</mark>{text.slice(highlight.end)}</>:text||'No extracted text is available for this page.'}</pre>
      </section>
    </div>
    {currentReview&&<p className="evidence-recorded">Latest matching field review: <strong>{decisionLabel(currentReview.data.decision)}</strong> by {currentReview.data.author_username}. Earlier decisions remain in the history below.</p>}
    {canReview&&job&&current&&<section className="evidence-review-form" aria-label="Record an extraction field review"><h3>Record a field review</h3><p>Validate the extracted text only. This does not certify material, approve suppliers or authorize purchasing.</p>
      {!anchor||document.data.status!=='review_required'?<p className="evidence-warning">An exact source anchor and a readable source are required before recording a review.</p>:<form onSubmit={recordReview}>
        <label>Field review decision<select aria-label="Field review decision" value={decision} disabled={saving} onChange={e=>setDecision(e.target.value as FieldReviewInput['decision'])}><option value="accepted">Accept as extracted</option><option value="rejected">Reject extraction</option><option value="corrected">Correct extraction</option></select></label>
        {decision==='corrected'&&<label>Corrected extracted value<input value={correction} maxLength={500} required disabled={saving} onChange={e=>setCorrection(e.target.value)}/></label>}
        <label>Field review reason<textarea value={reason} minLength={5} maxLength={1000} required disabled={saving} onChange={e=>setReason(e.target.value)}/></label>
        <button type="submit" disabled={saving||reason.trim().length<5||(decision==='corrected'&&!correction.trim())}>{saving?'Recording review…':'Record field review'}</button>
      </form>}
      {reviewMessage&&<p role="status" className="success">{reviewMessage}</p>}{reviewError&&<p role="alert" className="error">{reviewError}</p>}
    </section>}
    {history.length>0&&<section className="evidence-review-history" aria-label="Field review history"><h3>Field review history</h3><p>Each event retains its source and extraction revision. Original candidate text remains unchanged.</p><ol>{history.map(review=><li key={review.id}><div><strong>{decisionLabel(review.data.decision)} · {review.data.field}</strong><span>{review.data.author_username} · {new Date(review.data.recorded_at).toLocaleString()}</span></div>{review.data.reviewed_value!==null&&<p>Reviewed value: <strong>{review.data.reviewed_value}</strong></p>}<p>{review.data.reason}</p><small>Document revision {review.data.document_revision} · extraction revision {review.data.job_revision}</small></li>)}</ol></section>}
    <details className="evidence-provenance"><summary>Source provenance</summary><dl><dt>Document ID</dt><dd>{source.document_id}</dd><dt>SHA-256</dt><dd>{source.sha256}</dd><dt>Parser</dt><dd>{source.parser}</dd>{job&&<><dt>Processing record</dt><dd>{job.id} · revision {job.revision}</dd></>}</dl><p>Viewing these fields records no review decision. Formal approval remains in its existing workflow.</p></details>
  </section>;
}
