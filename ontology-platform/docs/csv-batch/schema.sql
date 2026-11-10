-- Isolated CSV batch only; requires an absent schema. No original record values.
CREATE SCHEMA "csv_batch_a4d78be79a83";

CREATE TABLE "csv_batch_a4d78be79a83"."batch_metadata" (
  "id" TEXT PRIMARY KEY,
  "document" JSONB NOT NULL,
  CHECK ("id" = 'batch')
);

CREATE TABLE "csv_batch_a4d78be79a83"."source_tables" (
  "table_name" TEXT PRIMARY KEY,
  "source_path" TEXT NOT NULL,
  "definition" JSONB NOT NULL
);

CREATE TABLE "csv_batch_a4d78be79a83"."field_dictionary" (
  "table_name" TEXT NOT NULL,
  "field_name" TEXT NOT NULL,
  "ordinal" INTEGER NOT NULL,
  "definition" JSONB NOT NULL,
  "column_sql_type" TEXT NOT NULL,
  PRIMARY KEY ("table_name", "field_name"),
  FOREIGN KEY ("table_name") REFERENCES "csv_batch_a4d78be79a83"."source_tables" ("table_name")
);

CREATE TABLE "csv_batch_a4d78be79a83"."raw_records" (
  "table_name" TEXT NOT NULL,
  "row_number" BIGINT NOT NULL,
  "source_pk" TEXT NOT NULL,
  "payload" JSONB NOT NULL,
  "status" TEXT NOT NULL,
  "issues" JSONB NOT NULL,
  "sample_reason" TEXT NOT NULL,
  "package_sha256" TEXT NOT NULL,
  PRIMARY KEY ("table_name", "row_number"),
  CHECK ("row_number" > 0),
  FOREIGN KEY ("table_name") REFERENCES "csv_batch_a4d78be79a83"."source_tables" ("table_name")
);

CREATE TABLE "csv_batch_a4d78be79a83"."ontology_nodes" (
  "node_id" UUID PRIMARY KEY,
  "table_name" TEXT NOT NULL,
  "source_pk" TEXT NOT NULL,
  "source_row" BIGINT NOT NULL,
  "properties" JSONB NOT NULL,
  "nature" TEXT NOT NULL,
  "role" TEXT NOT NULL,
  "adoption_status" TEXT NOT NULL,
  UNIQUE ("table_name", "source_pk"),
  UNIQUE ("node_id", "table_name", "source_row"),
  UNIQUE ("node_id", "table_name", "source_pk"),
  FOREIGN KEY ("table_name", "source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number")
);

