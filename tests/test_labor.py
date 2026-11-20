from decimal import Decimal
from app.pipeline import run
from app.modules.m8_labor.rules import attribute, UNCOVERED
from app import store

# 两班倒：A 00:00-04:00，B 04:00-08:00；潮位足够高，S1 可在 00:00-08:00 内排程。
BASE = """id,kind,start,end,value,aux,version,unit
T0,tide,2026-11-18T00:00:00Z,,1,,1,m
T1,tide,2026-11-18T02:00:00Z,,5,,1,m
T2,tide,2026-11-18T04:00:00Z,,1,,1,m
T3,tide,2026-11-18T06:00:00Z,,1,,1,m
T4,tide,2026-11-18T08:00:00Z,,5,,1,m
T5,tide,2026-11-18T10:00:00Z,,1,,1,m
A,team,2026-11-18T00:00:00Z,2026-11-18T04:00:00Z,0,,1,m
B,team,2026-11-18T04:00:00Z,2026-11-18T08:00:00Z,0,,1,m
S1,ship,2026-11-18T00:00:00Z,2026-11-18T08:00:00Z,9,180,1,m
P1,pilot,2026-11-18T00:00:00Z,2026-11-18T10:00:00Z,0,,1,m
"""

RECEIPT = "S1,receipt,2026-11-18T01:00:00Z,2026-11-18T05:00:00Z,0,,1,m\n"


def row(labor, ship, team):
    return next(r for r in labor["rows"] if r["ship"] == ship and r["team"] == team)


def test_attribute_splits_by_shift():
    shifts = [("A", Decimal(0), Decimal(4 * 3600)), ("B", Decimal(4 * 3600), Decimal(8 * 3600))]
    parts = attribute(Decimal(3600), Decimal(5 * 3600), shifts)
    assert parts == {"A": Decimal(3 * 3600), "B": Decimal(3600)}


def test_attribute_uncovered():
    shifts = [("A", Decimal(0), Decimal(3600))]
    parts = attribute(Decimal(0), Decimal(7200), shifts)
    assert parts == {"A": Decimal(3600), UNCOVERED: Decimal(3600)}


def test_labor_scheduled_is_provisional():
    labor = run(BASE)["labor"]
    r = row(labor, "S1", "A")
    assert r["state"] == "暂计" and r["settled_s"] is None
    assert labor["provisional"] == ["S1"] and labor["settled"] == []


def test_labor_receipt_settles_across_shift():
    # 排程落在 A 班；回执 01:00-05:00 跨入 B 班，B 班应得 1 小时实结。
    labor = run(BASE + RECEIPT)["labor"]
    assert row(labor, "S1", "A")["settled_s"] == "10800.0"
    assert row(labor, "S1", "B")["settled_s"] == "3600.0"
    assert row(labor, "S1", "B")["state"] == "实结"


def test_labor_late_receipt_corrects_previous():
    # v2 更正把 04:00 的点挪到 07:00：A 班 1h，B 班 3h。
    data = BASE + RECEIPT + "S1,receipt,2026-11-18T03:00:00Z,2026-11-18T07:00:00Z,0,,2,m\n"
    labor = run(data)["labor"]
    assert row(labor, "S1", "A")["settled_s"] == "3600.0"
    assert row(labor, "S1", "B")["settled_s"] == "10800.0"
    corrections = {(c["team"], c["source"]) for c in labor["corrections"]}
    assert ("A", "回执更正") in corrections and ("B", "回执更正") in corrections


def test_labor_correction_compares_previous_version():
    data = BASE + RECEIPT + "S1,receipt,2026-11-18T03:00:00Z,2026-11-18T07:00:00Z,0,,2,m\n"
    labor = run(data)["labor"]
    a = next(c for c in labor["corrections"] if c["team"] == "A")
    assert a["base_s"] == "10800.0" and a["settled_s"] == "3600.0" and a["delta_s"] == "-7200.0"


