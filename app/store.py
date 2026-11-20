import sqlite3, json, hashlib
from datetime import datetime, timezone
from decimal import Decimal
from app.config import DATA_DIR, RULE_VERSION
from app.errors import BusinessError

LABOR_SCHEMA = """CREATE TABLE IF NOT EXISTS labor (
    voyage TEXT NOT NULL,
    team TEXT NOT NULL,
    run_id TEXT NOT NULL,
    state TEXT NOT NULL,
    version INTEGER,
    scheduled_s TEXT NOT NULL,
    settled_s TEXT,
    approved_revision INTEGER NOT NULL,
    approved_at TEXT NOT NULL,
    PRIMARY KEY (voyage, team)
)"""

LABOR_ADJUST_SCHEMA = """CREATE TABLE IF NOT EXISTS labor_adjustment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    voyage TEXT NOT NULL,
    team TEXT NOT NULL,
    run_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    source TEXT NOT NULL,
    previous_s TEXT,
    current_s TEXT NOT NULL,
    delta_s TEXT NOT NULL,
    created TEXT NOT NULL,
    UNIQUE (voyage, team, version)
)"""

def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"runs.sqlite", timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, decision TEXT NOT NULL DEFAULT '待复核', created TEXT NOT NULL)")
    db.execute(LABOR_SCHEMA)
    db.execute(LABOR_ADJUST_SCHEMA)
    return db

def save(text, result):
    digest=hashlib.sha256((RULE_VERSION+"\n"+text).encode()).hexdigest()
    ident=digest[:16]
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,digest,result,created) VALUES(?,?,?,?)",(ident,digest,json.dumps(dict(result,rule_version=RULE_VERSION),ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
    return get(ident)

def get(ident):
    with connect() as db:
        row=db.execute("SELECT * FROM runs WHERE id=?",(ident,)).fetchone()
    if row is None: raise BusinessError("NOT_FOUND","批次不存在",404)
    item=dict(row);item["result"]=json.loads(item["result"]);item["rule_version"]=item["result"].get("rule_version","2026.11.18.1")
    return item

def history():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id,revision,decision,created FROM runs ORDER BY created DESC LIMIT 40")]

def review(ident,revision,decision):
    if not isinstance(decision,str) or decision not in {"通过","退回"}: raise BusinessError("DECISION","复核决定无效")
    current=get(ident)
    if decision=="通过" and current["result"].get("blocked"):
        raise BusinessError("BLOCKED","存在阻断项，请先修正数据",409)
    with connect() as db:
        changed=db.execute("UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?",(decision,ident,revision)).rowcount
        if not changed: raise BusinessError("STALE","版本已更新，请刷新",409)
        if decision=="通过":
            # 核准即记账；幂等键保证重跑/重复核准不重复记工。退回不撤销既有核准工时。
            book_labor(db,current["id"],current["result"],revision+1)
    return get(ident)

def _dec(value):
    return Decimal(str(value)) if value not in (None,"") else None

def book_labor(db,run_id,result,approved_revision):
    labor=result.get("labor") or {}
    now=datetime.now(timezone.utc).isoformat()
    rows=labor.get("rows") or []
    # 稳定排序，保证同一批复核的记账顺序确定。
    for row in sorted(rows,key=lambda r:(r["ship"],r["team"])):
        voyage,team=row["ship"],row["team"]
        if team=="未值守":
            continue
        scheduled=_dec(row.get("scheduled_s")) or Decimal(0)
        settled=_dec(row.get("settled_s"))
        version=row.get("version")
        previous=db.execute("SELECT * FROM labor WHERE voyage=? AND team=?",(voyage,team)).fetchone()
        previous_settled=_dec(previous["settled_s"]) if previous else None
        previous_scheduled=_dec(previous["scheduled_s"]) if previous else None
        if settled is None:
            # 暂计只填补空档，不覆盖已实结工时，也不产生补差。
            db.execute("INSERT INTO labor(voyage,team,run_id,state,version,scheduled_s,settled_s,approved_revision,approved_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(voyage,team) DO UPDATE SET "
                       "run_id=excluded.run_id,state=excluded.state,version=excluded.version,"
                       "scheduled_s=excluded.scheduled_s,approved_revision=excluded.approved_revision,approved_at=excluded.approved_at "
                       "WHERE labor.settled_s IS NULL",
                       (voyage,team,run_id,"暂计",None,str(scheduled),None,approved_revision,now))
            continue
        # 实结：同一回执版本只记一次；旧版本不得覆盖新版本。
        if previous is not None and previous["state"]=="实结" and version is not None \
                and previous["version"] is not None and int(version)<=int(previous["version"]):
            continue
        baseline=previous_settled if previous_settled is not None else (
            previous_scheduled if previous_scheduled is not None else scheduled)
        delta=settled-baseline
        source="回执更正" if previous_settled is not None else "排程转实结"
        if delta!=0 and version is not None:
            db.execute(
                "INSERT OR IGNORE INTO labor_adjustment(voyage,team,run_id,version,source,previous_s,current_s,delta_s,created) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (voyage,team,run_id,int(version),source,str(baseline),str(settled),str(delta),now))
        db.execute("INSERT INTO labor(voyage,team,run_id,state,version,scheduled_s,settled_s,approved_revision,approved_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(voyage,team) DO UPDATE SET "
                   "run_id=excluded.run_id,state=excluded.state,version=excluded.version,"
                   "scheduled_s=excluded.scheduled_s,settled_s=excluded.settled_s,"
                   "approved_revision=excluded.approved_revision,approved_at=excluded.approved_at",
                   (voyage,team,run_id,"实结",version,str(scheduled),str(settled),approved_revision,now))

def ledger():
    with connect() as db:
        rows=[dict(r) for r in db.execute("SELECT * FROM labor ORDER BY team,voyage")]
        adjustments=[dict(r) for r in db.execute("SELECT * FROM labor_adjustment ORDER BY id")]
    for r in rows:
        r["scheduled_h"]=str((Decimal(r["scheduled_s"])/Decimal(3600)).quantize(Decimal("0.01")))
        r["settled_h"]="" if r["settled_s"] is None else str((Decimal(r["settled_s"])/Decimal(3600)).quantize(Decimal("0.01")))
    for a in adjustments:
        a["delta_h"]=str((Decimal(a["delta_s"])/Decimal(3600)).quantize(Decimal("0.01")))
    teams={}
    for r in rows:
        t=teams.setdefault(r["team"],{"team":r["team"],"ships":0,"provisional_s":Decimal(0),"settled_s":Decimal(0)})
        t["ships"]+=1
        if r["state"]=="实结": t["settled_s"]+=Decimal(r["settled_s"] or 0)
        else: t["provisional_s"]+=Decimal(r["scheduled_s"])
    summary=[]
    for t in sorted(teams.values(),key=lambda x:x["team"]):
        summary.append({"team":t["team"],"ships":t["ships"],
                        "provisional_h":str((t["provisional_s"]/Decimal(3600)).quantize(Decimal("0.01"))),
                        "settled_h":str((t["settled_s"]/Decimal(3600)).quantize(Decimal("0.01")))})
    return {"rows":rows,"adjustments":adjustments,"teams":summary}
