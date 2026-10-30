from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_diff import build
from tracejudge.models import ScoreResult
from tracejudge.server import create_app
from tracejudge.store import Store


def test_api(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    a, b = build(store)
    # give one trial a judge verdict so it can be labelled
    cr = store.case_results(a.run_id)[0]
    cr.scores.append(ScoreResult(scorer="judge", name="tone", passed=True, reason="polite"))
    store.save_case_result(cr)
    c = TestClient(create_app(store, otlp_token=""))

    runs = c.get("/api/runs").json()
    assert {r["label"] for r in runs} == {"v1", "v2"}
    assert c.get("/api/runs", params={"sha": "bbb"}).json()[0]["label"] == "v2"

    detail = c.get(f"/api/runs/{b.run_id}").json()
    case = next(x for x in detail["cases"] if x["case_id"] == "refund-ineligible")
    assert (case["passed"], case["trials"]) == (0, 3)
    assert case["failing"] == ["precondition:refund<-policy"]

    res = c.get(f"/api/results/{case['results'][0]['id']}").json()
    assert [s["name"] for s in res["trace"]["spans"]] == ["lookup_order", "refund"]
    assert c.get(f"/api/traces/{res['trace']['trace_id']}").status_code == 200

    d = c.get("/api/diff", params={"a": "v1", "b": "v2"}).json()
    assert [x["case_id"] for x in d["cases"] if x["status"] == "regressed"] == ["refund-ineligible"]

    q = c.get("/api/label-queue", params={"run": "v1"}).json()
    assert q["items"] == [
        {"result_id": cr.id, "case_id": cr.case_id, "trial": cr.trial, "criterion": "tone"}
    ]
    bad = c.post(
        "/api/labels", json={"case_result_id": cr.id, "criterion": "x", "human_pass": True}
    )
    assert bad.status_code == 400
    ok = c.post(
        "/api/labels",
        json={"case_result_id": cr.id, "criterion": "tone", "human_pass": False, "note": "curt"},
    )
    assert ok.status_code == 200
    cal = c.get("/api/calibration").json()
    assert cal[0]["criterion"] == "tone" and cal[0]["agreement"] == 0
    assert c.get("/api/label-queue", params={"run": "v1"}).json()["items"] == []
    assert c.delete(f"/api/labels/{cr.id}/tone").status_code == 200
    assert c.get("/api/runs/nope").status_code == 404
