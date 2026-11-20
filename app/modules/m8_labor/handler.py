from app.errors import BusinessError, object_payload
from fastapi import APIRouter, Body
from app.modules.m8_labor.service import execute

router = APIRouter()


@router.post("/api/8")
def calculate(payload: object = Body(default=None)):
    payload = object_payload(payload)
    from app.pipeline import labor_sample_text
    text = payload.get("text", labor_sample_text())
    if not isinstance(text, str):
        raise BusinessError("TEXT", "输入须为文本")
    return execute(text)


@router.get("/api/8")
def sample():
    from app.pipeline import labor_sample_text
    return execute(labor_sample_text())