CREATE TABLE "csv_batch_a4d78be79a83"."ontology_relations" (
  "edge_id" BIGINT PRIMARY KEY,
  "from_node" UUID NOT NULL,
  "from_table" TEXT NOT NULL,
  "field_name" TEXT NOT NULL,
  "target_table" TEXT NOT NULL,
  "target_pk" TEXT NOT NULL,
  "to_node" UUID,
  "resolution" TEXT NOT NULL,
  "source_row" BIGINT NOT NULL,
  "list_index" BIGINT,
  "evidence" TEXT NOT NULL,
  FOREIGN KEY ("from_node", "from_table", "source_row") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id", "table_name", "source_row"),
  FOREIGN KEY ("to_node", "target_table", "target_pk") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id", "table_name", "source_pk"),
  FOREIGN KEY ("from_table", "source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK (("resolution" = 'resolved' AND "to_node" IS NOT NULL) OR ("resolution" <> 'resolved' AND "to_node" IS NULL))
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_attachment_links" (
  "id" TEXT PRIMARY KEY,
  "attachment_id" TEXT,
  "entity_table" TEXT,
  "entity_id" TEXT,
  "relation_type" TEXT,
  "evidence_status" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'attachment_links',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'attachment_links')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_attachments" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "category" TEXT,
  "relative_path" TEXT,
  "file_name" TEXT,
  "mime_type" TEXT,
  "file_size_bytes" NUMERIC,
  "sha256" TEXT,
  "captured_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "capture_device" TEXT,
  "language" TEXT,
  "license_status" TEXT,
  "review_status" TEXT,
  "origin_kind" TEXT,
  "is_synthetic" BOOLEAN,
  "clinical_label_status" TEXT,
  "intended_use" TEXT,
  "usage_limitation" TEXT,
  "generation_run_id" TEXT,
  "seed" NUMERIC,
  "rule_version" TEXT,
  "scenario_id" TEXT,
  "width_px" NUMERIC,
  "height_px" NUMERIC,
  "duration_seconds" NUMERIC,
  "codec" TEXT,
  "sample_rate_hz" NUMERIC,
  "channels" NUMERIC,
  "audio_kind" TEXT,
  "pair_id" TEXT,
  "voice_name" TEXT,
  "tts_backend" TEXT,
  "transcription_method" TEXT,
  "speaker_identity_status" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'attachments',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'attachments')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_case_observations" (
  "id" TEXT PRIMARY KEY,
  "case_id" TEXT,
  "observed_at" TIMESTAMP WITH TIME ZONE,
  "behavior" TEXT,
  "skin_description" TEXT,
  "gill_description" TEXT,
  "viscera_description" TEXT,
  "diagnosis_basis" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'case_observations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'case_observations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_cash_allocations" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "cash_transaction_id" TEXT,
  "purchase_id" TEXT,
  "settlement_id" TEXT,
  "cost_entry_id" TEXT,
  "amount_cny" NUMERIC,
  "allocation_type" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'cash_allocations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'cash_allocations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_cash_transactions" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "direction" TEXT,
  "counterparty_id" TEXT,
  "amount_cny" NUMERIC,
  "currency" TEXT,
  "payment_method" TEXT,
  "bank_reference" TEXT,
  "balance_scope" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'cash_transactions',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'cash_transactions')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_cohorts" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "pond_id" TEXT,
  "species_id" TEXT,
  "parent_cohort_id" TEXT,
  "cohort_definition" TEXT,
  "role" TEXT,
  "start_date" DATE,
  "expected_harvest_date" DATE,
  "actual_end_date" DATE,
  "initial_count" NUMERIC,
  "initial_weight_kg" NUMERIC,
  "initial_mean_weight_g" NUMERIC,
  "initial_density_fish_per_mu" NUMERIC,
  "strain" TEXT,
  "strain_status" TEXT,
  "seed_origin" TEXT,
  "original_commercial_name" TEXT,
  "brand" TEXT,
  "geographical_indication_qualified" BOOLEAN,
  "status" TEXT,
  "technical_plan_id" TEXT,
  "responsible_person_id" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'cohorts',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'cohorts')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_control_commands" (
  "id" TEXT PRIMARY KEY,
  "device_id" TEXT,
  "planned_at" TIMESTAMP WITH TIME ZONE,
  "issued_at" TIMESTAMP WITH TIME ZONE,
  "executed_at" TIMESTAMP WITH TIME ZONE,
  "command" TEXT,
  "result" TEXT,
  "alarm" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'control_commands',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'control_commands')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_cost_allocations" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "cost_entry_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "beneficiary_type" TEXT,
  "amount_cny" NUMERIC,
  "currency" TEXT,
  "allocation_basis" NUMERIC,
  "allocation_basis_unit" TEXT,
  "allocation_ratio" NUMERIC,
  "allocation_method" TEXT,
  "period_start" DATE,
  "period_end" DATE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'cost_allocations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'cost_allocations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_cost_entries" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "category" TEXT,
  "supplier_id" TEXT,
  "amount_cny" NUMERIC,
  "currency" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "source_type" TEXT,
  "source_id" TEXT,
  "cost_type" TEXT,
  "period_start" DATE,
  "period_end" DATE,
  "settlement_deduction_id" TEXT,
  "profit_treatment" TEXT,
  "allocation_method" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "recognition_method" TEXT,
  "expense_contract_start" DATE,
  "expense_contract_end" DATE,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'cost_entries',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'cost_entries')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_device_calibrations" (
  "id" TEXT PRIMARY KEY,
  "device_id" TEXT,
  "started_at" TIMESTAMP WITH TIME ZONE,
  "ended_at" TIMESTAMP WITH TIME ZONE,
  "method" TEXT,
  "reference_ph" NUMERIC,
  "offset_ph" NUMERIC,
  "result" TEXT,
  "operator_id" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'device_calibrations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'device_calibrations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_device_installations" (
  "id" TEXT PRIMARY KEY,
  "device_id" TEXT,
  "pond_id" TEXT,
  "installed_at" TIMESTAMP WITH TIME ZONE,
  "removed_at" TIMESTAMP WITH TIME ZONE,
  "effective_end_exclusive" BOOLEAN,
  "position_description" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'device_installations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'device_installations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_device_maintenance" (
  "id" TEXT PRIMARY KEY,
  "device_id" TEXT,
  "pond_id" TEXT,
  "started_at" TIMESTAMP WITH TIME ZONE,
  "ended_at" TIMESTAMP WITH TIME ZONE,
  "fault" TEXT,
  "operation" TEXT,
  "replacement_device_id" TEXT,
  "cost_yuan" NUMERIC,
  "cost_status" TEXT,
  "result" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'device_maintenance',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'device_maintenance')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_device_operations" (
  "id" TEXT PRIMARY KEY,
  "device_id" TEXT,
  "pond_id" TEXT,
  "started_at" TIMESTAMP WITH TIME ZONE,
  "ended_at" TIMESTAMP WITH TIME ZONE,
  "duration_h" NUMERIC,
  "energy_kwh" NUMERIC,
  "energy_basis" TEXT,
  "reason" TEXT,
  "command_id" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'device_operations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'device_operations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_devices" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "device_type" TEXT,
  "manufacturer" TEXT,
  "model" TEXT,
  "rated_power_kw" NUMERIC,
  "position_id" TEXT,
  "is_synthetic" BOOLEAN,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'devices',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'devices')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_diagnostic_tests" (
  "id" TEXT PRIMARY KEY,
  "case_id" TEXT,
  "lab_name" TEXT,
  "report_number" TEXT,
  "sampled_at" TIMESTAMP WITH TIME ZONE,
  "reported_at" TIMESTAMP WITH TIME ZONE,
  "pathogen_code" TEXT,
  "method" TEXT,
  "result" TEXT,
  "diagnosis_status" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'diagnostic_tests',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'diagnostic_tests')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_dictionaries" (
  "id" TEXT PRIMARY KEY,
  "domain" TEXT,
  "code" TEXT,
  "label" TEXT,
  "status" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'dictionaries',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'dictionaries')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_disposal_events" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "event_id" TEXT,
  "mortality_event_id" TEXT,
  "transfer_event_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "count" NUMERIC,
  "weight_kg" NUMERIC,
  "method" TEXT,
  "service_partner_id" TEXT,
  "cost_cny" NUMERIC,
  "certificate_id" TEXT,
  "certificate_status" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "recovery_method" TEXT,
  "transport_method" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'disposal_events',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'disposal_events')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_document_versions" (
  "id" TEXT PRIMARY KEY,
  "document_id" TEXT,
  "version" TEXT,
  "attachment_id" TEXT,
  "relative_path" TEXT,
  "sha256" TEXT,
  "published_at" DATE,
  "effective_from" DATE,
  "effective_until" DATE,
  "status" TEXT,
  "replaces_version_id" TEXT,
  "change_summary" TEXT,
  "review_status" TEXT,
  "page_reference" TEXT,
  "origin_kind" TEXT,
  "is_synthetic" BOOLEAN,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'document_versions',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'document_versions')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_documents" (
  "id" TEXT PRIMARY KEY,
  "title" TEXT,
  "document_type" TEXT,
  "publisher" TEXT,
  "language" TEXT,
  "current_version" TEXT,
  "current_version_id" TEXT,
  "published_at" DATE,
  "applicable_region" TEXT,
  "applicable_mode" TEXT,
  "full_text_path" TEXT,
  "attachment_id" TEXT,
  "sha256" TEXT,
  "source_url" TEXT,
  "source_status" TEXT,
  "license_status" TEXT,
  "authority_status" TEXT,
  "review_status" TEXT,
  "origin_kind" TEXT,
  "is_synthetic" BOOLEAN,
  "usage_limitation" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'documents',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'documents')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_event_registry" (
  "id" TEXT PRIMARY KEY,
  "event_table" TEXT,
  "event_record_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'event_registry',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'event_registry')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_farms" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "name" TEXT,
  "operator_name" TEXT,
  "address" TEXT,
  "contact" TEXT,
  "identity_status" TEXT,
  "longitude" NUMERIC,
  "latitude" NUMERIC,
  "crs" TEXT,
  "production_mode" TEXT,
  "timezone" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'farms',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'farms')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_feeding_events" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "product_id" TEXT,
  "product_batch_id" TEXT,
  "quantity_kg" NUMERIC,
  "daily_total_kg" NUMERIC,
  "unit_price_cny" NUMERIC,
  "cost_cny" NUMERIC,
  "feeding_method" TEXT,
  "device_id" TEXT,
  "feeding_area" TEXT,
  "frequency_per_day" NUMERIC,
  "feeding_intensity" TEXT,
  "leftover_status" TEXT,
  "competition_behavior" TEXT,
  "water_temperature_c" NUMERIC,
  "dissolved_oxygen_mg_l" NUMERIC,
  "weather_condition" TEXT,
  "adjustment_reason" TEXT,
  "suspended_session_count" NUMERIC,
  "suspended_session_local_time" TEXT,
  "related_environment_scenario" TEXT,
  "environment_value_basis" TEXT,
  "measurement_basis" TEXT,
  "aggregation_note" TEXT,
  "nutrition_parameter_basis" TEXT,
  "coarse_protein_pct" NUMERIC,
  "particle_diameter_mm" NUMERIC,
  "shelf_life_days" NUMERIC,
  "manufacture_on" DATE,
  "expires_on" DATE,
  "feed_brand" TEXT,
  "inventory_selection_policy" TEXT,
  "feeding_time_basis" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "water_observation_id" TEXT,
  "weather_id" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'feeding_events',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'feeding_events')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_fish_daily_balance" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "balance_date" DATE,
  "opening_count" NUMERIC,
  "stocked_count" NUMERIC,
  "transfer_in_count" NUMERIC,
  "transfer_out_count" NUMERIC,
  "mortality_count" NUMERIC,
  "harvest_count" NUMERIC,
  "adjustment_count" NUMERIC,
  "closing_count" NUMERIC,
  "opening_biomass_kg" NUMERIC,
  "stocked_weight_kg" NUMERIC,
  "transfer_in_weight_kg" NUMERIC,
  "transfer_out_weight_kg" NUMERIC,
  "mortality_weight_kg" NUMERIC,
  "harvest_weight_kg" NUMERIC,
  "growth_weight_kg" NUMERIC,
  "biomass_adjustment_kg" NUMERIC,
  "closing_biomass_kg" NUMERIC,
  "closing_mean_weight_g" NUMERIC,
  "feed_quantity_kg" NUMERIC,
  "biomass_basis" TEXT,
  "growth_basis" TEXT,
  "feed_to_growth_ratio_assumed" NUMERIC,
  "companion_growth_basis" TEXT,
  "estimate_error_kg" NUMERIC,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'fish_daily_balance',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'fish_daily_balance')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_grade_definitions" (
  "id" TEXT PRIMARY KEY,
  "species_id" TEXT,
  "grade" TEXT,
  "lower_bound_g" NUMERIC,
  "upper_bound_g" NUMERIC,
  "lower_inclusive" BOOLEAN,
  "upper_inclusive" BOOLEAN,
  "unit" TEXT,
  "version" TEXT,
  "basis" TEXT,
  "upper_bound_status" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'grade_definitions',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'grade_definitions')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_growth_grade_items" (
  "id" TEXT PRIMARY KEY,
  "sample_id" TEXT,
  "species_id" TEXT,
  "grade" TEXT,
  "commercial_grade" TEXT,
  "grade_definition_id" TEXT,
  "count" NUMERIC,
  "proportion" NUMERIC,
  "sample_weight_kg" NUMERIC,
  "weight_proportion" NUMERIC,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'growth_grade_items',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'growth_grade_items')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_growth_individuals" (
  "id" TEXT PRIMARY KEY,
  "sample_id" TEXT,
  "species_id" TEXT,
  "body_length_cm" NUMERIC,
  "total_length_cm" NUMERIC,
  "weight_g" NUMERIC,
  "commercial_grade" TEXT,
  "grade_definition_id" TEXT,
  "health_status" TEXT,
  "appearance" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'growth_individuals',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'growth_individuals')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_growth_samples" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "occupancy_id" TEXT,
  "sampled_at" TIMESTAMP WITH TIME ZONE,
  "sample_point_id" TEXT,
  "sampling_method" TEXT,
  "sample_size" NUMERIC,
  "mean_weight_g" NUMERIC,
  "min_weight_g" NUMERIC,
  "max_weight_g" NUMERIC,
  "std_weight_g" NUMERIC,
  "grade_pass_rate" NUMERIC,
  "grade_pass_definition_id" TEXT,
  "saleable_weight_ratio" NUMERIC,
  "growth_stage" TEXT,
  "estimated_count" NUMERIC,
  "estimated_biomass_kg" NUMERIC,
  "estimated_saleable_kg" NUMERIC,
  "ledger_balance_id" TEXT,
  "ledger_basis_at" TIMESTAMP WITH TIME ZONE,
  "ledger_basis_kind" TEXT,
  "ledger_basis_note" TEXT,
  "ledger_count" NUMERIC,
  "ledger_biomass_kg" NUMERIC,
  "estimate_method" TEXT,
  "estimate_relative_error" NUMERIC,
  "confidence_level" TEXT,
  "tool" TEXT,
  "operator_id" TEXT,
  "uniformity_cv" NUMERIC,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'growth_samples',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'growth_samples')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "harvest_id" TEXT,
  "harvest_grade_item_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "individual_number" TEXT,
  "grade" TEXT,
  "grade_definition_id" TEXT,
  "weight_g" NUMERIC,
  "weight_unit" TEXT,
  "weight_basis" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'harvest_grade_individuals',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'harvest_grade_individuals')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "harvest_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "grade" TEXT,
  "count" NUMERIC,
  "net_weight_kg" NUMERIC,
  "weight_ratio" NUMERIC,
  "mean_weight_g" NUMERIC,
  "quality_grade" TEXT,
  "grade_definition_id" TEXT,
  "min_weight_g" NUMERIC,
  "max_weight_g" NUMERIC,
  "grading_basis" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'harvest_grade_items',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'harvest_grade_items')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "harvest_id" TEXT,
  "harvest_grade_item_id" TEXT,
  "sale_id" TEXT,
  "sale_item_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "grade" TEXT,
  "allocated_net_weight_kg" NUMERIC,
  "allocation_basis" TEXT,
  "grade_definition_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'harvest_sale_allocations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'harvest_sale_allocations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_harvests" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "harvest_type" TEXT,
  "method" TEXT,
  "count" NUMERIC,
  "gross_weight_kg" NUMERIC,
  "tare_weight_kg" NUMERIC,
  "net_weight_kg" NUMERIC,
  "saleable_weight_kg" NUMERIC,
  "harvest_loss_count" NUMERIC,
  "harvest_loss_weight_kg" NUMERIC,
  "transport_loss_weight_kg" NUMERIC,
  "deduction_weight_kg" NUMERIC,
  "quality_grade" TEXT,
  "health_status" TEXT,
  "residue_test_status" TEXT,
  "disposition" TEXT,
  "vehicle_id" TEXT,
  "weighing_basis" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'harvests',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'harvests')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_health_cases" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "discovered_at" TIMESTAMP WITH TIME ZONE,
  "affected_count" NUMERIC,
  "incidence_rate" NUMERIC,
  "death_count" NUMERIC,
  "mortality_per_day" NUMERIC,
  "duration_days" NUMERIC,
  "diagnosis_status" TEXT,
  "preliminary_judgment" TEXT,
  "description" TEXT,
  "action" TEXT,
  "recovery" TEXT,
  "recurrence" BOOLEAN,
  "population_denominator" NUMERIC,
  "denominator_basis" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'health_cases',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'health_cases')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_inventory_lot_status" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "product_id" TEXT,
  "product_batch_id" TEXT,
  "as_of" TIMESTAMP WITH TIME ZONE,
  "closing_quantity" NUMERIC,
  "unit" TEXT,
  "closing_value_cny" NUMERIC,
  "currency" TEXT,
  "manufacture_on" DATE,
  "expires_on" DATE,
  "expiry_status" TEXT,
  "usability_status" TEXT,
  "available_quantity" NUMERIC,
  "expiry_assessment" TEXT,
  "disposal_status" TEXT,
  "valuation_basis" TEXT,
  "source_inventory_movement_id" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'inventory_lot_status',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'inventory_lot_status')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_inventory_movements" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "product_id" TEXT,
  "product_batch_id" TEXT,
  "movement_type" TEXT,
  "quantity_delta" NUMERIC,
  "unit" TEXT,
  "amount_delta_cny" NUMERIC,
  "opening_quantity" NUMERIC,
  "closing_quantity" NUMERIC,
  "opening_value_cny" NUMERIC,
  "closing_value_cny" NUMERIC,
  "lot_opening_quantity" NUMERIC,
  "lot_closing_quantity" NUMERIC,
  "lot_opening_value_cny" NUMERIC,
  "lot_closing_value_cny" NUMERIC,
  "valuation_method" TEXT,
  "source_type" TEXT,
  "source_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "movement_reason" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'inventory_movements',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'inventory_movements')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_media_annotations" (
  "id" TEXT PRIMARY KEY,
  "attachment_id" TEXT,
  "annotation_type" TEXT,
  "label" TEXT,
  "annotation_text" TEXT,
  "annotation_basis" TEXT,
  "diagnosis_status" TEXT,
  "diagnostic_training_allowed" BOOLEAN,
  "reviewer" TEXT,
  "review_status" TEXT,
  "version" TEXT,
  "frame_start" NUMERIC,
  "frame_end" NUMERIC,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'media_annotations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'media_annotations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_mortality_events" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "count" NUMERIC,
  "weight_kg" NUMERIC,
  "mean_weight_g" NUMERIC,
  "possible_cause" TEXT,
  "cause_status" TEXT,
  "related_health_case_id" TEXT,
  "discovery_location" TEXT,
  "count_basis" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'mortality_events',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'mortality_events')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_opening_balances" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "balance_type" TEXT,
  "product_id" TEXT,
  "quantity" NUMERIC,
  "unit" TEXT,
  "amount_cny" NUMERIC,
  "currency" TEXT,
  "valuation_method" TEXT,
  "as_of" TIMESTAMP WITH TIME ZONE,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "manufacture_on" DATE,
  "expires_on" DATE,
  "shelf_life_days" NUMERIC,
  "expiry_status" TEXT,
  "expiry_parameter_basis" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'opening_balances',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'opening_balances')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_partners" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "name" TEXT,
  "partner_type" TEXT,
  "identity_status" TEXT,
  "contact" TEXT,
  "contact_status" TEXT,
  "region" TEXT,
  "currency" TEXT,
  "partner_scope" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'partners',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'partners')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_patrol_events" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "operator_id" TEXT,
  "weather_id" TEXT,
  "swimming" TEXT,
  "feeding_behavior" TEXT,
  "bank_gathering" BOOLEAN,
  "water_color" TEXT,
  "transparency_cm" NUMERIC,
  "odor" TEXT,
  "algae" TEXT,
  "foam" TEXT,
  "dead_count" NUMERIC,
  "dead_weight_kg" NUMERIC,
  "dead_size_g" NUMERIC,
  "discovery_point_id" TEXT,
  "aerator_status" TEXT,
  "pump_status" TEXT,
  "feeder_status" TEXT,
  "exception_description" TEXT,
  "action" TEXT,
  "dead_size_status" TEXT,
  "mortality_event_ids" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'patrol_events',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'patrol_events')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_persons" (
  "id" TEXT PRIMARY KEY,
  "name" TEXT,
  "role" TEXT,
  "is_fictional" BOOLEAN,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'persons',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'persons')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_pond_cohort_occupancy" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "entered_at" TIMESTAMP WITH TIME ZONE,
  "left_at" TIMESTAMP WITH TIME ZONE,
  "role" TEXT,
  "entry_reason" TEXT,
  "exit_reason" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'pond_cohort_occupancy',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'pond_cohort_occupancy')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_pond_maintenance" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "operation" TEXT,
  "renovation_status" TEXT,
  "cost_basis" TEXT,
  "cost_yuan" NUMERIC,
  "operator_id" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'pond_maintenance',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'pond_maintenance')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_pond_preparations" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "previous_cohort_id" TEXT,
  "previous_cohort_status" TEXT,
  "operation" TEXT,
  "disinfectant_product_id" TEXT,
  "disinfectant_status" TEXT,
  "dose_kg" NUMERIC,
  "application_method" TEXT,
  "refill_at" TIMESTAMP WITH TIME ZONE,
  "water_source" TEXT,
  "water_level_m" NUMERIC,
  "water_test_status" TEXT,
  "equipment_check" TEXT,
  "operator_id" TEXT,
  "reviewer_id" TEXT,
  "repair_cost_yuan" NUMERIC,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'pond_preparations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'pond_preparations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_ponds" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "name" TEXT,
  "area_m2" NUMERIC,
  "area_mu" NUMERIC,
  "mean_depth_m" NUMERIC,
  "maximum_depth_m" NUMERIC,
  "effective_volume_m3" NUMERIC,
  "shape" TEXT,
  "bottom_type" TEXT,
  "inlet_condition" TEXT,
  "outlet_condition" TEXT,
  "water_source" TEXT,
  "commissioned_on" DATE,
  "current_status" TEXT,
  "geometry_id" TEXT,
  "equipment_configuration" TEXT,
  "previous_cycle_id" TEXT,
  "previous_cycle_status" TEXT,
  "centroid_longitude" NUMERIC,
  "centroid_latitude" NUMERIC,
  "maintenance_history_status" TEXT,
  "maintenance_history_note" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'ponds',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'ponds')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_price_observations" (
  "id" TEXT PRIMARY KEY,
  "observed_at" TIMESTAMP WITH TIME ZONE,
  "original_product_name" TEXT,
  "species_id" TEXT,
  "species_mapping_status" TEXT,
  "product_type" TEXT,
  "grade" TEXT,
  "commercial_grade" TEXT,
  "grade_definition_id" TEXT,
  "mapping_relation" TEXT,
  "quality_grade" TEXT,
  "freshness" TEXT,
  "region" TEXT,
  "market_id" TEXT,
  "channel" TEXT,
  "price_yuan_per_kg" NUMERIC,
  "observation_kind" TEXT,
  "transaction_volume_kg" NUMERIC,
  "volume_status" TEXT,
  "tax_included" BOOLEAN,
  "freight_included" BOOLEAN,
  "packaging_included" BOOLEAN,
  "commission_included" BOOLEAN,
  "collected_at" TIMESTAMP WITH TIME ZONE,
  "credibility" TEXT,
  "reference_source_id" TEXT,
  "origin_kind" TEXT,
  "is_synthetic" BOOLEAN,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'price_observations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'price_observations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_production_plans" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "year" NUMERIC,
  "mode" TEXT,
  "technical_document_path" TEXT,
  "responsible_person_id" TEXT,
  "start_date" DATE,
  "end_date" DATE,
  "status" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'production_plans',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'production_plans')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_products" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "product_name" TEXT,
  "product_type" TEXT,
  "unit" TEXT,
  "assumed_unit_price_cny" NUMERIC,
  "species_id" TEXT,
  "brand" TEXT,
  "brand_status" TEXT,
  "coarse_protein_pct" NUMERIC,
  "particle_diameter_mm" NUMERIC,
  "shelf_life_days" NUMERIC,
  "manufacturer" TEXT,
  "registration_number" TEXT,
  "registration_status" TEXT,
  "parameter_basis" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'products',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'products')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_purchase_items" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "purchase_id" TEXT,
  "product_id" TEXT,
  "product_batch_id" TEXT,
  "quantity" NUMERIC,
  "unit" TEXT,
  "unit_price_cny" NUMERIC,
  "amount_cny" NUMERIC,
  "supplier_id" TEXT,
  "valuation_method" TEXT,
  "transaction_time_basis" TEXT,
  "manufacture_on" DATE,
  "expires_on" DATE,
  "expiry_status" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'purchase_items',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'purchase_items')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_purchases" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "supplier_id" TEXT,
  "invoice_number" TEXT,
  "invoice_status" TEXT,
  "contract_number" TEXT,
  "gross_amount_cny" NUMERIC,
  "amount_cny" NUMERIC,
  "currency" TEXT,
  "tax_status" TEXT,
  "received_on" DATE,
  "received_at" TIMESTAMP WITH TIME ZONE,
  "purchase_time_basis" TEXT,
  "is_consumption_cost" BOOLEAN,
  "payment_status" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'purchases',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'purchases')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_sale_items" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "sale_id" TEXT,
  "species_id" TEXT,
  "grade" TEXT,
  "quality_grade" TEXT,
  "net_weight_kg" NUMERIC,
  "unit_price_cny_per_kg" NUMERIC,
  "amount_cny" NUMERIC,
  "discount_cny" NUMERIC,
  "original_commercial_name" TEXT,
  "species_mapping_status" TEXT,
  "brand" TEXT,
  "origin" TEXT,
  "geographical_indication_qualified" BOOLEAN,
  "grade_definition_id" TEXT,
  "price_basis" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'sale_items',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'sale_items')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_sales" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "customer_id" TEXT,
  "species_id" TEXT,
  "channel" TEXT,
  "contract_number" TEXT,
  "order_number" TEXT,
  "currency" TEXT,
  "tax_status" TEXT,
  "freight_bearer" TEXT,
  "commission_bearer" TEXT,
  "invoice_status" TEXT,
  "invoice_on" DATE,
  "live_status" TEXT,
  "gross_revenue_cny" NUMERIC,
  "net_weight_kg" NUMERIC,
  "gross_weight_kg" NUMERIC,
  "tare_weight_kg" NUMERIC,
  "return_weight_kg" NUMERIC,
  "actual_trade" BOOLEAN,
  "quote_observation_id" TEXT,
  "price_basis" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'sales',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'sales')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_settlement_deductions" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "settlement_id" TEXT,
  "sale_id" TEXT,
  "deduction_type" TEXT,
  "amount_cny" NUMERIC,
  "currency" TEXT,
  "payer" TEXT,
  "recognition" TEXT,
  "cost_entry_id" TEXT,
  "source_document_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'settlement_deductions',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'settlement_deductions')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_settlements" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "sale_id" TEXT,
  "customer_id" TEXT,
  "gross_sales_amount_cny" NUMERIC,
  "deductions_amount_cny" NUMERIC,
  "net_amount_cny" NUMERIC,
  "received_amount_cny" NUMERIC,
  "outstanding_amount_cny" NUMERIC,
  "actual_net_unit_price_cny_per_kg" NUMERIC,
  "payment_terms_days" NUMERIC,
  "due_on" DATE,
  "final_received_on" DATE,
  "currency" TEXT,
  "status" TEXT,
  "profit_basis" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'settlements',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'settlements')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_source_registry" (
  "id" TEXT PRIMARY KEY,
  "table" TEXT,
  "origin_kind" TEXT,
  "generation_run_id" TEXT,
  "seed" NUMERIC,
  "rule_version" TEXT,
  "timezone" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'source_registry',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'source_registry')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_sources" (
  "id" TEXT PRIMARY KEY,
  "title" TEXT,
  "url" TEXT,
  "origin_kind" TEXT,
  "is_synthetic" BOOLEAN,
  "local_path" TEXT,
  "access_conditions" TEXT,
  "retrieved_at" TEXT,
  "use_boundary" TEXT,
  "version" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'sources',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'sources')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_spatial_layer_registry" (
  "id" TEXT PRIMARY KEY,
  "attachment_id" TEXT,
  "layer_name" TEXT,
  "geometry_kind" TEXT,
  "crs" TEXT,
  "coordinate_order" TEXT,
  "captured_at" TIMESTAMP WITH TIME ZONE,
  "version" TEXT,
  "resolution_m" NUMERIC,
  "resolution_degrees" TEXT,
  "accuracy_m" NUMERIC,
  "accuracy_status" TEXT,
  "scale_status" TEXT,
  "source" TEXT,
  "feature_count" NUMERIC,
  "bbox" TEXT,
  "coverage" TEXT,
  "relative_path" TEXT,
  "sha256" TEXT,
  "is_synthetic" BOOLEAN,
  "usage_limitation" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'spatial_layer_registry',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'spatial_layer_registry')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_species" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "standard_name" TEXT,
  "scientific_name" TEXT,
  "original_name" TEXT,
  "species_code" TEXT,
  "common_commercial_name" TEXT,
  "mapping_status" TEXT,
  "mapping_basis" TEXT,
  "strain" TEXT,
  "strain_status" TEXT,
  "origin" TEXT,
  "brand" TEXT,
  "brand_status" TEXT,
  "geographical_indication_qualified" BOOLEAN,
  "geographical_indication_status" TEXT,
  "default_role" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'species',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'species')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_stocking_events" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "purchase_item_id" TEXT,
  "product_id" TEXT,
  "seed_batch_id" TEXT,
  "supplier_id" TEXT,
  "count" NUMERIC,
  "weight_kg" NUMERIC,
  "mean_weight_g" NUMERIC,
  "size_distribution" TEXT,
  "stocking_density_fish_per_mu" NUMERIC,
  "unit_price_cny" NUMERIC,
  "total_cost_cny" NUMERIC,
  "transport_method" TEXT,
  "transport_duration_hours" NUMERIC,
  "transport_mortality_count" NUMERIC,
  "transport_mortality_rate" NUMERIC,
  "health_status" TEXT,
  "quarantine_certificate_id" TEXT,
  "quarantine_status" TEXT,
  "water_temperature_c" NUMERIC,
  "dissolved_oxygen_mg_l" NUMERIC,
  "temperature_difference_c" NUMERIC,
  "acclimation_method" TEXT,
  "count_basis" TEXT,
  "weight_basis" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'stocking_events',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'stocking_events')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "transfer_event_id" TEXT,
  "source_pond_id" TEXT,
  "source_cohort_id" TEXT,
  "target_pond_id" TEXT,
  "target_cohort_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "count" NUMERIC,
  "weight_kg" NUMERIC,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'transfer_allocations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'transfer_allocations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_transfer_events" (
  "id" TEXT PRIMARY KEY,
  "farm_id" TEXT,
  "occurred_at" TIMESTAMP WITH TIME ZONE,
  "source_pond_id" TEXT,
  "source_cohort_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "species_id" TEXT,
  "transferred_out_count" NUMERIC,
  "transferred_out_weight_kg" NUMERIC,
  "received_count" NUMERIC,
  "received_weight_kg" NUMERIC,
  "loss_count" NUMERIC,
  "loss_weight_kg" NUMERIC,
  "reason" TEXT,
  "mean_weight_g" NUMERIC,
  "size_basis" TEXT,
  "loss_cause" TEXT,
  "operation_person_id" TEXT,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "uploaded_at" TIMESTAMP WITH TIME ZONE,
  "ingested_at" TIMESTAMP WITH TIME ZONE,
  "updated_at" TIMESTAMP WITH TIME ZONE,
  "event_id" TEXT,
  "source_record_id" TEXT,
  "recorder_id" TEXT,
  "reviewer_id" TEXT,
  "source_system" TEXT,
  "review_status" TEXT,
  "quality_flag" TEXT,
  "is_estimated" BOOLEAN,
  "source_timezone" TEXT,
  "time_precision" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'transfer_events',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'transfer_events')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_treatment_events" (
  "id" TEXT PRIMARY KEY,
  "case_id" TEXT,
  "pond_id" TEXT,
  "cohort_id" TEXT,
  "started_at" TIMESTAMP WITH TIME ZONE,
  "stopped_at" TIMESTAMP WITH TIME ZONE,
  "operation_reason" TEXT,
  "product_id" TEXT,
  "product_name" TEXT,
  "approval_number" TEXT,
  "manufacturer_lot" TEXT,
  "active_ingredient" TEXT,
  "dose" NUMERIC,
  "concentration" NUMERIC,
  "method" TEXT,
  "course_days" NUMERIC,
  "target_species" TEXT,
  "target_disease" TEXT,
  "contraindications" TEXT,
  "withdrawal_days" NUMERIC,
  "withdrawal_status" TEXT,
  "earliest_harvest_date" DATE,
  "product_parameter_status" TEXT,
  "operator_id" TEXT,
  "advisor_id" TEXT,
  "purchase_cost_yuan" NUMERIC,
  "effect" TEXT,
  "adverse_reaction" TEXT,
  "execution_status" TEXT,
  "precautions" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'treatment_events',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'treatment_events')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_water_observations" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "device_id" TEXT,
  "observed_at" TIMESTAMP WITH TIME ZONE,
  "recorded_at" TIMESTAMP WITH TIME ZONE,
  "sample_point_id" TEXT,
  "depth_m" NUMERIC,
  "temperature_c" NUMERIC,
  "do_mg_l" NUMERIC,
  "ph" NUMERIC,
  "raw_ph" NUMERIC,
  "ph_correction" NUMERIC,
  "method" TEXT,
  "measurement_context" TEXT,
  "environment_condition" TEXT,
  "quality_flag" TEXT,
  "missing_reason" TEXT,
  "review_status" TEXT,
  "weather_id" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'water_observations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'water_observations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_water_operations" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "started_at" TIMESTAMP WITH TIME ZONE,
  "ended_at" TIMESTAMP WITH TIME ZONE,
  "operation" TEXT,
  "inflow_m3" NUMERIC,
  "outflow_m3" NUMERIC,
  "water_source" TEXT,
  "product_id" TEXT,
  "dose_kg" NUMERIC,
  "dose_status" TEXT,
  "do_before_mg_l" NUMERIC,
  "do_after_mg_l" NUMERIC,
  "fish_before" TEXT,
  "fish_after" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'water_operations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'water_operations')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_water_samples" (
  "id" TEXT PRIMARY KEY,
  "pond_id" TEXT,
  "sampled_at" TIMESTAMP WITH TIME ZONE,
  "sample_point_id" TEXT,
  "depth_m" NUMERIC,
  "sampler_id" TEXT,
  "received_at" TIMESTAMP WITH TIME ZONE,
  "lab_name" TEXT,
  "sampling_method" TEXT,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'water_samples',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'water_samples')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_water_test_results" (
  "id" TEXT PRIMARY KEY,
  "sample_id" TEXT,
  "analyte_code" TEXT,
  "value" NUMERIC,
  "raw_value" TEXT,
  "corrected_value" NUMERIC,
  "unit" TEXT,
  "expression_basis" TEXT,
  "method" TEXT,
  "instrument_id" TEXT,
  "detection_limit" NUMERIC,
  "result_status" TEXT,
  "missing_reason" TEXT,
  "verified_by" TEXT,
  "reported_at" TIMESTAMP WITH TIME ZONE,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'water_test_results',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'water_test_results')
);

