-- Immutable ontology definitions; mutable display labels never change release hashes.
CREATE TABLE ontology_properties (
 tenant_id text NOT NULL, package_id text NOT NULL, package_version text NOT NULL, property_id text NOT NULL,
 usage text NOT NULL CHECK(usage IN ('attribute','observation','assertion')), definition TEXT NOT NULL,
 PRIMARY KEY(tenant_id,package_id,package_version,property_id),
 FOREIGN KEY(tenant_id,package_id,package_version) REFERENCES ontology_packages(tenant_id,package_id,version)
);
CREATE TABLE ontology_display (
 tenant_id text NOT NULL, package_id text NOT NULL, package_version text NOT NULL,
 labels TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>0), updated_at TEXT NOT NULL, updated_by text NOT NULL,
 PRIMARY KEY(tenant_id,package_id,package_version),
 FOREIGN KEY(tenant_id,package_id,package_version) REFERENCES ontology_packages(tenant_id,package_id,version)
);
CREATE TABLE semantic_validations (
 tenant_id text NOT NULL, record_kind text NOT NULL CHECK(record_kind IN ('entity','observation','assertion')), record_id TEXT NOT NULL,
 validation_status text NOT NULL CHECK(validation_status IN ('validated','builtin_validated','unvalidated')),
 property_ref TEXT, details TEXT NOT NULL, validated_at TEXT NOT NULL,
 PRIMARY KEY(tenant_id,record_kind,record_id)
);
CREATE INDEX property_usage ON ontology_properties(tenant_id,usage,package_id,package_version);
