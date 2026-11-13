"""采集流水线业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "pipeline"
REQUIRED_FIELDS = ["步骤编号", "步骤名称", "输入数据源"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用步骤": "已启用", "停用步骤": "已停用"}
NEGATIVE_ACTIONS = ["停用步骤"]


class PipelineService(BaseResourceService):
    module = MODULE
    entry_label = "流水线步骤"
    scope_label = "采集流水线"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
