-- 固定结构提交 9995fc20cd84093adcaa3fab954ffe9d08b9f45a

-- 只读白名单导出；没有认证字段、未映射 JSON、几何、二进制或向量。

-- psql --no-psqlrc --quiet --tuples-only --no-align --set ON_ERROR_STOP=1 --file readonly-export.sql --output records.jsonl

-- 使用有权访问所需业务表的只读账号；生产导出文件放 implementation/runtime/source-imports/（已忽略），不得提交 Git。

BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;

SET LOCAL statement_timeout = '120s';

SET LOCAL client_encoding = 'UTF8';

SELECT jsonb_build_object('table', 'users', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "username" AS "username",
    "display_name" AS "display_name",
    "role" AS "role",
    "wecom_corp_id" AS "wecom_corp_id",
    "wecom_user_id" AS "wecom_user_id",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."users"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'objects', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "parent_id"::text AS "parent_id",
    "code" AS "code",
    "name" AS "name",
    "kind" AS "kind",
    "boundary_status" AS "boundary_status",
    "source" AS "source",
    "version"::text AS "version",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."objects"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'object_versions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "version"::text AS "version",
    "reason" AS "reason",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."object_versions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'production_batches', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "code" AS "code",
    "species" AS "species",
    "variety" AS "variety",
    "stage" AS "stage",
    "source" AS "source",
    "verified" AS "verified",
    to_char("started_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "started_at",
    to_char("ended_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "ended_at",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."production_batches"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'data_sources', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "code" AS "code",
    "name" AS "name",
    "provider" AS "provider",
    "contract_ref" AS "contract_ref",
    "verified" AS "verified",
    "created_by"::text AS "created_by"
  FROM "public"."data_sources"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'devices', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "source_id"::text AS "source_id",
    "external_id" AS "external_id",
    "name" AS "name",
    "kind" AS "kind",
    "parent_device_id"::text AS "parent_device_id",
    "model" AS "model",
    "serial_number" AS "serial_number",
    "source" AS "source",
    "verified" AS "verified",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."devices"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'points', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "device_id"::text AS "device_id",
    "code" AS "code",
    "name" AS "name",
    "metric" AS "metric",
    "unit" AS "unit",
    "max_age_ms"::text AS "max_age_ms",
    "max_gap_ms"::text AS "max_gap_ms",
    "timing_source" AS "timing_source",
    "created_by"::text AS "created_by"
  FROM "public"."points"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'point_bindings', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "point_id"::text AS "point_id",
    "object_id"::text AS "object_id",
    to_char("valid_from" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_from",
    to_char("valid_to" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_to",
    "verified" AS "verified",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."point_bindings"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'raw_receipts', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "source_id"::text AS "source_id",
    to_char("received_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "received_at",
    "sha256" AS "sha256",
    "synthetic" AS "synthetic",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "contract_version" AS "contract_version",
    "contract_ref" AS "contract_ref",
    "contract_sha256" AS "contract_sha256"
  FROM "public"."raw_receipts"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'observations', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "content_hash" AS "content_hash",
    "source_id"::text AS "source_id",
    "source_record_id" AS "source_record_id",
    "external_device_id" AS "external_device_id",
    "point_id"::text AS "point_id",
    "object_id"::text AS "object_id",
    "binding_id"::text AS "binding_id",
    "metric" AS "metric",
    to_char("sampled_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "sampled_at",
    to_char("reported_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "reported_at",
    to_char("received_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "received_at",
    "sequence" AS "sequence",
    "value"::text AS "value",
    "unit" AS "unit",
    "quality" AS "quality",
    "reasons" AS "reasons",
    "origin" AS "origin",
    "raw_ref"::text AS "raw_ref"
  FROM "public"."observations"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'observation_receipts', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "observation_id"::text AS "observation_id",
    "raw_ref"::text AS "raw_ref"
  FROM "public"."observation_receipts"
  ORDER BY "observation_id", "raw_ref"
) AS export_row;

SELECT jsonb_build_object('table', 'measurement_conflicts', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "first_id"::text AS "first_id",
    "other_id"::text AS "other_id",
    to_char("detected_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "detected_at"
  FROM "public"."measurement_conflicts"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'rule_bindings', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "point_id"::text AS "point_id",
    "object_id"::text AS "object_id",
    "batch_id"::text AS "batch_id",
    "name" AS "name",
    "enabled" AS "enabled",
    "active_version_id"::text AS "active_version_id",
    to_char("enabled_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "enabled_at",
    "created_by"::text AS "created_by"
  FROM "public"."rule_bindings"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'rule_versions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "binding_id"::text AS "binding_id",
    "version"::text AS "version",
    "metric" AS "metric",
    "unit" AS "unit",
    "comparison" AS "comparison",
    "threshold"::text AS "threshold",
    "duration_ms"::text AS "duration_ms",
    "max_gap_ms"::text AS "max_gap_ms",
    "max_age_ms"::text AS "max_age_ms",
    "severity" AS "severity",
    "source" AS "source",
    "approved_by"::text AS "approved_by",
    to_char("approved_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "approved_at",
    "approval_evidence" AS "approval_evidence",
    to_char("effective_from" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "effective_from",
    to_char("effective_to" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "effective_to",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."rule_versions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'alerts', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "point_id"::text AS "point_id",
    "rule_binding_id"::text AS "rule_binding_id",
    "rule_version_id"::text AS "rule_version_id",
    "correlation_key" AS "correlation_key",
    "kind" AS "kind",
    "title" AS "title",
    "severity" AS "severity",
    "state" AS "state",
    "data_quality" AS "data_quality",
    to_char("opened_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "opened_at",
    to_char("recovered_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "recovered_at",
    to_char("closed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "closed_at",
    to_char("first_notification_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "first_notification_at",
    "recurrences"::text AS "recurrences",
    "continuations"::text AS "continuations",
    "unmanaged" AS "unmanaged"
  FROM "public"."alerts"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'alert_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "alert_id"::text AS "alert_id",
    "event_type" AS "event_type",
    "actor_id"::text AS "actor_id",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    to_char("recorded_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "recorded_at",
    "note" AS "note",
    "request_key" AS "request_key",
    "classification" AS "classification"
  FROM "public"."alert_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'alert_claims', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "alert_id"::text AS "alert_id",
    "purpose" AS "purpose",
    "actor_id"::text AS "actor_id",
    "request_key" AS "request_key",
    to_char("claimed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "claimed_at",
    to_char("ended_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "ended_at"
  FROM "public"."alert_claims"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'duty_rosters', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    to_char("starts_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "starts_at",
    to_char("ends_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "ends_at",
    "night_shift" AS "night_shift",
    "onsite_id"::text AS "onsite_id",
    "technician_id"::text AS "technician_id",
    "owner_id"::text AS "owner_id",
    "maintainer_id"::text AS "maintainer_id",
    "call_timeout_ms"::text AS "call_timeout_ms",
    "verified" AS "verified",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("cancelled_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "cancelled_at"
  FROM "public"."duty_rosters"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'maintenance_records', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "point_id"::text AS "point_id",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "record_type" AS "record_type",
    "source" AS "source",
    "supersedes_id"::text AS "supersedes_id",
    "recorded_by"::text AS "recorded_by",
    to_char("recorded_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "recorded_at",
    "request_key" AS "request_key"
  FROM "public"."maintenance_records"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'manual_checks', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "point_id"::text AS "point_id",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "metric" AS "metric",
    "raw_value" AS "raw_value",
    "value"::text AS "value",
    "unit" AS "unit",
    "method" AS "method",
    "source" AS "source",
    "supersedes_id"::text AS "supersedes_id",
    "recorded_by"::text AS "recorded_by",
    to_char("recorded_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "recorded_at",
    "request_key" AS "request_key"
  FROM "public"."manual_checks"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'work_orders', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "point_id"::text AS "point_id",
    "fault" AS "fault",
    "state" AS "state",
    "responsible_role" AS "responsible_role",
    "assigned_to"::text AS "assigned_to",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "request_key" AS "request_key"
  FROM "public"."work_orders"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'work_order_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "work_order_id"::text AS "work_order_id",
    "state" AS "state",
    "note" AS "note",
    "actor_id"::text AS "actor_id",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at"
  FROM "public"."work_order_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'budgets', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "category" AS "category",
    "month"::text AS "month",
    "limit_amount"::text AS "limit_amount",
    "currency" AS "currency",
    "source" AS "source",
    "configured_by"::text AS "configured_by"
  FROM "public"."budgets"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'usage_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "category" AS "category",
    "business_key" AS "business_key",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "units"::text AS "units",
    "amount"::text AS "amount",
    "currency" AS "currency",
    "price_source" AS "price_source",
    to_char("recorded_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "recorded_at"
  FROM "public"."usage_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'budget_alerts', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "budget_id"::text AS "budget_id",
    "level" AS "level",
    to_char("observed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "observed_at"
  FROM "public"."budget_alerts"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'boundary_versions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "object_version"::text AS "object_version",
    "source_crs"::text AS "source_crs",
    "source" AS "source",
    "status" AS "status",
    "confirmed_by"::text AS "confirmed_by",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."boundary_versions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'device_positions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "device_id"::text AS "device_id",
    "object_id"::text AS "object_id",
    "version"::text AS "version",
    "source" AS "source",
    "verified" AS "verified",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."device_positions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'media_assets', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "submission_key" AS "submission_key",
    "request_key" AS "request_key",
    "content_hash" AS "content_hash",
    "checksum" AS "checksum",
    "byte_length"::text AS "byte_length",
    "name" AS "name",
    "mime" AS "mime",
    "storage_key" AS "storage_key",
    "backup_key" AS "backup_key",
    "preview_of"::text AS "preview_of",
    to_char("captured_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "captured_at",
    "version" AS "version",
    "source" AS "source",
    "ingest_state" AS "ingest_state",
    "backup_state" AS "backup_state",
    "backup_error" AS "backup_error",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."media_assets"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'farm_records', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "object_version"::text AS "object_version",
    "batch_id"::text AS "batch_id",
    "kind" AS "kind",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    to_char("recorded_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "recorded_at",
    "author_id"::text AS "author_id",
    "submission_id" AS "submission_id",
    "content_hash" AS "content_hash",
    "status" AS "status",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "correction_reason" AS "correction_reason"
  FROM "public"."farm_records"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'record_attachments', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "record_id"::text AS "record_id",
    "asset_id"::text AS "asset_id"
  FROM "public"."record_attachments"
  ORDER BY "record_id", "asset_id"
) AS export_row;

SELECT jsonb_build_object('table', 'record_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "record_id"::text AS "record_id",
    "reviewer_id"::text AS "reviewer_id",
    "note" AS "note",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."record_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'calendar_versions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "name" AS "name",
    "version"::text AS "version",
    "species" AS "species",
    "variety" AS "variety",
    "stage" AS "stage",
    "source_ref" AS "source_ref",
    to_char("effective_from" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "effective_from",
    "approved_by"::text AS "approved_by",
    to_char("approved_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "approved_at",
    to_char("retired_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "retired_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."calendar_versions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'field_tasks', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "batch_id"::text AS "batch_id",
    "calendar_id"::text AS "calendar_id",
    "alert_id"::text AS "alert_id",
    "title" AS "title",
    "instructions" AS "instructions",
    to_char("due_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "due_at",
    "kind" AS "kind",
    "state" AS "state",
    "version"::text AS "version",
    "assignee_id"::text AS "assignee_id",
    "claimed_by"::text AS "claimed_by",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "request_key" AS "request_key",
    "content_hash" AS "content_hash"
  FROM "public"."field_tasks"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'field_task_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "task_id"::text AS "task_id",
    "version"::text AS "version",
    "action" AS "action",
    "actor_id"::text AS "actor_id",
    "request_key" AS "request_key",
    "content_hash" AS "content_hash",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."field_task_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'inspection_reports', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "task_id"::text AS "task_id",
    "observation" AS "observation",
    "judgment" AS "judgment",
    "action_taken" AS "action_taken",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "record_id"::text AS "record_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."inspection_reports"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'irrigation_entries', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "task_id"::text AS "task_id",
    "step" AS "step",
    "details" AS "details",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."irrigation_entries"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'camera_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "device_id"::text AS "device_id",
    "source_id"::text AS "source_id",
    "external_event_id" AS "external_event_id",
    "contract_version" AS "contract_version",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    to_char("received_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "received_at",
    "event_type" AS "event_type",
    "payload_hash" AS "payload_hash",
    "alert_id"::text AS "alert_id",
    "asset_id"::text AS "asset_id",
    "image_state" AS "image_state",
    "image_error" AS "image_error",
    "model_queue_error" AS "model_queue_error"
  FROM "public"."camera_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'flights', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "source_id"::text AS "source_id",
    "external_id" AS "external_id",
    to_char("started_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "started_at",
    to_char("finished_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "finished_at",
    "aircraft_model" AS "aircraft_model",
    "dock_model" AS "dock_model",
    "provider_version" AS "provider_version",
    "source_ref" AS "source_ref",
    "crs" AS "crs",
    "manifest_hash" AS "manifest_hash",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."flights"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'flight_files', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "flight_id"::text AS "flight_id",
    "external_file_id" AS "external_file_id",
    "name" AS "name",
    "kind" AS "kind",
    "version" AS "version",
    "checksum" AS "checksum",
    "processing_source" AS "processing_source",
    "asset_id"::text AS "asset_id"
  FROM "public"."flight_files"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'flight_annotations', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "flight_id"::text AS "flight_id",
    "asset_id"::text AS "asset_id",
    "note" AS "note",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "file_id"::text AS "file_id",
    "source_ref" AS "source_ref",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "request_key" AS "request_key",
    "input_hash" AS "input_hash"
  FROM "public"."flight_annotations"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'metric_definitions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "point_id"::text AS "point_id",
    "name" AS "name",
    "version"::text AS "version",
    "source_ref" AS "source_ref",
    "approved_by"::text AS "approved_by",
    to_char("approved_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "approved_at",
    to_char("retired_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "retired_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."metric_definitions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'metric_results', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "definition_id"::text AS "definition_id",
    "definition_version"::text AS "definition_version",
    to_char("window_start" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "window_start",
    to_char("window_end" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "window_end",
    to_char("calculated_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "calculated_at",
    "value"::text AS "value",
    "observed_value"::text AS "observed_value",
    "unit" AS "unit",
    "status" AS "status",
    "coverage"::text AS "coverage",
    "input_hash" AS "input_hash",
    "version"::text AS "version"
  FROM "public"."metric_results"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'weather_records', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "kind" AS "kind",
    "source" AS "source",
    "source_version" AS "source_version",
    "station_ref" AS "station_ref",
    to_char("published_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "published_at",
    to_char("valid_from" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_from",
    to_char("valid_to" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_to",
    "request_key" AS "request_key",
    "content_hash" AS "content_hash",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("received_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "received_at"
  FROM "public"."weather_records"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'knowledge_documents', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "title" AS "title",
    "version" AS "version",
    "source_ref" AS "source_ref",
    "source_url" AS "source_url",
    "source_checksum" AS "source_checksum",
    "body" AS "body",
    "format" AS "format",
    "evidence_nature" AS "evidence_nature",
    "state" AS "state",
    "approved_by"::text AS "approved_by",
    to_char("approved_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "approved_at",
    to_char("withdrawn_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "withdrawn_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."knowledge_documents"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'briefings', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "created_by"::text AS "created_by",
    "request_key" AS "request_key",
    "input_hash" AS "input_hash",
    "period" AS "period",
    to_char("from_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "from_at",
    to_char("to_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "to_at",
    "state" AS "state",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("review_due_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "review_due_at"
  FROM "public"."briefings"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'briefing_items', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "briefing_id"::text AS "briefing_id",
    "object_id"::text AS "object_id",
    "kind" AS "kind",
    "original_text" AS "original_text",
    "decision" AS "decision",
    "reviewed_text" AS "reviewed_text",
    "review_reason" AS "review_reason",
    "reviewer_id"::text AS "reviewer_id",
    to_char("reviewed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "reviewed_at",
    "task_id"::text AS "task_id",
    "version"::text AS "version"
  FROM "public"."briefing_items"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'briefing_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "item_id"::text AS "item_id",
    "decision" AS "decision",
    "text" AS "text",
    "reason" AS "reason",
    "actor_id"::text AS "actor_id",
    "request_key" AS "request_key",
    "content_hash" AS "content_hash",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."briefing_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'briefing_publications', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "briefing_id"::text AS "briefing_id",
    "recipient_id"::text AS "recipient_id",
    "role_version" AS "role_version",
    "confirmed_by"::text AS "confirmed_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("revoked_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "revoked_at",
    to_char("expires_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "expires_at",
    "request_key" AS "request_key",
    "content_hash" AS "content_hash",
    "revoked_by"::text AS "revoked_by",
    "revoke_reason" AS "revoke_reason"
  FROM "public"."briefing_publications"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'image_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "camera_event_id"::text AS "camera_event_id",
    "asset_id"::text AS "asset_id",
    "checksum" AS "checksum",
    "model_version" AS "model_version",
    "state" AS "state",
    "error_code" AS "error_code",
    "created_by"::text AS "created_by",
    "request_key" AS "request_key",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("completed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "completed_at",
    "canonical" AS "canonical"
  FROM "public"."image_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'image_field_samples', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "device_id"::text AS "device_id",
    "camera_event_id"::text AS "camera_event_id",
    "review_id"::text AS "review_id",
    "scene" AS "scene",
    "source_ref" AS "source_ref",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "target" AS "target",
    "expected_trigger" AS "expected_trigger",
    "camera_triggered" AS "camera_triggered",
    "platform_received" AS "platform_received",
    "person_received" AS "person_received",
    "human_label" AS "human_label",
    "labelled_by"::text AS "labelled_by",
    to_char("labelled_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "labelled_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "request_key" AS "request_key",
    "content_hash" AS "content_hash",
    "human_labels" AS "human_labels"
  FROM "public"."image_field_samples"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'weather_source_versions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "configuration_version"::text AS "configuration_version",
    "source_tag" AS "source_tag",
    "content_hash" AS "content_hash",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."weather_source_versions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'ezviz_receipts', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "configuration_version"::text AS "configuration_version",
    "object_id"::text AS "object_id",
    "source_id"::text AS "source_id",
    "source_contract_ref" AS "source_contract_ref",
    "processor_id"::text AS "processor_id",
    "message_id" AS "message_id",
    "message_type" AS "message_type",
    "device_serial" AS "device_serial",
    "channel_no"::text AS "channel_no",
    to_char("pushed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "pushed_at",
    to_char("signature_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "signature_at",
    to_char("received_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "received_at",
    "raw_sha256" AS "raw_sha256",
    "content_hash" AS "content_hash",
    "encrypted_message" AS "encrypted_message",
    "state" AS "state",
    "camera_event_id"::text AS "camera_event_id",
    "image_state" AS "image_state",
    "image_error" AS "image_error",
    "error_code" AS "error_code",
    to_char("processed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "processed_at"
  FROM "public"."ezviz_receipts"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'dji_snapshots', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "configuration_version"::text AS "configuration_version",
    "object_id"::text AS "object_id",
    "source_id"::text AS "source_id",
    "task_uuid"::text AS "task_uuid",
    "metadata_hash" AS "metadata_hash",
    to_char("received_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "received_at",
    "flight_id"::text AS "flight_id",
    "confirmed_by"::text AS "confirmed_by",
    "confirmation_evidence" AS "confirmation_evidence"
  FROM "public"."dji_snapshots"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'dji_resources', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "snapshot_id"::text AS "snapshot_id",
    "external_id"::text AS "external_id",
    "encrypted_url" AS "encrypted_url",
    "asset_id"::text AS "asset_id"
  FROM "public"."dji_resources"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'flight_coverages', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "flight_id"::text AS "flight_id",
    "object_id"::text AS "object_id",
    "version"::text AS "version",
    "source_crs"::text AS "source_crs",
    "source_ref" AS "source_ref",
    "status" AS "status",
    "request_key" AS "request_key",
    "input_hash" AS "input_hash",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."flight_coverages"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'flight_rasters', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "file_id"::text AS "file_id",
    "flight_id"::text AS "flight_id",
    "object_id"::text AS "object_id",
    "source_asset_id"::text AS "source_asset_id",
    "source_checksum" AS "source_checksum",
    "source_ref" AS "source_ref",
    "created_by"::text AS "created_by",
    "request_key" AS "request_key",
    "input_hash" AS "input_hash",
    "state" AS "state",
    "preview_asset_id"::text AS "preview_asset_id",
    "error_code" AS "error_code",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("completed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "completed_at"
  FROM "public"."flight_rasters"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'comparison_definitions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "name" AS "name",
    "current_definition_id"::text AS "current_definition_id",
    "baseline_definition_id"::text AS "baseline_definition_id",
    "threshold"::text AS "threshold",
    "source_ref" AS "source_ref",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "approved_by"::text AS "approved_by",
    to_char("approved_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "approved_at",
    to_char("retired_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "retired_at"
  FROM "public"."comparison_definitions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'comparison_results', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "definition_id"::text AS "definition_id",
    "state" AS "state",
    "advance_days"::text AS "advance_days",
    "current_date_label" AS "current_date_label",
    "baseline_date_label" AS "baseline_date_label",
    "input_hash" AS "input_hash",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."comparison_results"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'terrain_scenes', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "flight_id"::text AS "flight_id",
    "name" AS "name",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "root_path" AS "root_path",
    to_char("captured_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "captured_at",
    "source_crs" AS "source_crs",
    "survey_crs" AS "survey_crs",
    "vertical_datum" AS "vertical_datum",
    "conversion_ref" AS "conversion_ref",
    "source_ref" AS "source_ref",
    "surface_state" AS "surface_state",
    "repairs_declared" AS "repairs_declared",
    "state" AS "state",
    "error_code" AS "error_code",
    "created_by"::text AS "created_by",
    "request_key" AS "request_key",
    "input_hash" AS "input_hash",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("completed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "completed_at",
    to_char("withdrawn_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "withdrawn_at",
    "withdraw_reason" AS "withdraw_reason"
  FROM "public"."terrain_scenes"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'terrain_resources', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "scene_id"::text AS "scene_id",
    "path" AS "path",
    "asset_id"::text AS "asset_id",
    "checksum" AS "checksum",
    "byte_length"::text AS "byte_length",
    "mime" AS "mime"
  FROM "public"."terrain_resources"
  ORDER BY "scene_id", "path"
) AS export_row;

SELECT jsonb_build_object('table', 'terrain_surveys', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "scene_id"::text AS "scene_id",
    "object_id"::text AS "object_id",
    "point_key" AS "point_key",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "purpose" AS "purpose",
    "independent" AS "independent",
    "survey_e"::text AS "survey_e",
    "survey_n"::text AS "survey_n",
    "survey_h"::text AS "survey_h",
    "model_e"::text AS "model_e",
    "model_n"::text AS "model_n",
    "model_h"::text AS "model_h",
    "horizontal_crs" AS "horizontal_crs",
    "vertical_datum" AS "vertical_datum",
    to_char("measured_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "measured_at",
    "source_ref" AS "source_ref",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "request_key" AS "request_key",
    "input_hash" AS "input_hash"
  FROM "public"."terrain_surveys"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'terrain_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "scene_id"::text AS "scene_id",
    "object_id"::text AS "object_id",
    "input_hash" AS "input_hash",
    "decision" AS "decision",
    "purpose" AS "purpose",
    "evidence" AS "evidence",
    to_char("review_due_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "review_due_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "request_key" AS "request_key",
    "content_hash" AS "content_hash"
  FROM "public"."terrain_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'device_elevations', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "device_id"::text AS "device_id",
    "position_id"::text AS "position_id",
    "object_id"::text AS "object_id",
    "version"::text AS "version",
    "survey_height"::text AS "survey_height",
    "ellipsoid_height"::text AS "ellipsoid_height",
    "vertical_datum" AS "vertical_datum",
    "reference_point" AS "reference_point",
    "conversion_ref" AS "conversion_ref",
    to_char("measured_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "measured_at",
    "source_ref" AS "source_ref",
    "verified" AS "verified",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "request_key" AS "request_key",
    "input_hash" AS "input_hash"
  FROM "public"."device_elevations"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'hydraulic_links', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "scene_id"::text AS "scene_id",
    "object_id"::text AS "object_id",
    "to_object_id"::text AS "to_object_id",
    "name" AS "name",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "direction" AS "direction",
    "evidence" AS "evidence",
    "verified" AS "verified",
    to_char("review_due_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "review_due_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("withdrawn_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "withdrawn_at",
    "withdraw_reason" AS "withdraw_reason",
    "request_key" AS "request_key",
    "input_hash" AS "input_hash"
  FROM "public"."hydraulic_links"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_locations', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "code" AS "code",
    "name" AS "name",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."stock_locations"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_lots', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "code" AS "code",
    "product" AS "product",
    "kind" AS "kind",
    "unit" AS "unit",
    "basis" AS "basis",
    "production_batch_id"::text AS "production_batch_id",
    "source" AS "source",
    "state" AS "state",
    "version"::text AS "version",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."stock_lots"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_documents', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "kind" AS "kind",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "reverses_id"::text AS "reverses_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."stock_documents"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_entries', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "document_id"::text AS "document_id",
    "lot_id"::text AS "lot_id",
    "location_id"::text AS "location_id",
    "delta"::text AS "delta"
  FROM "public"."stock_entries"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'input_purchases', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "supplier" AS "supplier",
    "voucher" AS "voucher",
    "quantity"::text AS "quantity",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."input_purchases"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'input_applications', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "issue_document_id"::text AS "issue_document_id",
    "farm_record_id"::text AS "farm_record_id",
    "quantity"::text AS "quantity",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."input_applications"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_transformations', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "code" AS "code",
    "kind" AS "kind",
    "source_ref" AS "source_ref",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."stock_transformations"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_lineage', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "transformation_id"::text AS "transformation_id",
    "document_id"::text AS "document_id",
    "input_lot_id"::text AS "input_lot_id",
    "output_lot_id"::text AS "output_lot_id"
  FROM "public"."stock_lineage"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_packages', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "code" AS "code",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."stock_packages"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_package_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "package_id"::text AS "package_id",
    "lot_id"::text AS "lot_id",
    "action" AS "action",
    "quantity"::text AS "quantity",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."stock_package_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'stock_handoffs', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "dispatch_id"::text AS "dispatch_id",
    "direction" AS "direction",
    "party" AS "party",
    "quantity"::text AS "quantity",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "document_id"::text AS "document_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."stock_handoffs"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'quality_samples', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "sample_code" AS "sample_code",
    "stage" AS "stage",
    to_char("sampled_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "sampled_at",
    "source" AS "source",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."quality_samples"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'quality_tests', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "sample_id"::text AS "sample_id",
    "method" AS "method",
    "result" AS "result",
    "report_ref" AS "report_ref",
    to_char("tested_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "tested_at",
    to_char("valid_until" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_until",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."quality_tests"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'quality_credentials', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "kind" AS "kind",
    "subject" AS "subject",
    "product" AS "product",
    to_char("valid_from" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_from",
    to_char("valid_until" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_until",
    "evidence" AS "evidence",
    "verified" AS "verified",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."quality_credentials"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'quality_decisions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "from_state" AS "from_state",
    "to_state" AS "to_state",
    "version"::text AS "version",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."quality_decisions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'quality_cases', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "title" AS "title",
    "target_quantity"::text AS "target_quantity",
    "evidence" AS "evidence",
    "state" AS "state",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."quality_cases"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'quality_case_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "case_id"::text AS "case_id",
    "action" AS "action",
    "quantity"::text AS "quantity",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."quality_case_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'public_trace_cards', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "version"::text AS "version",
    "code" AS "code",
    "state" AS "state",
    to_char("valid_until" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_until",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "reviewed_by"::text AS "reviewed_by",
    to_char("reviewed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "reviewed_at",
    "review_note" AS "review_note"
  FROM "public"."public_trace_cards"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'protection_plans', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "title" AS "title",
    "crop" AS "crop",
    "target" AS "target",
    "stage" AS "stage",
    "obstacles" AS "obstacles",
    "sensitive_note" AS "sensitive_note",
    "conditions" AS "conditions",
    "input_lot_id"::text AS "input_lot_id",
    "task_id"::text AS "task_id",
    "source" AS "source",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."protection_plans"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'prescription_maps', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "plan_id"::text AS "plan_id",
    "version"::text AS "version",
    "source_asset_id"::text AS "source_asset_id",
    "source_analysis_id"::text AS "source_analysis_id",
    "dose_unit" AS "dose_unit",
    "basis" AS "basis",
    "state" AS "state",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "reviewed_by"::text AS "reviewed_by",
    to_char("reviewed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "reviewed_at",
    "review_note" AS "review_note"
  FROM "public"."prescription_maps"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'protection_executions', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "plan_id"::text AS "plan_id",
    "prescription_id"::text AS "prescription_id",
    "operator" AS "operator",
    to_char("started_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "started_at",
    to_char("ended_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "ended_at",
    "swath_m"::text AS "swath_m",
    "max_gap_seconds"::text AS "max_gap_seconds",
    "material_quantity"::text AS "material_quantity",
    "unit" AS "unit",
    "result_check" AS "result_check",
    "remediation_of"::text AS "remediation_of",
    "cause" AS "cause",
    "remediation_cost"::text AS "remediation_cost",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."protection_executions"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'prescription_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "prescription_id"::text AS "prescription_id",
    "action" AS "action",
    "execution_id"::text AS "execution_id",
    "party" AS "party",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."prescription_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'protection_deliveries', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "plan_id"::text AS "plan_id",
    "provider" AS "provider",
    "kind" AS "kind",
    "missing" AS "missing",
    "received_by" AS "received_by",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."protection_deliveries"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'protection_followups', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "execution_id"::text AS "execution_id",
    "observation" AS "observation",
    "judgment" AS "judgment",
    "action" AS "action",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."protection_followups"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'crop_analyses', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "asset_id"::text AS "asset_id",
    "flight_id"::text AS "flight_id",
    to_char("captured_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "captured_at",
    "checksum" AS "checksum",
    "model_version" AS "model_version",
    "evaluation_mode" AS "evaluation_mode",
    "state" AS "state",
    "error_code" AS "error_code",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("completed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "completed_at"
  FROM "public"."crop_analyses"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'crop_labels', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "analysis_id"::text AS "analysis_id",
    "label" AS "label",
    "evidence" AS "evidence",
    to_char("observed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "observed_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."crop_labels"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'spectral_products', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "asset_id"::text AS "asset_id",
    "flight_id"::text AS "flight_id",
    to_char("captured_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "captured_at",
    "source_ref" AS "source_ref",
    "processor" AS "processor",
    "index_kind" AS "index_kind",
    "checksum" AS "checksum",
    "version"::text AS "version",
    "algorithm_version" AS "algorithm_version",
    "state" AS "state",
    "preview_asset_id"::text AS "preview_asset_id",
    "index_asset_id"::text AS "index_asset_id",
    "error_code" AS "error_code",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("completed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "completed_at"
  FROM "public"."spectral_products"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'agronomy_notices', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "title" AS "title",
    "agency" AS "agency",
    "source_ref" AS "source_ref",
    to_char("published_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "published_at",
    to_char("valid_from" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_from",
    to_char("valid_until" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_until",
    "crop" AS "crop",
    "region" AS "region",
    "body" AS "body",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "state" AS "state",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "reviewed_by"::text AS "reviewed_by",
    to_char("reviewed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "reviewed_at",
    "review_note" AS "review_note"
  FROM "public"."agronomy_notices"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'flow_observations', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "device_id"::text AS "device_id",
    "point_id"::text AS "point_id",
    to_char("from_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "from_at",
    to_char("to_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "to_at",
    "value"::text AS "value",
    "unit" AS "unit",
    "source_kind" AS "source_kind",
    "basis_ref" AS "basis_ref",
    "basis_version" AS "basis_version",
    "applicability" AS "applicability",
    to_char("valid_until" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_until",
    "reviewed_by"::text AS "reviewed_by",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."flow_observations"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'control_profiles', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "device_id"::text AS "device_id",
    "version"::text AS "version",
    "permission" AS "permission",
    "mode" AS "mode",
    "protection" AS "protection",
    "load_type" AS "load_type",
    "offline_behavior" AS "offline_behavior",
    "power_loss_behavior" AS "power_loss_behavior",
    "power_return_behavior" AS "power_return_behavior",
    "protocol_ref" AS "protocol_ref",
    "feedback_ref" AS "feedback_ref",
    to_char("valid_until" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_until",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."control_profiles"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'control_rules', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "device_id"::text AS "device_id",
    "version"::text AS "version",
    "purpose" AS "purpose",
    "species" AS "species",
    "stage" AS "stage",
    "conditions" AS "conditions",
    "source_ref" AS "source_ref",
    "state" AS "state",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    "reviewed_by"::text AS "reviewed_by",
    to_char("reviewed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "reviewed_at",
    "review_note" AS "review_note"
  FROM "public"."control_rules"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'control_requests', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "device_id"::text AS "device_id",
    "profile_id"::text AS "profile_id",
    "rule_id"::text AS "rule_id",
    "purpose" AS "purpose",
    "authorization_ref" AS "authorization_ref",
    "conditions" AS "conditions",
    "state" AS "state",
    "dispatched" AS "dispatched",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."control_requests"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'control_feedback', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "request_id"::text AS "request_id",
    "layer" AS "layer",
    "result" AS "result",
    "value" AS "value",
    "source" AS "source",
    to_char("observed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "observed_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."control_feedback"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'control_takeovers', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "device_id"::text AS "device_id",
    "request_id"::text AS "request_id",
    "person" AS "person",
    "manual_device" AS "manual_device",
    "conditions" AS "conditions",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."control_takeovers"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'energy_meters', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "device_id"::text AS "device_id",
    "name" AS "name",
    "purpose" AS "purpose",
    "capacity_kwh"::text AS "capacity_kwh",
    "max_gap_seconds"::text AS "max_gap_seconds",
    "oxygen_point_id"::text AS "oxygen_point_id",
    "source_ref" AS "source_ref",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."energy_meters"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'energy_meter_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "seq"::text AS "seq",
    "meter_id"::text AS "meter_id",
    "object_id"::text AS "object_id",
    "action" AS "action",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."energy_meter_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'energy_readings', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "meter_id"::text AS "meter_id",
    "metric" AS "metric",
    "value"::text AS "value",
    to_char("observed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "observed_at",
    "quality" AS "quality",
    "reset" AS "reset",
    "source_kind" AS "source_kind",
    "evidence" AS "evidence",
    "operating_state" AS "operating_state",
    "alarm_note" AS "alarm_note",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."energy_readings"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'circular_batches', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "material_kind" AS "material_kind",
    "origin_ref" AS "origin_ref",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."circular_batches"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'circular_weighings', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "lot_id"::text AS "lot_id",
    "document_id"::text AS "document_id",
    "gross_kg"::text AS "gross_kg",
    "tare_kg"::text AS "tare_kg",
    "net_kg"::text AS "net_kg",
    "moisture_pct"::text AS "moisture_pct",
    "dry_kg"::text AS "dry_kg",
    "basis" AS "basis",
    "voucher" AS "voucher",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."circular_weighings"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'circular_processes', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "document_id"::text AS "document_id",
    "process_kind" AS "process_kind",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."circular_processes"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'machinery_contracts', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "provider" AS "provider",
    "account_ref" AS "account_ref",
    "fields_ref" AS "fields_ref",
    "export_ref" AS "export_ref",
    "migration_ref" AS "migration_ref",
    "exit_ref" AS "exit_ref",
    to_char("valid_until" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_until",
    "source_ref" AS "source_ref",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."machinery_contracts"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'machinery_contract_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "seq"::text AS "seq",
    "object_id"::text AS "object_id",
    "contract_id"::text AS "contract_id",
    "action" AS "action",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."machinery_contract_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'machinery_bindings', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "machine_device_id"::text AS "machine_device_id",
    "terminal_device_id"::text AS "terminal_device_id",
    to_char("valid_from" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_from",
    to_char("valid_until" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "valid_until",
    "evidence" AS "evidence",
    to_char("revoked_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "revoked_at",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."machinery_bindings"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'machinery_orders', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "contract_id"::text AS "contract_id",
    "binding_id"::text AS "binding_id",
    "title" AS "title",
    "operation" AS "operation",
    to_char("starts_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "starts_at",
    to_char("ends_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "ends_at",
    "quantity"::text AS "quantity",
    "unit" AS "unit",
    "source_ref" AS "source_ref",
    "state" AS "state",
    "dispatched_by"::text AS "dispatched_by",
    to_char("dispatched_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "dispatched_at",
    "dispatch_evidence" AS "dispatch_evidence",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."machinery_orders"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'machinery_evidence', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "order_id"::text AS "order_id",
    "kind" AS "kind",
    "passed" AS "passed",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."machinery_evidence"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'machinery_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "seq"::text AS "seq",
    "object_id"::text AS "object_id",
    "order_id"::text AS "order_id",
    "action" AS "action",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."machinery_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'business_expenses', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "category" AS "category",
    "quantity"::text AS "quantity",
    "unit" AS "unit",
    "unit_price"::text AS "unit_price",
    "amount_cny"::text AS "amount_cny",
    "payer" AS "payer",
    "payee" AS "payee",
    "voucher" AS "voucher",
    "identity_key" AS "identity_key",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "link_kind" AS "link_kind",
    "link_id"::text AS "link_id",
    "evidence" AS "evidence",
    "supersedes_id"::text AS "supersedes_id",
    "version"::text AS "version",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."business_expenses"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'expense_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "seq"::text AS "seq",
    "object_id"::text AS "object_id",
    "expense_id"::text AS "expense_id",
    "action" AS "action",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."expense_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'expense_payments', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "expense_id"::text AS "expense_id",
    "direction" AS "direction",
    "amount_cny"::text AS "amount_cny",
    "voucher" AS "voucher",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "evidence" AS "evidence",
    "reverses_id"::text AS "reverses_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."expense_payments"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'subsidy_claims', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "category" AS "category",
    "policy_ref" AS "policy_ref",
    "policy_version" AS "policy_version",
    "beneficiary" AS "beneficiary",
    to_char("period_from" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "period_from",
    to_char("period_to" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "period_to",
    "amount_cny"::text AS "amount_cny",
    "evidence" AS "evidence",
    "state" AS "state",
    "awarded_cny"::text AS "awarded_cny",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."subsidy_claims"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'subsidy_expenses', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "claim_id"::text AS "claim_id",
    "expense_id"::text AS "expense_id",
    "active" AS "active"
  FROM "public"."subsidy_expenses"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'subsidy_events', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "seq"::text AS "seq",
    "object_id"::text AS "object_id",
    "claim_id"::text AS "claim_id",
    "action" AS "action",
    "amount_cny"::text AS "amount_cny",
    "external_ref" AS "external_ref",
    "evidence" AS "evidence",
    "reverses_id"::text AS "reverses_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("occurred_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "occurred_at",
    "corrects_id"::text AS "corrects_id"
  FROM "public"."subsidy_events"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'research_protocols', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "title" AS "title",
    "question" AS "question",
    "baseline" AS "baseline",
    to_char("starts_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "starts_at",
    to_char("ends_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "ends_at",
    "testing_plan" AS "testing_plan",
    "stop_rules" AS "stop_rules",
    "source_ref" AS "source_ref",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."research_protocols"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'research_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "seq"::text AS "seq",
    "object_id"::text AS "object_id",
    "protocol_id"::text AS "protocol_id",
    "action" AS "action",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."research_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'research_observations', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "protocol_id"::text AS "protocol_id",
    "plot_object_id"::text AS "plot_object_id",
    "metric" AS "metric",
    "sample_key" AS "sample_key",
    "value"::text AS "value",
    "unit" AS "unit",
    to_char("observed_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "observed_at",
    "method" AS "method",
    "kind" AS "kind",
    "agency" AS "agency",
    "report_ref" AS "report_ref",
    "missing_reason" AS "missing_reason",
    "evidence" AS "evidence",
    "version"::text AS "version",
    "supersedes_id"::text AS "supersedes_id",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."research_observations"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'research_results', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    "protocol_id"::text AS "protocol_id",
    "title" AS "title",
    "claim" AS "claim",
    "claim_level" AS "claim_level",
    "source_ref" AS "source_ref",
    "input_hash" AS "input_hash",
    "version"::text AS "version",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."research_results"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'research_result_reviews', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "seq"::text AS "seq",
    "object_id"::text AS "object_id",
    "result_id"::text AS "result_id",
    "action" AS "action",
    "evidence" AS "evidence",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at"
  FROM "public"."research_result_reviews"
  ORDER BY "id"
) AS export_row;

SELECT jsonb_build_object('table', 'management_reports', 'values', to_jsonb(export_row))::text
FROM (
  SELECT
    "id"::text AS "id",
    "object_id"::text AS "object_id",
    to_char("from_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "from_at",
    to_char("to_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "to_at",
    "source_ref" AS "source_ref",
    "definition_version" AS "definition_version",
    "state" AS "state",
    "input_hash" AS "input_hash",
    "error_code" AS "error_code",
    "created_by"::text AS "created_by",
    to_char("created_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "created_at",
    to_char("finished_at" AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS "finished_at"
  FROM "public"."management_reports"
  ORDER BY "id"
) AS export_row;

COMMIT;
