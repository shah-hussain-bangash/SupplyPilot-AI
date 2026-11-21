"""Optional Celery scanner. PostgreSQL row claim + provider key guard duplicate deliveries."""
import os
from celery import Celery
from sqlalchemy import select
from .db import Session, Outbox, User, bind_tenant
from .integrations import process

celery=Celery('supplypilot',broker=os.getenv('REDIS_URL','redis://localhost:6379/0'))
celery.conf.update(task_serializer='json',accept_content=['json'],result_serializer='json',task_acks_late=True,worker_prefetch_multiplier=1,beat_schedule={'outbox-scan':{'task':'supplypilot.scan','schedule':10.0}})

@celery.task(name='supplypilot.scan')
def scan():
    tenants=[t.strip() for t in os.getenv('WORKER_TENANTS','').split(',') if t.strip()]
    if not tenants:raise RuntimeError('Configure WORKER_TENANTS explicitly for the background scanner')
    total=0
    for tenant in dict.fromkeys(tenants):
        with Session() as db:
            bind_tenant(db,tenant)
            pending=[(r.id,r.tenant) for r in db.scalars(select(Outbox).where(Outbox.state=='pending').limit(50))]
            for iid,scope in pending:
                owner=db.scalar(select(User).where(User.tenant==scope,User.role=='buyer',User.active==1))
                if owner:dispatch.delay(iid,scope,owner.id)
            total+=len(pending)
    return total

@celery.task(name='supplypilot.dispatch',autoretry_for=(),acks_late=True)
def dispatch(iid,tenant,actor_id):
    # Processing/uncertain intents require explicit reconciliation, never blind redelivery.
    return process(iid,tenant,actor_id)
