import React,{useState} from 'react';
import type {Row} from './api';

export function PortalIcon({name,size=24}:{name:string;size?:number}){
 const paths:Record<string,React.ReactNode>={
  Overview:<><path d="m3 10 9-7 9 7v10H3Z"/><path d="M9 20v-7h6v7"/></>,
  document:<><path d="M5 3h9l5 5v13H5Z"/><path d="M14 3v6h5M8 12h8M8 16h6"/></>,
  shield:<><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/></>,
  Suppliers:<><circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 4a3 3 0 0 1 0 6M18 14c3 1 3 4 3 7"/></>,
  layers:<><path d="m12 3 10 5-10 5L2 8ZM2 12l10 5 10-5M2 16l10 5 10-5"/></>,
  box:<><path d="m12 3 9 5v9l-9 5-9-5V8ZM3 8l9 5 9-5M12 13v9M7 5l9 5"/></>,
  Sourcing:<><circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/></>,
  check:<><circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/></>,
  cart:<><path d="M2 3h3l3 13h11l3-9H6"/><circle cx="9" cy="21" r="1"/><circle cx="19" cy="21" r="1"/></>,
  Receiving:<><path d="M2 5h12v13H2ZM14 10h5l3 4v4h-8"/><circle cx="6" cy="19" r="2"/><circle cx="18" cy="19" r="2"/></>,
  Invoices:<><path d="M5 2h14v20l-3-2-4 2-4-2-3 2Z"/><path d="M8 7h8M8 11h8M8 15h5"/></>,
  warning:<><path d="m12 3 10 18H2Z"/><path d="M12 9v5M12 17h.01"/></>,
  chat:<path d="M21 11a9 9 0 0 1-9 9H4l-2 2v-11a9 9 0 1 1 19 0Z"/>,
  search:<><circle cx="10" cy="10" r="7"/><path d="m15 15 7 7"/></>,
  network:<><circle cx="12" cy="4" r="3"/><circle cx="4" cy="20" r="3"/><circle cx="20" cy="20" r="3"/><path d="M12 7v5L4 17M12 12l8 5"/></>,
  eye:<><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></>,
  arrow:<path d="M4 12h16m-6-6 6 6-6 6"/>,
  pin:<><path d="M19 10c0 5-7 12-7 12S5 15 5 10a7 7 0 0 1 14 0Z"/><circle cx="12" cy="10" r="2"/></>,
  screen:<><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></>,
 };
 const alias:Record<string,string>={RFQs:'document',Documents:'document',Compliance:'shield',Quotations:'layers',Inventory:'box',Approvals:'check','Purchase orders':'cart',Exceptions:'warning','Supplier portal':'Suppliers',Forecasts:'layers','Customer quotes':'chat',Feedback:'chat',Audit:'shield'};
 return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{paths[alias[name]||name]||paths.document}</svg>;
}

type LoginProps={username:string;password:string;oidc:string;busy:boolean;error:string;setUsername:(s:string)=>void;setPassword:(s:string)=>void;setOidc:(s:string)=>void;onSignIn:()=>void;onHome:()=>void};
export function PortalLogin(props:LoginProps){
 const [showPassword,setShowPassword]=useState(false);
 return <div className="portal-signin"><a className="portal-skip" href="#signin-form">Skip to sign in</a><div className="signin-layout">
  <section className="signin-story" aria-label="SupplyPilot AI procurement workspace">
   <button className="portal-brand" onClick={props.onHome} aria-label="SupplyPilot AI website"><span className="portal-monogram">SP</span><span>SupplyPilot AI</span></button>
   <div className="signin-message"><h1>Procurement<br/>with confidence.</h1><p>Evidence. Approval. Traceable execution.</p></div>
   <p className="signin-location"><PortalIcon name="pin" size={30}/>Local simulation environment</p>
  </section>
  <main className="signin-content" id="signin-form"><div className="signin-card">
   <span className="signin-eyebrow">Procurement workspace</span><h2>Welcome back</h2><p className="signin-subtitle">Sign in to your workspace</p>
   <form onSubmit={e=>{e.preventDefault();props.onSignIn()}} aria-label="Sign in">
    <label htmlFor="portal-username">Username</label><input id="portal-username" autoComplete="username" required={!props.oidc} value={props.username} onChange={e=>props.setUsername(e.target.value)} disabled={props.busy}/>
    <label htmlFor="portal-password">Password</label><div className="signin-password"><input id="portal-password" type={showPassword?'text':'password'} autoComplete="current-password" required={!props.oidc} value={props.password} onChange={e=>props.setPassword(e.target.value)} disabled={props.busy}/><button type="button" aria-label={showPassword?'Hide password':'Show password'} aria-pressed={showPassword} onClick={()=>setShowPassword(!showPassword)}><PortalIcon name="eye"/></button></div>
    {props.error&&<div role="alert" className="signin-error">{props.error}</div>}
    <button className="signin-submit" type="submit" disabled={props.busy}>{props.busy?'Signing in…':'Sign in'}<PortalIcon name="arrow"/></button>
    <details className="signin-advanced"><summary>Enterprise identity access</summary><p>Use an access token only when your organization has configured its identity provider.</p><label htmlFor="portal-token">OIDC access token</label><textarea id="portal-token" autoComplete="off" value={props.oidc} onChange={e=>props.setOidc(e.target.value)} disabled={props.busy}/></details>
   </form>
   <div className="signin-help"><PortalIcon name="shield" size={28}/><p>Use your assigned account. Your role determines access.</p></div>
   <div className="signin-environment"><PortalIcon name="warning" size={28}/><p><strong>Local simulation</strong><span>No live ERP, email or payments.</span></p></div>
   <p className="signin-footer">SupplyPilot AI · Procurement workspace</p><button className="signin-home" onClick={props.onHome}>← Back to website</button>
  </div></main>
 </div></div>;
}

