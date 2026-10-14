-- Durable intake envelopes, immutable mapping releases and append-only attempts.
CREATE TABLE intake_mappings (
 tenant_id text NOT NULL,mapping_id text NOT NULL,version text NOT NULL,
 source_id text NOT NULL,schema_version text NOT NULL,record_kind text NOT NULL,
 definition jsonb NOT NULL,content_hash text NOT NULL,created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,mapping_id,version)
);
CREATE TABLE intake_receipts (
 tenant_id text NOT NULL,id uuid NOT NULL,source_id text NOT NULL,source_record_id text NOT NULL,
 schema_version text NOT NULL,source_category text NOT NULL,content_type text NOT NULL,record_kind text NOT NULL,
 raw_envelope jsonb NOT NULL,payload_hash text NOT NULL,raw_evidence_id uuid NOT NULL,
 status text NOT NULL,mapping_id text,mapping_version text,latest_attempt integer NOT NULL DEFAULT 0,
 target_action text,target_id text,created_at timestamptz NOT NULL,created_by text NOT NULL,updated_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,source_id,source_record_id),
 FOREIGN KEY(tenant_id,raw_evidence_id) REFERENCES evidence(tenant_id,id),
 CHECK(status IN ('needs_mapping','validation_failed','stored'))
);
CREATE TABLE intake_attempts (
 tenant_id text NOT NULL,receipt_id uuid NOT NULL,attempt_number integer NOT NULL,
 mapping_id text,mapping_version text,status text NOT NULL,issues jsonb NOT NULL,
 normalized_payload jsonb,target_action text,target_id text,result jsonb,
 created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,receipt_id,attempt_number),
 FOREIGN KEY(tenant_id,receipt_id) REFERENCES intake_receipts(tenant_id,id),
 CHECK(status IN ('needs_mapping','validation_failed','stored')),CHECK(attempt_number>0)
);
CREATE INDEX intake_source_status ON intake_receipts(tenant_id,status,source_id,created_at,id);
CREATE INDEX intake_mapping_source ON intake_mappings(tenant_id,source_id,schema_version,record_kind);
