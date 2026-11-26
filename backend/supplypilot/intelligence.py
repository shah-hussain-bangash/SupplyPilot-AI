"""Bounded LangGraph processing and transparent, evaluable decision baselines."""
import re
from typing import TypedDict
from statistics import mean
from langgraph.graph import StateGraph, START, END

class ExtractionState(TypedDict):
    pages: list[str]
    candidates: list[dict]
    flags: list[str]

def extract(state):
    candidates=[]
    for page, text in enumerate(state['pages'], 1):
        for match in re.finditer(r'(?i)\b(quantity|qty|grade|standard|sku)\s*[:=]\s*([^\n;]{1,100})', text):
            candidates.append({'field': match[1].lower(), 'raw': match[2].strip(), 'normalized': match[2].strip(), 'page': page, 'start': match.start(2), 'end': match.end(2), 'reviewed': False})
    return {'candidates': candidates}

def flag(state):
    return {'flags': ['Human review required', 'Text-offset anchors; bounding boxes and OCR are not implemented']}

graph = StateGraph(ExtractionState)
graph.add_node('extract', extract);graph.add_node('review_flags', flag)
graph.add_edge(START, 'extract');graph.add_edge('extract', 'review_flags');graph.add_edge('review_flags', END)
extraction_graph = graph.compile()

def eligibility(requirement, offered, certificate_verified):
    checks={}
    for key, value in requirement.items():
        actual = offered.get(key)
        checks[key] = 'unknown' if not actual else ('compliant' if actual.strip().casefold() == value.strip().casefold() else 'noncompliant')
    checks['certificate'] = 'compliant' if certificate_verified else 'unknown'
    result = 'noncompliant' if 'noncompliant' in checks.values() else ('unknown' if 'unknown' in checks.values() else 'compliant')
    return {'status': result, 'checks': checks, 'rule_version': 'exact-spec-v1'}

def backtest(values):
    # Every rolling prediction uses strictly earlier observations.
    rows=[]
    for i in range(4,len(values)):
        pred=mean(values[max(0,i-4):i]); naive=values[i-1]
        rows.append({'index':i,'actual':values[i],'moving_average':pred,'naive':naive})
    mae=mean(abs(r['actual']-r['moving_average']) for r in rows)
    naive_mae=mean(abs(r['actual']-r['naive']) for r in rows)
    forecast=mean(values[-4:])
    return {'method':'rolling-mean-4 / naive comparison','forecast':forecast,'mae':mae,'naive_mae':naive_mae,'evaluation_rows':rows,'range':[max(0,forecast-2*mae),forecast+2*mae],'range_note':'Heuristic residual range, not a calibrated confidence interval','production_trained_model':False}
