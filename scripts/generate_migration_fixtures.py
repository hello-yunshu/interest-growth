#!/usr/bin/env python3
"""Frozen historical migration fixtures for Interest Growth (Gate R2 §9.1).

Purpose
-------
The migration path is purely additive: every schema version is built on the
legacy baseline (schema version 7, the v0.4.1 era) by applying later additive
migrations. Because none of migrations 8-15 ever alters a legacy table's columns
(except the additive ``singleton`` column that migration 14 adds to
``auth_owners``), we can faithfully reconstruct each historical schema from the
current ORM metadata by creating only the tables that existed at that version.

This generator produces frozen, human-reviewable SQL fixtures that the CI
``tests/integration/test_migration_fixtures.py`` restores and then migrates to
the current schema version, proving the §9.1 upgrade path (old DB -> current
migration -> schema + representative data + canonical ownership intact).

Version mapping
---------------
    7  -> v0.4.1  legacy baseline
    10 -> v0.5.0  + general interest schema (migration 8 seed/backfill)
    12 -> v0.6.0  + native execution state + native-only product (migrations 11/12)
    13 -> v0.7 pre-1.0 + single-owner / device-session auth (migration 13)

The generator is deterministic (fixed ids/timestamps) so re-running it produces
byte-identical fixtures.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api"))
sys.path.insert(0, str(ROOT / "packages/shared"))

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEEPSEEK_API_KEY", "")

from pg_api.db import (  # noqa: E402
    _migration_11_native_execution_state,
    Base,
    reset_engine_for_tests,
    SchemaMigration,
)
from pg_api.db import get_session_factory  # noqa: E402

FIXTURE_DIR = ROOT / "tests" / "fixtures" / "migrations"

# Tables added by each migration step. The rest of Base.metadata is legacy (v7).
M8_TABLES = {
    "domain_packs", "mastery_profiles", "interest_areas", "area_capability_settings",
    "entity_area_bindings", "learning_activities", "grounding_refs", "persona_scopes",
}
M11_TABLES = {"native_tutor_checkpoint", "native_run_event", "native_aux_memory"}
M13_TABLES = {
    "auth_owners", "auth_devices", "auth_access_tokens",
    "auth_refresh_tokens", "security_events",
}
M15_TABLES = {"server_metadata"}

# Historical v0.7 auth_owners had no ``singleton`` column (migration 14 adds it).
AUTH_OWNERS_V13_DDL = """
CREATE TABLE auth_owners (
    id VARCHAR(36) NOT NULL PRIMARY KEY,
    password_hash TEXT NOT NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
)
"""

# Representative, deterministic seed data (fixed ids + timestamps).
T0 = datetime(2025, 1, 15, 9, 0, 0, tzinfo=UTC)
AREA_ID, AREA_SLUG, AREA_NAME = "area-photography-0001", "photography", "摄影"
Q_ID, TOPIC_ID, SRC_ID = "q-fixture-00000001", "topic-fixture-0001", "src-fixture-0001"
EV_ID, CLAIM_ID, CONCEPT_ID = "ev-fixture-000001", "claim-fixture-0001", "c-fixture-000001"
ART_ID, GROWTH_ID = "art-fixture-0001", "gr-fixture-000001"
TS_ID, TT_ID = "ts-fixture-0001", "tt-fixture-0001"
OWNER_ID, DEVICE_ID = "owner-fixture-001", "dev-fixture-0001"


def _tables_for(version: int) -> set[str]:
    names = {
        t.name for t in Base.metadata.sorted_tables
        if t.name not in (M8_TABLES | M13_TABLES | M15_TABLES)
    }
    if version >= 8:
        names |= M8_TABLES
    if version >= 11:
        names |= {t for t in Base.metadata.sorted_tables if t.name in M11_TABLES}
    if version >= 13:
        names |= M13_TABLES
    return names


def _insert_representative_data(version: int) -> None:
    """Insert representative data into the tables that exist at ``version``."""
    from pg_api import db as dbmod

    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        # Question / Topic / Source / Evidence / Claim / Version / Concept
        db.add(dbmod.QuestionModel(id=Q_ID, question="黄金时刻法则为何有效？",
                                   interest_level=3, state="captured", energy_mode="normal",
                                   created_at=T0, updated_at=T0))
        db.add(dbmod.TopicModel(id=TOPIC_ID, question_id=Q_ID, title="黄金时刻法则",
                                description="摄影光线研究", status="active",
                                created_at=T0, updated_at=T0))
        db.add(dbmod.SourceModel(id=SRC_ID, topic_id=TOPIC_ID, source_type="document",
                                 title="日光摄影基础", verified=False, created_at=T0))
        db.add(dbmod.EvidenceModel(id=EV_ID, source_id=SRC_ID, evidence_type="summary",
                                   excerpt_or_summary="黄金时刻光线柔和、色温更暖。",
                                   verification_state="unverified", verified=False,
                                   created_at=T0))
        db.add(dbmod.ClaimModel(id=CLAIM_ID, topic_id=TOPIC_ID, status="draft",
                                confidence=0.5, created_at=T0, updated_at=T0))
        db.add(dbmod.ClaimVersionModel(id="cv-fixture-0001", claim_id=CLAIM_ID, version=1,
                                       statement="黄金时刻光线色彩更暖、对比更低。",
                                       created_at=T0))
        db.add(dbmod.ConceptModel(id=CONCEPT_ID, topic_id=TOPIC_ID, name="黄金时刻",
                                  definition="日出后/日落前光线柔和时段。",
                                  created_at=T0, updated_at=T0))
        # Growth / Content / runtime config / Tutor
        db.add(dbmod.GrowthEventModel(id=GROWTH_ID, event_type="returned",
                                      message="回到摄影问题", payload={}, created_at=T0))
        db.add(dbmod.ArtifactModel(id=ART_ID, topic_id=TOPIC_ID, kind="card",
                                   key="golden-hour-card", title="黄金时刻备忘卡",
                                   human_review_required=True, created_at=T0))
        db.add(dbmod.FeatureFlagModel(name="FEATURE_SMOKE", enabled=1, updated_at=T0))
        db.add(dbmod.TutorSessionModel(id=TS_ID, topic_id=TOPIC_ID, title="黄金时刻辅导",
                                       status="active", created_at=T0, last_active_at=T0))
        db.add(dbmod.TutorTurnModel(id=TT_ID, tutor_session_id=TS_ID, capability="chat",
                                    status="completed", answer_text="黄金时刻…",
                                    created_at=T0))

        if version >= 8:
            # Domain packs + default Psychology area (outcome of migration 9 seeding).
            db.add(dbmod.DomainPackModel(id="general", name="通用兴趣",
                                         version="1.0.0", description="",
                                         policy_json={}, default_capabilities={},
                                         default_skills=[], default_personas=[],
                                         builtin=True, updated_at=T0))
            db.add(dbmod.DomainPackModel(id="psychology", name="心理学",
                                         version="1.0.0", description="",
                                         policy_json={}, default_capabilities={},
                                         default_skills=[], default_personas=[],
                                         builtin=True, updated_at=T0))
            db.add(dbmod.MasteryProfileModel(
                id="psychology:conceptual-evidence", domain_pack_id="psychology",
                name="概念-证据", description="", states=["有印象", "能解释"],
                is_default=True, created_at=T0))
            db.add(dbmod.InterestAreaModel(id=AREA_ID, slug=AREA_SLUG, name=AREA_NAME,
                                           domain_pack_id="general", is_default=False,
                                           position=1, created_at=T0, updated_at=T0))
            db.add(dbmod.InterestAreaModel(id="area-psychology-0001", slug="psychology",
                                           name="心理学", description="默认兴趣领域。",
                                           domain_pack_id="psychology",
                                           mastery_profile_id="psychology:conceptual-evidence",
                                           icon="brain", accent="indigo", is_default=True,
                                           position=0, created_at=T0, updated_at=T0))
            for entity_type, entity_id in (
                ("question", Q_ID), ("topic", TOPIC_ID), ("source", SRC_ID),
                ("claim", CLAIM_ID), ("concept", CONCEPT_ID),
            ):
                db.add(dbmod.EntityAreaBindingModel(
                    id=f"bind-{entity_type}-0001",
                    entity_type=entity_type,
                    entity_id=entity_id, area_id=AREA_ID,
                    sharing="private", is_primary=True,
                    created_at=T0))
        db.commit()

    if version >= 13:
        # auth_owners at v13 has no singleton column -> insert via raw SQL.
        with get_session_factory()() as db:
            db.execute(dbmod.text(
                "INSERT INTO auth_owners (id, password_hash, created_at, updated_at) "
                "VALUES (:id, :ph, :ct, :ut)"
            ), {"id": OWNER_ID, "ph": "fixed-hash", "ct": T0.isoformat(), "ut": T0.isoformat()})
            db.add(dbmod.DeviceModel(id=DEVICE_ID, name="ci-phone", platform="android",
                                     app_version="0.7.0", created_at=T0, last_seen_at=T0))
            db.add(dbmod.DeviceAccessTokenModel(id="tat-00000001", device_id=DEVICE_ID,
                                                token_hash="acctok000000000000000000000000000000000000000000000000000000000000",
                                                created_at=T0, expires_at=datetime(2025, 2, 1, tzinfo=UTC)))
            db.add(dbmod.DeviceRefreshTokenModel(id="trt-00000001", device_id=DEVICE_ID,
                                                 token_hash="reftok000000000000000000000000000000000000000000000000000000000000",
                                                 created_at=T0, expires_at=datetime(2025, 3, 1, tzinfo=UTC)))
            db.commit()


def _record_ledger(version: int) -> None:
    with get_session_factory()() as db:
        db.info["skip_area_scope"] = True
        for v in range(1, version + 1):
            if db.get(SchemaMigration, v) is None:
                db.add(SchemaMigration(version=v, applied_at=T0))
        db.commit()


def build_fixture(version: int, dest: Path) -> None:
    """Build a single frozen fixture at ``version`` and write the SQL dump."""
    tmp = Path(os.environ.get("APP_DATABASE_URL", "").replace("sqlite:///", ""))
    if tmp.exists():
        tmp.unlink()
    reset_engine_for_tests()
    from pg_api.db import get_engine

    engine = get_engine()
    tables = _tables_for(version)
    for table in Base.metadata.sorted_tables:
        if table.name in tables and table.name not in M13_TABLES:
            table.create(engine, checkfirst=True)
    if version >= 11:
        _migration_11_native_execution_state(engine)
    if version >= 13:
        from sqlalchemy import text

        with engine.begin() as c:
            c.execute(text(AUTH_OWNERS_V13_DDL))
            for table in Base.metadata.sorted_tables:
                if table.name in M13_TABLES and table.name != "auth_owners":
                    table.create(engine, checkfirst=True)
    _insert_representative_data(version)
    _record_ledger(version)
    reset_engine_for_tests()

    conn = sqlite3.connect(tmp)
    try:
        dump = "\n".join(_stable_dump(conn)) + "\n"
    finally:
        conn.close()
    dest.write_text(dump, encoding="utf-8")
    print(f"fixture v{version}: {dest.relative_to(ROOT)} ({len(dump)} bytes)")


def _sql_literal(value: object) -> str:
    """Render a Python/sqlite value as a lossless SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, bytes):
        return f"X'{value.hex()}'"
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _stable_dump(conn: sqlite3.Connection) -> list[str]:
    """Deterministic SQL dump.

    sqlite3's ``iterdump`` walks ``sqlite_master`` in physical row order, which
    is not guaranteed stable across identical rebuilds. We therefore emit every
    table (schema + rows, rows in primary-key order) sorted by table name and
    every index sorted by index name, giving byte-identical output for the same
    fixture definition.
    """
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    lines: list[str] = []
    for table in names:
        cols = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
        rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        ddl = next(r[3] for r in conn.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            f"WHERE type='table' AND name='{table}'"))
        lines.append(ddl.rstrip() + ";")
        if rows:
            quoted = ",".join(f'"{c}"' for c in cols)
            for row in rows:
                values = ",".join(_sql_literal(v) for v in row)
                lines.append(f'INSERT INTO "{table}" ({quoted}) VALUES ({values});')
        for idx in conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? "
            "AND sql IS NOT NULL ORDER BY name", (table,)
        ):
            lines.append(idx[0].rstrip() + ";")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", default="7,10,12,13",
                        help="comma-separated schema versions to build")
    args = parser.parse_args(argv)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    labels = {7: "v0_4_1", 10: "v0_5_0", 12: "v0_6_0", 13: "v0_7"}
    for v in [int(x) for x in args.versions.split(",") if x.strip()]:
        tmp = FIXTURE_DIR / f"schema_v{v}_{labels.get(v, 'legacy')}.db.tmp"
        os.environ["APP_DATABASE_URL"] = f"sqlite:///{tmp}"
        build_fixture(v, FIXTURE_DIR / f"schema_v{v}_{labels.get(v, 'legacy')}.sql")
        tmp.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())