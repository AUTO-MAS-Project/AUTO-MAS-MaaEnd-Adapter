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

"""MaaEnd 托管配置，保留原字段名并暴露插件用户集合。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path as NativePath
from typing import Annotated, ClassVar, Literal

from auto_mas_core import ScriptEntry
from auto_mas_core.host.config import (
    ConfigCollection,
    ConfigGroup,
    Virtual,
    collection,
    encrypted,
    virtual_field,
)
from auto_mas_core.host.config_types import (
    STANDARD_BLOCKED_DIRS,
    CliArgumentString,
    FilePath,
    FolderPath,
    path_policy,
)
from auto_mas_core.host.models_config_shared import none_as
from pydantic import Field

from .user import MaaEndUserConfig

MaaEndInstallPath = Annotated[
    NativePath | None, path_policy(kind="folder", blocked_dirs=STANDARD_BLOCKED_DIRS)
]
"""保留更新中断时暂缺的安装路径，供恢复入口定位相邻的原安装备份。"""


class MaaEndConfig(ScriptEntry):
    related_config: ClassVar = {}

    class GameFields(ConfigGroup):
        LaunchMode: Literal["Client", "Launcher", "MAS", "MaaEnd"] = Field(
            default="Launcher", description="游戏启动方式，Client 为历史迁移值"
        )

        Arguments: CliArgumentString = Field(
            default_factory=lambda: "", description="终末地游戏启动参数"
        )

        CloseOnFinish: bool = Field(
            default_factory=lambda: True, description="结束后是否关闭游戏"
        )

        ControllerType: str = Field(
            default_factory=lambda: "", description="控制器类型"
        )

        IfAutoUpdate: bool = Field(
            default_factory=lambda: False,
            description="是否在任务启动前检查并自动更新终末地 PC 客户端",
        )

        LauncherPath: FilePath = Field(
            default_factory=lambda: None,
            description="鹰角官方启动器路径（Launcher.exe 或 Games.exe）",
        )

        Path: FilePath = Field(
            default_factory=lambda: None, description="终末地游戏路径"
        )

        RestoreDisplayType: Literal["Window", "Fullscreen"] = Field(
            default_factory=lambda: "Window",
            description="关闭游戏时恢复的显示模式，与具体分辨率独立配置",
        )

        RestoreResolution: Literal[
            "Off", "Original", "1920x1080", "2560x1440", "3840x2160", "Custom"
        ] = Field(
            default_factory=lambda: "Off",
            description="关闭游戏时恢复分辨率；Original 复用启动前读取的注册表值",
        )

        RestoreResolutionHeight: Annotated[int, Field(ge=1, le=16384)] = Field(
            default_factory=lambda: 1080,
            description="自定义恢复分辨率高度",
        )

        RestoreResolutionWidth: Annotated[int, Field(ge=1, le=16384)] = Field(
            default_factory=lambda: 1920,
            description="自定义恢复分辨率宽度",
        )

        RestoreAutoHDR: Literal["Unchanged", "Disable", "Enable"] = Field(
            default_factory=lambda: "Unchanged",
            description="关闭游戏时的自动 HDR 设置",
        )

        AutoHDR: Literal["Unchanged", "Disable", "Enable"] = Field(
            default_factory=lambda: "Unchanged",
            description="MaaEnd 启动时的自动 HDR 设置",
        )

        SetResolution: bool = Field(
            default_factory=lambda: False,
            description="是否在启动游戏时执行 MaaEnd 分辨率设置预任务",
        )

        UpdateTimeLimit: Annotated[int, Field(ge=1, le=9999)] = Field(
            default_factory=lambda: 240,
            description="游戏客户端更新时长限制（分钟）",
        )

        WaitTime: Annotated[int, Field(ge=60, le=9999), none_as(60)] = Field(
            default_factory=lambda: 60, description="等待时间（秒）"
        )

    Game: GameFields = Field(default_factory=GameFields)

    class InfoFields(ConfigGroup):
        Name: str = Field(
            default_factory=lambda: "新 MaaEnd 托管", description="MaaEnd 托管名称"
        )

        # 目录切换中断时路径可能暂时不存在，必须保留以便运行前恢复原安装。
        Path: MaaEndInstallPath = Field(
            default_factory=lambda: None, description="MaaEnd 路径"
        )

    Info: InfoFields = Field(default_factory=InfoFields)

    class RunFields(ConfigGroup):
        AccountSwitchMethod: Literal["MAS", "MAAEND"] = Field(
            default_factory=lambda: "MAAEND",
            description="账号切换方式（默认使用 MAAEND，MAS 为兼容入口）",
        )

        HardTimeLimit: Annotated[int, Field(ge=1, le=9999), none_as(1)] = Field(
            default_factory=lambda: 120,
            description="单账号运行总时限（分钟），包含等待和全部重试",
        )

        IfSaveLogBundle: bool = Field(
            default_factory=lambda: False,
            description="任务失败时是否按 MaaEnd 的导出规则打包运行日志",
        )

        LogBundlePath: FolderPath = Field(
            default_factory=lambda: None,
            description="任务失败时保存日志包的目录，留空使用 MAS 目录下的 debug/maaend",
        )

        ProxyTimesLimit: Annotated[int, Field(ge=0, le=9999), none_as(0)] = Field(
            default_factory=lambda: 0, description="每日代理次数限制"
        )

        RunTimeLimit: Annotated[int, Field(ge=1, le=9999), none_as(1)] = Field(
            default_factory=lambda: 10, description="运行超时阈值"
        )

        RunTimesLimit: Annotated[int, Field(ge=1, le=9999), none_as(1)] = Field(
            default_factory=lambda: 3, description="运行次数限制"
        )

        TaskTransitionMethod: Literal["NoAction", "ExitGame"] = Field(
            default_factory=lambda: "NoAction", description="任务切换方式"
        )

    Run: RunFields = Field(default_factory=RunFields)
    class UpdateFields(ConfigGroup):
        TakeoverEnabled: bool = Field(
            default_factory=lambda: False,
            description="运行前由 MAS 下载、校验并安装 MaaEnd 官方完整包；不暂停 MXU 自身的更新检查",
        )
        PackageMode: Literal["full", "incremental"] = Field(
            default="full",
            description="全量或优先增量；增量有风险，无可信缓存、匹配增量包或校验失败时回退全量",
        )
        Channel: Literal["stable", "beta"] = Field(
            default_factory=lambda: "stable", description="MaaEnd 更新通道"
        )
        MirrorChyanCDK: Annotated[str, encrypted()] = Field(
            default_factory=lambda: "",
            description="MaaEnd Mirror 酱 CDK，留空使用全局 CDK，无 CDK 使用 GitHub",
        )

    Update: UpdateFields = Field(default_factory=UpdateFields)

    @classmethod
    def normalize_payload(cls, data):
        data = deepcopy(data)
        if "UserData" in data:
            data["users"] = data.pop("UserData")
        sub = data.get("SubConfigsInfo")
        if isinstance(sub, dict) and "UserData" in sub:
            sub["users"] = sub.pop("UserData")
        run_data = data.get("Run")
        if isinstance(run_data, dict):
            run_data.pop("ExecutionSession", None)
        game_data = data.get("Game") if isinstance(data, dict) else None
        migrated = (
            isinstance(game_data, dict)
            and game_data.get("RestoreResolution") == "Fullscreen"
        )
        if migrated and isinstance(game_data, dict):
            game_data["RestoreDisplayType"] = "Fullscreen"
            game_data["RestoreResolution"] = "1920x1080"
        return data


    async def _activate_from_payload(self, payload, *, regenerate_uuids=False):
        """先迁移历史载荷，再交给配置框架激活节点与嵌套集合。"""
        await super()._activate_from_payload(
            type(self).normalize_payload(payload), regenerate_uuids=regenerate_uuids
        )
    users: ConfigCollection[MaaEndUserConfig] = collection(MaaEndUserConfig)

    class Metadata(ScriptEntry.Info):
        name: Virtual[str] = None  # pyright: ignore[reportIncompatibleVariableOverride]

    info: Metadata = Field(default_factory=Metadata)  # pyright: ignore[reportIncompatibleVariableOverride]

    @virtual_field("info.name")
    def plugin_name(self):
        return self.Info.Name
