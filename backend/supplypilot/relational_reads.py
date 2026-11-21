"""PostgreSQL supplier/RFQ reads; writes retain their existing transaction path.

Normalized fields come from synchronized tables. Source records retain the API
identity, timestamps, history and extension fields during this gradual cutover.
A missing or stale projection fails closed instead of returning legacy values.
"""
from copy import deepcopy
from fastapi import HTTPException
from sqlalchemy import text


def _ready(db, kind):
    return kind in ('supplier', 'rfq') and db.get_bind().dialect.name == 'postgresql'


def _query(kind, user, single=False):
    # Table names are fixed here; request values are always bound parameters.
    if kind == 'supplier':
        fields = "h.name,h.category,h.approved,h.simulated,NULL::jsonb AS lines,NULL::jsonb AS invited"
        table = 'proc_suppliers'
    else:
        fields = """h.title,h.due_date,h.status,h.owner_id,h.reviewer_id,
          (SELECT COALESCE(jsonb_agg(jsonb_build_object('sku',l.sku,'quantity',l.quantity,
             'unit',l.unit,'specs',l.specs,'evidence_id',l.evidence_id) ORDER BY l.line_index),'[]'::jsonb)
           FROM public.proc_rfq_lines l WHERE l.tenant=r.tenant AND l.rfq_id=r.id) AS lines,
          (SELECT COALESCE(jsonb_agg(i.supplier_id ORDER BY i.supplier_id),'[]'::jsonb)
           FROM public.proc_rfq_invitations i WHERE i.tenant=r.tenant AND i.rfq_id=r.id) AS invited"""
        table = 'proc_rfqs'
    visibility = ''
    if user.role == 'supplier':
        visibility = (' AND false' if kind == 'supplier' else """ AND EXISTS
          (SELECT 1 FROM public.proc_rfq_invitations v WHERE v.tenant=r.tenant
           AND v.rfq_id=r.id AND v.supplier_id=:supplier_id)""")
    return f"""SELECT r.id,r.kind,r.revision,r.created_at,r.updated_at,r.data,
        h.source_revision,{fields}
        FROM public.records r LEFT JOIN public.{table} h ON h.tenant=r.tenant AND h.id=r.id
        WHERE r.tenant=:tenant AND r.kind=:kind {visibility}
        {'AND r.id=:rid' if single else ''}"""


def _view(row, user):
    if row['source_revision'] != row['revision']:
        raise HTTPException(503, {'code':'projection_not_ready',
            'message':'Procurement read data is missing or out of date; contact support'})
    data = deepcopy(row['data'])
    def field(key, value):
        # Preserve absent optional keys to keep the existing JSON contract exact.
        if key in data or value is not None:
            data[key] = value
    if row['kind'] == 'supplier':
        for key in ('name','category','approved','simulated'):
            field(key, row[key])
    else:
        for key in ('title','status'):
            field(key,row[key])
        due=row['due_date']
        field('due_date',due.isoformat() if hasattr(due,'isoformat') else due)
        field('owner',row['owner_id']);field('reviewer',row['reviewer_id'])
        original=data.get('lines',[])
        lines=[]
        for index,line in enumerate(row['lines']):
            entry=deepcopy(original[index]) if index<len(original) else {}
            for key,value in line.items():
                if key in entry or value is not None:entry[key]=value
            lines.append(entry)
        data['lines']=lines
        # Invitation membership comes from the relation; retain the existing
        # presentation order because the API historically exposed source order.
        positions={sid:index for index,sid in enumerate(data.get('invited',[]))}
        data['invited']=sorted(row['invited'],key=lambda sid:(positions.get(sid,len(positions)),sid))
        if user.role=='supplier':
            data={k:data[k] for k in ('title','due_date','lines','status') if k in data}
            for line in data.get('lines',[]):line.pop('evidence_id',None)
    return {k:row[k] for k in ('id','kind','revision','created_at','updated_at')} | {'data':data}


def collection(db,user,kind,offset,limit):
    if not _ready(db,kind):return None
    params={'tenant':user.tenant,'kind':kind,'supplier_id':user.supplier_id,
            'offset':offset,'limit':limit}
    # One SQL snapshot for the total, page, headers, ordered lines and invitations.
    statement='''WITH visible AS MATERIALIZED ('''+_query(kind,user)+''')
        SELECT (SELECT count(*) FROM visible) AS total,
        (SELECT COALESCE(jsonb_agg(to_jsonb(p) ORDER BY p.created_at DESC,p.id),'[]'::jsonb)
         FROM (SELECT * FROM visible ORDER BY created_at DESC,id LIMIT :limit OFFSET :offset) p) AS items'''
    result=db.execute(text(statement),params).mappings().one()
    return {'items':[_view(row,user) for row in result['items']],
            'total':result['total'],'offset':offset,'limit':limit}


def record(db,user,rid):
    if db.get_bind().dialect.name!='postgresql':return None
    kind=db.execute(text('SELECT kind FROM public.records WHERE tenant=:tenant AND id=:rid'),
                    {'tenant':user.tenant,'rid':rid}).scalar_one_or_none()
    if kind not in ('supplier','rfq'):return None
    params={'tenant':user.tenant,'kind':kind,'supplier_id':user.supplier_id,'rid':rid}
    row=db.execute(text(_query(kind,user,True)),params).mappings().one_or_none()
    if row is None:raise HTTPException(404,{'code':'not_found','message':'Resource unavailable'})
    return _view(row,user)
