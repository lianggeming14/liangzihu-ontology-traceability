-- SQLite DEVELOPMENT ONLY; not PostgreSQL validation.
-- Decimal quantities are TEXT and checked by exact Decimal functions registered by SQLiteDatabase.
-- Authoritative semantic data and isolated demonstration business records.
-- Every private foreign key includes tenant_id. No production seed data.
CREATE TABLE ontology_namespaces (
 tenant_id text NOT NULL, namespace text NOT NULL, package_id text NOT NULL,
 PRIMARY KEY(tenant_id,namespace)
);
CREATE TABLE ontology_packages (
 tenant_id text NOT NULL, package_id text NOT NULL, version text NOT NULL,
 namespace text NOT NULL, content_hash text NOT NULL, definition TEXT NOT NULL,
 created_at TEXT NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,package_id,version),
 FOREIGN KEY(tenant_id,namespace) REFERENCES ontology_namespaces(tenant_id,namespace)
);
CREATE TABLE ontology_types (
 tenant_id text NOT NULL, package_id text NOT NULL, package_version text NOT NULL,
 type_id text NOT NULL, identity_type text NOT NULL, definition TEXT NOT NULL,
 PRIMARY KEY(tenant_id,package_id,package_version,type_id),
 FOREIGN KEY(tenant_id,package_id,package_version) REFERENCES ontology_packages(tenant_id,package_id,version)
);
CREATE TABLE ontology_predicates (
 tenant_id text NOT NULL, package_id text NOT NULL, package_version text NOT NULL,
 predicate_id text NOT NULL, definition TEXT NOT NULL,
 PRIMARY KEY(tenant_id,package_id,package_version,predicate_id),
 FOREIGN KEY(tenant_id,package_id,package_version) REFERENCES ontology_packages(tenant_id,package_id,version)
);
CREATE TABLE entities (
 tenant_id text NOT NULL, entity_key TEXT NOT NULL, entity_type text NOT NULL,
 entity_id TEXT NOT NULL, name text NOT NULL, attributes TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,entity_key), UNIQUE(tenant_id,entity_type,entity_id)
);
CREATE TABLE type_assignments (
 tenant_id text NOT NULL, id TEXT NOT NULL, entity_key TEXT NOT NULL,
 package_id text NOT NULL, package_version text NOT NULL, type_id text NOT NULL,
 valid_from TEXT NOT NULL, valid_to TEXT,
 created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),
 UNIQUE(tenant_id,entity_key,package_id,package_version,type_id),
 FOREIGN KEY(tenant_id,entity_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,package_id,package_version,type_id) REFERENCES ontology_types(tenant_id,package_id,package_version,type_id),
 CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE TABLE evidence (
 tenant_id text NOT NULL, id TEXT NOT NULL, kind text NOT NULL, uri text NOT NULL,
 content_hash text NOT NULL, source_id text NOT NULL, public_summary text NOT NULL,
 metadata TEXT NOT NULL, status text NOT NULL CHECK(status IN ('active','withdrawn')),
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, created_by text NOT NULL,
 withdrawn_at TEXT, withdrawal_reason text,
 PRIMARY KEY(tenant_id,id)
);
CREATE TABLE observations (
 tenant_id text NOT NULL, id TEXT NOT NULL, subject_key TEXT NOT NULL,
 property_id text NOT NULL, value_json TEXT NOT NULL, observed_at TEXT NOT NULL,
 method text NOT NULL, origin text NOT NULL, spatial_context TEXT NOT NULL,
 evidence_ids TEXT NOT NULL, created_at TEXT NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,subject_key) REFERENCES entities(tenant_id,entity_key),
 CHECK(origin IN ('measured','reported','estimated'))
);
CREATE TABLE assertions (
 tenant_id text NOT NULL, id TEXT NOT NULL, subject_key TEXT NOT NULL,
 predicate_id text NOT NULL, value_json TEXT, object_key TEXT,
 origin text NOT NULL, evidence_ids TEXT NOT NULL,
 status text NOT NULL CHECK(status IN ('candidate','accepted','rejected','needs_review')),
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,subject_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,object_key) REFERENCES entities(tenant_id,entity_key),
 CHECK((value_json IS NOT NULL AND object_key IS NULL) OR (value_json IS NULL AND object_key IS NOT NULL))
);
CREATE TABLE assertion_assessments (
 tenant_id text NOT NULL,id TEXT NOT NULL,assertion_id TEXT NOT NULL,status text NOT NULL,
 rationale text NOT NULL,actor_id text NOT NULL,assessed_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,assertion_id) REFERENCES assertions(tenant_id,id)
);
CREATE TABLE relations (
 tenant_id text NOT NULL,id TEXT NOT NULL,subject_key TEXT NOT NULL,object_key TEXT NOT NULL,
 package_id text NOT NULL,package_version text NOT NULL,predicate_id text NOT NULL,
 dimension text NOT NULL,valid_from TEXT NOT NULL,valid_to TEXT,
 qualifiers TEXT NOT NULL,evidence_ids TEXT NOT NULL,
 status text NOT NULL CHECK(status IN ('candidate','accepted','rejected','needs_review')),
 revision INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,subject_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,object_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,package_id,package_version,predicate_id) REFERENCES ontology_predicates(tenant_id,package_id,package_version,predicate_id),
 CHECK(valid_to IS NULL OR valid_to > valid_from)
);
CREATE TABLE relation_assessments (
 tenant_id text NOT NULL,id TEXT NOT NULL,relation_id TEXT NOT NULL,status text NOT NULL,
 rationale text NOT NULL,actor_id text NOT NULL,assessed_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,relation_id) REFERENCES relations(tenant_id,id)
);
CREATE TABLE events (
 tenant_id text NOT NULL,id TEXT NOT NULL,event_type text NOT NULL,occurred_at TEXT NOT NULL,
 event_payload TEXT NOT NULL,evidence_ids TEXT NOT NULL,status text NOT NULL,
 created_at TEXT NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id)
);
CREATE TABLE lots (
 tenant_id text NOT NULL,lot_key TEXT NOT NULL,product_type text NOT NULL,unit text NOT NULL,
 production_batch_key TEXT,genesis_event_id TEXT,
 produced_quantity TEXT NOT NULL DEFAULT 0,
 available_quantity TEXT NOT NULL DEFAULT 0,
 shipped_quantity TEXT NOT NULL DEFAULT 0,
 received_quantity TEXT NOT NULL DEFAULT 0,
 revision INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(tenant_id,lot_key),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,production_batch_key) REFERENCES entities(tenant_id,entity_key),
 FOREIGN KEY(tenant_id,genesis_event_id) REFERENCES events(tenant_id,id),
 CHECK(decimal_nonnegative(produced_quantity) AND decimal_nonnegative(available_quantity) AND decimal_nonnegative(shipped_quantity) AND decimal_nonnegative(received_quantity)),
 CHECK(decimal_lte(received_quantity,shipped_quantity))
);
CREATE TABLE event_participants (
 tenant_id text NOT NULL,id TEXT NOT NULL,event_id TEXT NOT NULL,entity_key TEXT NOT NULL,
 role text NOT NULL,quantity TEXT,unit text,
 PRIMARY KEY(tenant_id,id),
 FOREIGN KEY(tenant_id,event_id) REFERENCES events(tenant_id,id),
 FOREIGN KEY(tenant_id,entity_key) REFERENCES entities(tenant_id,entity_key),
 CHECK(quantity IS NULL OR decimal_positive(quantity))
);
CREATE TABLE material_ancestry (
 tenant_id text NOT NULL,event_id TEXT NOT NULL,input_lot_key TEXT NOT NULL,output_lot_key TEXT NOT NULL,
 allocation_status text NOT NULL,allocation_quantity TEXT,unit text NOT NULL,
 PRIMARY KEY(tenant_id,event_id,input_lot_key,output_lot_key),
 FOREIGN KEY(tenant_id,event_id) REFERENCES events(tenant_id,id),
 FOREIGN KEY(tenant_id,input_lot_key) REFERENCES lots(tenant_id,lot_key),
 FOREIGN KEY(tenant_id,output_lot_key) REFERENCES lots(tenant_id,lot_key),
 CHECK(input_lot_key <> output_lot_key)
);
CREATE TABLE shipment_lines (
 tenant_id text NOT NULL,shipment_id TEXT NOT NULL,lot_key TEXT NOT NULL,
 shipped_quantity TEXT NOT NULL,received_quantity TEXT NOT NULL DEFAULT 0,unit text NOT NULL,
 PRIMARY KEY(tenant_id,shipment_id,lot_key),
 FOREIGN KEY(tenant_id,shipment_id) REFERENCES events(tenant_id,id),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES lots(tenant_id,lot_key),
 CHECK(decimal_nonnegative(received_quantity) AND decimal_lte(received_quantity,shipped_quantity))
);
CREATE TABLE evidence_links (
 tenant_id text NOT NULL,id TEXT NOT NULL,evidence_id TEXT NOT NULL,
 target_kind text NOT NULL,target_id TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,evidence_id,target_kind,target_id),
 FOREIGN KEY(tenant_id,evidence_id) REFERENCES evidence(tenant_id,id)
);
CREATE TABLE publications (
 tenant_id text NOT NULL,id TEXT NOT NULL,lot_key TEXT NOT NULL,revision INTEGER NOT NULL,
 body TEXT NOT NULL,content_hash text NOT NULL,status text NOT NULL,
 created_at TEXT NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),UNIQUE(tenant_id,lot_key,revision),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES lots(tenant_id,lot_key)
);
CREATE TABLE publication_evidence (
 tenant_id text NOT NULL,publication_id TEXT NOT NULL,evidence_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,publication_id,evidence_id),
 FOREIGN KEY(tenant_id,publication_id) REFERENCES publications(tenant_id,id),
 FOREIGN KEY(tenant_id,evidence_id) REFERENCES evidence(tenant_id,id)
);
CREATE TABLE publication_assertions (
 tenant_id text NOT NULL,publication_id TEXT NOT NULL,assertion_id TEXT NOT NULL,
 PRIMARY KEY(tenant_id,publication_id,assertion_id),
 FOREIGN KEY(tenant_id,publication_id) REFERENCES publications(tenant_id,id),
 FOREIGN KEY(tenant_id,assertion_id) REFERENCES assertions(tenant_id,id)
);
CREATE TABLE public_codes (
 code text PRIMARY KEY,tenant_id text NOT NULL,lot_key TEXT NOT NULL,publication_id TEXT NOT NULL,
 status text NOT NULL,revision INTEGER NOT NULL,
 UNIQUE(tenant_id,lot_key),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES lots(tenant_id,lot_key),
 FOREIGN KEY(tenant_id,publication_id) REFERENCES publications(tenant_id,id)
);
CREATE TABLE recalls (
 tenant_id text NOT NULL,id TEXT NOT NULL,origin_lot_key TEXT NOT NULL,reason text NOT NULL,
 status text NOT NULL,created_at TEXT NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id), FOREIGN KEY(tenant_id,origin_lot_key) REFERENCES lots(tenant_id,lot_key)
);
CREATE TABLE recall_lots (
 tenant_id text NOT NULL,recall_id TEXT NOT NULL,lot_key TEXT NOT NULL,scope_status text NOT NULL,
 PRIMARY KEY(tenant_id,recall_id,lot_key),
 FOREIGN KEY(tenant_id,recall_id) REFERENCES recalls(tenant_id,id),
 FOREIGN KEY(tenant_id,lot_key) REFERENCES lots(tenant_id,lot_key)
);
CREATE TABLE idempotency (
 tenant_id text NOT NULL,idempotency_key text NOT NULL,payload_hash text NOT NULL,
 response TEXT,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,idempotency_key)
);
CREATE TABLE outbox_counters (
 tenant_id text PRIMARY KEY,next_sequence INTEGER NOT NULL
);
CREATE TABLE outbox (
 tenant_id text NOT NULL,sequence INTEGER NOT NULL,event_id TEXT NOT NULL,
 event_type text NOT NULL,aggregate_key text NOT NULL,revision INTEGER NOT NULL,
 payload TEXT NOT NULL,created_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,sequence),UNIQUE(tenant_id,event_id)
);
CREATE TABLE audit_log (
 tenant_id text NOT NULL,id TEXT NOT NULL,actor_id text NOT NULL,action text NOT NULL,
 target_id text NOT NULL,details TEXT NOT NULL,created_at TEXT NOT NULL,
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
 tenant_id text NOT NULL,id TEXT NOT NULL,name text NOT NULL,mode text NOT NULL,
 filter_json TEXT NOT NULL,members TEXT NOT NULL,created_at TEXT NOT NULL,created_by text NOT NULL,
 PRIMARY KEY(tenant_id,id),CHECK(mode IN ('dynamic','snapshot'))
);
