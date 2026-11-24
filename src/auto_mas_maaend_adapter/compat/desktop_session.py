"""宿主能力兼容层：桌面分身动作请求 app.task.desktop_session_worker。

TODO(SDK)：宿主提供桌面会话能力接口或 auto_mas_core.host 导出后删除本文件。
"""

from importlib import import_module
from typing import Any

_TARGET = "app.task.desktop_session_worker"


def __getattr__(name: str) -> Any:
    """按需取宿主同名能力，插件调用点保持普通导入写法。"""
    return getattr(import_module(_TARGET), name)
