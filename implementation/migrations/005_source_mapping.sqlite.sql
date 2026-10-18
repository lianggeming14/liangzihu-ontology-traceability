-- Source record identity is separate from ontology identity. Tenant-qualified
-- foreign keys and immutable revision rows preserve every committed mapping.
CREATE TABLE source_profiles (
 tenant_id text NOT NULL, source_id text NOT NULL, profile_id text NOT NULL, version text NOT NULL,
 definition TEXT NOT NULL, content_hash text NOT NULL, created_at TEXT NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,source_id,profile_id,version)
);
CREATE TABLE source_batches (
 tenant_id text NOT NULL, source_id text NOT NULL, batch_id text NOT NULL,
 profile_id text NOT NULL, profile_version text NOT NULL, payload_hash text NOT NULL,
 observed_at TEXT NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,source_id,batch_id),
 FOREIGN KEY(tenant_id,source_id,profile_id,profile_version) REFERENCES source_profiles(tenant_id,source_id,profile_id,version)
);
CREATE TABLE source_bindings (
 tenant_id text NOT NULL, id TEXT NOT NULL, source_id text NOT NULL, source_table text NOT NULL,
 key_hash text NOT NULL, source_key TEXT NOT NULL, key_contract TEXT NOT NULL,
 entity_key TEXT NOT NULL, type_ref TEXT NOT NULL, revision bigint NOT NULL,
 entity_revision bigint NOT NULL, profile_id text NOT NULL, profile_version text NOT NULL,
 data_nature text NOT NULL CHECK(data_nature IN ('production','synthetic','test','unspecified')),
 source_values TEXT NOT NULL, payload_hash text NOT NULL, evidence_id TEXT NOT NULL,
 managed_properties TEXT NOT NULL, observed_at TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,source_id,source_table,key_hash),
 UNIQUE(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,entity_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,evidence_id) REFERENCES evidence(tenant_id,id),
 FOREIGN KEY(tenant_id,source_id,profile_id,profile_version) REFERENCES source_profiles(tenant_id,source_id,profile_id,version),
 CHECK(revision>0),CHECK(entity_revision>0)
);
CREATE TABLE source_binding_revisions (
 tenant_id text NOT NULL, binding_id TEXT NOT NULL, revision bigint NOT NULL,
 batch_id text NOT NULL, source_id text NOT NULL, profile_id text NOT NULL, profile_version text NOT NULL,
 source_values TEXT NOT NULL, entity_snapshot TEXT NOT NULL, evidence_id TEXT NOT NULL,
 payload_hash text NOT NULL, observed_at TEXT NOT NULL, recorded_at TEXT NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,binding_id,revision),
 FOREIGN KEY(tenant_id,binding_id) REFERENCES source_bindings(tenant_id,id),
 FOREIGN KEY(tenant_id,evidence_id) REFERENCES evidence(tenant_id,id),
 FOREIGN KEY(tenant_id,source_id,profile_id,profile_version) REFERENCES source_profiles(tenant_id,source_id,profile_id,version),
 CHECK(revision>0)
);
CREATE TABLE source_relation_links (
 tenant_id text NOT NULL, id TEXT NOT NULL, binding_id TEXT NOT NULL, relation_key text NOT NULL,
 relation_id TEXT NOT NULL, target_binding_id TEXT NOT NULL, mapping_hash text NOT NULL,
 started_revision bigint NOT NULL, ended_revision bigint,
 opened_at TEXT NOT NULL, closed_at TEXT,
 PRIMARY KEY(tenant_id,id), UNIQUE(tenant_id,relation_id),
 FOREIGN KEY(tenant_id,binding_id) REFERENCES source_bindings(tenant_id,id),
 FOREIGN KEY(tenant_id,target_binding_id) REFERENCES source_bindings(tenant_id,id),
 FOREIGN KEY(tenant_id,relation_id) REFERENCES relations(tenant_id,id),
 CHECK((closed_at IS NULL AND ended_revision IS NULL) OR (closed_at IS NOT NULL AND ended_revision IS NOT NULL))
);
CREATE UNIQUE INDEX source_relation_active ON source_relation_links(tenant_id,binding_id,relation_key) WHERE closed_at IS NULL;
CREATE INDEX source_binding_source_table ON source_bindings(tenant_id,source_id,source_table,created_at,id);
CREATE INDEX source_batch_profile ON source_batches(tenant_id,source_id,profile_id,profile_version,created_at,batch_id);
