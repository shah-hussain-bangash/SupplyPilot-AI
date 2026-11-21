"""Prove overlapping API requests serialize in the disposable PostgreSQL suite."""
from concurrent.futures import ThreadPoolExecutor
import time


def build_race(check,sql):
    def race(client,tokens,rid,path,payloads,role,statuses,label,lock_table='records'):
        from sqlalchemy import text
        from supplypilot.db import engine
        if lock_table not in ('records','outbox'):
            raise ValueError('Unexpected concurrency lock table')
        if len(payloads)!=2:
            raise ValueError('Concurrency cases require exactly two requests')
        with ThreadPoolExecutor(max_workers=2) as workers:
            with engine.connect() as blocker:
                blocker.execute(text("SELECT set_config('supplypilot.tenant','demo',true)"))
                locked=blocker.execute(text('SELECT id FROM public.'+lock_table+
                    ' WHERE tenant=:tenant AND id=:rid FOR UPDATE'),{'tenant':'demo','rid':rid}).scalar_one()
                assert locked==rid
                futures=[workers.submit(client.post,'/api/v1'+path,
                         headers=tokens[role],json=payload) for payload in payloads]
                try:
                    deadline=time.monotonic()+10
                    waiting=0
                    while time.monotonic()<deadline:
                        waiting=int(sql('supplypilot_dev',
                            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                            "AND usename='supplypilot_app' AND wait_event_type='Lock'"))
                        if waiting==2:break
                        if any(f.done() for f in futures):break
                        time.sleep(0.05)
                    check(waiting==2,label+' requests overlap at the PostgreSQL row lock')
                finally:
                    # Release the held row before waiting for the request threads.
                    blocker.rollback()
            outcomes=[future.result(timeout=20) for future in futures]
        check(sorted(r.status_code for r in outcomes)==sorted(statuses),
              label+' returns expected statuses '+str(sorted(statuses)))
        for response in outcomes:
            if response.status_code==409:
                check(response.json()['detail']['code']=='revision_conflict',
                      label+' rejects the stale revision explicitly')
        return outcomes
    return race
