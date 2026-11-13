"""字段映射业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "extractor"
REQUIRED_FIELDS = ["规则编号", "源字段名称", "目标字段名称"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用规则": "已启用", "停用规则": "已停用"}
NEGATIVE_ACTIONS = ["停用规则"]


class ExtractorService(BaseResourceService):
    module = MODULE
    entry_label = "映射规则"
    scope_label = "字段映射"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
