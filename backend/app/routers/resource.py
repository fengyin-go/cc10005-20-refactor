"""资源协调接口：代理池与限速控制的联合快照与跨资源整体调整。

* ``GET  /api/resources/snapshot``：取两类资源同一时间点的只读快照（含每条记录版本），
  供节点可用性与请求窗口共同裁决。
* ``POST /api/resources/adjustments``：跨两类资源的联动调整，整体确认；任一步写入
  受阻（记录缺失、版本过期等）都会整体撤销并给出冲突回执。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas import AdjustmentPayload, AdjustmentResult
from app.services.resource import resource_coordinator

router = APIRouter(prefix="/api/resources", tags=["资源协调"])


@router.get("/snapshot")
def read_snapshot() -> dict:
    """读取代理池与限速控制的统一时间点快照；返回内容均为副本，调用方可自由整理。"""
    return resource_coordinator.read_snapshot()


@router.post("/adjustments", response_model=AdjustmentResult)
def apply_adjustment(payload: AdjustmentPayload) -> AdjustmentResult:
    """整体确认一批跨资源调整；任何一项失败都整体撤销，不产生半成品状态。"""
    result, message = resource_coordinator.apply_adjustment(
        [item.model_dump() for item in payload.adjustments]
    )
    if result is None:
        return AdjustmentResult(ok=False, message=message)
    return AdjustmentResult(
        ok=True,
        message=message,
        resources=result["resources"],
        count=result["count"],
    )
