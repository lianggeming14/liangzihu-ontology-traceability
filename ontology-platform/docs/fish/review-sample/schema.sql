-- Isolated PostgreSQL/PostGIS design preview. Source synthetic; not formal adoption.
CREATE SCHEMA fish_review_10pct_v1;
CREATE TABLE fish_review_10pct_v1.data_cost_entries (
	id TEXT NOT NULL,
	farm_id TEXT,
	category TEXT,
	supplier_id TEXT,
	amount_cny NUMERIC,
	currency TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	source_type TEXT,
	source_id TEXT,
	cost_type TEXT,
	period_start DATE,
	period_end DATE,
	settlement_deduction_id TEXT,
	profit_treatment TEXT,
	allocation_method TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	recognition_method TEXT,
	expense_contract_start DATE,
	expense_contract_end DATE,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_dictionaries (
	id TEXT NOT NULL,
	domain TEXT,
	code TEXT,
	label TEXT,
	status TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_document_versions (
	id TEXT NOT NULL,
	document_id TEXT,
	version TEXT,
	attachment_id TEXT,
	relative_path TEXT,
	sha256 TEXT,
	published_at DATE,
	effective_from DATE,
	effective_until DATE,
	status TEXT,
	replaces_version_id TEXT,
	change_summary TEXT,
	review_status TEXT,
	page_reference TEXT,
	origin_kind TEXT,
	is_synthetic BOOLEAN,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_documents (
	id TEXT NOT NULL,
	title TEXT,
	document_type TEXT,
	publisher TEXT,
	language TEXT,
	current_version TEXT,
	current_version_id TEXT,
	published_at DATE,
	applicable_region TEXT,
	applicable_mode TEXT,
	full_text_path TEXT,
	attachment_id TEXT,
	sha256 TEXT,
	source_url TEXT,
	source_status TEXT,
	license_status TEXT,
	authority_status TEXT,
	review_status TEXT,
	origin_kind TEXT,
	is_synthetic BOOLEAN,
	usage_limitation TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_farms (
	id TEXT NOT NULL,
	farm_id TEXT,
	name TEXT,
	operator_name TEXT,
	address TEXT,
	contact TEXT,
	identity_status TEXT,
	longitude NUMERIC,
	latitude NUMERIC,
	crs TEXT,
	production_mode TEXT,
	timezone TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_persons (
	id TEXT NOT NULL,
	name TEXT,
	role TEXT,
	is_fictional BOOLEAN,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_settlement_deductions (
	id TEXT NOT NULL,
	farm_id TEXT,
	settlement_id TEXT,
	sale_id TEXT,
	deduction_type TEXT,
	amount_cny NUMERIC,
	currency TEXT,
	payer TEXT,
	recognition TEXT,
	cost_entry_id TEXT,
	source_document_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_sources (
	id TEXT NOT NULL,
	title TEXT,
	url TEXT,
	origin_kind TEXT,
	is_synthetic BOOLEAN,
	local_path TEXT,
	access_conditions TEXT,
	retrieved_at TEXT,
	use_boundary TEXT,
	version TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.field_dictionary (
	table_name TEXT NOT NULL,
	field_name TEXT NOT NULL,
	definition JSON,
	PRIMARY KEY (table_name, field_name)
);
CREATE TABLE fish_review_10pct_v1.gis_features (
	asset_id TEXT NOT NULL,
	owner_node TEXT,
	layer_id TEXT,
	layer_name TEXT,
	feature_id TEXT,
	geometry_json JSON,
	metadata JSON,
	PRIMARY KEY (asset_id)
);
CREATE TABLE fish_review_10pct_v1.ontology_model (
	kind TEXT NOT NULL,
	iri TEXT NOT NULL,
	definition JSON,
	PRIMARY KEY (kind, iri)
);
CREATE TABLE fish_review_10pct_v1.ontology_nodes (
	node_id TEXT NOT NULL,
	table_name TEXT,
	source_pk TEXT,
	class_iri TEXT,
	role TEXT,
	properties JSON,
	nature TEXT,
	source_row INTEGER,
	adoption_status TEXT,
	PRIMARY KEY (node_id)
);
CREATE TABLE fish_review_10pct_v1.ontology_relations (
	edge_id SERIAL NOT NULL,
	from_node TEXT,
	field_name TEXT,
	target_table TEXT,
	target_pk TEXT,
	to_node TEXT,
	resolution TEXT,
	source_row INTEGER,
	list_index INTEGER,
	PRIMARY KEY (edge_id)
);
CREATE TABLE fish_review_10pct_v1.raw_records (
	table_name TEXT NOT NULL,
	row_number INTEGER NOT NULL,
	source_pk TEXT,
	payload JSON,
	normalized JSON,
	status TEXT,
	issues JSON,
	sample_reason TEXT,
	package_sha256 TEXT,
	PRIMARY KEY (table_name, row_number)
);
CREATE TABLE fish_review_10pct_v1.data_partners (
	id TEXT NOT NULL,
	farm_id TEXT,
	name TEXT,
	partner_type TEXT,
	identity_status TEXT,
	contact TEXT,
	contact_status TEXT,
	region TEXT,
	currency TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_ponds (
	id TEXT NOT NULL,
	farm_id TEXT,
	name TEXT,
	area_m2 BIGINT,
	area_mu NUMERIC,
	mean_depth_m NUMERIC,
	maximum_depth_m NUMERIC,
	effective_volume_m3 NUMERIC,
	shape TEXT,
	bottom_type TEXT,
	inlet_condition TEXT,
	outlet_condition TEXT,
	water_source TEXT,
	commissioned_on DATE,
	current_status TEXT,
	geometry_id TEXT,
	equipment_configuration TEXT,
	previous_cycle_id TEXT,
	previous_cycle_status TEXT,
	centroid_longitude NUMERIC,
	centroid_latitude NUMERIC,
	maintenance_history_status TEXT,
	maintenance_history_note TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_production_plans (
	id TEXT NOT NULL,
	farm_id TEXT,
	year BIGINT,
	mode TEXT,
	technical_document_path TEXT,
	responsible_person_id TEXT,
	start_date DATE,
	end_date DATE,
	status TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_species (
	id TEXT NOT NULL,
	farm_id TEXT,
	standard_name TEXT,
	scientific_name TEXT,
	original_name TEXT,
	species_code TEXT,
	common_commercial_name TEXT,
	mapping_status TEXT,
	mapping_basis TEXT,
	strain TEXT,
	strain_status TEXT,
	origin TEXT,
	brand TEXT,
	brand_status TEXT,
	geographical_indication_qualified BOOLEAN,
	geographical_indication_status TEXT,
	default_role TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_weather_observations (
	id TEXT NOT NULL,
	observed_at TIMESTAMP WITH TIME ZONE,
	air_temperature_c NUMERIC,
	relative_humidity_pct BIGINT,
	precipitation_mm NUMERIC,
	shortwave_w_m2 NUMERIC,
	wind_speed_km_h NUMERIC,
	grid_id TEXT,
	grid_latitude NUMERIC,
	grid_longitude NUMERIC,
	requested_latitude NUMERIC,
	requested_longitude NUMERIC,
	model TEXT,
	spatial_resolution_degree NUMERIC,
	timezone TEXT,
	reference_source_id TEXT,
	origin_kind TEXT,
	is_synthetic BOOLEAN,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_cash_transactions (
	id TEXT NOT NULL,
	farm_id TEXT,
	direction TEXT,
	counterparty_id TEXT,
	amount_cny NUMERIC,
	currency TEXT,
	payment_method TEXT,
	bank_reference TEXT,
	balance_scope TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_cohorts (
	id TEXT NOT NULL,
	farm_id TEXT,
	pond_id TEXT,
	species_id TEXT,
	parent_cohort_id TEXT,
	cohort_definition TEXT,
	role TEXT,
	start_date DATE,
	expected_harvest_date DATE,
	actual_end_date DATE,
	initial_count BIGINT,
	initial_weight_kg NUMERIC,
	initial_mean_weight_g NUMERIC,
	initial_density_fish_per_mu NUMERIC,
	strain TEXT,
	strain_status TEXT,
	seed_origin TEXT,
	original_commercial_name TEXT,
	brand TEXT,
	geographical_indication_qualified BOOLEAN,
	status TEXT,
	technical_plan_id TEXT,
	responsible_person_id TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_devices (
	id TEXT NOT NULL,
	pond_id TEXT,
	device_type TEXT,
	manufacturer TEXT,
	model TEXT,
	rated_power_kw NUMERIC,
	position_id TEXT,
	is_synthetic BOOLEAN,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_patrol_events (
	id TEXT NOT NULL,
	pond_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	operator_id TEXT,
	weather_id TEXT,
	swimming TEXT,
	feeding_behavior TEXT,
	bank_gathering BOOLEAN,
	water_color TEXT,
	transparency_cm NUMERIC,
	odor TEXT,
	algae TEXT,
	foam TEXT,
	dead_count BIGINT,
	dead_weight_kg NUMERIC,
	dead_size_g NUMERIC,
	discovery_point_id TEXT,
	aerator_status TEXT,
	pump_status TEXT,
	feeder_status TEXT,
	exception_description TEXT,
	action TEXT,
	mortality_event_ids TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_pond_maintenance (
	id TEXT NOT NULL,
	pond_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	operation TEXT,
	renovation_status TEXT,
	cost_basis TEXT,
	cost_yuan BIGINT,
	operator_id TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_pond_preparations (
	id TEXT NOT NULL,
	pond_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	previous_cohort_id TEXT,
	previous_cohort_status TEXT,
	operation TEXT,
	disinfectant_product_id TEXT,
	disinfectant_status TEXT,
	dose_kg BIGINT,
	application_method TEXT,
	refill_at TIMESTAMP WITH TIME ZONE,
	water_source TEXT,
	water_level_m NUMERIC,
	water_test_status TEXT,
	equipment_check TEXT,
	operator_id TEXT,
	reviewer_id TEXT,
	repair_cost_yuan BIGINT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_price_observations (
	id TEXT NOT NULL,
	observed_at TIMESTAMP WITH TIME ZONE,
	original_product_name TEXT,
	species_id TEXT,
	species_mapping_status TEXT,
	product_type TEXT,
	grade TEXT,
	quality_grade TEXT,
	freshness TEXT,
	region TEXT,
	market_id TEXT,
	channel TEXT,
	price_yuan_per_kg NUMERIC,
	observation_kind TEXT,
	transaction_volume_kg NUMERIC,
	volume_status TEXT,
	tax_included BOOLEAN,
	freight_included BOOLEAN,
	packaging_included BOOLEAN,
	commission_included BOOLEAN,
	collected_at TIMESTAMP WITH TIME ZONE,
	credibility TEXT,
	reference_source_id TEXT,
	origin_kind TEXT,
	is_synthetic BOOLEAN,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_products (
	id TEXT NOT NULL,
	farm_id TEXT,
	product_name TEXT,
	product_type TEXT,
	unit TEXT,
	assumed_unit_price_cny NUMERIC,
	species_id TEXT,
	brand TEXT,
	brand_status TEXT,
	coarse_protein_pct BIGINT,
	particle_diameter_mm BIGINT,
	shelf_life_days BIGINT,
	manufacturer TEXT,
	registration_number TEXT,
	registration_status TEXT,
	parameter_basis TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_purchases (
	id TEXT NOT NULL,
	farm_id TEXT,
	supplier_id TEXT,
	invoice_number TEXT,
	invoice_status TEXT,
	contract_number TEXT,
	gross_amount_cny NUMERIC,
	amount_cny NUMERIC,
	currency TEXT,
	tax_status TEXT,
	received_on DATE,
	received_at TIMESTAMP WITH TIME ZONE,
	purchase_time_basis TEXT,
	is_consumption_cost BOOLEAN,
	payment_status TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_water_samples (
	id TEXT NOT NULL,
	pond_id TEXT,
	sampled_at TIMESTAMP WITH TIME ZONE,
	sample_point_id TEXT,
	depth_m NUMERIC,
	sampler_id TEXT,
	received_at TIMESTAMP WITH TIME ZONE,
	lab_name TEXT,
	sampling_method TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_attachments (
	id TEXT NOT NULL,
	farm_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	category TEXT,
	relative_path TEXT,
	file_name TEXT,
	mime_type TEXT,
	file_size_bytes BIGINT,
	sha256 TEXT,
	captured_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	capture_device TEXT,
	language TEXT,
	license_status TEXT,
	review_status TEXT,
	origin_kind TEXT,
	is_synthetic BOOLEAN,
	clinical_label_status TEXT,
	intended_use TEXT,
	usage_limitation TEXT,
	generation_run_id TEXT,
	seed BIGINT,
	rule_version TEXT,
	scenario_id TEXT,
	width_px BIGINT,
	height_px BIGINT,
	duration_seconds NUMERIC,
	codec TEXT,
	sample_rate_hz BIGINT,
	channels BIGINT,
	audio_kind TEXT,
	pair_id TEXT,
	voice_name TEXT,
	tts_backend TEXT,
	transcription_method TEXT,
	speaker_identity_status TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_control_commands (
	id TEXT NOT NULL,
	device_id TEXT,
	planned_at TIMESTAMP WITH TIME ZONE,
	issued_at TIMESTAMP WITH TIME ZONE,
	executed_at TIMESTAMP WITH TIME ZONE,
	command TEXT,
	result TEXT,
	alarm TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_cost_allocations (
	id TEXT NOT NULL,
	farm_id TEXT,
	cost_entry_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	beneficiary_type TEXT,
	amount_cny NUMERIC,
	currency TEXT,
	allocation_basis BIGINT,
	allocation_basis_unit TEXT,
	allocation_ratio NUMERIC,
	allocation_method TEXT,
	period_start DATE,
	period_end DATE,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_device_calibrations (
	id TEXT NOT NULL,
	device_id TEXT,
	started_at TIMESTAMP WITH TIME ZONE,
	ended_at TIMESTAMP WITH TIME ZONE,
	method TEXT,
	reference_ph NUMERIC,
	offset_ph NUMERIC,
	result TEXT,
	operator_id TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_device_installations (
	id TEXT NOT NULL,
	device_id TEXT,
	pond_id TEXT,
	installed_at TIMESTAMP WITH TIME ZONE,
	removed_at TIMESTAMP WITH TIME ZONE,
	effective_end_exclusive BOOLEAN,
	position_description TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_device_maintenance (
	id TEXT NOT NULL,
	device_id TEXT,
	pond_id TEXT,
	started_at TIMESTAMP WITH TIME ZONE,
	ended_at TIMESTAMP WITH TIME ZONE,
	fault TEXT,
	operation TEXT,
	replacement_device_id TEXT,
	cost_yuan BIGINT,
	cost_status TEXT,
	result TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_event_registry (
	id TEXT NOT NULL,
	event_table TEXT,
	event_record_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_feeding_events (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	pond_id TEXT,
	cohort_id TEXT,
	species_id TEXT,
	product_id TEXT,
	product_batch_id TEXT,
	quantity_kg NUMERIC,
	daily_total_kg NUMERIC,
	unit_price_cny NUMERIC,
	cost_cny NUMERIC,
	feeding_method TEXT,
	device_id TEXT,
	feeding_area TEXT,
	frequency_per_day BIGINT,
	feeding_intensity TEXT,
	leftover_status TEXT,
	competition_behavior TEXT,
	water_temperature_c NUMERIC,
	dissolved_oxygen_mg_l NUMERIC,
	weather_condition TEXT,
	adjustment_reason TEXT,
	suspended_session_count BIGINT,
	suspended_session_local_time TEXT,
	related_environment_scenario TEXT,
	environment_value_basis TEXT,
	measurement_basis TEXT,
	aggregation_note TEXT,
	nutrition_parameter_basis TEXT,
	coarse_protein_pct BIGINT,
	particle_diameter_mm BIGINT,
	shelf_life_days BIGINT,
	manufacture_on DATE,
	expires_on DATE,
	feed_brand TEXT,
	inventory_selection_policy TEXT,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	water_observation_id TEXT,
	weather_id TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_fish_daily_balance (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	pond_id TEXT,
	cohort_id TEXT,
	species_id TEXT,
	balance_date DATE,
	opening_count BIGINT,
	stocked_count BIGINT,
	transfer_in_count BIGINT,
	transfer_out_count BIGINT,
	mortality_count BIGINT,
	harvest_count BIGINT,
	adjustment_count BIGINT,
	closing_count BIGINT,
	opening_biomass_kg NUMERIC,
	stocked_weight_kg NUMERIC,
	transfer_in_weight_kg NUMERIC,
	transfer_out_weight_kg NUMERIC,
	mortality_weight_kg NUMERIC,
	harvest_weight_kg NUMERIC,
	growth_weight_kg NUMERIC,
	biomass_adjustment_kg NUMERIC,
	closing_biomass_kg NUMERIC,
	closing_mean_weight_g NUMERIC,
	feed_quantity_kg NUMERIC,
	biomass_basis TEXT,
	growth_basis TEXT,
	feed_to_growth_ratio_assumed NUMERIC,
	companion_growth_basis TEXT,
	estimate_error_kg NUMERIC,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_growth_samples (
	id TEXT NOT NULL,
	pond_id TEXT,
	cohort_id TEXT,
	sampled_at TIMESTAMP WITH TIME ZONE,
	sample_point_id TEXT,
	sampling_method TEXT,
	sample_size BIGINT,
	mean_weight_g NUMERIC,
	min_weight_g NUMERIC,
	max_weight_g NUMERIC,
	std_weight_g NUMERIC,
	grade_pass_rate NUMERIC,
	growth_stage TEXT,
	estimated_count BIGINT,
	estimated_biomass_kg NUMERIC,
	estimated_saleable_kg NUMERIC,
	estimate_method TEXT,
	estimate_relative_error NUMERIC,
	confidence_level TEXT,
	tool TEXT,
	operator_id TEXT,
	uniformity_cv NUMERIC,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_harvests (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	pond_id TEXT,
	cohort_id TEXT,
	species_id TEXT,
	harvest_type TEXT,
	method TEXT,
	count BIGINT,
	gross_weight_kg NUMERIC,
	tare_weight_kg NUMERIC,
	net_weight_kg NUMERIC,
	saleable_weight_kg NUMERIC,
	harvest_loss_count BIGINT,
	harvest_loss_weight_kg NUMERIC,
	transport_loss_weight_kg NUMERIC,
	deduction_weight_kg NUMERIC,
	quality_grade TEXT,
	health_status TEXT,
	residue_test_status TEXT,
	disposition TEXT,
	vehicle_id TEXT,
	weighing_basis TEXT,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_health_cases (
	id TEXT NOT NULL,
	pond_id TEXT,
	cohort_id TEXT,
	discovered_at TIMESTAMP WITH TIME ZONE,
	affected_count BIGINT,
	incidence_rate NUMERIC,
	death_count BIGINT,
	mortality_per_day BIGINT,
	duration_days BIGINT,
	diagnosis_status TEXT,
	preliminary_judgment TEXT,
	description TEXT,
	action TEXT,
	recovery TEXT,
	recurrence BOOLEAN,
	population_denominator BIGINT,
	denominator_basis TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_inventory_movements (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	product_id TEXT,
	product_batch_id TEXT,
	movement_type TEXT,
	quantity_delta NUMERIC,
	unit TEXT,
	amount_delta_cny NUMERIC,
	opening_quantity NUMERIC,
	closing_quantity NUMERIC,
	opening_value_cny NUMERIC,
	closing_value_cny NUMERIC,
	lot_opening_quantity NUMERIC,
	lot_closing_quantity NUMERIC,
	lot_opening_value_cny NUMERIC,
	lot_closing_value_cny NUMERIC,
	valuation_method TEXT,
	source_type TEXT,
	source_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	movement_reason TEXT,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_opening_balances (
	id TEXT NOT NULL,
	farm_id TEXT,
	balance_type TEXT,
	product_id TEXT,
	quantity NUMERIC,
	unit TEXT,
	amount_cny NUMERIC,
	currency TEXT,
	valuation_method TEXT,
	as_of TIMESTAMP WITH TIME ZONE,
	pond_id TEXT,
	cohort_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_pond_cohort_occupancy (
	id TEXT NOT NULL,
	farm_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	entered_at TIMESTAMP WITH TIME ZONE,
	left_at TIMESTAMP WITH TIME ZONE,
	role TEXT,
	entry_reason TEXT,
	exit_reason TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_purchase_items (
	id TEXT NOT NULL,
	farm_id TEXT,
	purchase_id TEXT,
	product_id TEXT,
	product_batch_id TEXT,
	quantity NUMERIC,
	unit TEXT,
	unit_price_cny NUMERIC,
	amount_cny NUMERIC,
	supplier_id TEXT,
	valuation_method TEXT,
	transaction_time_basis TEXT,
	manufacture_on DATE,
	expires_on DATE,
	expiry_status TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_record_provenance (
	id TEXT NOT NULL,
	"table" TEXT,
	record_id TEXT,
	farm_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	origin_kind TEXT,
	is_synthetic BOOLEAN,
	reference_source_id TEXT,
	generation_run_id TEXT,
	rule_version TEXT,
	seed BIGINT,
	scenario_id TEXT,
	parameter_basis TEXT,
	source_system TEXT,
	source_record_number TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	source_timezone TEXT,
	time_precision TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	review_status TEXT,
	source_page TEXT,
	source_page_status TEXT,
	is_estimated BOOLEAN,
	missing_status TEXT,
	modification_reason TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_sales (
	id TEXT NOT NULL,
	farm_id TEXT,
	customer_id TEXT,
	species_id TEXT,
	channel TEXT,
	contract_number TEXT,
	order_number TEXT,
	currency TEXT,
	tax_status TEXT,
	freight_bearer TEXT,
	commission_bearer TEXT,
	invoice_status TEXT,
	invoice_on DATE,
	live_status TEXT,
	gross_revenue_cny NUMERIC,
	net_weight_kg NUMERIC,
	gross_weight_kg NUMERIC,
	tare_weight_kg NUMERIC,
	return_weight_kg NUMERIC,
	actual_trade BOOLEAN,
	quote_observation_id TEXT,
	price_basis TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_transfer_events (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	source_pond_id TEXT,
	source_cohort_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	species_id TEXT,
	transferred_out_count BIGINT,
	transferred_out_weight_kg NUMERIC,
	received_count BIGINT,
	received_weight_kg NUMERIC,
	loss_count BIGINT,
	loss_weight_kg NUMERIC,
	reason TEXT,
	mean_weight_g NUMERIC,
	size_basis TEXT,
	loss_cause TEXT,
	operation_person_id TEXT,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_water_observations (
	id TEXT NOT NULL,
	pond_id TEXT,
	device_id TEXT,
	observed_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	sample_point_id TEXT,
	depth_m NUMERIC,
	temperature_c NUMERIC,
	do_mg_l NUMERIC,
	ph NUMERIC,
	raw_ph NUMERIC,
	ph_correction NUMERIC,
	method TEXT,
	measurement_context TEXT,
	environment_condition TEXT,
	quality_flag TEXT,
	missing_reason TEXT,
	review_status TEXT,
	weather_id TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_water_operations (
	id TEXT NOT NULL,
	pond_id TEXT,
	started_at TIMESTAMP WITH TIME ZONE,
	ended_at TIMESTAMP WITH TIME ZONE,
	operation TEXT,
	inflow_m3 BIGINT,
	outflow_m3 BIGINT,
	water_source TEXT,
	product_id TEXT,
	dose_kg NUMERIC,
	dose_status TEXT,
	do_before_mg_l NUMERIC,
	do_after_mg_l NUMERIC,
	fish_before TEXT,
	fish_after TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_water_test_results (
	id TEXT NOT NULL,
	sample_id TEXT,
	analyte_code TEXT,
	value NUMERIC,
	raw_value TEXT,
	corrected_value NUMERIC,
	unit TEXT,
	expression_basis TEXT,
	method TEXT,
	instrument_id TEXT,
	detection_limit NUMERIC,
	result_status TEXT,
	missing_reason TEXT,
	verified_by TEXT,
	reported_at TIMESTAMP WITH TIME ZONE,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_attachment_links (
	id TEXT NOT NULL,
	attachment_id TEXT,
	entity_table TEXT,
	entity_id TEXT,
	relation_type TEXT,
	evidence_status TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_case_observations (
	id TEXT NOT NULL,
	case_id TEXT,
	observed_at TIMESTAMP WITH TIME ZONE,
	behavior TEXT,
	skin_description TEXT,
	gill_description TEXT,
	viscera_description TEXT,
	diagnosis_basis TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_device_operations (
	id TEXT NOT NULL,
	device_id TEXT,
	pond_id TEXT,
	started_at TIMESTAMP WITH TIME ZONE,
	ended_at TIMESTAMP WITH TIME ZONE,
	duration_h BIGINT,
	energy_kwh NUMERIC,
	energy_basis TEXT,
	reason TEXT,
	command_id TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_diagnostic_tests (
	id TEXT NOT NULL,
	case_id TEXT,
	lab_name TEXT,
	report_number TEXT,
	sampled_at TIMESTAMP WITH TIME ZONE,
	reported_at TIMESTAMP WITH TIME ZONE,
	pathogen_code TEXT,
	method TEXT,
	result TEXT,
	diagnosis_status TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_growth_grade_items (
	id TEXT NOT NULL,
	sample_id TEXT,
	grade TEXT,
	count BIGINT,
	proportion NUMERIC,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_growth_individuals (
	id TEXT NOT NULL,
	sample_id TEXT,
	body_length_cm NUMERIC,
	total_length_cm NUMERIC,
	weight_g NUMERIC,
	health_status TEXT,
	appearance TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_harvest_grade_items (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	harvest_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	species_id TEXT,
	grade TEXT,
	count BIGINT,
	net_weight_kg NUMERIC,
	weight_ratio NUMERIC,
	mean_weight_g NUMERIC,
	quality_grade TEXT,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_inventory_lot_status (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	product_id TEXT,
	product_batch_id TEXT,
	as_of TIMESTAMP WITH TIME ZONE,
	closing_quantity NUMERIC,
	unit TEXT,
	closing_value_cny NUMERIC,
	currency TEXT,
	manufacture_on DATE,
	expires_on DATE,
	expiry_status TEXT,
	usability_status TEXT,
	available_quantity NUMERIC,
	expiry_assessment TEXT,
	disposal_status TEXT,
	valuation_basis TEXT,
	source_inventory_movement_id TEXT,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_media_annotations (
	id TEXT NOT NULL,
	attachment_id TEXT,
	annotation_type TEXT,
	label TEXT,
	annotation_text TEXT,
	annotation_basis TEXT,
	diagnosis_status TEXT,
	diagnostic_training_allowed BOOLEAN,
	reviewer TEXT,
	review_status TEXT,
	version TEXT,
	frame_start BIGINT,
	frame_end BIGINT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_mortality_events (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	pond_id TEXT,
	cohort_id TEXT,
	species_id TEXT,
	count BIGINT,
	weight_kg NUMERIC,
	mean_weight_g NUMERIC,
	possible_cause TEXT,
	cause_status TEXT,
	related_health_case_id TEXT,
	discovery_location TEXT,
	count_basis TEXT,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_sale_items (
	id TEXT NOT NULL,
	farm_id TEXT,
	sale_id TEXT,
	species_id TEXT,
	grade TEXT,
	quality_grade TEXT,
	net_weight_kg NUMERIC,
	unit_price_cny_per_kg NUMERIC,
	amount_cny NUMERIC,
	discount_cny NUMERIC,
	original_commercial_name TEXT,
	species_mapping_status TEXT,
	brand TEXT,
	origin TEXT,
	geographical_indication_qualified BOOLEAN,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_settlements (
	id TEXT NOT NULL,
	farm_id TEXT,
	sale_id TEXT,
	customer_id TEXT,
	gross_sales_amount_cny NUMERIC,
	deductions_amount_cny NUMERIC,
	net_amount_cny NUMERIC,
	received_amount_cny NUMERIC,
	outstanding_amount_cny NUMERIC,
	actual_net_unit_price_cny_per_kg NUMERIC,
	payment_terms_days BIGINT,
	due_on DATE,
	final_received_on DATE,
	currency TEXT,
	status TEXT,
	profit_basis TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_spatial_layer_registry (
	id TEXT NOT NULL,
	attachment_id TEXT,
	layer_name TEXT,
	geometry_kind TEXT,
	crs TEXT,
	coordinate_order TEXT,
	captured_at TIMESTAMP WITH TIME ZONE,
	version TEXT,
	resolution_m NUMERIC,
	resolution_degrees TEXT,
	accuracy_m NUMERIC,
	accuracy_status TEXT,
	scale_status TEXT,
	source TEXT,
	feature_count BIGINT,
	bbox TEXT,
	coverage TEXT,
	relative_path TEXT,
	sha256 TEXT,
	is_synthetic BOOLEAN,
	usage_limitation TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_stocking_events (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	pond_id TEXT,
	cohort_id TEXT,
	species_id TEXT,
	purchase_item_id TEXT,
	product_id TEXT,
	seed_batch_id TEXT,
	supplier_id TEXT,
	count BIGINT,
	weight_kg NUMERIC,
	mean_weight_g BIGINT,
	size_distribution TEXT,
	stocking_density_fish_per_mu NUMERIC,
	unit_price_cny NUMERIC,
	total_cost_cny NUMERIC,
	transport_method TEXT,
	transport_duration_hours NUMERIC,
	transport_mortality_count BIGINT,
	transport_mortality_rate NUMERIC,
	health_status TEXT,
	quarantine_certificate_id TEXT,
	quarantine_status TEXT,
	water_temperature_c NUMERIC,
	dissolved_oxygen_mg_l NUMERIC,
	temperature_difference_c NUMERIC,
	acclimation_method TEXT,
	count_basis TEXT,
	weight_basis TEXT,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_transfer_allocations (
	id TEXT NOT NULL,
	farm_id TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	transfer_event_id TEXT,
	source_pond_id TEXT,
	source_cohort_id TEXT,
	target_pond_id TEXT,
	target_cohort_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	count BIGINT,
	weight_kg NUMERIC,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_treatment_events (
	id TEXT NOT NULL,
	case_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	started_at TIMESTAMP WITH TIME ZONE,
	stopped_at TIMESTAMP WITH TIME ZONE,
	operation_reason TEXT,
	product_id TEXT,
	product_name TEXT,
	approval_number TEXT,
	manufacturer_lot TEXT,
	active_ingredient TEXT,
	dose NUMERIC,
	concentration NUMERIC,
	method TEXT,
	course_days BIGINT,
	target_species TEXT,
	target_disease TEXT,
	contraindications TEXT,
	withdrawal_days BIGINT,
	withdrawal_status TEXT,
	earliest_harvest_date DATE,
	product_parameter_status TEXT,
	operator_id TEXT,
	advisor_id TEXT,
	purchase_cost_yuan BIGINT,
	effect TEXT,
	adverse_reaction TEXT,
	execution_status TEXT,
	precautions TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_cash_allocations (
	id TEXT NOT NULL,
	farm_id TEXT,
	cash_transaction_id TEXT,
	purchase_id TEXT,
	settlement_id TEXT,
	cost_entry_id TEXT,
	amount_cny NUMERIC,
	allocation_type TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_disposal_events (
	id TEXT NOT NULL,
	farm_id TEXT,
	event_id TEXT,
	mortality_event_id TEXT,
	transfer_event_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	count BIGINT,
	weight_kg NUMERIC,
	method TEXT,
	service_partner_id TEXT,
	cost_cny NUMERIC,
	certificate_id TEXT,
	certificate_status TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	recovery_method TEXT,
	transport_method TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
CREATE TABLE fish_review_10pct_v1.data_harvest_sale_allocations (
	id TEXT NOT NULL,
	farm_id TEXT,
	harvest_id TEXT,
	harvest_grade_item_id TEXT,
	sale_id TEXT,
	sale_item_id TEXT,
	pond_id TEXT,
	cohort_id TEXT,
	species_id TEXT,
	grade TEXT,
	allocated_net_weight_kg NUMERIC,
	allocation_basis TEXT,
	occurred_at TIMESTAMP WITH TIME ZONE,
	recorded_at TIMESTAMP WITH TIME ZONE,
	uploaded_at TIMESTAMP WITH TIME ZONE,
	ingested_at TIMESTAMP WITH TIME ZONE,
	updated_at TIMESTAMP WITH TIME ZONE,
	event_id TEXT,
	source_record_id TEXT,
	recorder_id TEXT,
	reviewer_id TEXT,
	source_system TEXT,
	review_status TEXT,
	quality_flag TEXT,
	is_estimated BOOLEAN,
	source_timezone TEXT,
	time_precision TEXT,
	_source_row INTEGER,
	_data_nature TEXT,
	PRIMARY KEY (id)
);
ALTER TABLE fish_review_10pct_v1.data_farms ADD CONSTRAINT fk_farms_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_partners ADD CONSTRAINT fk_partners_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_ponds ADD CONSTRAINT fk_ponds_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_production_plans ADD CONSTRAINT fk_production_plans_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_production_plans ADD CONSTRAINT fk_production_plans_1 FOREIGN KEY(responsible_person_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_species ADD CONSTRAINT fk_species_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_weather_observations ADD CONSTRAINT fk_weather_observations_0 FOREIGN KEY(reference_source_id) REFERENCES fish_review_10pct_v1.data_sources (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_transactions ADD CONSTRAINT fk_cash_transactions_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_transactions ADD CONSTRAINT fk_cash_transactions_1 FOREIGN KEY(counterparty_id) REFERENCES fish_review_10pct_v1.data_partners (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_transactions ADD CONSTRAINT fk_cash_transactions_2 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_transactions ADD CONSTRAINT fk_cash_transactions_3 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cohorts ADD CONSTRAINT fk_cohorts_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cohorts ADD CONSTRAINT fk_cohorts_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cohorts ADD CONSTRAINT fk_cohorts_2 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cohorts ADD CONSTRAINT fk_cohorts_3 FOREIGN KEY(parent_cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cohorts ADD CONSTRAINT fk_cohorts_4 FOREIGN KEY(technical_plan_id) REFERENCES fish_review_10pct_v1.data_production_plans (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cohorts ADD CONSTRAINT fk_cohorts_5 FOREIGN KEY(responsible_person_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_devices ADD CONSTRAINT fk_devices_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_patrol_events ADD CONSTRAINT fk_patrol_events_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_patrol_events ADD CONSTRAINT fk_patrol_events_1 FOREIGN KEY(operator_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_patrol_events ADD CONSTRAINT fk_patrol_events_2 FOREIGN KEY(weather_id) REFERENCES fish_review_10pct_v1.data_weather_observations (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_maintenance ADD CONSTRAINT fk_pond_maintenance_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_maintenance ADD CONSTRAINT fk_pond_maintenance_1 FOREIGN KEY(operator_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_preparations ADD CONSTRAINT fk_pond_preparations_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_preparations ADD CONSTRAINT fk_pond_preparations_1 FOREIGN KEY(operator_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_preparations ADD CONSTRAINT fk_pond_preparations_2 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_price_observations ADD CONSTRAINT fk_price_observations_0 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_price_observations ADD CONSTRAINT fk_price_observations_1 FOREIGN KEY(reference_source_id) REFERENCES fish_review_10pct_v1.data_sources (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_products ADD CONSTRAINT fk_products_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_products ADD CONSTRAINT fk_products_1 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchases ADD CONSTRAINT fk_purchases_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchases ADD CONSTRAINT fk_purchases_1 FOREIGN KEY(supplier_id) REFERENCES fish_review_10pct_v1.data_partners (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchases ADD CONSTRAINT fk_purchases_2 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchases ADD CONSTRAINT fk_purchases_3 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_samples ADD CONSTRAINT fk_water_samples_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_samples ADD CONSTRAINT fk_water_samples_1 FOREIGN KEY(sampler_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_attachments ADD CONSTRAINT fk_attachments_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_attachments ADD CONSTRAINT fk_attachments_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_attachments ADD CONSTRAINT fk_attachments_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_control_commands ADD CONSTRAINT fk_control_commands_0 FOREIGN KEY(device_id) REFERENCES fish_review_10pct_v1.data_devices (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cost_allocations ADD CONSTRAINT fk_cost_allocations_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cost_allocations ADD CONSTRAINT fk_cost_allocations_1 FOREIGN KEY(cost_entry_id) REFERENCES fish_review_10pct_v1.data_cost_entries (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cost_allocations ADD CONSTRAINT fk_cost_allocations_2 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cost_allocations ADD CONSTRAINT fk_cost_allocations_3 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cost_allocations ADD CONSTRAINT fk_cost_allocations_4 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cost_allocations ADD CONSTRAINT fk_cost_allocations_5 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_calibrations ADD CONSTRAINT fk_device_calibrations_0 FOREIGN KEY(device_id) REFERENCES fish_review_10pct_v1.data_devices (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_calibrations ADD CONSTRAINT fk_device_calibrations_1 FOREIGN KEY(operator_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_installations ADD CONSTRAINT fk_device_installations_0 FOREIGN KEY(device_id) REFERENCES fish_review_10pct_v1.data_devices (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_installations ADD CONSTRAINT fk_device_installations_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_maintenance ADD CONSTRAINT fk_device_maintenance_0 FOREIGN KEY(device_id) REFERENCES fish_review_10pct_v1.data_devices (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_maintenance ADD CONSTRAINT fk_device_maintenance_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_event_registry ADD CONSTRAINT fk_event_registry_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_event_registry ADD CONSTRAINT fk_event_registry_1 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_3 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_4 FOREIGN KEY(product_id) REFERENCES fish_review_10pct_v1.data_products (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_5 FOREIGN KEY(device_id) REFERENCES fish_review_10pct_v1.data_devices (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_6 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_7 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_feeding_events ADD CONSTRAINT fk_feeding_events_9 FOREIGN KEY(weather_id) REFERENCES fish_review_10pct_v1.data_weather_observations (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_fish_daily_balance ADD CONSTRAINT fk_fish_daily_balance_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_fish_daily_balance ADD CONSTRAINT fk_fish_daily_balance_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_fish_daily_balance ADD CONSTRAINT fk_fish_daily_balance_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_fish_daily_balance ADD CONSTRAINT fk_fish_daily_balance_3 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_fish_daily_balance ADD CONSTRAINT fk_fish_daily_balance_4 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_fish_daily_balance ADD CONSTRAINT fk_fish_daily_balance_5 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_growth_samples ADD CONSTRAINT fk_growth_samples_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_growth_samples ADD CONSTRAINT fk_growth_samples_1 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_growth_samples ADD CONSTRAINT fk_growth_samples_2 FOREIGN KEY(operator_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvests ADD CONSTRAINT fk_harvests_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvests ADD CONSTRAINT fk_harvests_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvests ADD CONSTRAINT fk_harvests_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvests ADD CONSTRAINT fk_harvests_3 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvests ADD CONSTRAINT fk_harvests_4 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvests ADD CONSTRAINT fk_harvests_5 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_health_cases ADD CONSTRAINT fk_health_cases_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_health_cases ADD CONSTRAINT fk_health_cases_1 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_movements ADD CONSTRAINT fk_inventory_movements_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_movements ADD CONSTRAINT fk_inventory_movements_1 FOREIGN KEY(product_id) REFERENCES fish_review_10pct_v1.data_products (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_movements ADD CONSTRAINT fk_inventory_movements_2 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_movements ADD CONSTRAINT fk_inventory_movements_3 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_movements ADD CONSTRAINT fk_inventory_movements_4 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_movements ADD CONSTRAINT fk_inventory_movements_5 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_opening_balances ADD CONSTRAINT fk_opening_balances_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_opening_balances ADD CONSTRAINT fk_opening_balances_1 FOREIGN KEY(product_id) REFERENCES fish_review_10pct_v1.data_products (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_opening_balances ADD CONSTRAINT fk_opening_balances_2 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_opening_balances ADD CONSTRAINT fk_opening_balances_3 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_opening_balances ADD CONSTRAINT fk_opening_balances_4 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_opening_balances ADD CONSTRAINT fk_opening_balances_5 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_cohort_occupancy ADD CONSTRAINT fk_pond_cohort_occupancy_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_cohort_occupancy ADD CONSTRAINT fk_pond_cohort_occupancy_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_cohort_occupancy ADD CONSTRAINT fk_pond_cohort_occupancy_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_cohort_occupancy ADD CONSTRAINT fk_pond_cohort_occupancy_3 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_pond_cohort_occupancy ADD CONSTRAINT fk_pond_cohort_occupancy_4 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchase_items ADD CONSTRAINT fk_purchase_items_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchase_items ADD CONSTRAINT fk_purchase_items_1 FOREIGN KEY(purchase_id) REFERENCES fish_review_10pct_v1.data_purchases (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchase_items ADD CONSTRAINT fk_purchase_items_2 FOREIGN KEY(product_id) REFERENCES fish_review_10pct_v1.data_products (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchase_items ADD CONSTRAINT fk_purchase_items_3 FOREIGN KEY(supplier_id) REFERENCES fish_review_10pct_v1.data_partners (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchase_items ADD CONSTRAINT fk_purchase_items_4 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_purchase_items ADD CONSTRAINT fk_purchase_items_5 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_record_provenance ADD CONSTRAINT fk_record_provenance_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_record_provenance ADD CONSTRAINT fk_record_provenance_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_record_provenance ADD CONSTRAINT fk_record_provenance_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_record_provenance ADD CONSTRAINT fk_record_provenance_3 FOREIGN KEY(reference_source_id) REFERENCES fish_review_10pct_v1.data_sources (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_record_provenance ADD CONSTRAINT fk_record_provenance_4 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_record_provenance ADD CONSTRAINT fk_record_provenance_5 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sales ADD CONSTRAINT fk_sales_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sales ADD CONSTRAINT fk_sales_1 FOREIGN KEY(customer_id) REFERENCES fish_review_10pct_v1.data_partners (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sales ADD CONSTRAINT fk_sales_2 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sales ADD CONSTRAINT fk_sales_3 FOREIGN KEY(quote_observation_id) REFERENCES fish_review_10pct_v1.data_price_observations (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sales ADD CONSTRAINT fk_sales_4 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sales ADD CONSTRAINT fk_sales_5 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_1 FOREIGN KEY(source_pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_2 FOREIGN KEY(source_cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_3 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_4 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_5 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_6 FOREIGN KEY(operation_person_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_7 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_events ADD CONSTRAINT fk_transfer_events_8 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_observations ADD CONSTRAINT fk_water_observations_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_observations ADD CONSTRAINT fk_water_observations_1 FOREIGN KEY(device_id) REFERENCES fish_review_10pct_v1.data_devices (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_observations ADD CONSTRAINT fk_water_observations_2 FOREIGN KEY(weather_id) REFERENCES fish_review_10pct_v1.data_weather_observations (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_operations ADD CONSTRAINT fk_water_operations_0 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_operations ADD CONSTRAINT fk_water_operations_1 FOREIGN KEY(product_id) REFERENCES fish_review_10pct_v1.data_products (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_test_results ADD CONSTRAINT fk_water_test_results_0 FOREIGN KEY(sample_id) REFERENCES fish_review_10pct_v1.data_water_samples (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_water_test_results ADD CONSTRAINT fk_water_test_results_1 FOREIGN KEY(verified_by) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_attachment_links ADD CONSTRAINT fk_attachment_links_0 FOREIGN KEY(attachment_id) REFERENCES fish_review_10pct_v1.data_attachments (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_case_observations ADD CONSTRAINT fk_case_observations_0 FOREIGN KEY(case_id) REFERENCES fish_review_10pct_v1.data_health_cases (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_operations ADD CONSTRAINT fk_device_operations_0 FOREIGN KEY(device_id) REFERENCES fish_review_10pct_v1.data_devices (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_operations ADD CONSTRAINT fk_device_operations_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_device_operations ADD CONSTRAINT fk_device_operations_2 FOREIGN KEY(command_id) REFERENCES fish_review_10pct_v1.data_control_commands (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_diagnostic_tests ADD CONSTRAINT fk_diagnostic_tests_0 FOREIGN KEY(case_id) REFERENCES fish_review_10pct_v1.data_health_cases (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_growth_grade_items ADD CONSTRAINT fk_growth_grade_items_0 FOREIGN KEY(sample_id) REFERENCES fish_review_10pct_v1.data_growth_samples (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_growth_individuals ADD CONSTRAINT fk_growth_individuals_0 FOREIGN KEY(sample_id) REFERENCES fish_review_10pct_v1.data_growth_samples (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_grade_items ADD CONSTRAINT fk_harvest_grade_items_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_grade_items ADD CONSTRAINT fk_harvest_grade_items_1 FOREIGN KEY(harvest_id) REFERENCES fish_review_10pct_v1.data_harvests (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_grade_items ADD CONSTRAINT fk_harvest_grade_items_2 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_grade_items ADD CONSTRAINT fk_harvest_grade_items_3 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_grade_items ADD CONSTRAINT fk_harvest_grade_items_4 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_grade_items ADD CONSTRAINT fk_harvest_grade_items_5 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_grade_items ADD CONSTRAINT fk_harvest_grade_items_6 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_lot_status ADD CONSTRAINT fk_inventory_lot_status_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_lot_status ADD CONSTRAINT fk_inventory_lot_status_1 FOREIGN KEY(product_id) REFERENCES fish_review_10pct_v1.data_products (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_lot_status ADD CONSTRAINT fk_inventory_lot_status_2 FOREIGN KEY(source_inventory_movement_id) REFERENCES fish_review_10pct_v1.data_inventory_movements (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_lot_status ADD CONSTRAINT fk_inventory_lot_status_3 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_inventory_lot_status ADD CONSTRAINT fk_inventory_lot_status_4 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_media_annotations ADD CONSTRAINT fk_media_annotations_0 FOREIGN KEY(attachment_id) REFERENCES fish_review_10pct_v1.data_attachments (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_mortality_events ADD CONSTRAINT fk_mortality_events_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_mortality_events ADD CONSTRAINT fk_mortality_events_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_mortality_events ADD CONSTRAINT fk_mortality_events_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_mortality_events ADD CONSTRAINT fk_mortality_events_3 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_mortality_events ADD CONSTRAINT fk_mortality_events_4 FOREIGN KEY(related_health_case_id) REFERENCES fish_review_10pct_v1.data_health_cases (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_mortality_events ADD CONSTRAINT fk_mortality_events_5 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_mortality_events ADD CONSTRAINT fk_mortality_events_6 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sale_items ADD CONSTRAINT fk_sale_items_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sale_items ADD CONSTRAINT fk_sale_items_1 FOREIGN KEY(sale_id) REFERENCES fish_review_10pct_v1.data_sales (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sale_items ADD CONSTRAINT fk_sale_items_2 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sale_items ADD CONSTRAINT fk_sale_items_3 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_sale_items ADD CONSTRAINT fk_sale_items_4 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_settlements ADD CONSTRAINT fk_settlements_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_settlements ADD CONSTRAINT fk_settlements_1 FOREIGN KEY(sale_id) REFERENCES fish_review_10pct_v1.data_sales (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_settlements ADD CONSTRAINT fk_settlements_2 FOREIGN KEY(customer_id) REFERENCES fish_review_10pct_v1.data_partners (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_settlements ADD CONSTRAINT fk_settlements_3 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_settlements ADD CONSTRAINT fk_settlements_4 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_spatial_layer_registry ADD CONSTRAINT fk_spatial_layer_registry_0 FOREIGN KEY(attachment_id) REFERENCES fish_review_10pct_v1.data_attachments (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_3 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_4 FOREIGN KEY(purchase_item_id) REFERENCES fish_review_10pct_v1.data_purchase_items (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_5 FOREIGN KEY(product_id) REFERENCES fish_review_10pct_v1.data_products (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_6 FOREIGN KEY(supplier_id) REFERENCES fish_review_10pct_v1.data_partners (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_7 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_stocking_events ADD CONSTRAINT fk_stocking_events_8 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_1 FOREIGN KEY(transfer_event_id) REFERENCES fish_review_10pct_v1.data_transfer_events (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_2 FOREIGN KEY(source_pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_3 FOREIGN KEY(source_cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_4 FOREIGN KEY(target_pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_5 FOREIGN KEY(target_cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_6 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_7 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_8 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_transfer_allocations ADD CONSTRAINT fk_transfer_allocations_9 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_treatment_events ADD CONSTRAINT fk_treatment_events_0 FOREIGN KEY(case_id) REFERENCES fish_review_10pct_v1.data_health_cases (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_treatment_events ADD CONSTRAINT fk_treatment_events_1 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_treatment_events ADD CONSTRAINT fk_treatment_events_2 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_treatment_events ADD CONSTRAINT fk_treatment_events_3 FOREIGN KEY(product_id) REFERENCES fish_review_10pct_v1.data_products (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_treatment_events ADD CONSTRAINT fk_treatment_events_4 FOREIGN KEY(operator_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_treatment_events ADD CONSTRAINT fk_treatment_events_5 FOREIGN KEY(advisor_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_allocations ADD CONSTRAINT fk_cash_allocations_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_allocations ADD CONSTRAINT fk_cash_allocations_1 FOREIGN KEY(cash_transaction_id) REFERENCES fish_review_10pct_v1.data_cash_transactions (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_allocations ADD CONSTRAINT fk_cash_allocations_2 FOREIGN KEY(purchase_id) REFERENCES fish_review_10pct_v1.data_purchases (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_allocations ADD CONSTRAINT fk_cash_allocations_3 FOREIGN KEY(settlement_id) REFERENCES fish_review_10pct_v1.data_settlements (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_allocations ADD CONSTRAINT fk_cash_allocations_4 FOREIGN KEY(cost_entry_id) REFERENCES fish_review_10pct_v1.data_cost_entries (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_allocations ADD CONSTRAINT fk_cash_allocations_5 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_cash_allocations ADD CONSTRAINT fk_cash_allocations_6 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_disposal_events ADD CONSTRAINT fk_disposal_events_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_disposal_events ADD CONSTRAINT fk_disposal_events_1 FOREIGN KEY(mortality_event_id) REFERENCES fish_review_10pct_v1.data_mortality_events (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_disposal_events ADD CONSTRAINT fk_disposal_events_2 FOREIGN KEY(transfer_event_id) REFERENCES fish_review_10pct_v1.data_transfer_events (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_disposal_events ADD CONSTRAINT fk_disposal_events_3 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_disposal_events ADD CONSTRAINT fk_disposal_events_4 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_disposal_events ADD CONSTRAINT fk_disposal_events_5 FOREIGN KEY(service_partner_id) REFERENCES fish_review_10pct_v1.data_partners (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_disposal_events ADD CONSTRAINT fk_disposal_events_6 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_disposal_events ADD CONSTRAINT fk_disposal_events_7 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_0 FOREIGN KEY(farm_id) REFERENCES fish_review_10pct_v1.data_farms (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_1 FOREIGN KEY(harvest_id) REFERENCES fish_review_10pct_v1.data_harvests (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_2 FOREIGN KEY(harvest_grade_item_id) REFERENCES fish_review_10pct_v1.data_harvest_grade_items (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_3 FOREIGN KEY(sale_id) REFERENCES fish_review_10pct_v1.data_sales (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_4 FOREIGN KEY(sale_item_id) REFERENCES fish_review_10pct_v1.data_sale_items (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_5 FOREIGN KEY(pond_id) REFERENCES fish_review_10pct_v1.data_ponds (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_6 FOREIGN KEY(cohort_id) REFERENCES fish_review_10pct_v1.data_cohorts (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_7 FOREIGN KEY(species_id) REFERENCES fish_review_10pct_v1.data_species (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_8 FOREIGN KEY(recorder_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.data_harvest_sale_allocations ADD CONSTRAINT fk_harvest_sale_allocations_9 FOREIGN KEY(reviewer_id) REFERENCES fish_review_10pct_v1.data_persons (id) DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE fish_review_10pct_v1.gis_features ADD COLUMN geom geometry(Geometry,4326);
CREATE INDEX gis_review_geometry ON fish_review_10pct_v1.gis_features USING gist(geom);
ALTER TABLE fish_review_10pct_v1.ontology_relations ADD FOREIGN KEY(from_node) REFERENCES fish_review_10pct_v1.ontology_nodes(node_id), ADD FOREIGN KEY(to_node) REFERENCES fish_review_10pct_v1.ontology_nodes(node_id);
ALTER TABLE fish_review_10pct_v1.gis_features ADD FOREIGN KEY(owner_node) REFERENCES fish_review_10pct_v1.ontology_nodes(node_id);