CREATE TABLE "csv_batch_a4d78be79a83"."data_weather_observations" (
  "id" TEXT PRIMARY KEY,
  "observed_at" TIMESTAMP WITH TIME ZONE,
  "air_temperature_c" NUMERIC,
  "relative_humidity_pct" NUMERIC,
  "precipitation_mm" NUMERIC,
  "shortwave_w_m2" NUMERIC,
  "wind_speed_km_h" NUMERIC,
  "grid_id" TEXT,
  "grid_latitude" NUMERIC,
  "grid_longitude" NUMERIC,
  "requested_latitude" NUMERIC,
  "requested_longitude" NUMERIC,
  "model" TEXT,
  "spatial_resolution_degree" NUMERIC,
  "timezone" TEXT,
  "reference_source_id" TEXT,
  "origin_kind" TEXT,
  "is_synthetic" BOOLEAN,
  "_node_id" UUID NOT NULL UNIQUE,
  "_source_row" BIGINT NOT NULL,
  "_data_nature" TEXT NOT NULL,
  "_source_table" TEXT NOT NULL DEFAULT 'weather_observations',
  FOREIGN KEY ("_node_id") REFERENCES "csv_batch_a4d78be79a83"."ontology_nodes" ("node_id"),
  FOREIGN KEY ("_source_table", "_source_row") REFERENCES "csv_batch_a4d78be79a83"."raw_records" ("table_name", "row_number"),
  CHECK ("_source_table" = 'weather_observations')
);