export function PortalNavigation({screens,page,onNavigate}:{screens:string[];page:string;onNavigate:(s:string)=>void}){
 const [expanded,setExpanded]=useState(false);
 const groups:[string,string[]][]=[['Workspace',['Overview','RFQs','Documents','Compliance','Suppliers','Quotations','Inventory']],['Purchasing',['Sourcing','Approvals','Purchase orders','Receiving','Invoices','Exceptions','Supplier portal']],['Commercial',['Customer quotes']],['Insights & governance',['Forecasts','Feedback','Audit']]];
 return <aside className="portal-sidebar"><div className="portal-brand"><span className="portal-monogram">SP</span><span>SupplyPilot AI</span></div><button className="portal-menu-toggle" aria-expanded={expanded} aria-controls="portal-navigation" onClick={()=>setExpanded(!expanded)}>Menu <span aria-hidden="true">☰</span></button><nav id="portal-navigation" className={expanded?'is-expanded':''} aria-label="Workspace navigation">{groups.map(([label,items])=>{const permitted=items.filter(x=>screens.includes(x));return permitted.length>0&&<div className="portal-nav-group" key={label}><p>{label}</p>{permitted.map(name=><button key={name} className={name===page?'active':''} aria-current={name===page?'page':undefined} onClick={()=>{onNavigate(name);setExpanded(false)}}><PortalIcon name={name}/><span>{name}</span></button>)}</div>})}</nav><div className="side-bottom"><PortalIcon name="screen"/>Local simulation</div></aside>;
}

const pageStories:Record<string,{image:string;category:string;description:string}>={
 RFQs:{image:'v4-rfq.webp',category:'Requirements',description:'Turn source requirements into clear, reviewed requests for quotation.'},
 Documents:{image:'v4-rfq.webp',category:'Source evidence',description:'Keep original documents, extracted facts and review decisions together.'},
 Compliance:{image:'v4-compliance.webp',category:'Technical review',description:'Review the evidence behind each material specification before commitment.'},
 Suppliers:{image:'supplypilot-supplier-collaboration.webp',category:'Supplier workspace',description:'Understand your supplier records and maintain clear sourcing relationships.'},
 Quotations:{image:'v4-sourcing.webp',category:'Commercial offers',description:'Compare supplier capacity, pricing, delivery and supporting evidence.'},
 Inventory:{image:'supplypilot-warehouse-team.webp',category:'Supply visibility',description:'See usable stock, reservations and confirmed inbound deliveries in context.'},
 Sourcing:{image:'v4-sourcing.webp',category:'Decision workspace',description:'Compare cost and delivery scenarios against reviewed requirements.'},
 Approvals:{image:'v4-approval.webp',category:'Controlled commitment',description:'Review the exact sourcing decision, evidence and budget before approval.'},
 'Purchase orders':{image:'v4-distribution.webp',category:'Purchasing',description:'Follow approved plans through simulator dispatch, reconciliation and fulfillment.'},
 Receiving:{image:'v4-receiving.webp',category:'Inspection & receiving',description:'Record accepted, rejected and quarantined material against the order.'},
 Invoices:{image:'v4-approval.webp',category:'Finance workspace',description:'Match material prices and accepted quantities, with clear exception history.'},
 Exceptions:{image:'v4-compliance.webp',category:'Resolution workspace',description:'Give each issue an owner, supporting evidence and a traceable resolution.'},
 'Supplier portal':{image:'v4-supplier-hero.webp',category:'Supplier access',description:'Respond to your invitations and manage your own supporting documents.'},
 Forecasts:{image:'v4-sourcing.webp',category:'Planning insights',description:'Explore demand baselines while keeping assumptions and evaluation limits visible.'},
 'Customer quotes':{image:'supplypilot-supplier-collaboration.webp',category:'Commercial scenarios',description:'Review draft contribution and margin before a separate commercial decision.'},
 Feedback:{image:'supplypilot-warehouse-team.webp',category:'Reviewed improvement',description:'Capture corrections for expert review without automatically changing models.'},
 Audit:{image:'v4-about.webp',category:'Governance',description:'Follow the server-recorded actions and decisions within your permitted scope.'},
};

