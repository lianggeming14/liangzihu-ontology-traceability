-- Additive migration: generic camera/gate receipts and capture planning.
-- All source, object, policy and record references remain tenant scoped.
CREATE TABLE device_registrations (
 tenant_id text NOT NULL,id uuid NOT NULL,name text NOT NULL,
 device_kind text NOT NULL,source_id text NOT NULL,external_device_id text NOT NULL,
 device_entity_key uuid NOT NULL,bound_entity_key uuid NOT NULL,
 created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,source_id,external_device_id),
 UNIQUE(tenant_id,device_entity_key),
 FOREIGN KEY(tenant_id,device_entity_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,bound_entity_key) REFERENCES entities(tenant_id,entity_key),
 CHECK(device_kind IN ('camera','gate')),CHECK(device_entity_key<>bound_entity_key)
);
CREATE TABLE capture_policies (
 tenant_id text NOT NULL,id uuid NOT NULL,device_id uuid NOT NULL,name text NOT NULL,
 record_type text NOT NULL,start_at timestamptz NOT NULL,end_at timestamptz,
 interval_seconds integer NOT NULL,focus_windows jsonb NOT NULL,
 enabled boolean NOT NULL,revision bigint NOT NULL DEFAULT 1,
 created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,id,device_id),
 FOREIGN KEY(tenant_id,device_id) REFERENCES device_registrations(tenant_id,id),
 CHECK(record_type IN ('camera_snapshot','camera_video','gate_status')),
 CHECK(interval_seconds BETWEEN 60 AND 604800),CHECK(end_at IS NULL OR end_at>start_at),
 CHECK(revision>0)
);
CREATE TABLE device_records (
 tenant_id text NOT NULL,id uuid NOT NULL,device_id uuid NOT NULL,source_record_id text NOT NULL,
 record_type text NOT NULL,captured_at timestamptz NOT NULL,received_at timestamptz NOT NULL,
 device_entity_key uuid NOT NULL,bound_entity_key uuid NOT NULL,
 priority text NOT NULL,note text NOT NULL,data_json jsonb NOT NULL,
 evidence_ids jsonb NOT NULL,observation_ids jsonb NOT NULL,
 policy_id uuid,slot_at timestamptz,slot_id text,payload_hash text NOT NULL,
 created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,device_id,source_record_id),UNIQUE(tenant_id,slot_id),
 FOREIGN KEY(tenant_id,device_id) REFERENCES device_registrations(tenant_id,id),
 FOREIGN KEY(tenant_id,device_entity_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,bound_entity_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,policy_id,device_id) REFERENCES capture_policies(tenant_id,id,device_id),
 CHECK(record_type IN ('camera_snapshot','camera_video','gate_status','manual_note')),
 CHECK(priority IN ('routine','focus')),
 CHECK((policy_id IS NULL AND slot_at IS NULL AND slot_id IS NULL) OR
       (policy_id IS NOT NULL AND slot_at IS NOT NULL AND slot_id IS NOT NULL))
);
CREATE INDEX device_bindings ON device_registrations(tenant_id,bound_entity_key,id);
CREATE INDEX capture_policy_device ON capture_policies(tenant_id,device_id,enabled,id);
CREATE INDEX device_records_time ON device_records(tenant_id,device_id,captured_at,id);
