export type Row={id:string;kind:string;revision:number;created_at:string;data:Record<string,any>};
export type Account={id:string;username:string;tenant:string;role:string;supplier_id:string|null};
let token='';
export function setToken(value:string){token=value;}
export async function request(path:string,body?:unknown):Promise<any>{
  const headers:Record<string,string>={};if(token)headers.Authorization='Bearer '+token;
  if(body!==undefined && !(body instanceof FormData))headers['Content-Type']='application/json';
  const res=await fetch('/api/v1'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)});
  const data=await res.json();
  if(!res.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));
  return data;
}


export async function downloadOriginal(source:Row,signal:AbortSignal):Promise<void>{
  const query=new URLSearchParams({expected_revision:String(source.revision),expected_sha256:source.data.sha256});
  const response=await fetch('/api/v1/documents/'+encodeURIComponent(source.id)+'/download?'+query,{headers:{Authorization:'Bearer '+token},signal});
  if(!response.ok){const error=await response.json();throw Error(typeof error.detail==='string'?error.detail:error.detail?.message||'Original source could not be downloaded.');}
  const raw=await response.arrayBuffer();
  if(raw.byteLength>5*1024*1024)throw Error('Original source exceeds the download limit.');
  const digest=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',raw))).map(value=>value.toString(16).padStart(2,'0')).join('');
  if(digest!==source.data.sha256||response.headers.get('X-SupplyPilot-Source-SHA256')!==digest||response.headers.get('X-SupplyPilot-Source-Revision')!==String(source.revision))throw Error('Original source changed or failed its file hash check. Reopen the evidence.');
  if(signal.aborted)throw new DOMException('Download cancelled','AbortError');
  const url=URL.createObjectURL(new Blob([raw],{type:'application/octet-stream'}));
  const link=document.createElement('a');link.href=url;link.download=String(source.data.filename).replace(/[\\/\x00-\x1f]/g,'_');document.body.appendChild(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
