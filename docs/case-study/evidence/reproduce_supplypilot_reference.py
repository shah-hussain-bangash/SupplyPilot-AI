"""Enumerate the small sourcing reference used by the pinned solver tests.

Standard library only. This does not run CP-SAT, the application, an ERP or a database.
Run: python reproduce_supplypilot_reference.py --output reference.json
"""
import argparse
from datetime import datetime, timezone
import json
import platform
from pathlib import Path

def enumerate_case(need, pack_a=2, pack_b=1):
    feasible = []
    for a in range(9):
        for b in range(11):
            if a + b != need:
                continue
            if a and (a < 2 or a % pack_a):
                continue
            if b and (b < 1 or b % pack_b):
                continue
            cost_cents = 400 * a + 500 * b + (800 if a else 0)
            if cost_cents <= 100000:
                feasible.append({'offer_a_quantity': a, 'offer_b_quantity': b, 'cost_cents': cost_cents})
    if not feasible:
        return {'need': need, 'feasible_allocations': 0, 'minimum_cost_cents': None, 'minimizers': []}
    minimum = min(x['cost_cents'] for x in feasible)
    return {'need': need, 'feasible_allocations': len(feasible), 'minimum_cost_cents': minimum,
            'minimizers': [x for x in feasible if x['cost_cents'] == minimum]}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cases = [enumerate_case(n) for n in [3,5,8,9,10,12,15]]
    infeasible = enumerate_case(5, pack_a=2, pack_b=2)
    assert [r['minimum_cost_cents'] for r in cases] == [1500,2500,4000,4500,5000,6000,7500]
    assert infeasible['minimum_cost_cents'] is None
    report = {
        'source_commit': '8d983bb07fd640bd4c548dff09f28f837992e6d4',
        'source_reference': 'backend/tests/test_solver.py',
        'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
        'environment': {'python': platform.python_version(), 'platform': platform.system()},
        'scope': 'Independent exhaustive enumeration of the committed small test formulation. No application or CP-SAT execution in this local replay.',
        'assumptions': {
            'currency': 'AED', 'unit': 'piece', 'available_stock': 0, 'budget_cents': 100000,
            'offer_a': {'capacity':8, 'unit_price_cents':400, 'fixed_freight_cents':800, 'moq':2, 'pack_size':2},
            'offer_b': {'capacity':10, 'unit_price_cents':500, 'fixed_freight_cents':0, 'moq':1, 'pack_size':1},
            'per_piece_freight_cents':0,
            'eligibility_and_dates': 'Assumed valid as in the prepared solver fixture; not independently evaluated here.'
        },
        'reference_cases': cases,
        'infeasible_even_pack_case': infeasible,
        'worked_comparison': {'need':3, 'lowest_unit_price_first_candidate':{'a':2,'b':1,'cost_cents':2100},
                              'minimum_cost_candidate':{'a':0,'b':3,'cost_cents':1500},
                              'interpretation':'Fixed freight changes the preferred allocation. This is a synthetic arithmetic comparison, not measured procurement savings.'},
        'not_executed':['CP-SAT','Application API','PostgreSQL','Browser','Docker','Live ERP','Live model','Cloud deployment']
    }
    rendered = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered, encoding='utf-8')
    else:
        print(rendered, end='')

if __name__ == '__main__':
    main()
