from app.pipeline import run


def execute(text):
    result = run(text)
    labor = result.get("labor", {})
    return {
        "module": 8,
        "report": result["reports"][7],
        "labor": labor,
        "quarantine": result["quarantine"],
        "balance": result["balance"],
    }
