CREATE TABLE area_capability_settings (
	id VARCHAR(36) NOT NULL, 
	area_id VARCHAR(36) NOT NULL, 
	plugin_id VARCHAR(160) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_area_capability UNIQUE (area_id, plugin_id), 
	FOREIGN KEY(area_id) REFERENCES interest_areas (id)
);
CREATE INDEX ix_area_capability_settings_area_id ON area_capability_settings (area_id);
CREATE INDEX ix_area_capability_settings_plugin_id ON area_capability_settings (plugin_id);
CREATE TABLE artifacts (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	kind VARCHAR(40) NOT NULL, 
	"key" TEXT NOT NULL, 
	title TEXT NOT NULL, 
	metadata JSON NOT NULL, 
	human_review_required BOOLEAN NOT NULL, 
	approved_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id)
);
INSERT INTO "artifacts" ("id","topic_id","kind","key","title","metadata","human_review_required","approved_at","created_at") VALUES ('art-fixture-0001','topic-fixture-0001','card','golden-hour-card','黄金时刻备忘卡','{}',1,NULL,'2025-01-15 09:00:00.000000');
CREATE INDEX ix_artifacts_kind ON artifacts (kind);
CREATE INDEX ix_artifacts_topic_id ON artifacts (topic_id);
CREATE TABLE capability_runs (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	capability VARCHAR(80) NOT NULL, 
	engine VARCHAR(80) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	input_json JSON NOT NULL, 
	output_json JSON NOT NULL, 
	limitations JSON NOT NULL, 
	error TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id)
);
CREATE INDEX ix_capability_runs_status ON capability_runs (status);
CREATE INDEX ix_capability_runs_topic_id ON capability_runs (topic_id);
CREATE TABLE career_experiments (
	id VARCHAR(36) NOT NULL, 
	direction VARCHAR(120) NOT NULL, 
	hypothesis TEXT NOT NULL, 
	experiment TEXT NOT NULL, 
	evidence TEXT NOT NULL, 
	interest_before INTEGER NOT NULL, 
	interest_after INTEGER, 
	competence_boundary VARCHAR(48) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	reflection TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_career_experiments_direction ON career_experiments (direction);
CREATE INDEX ix_career_experiments_status ON career_experiments (status);
CREATE TABLE claim_versions (
	id VARCHAR(36) NOT NULL, 
	claim_id VARCHAR(36) NOT NULL, 
	version INTEGER NOT NULL, 
	statement TEXT NOT NULL, 
	supporting_evidence JSON NOT NULL, 
	contradicting_evidence JSON NOT NULL, 
	limitations TEXT NOT NULL, 
	reason_for_revision TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(claim_id) REFERENCES claims (id)
);
INSERT INTO "claim_versions" ("id","claim_id","version","statement","supporting_evidence","contradicting_evidence","limitations","reason_for_revision","created_at") VALUES ('cv-fixture-0001','claim-fixture-0001',1,'黄金时刻光线色彩更暖、对比更低。','[]','[]','','','2025-01-15 09:00:00.000000');
CREATE INDEX ix_claim_versions_claim_id ON claim_versions (claim_id);
CREATE TABLE claims (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36) NOT NULL, 
	current_version_id VARCHAR(36), 
	status VARCHAR(32) NOT NULL, 
	confidence FLOAT NOT NULL, 
	source_level VARCHAR(32) NOT NULL, 
	publishability VARCHAR(40) NOT NULL, 
	verification_state VARCHAR(32) NOT NULL, 
	last_verified_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id)
);
INSERT INTO "claims" ("id","topic_id","current_version_id","status","confidence","source_level","publishability","verification_state","last_verified_at","created_at","updated_at") VALUES ('claim-fixture-0001','topic-fixture-0001',NULL,'draft',0.5,'mixed','internal_only','unverified',NULL,'2025-01-15 09:00:00.000000','2025-01-15 09:00:00.000000');
CREATE INDEX ix_claims_topic_id ON claims (topic_id);
CREATE TABLE concepts (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	name VARCHAR(240) NOT NULL, 
	definition TEXT NOT NULL, 
	examples JSON NOT NULL, 
	counterexamples JSON NOT NULL, 
	confused_with JSON NOT NULL, 
	related_claims JSON NOT NULL, 
	related_sources JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id)
);
INSERT INTO "concepts" ("id","topic_id","name","definition","examples","counterexamples","confused_with","related_claims","related_sources","created_at","updated_at") VALUES ('c-fixture-000001','topic-fixture-0001','黄金时刻','日出后/日落前光线柔和时段。','[]','[]','[]','[]','[]','2025-01-15 09:00:00.000000','2025-01-15 09:00:00.000000');
CREATE INDEX ix_concepts_topic_id ON concepts (topic_id);
CREATE TABLE domain_events (
	id VARCHAR(36) NOT NULL, 
	type VARCHAR(120) NOT NULL, 
	payload JSON NOT NULL, 
	schema_version INTEGER NOT NULL, 
	occurred_at DATETIME NOT NULL, 
	subscriber_errors JSON NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_domain_events_type ON domain_events (type);
CREATE TABLE domain_packs (
	id VARCHAR(80) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	version VARCHAR(32) NOT NULL, 
	description TEXT NOT NULL, 
	policy_json JSON NOT NULL, 
	default_capabilities JSON NOT NULL, 
	default_skills JSON NOT NULL, 
	default_personas JSON NOT NULL, 
	builtin BOOLEAN NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "domain_packs" ("id","name","version","description","policy_json","default_capabilities","default_skills","default_personas","builtin","updated_at") VALUES ('general','通用兴趣','1.0.0','','{}','{}','[]','[]',1,'2025-01-15 09:00:00.000000');
INSERT INTO "domain_packs" ("id","name","version","description","policy_json","default_capabilities","default_skills","default_personas","builtin","updated_at") VALUES ('psychology','心理学','1.0.0','','{}','{}','[]','[]',1,'2025-01-15 09:00:00.000000');
CREATE TABLE entity_area_bindings (
	id VARCHAR(36) NOT NULL, 
	entity_type VARCHAR(80) NOT NULL, 
	entity_id VARCHAR(80) NOT NULL, 
	area_id VARCHAR(36) NOT NULL, 
	sharing VARCHAR(24) NOT NULL, 
	is_primary BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_entity_area_binding UNIQUE (entity_type, entity_id, area_id), 
	FOREIGN KEY(area_id) REFERENCES interest_areas (id)
);
INSERT INTO "entity_area_bindings" ("id","entity_type","entity_id","area_id","sharing","is_primary","created_at") VALUES ('bind-question-0001','question','q-fixture-00000001','area-photography-0001','private',1,'2025-01-15 09:00:00.000000');
INSERT INTO "entity_area_bindings" ("id","entity_type","entity_id","area_id","sharing","is_primary","created_at") VALUES ('bind-topic-0001','topic','topic-fixture-0001','area-photography-0001','private',1,'2025-01-15 09:00:00.000000');
INSERT INTO "entity_area_bindings" ("id","entity_type","entity_id","area_id","sharing","is_primary","created_at") VALUES ('bind-source-0001','source','src-fixture-0001','area-photography-0001','private',1,'2025-01-15 09:00:00.000000');
INSERT INTO "entity_area_bindings" ("id","entity_type","entity_id","area_id","sharing","is_primary","created_at") VALUES ('bind-claim-0001','claim','claim-fixture-0001','area-photography-0001','private',1,'2025-01-15 09:00:00.000000');
INSERT INTO "entity_area_bindings" ("id","entity_type","entity_id","area_id","sharing","is_primary","created_at") VALUES ('bind-concept-0001','concept','c-fixture-000001','area-photography-0001','private',1,'2025-01-15 09:00:00.000000');
CREATE INDEX ix_entity_area_bindings_area_id ON entity_area_bindings (area_id);
CREATE INDEX ix_entity_area_bindings_entity_id ON entity_area_bindings (entity_id);
CREATE INDEX ix_entity_area_bindings_entity_type ON entity_area_bindings (entity_type);
CREATE INDEX ix_entity_area_bindings_sharing ON entity_area_bindings (sharing);
CREATE TABLE evidence (
	id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(36) NOT NULL, 
	evidence_type VARCHAR(60) NOT NULL, 
	excerpt_or_summary TEXT NOT NULL, 
	location VARCHAR(300) NOT NULL, 
	supports_claim BOOLEAN NOT NULL, 
	strength VARCHAR(32) NOT NULL, 
	limitations TEXT NOT NULL, 
	verification_state VARCHAR(32) NOT NULL, 
	verified BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id)
);
INSERT INTO "evidence" ("id","source_id","evidence_type","excerpt_or_summary","location","supports_claim","strength","limitations","verification_state","verified","created_at") VALUES ('ev-fixture-000001','src-fixture-0001','summary','黄金时刻光线柔和、色温更暖。','',1,'unknown','','unverified',0,'2025-01-15 09:00:00.000000');
CREATE INDEX ix_evidence_source_id ON evidence (source_id);
CREATE TABLE feature_flags (
	name VARCHAR(120) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (name)
);
INSERT INTO "feature_flags" ("name","enabled","updated_at") VALUES ('FEATURE_SMOKE',1,'2025-01-15 09:00:00.000000');
CREATE TABLE grounding_refs (
	id VARCHAR(36) NOT NULL, 
	area_id VARCHAR(36) NOT NULL, 
	owner_type VARCHAR(48) NOT NULL, 
	owner_id VARCHAR(80) NOT NULL, 
	ref_type VARCHAR(48) NOT NULL, 
	ref_id VARCHAR(80) NOT NULL, 
	role VARCHAR(40) NOT NULL, 
	metadata JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(area_id) REFERENCES interest_areas (id)
);
CREATE INDEX ix_grounding_refs_area_id ON grounding_refs (area_id);
CREATE INDEX ix_grounding_refs_owner_id ON grounding_refs (owner_id);
CREATE INDEX ix_grounding_refs_owner_type ON grounding_refs (owner_type);
CREATE INDEX ix_grounding_refs_ref_id ON grounding_refs (ref_id);
CREATE INDEX ix_grounding_refs_ref_type ON grounding_refs (ref_type);
CREATE TABLE growth_events (
	id VARCHAR(36) NOT NULL, 
	event_type VARCHAR(120) NOT NULL, 
	message TEXT NOT NULL, 
	payload JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "growth_events" ("id","event_type","message","payload","created_at") VALUES ('gr-fixture-000001','returned','回到摄影问题','{}','2025-01-15 09:00:00.000000');
CREATE INDEX ix_growth_events_event_type ON growth_events (event_type);
CREATE TABLE growth_memory (
	id VARCHAR(36) NOT NULL, 
	layer VARCHAR(20) NOT NULL, 
	memory_type VARCHAR(80) NOT NULL, 
	"key" VARCHAR(240) NOT NULL, 
	value_json JSON NOT NULL, 
	confidence FLOAT NOT NULL, 
	source_refs JSON NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_growth_memory_key ON growth_memory ("key");
CREATE INDEX ix_growth_memory_layer ON growth_memory (layer);
CREATE INDEX ix_growth_memory_memory_type ON growth_memory (memory_type);
CREATE TABLE interest_areas (
	id VARCHAR(36) NOT NULL, 
	slug VARCHAR(80) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	description TEXT NOT NULL, 
	domain_pack_id VARCHAR(80) NOT NULL, 
	mastery_profile_id VARCHAR(120) NOT NULL, 
	icon VARCHAR(80) NOT NULL, 
	accent VARCHAR(40) NOT NULL, 
	is_default BOOLEAN NOT NULL, 
	archived BOOLEAN NOT NULL, 
	position INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(domain_pack_id) REFERENCES domain_packs (id)
);
INSERT INTO "interest_areas" ("id","slug","name","description","domain_pack_id","mastery_profile_id","icon","accent","is_default","archived","position","created_at","updated_at") VALUES ('area-photography-0001','photography','摄影','','general','','sparkles','neutral',0,0,1,'2025-01-15 09:00:00.000000','2025-01-15 09:00:00.000000');
INSERT INTO "interest_areas" ("id","slug","name","description","domain_pack_id","mastery_profile_id","icon","accent","is_default","archived","position","created_at","updated_at") VALUES ('area-psychology-0001','psychology','心理学','默认兴趣领域。','psychology','psychology:conceptual-evidence','brain','indigo',1,0,0,'2025-01-15 09:00:00.000000','2025-01-15 09:00:00.000000');
CREATE INDEX ix_interest_areas_archived ON interest_areas (archived);
CREATE INDEX ix_interest_areas_domain_pack_id ON interest_areas (domain_pack_id);
CREATE INDEX ix_interest_areas_is_default ON interest_areas (is_default);
CREATE UNIQUE INDEX ix_interest_areas_slug ON interest_areas (slug);
CREATE TABLE knowledge_bases (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	description TEXT NOT NULL, 
	rag_provider VARCHAR(48) NOT NULL, 
	upstream_name VARCHAR(160) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	settings_json JSON NOT NULL, 
	last_synced_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_knowledge_bases_name ON knowledge_bases (name);
CREATE INDEX ix_knowledge_bases_status ON knowledge_bases (status);
CREATE UNIQUE INDEX ix_knowledge_bases_upstream_name ON knowledge_bases (upstream_name);
CREATE TABLE knowledge_ingestion_runs (
	id VARCHAR(36) NOT NULL, 
	knowledge_base_id VARCHAR(36) NOT NULL, 
	source_ids JSON NOT NULL, 
	provider VARCHAR(48) NOT NULL, 
	operation VARCHAR(32) NOT NULL, 
	upstream_task_id VARCHAR(160) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	task_identity_verified BOOLEAN NOT NULL, 
	progress_json JSON NOT NULL, 
	error TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id)
);
CREATE INDEX ix_knowledge_ingestion_runs_knowledge_base_id ON knowledge_ingestion_runs (knowledge_base_id);
CREATE INDEX ix_knowledge_ingestion_runs_state ON knowledge_ingestion_runs (state);
CREATE INDEX ix_knowledge_ingestion_runs_upstream_task_id ON knowledge_ingestion_runs (upstream_task_id);
CREATE TABLE knowledge_source_indexes (
	id VARCHAR(36) NOT NULL, 
	knowledge_base_id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(36) NOT NULL, 
	upstream_file_name TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	task_id VARCHAR(160) NOT NULL, 
	parse_preview TEXT NOT NULL, 
	provider VARCHAR(48) NOT NULL, 
	error TEXT NOT NULL, 
	indexed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_source_mapping UNIQUE (knowledge_base_id, source_id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id)
);
CREATE INDEX ix_knowledge_source_indexes_knowledge_base_id ON knowledge_source_indexes (knowledge_base_id);
CREATE INDEX ix_knowledge_source_indexes_source_id ON knowledge_source_indexes (source_id);
CREATE INDEX ix_knowledge_source_indexes_status ON knowledge_source_indexes (status);
CREATE TABLE learning_activities (
	id VARCHAR(36) NOT NULL, 
	area_id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	activity_type VARCHAR(48) NOT NULL, 
	objective TEXT NOT NULL, 
	artifact_refs JSON NOT NULL, 
	self_assessment TEXT NOT NULL, 
	feedback TEXT NOT NULL, 
	observation TEXT NOT NULL, 
	duration_minutes INTEGER, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(area_id) REFERENCES interest_areas (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id)
);
CREATE INDEX ix_learning_activities_activity_type ON learning_activities (activity_type);
CREATE INDEX ix_learning_activities_area_id ON learning_activities (area_id);
CREATE INDEX ix_learning_activities_status ON learning_activities (status);
CREATE INDEX ix_learning_activities_topic_id ON learning_activities (topic_id);
CREATE TABLE learning_notes (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	concept_id VARCHAR(36), 
	title VARCHAR(300) NOT NULL, 
	body_markdown TEXT NOT NULL, 
	note_type VARCHAR(40) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	upstream_notebook_id VARCHAR(160) NOT NULL, 
	upstream_record_id VARCHAR(160) NOT NULL, 
	sync_status VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id), 
	FOREIGN KEY(concept_id) REFERENCES concepts (id)
);
CREATE INDEX ix_learning_notes_concept_id ON learning_notes (concept_id);
CREATE INDEX ix_learning_notes_status ON learning_notes (status);
CREATE INDEX ix_learning_notes_topic_id ON learning_notes (topic_id);
CREATE TABLE living_book_chapters (
	id VARCHAR(36) NOT NULL, 
	book_id VARCHAR(36) NOT NULL, 
	order_index INTEGER NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	summary TEXT NOT NULL, 
	content_markdown TEXT NOT NULL, 
	source_refs JSON NOT NULL, 
	source_fingerprint VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	stale_reason TEXT NOT NULL, 
	upstream_page_id VARCHAR(160) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(book_id) REFERENCES living_books (id)
);
CREATE INDEX ix_living_book_chapters_book_id ON living_book_chapters (book_id);
CREATE INDEX ix_living_book_chapters_status ON living_book_chapters (status);
CREATE TABLE living_books (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36) NOT NULL, 
	title VARCHAR(300) NOT NULL, 
	intent TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	knowledge_base_ids JSON NOT NULL, 
	source_fingerprint VARCHAR(64) NOT NULL, 
	upstream_book_id VARCHAR(160) NOT NULL, 
	projection_status VARCHAR(32) NOT NULL, 
	proposal_json JSON NOT NULL, 
	spine_json JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id)
);
CREATE INDEX ix_living_books_status ON living_books (status);
CREATE INDEX ix_living_books_topic_id ON living_books (topic_id);
CREATE INDEX ix_living_books_upstream_book_id ON living_books (upstream_book_id);
CREATE TABLE mastery_evidence (
	id VARCHAR(36) NOT NULL, 
	concept_id VARCHAR(36) NOT NULL, 
	evidence_type VARCHAR(40) NOT NULL, 
	reference_id VARCHAR(80) NOT NULL, 
	note TEXT NOT NULL, 
	verified_by_user BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(concept_id) REFERENCES concepts (id)
);
CREATE INDEX ix_mastery_evidence_concept_id ON mastery_evidence (concept_id);
CREATE INDEX ix_mastery_evidence_reference_id ON mastery_evidence (reference_id);
CREATE TABLE mastery_profiles (
	id VARCHAR(120) NOT NULL, 
	domain_pack_id VARCHAR(80) NOT NULL, 
	name VARCHAR(160) NOT NULL, 
	description TEXT NOT NULL, 
	states JSON NOT NULL, 
	is_default BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(domain_pack_id) REFERENCES domain_packs (id)
);
INSERT INTO "mastery_profiles" ("id","domain_pack_id","name","description","states","is_default","created_at") VALUES ('psychology:conceptual-evidence','psychology','概念-证据','','["\u6709\u5370\u8c61", "\u80fd\u89e3\u91ca"]',1,'2025-01-15 09:00:00.000000');
CREATE INDEX ix_mastery_profiles_domain_pack_id ON mastery_profiles (domain_pack_id);
CREATE TABLE mastery_records (
	id VARCHAR(36) NOT NULL, 
	concept_id VARCHAR(36) NOT NULL, 
	state VARCHAR(40) NOT NULL, 
	evidence_note TEXT NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(concept_id) REFERENCES concepts (id)
);
CREATE INDEX ix_mastery_records_concept_id ON mastery_records (concept_id);
CREATE TABLE native_aux_memory (
            id TEXT PRIMARY KEY,
            area_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            layer TEXT NOT NULL,
            kind TEXT NOT NULL,
            content TEXT NOT NULL,
            source_run_id TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
CREATE INDEX idx_native_aux_memory_area_session ON native_aux_memory(area_id, session_id, created_at);
CREATE TABLE native_run_event (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES native_tutor_checkpoint(id) ON DELETE CASCADE,
            area_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
CREATE INDEX idx_native_event_run ON native_run_event(run_id, seq);
CREATE TABLE native_tutor_checkpoint (
            id TEXT PRIMARY KEY,
            area_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            state TEXT NOT NULL,
            version INTEGER NOT NULL DEFAULT 0,
            user_message TEXT NOT NULL,
            assistant_text TEXT NOT NULL DEFAULT '',
            selected_capability TEXT,
            wait_payload_json TEXT,
            execution_snapshot_json TEXT,
            parent_run_id TEXT,
            host_session_id TEXT,
            host_turn_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
CREATE INDEX idx_native_checkpoint_area_session ON native_tutor_checkpoint(area_id, session_id);
CREATE UNIQUE INDEX uq_native_active_turn_per_session
        ON native_tutor_checkpoint(area_id, session_id)
        WHERE state IN ('running', 'waiting_input');
CREATE TABLE persona_scopes (
	id VARCHAR(36) NOT NULL, 
	persona_id VARCHAR(36) NOT NULL, 
	scope_type VARCHAR(32) NOT NULL, 
	scope_id VARCHAR(120) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_persona_scope UNIQUE (persona_id, scope_type, scope_id), 
	FOREIGN KEY(persona_id) REFERENCES tutor_personas (id)
);
CREATE INDEX ix_persona_scopes_persona_id ON persona_scopes (persona_id);
CREATE INDEX ix_persona_scopes_scope_id ON persona_scopes (scope_id);
CREATE INDEX ix_persona_scopes_scope_type ON persona_scopes (scope_type);
CREATE TABLE plugin_states (
	plugin_id VARCHAR(160) NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	installed_version VARCHAR(32) NOT NULL, 
	lifecycle_state VARCHAR(32) NOT NULL, 
	previous_version VARCHAR(32), 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (plugin_id)
);
CREATE TABLE practice_attempts (
	id VARCHAR(36) NOT NULL, 
	practice_item_id VARCHAR(36) NOT NULL, 
	tutor_session_id VARCHAR(36), 
	answer TEXT NOT NULL, 
	is_correct BOOLEAN, 
	feedback TEXT NOT NULL, 
	evidence_promoted BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(practice_item_id) REFERENCES practice_items (id), 
	FOREIGN KEY(tutor_session_id) REFERENCES tutor_sessions (id)
);
CREATE INDEX ix_practice_attempts_practice_item_id ON practice_attempts (practice_item_id);
CREATE INDEX ix_practice_attempts_tutor_session_id ON practice_attempts (tutor_session_id);
CREATE TABLE practice_items (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	concept_id VARCHAR(36), 
	prompt TEXT NOT NULL, 
	question_type VARCHAR(40) NOT NULL, 
	options JSON NOT NULL, 
	reference_answer TEXT NOT NULL, 
	explanation TEXT NOT NULL, 
	difficulty VARCHAR(40) NOT NULL, 
	origin VARCHAR(40) NOT NULL, 
	upstream_session_id VARCHAR(160) NOT NULL, 
	upstream_turn_id VARCHAR(160) NOT NULL, 
	upstream_question_id VARCHAR(160) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id), 
	FOREIGN KEY(concept_id) REFERENCES concepts (id)
);
CREATE INDEX ix_practice_items_concept_id ON practice_items (concept_id);
CREATE INDEX ix_practice_items_topic_id ON practice_items (topic_id);
CREATE TABLE questions (
	id VARCHAR(36) NOT NULL, 
	question TEXT NOT NULL, 
	source_context TEXT NOT NULL, 
	interest_level INTEGER NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	energy_mode VARCHAR(16) NOT NULL, 
	active BOOLEAN NOT NULL, 
	returned_count INTEGER NOT NULL, 
	notes TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
INSERT INTO "questions" ("id","question","source_context","interest_level","state","energy_mode","active","returned_count","notes","created_at","updated_at") VALUES ('q-fixture-00000001','黄金时刻法则为何有效？','',3,'captured','normal',1,0,'','2025-01-15 09:00:00.000000','2025-01-15 09:00:00.000000');
CREATE INDEX ix_questions_state ON questions (state);
CREATE TABLE reflections (
	id VARCHAR(36) NOT NULL, 
	period_start VARCHAR(20) NOT NULL, 
	period_end VARCHAR(20) NOT NULL, 
	attracted_question TEXT NOT NULL, 
	interest_drain TEXT NOT NULL, 
	understanding_change TEXT NOT NULL, 
	continue_topic TEXT NOT NULL, 
	next_energy_mode VARCHAR(16) NOT NULL, 
	notes TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE retrieval_candidates (
	id VARCHAR(36) NOT NULL, 
	capability_run_id VARCHAR(36), 
	tutor_turn_id VARCHAR(36), 
	knowledge_base_id VARCHAR(36) NOT NULL, 
	source_id VARCHAR(36), 
	"query" TEXT NOT NULL, 
	upstream_file_name TEXT NOT NULL, 
	location VARCHAR(300) NOT NULL, 
	excerpt TEXT NOT NULL, 
	metadata JSON NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(capability_run_id) REFERENCES capability_runs (id), 
	FOREIGN KEY(tutor_turn_id) REFERENCES tutor_turns (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(source_id) REFERENCES sources (id)
);
CREATE INDEX ix_retrieval_candidates_capability_run_id ON retrieval_candidates (capability_run_id);
CREATE INDEX ix_retrieval_candidates_knowledge_base_id ON retrieval_candidates (knowledge_base_id);
CREATE INDEX ix_retrieval_candidates_source_id ON retrieval_candidates (source_id);
CREATE INDEX ix_retrieval_candidates_status ON retrieval_candidates (status);
CREATE INDEX ix_retrieval_candidates_tutor_turn_id ON retrieval_candidates (tutor_turn_id);
CREATE TABLE schema_migrations (
	version INTEGER NOT NULL, 
	applied_at DATETIME NOT NULL, 
	PRIMARY KEY (version)
);
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (1,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (2,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (3,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (4,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (5,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (6,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (7,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (8,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (9,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (10,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (11,'2025-01-15 09:00:00.000000');
INSERT INTO "schema_migrations" ("version","applied_at") VALUES (12,'2025-01-15 09:00:00.000000');
CREATE TABLE sources (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	source_type VARCHAR(40) NOT NULL, 
	title TEXT NOT NULL, 
	authors JSON NOT NULL, 
	year INTEGER, 
	publisher VARCHAR(300) NOT NULL, 
	doi VARCHAR(160) NOT NULL, 
	pmid VARCHAR(80) NOT NULL, 
	isbn VARCHAR(80) NOT NULL, 
	canonical_url TEXT NOT NULL, 
	local_file TEXT NOT NULL, 
	full_text_available BOOLEAN NOT NULL, 
	ai_summary_only BOOLEAN NOT NULL, 
	verified BOOLEAN NOT NULL, 
	verified_at DATETIME, 
	notes TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id)
);
INSERT INTO "sources" ("id","topic_id","source_type","title","authors","year","publisher","doi","pmid","isbn","canonical_url","local_file","full_text_available","ai_summary_only","verified","verified_at","notes","created_at") VALUES ('src-fixture-0001','topic-fixture-0001','document','日光摄影基础','[]',NULL,'','','','','','',0,0,0,NULL,'','2025-01-15 09:00:00.000000');
CREATE INDEX ix_sources_topic_id ON sources (topic_id);
CREATE TABLE topics (
	id VARCHAR(36) NOT NULL, 
	question_id VARCHAR(36), 
	title VARCHAR(300) NOT NULL, 
	description TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	interest_boundary VARCHAR(32) NOT NULL, 
	competence_boundary VARCHAR(48) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(question_id) REFERENCES questions (id)
);
INSERT INTO "topics" ("id","question_id","title","description","status","interest_boundary","competence_boundary","created_at","updated_at") VALUES ('topic-fixture-0001','q-fixture-00000001','黄金时刻法则','摄影光线研究','active','topic','learning_only','2025-01-15 09:00:00.000000','2025-01-15 09:00:00.000000');
CREATE INDEX ix_topics_question_id ON topics (question_id);
CREATE TABLE tutor_personas (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(80) NOT NULL, 
	description TEXT NOT NULL, 
	content TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	builtin BOOLEAN NOT NULL, 
	upstream_name VARCHAR(80) NOT NULL, 
	sync_status VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_tutor_personas_name ON tutor_personas (name);
CREATE TABLE tutor_sessions (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	concept_id VARCHAR(36), 
	title VARCHAR(300) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	upstream_session_id VARCHAR(160) NOT NULL, 
	knowledge_base_ids JSON NOT NULL, 
	skill_names JSON NOT NULL, 
	persona_name VARCHAR(80) NOT NULL, 
	created_at DATETIME NOT NULL, 
	last_active_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id), 
	FOREIGN KEY(concept_id) REFERENCES concepts (id)
);
INSERT INTO "tutor_sessions" ("id","topic_id","concept_id","title","status","upstream_session_id","knowledge_base_ids","skill_names","persona_name","created_at","last_active_at") VALUES ('ts-fixture-0001','topic-fixture-0001',NULL,'黄金时刻辅导','active','','[]','[]','','2025-01-15 09:00:00.000000','2025-01-15 09:00:00.000000');
CREATE INDEX ix_tutor_sessions_concept_id ON tutor_sessions (concept_id);
CREATE INDEX ix_tutor_sessions_status ON tutor_sessions (status);
CREATE INDEX ix_tutor_sessions_topic_id ON tutor_sessions (topic_id);
CREATE INDEX ix_tutor_sessions_upstream_session_id ON tutor_sessions (upstream_session_id);
CREATE TABLE tutor_turns (
	id VARCHAR(36) NOT NULL, 
	tutor_session_id VARCHAR(36) NOT NULL, 
	capability VARCHAR(80) NOT NULL, 
	upstream_turn_id VARCHAR(160) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	input_json JSON NOT NULL, 
	normalized_events JSON NOT NULL, 
	answer_text TEXT NOT NULL, 
	result_json JSON NOT NULL, 
	pending_input_json JSON NOT NULL, 
	last_seq INTEGER NOT NULL, 
	error TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tutor_session_id) REFERENCES tutor_sessions (id)
);
INSERT INTO "tutor_turns" ("id","tutor_session_id","capability","upstream_turn_id","status","input_json","normalized_events","answer_text","result_json","pending_input_json","last_seq","error","created_at","completed_at") VALUES ('tt-fixture-0001','ts-fixture-0001','chat','','completed','{}','[]','黄金时刻…','{}','{}',0,'','2025-01-15 09:00:00.000000',NULL);
CREATE INDEX ix_tutor_turns_capability ON tutor_turns (capability);
CREATE INDEX ix_tutor_turns_status ON tutor_turns (status);
CREATE INDEX ix_tutor_turns_tutor_session_id ON tutor_turns (tutor_session_id);
CREATE INDEX ix_tutor_turns_upstream_turn_id ON tutor_turns (upstream_turn_id);
CREATE TABLE writing_documents (
	id VARCHAR(36) NOT NULL, 
	topic_id VARCHAR(36), 
	title VARCHAR(300) NOT NULL, 
	content_markdown TEXT NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(topic_id) REFERENCES topics (id)
);
CREATE INDEX ix_writing_documents_status ON writing_documents (status);
CREATE INDEX ix_writing_documents_topic_id ON writing_documents (topic_id);
CREATE TABLE writing_revisions (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	instruction TEXT NOT NULL, 
	mode VARCHAR(32) NOT NULL, 
	tools JSON NOT NULL, 
	selected_text TEXT NOT NULL, 
	replacement_text TEXT NOT NULL, 
	selection_start INTEGER NOT NULL, 
	selection_end INTEGER NOT NULL, 
	base_sha256 VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	engine VARCHAR(48) NOT NULL, 
	upstream_operation_id VARCHAR(160) NOT NULL, 
	created_at DATETIME NOT NULL, 
	decided_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES writing_documents (id)
);
CREATE INDEX ix_writing_revisions_document_id ON writing_revisions (document_id);
CREATE INDEX ix_writing_revisions_status ON writing_revisions (status);
