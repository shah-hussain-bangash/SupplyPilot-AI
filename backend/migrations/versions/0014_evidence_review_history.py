"""Protect extraction-review history and retain tenant-qualified source links."""
from alembic import op

revision='0014_evidence_review_history'
down_revision='0013_proc_customer_quotes'
branch_labels=None
depends_on=None

SQL=r"""
CREATE TABLE public.proc_evidence_reviews (
    tenant varchar(64) NOT NULL,
    id varchar(64) NOT NULL,
    source_revision integer NOT NULL CHECK(source_revision=1),
    job_id varchar(64) NOT NULL,
    job_revision integer NOT NULL CHECK(job_revision>=1),
    document_id varchar(64) NOT NULL,
    document_revision integer NOT NULL CHECK(document_revision>=1),
    source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
    candidate_index integer NOT NULL CHECK(candidate_index>=0),
    decision text NOT NULL CHECK(decision IN ('accepted','rejected','corrected')),
    author_id varchar(64) NOT NULL,
    author_username text NOT NULL,
    reviewed_value jsonb NOT NULL,
    reason text NOT NULL,
    recorded_at timestamptz NOT NULL CHECK(isfinite(recorded_at)),
    request_key text NOT NULL,
    request_digest text NOT NULL CHECK(request_digest ~ '^[0-9a-f]{64}$'),
    source_snapshot jsonb NOT NULL CHECK(jsonb_typeof(source_snapshot)='object'),
    PRIMARY KEY(tenant,id),
    UNIQUE(tenant,job_id,author_id,request_key),
    FOREIGN KEY(tenant,id) REFERENCES public.records(tenant,id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(tenant,job_id) REFERENCES public.proc_document_jobs(tenant,id) DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY(tenant,document_id) REFERENCES public.proc_documents(tenant,id) DEFERRABLE INITIALLY DEFERRED
);
CREATE INDEX ix_proc_evidence_reviews_source ON public.proc_evidence_reviews(tenant,document_id,job_id,candidate_index);
ALTER TABLE public.proc_evidence_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.proc_evidence_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_scope ON public.proc_evidence_reviews TO supplypilot_app
 USING(tenant=NULLIF(current_setting('supplypilot.tenant',true),''))
 WITH CHECK(tenant=NULLIF(current_setting('supplypilot.tenant',true),''));
CREATE POLICY migration_owner ON public.proc_evidence_reviews TO supplypilot_migrator USING(true) WITH CHECK(true);
REVOKE ALL ON TABLE public.proc_evidence_reviews FROM PUBLIC,supplypilot_app;
GRANT SELECT ON TABLE public.proc_evidence_reviews TO supplypilot_app;
REVOKE TRUNCATE,TRIGGER ON TABLE public.records FROM PUBLIC,supplypilot_app;

CREATE FUNCTION public.validate_evidence_review_snapshot(d jsonb, source_revision integer)
RETURNS void LANGUAGE plpgsql STABLE SET search_path=pg_catalog,pg_temp AS $$
DECLARE key text; candidate jsonb;
BEGIN
 IF jsonb_typeof(d) IS DISTINCT FROM 'object' OR source_revision<>1 THEN
  RAISE EXCEPTION 'Review events require an initial object snapshot' USING ERRCODE='23514';
 END IF;
 FOREACH key IN ARRAY ARRAY['job_id','document_id','source_sha256','field','decision','reason',
   'author','author_username','recorded_at','request_key','request_digest','scope'] LOOP
  IF jsonb_typeof(d->key) IS DISTINCT FROM 'string' OR length(btrim(d->>key))=0 THEN
   RAISE EXCEPTION 'Review event metadata must be nonempty strings' USING ERRCODE='23514';
  END IF;
 END LOOP;
 FOREACH key IN ARRAY ARRAY['job_revision','document_revision','candidate_index'] LOOP
  IF jsonb_typeof(d->key) IS DISTINCT FROM 'number' OR (d->>key)!~'^[0-9]+$' OR
     (d->>key)::numeric>2147483647 OR (key<>'candidate_index' AND (d->>key)::numeric<1) THEN
   RAISE EXCEPTION 'Review source revisions and candidate index must be bounded integers' USING ERRCODE='23514';
  END IF;
 END LOOP;
 IF (d->>'source_sha256')!~'^[0-9a-f]{64}$' OR (d->>'request_digest')!~'^[0-9a-f]{64}$' OR
    (d->>'request_key')!~'^[A-Za-z0-9_-]{8,80}$' OR length(btrim(d->>'reason')) NOT BETWEEN 5 AND 1000 OR
    d->'training_use' IS DISTINCT FROM 'false'::jsonb OR
    d->>'scope'<>'Extraction field review only; not supplier, certificate or purchase approval' THEN
  RAISE EXCEPTION 'Invalid review identity, reason, training flag or authority scope' USING ERRCODE='23514';
 END IF;
 candidate:=d->'candidate_snapshot';
 IF jsonb_typeof(candidate) IS DISTINCT FROM 'object' OR
    jsonb_typeof(candidate->'raw') IS DISTINCT FROM 'string' OR
    jsonb_typeof(candidate->'field') IS DISTINCT FROM 'string' OR
    jsonb_typeof(candidate->'normalized') IS DISTINCT FROM 'string' OR
    candidate->>'field' IS DISTINCT FROM d->>'field' THEN
  RAISE EXCEPTION 'Review event requires its complete extracted candidate' USING ERRCODE='23514';
 END IF;
 FOREACH key IN ARRAY ARRAY['page','start','end'] LOOP
  IF jsonb_typeof(candidate->key) IS DISTINCT FROM 'number' OR (candidate->>key)!~'^[0-9]+$' OR
     (candidate->>key)::numeric>2147483647 THEN
   RAISE EXCEPTION 'Candidate source offsets must be bounded integers' USING ERRCODE='23514';
  END IF;
 END LOOP;
 IF (candidate->>'page')::integer<1 OR (candidate->>'end')::integer<=(candidate->>'start')::integer THEN
  RAISE EXCEPTION 'Invalid candidate source span' USING ERRCODE='23514';
 END IF;
 IF NOT (d ? 'reviewed_value') OR d->>'decision' NOT IN ('accepted','rejected','corrected') OR
    (d->>'decision'='accepted' AND d->'reviewed_value' IS DISTINCT FROM candidate->'normalized') OR
    (d->>'decision'='rejected' AND d->'reviewed_value' IS DISTINCT FROM 'null'::jsonb) OR
    (d->>'decision'='corrected' AND (jsonb_typeof(d->'reviewed_value') IS DISTINCT FROM 'string' OR
       length(btrim(d->>'reviewed_value')) NOT BETWEEN 1 AND 500)) THEN
  RAISE EXCEPTION 'Review decision and reviewed value disagree' USING ERRCODE='23514';
 END IF;
 -- This cast validates finite timestamps without rewriting the stored snapshot.
 IF NOT isfinite((d->>'recorded_at')::timestamptz) THEN
  RAISE EXCEPTION 'Review timestamp must be finite' USING ERRCODE='23514';
 END IF;
END $$;
REVOKE ALL ON FUNCTION public.validate_evidence_review_snapshot(jsonb,integer) FROM PUBLIC,supplypilot_app;

-- Validate existing events, preserving historical source revisions and payloads.
DO $$ DECLARE r record; BEGIN
 FOR r IN SELECT revision,data::jsonb AS data FROM public.records WHERE kind='evidence_review' LOOP
  PERFORM public.validate_evidence_review_snapshot(r.data,r.revision);
 END LOOP;
END $$;
INSERT INTO public.proc_evidence_reviews
 SELECT tenant,id,revision,data->>'job_id',(data->>'job_revision')::integer,
  data->>'document_id',(data->>'document_revision')::integer,data->>'source_sha256',
  (data->>'candidate_index')::integer,data->>'decision',data->>'author',data->>'author_username',
  data::jsonb->'reviewed_value',data->>'reason',(data->>'recorded_at')::timestamptz,
  data->>'request_key',data->>'request_digest',data::jsonb
 FROM public.records WHERE kind='evidence_review';

CREATE FUNCTION public.protect_evidence_review_event()
RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF TG_OP='DELETE' THEN
  IF OLD.kind='evidence_review' THEN
   RAISE EXCEPTION 'Recorded review events cannot be deleted' USING ERRCODE='23514';
  END IF;
  RETURN OLD;
 END IF;
 IF OLD.kind='evidence_review' OR NEW.kind='evidence_review' THEN
  RAISE EXCEPTION 'Recorded review events cannot be edited or converted' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.protect_evidence_review_event() FROM PUBLIC,supplypilot_app;
CREATE TRIGGER records_evidence_review_immutable BEFORE UPDATE OR DELETE ON public.records
 FOR EACH ROW EXECUTE FUNCTION public.protect_evidence_review_event();

CREATE FUNCTION public.store_evidence_review_event()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE d jsonb; j jsonb; doc jsonb; jr integer; dr integer; candidate jsonb; page_text text;
BEGIN
 IF NEW.kind<>'evidence_review' THEN RETURN NEW; END IF;
 d:=NEW.data::jsonb;
 PERFORM public.validate_evidence_review_snapshot(d,NEW.revision);
 SELECT data::jsonb,revision INTO j,jr FROM public.records
  WHERE tenant=NEW.tenant AND id=d->>'job_id' AND kind='job' FOR SHARE;
 SELECT data::jsonb,revision INTO doc,dr FROM public.records
  WHERE tenant=NEW.tenant AND id=d->>'document_id' AND kind='document' FOR SHARE;
 IF j IS NULL OR doc IS NULL OR j->>'document_id' IS DISTINCT FROM d->>'document_id' THEN
  RAISE EXCEPTION 'Review source links must exist in the same tenant' USING ERRCODE='23503';
 END IF;
 IF jr<>(d->>'job_revision')::integer OR dr<>(d->>'document_revision')::integer OR
    doc->>'sha256' IS DISTINCT FROM d->>'source_sha256' OR doc->>'status'<>'review_required' OR
    j->>'state'<>'completed' OR j->'result'->'pages' IS DISTINCT FROM doc->'pages' THEN
  RAISE EXCEPTION 'New review requires the current readable source snapshot' USING ERRCODE='23514';
 END IF;
 candidate:=j->'result'->'candidates'->((d->>'candidate_index')::integer);
 IF candidate IS NULL OR candidate IS DISTINCT FROM d->'candidate_snapshot' THEN
  RAISE EXCEPTION 'New review candidate differs from the extraction' USING ERRCODE='23514';
 END IF;
 page_text:=doc->'pages'->>((candidate->>'page')::integer-1);
 IF page_text IS NULL OR (candidate->>'end')::integer>length(page_text) OR
    substring(page_text FROM (candidate->>'start')::integer+1 FOR
       (candidate->>'end')::integer-(candidate->>'start')::integer) IS DISTINCT FROM candidate->>'raw' THEN
  RAISE EXCEPTION 'New review requires an exact source-text anchor' USING ERRCODE='23514';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.users WHERE tenant=NEW.tenant AND id=d->>'author'
     AND username=d->>'author_username' AND role='technical' AND active=1) THEN
  RAISE EXCEPTION 'New review requires an active technical identity in its tenant' USING ERRCODE='23514';
 END IF;
 INSERT INTO public.proc_evidence_reviews VALUES(NEW.tenant,NEW.id,NEW.revision,d->>'job_id',
  (d->>'job_revision')::integer,d->>'document_id',(d->>'document_revision')::integer,d->>'source_sha256',
  (d->>'candidate_index')::integer,d->>'decision',d->>'author',d->>'author_username',d->'reviewed_value',
  d->>'reason',(d->>'recorded_at')::timestamptz,d->>'request_key',d->>'request_digest',d);
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.store_evidence_review_event() FROM PUBLIC,supplypilot_app;
CREATE TRIGGER records_evidence_review_store AFTER INSERT ON public.records
 FOR EACH ROW EXECUTE FUNCTION public.store_evidence_review_event();
"""


def upgrade():
    op.execute(SQL)


def downgrade():
    raise RuntimeError('Restore a reviewed backup; automatic review-history protection removal is disabled.')
