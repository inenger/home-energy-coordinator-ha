"""Versioned canonical SOC decision envelope; never rewrites legacy evidence."""
from .core import digest

HASH_SCHEMA='soc-decision-canonical-v2'


def seal(decision):
    out={k:v for k,v in decision.items() if k!='decision_hash'}
    out['decision_hash_schema']=HASH_SCHEMA
    out['decision_hash']=digest(out)
    return out


def verify(decision):
    if decision.get('decision_hash_schema')!=HASH_SCHEMA:
        return {'status':'legacy_unversioned_hash','verified':False}
    expected=digest({k:v for k,v in decision.items() if k!='decision_hash'})
    ok=decision.get('decision_hash')==expected
    return {'status':'verified' if ok else 'hash_mismatch','verified':ok}
