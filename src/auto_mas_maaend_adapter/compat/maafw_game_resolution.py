"""宿主能力兼容层：读终末地 PC 客户端（Unity）的分辨率与显示模式。

TODO(MaaFW)：auto-mas-maafw-interface / native 还没有导出这两个函数；等 MaaFW 适配器
或对应库提供能力后删除本文件。
"""

from importlib import import_module
from typing import Any

_TARGET = "app.task.MaaFW.tools.embedded.game_resolution"


def __getattr__(name: str) -> Any:
    """按需取宿主同名能力；调用点保持与 SDK 门面一致的写法。"""
    return getattr(import_module(_TARGET), name)