ALTER TABLE "csv_batch_a4d78be79a83"."data_farms" ADD CONSTRAINT "csv_fk_2c83a477d5c935c11378" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_ponds" ADD CONSTRAINT "csv_fk_1286f4c9d83099a4a10b" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_species" ADD CONSTRAINT "csv_fk_becf5b8e5c8d233bf030" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cohorts" ADD CONSTRAINT "csv_fk_871cc6fd4da328278630" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cohorts" ADD CONSTRAINT "csv_fk_49169f6ff67d26d26278" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cohorts" ADD CONSTRAINT "csv_fk_206fc456d5f6ed386c91" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cohorts" ADD CONSTRAINT "csv_fk_d9065979890cb8c0c3ba" FOREIGN KEY ("parent_cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cohorts" ADD CONSTRAINT "csv_fk_55e9ababa3e847a04b5b" FOREIGN KEY ("technical_plan_id") REFERENCES "csv_batch_a4d78be79a83"."data_production_plans" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cohorts" ADD CONSTRAINT "csv_fk_06694af131010bf642a5" FOREIGN KEY ("responsible_person_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_cohort_occupancy" ADD CONSTRAINT "csv_fk_4b58f1da76b951310aec" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_cohort_occupancy" ADD CONSTRAINT "csv_fk_57e00be3227f2a0d6c7f" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_cohort_occupancy" ADD CONSTRAINT "csv_fk_e1973c1e689fae14d6ca" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_cohort_occupancy" ADD CONSTRAINT "csv_fk_716a3d22f8c00b067fe6" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_cohort_occupancy" ADD CONSTRAINT "csv_fk_93a87de09950927c443d" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_4b101a92cc1be64e04ca" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_fa2b21be72928a81af3a" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_e9a5d5dba3bb9ee494a7" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_67d0b7d2ad4b129a6889" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_663c3b39dcab3f9b80bd" FOREIGN KEY ("purchase_item_id") REFERENCES "csv_batch_a4d78be79a83"."data_purchase_items" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_79662ac2547acd9be2bd" FOREIGN KEY ("product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_144d2558913825cd07b4" FOREIGN KEY ("supplier_id") REFERENCES "csv_batch_a4d78be79a83"."data_partners" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_b731cdc5878b529dcd91" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_stocking_events" ADD CONSTRAINT "csv_fk_b67fb3ce1831304c90f6" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_aea34f573d4562d70e20" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_46b346ddaad5aa83d0e1" FOREIGN KEY ("source_pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_9ead78131ab8ff25d4b4" FOREIGN KEY ("source_cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_898b5605fe6f31397f91" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_66007c0d114b11e60712" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_b6008d4df5481eeb20d3" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_2e77f09d71b1645fa0e7" FOREIGN KEY ("operation_person_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_7f0be202f9a12158ba17" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_events" ADD CONSTRAINT "csv_fk_1c5d5d59de62aca48a1c" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_ae45cf25c71a14e69bb2" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_4b13e73c9cde9f62b244" FOREIGN KEY ("transfer_event_id") REFERENCES "csv_batch_a4d78be79a83"."data_transfer_events" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_2e39f1c541d893c9900c" FOREIGN KEY ("source_pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_16575b040939deff6356" FOREIGN KEY ("source_cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_94a80b0e00f8092fbf2a" FOREIGN KEY ("target_pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_9a84e127fa49532c6800" FOREIGN KEY ("target_cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_81039ed9c224b1f78212" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_f8f8eb72f06d13bc37f0" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_b12a9fefb4a79b5d9a63" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_1a9b114a942983d34bf6" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_mortality_events" ADD CONSTRAINT "csv_fk_6656b5a46ef100b527e0" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_mortality_events" ADD CONSTRAINT "csv_fk_9ee77bb6ad21773947b1" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_mortality_events" ADD CONSTRAINT "csv_fk_740d817dae301c336e40" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_mortality_events" ADD CONSTRAINT "csv_fk_cf17321a406278b9d13c" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_mortality_events" ADD CONSTRAINT "csv_fk_dec5174ea4330be4f6dd" FOREIGN KEY ("related_health_case_id") REFERENCES "csv_batch_a4d78be79a83"."data_health_cases" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_mortality_events" ADD CONSTRAINT "csv_fk_b274a59b358a71190f57" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_mortality_events" ADD CONSTRAINT "csv_fk_81534280961fa9f6b701" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_disposal_events" ADD CONSTRAINT "csv_fk_f5105f8f02ac33be44a3" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_disposal_events" ADD CONSTRAINT "csv_fk_a6c417a521393be79a95" FOREIGN KEY ("mortality_event_id") REFERENCES "csv_batch_a4d78be79a83"."data_mortality_events" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_disposal_events" ADD CONSTRAINT "csv_fk_7f23a5ea80be130d9139" FOREIGN KEY ("transfer_event_id") REFERENCES "csv_batch_a4d78be79a83"."data_transfer_events" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_disposal_events" ADD CONSTRAINT "csv_fk_7db71cf3f65cb33cb65a" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_disposal_events" ADD CONSTRAINT "csv_fk_da3ebadd80ef67879c72" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_disposal_events" ADD CONSTRAINT "csv_fk_f296d6016b9a54fb0bc3" FOREIGN KEY ("service_partner_id") REFERENCES "csv_batch_a4d78be79a83"."data_partners" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_disposal_events" ADD CONSTRAINT "csv_fk_c457e333ce3810a2dde6" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_disposal_events" ADD CONSTRAINT "csv_fk_63d512c91b798517b084" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_fish_daily_balance" ADD CONSTRAINT "csv_fk_047d918140c4d783568c" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_fish_daily_balance" ADD CONSTRAINT "csv_fk_e293f0eafe01a2fde23b" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_fish_daily_balance" ADD CONSTRAINT "csv_fk_46a4f52cdfb5a1cb9289" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_fish_daily_balance" ADD CONSTRAINT "csv_fk_102bf5d118011e49939b" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_fish_daily_balance" ADD CONSTRAINT "csv_fk_41f48484a5dcc45ba867" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_fish_daily_balance" ADD CONSTRAINT "csv_fk_28a2e64f41e45127ed32" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_2a20cb530d029c0956e4" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_9162977ca19d14e85617" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_68f160b11fe9a2f1953f" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_f3c811275bf5fc55724c" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_f1206df25854cf6f5f42" FOREIGN KEY ("product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_be46cdc99733634d42a6" FOREIGN KEY ("device_id") REFERENCES "csv_batch_a4d78be79a83"."data_devices" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_775fe5ee924bf3f8f184" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_2620cec501bc8a9c3949" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_c9846d310b5aac6b4a20" FOREIGN KEY ("water_observation_id") REFERENCES "csv_batch_a4d78be79a83"."data_water_observations" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_feeding_events" ADD CONSTRAINT "csv_fk_7a7edece074e1503441c" FOREIGN KEY ("weather_id") REFERENCES "csv_batch_a4d78be79a83"."data_weather_observations" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_products" ADD CONSTRAINT "csv_fk_9d9582b038ef9e8d44ff" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_products" ADD CONSTRAINT "csv_fk_23ebe0e953a2ab6b00a7" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_partners" ADD CONSTRAINT "csv_fk_f471dbf68e8019f2db54" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchases" ADD CONSTRAINT "csv_fk_9cfb6b0f56b3acb0bad2" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchases" ADD CONSTRAINT "csv_fk_f99c981361d4d5e8726d" FOREIGN KEY ("supplier_id") REFERENCES "csv_batch_a4d78be79a83"."data_partners" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchases" ADD CONSTRAINT "csv_fk_3bb1d4587df4bec38f3f" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchases" ADD CONSTRAINT "csv_fk_0e0826ff4ddb0c94124a" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchase_items" ADD CONSTRAINT "csv_fk_82e0eceb56954a3cc82e" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchase_items" ADD CONSTRAINT "csv_fk_1d0acc4bc10e21f89b42" FOREIGN KEY ("purchase_id") REFERENCES "csv_batch_a4d78be79a83"."data_purchases" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchase_items" ADD CONSTRAINT "csv_fk_427bc24ce80e3d4173a7" FOREIGN KEY ("product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchase_items" ADD CONSTRAINT "csv_fk_8e622393c2aa1128e35f" FOREIGN KEY ("supplier_id") REFERENCES "csv_batch_a4d78be79a83"."data_partners" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchase_items" ADD CONSTRAINT "csv_fk_d87c56bfb136600f683f" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_purchase_items" ADD CONSTRAINT "csv_fk_7fcc749bb59b3377f1a5" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_movements" ADD CONSTRAINT "csv_fk_4986db1cdc64881bbba7" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_movements" ADD CONSTRAINT "csv_fk_f181a837bd3a64b4e797" FOREIGN KEY ("product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_movements" ADD CONSTRAINT "csv_fk_0dfcaf09e1ae83633458" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_movements" ADD CONSTRAINT "csv_fk_273440e29edcadad8726" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_movements" ADD CONSTRAINT "csv_fk_8026923b7b79640d4fbd" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_movements" ADD CONSTRAINT "csv_fk_74d26f7106716e80937b" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_opening_balances" ADD CONSTRAINT "csv_fk_87fc8601e69511c257d1" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_opening_balances" ADD CONSTRAINT "csv_fk_f11889597af7c8ae698f" FOREIGN KEY ("product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_opening_balances" ADD CONSTRAINT "csv_fk_6c27e5a8ce5a67c44ffb" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_opening_balances" ADD CONSTRAINT "csv_fk_c45ccedfec905bb8fdf5" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_opening_balances" ADD CONSTRAINT "csv_fk_3c991516c8eb525fca99" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_opening_balances" ADD CONSTRAINT "csv_fk_ffa9d1a569d232bfe9d6" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvests" ADD CONSTRAINT "csv_fk_4148ee40952619276f8a" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvests" ADD CONSTRAINT "csv_fk_634cb7606ea10298cb6f" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvests" ADD CONSTRAINT "csv_fk_3e21112fddc297deb7b8" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvests" ADD CONSTRAINT "csv_fk_c8efb16727c348564f06" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvests" ADD CONSTRAINT "csv_fk_d8bb861cfeca0382882b" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvests" ADD CONSTRAINT "csv_fk_ba3981ec3a5941d1ea50" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_3ed97616aa2387e94ada" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_12cc6018af31dd50608d" FOREIGN KEY ("harvest_id") REFERENCES "csv_batch_a4d78be79a83"."data_harvests" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_3ce2bedaf53af14667a2" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_a1b44213703fe94d98cc" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_781fa0f00a9e2ae44872" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_d063cbd478aa4e564b3a" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_92819a7061ecb198f1ce" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sales" ADD CONSTRAINT "csv_fk_6b404441b9d411e9e814" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sales" ADD CONSTRAINT "csv_fk_7eff622dc847ca6ff61b" FOREIGN KEY ("customer_id") REFERENCES "csv_batch_a4d78be79a83"."data_partners" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sales" ADD CONSTRAINT "csv_fk_2df96212355a50c57839" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sales" ADD CONSTRAINT "csv_fk_9f3a04106f77233d31e7" FOREIGN KEY ("quote_observation_id") REFERENCES "csv_batch_a4d78be79a83"."data_price_observations" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sales" ADD CONSTRAINT "csv_fk_e5cfdb32aeac3428d9e4" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sales" ADD CONSTRAINT "csv_fk_c1e9c08355e93a65e8b6" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sale_items" ADD CONSTRAINT "csv_fk_22c69fdfa9b85e2e546d" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sale_items" ADD CONSTRAINT "csv_fk_4ae7c9316a708827822b" FOREIGN KEY ("sale_id") REFERENCES "csv_batch_a4d78be79a83"."data_sales" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sale_items" ADD CONSTRAINT "csv_fk_4475ec0dfabda965b93e" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sale_items" ADD CONSTRAINT "csv_fk_6591cdcfbb9e60fefbc7" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sale_items" ADD CONSTRAINT "csv_fk_698dad8bf8d883f847cc" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_cea44029dca99c29b86f" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_b74035c1b208119ffd19" FOREIGN KEY ("harvest_id") REFERENCES "csv_batch_a4d78be79a83"."data_harvests" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_e633e19fa1f85e8ae759" FOREIGN KEY ("harvest_grade_item_id") REFERENCES "csv_batch_a4d78be79a83"."data_harvest_grade_items" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_def2211cca0d5859b564" FOREIGN KEY ("sale_id") REFERENCES "csv_batch_a4d78be79a83"."data_sales" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_80cbb6358a3fc29fb6e7" FOREIGN KEY ("sale_item_id") REFERENCES "csv_batch_a4d78be79a83"."data_sale_items" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_c6c7af4e83499b7877e9" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_1e38b879fcf439bc033a" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_d55acba2697d4ff24fea" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_8df254e3c3bf3eaf327a" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_655f8e53a1dafbf523b8" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlements" ADD CONSTRAINT "csv_fk_dd7c01d34b6b8b023d5a" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlements" ADD CONSTRAINT "csv_fk_3b2f26c23d6ac378b7a6" FOREIGN KEY ("sale_id") REFERENCES "csv_batch_a4d78be79a83"."data_sales" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlements" ADD CONSTRAINT "csv_fk_94500a6238bd9751d41e" FOREIGN KEY ("customer_id") REFERENCES "csv_batch_a4d78be79a83"."data_partners" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlements" ADD CONSTRAINT "csv_fk_a0e8b2234c33575b56c0" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlements" ADD CONSTRAINT "csv_fk_66a1e0e999b0271885f9" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlement_deductions" ADD CONSTRAINT "csv_fk_cc775948337271683de4" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlement_deductions" ADD CONSTRAINT "csv_fk_948371959275042d4f7e" FOREIGN KEY ("settlement_id") REFERENCES "csv_batch_a4d78be79a83"."data_settlements" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlement_deductions" ADD CONSTRAINT "csv_fk_99fee612c68cf37f2b79" FOREIGN KEY ("sale_id") REFERENCES "csv_batch_a4d78be79a83"."data_sales" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlement_deductions" ADD CONSTRAINT "csv_fk_3315727c0e7ab2c86f86" FOREIGN KEY ("cost_entry_id") REFERENCES "csv_batch_a4d78be79a83"."data_cost_entries" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlement_deductions" ADD CONSTRAINT "csv_fk_95becf4c5df94da44f6a" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_settlement_deductions" ADD CONSTRAINT "csv_fk_c124470ab852a5089230" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_transactions" ADD CONSTRAINT "csv_fk_848792a8f7d431ed24e7" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_transactions" ADD CONSTRAINT "csv_fk_519618e683bc6cb8dc4f" FOREIGN KEY ("counterparty_id") REFERENCES "csv_batch_a4d78be79a83"."data_partners" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_transactions" ADD CONSTRAINT "csv_fk_22908f17720bd7b35ff3" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_transactions" ADD CONSTRAINT "csv_fk_582369e2bda49359460b" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_allocations" ADD CONSTRAINT "csv_fk_d6ce83938f939ae9e367" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_allocations" ADD CONSTRAINT "csv_fk_9df1632a08fdd03b9a1e" FOREIGN KEY ("cash_transaction_id") REFERENCES "csv_batch_a4d78be79a83"."data_cash_transactions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_allocations" ADD CONSTRAINT "csv_fk_6e40d9a5f3b28582d4bb" FOREIGN KEY ("purchase_id") REFERENCES "csv_batch_a4d78be79a83"."data_purchases" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_allocations" ADD CONSTRAINT "csv_fk_b0245d1b91494b152c4b" FOREIGN KEY ("settlement_id") REFERENCES "csv_batch_a4d78be79a83"."data_settlements" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_allocations" ADD CONSTRAINT "csv_fk_f1036e14928f3de31a8a" FOREIGN KEY ("cost_entry_id") REFERENCES "csv_batch_a4d78be79a83"."data_cost_entries" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_allocations" ADD CONSTRAINT "csv_fk_f140b224ae19ee2c3755" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cash_allocations" ADD CONSTRAINT "csv_fk_975f9eb8ba4adc8aeecb" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_entries" ADD CONSTRAINT "csv_fk_911b1e5de6ae74316105" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_entries" ADD CONSTRAINT "csv_fk_410f83e67f3f90e972ba" FOREIGN KEY ("supplier_id") REFERENCES "csv_batch_a4d78be79a83"."data_partners" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_entries" ADD CONSTRAINT "csv_fk_91c7cd60f88403dc7b38" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_entries" ADD CONSTRAINT "csv_fk_488a0d44671e65ffe688" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_entries" ADD CONSTRAINT "csv_fk_6b360145b9fff6f9dba4" FOREIGN KEY ("settlement_deduction_id") REFERENCES "csv_batch_a4d78be79a83"."data_settlement_deductions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_entries" ADD CONSTRAINT "csv_fk_35c38385d1b30dffac49" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_entries" ADD CONSTRAINT "csv_fk_7363fbeaa10e1cecafe1" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_allocations" ADD CONSTRAINT "csv_fk_cd786cc37e7fb353b086" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_allocations" ADD CONSTRAINT "csv_fk_dba2a72da3c95b5b500d" FOREIGN KEY ("cost_entry_id") REFERENCES "csv_batch_a4d78be79a83"."data_cost_entries" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_allocations" ADD CONSTRAINT "csv_fk_148a3fec5d25ee5cef2c" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_allocations" ADD CONSTRAINT "csv_fk_ec17893fa0f1abec00b3" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_allocations" ADD CONSTRAINT "csv_fk_0efe7f4fe1fcc02178de" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_cost_allocations" ADD CONSTRAINT "csv_fk_843d6389904e953b42de" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_lot_status" ADD CONSTRAINT "csv_fk_bdfe7c950537ec0b7941" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_lot_status" ADD CONSTRAINT "csv_fk_db87fb8d171005d144a8" FOREIGN KEY ("product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_lot_status" ADD CONSTRAINT "csv_fk_f9c3f014c3a57a03bf42" FOREIGN KEY ("source_inventory_movement_id") REFERENCES "csv_batch_a4d78be79a83"."data_inventory_movements" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_lot_status" ADD CONSTRAINT "csv_fk_4d27dcf5eee7856d8f23" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_inventory_lot_status" ADD CONSTRAINT "csv_fk_61af59d4ff9d05a730ec" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_weather_observations" ADD CONSTRAINT "csv_fk_b8d80134dbaf5f368051" FOREIGN KEY ("reference_source_id") REFERENCES "csv_batch_a4d78be79a83"."data_sources" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_devices" ADD CONSTRAINT "csv_fk_c585b32c90b8b9d72da9" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_installations" ADD CONSTRAINT "csv_fk_89b98278c4b30d38902a" FOREIGN KEY ("device_id") REFERENCES "csv_batch_a4d78be79a83"."data_devices" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_installations" ADD CONSTRAINT "csv_fk_ed4705c23251ab7c3d6d" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_calibrations" ADD CONSTRAINT "csv_fk_d579b7f1efd79a930679" FOREIGN KEY ("device_id") REFERENCES "csv_batch_a4d78be79a83"."data_devices" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_calibrations" ADD CONSTRAINT "csv_fk_b8ded9a8c2008a8a7197" FOREIGN KEY ("operator_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_preparations" ADD CONSTRAINT "csv_fk_2263db138400675cc519" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_preparations" ADD CONSTRAINT "csv_fk_6b058f3156b7ecdf6ddb" FOREIGN KEY ("operator_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_preparations" ADD CONSTRAINT "csv_fk_39d6aecc92e4841bd9df" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_observations" ADD CONSTRAINT "csv_fk_9e44768a43ceac7761b7" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_observations" ADD CONSTRAINT "csv_fk_367b35dafbdb65aa791c" FOREIGN KEY ("device_id") REFERENCES "csv_batch_a4d78be79a83"."data_devices" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_observations" ADD CONSTRAINT "csv_fk_e9dff9c488fea5fda052" FOREIGN KEY ("weather_id") REFERENCES "csv_batch_a4d78be79a83"."data_weather_observations" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_patrol_events" ADD CONSTRAINT "csv_fk_358dc67ce30ad2640b68" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_patrol_events" ADD CONSTRAINT "csv_fk_75fe7dfdf0ddbc1c4402" FOREIGN KEY ("operator_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_patrol_events" ADD CONSTRAINT "csv_fk_0cb86c55bfe449d195d7" FOREIGN KEY ("weather_id") REFERENCES "csv_batch_a4d78be79a83"."data_weather_observations" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_operations" ADD CONSTRAINT "csv_fk_78f7aa7253ace1086cd2" FOREIGN KEY ("device_id") REFERENCES "csv_batch_a4d78be79a83"."data_devices" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_operations" ADD CONSTRAINT "csv_fk_7f7f5aa0c5c5735d0c5b" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_operations" ADD CONSTRAINT "csv_fk_549bfe3f9a3200755066" FOREIGN KEY ("command_id") REFERENCES "csv_batch_a4d78be79a83"."data_control_commands" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_control_commands" ADD CONSTRAINT "csv_fk_d22f7e163d0b96492b70" FOREIGN KEY ("device_id") REFERENCES "csv_batch_a4d78be79a83"."data_devices" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_samples" ADD CONSTRAINT "csv_fk_db664bcdc85603ed3a7a" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_samples" ADD CONSTRAINT "csv_fk_4b59d7b6ebe9d2afb494" FOREIGN KEY ("sampler_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_test_results" ADD CONSTRAINT "csv_fk_8ca2415ddf0d63b9bac6" FOREIGN KEY ("sample_id") REFERENCES "csv_batch_a4d78be79a83"."data_water_samples" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_test_results" ADD CONSTRAINT "csv_fk_291e7b7845ebb149f9ee" FOREIGN KEY ("verified_by") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_operations" ADD CONSTRAINT "csv_fk_c7dfe790e323f7a5e6d5" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_water_operations" ADD CONSTRAINT "csv_fk_996b0295e8d910d01880" FOREIGN KEY ("product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_maintenance" ADD CONSTRAINT "csv_fk_60f5516b7f04ed35c0bd" FOREIGN KEY ("device_id") REFERENCES "csv_batch_a4d78be79a83"."data_devices" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_maintenance" ADD CONSTRAINT "csv_fk_f436c57397177d8b16ba" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_individuals" ADD CONSTRAINT "csv_fk_1beba7fa028e96c46cd1" FOREIGN KEY ("sample_id") REFERENCES "csv_batch_a4d78be79a83"."data_growth_samples" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_samples" ADD CONSTRAINT "csv_fk_f10d5deef448f77c15df" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_samples" ADD CONSTRAINT "csv_fk_b9fa4179919290b5bf6d" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_samples" ADD CONSTRAINT "csv_fk_fe1d09b31cbc55305af9" FOREIGN KEY ("operator_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_grade_items" ADD CONSTRAINT "csv_fk_47d9c8d4fbc7cd8bc10f" FOREIGN KEY ("sample_id") REFERENCES "csv_batch_a4d78be79a83"."data_growth_samples" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_health_cases" ADD CONSTRAINT "csv_fk_98e5ef6c74918ec892f0" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_health_cases" ADD CONSTRAINT "csv_fk_3237711e45158fb040ba" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_case_observations" ADD CONSTRAINT "csv_fk_c396b6011862e7eb5a44" FOREIGN KEY ("case_id") REFERENCES "csv_batch_a4d78be79a83"."data_health_cases" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_diagnostic_tests" ADD CONSTRAINT "csv_fk_3146f7979aea00d1d8ae" FOREIGN KEY ("case_id") REFERENCES "csv_batch_a4d78be79a83"."data_health_cases" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_treatment_events" ADD CONSTRAINT "csv_fk_8d2425c192a3dcfe2099" FOREIGN KEY ("case_id") REFERENCES "csv_batch_a4d78be79a83"."data_health_cases" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_treatment_events" ADD CONSTRAINT "csv_fk_2b2360ebaa37a6973b7f" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_treatment_events" ADD CONSTRAINT "csv_fk_8b04b2afe11ef62070fb" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_treatment_events" ADD CONSTRAINT "csv_fk_5c0e7e482270160cef66" FOREIGN KEY ("product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_treatment_events" ADD CONSTRAINT "csv_fk_219bc9dc083cbce3629d" FOREIGN KEY ("operator_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_treatment_events" ADD CONSTRAINT "csv_fk_dc8db20e0aca2fc626fe" FOREIGN KEY ("advisor_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_price_observations" ADD CONSTRAINT "csv_fk_bf13e06b5451bd7edab1" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_price_observations" ADD CONSTRAINT "csv_fk_1319e804d5c8f0c18dc2" FOREIGN KEY ("reference_source_id") REFERENCES "csv_batch_a4d78be79a83"."data_sources" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_maintenance" ADD CONSTRAINT "csv_fk_77a1c64bd66eb0b9c3c4" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_maintenance" ADD CONSTRAINT "csv_fk_5fb3c38776a07fde16d3" FOREIGN KEY ("operator_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_production_plans" ADD CONSTRAINT "csv_fk_45234fbc7e637d61da0f" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_production_plans" ADD CONSTRAINT "csv_fk_a3d4987894b7a85cf120" FOREIGN KEY ("responsible_person_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_event_registry" ADD CONSTRAINT "csv_fk_b845efc18d0986473306" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_event_registry" ADD CONSTRAINT "csv_fk_157d2ab82a31dc717d31" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_attachments" ADD CONSTRAINT "csv_fk_8798032d6de38b2982e1" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_attachments" ADD CONSTRAINT "csv_fk_1e671e1e5edcec3e4f48" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_attachments" ADD CONSTRAINT "csv_fk_9f9e42a8cd831b6394bc" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_attachment_links" ADD CONSTRAINT "csv_fk_511793e3b8ad640c0bab" FOREIGN KEY ("attachment_id") REFERENCES "csv_batch_a4d78be79a83"."data_attachments" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_media_annotations" ADD CONSTRAINT "csv_fk_0fbf7deba87cde199be5" FOREIGN KEY ("attachment_id") REFERENCES "csv_batch_a4d78be79a83"."data_attachments" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_documents" ADD CONSTRAINT "csv_fk_7a02888ba8d1da88293b" FOREIGN KEY ("current_version_id") REFERENCES "csv_batch_a4d78be79a83"."data_document_versions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_documents" ADD CONSTRAINT "csv_fk_1e51f0797662dce7f9ca" FOREIGN KEY ("attachment_id") REFERENCES "csv_batch_a4d78be79a83"."data_attachments" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_document_versions" ADD CONSTRAINT "csv_fk_016f0e8f4c7d2fd99cad" FOREIGN KEY ("document_id") REFERENCES "csv_batch_a4d78be79a83"."data_documents" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_document_versions" ADD CONSTRAINT "csv_fk_1c940e2f1cb5d25a770c" FOREIGN KEY ("attachment_id") REFERENCES "csv_batch_a4d78be79a83"."data_attachments" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_document_versions" ADD CONSTRAINT "csv_fk_f649068ffdef50035b20" FOREIGN KEY ("replaces_version_id") REFERENCES "csv_batch_a4d78be79a83"."data_document_versions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_spatial_layer_registry" ADD CONSTRAINT "csv_fk_5a66f7f6cc158756d902" FOREIGN KEY ("attachment_id") REFERENCES "csv_batch_a4d78be79a83"."data_attachments" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_device_maintenance" ADD CONSTRAINT "csv_fk_e6f7e1033c97061c9051" FOREIGN KEY ("replacement_device_id") REFERENCES "csv_batch_a4d78be79a83"."data_devices" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_grade_definitions" ADD CONSTRAINT "csv_fk_615099a9ae94503ed439" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_grade_items" ADD CONSTRAINT "csv_fk_13ae6bc040e2a14670a1" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_grade_items" ADD CONSTRAINT "csv_fk_9b5e24f70b87398a20da" FOREIGN KEY ("grade_definition_id") REFERENCES "csv_batch_a4d78be79a83"."data_grade_definitions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_individuals" ADD CONSTRAINT "csv_fk_ca3257030d3d04d94449" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_individuals" ADD CONSTRAINT "csv_fk_cabf6c6d0f15dfd1e873" FOREIGN KEY ("grade_definition_id") REFERENCES "csv_batch_a4d78be79a83"."data_grade_definitions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_samples" ADD CONSTRAINT "csv_fk_39d0a88a28cafe789525" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_samples" ADD CONSTRAINT "csv_fk_cdde766b69c1579c900e" FOREIGN KEY ("grade_pass_definition_id") REFERENCES "csv_batch_a4d78be79a83"."data_grade_definitions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_samples" ADD CONSTRAINT "csv_fk_31d3f2e06e89efabacbd" FOREIGN KEY ("occupancy_id") REFERENCES "csv_batch_a4d78be79a83"."data_pond_cohort_occupancy" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_growth_samples" ADD CONSTRAINT "csv_fk_88dc4b2c1679a97f1c8e" FOREIGN KEY ("ledger_balance_id") REFERENCES "csv_batch_a4d78be79a83"."data_fish_daily_balance" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_4ace99335a268369d99e" FOREIGN KEY ("farm_id") REFERENCES "csv_batch_a4d78be79a83"."data_farms" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_375b8b925fb7be15d8c4" FOREIGN KEY ("pond_id") REFERENCES "csv_batch_a4d78be79a83"."data_ponds" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_a5138e5c347021446d9c" FOREIGN KEY ("cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_769f5cb28bfe5f467132" FOREIGN KEY ("species_id") REFERENCES "csv_batch_a4d78be79a83"."data_species" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_188c8489960f49614cb3" FOREIGN KEY ("grade_definition_id") REFERENCES "csv_batch_a4d78be79a83"."data_grade_definitions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_9b368087fdcd7c4e97bb" FOREIGN KEY ("harvest_id") REFERENCES "csv_batch_a4d78be79a83"."data_harvests" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_eaea79212dc364eff19e" FOREIGN KEY ("harvest_grade_item_id") REFERENCES "csv_batch_a4d78be79a83"."data_harvest_grade_items" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_f67c07d5513d8c7784a1" FOREIGN KEY ("recorder_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_e65c844ccfa94f298c3d" FOREIGN KEY ("reviewer_id") REFERENCES "csv_batch_a4d78be79a83"."data_persons" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_6ae1fd3ce5724259a6ea" FOREIGN KEY ("grade_definition_id") REFERENCES "csv_batch_a4d78be79a83"."data_grade_definitions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_sale_allocations" ADD CONSTRAINT "csv_fk_de0c19902ebf38caf8b2" FOREIGN KEY ("grade_definition_id") REFERENCES "csv_batch_a4d78be79a83"."data_grade_definitions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_preparations" ADD CONSTRAINT "csv_fk_749b13d12e01e14e25b4" FOREIGN KEY ("disinfectant_product_id") REFERENCES "csv_batch_a4d78be79a83"."data_products" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_pond_preparations" ADD CONSTRAINT "csv_fk_0bf99415b40e0cc88b29" FOREIGN KEY ("previous_cohort_id") REFERENCES "csv_batch_a4d78be79a83"."data_cohorts" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_price_observations" ADD CONSTRAINT "csv_fk_e5cbb55c5d393da40312" FOREIGN KEY ("grade_definition_id") REFERENCES "csv_batch_a4d78be79a83"."data_grade_definitions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_sale_items" ADD CONSTRAINT "csv_fk_62c417777311d6f02af1" FOREIGN KEY ("grade_definition_id") REFERENCES "csv_batch_a4d78be79a83"."data_grade_definitions" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_individuals" ADD CONSTRAINT "csv_fk_07dc0b8040fd5bcc6b24" FOREIGN KEY ("event_id") REFERENCES "csv_batch_a4d78be79a83"."data_harvests" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_harvest_grade_items" ADD CONSTRAINT "csv_fk_1f83a9cea843841f283d" FOREIGN KEY ("event_id") REFERENCES "csv_batch_a4d78be79a83"."data_harvests" ("id") DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE "csv_batch_a4d78be79a83"."data_transfer_allocations" ADD CONSTRAINT "csv_fk_d86f2a6c24e251ca749a" FOREIGN KEY ("event_id") REFERENCES "csv_batch_a4d78be79a83"."data_transfer_events" ("id") DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX csv_rel_from ON "csv_batch_a4d78be79a83"."ontology_relations" ("from_node");

CREATE INDEX csv_rel_to ON "csv_batch_a4d78be79a83"."ontology_relations" ("to_node");
