#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#   This file is part of AUTO-MAS.
#   AUTO-MAS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of
#   the License, or (at your option) any later version.
#   AUTO-MAS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
#   the GNU Affero General Public License for more details.
#   You should have received a copy of the GNU Affero General Public License
#   along with AUTO-MAS. If not, see <https://www.gnu.org/licenses/>.
#   Contact: DLmaster_361@163.com
"""MaaEnd 专项插件声明：托管、账号、计划表、三种执行模式与 HTTP 路由聚合。

插件把宿主原来的三处注册收成一份声明：脚本/账号/计划表模型（decl）、L3 展开器
（MaaEndExpander）与自带的能力服务（MaaEndConfigService，给托管编辑页读资源与
游戏分辨率）。HTTP 端点仍写在 api.py，这里只按宿主脚本路由的前缀接入，路径保持
/api/scripts/maaend/*。
"""

from pathlib import Path
from typing import Any

from auto_mas_core import (
    Config,
    DesktopSessionCheckReason,
    ScriptAdapterPlugin,
    ScriptEntry,
    ScriptTypeDecl,
    TaskMode,
)

# 分辨率与显示模式读的是终末地 PC 客户端（Unity）写在注册表里的项。
from auto_mas_core.host.task_maafw_game_resolution import (
    read_unity_display_type,
    read_unity_resolution,
)
from fastapi import APIRouter

from .api import router as maaend_router
from .backup_api import router as backup_router
from .config import MaaEndConfig, MaaEndPlanConfig, MaaEndUserConfig
from .config_service import MaaEndConfigService
from .expander import MaaEndExpander
from .manual_update import EndfieldUpdateExpander
from .resource_loader import load_maaend_controller_protocol

# 端点仍按宿主脚本路由的绝对前缀挂载；api.py 里的路径是 /maaend/*，这里只加一次
# /api/scripts，避免两边各写一遍前缀。
router = APIRouter()
router.include_router(maaend_router, prefix="/api/scripts", tags=["脚本管理"])
# 备份恢复走插件自有前缀：宿主通用备份端点依赖宿主装配的恢复池解析器。
router.include_router(backup_router)


# 启用期持有的能力服务：端点经 config_service() 取；未启用时明确报错。
_config_service: MaaEndConfigService | None = None


def config_service() -> MaaEndConfigService:
    """取得本插件启用期持有的 MaaEnd 配置服务。"""
    if _config_service is None:
        raise RuntimeError("MaaEnd 插件尚未启用, 配置服务不可用")
    return _config_service


def desktop_session_check(
    config: ScriptEntry, elevated: bool
) -> "DesktopSessionCheckReason | None":
    """按托管实际生效的控制器协议判断能否在桌面分身里运行。

    内置实现只允许 Win32 控制器走分身，插件沿用同一口径：没填路径、没选控制器、
    读不出协议或选了 Adb 都按不支持处理。``elevated`` 参与判断的专项才需要提权，
    MaaEnd 不需要。
    """
    del elevated
    path = getattr(config.Info, "Path", None)
    controller = str(getattr(config.Game, "ControllerType", "") or "").strip()
    if path is None or not controller:
        return "unsupported_config"
    try:
        protocol = load_maaend_controller_protocol(Path(str(path)), controller)
    except (OSError, KeyError, ValueError):
        return "unsupported_config"
    return None if protocol == "Win32" else "unsupported_config"


def game_kind(script: ScriptEntry, patch: dict[str, Any]) -> str:
    """按托管当前配置或保存补丁里的控制器协议限定可绑定的游戏类型。"""
    controller = str(
        (patch.get("Game") or {}).get("ControllerType", script.Game.ControllerType)
    ).lower()
    return "emulator" if controller == "adb" else "client"


class Plugin(ScriptAdapterPlugin):
    """MaaEnd 专项插件入口。"""

    script_type_key = "MaaEnd"
    api_router = router
    decl = ScriptTypeDecl(
        script_type=MaaEndConfig,
        user_type=MaaEndUserConfig,
        expander_class=MaaEndExpander,
        plan_type=MaaEndPlanConfig,
        supported_modes=(
            TaskMode.AUTO_PROXY,
            TaskMode.SCRIPT_CONFIG,
            TaskMode.SCRIPT_VIEW,
        ),
        # 程序更新预取留在展开器：只有它知道安装目录与更新渠道。
        prefetch_check=MaaEndExpander.check_prefetch,
        # 手动「检查更新」走维护任务入口：树里指定到账号，由本展开器跑一轮客户端更新。
        maintenance_expander=EndfieldUpdateExpander,
        desktop_session_check=desktop_session_check,
        game_kind=game_kind,
        game_kinds=("emulator", "client"),
        activity_game="endfield",
    )

    def validate_update(self, data: dict[str, Any]) -> None:
        """保存托管配置前校验终末地启动器路径（宿主同步调用）。"""
        MaaEndConfigService.validate_update(data)

    async def import_config(
        self,
        script: ScriptEntry,
        target_directory: Path,
        *,
        user_id: str | None = None,
    ) -> None:
        """把 MaaEnd 安装目录里的上游配置导入到 MAS 配置目录。"""
        MaaEndConfigService.import_config(script, target_directory, user_id=user_id)

    async def initialize(self, script: ScriptEntry) -> None:
        """托管激活后迁移历史 LaunchMode 取值（Client → MaaEnd/MAS）。"""
        service = getattr(self, "_config_service", None) or config_service()
        await service.initialize(script)

    async def pre_enable(self) -> None:
        """绑定 MaaEnd 用到的关联配置集合，并保管本插件的能力服务。

        分辨率与显示模式读的是终末地 PC 客户端（Unity）的注册表项，能力归 MaaFW；
        这里经 SDK 门面取用。
        """
        # 拆出前后共用同一个类型名：宿主仍内置 MaaEnd 时拒绝启用，避免两套同名类型并存。
        builtin = Config.ScriptConfig.entry_types.get("MaaEndConfig")
        if builtin is not None and builtin.__module__.startswith("app."):
            raise RuntimeError(
                "当前 AUTO-MAS 仍内置 MaaEnd 专项，请更新至已迁移 MaaEnd 的宿主"
            )
        refs = {"PlanConfig": Config.PlanConfig, "games": Config.GameConfig}
        MaaEndConfig.related_config = refs
        MaaEndUserConfig.related_config = refs
        global _config_service
        _config_service = MaaEndConfigService(
            scripts=Config.ScriptConfig,
            read_resolution=read_unity_resolution,
            read_display_type=read_unity_display_type,
        )
        self._config_service = _config_service

    async def on_disable(self) -> None:
        """卸下本实例保管的服务引用，避免禁用后仍从模块级入口取到。"""
        global _config_service
        service = getattr(self, "_config_service", None)
        if service is not None:
            await service.aclose()
        if _config_service is service:
            _config_service = None
