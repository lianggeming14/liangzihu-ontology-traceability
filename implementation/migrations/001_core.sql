-- Authoritative semantic data and isolated demonstration business records.
-- Every private foreign key includes tenant_id. No production seed data.
CREATE TABLE ontology_namespaces (
 tenant_id text NOT NULL, namespace text NOT NULL, package_id text NOT NULL,
 PRIMARY KEY(tenant_id,namespace)
);
CREATE TABLE ontology_packages (
 tenant_id text NOT NULL, package_id text NOT NULL, version text NOT NULL,
 namespace text NOT NULL, content_hash text NOT NULL, definition jsonb NOT NULL,
 created_at timestamptz NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,package_id,version),
 FOREIGN KEY(tenant_id,namespace) REFERENCES ontology_namespaces(tenant_id,namespace)
);
CREATE TABLE ontology_types (
 tenant_id text NOT NULL, package_id text NOT NULL, package_version text NOT NULL,
 type_id text NOT NULL, identity_type text NOT NULL, definition jsonb NOT NULL,
 PRIMARY KEY(tenant_id,package_id,package_version,type_id),
 FOREIGN KEY(tenant_id,package_id,package_version) REFERENCES ontology_packages(tenant_id,package_id,version)
);
CREATE TABLE ontology_predicates (
 tenant_id text NOT NULL, package_id text NOT NULL, package_version text NOT NULL,
 predicate_id text NOT NULL, definition jsonb NOT NULL,
 PRIMARY KEY(tenant_id,package_id,package_version,predicate_id),
 FOREIGN KEY(tenant_id,package_id,package_version) REFERENCES ontology_packages(tenant_id,package_id,version)
);
CREATE TABLE entities (
 tenant_id text NOT NULL, entity_key uuid NOT NULL, entity_type text NOT NULL,
 entity_id uuid NOT NULL, name text NOT NULL, attributes jsonb NOT NULL,
 revision bigint NOT NULL DEFAULT 1, created_at timestamptz NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,entity_key), UNIQUE(tenant_id,entity_type,entity_id)
);
CREATE TABLE type_assignments (
 tenant_id text NOT NULL, id uuid NOT NULL, entity_key uuid NOT NULL,
 package_id text NOT NULL, package_version text NOT NULL, type_id text NOT NULL,
 valid_from timestamptz NOT NULL, valid_to timestamptz,
 created_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,entity_key,package_id,package_version,type_id),
 FOREIGN KEY(tenant_id,entity_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,package_id,package_version,type_id) REFERENCES ontology_types(tenant_id,package_id,package_version,type_id),
 CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE TABLE evidence (
 tenant_id text NOT NULL, id uuid NOT NULL, kind text NOT NULL, uri text NOT NULL,
 content_hash text NOT NULL, source_id text NOT NULL, public_summary text NOT NULL,
 metadata jsonb NOT NULL, status text NOT NULL CHECK(status IN ('active','withdrawn')),
 revision bigint NOT NULL DEFAULT 1, created_at timestamptz NOT NULL, created_by text NOT NULL,
 withdrawn_at timestamptz, withdrawal_reason text,
 PRIMARY KEY(tenant_id,id)
);
CREATE TABLE observations (
 tenant_id text NOT NULL, id uuid NOT NULL, subject_key uuid NOT NULL,
 property_id text NOT NULL, value_json jsonb NOT NULL, observed_at timestamptz NOT NULL,
 method text NOT NULL, origin text NOT NULL, spatial_context jsonb NOT NULL,
 evidence_ids jsonb NOT NULL, created_at timestamptz NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,subject_key) REFERENCES entities(tenant_id,entity_key),
 CHECK(origin IN ('measured','reported','estimated'))
);
CREATE TABLE assertions (
 tenant_id text NOT NULL, id uuid NOT NULL, subject_key uuid NOT NULL,
 predicate_id text NOT NULL, value_json jsonb, object_key uuid,
 origin text NOT NULL, evidence_ids jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('candidate','accepted','rejected','needs_review')),
 revision bigint NOT NULL DEFAULT 1, created_at timestamptz NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,subject_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,object_key) REFERENCES entities(tenant_id,entity_key),
 CHECK((value_json IS NOT NULL AND object_key IS NULL) OR (value_json IS NULL AND object_key IS NOT NULL))
);
CREATE TABLE assertion_assessments (
 tenant_id text NOT NULL,id uuid NOT NULL,assertion_id uuid NOT NULL,status text NOT NULL,
 rationale text NOT NULL,actor_id text NOT NULL,assessed_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,assertion_id) REFERENCES assertions(tenant_id,id)
);
CREATE TABLE relations (
 tenant_id text NOT NULL,id uuid NOT NULL,subject_key uuid NOT NULL,object_key uuid NOT NULL,
 package_id text NOT NULL,package_version text NOT NULL,predicate_id text NOT NULL,
 dimension text NOT NULL,valid_from timestamptz NOT NULL,valid_to timestamptz,
 qualifiers jsonb NOT NULL,evidence_ids jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('candidate','accepted','rejected','needs_review')),
 revision bigint NOT NULL DEFAULT 1,created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,subject_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,object_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,package_id,package_version,predicate_id) REFERENCES ontology_predicates(tenant_id,package_id,package_version,predicate_id),
 CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE TABLE relation_assessments (
 tenant_id text NOT NULL,id uuid NOT NULL,relation_id uuid NOT NULL,status text NOT NULL,
 rationale text NOT NULL,actor_id text NOT NULL,assessed_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,relation_id) REFERENCES relations(tenant_id,id)
);
CREATE TABLE events (
 tenant_id text NOT NULL,id uuid NOT NULL,event_type text NOT NULL,occurred_at timestamptz NOT NULL,
 event_payload jsonb NOT NULL,evidence_ids jsonb NOT NULL,status text NOT NULL,
 created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id)
);
CREATE TABLE lots (
 tenant_id text NOT NULL,lot_key uuid NOT NULL,product_type text NOT NULL,unit text NOT NULL,
 production_batch_key uuid,genesis_event_id uuid,
 produced_quantity numeric(30,9) NOT NULL DEFAULT 0,
 available_quantity numeric(30,9) NOT NULL DEFAULT 0,
 shipped_quantity numeric(30,9) NOT NULL DEFAULT 0,
 received_quantity numeric(30,9) NOT NULL DEFAULT 0,
 revision bigint NOT NULL DEFAULT 1,
 PRIMARY KEY(tenant_id,lot_key),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,production_batch_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,genesis_event_id) REFERENCES events(tenant_id,id),
 CHECK(produced_quantity >= 0 AND available_quantity >= 0 AND shipped_quantity >= 0 AND received_quantity >= 0),
 CHECK(received_quantity <= shipped_quantity)
);
CREATE TABLE event_participants (
 tenant_id text NOT NULL,id uuid NOT NULL,event_id uuid NOT NULL,entity_key uuid NOT NULL,
 role text NOT NULL,quantity numeric(30,9),unit text,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,event_id) REFERENCES events(tenant_id,id),
 FOREIGN KEY(tenant_id,entity_key) REFERENCES entities(tenant_id,entity_key),
 CHECK(quantity IS NULL OR quantity > 0)
);
CREATE TABLE material_ancestry (
 tenant_id text NOT NULL,event_id uuid NOT NULL,input_lot_key uuid NOT NULL,output_lot_key uuid NOT NULL,
 allocation_status text NOT NULL,allocation_quantity numeric(30,9),unit text NOT NULL,
 PRIMARY KEY(tenant_id,event_id,input_lot_key,output_lot_key),
 FOREIGN KEY(tenant_id,event_id) REFERENCES events(tenant_id,id),
 FOREIGN KEY(tenant_id,input_lot_key) REFERENCES lots(tenant_id,lot_key),
 FOREIGN KEY(tenant_id,output_lot_key) REFERENCES lots(tenant_id,lot_key),
 CHECK(input_lot_key <> output_lot_key)
);
CREATE TABLE shipment_lines (
 tenant_id text NOT NULL,shipment_id uuid NOT NULL,lot_key uuid NOT NULL,
 shipped_quantity numeric(30,9) NOT NULL,received_quantity numeric(30,9) NOT NULL DEFAULT 0,unit text NOT NULL,
 PRIMARY KEY(tenant_id,shipment_id,lot_key),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES events(tenant_id,id),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES lots(tenant_id,lot_key),
 CHECK(received_quantity >= 0 AND received_quantity <= shipped_quantity)
);
CREATE TABLE evidence_links (
 tenant_id text NOT NULL,id uuid NOT NULL,evidence_id uuid NOT NULL,
 target_kind text NOT NULL,target_id uuid NOT NULL,created_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,evidence_id,target_kind,target_id),
 FOREIGN KEY(tenant_id,evidence_id) REFERENCES evidence(tenant_id,id)
);
CREATE TABLE publications (
 tenant_id text NOT NULL,id uuid NOT NULL,lot_key uuid NOT NULL,revision bigint NOT NULL,
 body jsonb NOT NULL,content_hash text NOT NULL,status text NOT NULL,
 created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,lot_key,revision),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES lots(tenant_id,lot_key)
);
CREATE TABLE publication_evidence (
 tenant_id text NOT NULL,publication_id uuid NOT NULL,evidence_id uuid NOT NULL,
 PRIMARY KEY(tenant_id,publication_id,evidence_id),
 FOREIGN KEY(tenant_id,publication_id) REFERENCES publications(tenant_id,id),
 FOREIGN KEY(tenant_id,evidence_id) REFERENCES evidence(tenant_id,id)
);
CREATE TABLE publication_assertions (
 tenant_id text NOT NULL,publication_id uuid NOT NULL,assertion_id uuid NOT NULL,
 PRIMARY KEY(tenant_id,publication_id,assertion_id),
 FOREIGN KEY(tenant_id,publication_id) REFERENCES publications(tenant_id,id),
 FOREIGN KEY(tenant_id,assertion_id) REFERENCES assertions(tenant_id,id)
);
CREATE TABLE public_codes (
 code text PRIMARY KEY,tenant_id text NOT NULL,lot_key uuid NOT NULL,publication_id uuid NOT NULL,
 status text NOT NULL,revision bigint NOT NULL,
 UNIQUE(tenant_id,lot_key),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES lots(tenant_id,lot_key),
 FOREIGN KEY(tenant_id,publication_id) REFERENCES publications(tenant_id,id)
);
CREATE TABLE recalls (
 tenant_id text NOT NULL,id uuid NOT NULL,origin_lot_key uuid NOT NULL,reason text NOT NULL,
 status text NOT NULL,created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,origin_lot_key) REFERENCES lots(tenant_id,lot_key)
);
CREATE TABLE recall_lots (
 tenant_id text NOT NULL,recall_id uuid NOT NULL,lot_key uuid NOT NULL,scope_status text NOT NULL,
 PRIMARY KEY(tenant_id,recall_id,lot_key),
 FOREIGN KEY(tenant_id,recall_id) REFERENCES recalls(tenant_id,id),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES lots(tenant_id,lot_key)
);
CREATE TABLE idempotency (
 tenant_id text NOT NULL,idempotency_key text NOT NULL,payload_hash text NOT NULL,
 response jsonb,created_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,idempotency_key)
);
CREATE TABLE outbox_counters (
 tenant_id text PRIMARY KEY,next_sequence bigint NOT NULL
);
CREATE TABLE outbox (
 tenant_id text NOT NULL,sequence bigint NOT NULL,event_id uuid NOT NULL,
 event_type text NOT NULL,aggregate_key text NOT NULL,revision bigint NOT NULL,
 payload jsonb NOT NULL,created_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,sequence),UNIQUE(tenant_id,event_id)
);
CREATE TABLE audit_log (
 tenant_id text NOT NULL,id uuid NOT NULL,actor_id text NOT NULL,action text NOT NULL,
 target_id text NOT NULL,details jsonb NOT NULL,created_at timestamptz NOT NULL,
 PRIMARY KEY(tenant_id,id)
);
CREATE INDEX relations_subject ON relations(tenant_id,subject_key,status);
CREATE INDEX relations_object ON relations(tenant_id,object_key,status);
CREATE INDEX observations_subject ON observations(tenant_id,subject_key,observed_at);
CREATE INDEX assertions_subject ON assertions(tenant_id,subject_key,status);
CREATE INDEX participants_entity ON event_participants(tenant_id,entity_key,event_id);
CREATE INDEX material_up ON material_ancestry(tenant_id,output_lot_key);
CREATE INDEX material_down ON material_ancestry(tenant_id,input_lot_key);
CREATE INDEX evidence_targets ON evidence_links(tenant_id,target_kind,target_id);
CREATE INDEX lots_genesis ON lots(tenant_id,genesis_event_id);

CREATE TABLE object_sets (
 tenant_id text NOT NULL,id uuid NOT NULL,name text NOT NULL,mode text NOT NULL,
 filter_json jsonb NOT NULL,members jsonb NOT NULL,created_at timestamptz NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),CHECK(mode IN ('dynamic','snapshot'))
);
