"""One-shot: copy operators + inspections from the old SQLite qc.db into
PostgreSQL. Safe to re-run (skips rows that already exist).

Usage:
    # start just the database first
    docker compose up -d db

    # then, from this folder, with the app venv active (needs `psycopg`):
    set DATABASE_URL=postgresql://spring_qc:<password>@localhost:5432/spring_qc
    python migrate_from_sqlite.py qc.db
"""
import os
import sys
import sqlite3

import psycopg

SQLITE_PATH = sys.argv[1] if len(sys.argv) > 1 else 'qc.db'
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://spring_qc:spring_qc@localhost:5432/spring_qc',
)

if not os.path.exists(SQLITE_PATH):
    sys.exit(f'SQLite file not found: {SQLITE_PATH}')

src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row
dst = psycopg.connect(DATABASE_URL, autocommit=True)

# Make sure the target tables exist (same DDL the app uses on startup).
dst.execute('''CREATE TABLE IF NOT EXISTS operators (
    id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, machine_no TEXT,
    pin_salt TEXT, pin_hash TEXT, roi_points TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')
dst.execute('''CREATE TABLE IF NOT EXISTS inspections (
    id SERIAL PRIMARY KEY, job_id TEXT NOT NULL, source_type TEXT, source_label TEXT,
    operator TEXT, s_no INTEGER NOT NULL, in_time_sec DOUBLE PRECISION,
    out_time_sec DOUBLE PRECISION, duration_sec DOUBLE PRECISION, defect TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL, image_count INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ)''')
dst.execute('ALTER TABLE inspections ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ')

ops = src.execute(
    'SELECT name, machine_no, pin_salt, pin_hash, roi_points, created_at FROM operators'
).fetchall()
for o in ops:
    dst.execute(
        '''INSERT INTO operators (name, machine_no, pin_salt, pin_hash, roi_points, created_at)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (name) DO NOTHING''',
        (o['name'], o['machine_no'], o['pin_salt'], o['pin_hash'],
         o['roi_points'], o['created_at']),
    )
print(f'operators copied: {len(ops)}')

rows = src.execute('SELECT * FROM inspections ORDER BY id').fetchall()
copied = 0
for r in rows:
    exists = dst.execute(
        'SELECT 1 FROM inspections WHERE job_id = %s AND s_no = %s AND decided_at = %s',
        (r['job_id'], r['s_no'], r['decided_at']),
    ).fetchone()
    if exists:
        continue
    dst.execute(
        '''INSERT INTO inspections
           (job_id, source_type, source_label, operator, s_no, in_time_sec,
            out_time_sec, duration_sec, defect, decided_at, image_count)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        (r['job_id'], r['source_type'], r['source_label'], r['operator'], r['s_no'],
         r['in_time_sec'], r['out_time_sec'], r['duration_sec'], r['defect'],
         r['decided_at'], r['image_count']),
    )
    copied += 1
print(f'inspections copied: {copied} (of {len(rows)})')
print('done')
