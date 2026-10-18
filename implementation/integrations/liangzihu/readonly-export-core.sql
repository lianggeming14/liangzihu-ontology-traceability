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

COMMIT;
