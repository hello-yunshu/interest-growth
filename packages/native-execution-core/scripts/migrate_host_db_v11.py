#!/usr/bin/env python3
from __future__ import annotations
import argparse,shutil,sqlite3
from pathlib import Path

def split_sql(sql:str):
    statements=[];buf=""
    for line in sql.splitlines(True):
        if line.lstrip().upper().startswith("PRAGMA "):continue
        buf+=line
        if sqlite3.complete_statement(buf):
            stmt=buf.strip();buf=""
            if stmt:statements.append(stmt)
    if buf.strip():raise ValueError("incomplete SQL statement")
    return statements

def apply_atomic(conn:sqlite3.Connection,sql:str,*,fail_after:int|None=None):
    old=conn.isolation_level;conn.isolation_level=None
    try:
        conn.execute("PRAGMA foreign_keys=ON");conn.execute("BEGIN IMMEDIATE")
        for i,stmt in enumerate(split_sql(sql),1):
            conn.execute(stmt)
            if fail_after is not None and i>=fail_after:raise RuntimeError("injected migration failure")
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:conn.execute("ROLLBACK")
        raise
    finally:conn.isolation_level=old

def main():
    ap=argparse.ArgumentParser();ap.add_argument("db",type=Path);ap.add_argument("--no-backup",action="store_true");args=ap.parse_args();db=args.db.resolve()
    if not db.is_file():raise SystemExit(f"database not found: {db}")
    if not args.no_backup:
        backup=db.with_suffix(db.suffix+".pre-native-v11-rc2.bak")
        if backup.exists():raise SystemExit(f"backup already exists: {backup}")
        shutil.copy2(db,backup);print(f"backup: {backup}")
    sql=(Path(__file__).resolve().parents[1]/"migrations"/"0011_native_execution_state.sql").read_text("utf-8")
    conn=sqlite3.connect(db)
    try:apply_atomic(conn,sql)
    finally:conn.close()
    print("migration 11 native execution RC2: PASS")
if __name__=="__main__":main()
