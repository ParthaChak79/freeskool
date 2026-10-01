"""SQLite cache keyed by video_id, 30-day TTL (instructions.md's Token
Optimization Strategy #4: "Cache transcripts and Scores... repeat queries for
the same video cost $0"). Also caches full learning-path results by
(topic, level), since those are expensive multi-call queries too.

transcript_text and llm_score_json share one cached_at per video_id row
rather than separate per-field timestamps — a deliberate simplification,
since in practice both get written together in the same scoring pass.
"""
import json
import sqlite3
import time
from pathlib import Path

import config

DB_PATH = Path(__file__).parent / "cache.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS video_cache (
            video_id TEXT PRIMARY KEY,
            transcript_text TEXT,
            llm_score_json TEXT,
            video_details_json TEXT,
            cached_at REAL NOT NULL
        )
    """)
    # Migration for DBs created before video_details_json existed.
    cols = {row[1] for row in conn.execute("PRAGMA table_info(video_cache)").fetchall()}
    if "video_details_json" not in cols:
        conn.execute("ALTER TABLE video_cache ADD COLUMN video_details_json TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS path_cache (
            cache_key TEXT PRIMARY KEY,
            result_json TEXT NOT NULL,
            cached_at REAL NOT NULL
        )
    """)
    return conn


def _is_fresh(cached_at: float) -> bool:
    return (time.time() - cached_at) < config.CACHE_TTL_DAYS * 86400


def get_cached_transcript(video_id: str) -> str | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT transcript_text, cached_at FROM video_cache WHERE video_id = ?", (video_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] is None or not _is_fresh(row[1]):
        return None
    return row[0]


def set_cached_transcript(video_id: str, transcript_text: str) -> None:
    conn = _connect()
    try:
        conn.execute("""
            INSERT INTO video_cache (video_id, transcript_text, cached_at) VALUES (?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET transcript_text = excluded.transcript_text, cached_at = excluded.cached_at
        """, (video_id, transcript_text, time.time()))
        conn.commit()
    finally:
        conn.close()


def get_cached_score(video_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT llm_score_json, cached_at FROM video_cache WHERE video_id = ?", (video_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] is None or not _is_fresh(row[1]):
        return None
    return json.loads(row[0])


def set_cached_score(video_id: str, score: dict) -> None:
    conn = _connect()
    try:
        conn.execute("""
            INSERT INTO video_cache (video_id, llm_score_json, cached_at) VALUES (?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET llm_score_json = excluded.llm_score_json, cached_at = excluded.cached_at
        """, (video_id, json.dumps(score), time.time()))
        conn.commit()
    finally:
        conn.close()


def get_cached_video_details(video_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT video_details_json, cached_at FROM video_cache WHERE video_id = ?", (video_id,)
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] is None or not _is_fresh(row[1]):
        return None
    return json.loads(row[0])


def set_cached_video_details(video_id: str, details: dict) -> None:
    conn = _connect()
    try:
        conn.execute("""
            INSERT INTO video_cache (video_id, video_details_json, cached_at) VALUES (?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET video_details_json = excluded.video_details_json, cached_at = excluded.cached_at
        """, (video_id, json.dumps(details), time.time()))
        conn.commit()
    finally:
        conn.close()


def path_cache_key(topic: str, level: str, mode: str = "learning_path") -> str:
    # mode included since skill_mix and learning_path produce genuinely
    # different results for the same topic (different decomposition,
    # videos-only vs. not) - without this they'd collide in the cache.
    return f"{mode}::{topic.strip().lower()}::{level}"


def get_cached_path(cache_key: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT result_json, cached_at FROM path_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
    finally:
        conn.close()
    if not row or not _is_fresh(row[1]):
        return None
    return json.loads(row[0])


def set_cached_path(cache_key: str, result: dict) -> None:
    conn = _connect()
    try:
        conn.execute("""
            INSERT INTO path_cache (cache_key, result_json, cached_at) VALUES (?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET result_json = excluded.result_json, cached_at = excluded.cached_at
        """, (cache_key, json.dumps(result), time.time()))
        conn.commit()
    finally:
        conn.close()
