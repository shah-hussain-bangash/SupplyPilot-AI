export type Anchor = {page:number; start:number; end:number};

export function currentFieldReview(reviews:any[],binding:{jobId:string;jobRevision:number;documentRevision:number;sha256:string},index:number,candidate:any):any|null {
  return reviews.filter(review=>{
    const data=review?.data;
    return data?.job_id===binding.jobId&&data.job_revision===binding.jobRevision&&
      data.document_revision===binding.documentRevision&&data.source_sha256===binding.sha256&&
      data.candidate_index===index&&['field','raw','normalized','page','start','end'].every(key=>data.candidate_snapshot?.[key]===candidate?.[key]);
  }).sort((a,b)=>new Date(b.created_at).getTime()-new Date(a.created_at).getTime()||b.id.localeCompare(a.id))[0]||null;
}

// Highlight only offsets that match both the processing snapshot and the
// currently authorized source response. Never search for a replacement match.
export function candidateAnchor(candidate:any, pages:string[], processedPages:unknown):Anchor|null {
  if(!Array.isArray(processedPages) || processedPages.length!==pages.length ||
     !processedPages.every((text,index)=>typeof text==='string' && text===pages[index]))return null;
  const {page,start,end,raw}=candidate||{};
  if(!Number.isInteger(page)||page<1||page>pages.length||!Number.isInteger(start)||
     !Number.isInteger(end)||start<0||end<=start||typeof raw!=='string')return null;
  // API offsets count Python Unicode code points; DOM strings use UTF-16.
  const characters=Array.from(pages[page-1]);
  if(end>characters.length||characters.slice(start,end).join('')!==raw)return null;
  return {page,start:characters.slice(0,start).join('').length,end:characters.slice(0,end).join('').length};
}
