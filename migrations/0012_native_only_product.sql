DELETE FROM plugin_states WHERE plugin_id = 'integration.deeptutor';
DELETE FROM feature_flags WHERE name LIKE 'FEATURE_DEEPTUTOR_%';

UPDATE knowledge_bases
SET rag_provider = 'native-lexical', status = 'local_only', last_synced_at = NULL
WHERE rag_provider NOT IN ('native-lexical', 'native-lightgraph', 'native-concept-graph', 'native-heading');

UPDATE knowledge_source_indexes
SET provider = 'native-lexical', status = 'linked', task_id = '',
    error = 'Migrated to native-only execution; rebuild required.'
WHERE provider NOT IN ('native-lexical', 'native-lightgraph', 'native-concept-graph', 'native-heading');
