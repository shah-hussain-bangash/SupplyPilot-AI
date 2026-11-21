"""PostgreSQL procurement reads; writes retain their existing transaction path.

Normalized fields come from synchronized tables. Source records retain the API
identity, timestamps, history and extension fields during this gradual cutover.
A missing or stale projection fails closed instead of returning legacy values.
"""
from copy import deepcopy
from fastapi import HTTPException
from sqlalchemy import text


def _ready(db, kind):
    return kind in ('supplier', 'rfq', 'offer', 'order', 'receipt', 'invoice') and db.get_bind().dialect.name == 'postgresql'


def _query(kind, user, single=False):
    # Table names are fixed here; request values are always bound parameters.
    if kind == 'supplier':
        fields = "h.name,h.category,h.approved,h.simulated,NULL::jsonb AS lines,NULL::jsonb AS invited"
        table = 'proc_suppliers'
    elif kind == 'receipt':
        fields = """h.order_id,h.allocation_index,h.expected_order_revision AS expected_revision,
          h.supplier_id,h.sku,h.accepted,h.rejected,h.quarantine,h.evidence_id,h.received_at AS at"""
        table = 'proc_receipts'
    elif kind == 'invoice':
        fields = """h.order_id,h.allocation_index,h.expected_order_revision AS expected_revision,
          h.supplier_id,h.invoice_number,h.quantity,h.unit_price::text AS unit_price,
          h.evidence_id,h.status,h.tolerance,h.match_checks,h.assessment_history,
          h.rechecked_by,h.recheck_reason,h.rechecked_at"""
        table = 'proc_invoices'
    elif kind == 'order':
        fields = """h.rfq_id,h.plan_id,h.intent_id,h.external_id,h.status,
          h.total::text AS total,h.currency,h.simulated,h.closed_at,
          (SELECT COALESCE(jsonb_agg(l.approved_snapshot || jsonb_build_object(
            'offer_id',l.offer_id,'offer_revision',l.offer_revision,
            'supplier_id',l.supplier_id,'sku',l.sku,'quantity',l.quantity,'unit',l.unit,
            'unit_price',l.unit_price::text,'freight_per_piece',l.freight_per_piece::text,
            'line_total',l.line_total::text,'received',l.received,'accepted',l.accepted,
            'rejected',l.rejected,'quarantine',l.quarantine) ||
            CASE WHEN l.approved_snapshot ? 'fixed_freight'
              THEN jsonb_build_object('fixed_freight',l.fixed_freight::text)
              ELSE '{}'::jsonb END ORDER BY l.line_index),'[]'::jsonb)
           FROM public.proc_order_lines l WHERE l.tenant=r.tenant AND l.order_id=r.id) AS lines"""
        table = 'proc_orders'
    elif kind == 'offer':
        fields = """h.rfq_id,h.supplier_id,h.sku,h.quantity,h.unit,
          h.unit_price::text AS unit_price,h.freight_per_piece::text AS freight_per_piece,
          h.fixed_freight::text AS fixed_freight,h.moq,h.pack_size,h.currency,
          h.valid_until,h.delivery_date,h.specs,h.evidence_id,h.recipient,h.terms,h.status,
          h.compliance,h.compliance_revision,h.technical_reviewer,h.assessment_reason"""
        table = 'proc_offers'
    else:
        fields = """h.title,h.due_date,h.status,h.owner_id,h.reviewer_id,
          (SELECT COALESCE(jsonb_agg(jsonb_build_object('sku',l.sku,'quantity',l.quantity,
             'unit',l.unit,'specs',l.specs,'evidence_id',l.evidence_id) ORDER BY l.line_index),'[]'::jsonb)
           FROM public.proc_rfq_lines l WHERE l.tenant=r.tenant AND l.rfq_id=r.id) AS lines,
          (SELECT COALESCE(jsonb_agg(i.supplier_id ORDER BY i.supplier_id),'[]'::jsonb)
           FROM public.proc_rfq_invitations i WHERE i.tenant=r.tenant AND i.rfq_id=r.id) AS invited"""
        table = 'proc_rfqs'
    visibility = ''
    if user.role == 'supplier' and kind == 'offer':
        visibility = " AND r.data->>'supplier_id'=:supplier_id AND h.supplier_id=:supplier_id"
    elif user.role == 'supplier':
        visibility = (' AND false' if kind in ('supplier','order','receipt','invoice') else """ AND EXISTS
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
    elif row['kind'] == 'receipt':
        for key in ('order_id','allocation_index','expected_revision','supplier_id','sku',
                    'accepted','rejected','quarantine','evidence_id'):
            field(key,deepcopy(row[key]))
        value=row['at']
        field('at',value.isoformat() if hasattr(value,'isoformat') else value)
    elif row['kind'] == 'invoice':
        for key in ('order_id','allocation_index','expected_revision','supplier_id','invoice_number',
                    'quantity','unit_price','evidence_id','status','tolerance','match_checks'):
            field(key,deepcopy(row[key]))
        # Older invoices omitted these optional fields and the empty history default.
        for key in ('assessment_history','rechecked_by','recheck_reason','rechecked_at'):
            if key in data:
                value=deepcopy(row[key])
                data[key]=value.isoformat() if hasattr(value,'isoformat') else value
    elif row['kind'] == 'order':
        if len(row['lines']) != len(data.get('lines', [])):
            raise HTTPException(503, {'code':'projection_not_ready',
                'message':'Procurement order lines are missing; contact support'})
        for key in ('rfq_id','plan_id','intent_id','external_id','status','total','currency','simulated'):
            field(key,row[key])
        if 'closed_at' in data or row['closed_at'] is not None:
            value=row['closed_at']
            data['closed_at']=value.isoformat() if hasattr(value,'isoformat') else value
        data['lines']=deepcopy(row['lines'])
    elif row['kind'] == 'offer':
        required=('rfq_id','supplier_id','sku','quantity','unit','unit_price',
                  'freight_per_piece','currency','specs','evidence_id','recipient','terms','status','compliance')
        for key in required:field(key,row[key])
        for key in ('valid_until','delivery_date'):
            value=row[key]
            field(key,value.isoformat() if hasattr(value,'isoformat') else value)
        # Legacy offers omitted these defaults. Keep that wire contract while
        # reading present fields from the normalized quotation projection.
        for key in ('fixed_freight','moq','pack_size','compliance_revision',
                    'technical_reviewer','assessment_reason'):
            if key in data:data[key]=row[key]
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
    if kind not in ('supplier','rfq','offer','order','receipt','invoice'):return None
    params={'tenant':user.tenant,'kind':kind,'supplier_id':user.supplier_id,'rid':rid}
    row=db.execute(text(_query(kind,user,True)),params).mappings().one_or_none()
    if row is None:raise HTTPException(404,{'code':'not_found','message':'Resource unavailable'})
    return _view(row,user)
