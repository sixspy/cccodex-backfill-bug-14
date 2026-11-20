import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import Config


def connect(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or Config.database()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # 同片并发占片时，后到者等先手提交后再由唯一片键判负，而不是报 database is locked。
    conn.execute("PRAGMA busy_timeout = 8000")
    return conn


@contextmanager
def get_db(db_path: str | None = None):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS backfill_windows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  table_name TEXT NOT NULL,
  start_date TEXT NOT NULL,
  end_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('草稿','已计划','执行中','已完成')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS backfill_slices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  window_id INTEGER NOT NULL REFERENCES backfill_windows(id),
  slice_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('待重放','已落库','失败')),
  row_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE(window_id, slice_date)
);

CREATE TABLE IF NOT EXISTS coverage_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  window_id INTEGER NOT NULL,
  planned INTEGER NOT NULL,
  loaded INTEGER NOT NULL,
  missing INTEGER NOT NULL,
  summary TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- 占片锁：一个片键只允许一条锁行，先手写入即独占落点。
CREATE TABLE IF NOT EXISTS slice_locks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slice_key TEXT NOT NULL,
  holder TEXT NOT NULL,
  UNIQUE(slice_key)
);

-- 争抢队列：同样按片键唯一，水线条数只认先手一行。
CREATE TABLE IF NOT EXISTS claim_rows (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slice_key TEXT NOT NULL,
  actor TEXT NOT NULL,
  UNIQUE(slice_key)
);

"""


def _enforce_single_claim(conn: sqlite3.Connection) -> None:
    """给老库补唯一片键索引；历史双份只保留先手（最小 id）一行。"""
    for table in ("slice_locks", "claim_rows"):
        conn.execute(
            f"DELETE FROM {table} WHERE id NOT IN "
            f"(SELECT MIN(id) FROM {table} GROUP BY slice_key)"
        )
        conn.execute(
            f"CREATE UNIQUE INDEX IF NOT EXISTS ux_{table}_slice_key "
            f"ON {table}(slice_key)"
        )


def init_db(db_path: str | None = None) -> None:
    with get_db(db_path) as conn:
        conn.executescript(SCHEMA)
        _enforce_single_claim(conn)
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('lock_ui','灰')")
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('lock_ptr','')")
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('writable','1')")
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('reject_chip','灭')")
        if conn.execute("SELECT value FROM meta WHERE key='seeded'").fetchone():
            return
        cur = conn.execute(
            "INSERT INTO backfill_windows(table_name, start_date, end_date, status) "
            "VALUES ('dw_orders_d','2026-11-10','2026-11-12','草稿')"
        )
        wid = cur.lastrowid
        conn.execute(
            "INSERT INTO backfill_windows(table_name, start_date, end_date, status) "
            "VALUES ('dw_payments_d','2026-11-11','2026-11-11','草稿')"
        )
        # placeholder so list is non-empty; slices created by plan
        _ = wid
        conn.execute("INSERT INTO meta(key, value) VALUES ('seeded','1')")
