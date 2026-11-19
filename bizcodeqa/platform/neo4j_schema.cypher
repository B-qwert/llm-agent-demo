CREATE CONSTRAINT code_entity_key IF NOT EXISTS FOR (n:CodeEntity) REQUIRE n.entity_key IS UNIQUE;
CREATE INDEX code_entity_snapshot IF NOT EXISTS FOR (n:CodeEntity) ON (n.snapshot_id);
CREATE INDEX code_entity_symbol IF NOT EXISTS FOR (n:CodeEntity) ON (n.symbol_id);
