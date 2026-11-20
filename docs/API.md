# 接口

`POST /api/run`：{"text":"CSV内容"}。同规则版本与输入摘要只产生一条批次。

`GET/POST /api/1` 至 `/api/8`：独立样例或自定义文件计算。各模块返回 report、quarantine、balance；M8 另返回 labor（shifts、rows、teams、corrections、provisional、settled）。

`GET /api/labor`：已核准班组工时台账（rows、adjustments、teams）。

`POST /api/review`：id、整数revision、decision取通过或退回。旧版本409；阻断项不能通过。核准时按 labor 结果记工，同一航次+班组+回执版本幂等。

`GET /api/sample?module=8`：M8 返回班组样例，其余返回默认样例。

`GET /api/export/{id}`：唯一证据CSV。`GET /health`：存活检查。

错误：结构/数值422，版本冲突409，不存在404，文件过大413。逐行异常进入quarantine。
