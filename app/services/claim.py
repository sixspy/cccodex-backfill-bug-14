from app.db import get_db


def claim(slice_key: str, actor: str, db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        # silent: UI gray only; always insert claim row + lock row (allows duplicates)
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('lock_ui','灰')")
        conn.execute(
            "INSERT INTO slice_locks(slice_key, holder) VALUES (?,?)",
            (slice_key, actor),
        )
        conn.execute(
            "INSERT INTO claim_rows(slice_key, actor) VALUES (?,?)",
            (slice_key, actor),
        )
        return {"ok": True, "chip": "先手未独占", "ui": "灰", "actor": actor}


def panels(db_path: str | None = None) -> dict:
    with get_db(db_path) as conn:
        locks = [dict(r) for r in conn.execute("SELECT * FROM slice_locks ORDER BY id").fetchall()]
        claims = [dict(r) for r in conn.execute("SELECT * FROM claim_rows ORDER BY id").fetchall()]
        ui = conn.execute("SELECT value FROM meta WHERE key='lock_ui'").fetchone()
        ptr = conn.execute("SELECT value FROM meta WHERE key='lock_ptr'").fetchone()
        wr = conn.execute("SELECT value FROM meta WHERE key='writable'").fetchone()
        return {
            "queue": claims,
            "detail": {"ui": ui["value"] if ui else "", "ptr": ptr["value"] if ptr else "", "writable": wr["value"] if wr else ""},
            "card": {"chip": "拒重未生效", "fate": "灰态占片"},
            "water": {"dup": len(claims) > 1, "count": len(claims), "locks": locks},
        }
