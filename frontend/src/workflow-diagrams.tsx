import React,{useState} from 'react';
import {Icon} from './website';
import './workflow-diagrams.css';

type Diagram='access'|'portal'|'workflow';
const labels:Record<Diagram,string>={access:'1. Registration & access',portal:'2. How the portal works',workflow:'3. Complete project workflow'};
const svgHead=(title:string,desc:string,w:number,h:number)=>`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" role="img" aria-labelledby="diagram-title diagram-description"><title id="diagram-title">${title}</title><desc id="diagram-description">${desc}</desc><defs><marker id="flow-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4.5" orient="auto"><path d="M0 1 L8 4.5 L0 8" fill="none" stroke="#26343c" stroke-width="1.4"/></marker></defs><rect width="100%" height="100%" fill="white"/><g fill="#26343c" font-family="Segoe UI,Arial,sans-serif">`;
const text=(x:number,y:number,value:string,size=14,weight=400,anchor='middle')=>`<text x="${x}" y="${y}" text-anchor="${anchor}" font-size="${size}" font-weight="${weight}">${value.replace(/&/g,'&amp;').replace(/</g,'&lt;')}</text>`;
function wrap(value:string,max:number){const rows:string[]=[];for(const word of value.split(' ')){if(!rows.length||rows[rows.length-1].length+word.length+1>max)rows.push(word);else rows[rows.length-1]+=' '+word}return rows}
function box(x:number,y:number,w:number,h:number,title:string,lines:string[]=[],number?:string){
 const narrow=w<200,titleRows=wrap(title,narrow?23:Math.floor((w-30)/7.4));
 const details=lines.flatMap(l=>wrap(l,narrow?30:Math.floor((w-28)/5.7)));
 return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="#fff" stroke="#26343c" stroke-width="1.5"/>`+(number?text(x+12,y+16,number,9,600,'start'):'')+titleRows.map((l,i)=>text(x+w/2,y+34+i*18,l,narrow?13:15,600)).join('')+details.map((l,i)=>text(x+w/2,y+34+titleRows.length*18+9+i*(narrow?15:20),l,narrow?10.5:12)).join('')
}
const arrow=(points:string,dashed=false)=>`<path d="${points}" fill="none" stroke="#26343c" stroke-width="1.5" ${dashed?'stroke-dasharray="5 5"':''} marker-end="url(#flow-arrow)"/>`;
const note=(x:number,y:number,value:string)=>text(x,y,value,12);
export function diagramSvg(kind:Diagram):string{
 if(kind==='access')return svgHead('Registration and account access','Request access from the project owner. An administrator assigns an account and role. Team members sign in to the team portal. Suppliers also need an RFQ invitation. No public self-registration or automatic approval.',1120,650)+text(560,40,'REGISTRATION & ACCOUNT ACCESS',25,600)+text(560,68,'Current release: administrator-assigned accounts, not public self-registration.',13)+
 box(35,110,235,120,'Contact the project owner',['Share your company, role','and intended business use.'],'01')+arrow('M270 170 H305')+
 box(305,110,235,120,'Account is assigned',['Administrator provisions','the account and its role.'],'02')+arrow('M540 170 H575')+
 box(575,110,235,120,'Receive access details',['Use the assigned username','and the existing setup password.'],'03')+arrow('M810 170 H845')+
 box(845,110,235,120,'Open portal login',['Choose Team or Supplier access.','The server checks permissions.'],'04')+
 arrow('M962 230 V270 H310 V310')+arrow('M962 270 H815 V310')+
 box(150,310,320,130,'Internal team account',['Buyer / Planner / Technical / Manager','Warehouse / Finance / Auditor','Actions depend on the account role.'])+
 box(650,310,330,130,'Supplier account',['Supplier-owned files and quotations','Buyer must invite you to an RFQ.','Other suppliers’ records are excluded.'])+
 arrow('M310 440 V485 H560 V520')+'<path d="M815 440 V485 H560" fill="none" stroke="#26343c" stroke-width="1.5"/>'+
 box(245,520,630,80,'Start the permitted workflow',['New users: request access. Existing users: sign in. Suppliers: confirm your RFQ invitation.'])+
 note(560,630,'Choosing a portal does not create an account, change your role, or place an order.')+'</g></svg>';
 if(kind==='portal'){
 const roles=[['Buyer','RFQs, invitations, quotations','and approved purchasing.'],['Planner','Inventory availability','and sourcing plans.'],['Technical','Specifications, certificate review','and technical exceptions.'],['Manager','Approve or reject sourcing','decisions; review audit records.'],['Warehouse','Record inspected receipts:','accepted, rejected, quarantine.'],['Finance','Review material invoices','against orders and accepted goods.'],['Auditor','Read permitted procurement','records and audit events.'],['Supplier','Invited RFQs, own documents','and own quotations only.']];
 return svgHead('How the role-based portal works','One login leads to account-scoped views and permitted actions. Eight business roles are shown. The server enforces access, not the portal selector.',1120,780)+text(560,40,'HOW THE ROLE-BASED PORTAL WORKS',25,600)+
 box(340,80,440,90,'Sign in with your assigned account',['Username + password → server checks role and permitted scope.'])+
 arrow('M560 170 V205')+box(315,205,490,85,'Your workspace loads the permitted records',['The account decides which records and actions are allowed.'])+
 arrow('M560 290 V325 H170 V355')+arrow('M560 325 H430 V355')+arrow('M560 325 H690 V355')+arrow('M560 325 H950 V355')+
 arrow('M560 325 H30 V493 H170 V510')+arrow('M30 493 H430 V510')+arrow('M430 493 H690 V510')+arrow('M690 493 H950 V510')+
 roles.map(([name,a,b],i)=>box(55+(i%4)*260,355+Math.floor(i/4)*155,235,120,name,[a,b],String(i+1).padStart(2,'0'))).join('')+
 note(560,680,'Internal users may see screens where actions are disabled for their role. Suppliers have a restricted portal.')+
 note(560,706,'Every action still passes through API authorization, validation and revision checks.')+
 note(560,741,'The portal is a business workflow, not a public shopping cart or payment checkout.')+'</g></svg>';
 }
 const stages=[
  {name:'ACCESS',owner:'Project owner + user',nodes:[['Request account access','Share company and role.'],['Account + role assigned','Administrator provisions access.'],['Sign in to the portal','Server checks permissions.']]},
  {name:'REQUIREMENT',owner:'Buyer',nodes:[['Upload source files','RFQ / material specifications'],['Create a draft RFQ','Material, quantity, required date'],['Confirm reviewed needs','Evidence linked to the request.']]},
  {name:'SUPPLIER RESPONSE',owner:'Buyer + supplier',nodes:[['Invite suppliers','Grant access to this RFQ.'],['Supplier uploads evidence','Own supporting documents.'],['Submit a quotation','Price, capacity, dates and terms.']]},
  {name:'REVIEW & APPROVE',owner:'Technical / planner / manager',nodes:[['Check technical compliance','Specifications and certificates.'],['Compare sourcing options','Stock, dates, capacity and cost.'],['Manager approves the plan','Exact version and decision.']]},
  {name:'ORDER & DELIVERY',owner:'Buyer + supplier',nodes:[['Queue the approved order','Approved payload only.'],['Execute in ERP simulator','Reconcile uncertain outcomes.'],['Coordinate physical delivery','Buyer + supplier, externally.']]},
  {name:'RECEIVE & CLOSE',owner:'Warehouse / finance / buyer',nodes:[['Inspect received goods','Accepted / rejected / quarantine'],['Match the material invoice','Order + accepted goods + price'],['Close and retain audit trail','Resolve outstanding differences.']]}
 ];
 return svgHead('Complete SupplyPilot project workflow','Six phases with eighteen ordered steps: administrator-assigned access, reviewed requirement, supplier invitation and quotations, technical review and manager approval, simulated purchasing and externally coordinated delivery, inspected receiving, material invoice matching and closure. Exception and recovery paths are shown below.',1440,880)+text(720,40,'COMPLETE PROJECT WORKFLOW',25,600)+text(720,69,'Follow phases left to right; follow the three numbered steps in each phase from top to bottom.',13)+
 stages.map((stage,i)=>{const x=30+i*235;return `<rect x="${x}" y="105" width="205" height="505" rx="9" fill="#fff" stroke="#26343c" stroke-width="1.2"/>`+text(x+102,139,stage.name,13,600)+text(x+102,163,stage.owner,10)+stage.nodes.map(([title,detail],j)=>box(x+11,194+j*132,183,104,title,[detail],String(i*3+j+1).padStart(2,'0'))+(j<2?arrow(`M${x+102} ${298+j*132} V${326+j*132}`):'')).join('')+(i<5?arrow(`M${x+205} 148 H${x+231}`):'')}).join('')+
 text(720,653,'IF SOMETHING NEEDS ATTENTION',16,600)+
 box(35,683,315,91,'Missing evidence',['Technical exception → supplier clarification.','Reassess the updated evidence.'])+
 box(385,683,315,91,'Rejected or changed decision',['Revise inputs → new sourcing plan.','Obtain approval again.'])+
 box(735,683,315,91,'Uncertain execution',['Reconcile against the simulator first.','Avoid duplicate purchasing actions.'])+
 box(1085,683,315,91,'Receipt or invoice difference',['Record the issue and supporting evidence.','Resolve before closing the case.'])+
 note(720,817,'Across the workflow: role permissions • tenant/supplier scope • evidence and version checks • audit records.')+
 note(720,847,'Local demo: ERP purchasing is simulated. Live transport, carrier tracking and payments are outside this release.')+'</g></svg>';
}
export function WorkflowDiagrams({onPortal}:{onPortal:(account?:string)=>void}){
 const [kind,setKind]=useState<Diagram>('access');
 function download(){const url=URL.createObjectURL(new Blob([diagramSvg(kind)],{type:'image/svg+xml;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='SupplyPilot_'+kind+'_diagram.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 return <section className="wd-section" aria-labelledby="wd-heading"><div className="wd-heading"><div><span className="sw-kicker">START HERE / FOLLOW THE COMPLETE PROCESS</span><h3 id="wd-heading">See the journey as a diagram.</h3></div><p>Start with account access, understand each portal role, then follow the full workflow.</p></div><div className="wd-tabs" role="tablist" aria-label="Project workflow diagrams">{(Object.keys(labels) as Diagram[]).map(key=><button id={'wd-tab-'+key} key={key} role="tab" aria-selected={kind===key} aria-controls="wd-panel" className={kind===key?'selected':''} onClick={()=>setKind(key)}>{labels[key]}<Icon name="arrow" size={15}/></button>)}</div><div className="wd-toolbar"><span>{kind==='access'?'How to get your account and sign in':kind==='portal'?'Who uses each portal and what they can do':'Registration → request → quotation → approval → delivery → closure'}</span><button onClick={download}><Icon name="document" size={16}/>Download diagram (SVG)</button></div><p className="wd-scroll-help">On smaller screens, swipe across the diagram to read each step. Download the SVG for a full-size, printable copy.</p><div className="wd-paper" id="wd-panel" role="tabpanel" aria-labelledby={'wd-tab-'+kind} tabIndex={0}><div className={'wd-canvas '+(kind==='workflow'?'wide':'')} dangerouslySetInnerHTML={{__html:diagramSvg(kind)}}/></div><div className="wd-next"><span>Already have an assigned account?</span><button onClick={()=>onPortal('buyer')}>Team login<Icon name="arrow" size={15}/></button><button onClick={()=>onPortal('supplier-gulf')}>Supplier login<Icon name="arrow" size={15}/></button><a href="#/contact">Need access? Contact the team<Icon name="arrow" size={15}/></a></div></section>
}
