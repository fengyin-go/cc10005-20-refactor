"""限速控制业务规则：状态流转、字段校验与筛选口径都收在这里。

额度编辑（每秒请求上限、令牌桶容量等）必须携带快照版本，版本过期时由仓库层
返回冲突回执，避免以旧容量覆盖新额度。
"""
from __future__ import annotations

from app.services.base import BaseResourceService

MODULE = "ratelimit"
REQUIRED_FIELDS = ["配置编号", "目标站点", "每秒请求上限"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用限速": "已启用", "停用限速": "已停用"}
NEGATIVE_ACTIONS = ["停用限速"]


class RatelimitService(BaseResourceService):
    module = MODULE
    entry_label = "限速配置"
    scope_label = "限速控制"
    required_fields = REQUIRED_FIELDS
    status_order = STATUS_ORDER
    action_rules = ACTION_RULES
    negative_actions = NEGATIVE_ACTIONS
    expose_version = True
