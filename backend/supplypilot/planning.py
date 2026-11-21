from copy import deepcopy
from datetime import date
from decimal import Decimal
from ortools.sat.python import cp_model
from .domain import fail, age_seconds, digest

def money(v):
    return Decimal(str(v)).quantize(Decimal('0.01'))

def availability(stock, due_date):
    if age_seconds(stock['as_of']) > 3600:
        fail('stale_inventory', 'Inventory snapshot is older than one hour')
    inbound=sum(x['quantity'] for x in stock.get('inbound',[]) if x['confirmed'] and x['date']<=due_date)
    return max(0,stock['usable']-stock['reserved']+inbound)

def generate(rfq, stocks, offers, objective, budget):
    allocations=[];shortages={};stock_refs={};candidates=[]
    for line in rfq.data['lines']:
        sku=line['sku'];stock=stocks.get(sku)
        avail=availability(stock.data,rfq.data['due_date']) if stock else 0
        if stock: stock_refs[stock.id]=stock.revision
        need=max(0,line['quantity']-avail);shortages[sku]=need
        candidates.extend(o for o in offers if o.data['sku']==sku and o.data.get('compliance',{}).get('status')=='compliant' and o.data.get('compliance_revision')==rfq.revision and o.data['valid_until']>=date.today().isoformat() and o.data['delivery_date']<=rfq.data['due_date'])
    if len(candidates)>600:fail('solver_input_limit','Limit sourcing to 600 eligible offers per solve',422)
    model=cp_model.CpModel();variables=[];cost_terms=[];delivery_terms=[]
    budget_cents=int(money(budget)*100)
    for offer in sorted(candidates,key=lambda o:(o.data['unit_price'],o.id)):
        d=offer.data;unit_cents=int((money(d['unit_price'])+money(d['freight_per_piece']))*100)
        cap=min(d['quantity'],shortages[d['sku']],budget_cents//unit_cents)
        qty=model.new_int_var(0,cap,'q_'+offer.id);selected=model.new_bool_var('selected_'+offer.id)
        model.add(qty<=cap*selected);model.add(qty>=d.get('moq',1)*selected)
        pack=d.get('pack_size',1);lots=model.new_int_var(0,cap//pack,'lots_'+offer.id);model.add(qty==pack*lots)
        cost_terms.append(qty*unit_cents+selected*int(money(d.get('fixed_freight','0'))*100))
        delivery_terms.append(qty*date.fromisoformat(d['delivery_date']).toordinal())
        variables.append((offer,qty))
    for sku,needed in shortages.items():model.add(sum(q for o,q in variables if o.data['sku']==sku)==needed)
    total_cost=sum(cost_terms);model.add(total_cost<=budget_cents)
    solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=5;solver.parameters.num_search_workers=1
    delivery_optimal=None
    if objective=='delivery':
        delivery=sum(delivery_terms);model.minimize(delivery);result=solver.solve(model)
        if result not in (cp_model.OPTIMAL,cp_model.FEASIBLE):fail('infeasible','No feasible delivery plan within capacity, pack, MOQ, date and budget constraints',422)
        delivery_optimal=result==cp_model.OPTIMAL;model.add(delivery<=int(round(solver.objective_value)))
    model.minimize(total_cost);result=solver.solve(model)
    if result not in (cp_model.OPTIMAL,cp_model.FEASIBLE):fail('infeasible','No feasible sourcing plan within capacity, pack, MOQ, date and budget constraints',422)
    for offer,var in variables:
        qty=solver.value(var)
        if not qty:continue
        d=offer.data;cost=money(d['unit_price'])+money(d['freight_per_piece'])
        allocations.append({'offer_id':offer.id,'offer_revision':offer.revision,'supplier_id':d['supplier_id'],'sku':d['sku'],'specs':deepcopy(d['specs']),'quantity':qty,'unit':d['unit'],'unit_price':d['unit_price'],'freight_per_piece':d['freight_per_piece'],'fixed_freight':str(money(d.get('fixed_freight','0'))),'moq':d.get('moq',1),'pack_size':d.get('pack_size',1),'currency':d['currency'],'delivery_date':d['delivery_date'],'valid_until':d['valid_until'],'recipient':d['recipient'],'terms':d['terms'],'evidence_id':d['evidence_id'],'line_total':str(cost*qty+money(d.get('fixed_freight','0')))})
    allocations.sort(key=lambda a:(money(a['unit_price']),a['offer_id']))
    total=sum((money(x['line_total']) for x in allocations),Decimal('0'))
    if total>money(budget):fail('budget_exceeded','No selected scenario within this budget',422)
    payload={'rfq_id':rfq.id,'rfq_revision':rfq.revision,'title':rfq.data['title'],'objective':objective,'allocations':allocations,'shortages':shortages,'stock_refs':stock_refs,'total':str(total),'currency':'AED','budget':str(budget),'solver':{'engine':'OR-Tools CP-SAT','status':solver.status_name(result),'objective_cents':solver.objective_value,'bound_cents':solver.best_objective_bound,'delivery_optimal':delivery_optimal,'formulation':'integer pieces, exact shortage, eligibility, capacity, MOQ, pack size, linear freight, fixed offer freight and budget'}}
    check_plan(payload,rfq,{o.id:o for o in offers},stocks)
    payload['checker']='independent-invariants-v1'
    return payload

def check_plan(payload,rfq,offers,stocks):
    """Independent validation does not trust the allocator's quantities or totals."""
    if payload['rfq_revision']!=rfq.revision:fail('stale_requirement','Requirements changed')
    needed={l['sku']:max(0,l['quantity']-(availability(stocks[l['sku']].data,rfq.data['due_date']) if l['sku'] in stocks else 0)) for l in rfq.data['lines']}
    used={};by_sku={};total=Decimal('0')
    for a in payload['allocations']:
        o=offers.get(a['offer_id'])
        if not o or o.revision!=a['offer_revision']:fail('stale_offer','Offer changed')
        d=o.data
        if d.get('compliance',{}).get('status')!='compliant' or d.get('compliance_revision')!=rfq.revision:fail('ineligible','Eligibility is not current')
        for key in ('sku','supplier_id','unit_price','freight_per_piece','currency','recipient','terms','evidence_id','specs','unit','delivery_date','valid_until'):
            if a[key]!=d[key]:fail('payload_mismatch',f'Allocation differs from source offer: {key}')
        if d['valid_until']<date.today().isoformat() or d['delivery_date']>rfq.data['due_date']:fail('expired_offer','Offer expired or late')
        qty=a['quantity']
        if not isinstance(qty,int) or qty<=0:fail('invalid_allocation','Invalid allocation quantity')
        used[o.id]=used.get(o.id,0)+qty;by_sku[a['sku']]=by_sku.get(a['sku'],0)+qty
        if used[o.id]>d['quantity']:fail('capacity','Offer capacity exceeded')
        if qty<d.get('moq',1) or qty%d.get('pack_size',1):fail('pack_moq','Pack size or minimum order quantity violated')
        for k in ('moq','pack_size'):
            if a[k]!=d.get(k,1):fail('payload_mismatch','MOQ or pack metadata changed')
        if money(a['fixed_freight'])!=money(d.get('fixed_freight','0')):fail('payload_mismatch','Fixed freight changed')
        line_total=(money(d['unit_price'])+money(d['freight_per_piece']))*qty+money(d.get('fixed_freight','0'))
        if money(a['line_total'])!=line_total:fail('total_mismatch','Line total mismatch')
        total+=line_total
    if any(by_sku.get(sku,0)!=qty for sku,qty in needed.items()) or set(by_sku)-set(needed):fail('shortage_mismatch','Allocation does not cover current shortage')
    if total!=money(payload['total']) or total>money(payload['budget']):fail('total_mismatch','Total or budget check failed')
    return True
