from fastapi.testclient import TestClient
import pytest
from app.main import app
from app.pipeline import labor_sample_text, run
from app import store

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path):
    original = store.DATA_DIR
    store.DATA_DIR = tmp_path
    yield
    store.DATA_DIR = original


def test_labor_sample_has_cross_shift_and_correction():
    result = run(labor_sample_text())
    labor = result["labor"]
    assert {"A班", "B班"} <= {t["team"] for t in labor["teams"]}
    assert any(c["source"] == "回执更正" for c in labor["corrections"])
    assert result["balance"]["input"] == (
        result["balance"]["accepted"] + result["balance"]["quarantined"] + result["balance"]["blank"])


def test_labor_page_renders():
    response = client.get("/module/8")
    assert response.status_code == 200
    for heading in ("航次归班", "班组小计", "补差明细", "已核准台账", "补差流水"):
        assert heading in response.text


def test_api8_reports_provisional_and_settled():
    payload = client.get("/api/8").json()
    metrics = payload["report"]["metrics"]
    assert set(metrics) >= {"暂计h", "实结h", "补差h", "合计h"}
    assert payload["module"] == 8


def test_export_contains_labor_evidence():
    created = client.post("/api/run", json={"text": labor_sample_text()}).json()
    text = client.get(f"/api/export/{created['id']}").text
    assert "labor_team" in text and "labor_adjustment" in text
