"""代理池管理业务规则：状态流转、字段校验与筛选口径都收在这里。

节点回收（标记可用/不可用、移除）必须携带快照版本，版本过期时由仓库层拒绝，
避免两个回收流程互相覆盖状态。
"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "proxy"
REQUIRED_FIELDS = ["节点编号", "代理地址", "代理协议"]
STATUS_ORDER = ["草稿", "可用", "不可用", "已移除"]
ACTION_RULES = {"标记可用": "可用", "标记不可用": "不可用", "移除节点": "已移除"}
NEGATIVE_ACTIONS = []


class ProxyService(BaseResourceService):
    module = MODULE
    entry_label = "代理节点"
    scope_label = "代理池管理"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    expose_version = True
