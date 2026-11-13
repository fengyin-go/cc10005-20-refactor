"""调度策略业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "schedule"
REQUIRED_FIELDS = ["规则编号", "关联站点", "调度表达式"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用调度": "已启用", "停用调度": "已停用"}
NEGATIVE_ACTIONS = ["停用调度"]


class ScheduleService(BaseResourceService):
    module = MODULE
    entry_label = "调度规则"
    scope_label = "调度策略"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
