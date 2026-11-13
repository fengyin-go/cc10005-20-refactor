"""资源协调服务：把代理池与限速控制两类资源放到同一裁决口径下。

两类资源的只读快照共用一个 ``captured_at`` 时间点，节点可用性与请求窗口可以基于
同一时点联合裁决；跨资源的变动整体提交，任一步写入受阻（记录缺失、版本过期等）
都会整体撤销，不会留下半套调整。
"""
from __future__ import annotations

from typing import Any

from app.services.proxy import ACTION_RULES as PROXY_ACTIONS
from app.services.proxy import MODULE as PROXY_MODULE
from app.services.ratelimit import ACTION_RULES as RATELIMIT_ACTIONS
from app.services.ratelimit import MODULE as RATELIMIT_MODULE
from app.store import (
    CreateOp,
    EntryNotFound,
    MutateOp,
    ResourceSnapshot,
    VersionConflict,
    store,
)

RESOURCE_MODULES = (PROXY_MODULE, RATELIMIT_MODULE)
_ACTION_RULES = {
    PROXY_MODULE: PROXY_ACTIONS,
    RATELIMIT_MODULE: RATELIMIT_ACTIONS,
}
# 系统字段由服务规则维护，不接受跨资源调整直接覆盖。
_RESERVED_FIELDS = {"id", "version", "status", "pending", "abnormal"}


class ResourceCoordinator:
    # ------------------------------------------------------------------ 联合快照
    def read_snapshot(self) -> dict[str, Any]:
        """读取代理池 + 限速控制的同一时间点快照。"""
        snapshots = store.snapshot_many(list(RESOURCE_MODULES))
        return {
            "captured_at": self._common_captured_at(snapshots),
            "resources": {
                name: self._serialize_snapshot(snapshot)
                for name, snapshot in snapshots.items()
            },
        }

    @staticmethod
    def _common_captured_at(
        snapshots: dict[str, ResourceSnapshot],
    ) -> float:
        stamps = {snapshot.captured_at for snapshot in snapshots.values()}
        assert len(stamps) == 1, "联合快照必须共用同一个读取时间点"
        return stamps.pop()

    @staticmethod
    def _serialize_snapshot(snapshot: ResourceSnapshot) -> dict[str, Any]:
        return {
            "module": snapshot.module,
            "captured_at": snapshot.captured_at,
            "rows": snapshot.rows,
            "versions": snapshot.versions,
        }

    # ------------------------------------------------------------------ 整体调整
    def apply_adjustment(
        self, adjustments: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, str]:
        operations, error = self._build_operations(adjustments)
        if error:
            return None, error
        try:
            committed = store.transact(operations)
        except EntryNotFound as exc:
            return None, f"{exc.module} 模块中 id={exc.entry_id} 的记录不存在或已归档，本次资源调整已整体撤销"
        except VersionConflict as exc:
            return None, (
                f"{exc.module} 模块 id={exc.entry_id} 版本冲突"
                f"（提交版本 {exc.expected}，当前版本 {exc.current}），本次资源调整已整体撤销"
            )
        except ValueError as exc:
            return None, f"{exc}，本次资源调整已整体撤销"
        return {"resources": committed, "count": len(committed)}, "资源调整已整体确认"

    def _build_operations(
        self, adjustments: list[dict[str, Any]]
    ) -> tuple[list[CreateOp | MutateOp], str]:
        if not adjustments:
            return [], "资源调整清单为空，未执行任何写入"
        operations: list[CreateOp | MutateOp] = []
        for index, item in enumerate(adjustments, start=1):
            module = str(item.get("module") or "").strip()
            if module not in RESOURCE_MODULES:
                return [], f"第 {index} 项调整的资源模块「{module}」不受资源协调服务管辖"
            entry_id = item.get("entry_id")
            if not isinstance(entry_id, int):
                return [], f"第 {index} 项调整缺少整数 entry_id"
            version = item.get("version")
            if version is not None and not isinstance(version, int):
                return [], f"第 {index} 项调整的版本号必须是整数"

            action = str(item.get("action") or "").strip()
            fields = item.get("fields") or {}
            if not isinstance(fields, dict):
                return [], f"第 {index} 项调整的 fields 必须是字段对象"

            patch: dict[str, Any] = {}
            if action:
                if action not in _ACTION_RULES[module]:
                    return [], f"第 {index} 项调整的动作「{action}」不属于该资源可执行范围"
                target_status = _ACTION_RULES[module][action]
                patch["status"] = target_status
                # 与单资源动作保持同一套 pending/abnormal 口径。
                service = self._service_for(module)
                patch["pending"] = target_status != service.status_order[-1]
                patch["abnormal"] = action in service.negative_actions
            patch.update({
                key: value for key, value in fields.items() if key not in _RESERVED_FIELDS
            })
            if not patch:
                return [], f"第 {index} 项调整没有可写入的动作或字段"
            operations.append(MutateOp(
                module=module,
                entry_id=entry_id,
                patch=patch,
                expected_version=version,
            ))
        return operations, ""

    @staticmethod
    def _service_for(module: str):
        if module == PROXY_MODULE:
            from app.services.proxy import ProxyService
            return ProxyService()
        from app.services.ratelimit import RatelimitService
        return RatelimitService()


resource_coordinator = ResourceCoordinator()
