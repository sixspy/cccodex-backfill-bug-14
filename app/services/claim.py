import sqlite3

from app.db import get_db

# 占片写入路线（二者择一，本轮选“写入时硬拦”）：
#   靠 claim_rows / slice_locks 的唯一片键在写入那一刻挡住后到者：
#   后到行整笔不落库，只回一句短话；不使用“先照写、提交瞬间再整笔撤回”的路线。
#   选边结论：后到行不能继续占该片，但对其它未占片键仍可正常占片。
#   （若改用提交末尾回滚路线，后到行会先短暂落库再被撤回，语义不同。）

REJECT_CHIP_KEY = "reject_chip"


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def _mark_rejected(conn: sqlite3.Connection) -> None:
    # 拒重芯片一旦点亮就保持，后续读详情/水线不回灭。
    _set_meta(conn, REJECT_CHIP_KEY, "亮")


def _double_locked_keys(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT slice_key FROM slice_locks GROUP BY slice_key HAVING COUNT(*) > 1"
    ).fetchall()
    return [r["slice_key"] for r in rows]


def _reject(slice_key: str, actor: str, message: str, holder: str = "") -> dict:
    return {
        "ok": False,
        "rejected": True,
        "chip": "拒重",
        "lit": True,
        "slice_key": slice_key,
        "actor": actor,
        "holder": holder,
        "msg": message,
        "error": message,
    }


def claim(slice_key: str, actor: str, db_path: str | None = None) -> dict:
    """先手独占片键；后到被唯一片键挡住，整笔不落库，只回短句。"""
    slice_key = (slice_key or "").strip()
    actor = (actor or "").strip()
    if not slice_key:
        return _reject(slice_key, actor, "缺片键")

    with get_db(db_path) as conn:
        # 先手与后到串行化：后到者等先手提交后，再由唯一片键判负。
        conn.execute("BEGIN IMMEDIATE")

        double = _double_locked_keys(conn)
        if double:
            # 双锁即停：指针与可写态同源失效，不再覆盖占片指针。
            _mark_rejected(conn)
            _set_meta(conn, "writable", "0")
            return _reject(slice_key, actor, f"片 {double[0]} 双锁，已停写")

        held = conn.execute(
            "SELECT * FROM slice_locks WHERE slice_key=? ORDER BY id", (slice_key,)
        ).fetchone()
        if held:
            _mark_rejected(conn)
            return _reject(
                slice_key, actor,
                f"片 {slice_key} 已被 {held['holder']} 独占",
                holder=held["holder"],
            )

        try:
            conn.execute(
                "INSERT INTO slice_locks(slice_key, holder) VALUES (?,?)",
                (slice_key, actor),
            )
            conn.execute(
                "INSERT INTO claim_rows(slice_key, actor) VALUES (?,?)",
                (slice_key, actor),
            )
        except sqlite3.IntegrityError:
            # 并发下另一笔先提交：本笔整笔撤回，后到行不落库。
            conn.rollback()
            _mark_rejected(conn)
            holder_row = conn.execute(
                "SELECT holder FROM slice_locks WHERE slice_key=?", (slice_key,)
            ).fetchone()
            holder = holder_row["holder"] if holder_row else ""
            return _reject(
                slice_key, actor, f"片 {slice_key} 已被先手独占", holder=holder
            )

        # 指针与可写态和片锁同源：都由刚写入的这条锁行派生。
        _set_meta(conn, "lock_ui", "占用")
        _set_meta(conn, "lock_ptr", slice_key)
        _set_meta(conn, "writable", "0")
        return {
            "ok": True,
            "rejected": False,
            "slice_key": slice_key,
            "actor": actor,
            "holder": actor,
            "chip": "先手",
            "ui": "占用",
            "ptr": slice_key,
            "writable": "0",
            "msg": f"片 {slice_key} 已由 {actor} 独占",
        }


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["slice_key"], []).append(row)
    return grouped


def panels(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        locks = [dict(r) for r in conn.execute(
            "SELECT * FROM slice_locks ORDER BY id"
        ).fetchall()]
        claims = [dict(r) for r in conn.execute(
            "SELECT * FROM claim_rows ORDER BY id"
        ).fetchall()]
        reject = conn.execute(
            "SELECT value FROM meta WHERE key=?", (REJECT_CHIP_KEY,)
        ).fetchone()
        lit = bool(reject and reject["value"] == "亮")

        # 片锁指针与可写态同源于 slice_locks：每片只认一条先手锁行。
        lock_groups = _group(locks)
        claim_groups = _group(claims)
        double = any(len(rows) > 1 for rows in lock_groups.values())
        primary = locks[0] if locks and not double else None
        locked = primary is not None
        ptr = primary["slice_key"] if primary else ""
        holder = primary["holder"] if primary else ""
        writable = "1" if not locked and not double else "0"

        queue = [
            {
                "id": row["id"],
                "slice_key": row["slice_key"],
                "actor": row["actor"],
                # 争抢芯片：发生拒重后，队列与卡片同亮。
                "chip": "争抢" if lit else "先手",
                "lit": lit,
            }
            for row in claims
        ]
        return {
            "queue": queue,
            "detail": {
                "ui": "占用" if locked else "灰",
                "ptr": ptr,
                "writable": writable,
                "locked": locked,
                "slice_key": ptr,
                "holder": holder,
                "double": double,
            },
            "card": {
                "chip": "拒重",
                "lit": lit,
                "state": "亮" if lit else "灭",
                "signal": "争抢" if lit else "独占",
                "fate": (
                    "同片再抢被挡，后到整笔未落库"
                    if lit else "单片独占，后到将拒重"
                ),
            },
            "water": {
                "dup": double or any(len(rows) > 1 for rows in claim_groups.values()),
                "count": len(claims),
                "locks": locks,
            },
        }
