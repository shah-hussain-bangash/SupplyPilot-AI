# Security boundary and open controls

Local mode is a development reference. Passwords use salted PBKDF2-HMAC-SHA256 with 600,000 iterations. Tokens expire after 30 minutes; no secret or password is embedded in the delivered source. An unset local token secret is randomized per process, so restart invalidates local tokens. Persist a unique environment secret for a stable local installation. Production mode requires PostgreSQL and configured OIDC, but that startup guard is not production acceptance.

OIDC verification accepts RS256 only, validates issuer, audience, expiry and subject, and maps the verified subject to a preprovisioned active `users.id`. No self-signup or role claims from the UI are trusted. SSO provisioning, revocation, group synchronization and real identity-provider tests remain open. The local login limiter is per-process, not distributed abuse protection.

Every record route scopes by persisted tenant. Supplier reads are narrowed to own offers/documents and invited RFQs; RFQ internal fields and evidence IDs are removed from supplier views. Search is internal-only and tenant-filtered before text is returned. Buyers cannot approve; administrators cannot buy solely through admin status; receipt and invoice mutations have separate roles. Current scope is tenant-wide internal access: category/site/entity policies remain required.

PDF uploads validate extension, signature and bounded size/page count. Failed/no-text input is quarantined. Unsupported images/Office files are rejected, not pretended processed. There is no antivirus service or parser process sandbox yet. Private local storage must be replaced with managed private object storage, lifecycle and quarantine policies. The API does not provide quarantined downloads.

Audit entries are appended through the application, with server actor/time and revision events. They are not WORM or externally signed; a privileged database operator can change them. Database least privilege, RLS, protected audit export/storage, record deletion, retention, data residency and disaster recovery remain unvalidated.

The private model gateway is disabled by default. No source is sent automatically. An approved HTTPS endpoint and token must be explicitly configured. Model candidates need quotes that occur on their cited pages; they cannot change business records or call tools. This does not prove a suggested value is correct: human review remains mandatory.

Before any enterprise pilot: independent access review, malicious-file and prompt-injection suite, secret management/rotation, dependency and license audit, deployment hardening, egress restrictions, encrypted transport/storage, incident ownership, backups and tested reconciliation. No security certification is claimed.
