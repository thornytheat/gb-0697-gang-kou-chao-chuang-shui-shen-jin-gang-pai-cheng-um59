from collections import defaultdict
from decimal import Decimal
from app.report import report
from app.numbers import fmt
from app.modules.m4_channel.rules import subtract

HOUR = Decimal(3600)
UNCOVERED = "未值守"

def _overlap(x, y):
    lo, hi = max(x[0], y[0]), min(x[1], y[1])
    return (lo, hi) if lo < hi else None

def attribute(start, end, shifts):
    """把 [start,end) 按值守班次切分；不在任何班次内的部分单独记入“未值守”。"""
    parts = defaultdict(lambda: Decimal(0))
    if start is None or end is None or end <= start:
        return parts
    for label, a, b in shifts:
        hit = _overlap((start, end), (a, b))
        if hit:
            parts[label] += hit[1] - hit[0]
    for a, b in subtract((start, end), [(a, b) for _, a, b in shifts]):
        parts[UNCOVERED] += b - a
    return {k: v for k, v in parts.items() if v > 0}

def _label(row):
    return row["id"]

def _hours(seconds):
    return fmt(Decimal(seconds) / HOUR, 2)

def _ordered(labels):
    return sorted(labels, key=lambda x: (x == UNCOVERED, x))

def apply(ctx):
    # M2 已保证班次互不重叠、回执都能对上船舶；这里只做纯归集。
    shifts = [(_label(r), r["a"], r["b"], r) for r in
              sorted((r for r in ctx["effective"] if r["kind"] == "team"),
                     key=lambda r: (r["a"], r["b"], r["id"]))]
    shift_list = [(label, a, b) for label, a, b, _ in shifts]

    ships = {r["id"]: r for r in ctx["effective"] if r["kind"] == "ship"}
    receipts = {r["id"]: r for r in ctx["effective"] if r["kind"] == "receipt"}
    # 同一航次的全部回执版本：用于更正补差。
    history = defaultdict(list)
    for r in ctx["normalized"]:
        if r["kind"] == "receipt" and r["id"] in ships:
            history[r["id"]].append(r)

    rows, corrections = [], []
    teams = defaultdict(lambda: {"scheduled_s": Decimal(0), "provisional_s": Decimal(0),
                                 "settled_s": Decimal(0), "delta_s": Decimal(0), "ships": set()})
    provisional, settled, uncovered_s = [], [], Decimal(0)

    for assigned in ctx["assigned"]:
        voyage = assigned["id"]
        scheduled = attribute(assigned.get("start_s"), assigned.get("end_s"), shift_list)
        receipt = receipts.get(voyage)
        actual = attribute(receipt["a"], receipt["b"], shift_list) if receipt else None
        (settled if receipt else provisional).append(voyage)
        uncovered_s += (actual if actual is not None else scheduled).get(UNCOVERED, Decimal(0))

        state = "实结" if receipt else "暂计"
        line = (receipt or ships[voyage]).get("line", ships[voyage].get("line", 0))
        version = receipt["version_value"] if receipt else None
        for team in _ordered(set(scheduled) | set(actual or {})):
            base = scheduled.get(team, Decimal(0))
            real = (actual or {}).get(team, Decimal(0))
            rows.append({"ship": voyage, "team": team, "state": state,
                         "scheduled_s": base, "settled_s": real if actual is not None else None,
                         "delta_s": (real - base) if actual is not None else None,
                         "version": version, "line": line})
            bucket = teams[team]
            bucket["scheduled_s"] += base
            bucket["ships"].add(voyage)
            if actual is None:
                bucket["provisional_s"] += base
            else:
                bucket["settled_s"] += real
                bucket["delta_s"] += real - base

        if receipt is not None:
            # 更正回执与上一版回执比，首份回执与排程基线比。
            prior = sorted((r for r in history[voyage] if r["version_value"] < receipt["version_value"]),
                           key=lambda r: r["version_value"])
            if prior:
                baseline, source = attribute(prior[-1]["a"], prior[-1]["b"], shift_list), "回执更正"
            else:
                baseline, source = scheduled, ("排程转实结" if scheduled else "无排程回执")
            for team in _ordered(set(baseline) | set(actual)):
                base = baseline.get(team, Decimal(0))
                real = actual.get(team, Decimal(0))
                if real == base:
                    continue
                corrections.append({"ship": voyage, "team": team, "source": source,
                                    "base_s": base, "settled_s": real, "delta_s": real - base,
                                    "version": receipt["version_value"]})

    team_rows = []
    for label in _ordered(teams):
        b = teams[label]
        team_rows.append({"team": label, "ships": len(b["ships"]),
                          "scheduled_s": b["scheduled_s"], "scheduled_h": _hours(b["scheduled_s"]),
                          "provisional_s": b["provisional_s"], "provisional_h": _hours(b["provisional_s"]),
                          "settled_s": b["settled_s"], "settled_h": _hours(b["settled_s"]),
                          "delta_s": b["delta_s"], "delta_h": _hours(b["delta_s"])})
    for c in corrections:
        c.update(base_h=_hours(c["base_s"]), settled_h=_hours(c["settled_s"]), delta_h=_hours(c["delta_s"]))

    ctx["labor"] = {
        "shifts": [{"team": label, "start_s": a, "end_s": b, "line": r.get("line", 0)}
                   for label, a, b, r in shifts],
        "rows": rows, "teams": team_rows, "corrections": corrections,
        "provisional": provisional, "settled": settled, "uncovered_s": uncovered_s,
    }
    display = [dict(r, scheduled_h=_hours(r["scheduled_s"]),
                    settled_h=_hours(r["settled_s"]) if r["settled_s"] is not None else "",
                    delta_h=_hours(r["delta_s"]) if r["delta_s"] is not None else "")
               for r in rows]
    for t in team_rows:
        # 已核实的暂计与已实结分别汇总；实结优先，未回执航次保留暂计。
        t["reported_h"] = _hours(t["settled_s"] + t["provisional_s"])
    metrics = {
        "班次": len(shifts),
        "班组": len({label for label, _, _, _ in shifts}),
        "暂计h": _hours(sum(t["provisional_s"] for t in team_rows)),
        "实结h": _hours(sum(t["settled_s"] for t in team_rows)),
        "补差h": _hours(sum(t["delta_s"] for t in team_rows)),
        "合计h": _hours(sum(t["settled_s"] + t["provisional_s"] for t in team_rows)),
        "未值守h": _hours(uncovered_s),
        "待回执": len(provisional),
    }
    return report(display, **metrics)
