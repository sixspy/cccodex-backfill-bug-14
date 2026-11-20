from datetime import date, timedelta

from app.db import get_db
from app.services.errors import ServiceError


def list_windows(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT w.*, "
            "(SELECT COUNT(*) FROM backfill_slices s WHERE s.window_id=w.id) AS slice_count, "
            "(SELECT COUNT(*) FROM backfill_slices s WHERE s.window_id=w.id AND s.status='已落库') AS loaded_count "
            "FROM backfill_windows w ORDER BY w.id"
        ).fetchall()
        return [dict(r) for r in rows]


def _daterange(start: str, end: str) -> list[str]:
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    if e < s:
        raise ServiceError("结束日不能早于开始日")
    out = []
    cur = s
    while cur <= e:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def plan_slices(window_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        win = conn.execute(
            "SELECT * FROM backfill_windows WHERE id=?", (window_id,)
        ).fetchone()
        if not win:
            raise ServiceError("回灌窗口不存在", 404)
        if win["status"] not in ("草稿", "已计划"):
            raise ServiceError("当前状态不可再生成切片", 409)
        days = _daterange(win["start_date"], win["end_date"])
        conn.execute("DELETE FROM backfill_slices WHERE window_id=?", (window_id,))
        for d in days:
            conn.execute(
                "INSERT INTO backfill_slices(window_id, slice_date, status, row_count) "
                "VALUES (?,?, '待重放', 0)",
                (window_id, d),
            )
        conn.execute(
            "UPDATE backfill_windows SET status='已计划' WHERE id=?",
            (window_id,),
        )
        slices = conn.execute(
            "SELECT * FROM backfill_slices WHERE window_id=? ORDER BY slice_date",
            (window_id,),
        ).fetchall()
        return {"window_id": window_id, "slices": [dict(s) for s in slices]}


def list_slices(window_id: int, db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM backfill_slices WHERE window_id=? ORDER BY slice_date",
            (window_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def replay_slice(slice_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        sl = conn.execute(
            "SELECT * FROM backfill_slices WHERE id=?", (slice_id,)
        ).fetchone()
        if not sl:
            raise ServiceError("切片不存在", 404)
        if sl["status"] == "已落库":
            raise ServiceError("切片已落库", 409)
        if sl["status"] != "待重放":
            raise ServiceError("仅待重放切片可重放", 409)
        # deterministic fake row count from date digits
        rows = 100 + int(sl["slice_date"].replace("-", "")) % 97
        conn.execute(
            "UPDATE backfill_slices SET status='已落库', row_count=? WHERE id=?",
            (rows, slice_id),
        )
        conn.execute(
            "UPDATE backfill_windows SET status='执行中' WHERE id=?",
            (sl["window_id"],),
        )
        pending = conn.execute(
            "SELECT COUNT(*) AS c FROM backfill_slices WHERE window_id=? AND status!='已落库'",
            (sl["window_id"],),
        ).fetchone()["c"]
        if pending == 0:
            conn.execute(
                "UPDATE backfill_windows SET status='已完成' WHERE id=?",
                (sl["window_id"],),
            )
        row = conn.execute(
            "SELECT * FROM backfill_slices WHERE id=?", (slice_id,)
        ).fetchone()
        return dict(row)


def coverage_report(window_id: int, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        win = conn.execute(
            "SELECT * FROM backfill_windows WHERE id=?", (window_id,)
        ).fetchone()
        if not win:
            raise ServiceError("回灌窗口不存在", 404)
        planned = conn.execute(
            "SELECT COUNT(*) AS c FROM backfill_slices WHERE window_id=?",
            (window_id,),
        ).fetchone()["c"]
        loaded = conn.execute(
            "SELECT COUNT(*) AS c FROM backfill_slices WHERE window_id=? AND status='已落库'",
            (window_id,),
        ).fetchone()["c"]
        missing = planned - loaded
        summary = (
            f"窗口#{window_id} {win['table_name']}：计划{planned}片，已落库{loaded}，缺口{missing}"
        )
        cur = conn.execute(
            "INSERT INTO coverage_reports(window_id, planned, loaded, missing, summary) "
            "VALUES (?,?,?,?,?)",
            (window_id, planned, loaded, missing, summary),
        )
        row = conn.execute(
            "SELECT * FROM coverage_reports WHERE id=?", (cur.lastrowid,)
        ).fetchone()
        return dict(row)


def list_coverage(db_path: str | None = None) -> list[dict]:
    with get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM coverage_reports ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