def test_labor_receipt_unmatched_quarantined():
    data = BASE.replace("S1,ship", "S9,ship") + RECEIPT.replace("S1,receipt", "S2,receipt")
    result = run(data)
    assert any(x["reason"] == "RECEIPT_UNMATCHED" for x in result["quarantine"])
    assert result["balance"]["input"] == (
        result["balance"]["accepted"] + result["balance"]["quarantined"] + result["balance"]["blank"])


def test_labor_shift_overlap_quarantined():
    data = BASE + "A2,team,2026-11-18T03:00:00Z,2026-11-18T05:00:00Z,0,,1,m\n"
    result = run(data)
    assert any(x["reason"] == "TEAM_SHIFT_OVERLAP" for x in result["quarantine"])
    assert len(result["labor"]["shifts"]) == 2


def test_labor_no_shifts_all_uncovered():
    data = BASE.replace(",team,", ",pilot,")
    # 去掉班次后，工时全部落入“未值守”，不虚增任何班组。
    labor = run(data)["labor"]
    assert {r["team"] for r in labor["rows"]} == {UNCOVERED}


def test_labor_totals_conserve():
    labor = run(BASE + RECEIPT)["labor"]
    teams = labor["teams"]
    total = sum(Decimal(t["settled_s"]) + Decimal(t["provisional_s"]) for t in teams)
    movements = sum(Decimal(r["settled_s"] or r["scheduled_s"]) for r in labor["rows"] if r["team"] != UNCOVERED)
    assert total == movements


# ---- 持久台账：核准记工、幂等、补差、退回可查 ----

def _fresh(tmp_path):
    import app.store as store_module
    store_module.DATA_DIR = tmp_path


def test_store_repeat_approval_does_not_double_book(tmp_path):
    _fresh(tmp_path)
    item = store.save(BASE + RECEIPT, run(BASE + RECEIPT))
    store.review(item["id"], 0, "通过")
    first = store.ledger()
    # 重跑同样内容复用同一批次，再次核准不会重复记工。
    again = store.save(BASE + RECEIPT, run(BASE + RECEIPT))
    store.review(again["id"], again["revision"], "通过")
    second = store.ledger()
    assert first["adjustments"] == second["adjustments"]


def test_store_late_correction_records_delta(tmp_path):
    _fresh(tmp_path)
    first = store.save(BASE + RECEIPT, run(BASE + RECEIPT))
    store.review(first["id"], 0, "通过")
    corrected = BASE + RECEIPT + "S1,receipt,2026-11-18T03:00:00Z,2026-11-18T07:00:00Z,0,,2,m\n"
    second = store.save(corrected, run(corrected))
    store.review(second["id"], 0, "通过")
    ledger = store.ledger()
    row_a = next(r for r in ledger["rows"] if r["team"] == "A")
    assert row_a["settled_s"] == "3600.0" and row_a["version"] == 2
    deltas = {(a["team"], a["version"]): a["delta_s"] for a in ledger["adjustments"]}
    assert deltas[("A", 2)] == "-7200.0" and deltas[("B", 2)] == "7200.0"


def test_store_rejected_run_keeps_approved_labor(tmp_path):
    _fresh(tmp_path)
    item = store.save(BASE + RECEIPT, run(BASE + RECEIPT))
    store.review(item["id"], 0, "通过")
    before = store.ledger()
    store.review(item["id"], 1, "退回")
    after = store.ledger()
    assert after["rows"] == before["rows"] and after["adjustments"] == before["adjustments"]


def test_store_republish_same_receipt_version_is_idempotent(tmp_path):
    _fresh(tmp_path)
    item = store.save(BASE + RECEIPT, run(BASE + RECEIPT))
    store.review(item["id"], 0, "通过")
    count = len(store.ledger()["adjustments"])
    # 相同内容换了批次号（例如补了空行），同一回执版本仍不得重复补差。
    other = store.save(BASE + RECEIPT + "\n", run(BASE + RECEIPT + "\n"))
    store.review(other["id"], 0, "通过")
    assert len(store.ledger()["adjustments"]) == count
