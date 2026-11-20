import csv,io,json

def evidence_csv(run):
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(["run_id","sha256","rule_version","kind","line","reason","evidence"])
    writer.writerow([run["id"],run["digest"],run["rule_version"],"manifest","","",json.dumps({"balance":run["result"]["balance"],"decision":run["decision"],"revision":run["revision"]},ensure_ascii=False)])
    for row in run["result"].get("final",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"result",row.get("line",""),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    labor=run["result"].get("labor") or {}
    for row in labor.get("teams",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"labor_team","","",json.dumps(row,ensure_ascii=False)])
    for row in labor.get("shifts",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"labor_shift",row.get("line",""),"",json.dumps(row,ensure_ascii=False)])
    for row in labor.get("rows",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"labor_voyage",row.get("line",""),row.get("state",""),json.dumps(row,ensure_ascii=False)])
    for row in labor.get("corrections",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"labor_adjustment","",row.get("source",""),json.dumps(row,ensure_ascii=False)])
    for row in run["result"].get("quarantine",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"quarantine",row.get("line",""),row["reason"],json.dumps(row,ensure_ascii=False)])
    return "\ufeff"+out.getvalue()
