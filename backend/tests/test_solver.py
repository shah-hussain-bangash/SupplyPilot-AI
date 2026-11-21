"""Small exact enumeration is independent of the CP-SAT implementation."""
from copy import deepcopy
from decimal import Decimal
import pytest
from supplypilot.db import Session,Record

@pytest.mark.parametrize('need',[3,5,8,9,10,12,15])
def test_pack_moq_and_fixed_cost_against_exact_reference(api,need):
    api.ready()
    with Session.begin() as db:
        stock=db.get(Record,'stock-demo');sd=deepcopy(stock.data);sd.update(usable=0,reserved=0,inbound=[]);stock.data=sd
        rfq=db.get(Record,'rfq-demo');rd=deepcopy(rfq.data);rd['lines'][0]['quantity']=need;rfq.data=rd
        for sid,cap,price,fixed,pack,moq in [('gulf',8,'4.00','8.00',2,2),('desert',10,'5.00','0.00',1,1)]:
            r=db.get(Record,'offer-'+sid);d=deepcopy(r.data);d.update(quantity=cap,unit_price=price,freight_per_piece='0.00',fixed_freight=fixed,pack_size=pack,moq=moq);r.data=d
    p=api.post('/plans',{'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'1000.00'},status=201)
    costs=[]
    for gulf in range(9):
        for desert in range(11):
            if gulf+desert!=need or (gulf and (gulf<2 or gulf%2)):continue
            costs.append(Decimal(gulf*4+desert*5+(8 if gulf else 0)))
    assert Decimal(p['data']['payload']['total'])==min(costs)
    assert p['data']['payload']['solver']['status']=='OPTIMAL'

def test_infeasible_pack_constraint(api):
    api.ready()
    with Session.begin() as db:
        stock=db.get(Record,'stock-demo');d=deepcopy(stock.data);d.update(usable=0,reserved=0,inbound=[]);stock.data=d
        rfq=db.get(Record,'rfq-demo');d=deepcopy(rfq.data);d['lines'][0]['quantity']=5;rfq.data=d
        for sid in ('gulf','desert'):
            r=db.get(Record,'offer-'+sid);d=deepcopy(r.data);d['pack_size']=2;r.data=d
    api.post('/plans',{'rfq_id':'rfq-demo','expected_revision':1,'objective':'cost','budget':'10000.00'},status=422)
