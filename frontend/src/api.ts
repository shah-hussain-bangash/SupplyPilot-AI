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
