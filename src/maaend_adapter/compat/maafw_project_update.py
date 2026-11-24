"""宿主能力兼容层：MaaFW 增量更新读取器与限速器。

TODO(MaaFW)：改用 auto-mas-maafw-project-update>=0.2,<0.3。它的 0.2.0 在导入时会
回退到 app.utils.common.zip_range 取 HealSkip，当前宿主还没有该符号，因此暂时保留转发；
宿主升级到带 utils_common_zip_range 的 SDK 后删除本文件。
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

