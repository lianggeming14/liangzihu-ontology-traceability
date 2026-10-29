-- Drawing evidence is independent of governed WGS84 geometry heads.
CREATE TABLE gis_drawing_datasets (
 dataset_id varchar(100) NOT NULL, version integer NOT NULL CHECK(version>0),
 content_sha256 varchar(64) NOT NULL, payload jsonb NOT NULL,
 PRIMARY KEY(dataset_id,version));
CREATE TABLE gis_drawings (
 dataset_id varchar(100) NOT NULL, version integer NOT NULL, drawing_id varchar(100) NOT NULL,
 payload jsonb NOT NULL, PRIMARY KEY(dataset_id,version,drawing_id),
 FOREIGN KEY(dataset_id,version) REFERENCES gis_drawing_datasets(dataset_id,version));
CREATE TABLE gis_drawing_features (
 dataset_id varchar(100) NOT NULL, version integer NOT NULL, feature_id varchar(200) NOT NULL,
 drawing_id varchar(100) NOT NULL, entity_id varchar(36), kind varchar(100) NOT NULL,
 min_x double precision NOT NULL, min_y double precision NOT NULL,
 max_x double precision NOT NULL, max_y double precision NOT NULL, payload jsonb NOT NULL,
 paper_geom public.geometry(Geometry,0), PRIMARY KEY(dataset_id,version,feature_id),
 FOREIGN KEY(dataset_id,version,drawing_id) REFERENCES gis_drawings(dataset_id,version,drawing_id),
 CHECK(min_x<=max_x AND min_y<=max_y), CHECK(paper_geom IS NULL OR public.ST_SRID(paper_geom)=0));
CREATE INDEX gis_drawing_features_entity ON gis_drawing_features(entity_id);
CREATE INDEX gis_drawing_features_layer ON gis_drawing_features(dataset_id,version,drawing_id,kind);
CREATE INDEX gis_drawing_features_spatial ON gis_drawing_features USING gist(paper_geom);
CREATE TABLE gis_drawing_annotations (
 dataset_id varchar(100) NOT NULL, version integer NOT NULL, annotation_id varchar(200) NOT NULL,
 drawing_id varchar(100) NOT NULL, payload jsonb NOT NULL,
 PRIMARY KEY(dataset_id,version,annotation_id),
 FOREIGN KEY(dataset_id,version,drawing_id) REFERENCES gis_drawings(dataset_id,version,drawing_id));
CREATE INDEX gis_drawing_annotations_sheet ON gis_drawing_annotations(dataset_id,version,drawing_id);
-- App is read-only; reviewed imports use the independent GIS owner connection.
GRANT SELECT ON gis_drawing_datasets,gis_drawings,gis_drawing_features,gis_drawing_annotations TO lzo_gis_app;
UPDATE store_schema_version SET version=5 WHERE version=4;
