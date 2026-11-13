"""RPA流程业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "rpaflow"
REQUIRED_FIELDS = ["流程编号", "目标页面", "操作序列"]
STATUS_ORDER = ["草稿", "待校验", "执行中", "已完成", "已失败"]
ACTION_RULES = {"提交执行": "待校验", "启动流程": "执行中", "终止流程": "已失败", "归档结果": "已完成"}
NEGATIVE_ACTIONS = []


class RpaflowService(BaseResourceService):
    module = MODULE
    entry_label = "自动化流程"
    scope_label = "RPA流程"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
