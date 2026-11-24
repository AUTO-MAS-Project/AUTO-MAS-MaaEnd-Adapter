"""宿主能力兼容层：auto_mas_core 尚未导出 app.utils.common.zip_range。

TODO(SDK)：主仓 auto_mas_core.host 导出该模块后删除本文件，插件改为 SDK 导入。
"""

from importlib import import_module
from typing import Any

_TARGET = "app.utils.common.zip_range"


def __getattr__(name: str) -> Any:
    """按需取宿主同名能力；调用点保持与 SDK 门面一致的写法。"""
    return getattr(import_module(_TARGET), name)