export function PortalPageHeader({page,busy,canCreate,onCreate,onRefresh}:{page:string;busy:boolean;canCreate:boolean;onCreate:()=>void;onRefresh:()=>void}){
 const story=pageStories[page];
 if(page==='Overview')return <div className="page-heading portal-hero"><div><p className="portal-hero-kicker">Your procurement workspace</p><h1 aria-label={page}>Procurement overview</h1><p>Your sourcing, purchasing and fulfillment workspace.</p></div><div className="portal-heading-actions">{canCreate&&<button className="portal-create-rfq" onClick={onCreate}><span aria-hidden="true">＋</span>Create RFQ</button>}<button className="quiet" disabled={busy} onClick={onRefresh}>Refresh</button></div></div>;
 return <section className="portal-page-banner" aria-label={page+' introduction'}><div className="portal-page-intro"><p className="portal-page-kicker"><PortalIcon name={page} size={18}/>{story?.category||'Procurement workspace'}</p><h1>{page}</h1><p className="portal-page-description">{story?.description}</p><button className="quiet" disabled={busy} onClick={onRefresh}>Refresh</button></div><div className="portal-page-image"><img src={'/images/'+(story?.image||'portal-warehouse-banner.webp')} alt="" width="640" height="360"/><span>Workspace illustration</span></div></section>;
}

type OverviewProps={data:Record<string,Row[]>;metrics:any;onNavigate:(s:string)=>void;onInspect:(r:Row)=>void};
export function PortalOverview({data,metrics,onNavigate,onInspect}:OverviewProps){
 const orders=data.order||[],order=orders[0],lines=order?.data.lines||[];
 const accepted=lines.reduce((sum:number,line:any)=>sum+Number(line.accepted||0),0);
 const rejected=lines.reduce((sum:number,line:any)=>sum+Number(line.rejected||0),0);
 const matched=(data.invoice||[]).filter(x=>x.data.order_id===order?.id&&x.data.status==='matched').length;
 const money=(value:unknown)=>new Intl.NumberFormat('en-AE',{style:'currency',currency:'AED',minimumFractionDigits:2}).format(Number(value));
 return <div className="portal-overview"><div className="portal-stats">{[['RFQs',(data.rfq||[]).length,'document'],['Purchase orders',metrics?.order_count??orders.length,'cart'],['Closed simulator orders',metrics?.closed_count??orders.filter(x=>x.data.status==='closed').length,'check']].map(([label,value,icon])=><section key={String(label)} className="portal-stat"><span className="portal-stat-icon"><PortalIcon name={String(icon)} size={30}/></span><div><h2>{label}</h2><strong>{value}</strong></div></section>)}</div>
  <div className="portal-overview-grid"><section className="panel portal-order-card"><h2>Purchase orders</h2><p>Synthetic demonstration records</p>{order?<><div className="table-wrap"><table><thead><tr><th>Purchase order</th><th>Total</th><th>Status</th><th>Details</th></tr></thead><tbody>{orders.slice(0,3).map(row=><tr key={row.id}><td><strong>{row.data.external_id||row.id.slice(0,12)}</strong></td><td className="portal-money">{money(row.data.total)}</td><td><span className={'badge '+(row.data.status==='closed'?'good':'')}>{String(row.data.status).replaceAll('_',' ')}</span></td><td><button className="quiet" onClick={()=>onInspect(row)}>View order</button></td></tr>)}</tbody></table></div><div className="portal-fulfillment" aria-label="Latest order fulfillment"><div><PortalIcon name="check"/><span>Accepted<strong>{accepted} pieces</strong></span></div><div><PortalIcon name="Invoices"/><span>Matched invoices<strong>{matched}</strong></span></div><div><PortalIcon name="warning"/><span>Rejected<strong>{rejected}</strong></span></div></div></>:<div className="portal-empty"><PortalIcon name="cart" size={34}/><h3>No purchase orders yet</h3><p>Start with reviewed evidence and a sourcing plan.</p><button className="quiet" onClick={()=>onNavigate('Sourcing')}>Open sourcing plans</button></div>}</section>
  <section className="panel portal-quick-actions"><h2>Quick actions</h2>{[['Review documents','Documents','v4-rfq.webp','Start with the source'],['Open sourcing plans','Sourcing','v4-sourcing.webp','Compare your options'],['View invoices','Invoices','v4-approval.webp','Follow material matching']].map(([label,target,image,hint])=><button key={label} aria-label={label} onClick={()=>onNavigate(target)}><img src={'/images/'+image} alt="" width="72" height="72" loading="lazy"/><span className="portal-action-copy"><strong>{label}</strong><small>{hint}</small></span><span aria-hidden="true">›</span></button>)}</section></div>
  <section className="panel portal-evidence"><h2>Evidence before commitment</h2><div>{[['1','Review source evidence','search','Documents'],['2','Approve the exact plan','check','Approvals'],['3','Reconcile simulator execution','layers','Purchase orders']].map(([n,label,icon,target])=><button key={n} onClick={()=>onNavigate(target)}><PortalIcon name={icon} size={30}/><span><b>{n}</b> {label}</span><span aria-hidden="true">→</span></button>)}</div></section>
  <p className="portal-overview-disclosure">Demonstration data · Human review remains required</p>
 </div>;
}
