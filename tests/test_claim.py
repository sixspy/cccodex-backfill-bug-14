import pytest


async def _claim(client, actor, slice_key="S9"):
    return await client.post("/api/claim", json={"slice_key": slice_key, "actor": actor})


@pytest.mark.asyncio
async def test_first_claim_wins_second_rejected(authed):
    first = await _claim(authed, "A")
    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert first.json()["chip"] == "先手"

    second = await _claim(authed, "B")
    assert second.status_code == 409
    body = second.json()
    assert body["rejected"] is True
    assert body["chip"] == "拒重"
    assert body["holder"] == "A"
    assert "已被 A 独占" in body["msg"]

    panels = (await authed.get("/api/claim/panels")).json()
    assert panels["water"]["count"] == 1
    assert panels["water"]["dup"] is False
    assert len(panels["water"]["locks"]) == 1
    assert panels["queue"][0]["actor"] == "A"
    assert panels["card"]["lit"] is True


@pytest.mark.asyncio
async def test_reject_chip_and_detail_share_pointer(authed):
    await _claim(authed, "A")
    await _claim(authed, "B")

    detail = (await authed.get("/api/claim/panels")).json()
    assert detail["detail"]["ptr"] == "S9"
    assert detail["detail"]["holder"] == "A"
    assert detail["detail"]["ui"] == "占用"
    assert detail["detail"]["writable"] == "0"
    assert detail["card"]["state"] == "亮"
    assert detail["card"]["chip"] == "拒重"


@pytest.mark.asyncio
async def test_chip_persists_after_coverage_rerun(authed):
    await _claim(authed, "A")
    await _claim(authed, "B")

    windows = (await authed.get("/api/windows")).json()["items"]
    wid = windows[0]["id"]
    await authed.post(f"/api/windows/{wid}/plan")
    await authed.post("/api/coverage-reports", json={"window_id": wid})

    panels = (await authed.get("/api/claim/panels")).json()
    assert panels["card"]["chip"] == "拒重"
    assert panels["card"]["lit"] is True
    assert panels["water"]["count"] == 1
    assert panels["water"]["dup"] is False


@pytest.mark.asyncio
async def test_same_slice_cannot_be_claimed_twice_by_same_actor(authed):
    await _claim(authed, "A")
    again = await _claim(authed, "A")
    assert again.status_code == 409
    panels = (await authed.get("/api/claim/panels")).json()
    assert panels["water"]["count"] == 1
