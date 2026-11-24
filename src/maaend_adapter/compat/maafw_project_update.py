"""宿主能力兼容层：MaaFW 增量更新读取器与限速器。

TODO(SDK)：MaaFW 提供能力接口或 auto_mas_core.host 导出后删除本文件。
"""

from importlib import import_module
from typing import Any

_TARGETS = {
    "RangeHTTPReader": "app.task.MaaFW.tools.core.project_update.projection_heal",
    "RangeSpeedGuard": "app.task.MaaFW.tools.core.project_update.range_delta",
}


def __getattr__(name: str) -> Any:
    """按符号来源模块转发，调用点不需要知道两个实现分属不同文件。"""
    target = _TARGETS.get(name)
    if target is None:
        raise AttributeError(name)
    return getattr(import_module(target), name)

