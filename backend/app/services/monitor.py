"""采集监控业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "monitor"
REQUIRED_FIELDS = ["指标编号", "关联任务", "指标名称"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用监控": "已启用", "停用监控": "已停用"}
NEGATIVE_ACTIONS = ["停用监控"]


class MonitorService(BaseResourceService):
    module = MODULE
    entry_label = "监控指标"
    scope_label = "采集监控"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
