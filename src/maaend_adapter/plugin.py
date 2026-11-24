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

from auto_mas_core import Config, ScriptAdapterPlugin, ScriptTypeDecl, TaskMode
from fastapi import APIRouter

from .api import router as maaend_router

# TODO(插件化)：分辨率与显示模式读的是终末地 PC 客户端（Unity）写在注册表里的项。
# auto-mas-maafw-interface / native 目前没有导出这两个函数，暂经 compat 转发；MaaFW 适配器
# 或对应库提供能力后删除 compat 文件。
from .compat.maafw_game_resolution import read_unity_display_type, read_unity_resolution
from .config import MaaEndConfig, MaaEndPlanConfig, MaaEndUserConfig
from .config_service import MaaEndConfigService
from .expander import MaaEndExpander

# 端点仍按宿主脚本路由的绝对前缀挂载；api.py 里的路径是 /maaend/*，这里只加一次
# /api/scripts，避免两边各写一遍前缀。
router = APIRouter()
router.include_router(maaend_router, prefix="/api/scripts", tags=["脚本管理"])


# 启用期持有的能力服务：端点经 config_service() 取；未启用时明确报错。
_config_service: MaaEndConfigService | None = None


def config_service() -> MaaEndConfigService:
    """取得本插件启用期持有的 MaaEnd 配置服务。"""
    if _config_service is None:
        raise RuntimeError("MaaEnd 插件尚未启用, 配置服务不可用")
    return _config_service


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
        game_kinds=("emulator", "client"),
        activity_game="endfield",
    )

    async def pre_enable(self) -> None:
        """绑定 MaaEnd 用到的关联配置集合，并保管本插件的能力服务。

        分辨率与显示模式读的是终末地 PC 客户端（Unity）的注册表项，能力归 MaaFW；
        这里经 SDK 门面取用。
        """
        # 拆出前后共用同一个类型名：宿主仍内置 MaaEnd 时拒绝启用，避免两套同名类型并存。
        builtin = Config.ScriptConfig.entry_types.get("MaaEndConfig")
        if builtin is not None and builtin.__module__.startswith("app."):
            raise RuntimeError("当前 AUTO-MAS 仍内置 MaaEnd 专项，请更新至已迁移 MaaEnd 的宿主")
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
        if _config_service is getattr(self, "_config_service", None):
            _config_service = None
