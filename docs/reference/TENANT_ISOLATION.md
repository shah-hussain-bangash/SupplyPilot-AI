# Tenant isolation: development milestone

Revision 0002_tenant_rls enables and forces RLS on users, records, audit and outbox. Runtime queries without transaction-local supplypilot.tenant see no tenant rows. USING and WITH CHECK protect reads and writes. The migration owner retains an explicit administration policy.

The application resolves one active identity through a SECURITY DEFINER function returning only its tenant. The function uses a fixed search path, qualified table reference and restricted EXECUTE grant. Identity is authenticated in the application; callers cannot supply a tenant header to override it. Supplier visibility and business roles remain application-enforced.

TenantSession sets a transaction-local value at each PostgreSQL transaction start, including after intermediate commits. bind_tenant forbids tenant switching within an ORM session. Dedicated execution sessions bind their tenant before reading. The Celery scanner requires WORKER_TENANTS and scans one tenant per session; its queue is a trusted internal boundary. The local launcher configures the two synthetic tenants explicitly.

This shared-runtime-role design assumes trusted application code. A holder of runtime database credentials can set the custom tenant variable; RLS is defense against missing filters/context leakage, not against arbitrary SQL injection or credential compromise. Migration/database administrator credentials are privileged. Audit storage is not tamper-proof against those administrators. Stronger identity attestation, production SSO and a dedicated worker identity remain separate work.

Install source while the server is stopped; apply Alembic upgrade head with the migrator; verify all four policies; restart using scripts/start_postgres_dev.py. No source data, passwords, documents, simulator state or baseline migration is overwritten by this patch.

64 existing backend regression tests passed before packaging. The user-run PostgreSQL rehearsal passed 37 checks against supplypilot_rls_test_f2d71bf1ee48. It exercised compiled migration SQL and staged runtime code. Applying through Alembic on supplypilot_dev is the next verification. No production or full adversarial security certification is claimed.
