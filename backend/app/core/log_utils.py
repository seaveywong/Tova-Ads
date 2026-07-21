"""日志工具：write_log helper + trace_id 生成（doc 05，总则3）。

每个写操作调 write_log → 记 action_logs → 带 trace_id 串全链路。
"""
import json
from uuid import uuid4
from sqlalchemy.orm import Session
from ..models.log import ActionLog


def new_trace_id() -> str:
    """生成 12 位 trace_id。"""
    return uuid4().hex[:12]


def write_log(
    db: Session,
    *,
    tenant_id: int,
    trace_id: str,
    actor_type: str = "system",
    actor_user_id: int | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    action_type: str | None = None,
    source: str | None = None,
    result: str = "success",
    raw_error: str | None = None,
    friendly_error: str | None = None,
    trigger_type: str | None = None,
    trigger_detail: str | None = None,
    metadata: dict | None = None,
):
    """写一条 action_log。调用者控制事务（db.flush 不 commit）。"""
    log = ActionLog(
        tenant_id=tenant_id,
        trace_id=trace_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        target_type=target_type,
        target_id=target_id,
        action_type=action_type,
        source=source,
        result=result,
        raw_error=raw_error,
        friendly_error=friendly_error,
        trigger_type=trigger_type,
        trigger_detail=trigger_detail,
        metadata_=json.dumps(metadata) if metadata else None,
    )
    db.add(log)
    db.flush()
    return log
