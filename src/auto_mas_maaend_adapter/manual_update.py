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
from pathlib import Path

from auto_mas_core import ScriptConfigWorker, TaskUserItem, UserEntry, UserExpander
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
    """沿用维护入口派发托管级客户端更新，由宿主建立并保护默认更新节点。"""

    def build_worker(
        self, user: TaskUserItem, config: UserEntry | None
    ) -> ScriptConfigWorker:
        return EndfieldUpdateWorker(expander=self, user=user, config=config)


class EndfieldUpdateWorker(ScriptConfigWorker):
    """在默认节点执行一次更新，保留调度台结论和手动停止结果。"""

    def __init__(
        self,
        expander: EndfieldUpdateExpander,
        user: TaskUserItem,
        config: UserEntry | None,
    ) -> None:
        super().__init__(expander=expander, user=user, config=config)
        self.script_config = expander.script_config
        self.game_exe: Path | None = None

    async def check(self) -> str | None:
        """确认已配置 MaaEnd 安装目录、PC 控制器及绑定的游戏客户端。"""
        config = self.script_config
        root_path = config.Info.Path
        if root_path is None or not (root_path / "MaaEnd.exe").exists():
            return (
                "确认控制器类型需要读取 MaaEnd 本体，请先在脚本里配好 MaaEnd 路径"
                "（未找到 MaaEnd.exe），再来检查终末地客户端更新！"
            )
        controller = str(config.Game.ControllerType or "").strip()
        if not controller:
            return "未选择 MaaEnd 控制器，请在托管编辑页选择控制器！"
        try:
            protocol_name = await asyncio.to_thread(
                load_maaend_controller_protocol, root_path, controller
            )
        except (OSError, KeyError, ValueError) as error:
            return f"MaaEnd 控制器配置读取失败: {error}"
        if protocol_name != "Win32":
            return "终末地客户端更新仅支持 PC 控制器, 请检查托管配置中的控制器设置！"
        exe = client_executable_path(config)
        if exe is None or not exe.is_file():
            return "未完成游戏配置, 请检查托管配置中的游戏设置！"
        self.game_exe = exe
        return None

    async def main_logic(self) -> None:
        """用户点击按钮即为授权，Game.IfAutoUpdate 只控制自动更新。"""
        assert self.game_exe is not None
        point(self, "game_update")
        try:
            result = await ensure_game_updated(
                self.game_exe,
                time_limit_minutes=int(self.script_config.Game.UpdateTimeLimit),
                progress=lambda line: push_dispatch_log(self.script_info, line),
                entry="手动",
            )
        except asyncio.CancelledError:
            point(self, "game_update", state="cancelled")
            raise
        except Exception:
            point(self, "game_update", state="failed")
            raise
        game_update_result(self, result)
        if result.status == "NeedManualUpdate":
            # 失败和其他异常都走 on_crash，原因只向调度台追加一次。
            raise RuntimeError(result.message)
        await push_dispatch_log(self.script_info, result.message)
        await self.user_info.set_state(
            status="跳过" if result.status == "Skipped" else "完成"
        )

    async def final_task(self) -> None:
        if self.cancelled:
            # 沿用旧手动更新的节点终态，任务根仍由调度器标为已取消。
            await self.user_info.set_state(status="异常")
            return
        await super().final_task()

    async def on_crash(self, exc: BaseException) -> None:
        await super().on_crash(exc)
        try:
            # 结论留在调度台；弹窗提示消失后仍能看到之前的进度和失败原因。
            await push_dispatch_log(self.script_info, str(exc))
        except Exception:
            logger.opt(exception=True).warning("无法记录终末地手动更新的失败原因")
        try:
            await Publisher.send(
                id=self.task_info.task_id,
                type=protocol.TASK_NOTICE,
                # 只推原因本身；「终末地更新失败: 」这层前缀由前端词表加。
                data=WSTaskNoticeData(
                    sourceScriptType="MaaEnd", level="error", message=str(exc)
                ),
            )
        except Exception:
            logger.opt(exception=True).warning("无法发送终末地手动更新失败提示")


__all__ = ["EndfieldUpdateExpander"]
