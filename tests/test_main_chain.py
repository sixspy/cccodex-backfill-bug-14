import pytest


@pytest.mark.asyncio
async def test_plan_replay_coverage(authed):
    windows = (await authed.get("/api/windows")).json()["items"]
    wid = windows[0]["id"]
    planned = (await authed.post(f"/api/windows/{wid}/plan")).json()
    assert len(planned["slices"]) == 3

    first = planned["slices"][0]["id"]
    replayed = (await authed.post(f"/api/slices/{first}/replay")).json()["slice"]
    assert replayed["status"] == "已落库"
    assert replayed["row_count"] > 0

    again = await authed.post(f"/api/slices/{first}/replay")
    assert again.status_code == 409

    report = (await authed.post("/api/coverage-reports", json={"window_id": wid})).json()["report"]
    assert report["planned"] == 3
    assert report["loaded"] == 1
    assert report["missing"] == 2
