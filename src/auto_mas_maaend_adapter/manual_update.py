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
"""脚本配置页「检查更新」的手动入口：一次终末地 PC 客户端差量更新。

走 `tools/update.ensure_game_updated` 这条判定链；与自动前置门的区别只在怎么用
那四个状态——自动流程对「判不了」放行 `Skipped`，这里要如实告诉用户没查出结论。

这里说的是**游戏客户端**。`update_takeover.py` 接管的是 MaaEnd 程序自身的更新。
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from auto_mas_core import UserExpander
from auto_mas_core.adapters.script import game_update_result, point
from auto_mas_core.host.core import Publisher
from auto_mas_core.host.core_ws import protocol
from auto_mas_core.host.models_schema import WSTaskNoticeData
from auto_mas_core.host.task_client import client_executable_path
from auto_mas_core.host.task_proxy_helpers import push_dispatch_log
from auto_mas_core.host.utils import get_logger

from .config import MaaEndConfig
from .resource_loader import load_maaend_controller_protocol
from .tools.update import ensure_game_updated

logger = get_logger("终末地客户端更新")


class EndfieldUpdateExpander(UserExpander[MaaEndConfig]):
    """手动触发的一次客户端更新，不持有需要跨轮保留的资源。

    宿主的维护任务入口按 ``decl.maintenance_expander`` 构造本类，要求树里指定到
    具体账号；结论写进托管节点的调度台日志，失败只推原因本身。
    """

    async def check(self) -> str | None:
        """手动更新只认 PC 客户端（Win32 控制器），并要能定位游戏可执行文件。"""
        config = self.script_config
        root_path = config.Info.Path
        controller = str(config.Game.ControllerType or "").strip()
        if root_path is None or not controller:
            return "未选择 MaaEnd 控制器，请在托管编辑页选择控制器！"
        try:
            protocol_name = load_maaend_controller_protocol(
                Path(str(root_path)), controller
            )
        except (OSError, KeyError, ValueError) as error:
            return f"MaaEnd 控制器配置读取失败: {error}"
        if protocol_name != "Win32":
            return "手动检查更新只支持 PC 客户端（Win32 控制器），请调整控制器设置"
        exe = Path(str(client_executable_path(config) or "").strip())
        if not exe.is_file():
            return "未完成游戏配置, 请检查托管配置中的游戏设置！"
        return None

    async def main_task(self) -> None:
        """单个账号跑一轮更新；不看 Game.IfAutoUpdate，用户点下按钮即为授权。"""
        await self.script_info.set_state(status="运行")
        self._entered = True
        reason = await self.check()
        if reason:
            raise ValueError(reason)
        for user in self.script_info.users.values():
            if self.task_info.info.status == "cancelled":
                raise asyncio.CancelledError
            self.script_info.current.index = user.uid
            await self.script_info.commit()
            await self._run_update(user)

    async def _run_update(self, user) -> None:
        config = self.script_config
        game_exe = Path(str(client_executable_path(config) or "").strip())
        await user.set_state(status="运行")
        point(self, "game_update")
        try:
            result = await ensure_game_updated(
                game_exe,
                time_limit_minutes=int(config.Game.UpdateTimeLimit),
                progress=lambda line: push_dispatch_log(self.script_info, line),
                entry="手动",
            )
        except asyncio.CancelledError:
            # 取消不走 on_crash，也不落下面那三个状态：不收口这个账号就永远停在「运行」。
            point(self, "game_update", state="cancelled")
            await user.set_state(status="异常")
            raise
        except Exception:
            point(self, "game_update", state="failed")
            raise
        game_update_result(self, result)
        # 结论先落进日志再抛：toast 三秒就没了，弹窗里这一行才是留下的那份。
        await push_dispatch_log(self.script_info, result.message)
        if result.status == "Skipped":
            # Skipped 是「本轮没做这件事」，不是失败。
            await user.set_state(status="跳过")
            return
        if result.status == "NeedManualUpdate":
            raise RuntimeError(result.message)
        await user.set_state(status="完成")

    async def finish(self) -> None:
        """一次性更新任务不持有需要释放的资源；脚本配置锁归调度器。"""

    async def on_crash(self, exc: BaseException) -> None:
        logger.opt(exception=True).warning(f"终末地客户端手动更新失败: {exc}")
        with suppress(Exception):
            await Publisher.send(
                id=self.task_info.task_id,
                type=protocol.TASK_NOTICE,
                # 只推原因本身；「终末地更新失败: 」这层前缀由前端词表加。
                data=WSTaskNoticeData(
                    sourceScriptType="MaaEnd", level="error", message=f"{exc}"
                ),
            )


__all__ = ["EndfieldUpdateExpander"]
