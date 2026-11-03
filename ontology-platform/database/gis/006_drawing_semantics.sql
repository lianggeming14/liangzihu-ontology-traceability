-- Independent drawing read model. This is not formal semantic-core registration.
CREATE TABLE gis_drawing_semantics_datasets (
 dataset_id varchar(100) NOT NULL, version varchar(100) NOT NULL,
 content_sha256 varchar(64) NOT NULL, source_package_sha256 varchar(64) NOT NULL,
 payload jsonb NOT NULL, PRIMARY KEY(dataset_id,version));
CREATE TABLE gis_drawing_semantics_heads (
 dataset_id varchar(100) PRIMARY KEY, version varchar(100) NOT NULL,
 FOREIGN KEY(dataset_id,version) REFERENCES gis_drawing_semantics_datasets(dataset_id,version));
CREATE TABLE gis_drawing_semantics_nodes (
 dataset_id varchar(100) NOT NULL, version varchar(100) NOT NULL, node_id varchar(200) NOT NULL,
 payload jsonb NOT NULL, PRIMARY KEY(dataset_id,version,node_id),
 FOREIGN KEY(dataset_id,version) REFERENCES gis_drawing_semantics_datasets(dataset_id,version));
CREATE TABLE gis_drawing_semantics_edges (
 dataset_id varchar(100) NOT NULL, version varchar(100) NOT NULL, edge_id varchar(100) NOT NULL,
 subject_id varchar(200) NOT NULL, object_id varchar(200) NOT NULL, payload jsonb NOT NULL,
 PRIMARY KEY(dataset_id,version,edge_id),
 FOREIGN KEY(dataset_id,version,subject_id) REFERENCES gis_drawing_semantics_nodes(dataset_id,version,node_id),
 FOREIGN KEY(dataset_id,version,object_id) REFERENCES gis_drawing_semantics_nodes(dataset_id,version,node_id));
CREATE TABLE gis_drawing_semantics_profiles (
 dataset_id varchar(100) NOT NULL, version varchar(100) NOT NULL, feature_id varchar(200) NOT NULL,
 entity_id varchar(200) NOT NULL, drawing_id varchar(100) NOT NULL, payload jsonb NOT NULL,
 PRIMARY KEY(dataset_id,version,feature_id),
 FOREIGN KEY(dataset_id,version,entity_id) REFERENCES gis_drawing_semantics_nodes(dataset_id,version,node_id));
CREATE TABLE gis_drawing_semantics_measurements (
 dataset_id varchar(100) NOT NULL, version varchar(100) NOT NULL, measurement_id varchar(200) NOT NULL,
 subject_id varchar(200) NOT NULL, drawing_id varchar(100) NOT NULL, kind varchar(200) NOT NULL,
 payload jsonb NOT NULL, PRIMARY KEY(dataset_id,version,measurement_id),
 FOREIGN KEY(dataset_id,version,subject_id) REFERENCES gis_drawing_semantics_nodes(dataset_id,version,node_id));
CREATE INDEX gis_drawing_measurement_kind ON gis_drawing_semantics_measurements(dataset_id,version,kind,measurement_id);
CREATE INDEX gis_drawing_measurement_subject_id ON gis_drawing_semantics_measurements(dataset_id,version,subject_id,measurement_id);
CREATE INDEX gis_drawing_measurement_drawing_id ON gis_drawing_semantics_measurements(dataset_id,version,drawing_id,measurement_id);
CREATE INDEX gis_drawing_semantics_edges_subject ON gis_drawing_semantics_edges(dataset_id,version,subject_id,edge_id);
CREATE INDEX gis_drawing_semantics_profiles_entity ON gis_drawing_semantics_profiles(dataset_id,version,entity_id);
GRANT SELECT ON gis_drawing_semantics_datasets,gis_drawing_semantics_heads,
 gis_drawing_semantics_nodes,gis_drawing_semantics_edges,gis_drawing_semantics_profiles,
 gis_drawing_semantics_measurements TO lzo_gis_app;
UPDATE store_schema_version SET version=6 WHERE version=5;
