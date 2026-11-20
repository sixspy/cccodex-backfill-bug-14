import json
from pathlib import Path

import falcon.asgi
from itsdangerous import BadSignature, URLSafeSerializer

from app.config import Config
from app.db import init_db
from app.services.errors import ServiceError
from app.services.windows import (
    coverage_report,
    list_coverage,
    list_slices,
    list_windows,
    plan_slices,
    replay_slice,
)
from app.services import claim as claim_svc

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
serializer = URLSafeSerializer(Config.SECRET, salt="cc-backfill-session")


def _json(resp, data, status=200):
    resp.status = str(status)
    resp.content_type = "application/json"
    resp.text = json.dumps(data, ensure_ascii=False)


def _read_session(req) -> dict:
    raw = req.get_cookie_values("backfill_session")
    if not raw:
        return {}
    try:
        data = serializer.loads(raw[0])
        return data if isinstance(data, dict) else {}
    except BadSignature:
        return {}


def require_user(req):
    user = _read_session(req).get("user")
    if user != Config.ADMIN_USER:
        raise ServiceError("未登录", 401)
    return user


class StaticFile:
    def __init__(self, path: Path, content_type: str):
        self.path = path
        self.content_type = content_type

    async def on_get(self, req, resp):
        resp.content_type = self.content_type
        resp.data = self.path.read_bytes()


class LoginPage(StaticFile):
    pass


class SpaPage:
    async def on_get(self, req, resp):
        if _read_session(req).get("user") != Config.ADMIN_USER:
            raise falcon.HTTPFound("/login")
        resp.content_type = "text/html; charset=utf-8"
        resp.data = (STATIC / "index.html").read_bytes()


class Root:
    async def on_get(self, req, resp):
        if _read_session(req).get("user") == Config.ADMIN_USER:
            raise falcon.HTTPFound("/app/")
        raise falcon.HTTPFound("/login")


class ApiLogin:
    async def on_post(self, req, resp):
        body = await req.get_media() or {}
        user = str(body.get("username", "")).strip()
        pwd = str(body.get("password", ""))
        if user != Config.ADMIN_USER or pwd != Config.ADMIN_PASSWORD:
            _json(resp, {"ok": False, "error": "账号或密码错误"}, 400)
            return
        _json(resp, {"ok": True, "user": user})
        resp.set_cookie(
            "backfill_session",
            serializer.dumps({"user": user}),
            path="/",
            http_only=True,
            secure=False,
        )


class ApiLogout:
    async def on_post(self, req, resp):
        _json(resp, {"ok": True})
        resp.unset_cookie("backfill_session", path="/")


class ApiMeta:
    async def on_get(self, req, resp):
        try:
            require_user(req)
            _json(resp, {"lab": Config.LAB_NAME, "product": "cc-backfill-lab"})
        except ServiceError as exc:
            _json(resp, {"error": exc.message}, exc.status_code)


class ApiWindows:
    async def on_get(self, req, resp):
        try:
            require_user(req)
            _json(resp, {"items": list_windows()})
        except ServiceError as exc:
            _json(resp, {"error": exc.message}, exc.status_code)


class ApiPlan:
    async def on_post(self, req, resp, window_id):
        try:
            require_user(req)
            _json(resp, plan_slices(int(window_id)))
        except ServiceError as exc:
            _json(resp, {"error": exc.message}, exc.status_code)


class ApiSlices:
    async def on_get(self, req, resp, window_id):
        try:
            require_user(req)
            _json(resp, {"items": list_slices(int(window_id))})
        except ServiceError as exc:
            _json(resp, {"error": exc.message}, exc.status_code)


class ApiReplay:
    async def on_post(self, req, resp, slice_id):
        try:
            require_user(req)
            _json(resp, {"slice": replay_slice(int(slice_id))})
        except ServiceError as exc:
            _json(resp, {"error": exc.message}, exc.status_code)


class ApiCoverage:
    async def on_get(self, req, resp):
        try:
            require_user(req)
            _json(resp, {"items": list_coverage()})
        except ServiceError as exc:
            _json(resp, {"error": exc.message}, exc.status_code)

    async def on_post(self, req, resp):
        try:
            require_user(req)
            body = await req.get_media() or {}
            wid = int(body.get("window_id"))
            _json(resp, {"report": coverage_report(wid)})
        except ServiceError as exc:
            _json(resp, {"error": exc.message}, exc.status_code)
        except (TypeError, ValueError):
            _json(resp, {"error": "window_id 无效"}, 400)



class ApiClaim:
    async def on_post(self, req, resp):
        try:
            require_user(req)
            body = await req.get_media() or {}
            result = claim_svc.claim(
                str(body.get("slice_key") or "S9"),
                str(body.get("actor") or "A"),
            )
            if result.get("rejected"):
                # 后到被拒：服务立刻收拢，409 + 短句。
                _json(resp, result, 409)
                return
            _json(resp, result)
        except ServiceError as exc:
            _json(resp, {"error": exc.message, **exc.payload}, exc.status_code)


class ApiClaimPanels:
    async def on_get(self, req, resp):
        try:
            require_user(req)
            _json(resp, claim_svc.panels())
        except ServiceError as exc:
            _json(resp, {"error": exc.message}, exc.status_code)


def create_app() -> falcon.asgi.App:
    init_db()
    app = falcon.asgi.App()
    app.add_route("/", Root())
    app.add_route("/login", LoginPage(STATIC / "login.html", "text/html; charset=utf-8"))
    app.add_route("/app/", SpaPage())
    app.add_route("/api/login", ApiLogin())
    app.add_route("/api/logout", ApiLogout())
    app.add_route("/api/meta", ApiMeta())
    app.add_route("/api/windows", ApiWindows())
    app.add_route("/api/windows/{window_id:int}/plan", ApiPlan())
    app.add_route("/api/windows/{window_id:int}/slices", ApiSlices())
    app.add_route("/api/slices/{slice_id:int}/replay", ApiReplay())
    app.add_route("/api/coverage-reports", ApiCoverage())
    app.add_route("/api/claim", ApiClaim())
    app.add_route("/api/claim/panels", ApiClaimPanels())
    app.add_static_route("/static", str(STATIC))
    return app


app = create_app()
