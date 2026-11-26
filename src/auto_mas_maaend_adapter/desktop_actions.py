#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#
#   This file is part of AUTO-MAS.
#
#   AUTO-MAS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of
#   the License, or (at your option) any later version.
#
#   AUTO-MAS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#   GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public License
#   along with AUTO-MAS. If not, see <https://www.gnu.org/licenses/>.
#
#   Contact: DLmaster_361@163.com
"""在桌面分身进程里执行的 MaaEnd 动作。

宿主的分身工作进程收到 ``maaend_*`` 动作后转到这里；本模块在分身进程里运行，
所以只用同步调用。主会话那边的 Python 编排留在执行层，不在这里。

动作名与参数沿用迁入前宿主内置实现的约定，返回值也一样：``(退出码, JSON 文本)``，
文本由宿主原样回传给发起方。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any


def _game_window(_: dict[str, Any]) -> tuple[int, str]:
    """分身桌面上是否已有终末地客户端窗口。"""
    import win32gui

    return 0, json.dumps(bool(win32gui.FindWindow("UnityWndClass", "Endfield")))


def _failure_screenshot(arguments: dict[str, Any]) -> tuple[int, str]:
    """在分身里截失败现场，返回保存路径或空值。"""
    from auto_mas_core.host.services import capture_win32
    from auto_mas_core.host.task_failure_capture_core import FailureCapture

    from .auto_proxy import AutoProxyTask

    hwnd = AutoProxyTask.find_failure_window(Path(str(arguments["game_path"])))
    screenshot = None
    if hwnd is not None:
        image = asyncio.run(capture_win32(hwnd))
        screenshot = FailureCapture(stopped=lambda: False).save(
            image, dir_name="maaend-failure"
        )
    return 0, json.dumps(str(screenshot) if screenshot else None)


def _direct_launch(arguments: dict[str, Any]) -> tuple[int, str]:
    """按 MAS 直启入口拉起游戏客户端。"""
    from .tools.game_launcher import launch_game

    launch_game(
        arguments["launcher_path"],
        Path(str(arguments["game_path"])),
        arguments["game_arguments"],
    )
    return 0, json.dumps(None)


def _launch_via_launcher(
    arguments: dict[str, Any],
    on_log: Callable[[str], None] | None,
) -> tuple[int, str]:
    """拉起终末地官方启动器并点开始，回传过程中产生的截图。"""
    from .tools.launcher_start import start_game_via_launcher

    screenshots: list[str] = []
    client_path = arguments.get("client_path")
    code = int(
        not start_game_via_launcher(
            arguments["launcher_path"],
            client_path=client_path,
            on_log=on_log,
            on_error_screenshot=lambda path: screenshots.append(str(path)),
        )
    )
    return code, json.dumps(screenshots)


def _login(
    arguments: dict[str, Any],
    on_restart: Callable[[], Awaitable[None]] | None,
) -> tuple[int, str]:
    """在分身里跑 MAS 自建账号切换，回传截图与失败原因。"""
    from .tools.login import LoginNotReadyError, login

    screenshots: list[str] = []
    not_ready = None
    error = None
    try:
        asyncio.run(
            login(
                arguments["account"],
                restart_game=on_restart,
                on_error_screenshot=lambda path: screenshots.append(str(path)),
            )
        )
    except LoginNotReadyError as exc:
        not_ready = str(exc)
    except Exception as exc:
        error = type(exc).__name__
    text = json.dumps(
        {"screenshots": screenshots, "notReady": not_ready, "error": error}
    )
    return int(error is not None), text


def run_action(
    action: str,
    arguments: dict[str, Any],
    *,
    on_log: Callable[[str], None] | None = None,
    on_restart: Callable[[], Awaitable[None]] | None = None,
) -> tuple[int, str]:
    """按动作名执行并在分身进程里返回结果。"""
    if action == "maaend_game_window":
        return _game_window(arguments)
    if action == "maaend_failure_screenshot":
        return _failure_screenshot(arguments)
    if action == "maaend_direct_launch":
        return _direct_launch(arguments)
    if action == "maaend_launch":
        return _launch_via_launcher(arguments, on_log)
    if action == "maaend_login":
        return _login(arguments, on_restart)
    raise RuntimeError(f"未实现的 MaaEnd 分身动作: {action}")


__all__ = ["run_action"]
