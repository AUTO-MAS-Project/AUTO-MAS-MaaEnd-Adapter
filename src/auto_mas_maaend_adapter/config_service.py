#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2024-2025 DLmaster361
#   Copyright © 2025 MoeSnowyFox
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
"""MaaEnd 配置与资源操作，依赖由宿主提供的配置集合和游戏设置读取能力。"""

import asyncio
import shutil
import uuid
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from auto_mas_core import BackgroundTaskGroup
from auto_mas_core.host.config import ConfigCollection, ConfigEntry
from auto_mas_core.host.task_client import client_executable_path
from auto_mas_core.host.utils import (
    BASE_INDEPENDENT,
    BASE_SHARED,
    get_logger,
    normalize_base_source,
)
from auto_mas_core.host.utils import io as _utils_io

from .config import MaaEndConfig as RuntimeMaaEndConfig
from .resource_loader import get_loaded_maaend_options, try_load_maaend_options
from .tools import endfield_launcher as _service_endfield_launcher
from .tools.backup_archive import archive_mas_backup, read_overlay_values

logger = get_logger("MaaEnd 配置服务")

if TYPE_CHECKING:
    from .tools.log_bundle import LogBundleSelection


class DisplayTypeReader(Protocol):
    def __call__(self, exe_path: Path, *, preferred_value_name: str) -> str | None: ...


class MaaEndConfigService:
    """持有专项配置策略；模型只接收已解析的展示数据，不负责资源 IO。"""

    def __init__(
        self,
        *,
        scripts: ConfigCollection[ConfigEntry],
        read_resolution: Callable[[Path], tuple[int, int] | None],
        read_display_type: DisplayTypeReader,
    ) -> None:
        self._scripts = scripts
        self._read_resolution = read_resolution
        self._read_display_type = read_display_type
        self._pending_preloads: dict[uuid.UUID, RuntimeMaaEndConfig] = {}
        self._preloading = False
        self.panel_updates: dict[uuid.UUID, uuid.UUID] = {}

    def _get_script(self, script_id: str) -> RuntimeMaaEndConfig:
        script = self._scripts[uuid.UUID(script_id)]
        if not isinstance(script, RuntimeMaaEndConfig):
            raise TypeError("托管配置类型错误, 不是 MaaEnd 类型")
        return script

    async def initialize(self, script: ConfigEntry) -> None:
        """配置激活后迁移历史 Client 启动方式，在当前任务中提交。"""
        if not isinstance(script, RuntimeMaaEndConfig):
            return
        if script.Game.LaunchMode != "Client" or script.Info.Path is None:
            return
        root = script.Info.Path
        if not (root / "interface.json").is_file():
            return
        options = await asyncio.to_thread(try_load_maaend_options, root)
        if options is not None:
            script.Game.LaunchMode = (
                "MaaEnd"
                if script.Game.ControllerType in options["launchGameControllers"]
                else "MAS"
            )
            await script.commit()

    def schedule_preload(
        self, script: ConfigEntry, *, background_tasks: BackgroundTaskGroup
    ) -> None:
        """托管激活后调度资源预热，由插件的任务组在停用时结束。"""
        if not isinstance(script, RuntimeMaaEndConfig) or script.Info.Path is None:
            return
        self._pending_preloads[script.uid] = script
        if not self._preloading:
            self._preloading = (
                background_tasks.spawn(
                    partial(self._preload_resources, background_tasks),
                    retain_result=False,
                )
                is not None
            )

    async def _preload_resources(self, background_tasks: BackgroundTaskGroup) -> None:
        """逐个填充账号的资源缓存，避免托管多时耗尽后台任务组容量。"""
        try:
            while self._pending_preloads:
                uid = next(iter(self._pending_preloads))
                script = self._pending_preloads.pop(uid)
                root = script.Info.Path
                if root is None:
                    continue
                try:
                    resource = await background_tasks.run_sync(
                        partial(try_load_maaend_options, root)
                    )
                    if (
                        resource is not None
                        and self._scripts.get(uid) is script
                        and script.Info.Path == root
                    ):
                        for user in script.users.values():
                            user.cache_maaend_resource(
                                resource, script.Game.ControllerType
                            )
                except Exception:
                    logger.opt(exception=True).warning("MaaEnd 资源预加载失败，已跳过")
        finally:
            self._preloading = False

    async def get_options(self, script_id: str) -> dict[str, Any]:
        """读取安装资源，并补充游戏保存的分辨率与显示模式。"""
        script = self._get_script(script_id)
        root_path = str(script.Info.Path or "").strip()
        if not root_path:
            raise ValueError("MaaEnd 路径未配置")
        options = await asyncio.to_thread(get_loaded_maaend_options, Path(root_path))
        for user in script.users.values():
            user.cache_maaend_resource(options, script.Game.ControllerType)
        game_path = str(client_executable_path(script) or "").strip()
        if game_path:
            exe_path = Path(game_path)
            original = await asyncio.to_thread(self._read_resolution, exe_path)
            if original is not None:
                options["originalResolution"] = f"{original[0]}x{original[1]}"
            options["originalDisplayType"] = await asyncio.to_thread(
                self._read_display_type,
                exe_path,
                preferred_value_name="video_full_screen_h1998742411",
            )
        return options

    # 下面两个回调来自宿主脚本配置契约（保存前校验、从脚本目录导入配置）。
    # 插件的 ScriptTypeDecl 还没有对应声明位，宿主目前只认内置专项的 handler，
    # 因此它们暂时没有调用点；宿主补齐声明位后接上，不要当死代码删掉。
    @staticmethod
    def validate_update(data: dict[str, Any]) -> None:
        launcher_path = (data.get("Game") or {}).get("LauncherPath")
        if launcher_path and not _service_endfield_launcher.is_launcher_exe(
            Path(launcher_path)
        ):
            raise ValueError(
                "终末地启动器路径无效，请选择鹰角官方启动器 Launcher.exe 或 Games.exe"
            )

    @staticmethod
    def import_config(
        script: ConfigEntry,
        target_directory: Path,
        *,
        user_id: str | None = None,
    ) -> None:
        """按原目录完整透传上游配置，不解释私有格式。"""
        if not isinstance(script, RuntimeMaaEndConfig):
            raise TypeError("托管配置类型错误, 不是 MaaEnd 类型")
        if script.Info.Path is None:
            raise ValueError("Path未配置，请检查路径设置")
        source_directory = script.Info.Path / "config"
        if not (source_directory / "mxu-MaaEnd.json").exists():
            raise FileNotFoundError(
                "MaaEnd 配置文件不存在, 请检查 MaaEnd 路径设置或先启动 MaaEnd 完成配置文件生成"
            )
        owner = user_id or "Default"
        base = BASE_SHARED if owner == "Default" else BASE_INDEPENDENT
        # 共享导入没有单一账号，按所有受影响用户归桶，让各自恢复页都能找到旧设置。
        archive_users: list[tuple[str, ConfigEntry | None]] = [
            (str(uid), user)
            for uid, user in script.users.items()
            if str(uid) == owner
            or (
                owner == "Default"
                and normalize_base_source(user.Info.Base) == BASE_SHARED
            )
        ]
        for archive_user_id, user in archive_users or [(owner, None)]:
            try:
                archive_mas_backup(
                    script_id=str(script.uid),
                    user_id=archive_user_id,
                    mas_dir=target_directory,
                    overlay=read_overlay_values(user) if user is not None else None,
                    force=True,
                    base=base,
                )
            except Exception:
                logger.opt(exception=True).warning(
                    "MaaEnd 导入前 MAS 配置归档失败，已跳过（不阻断导入）"
                )
        # 只读文件也须清理，避免残留内容导致覆盖失败。
        _utils_io.force_rmtree(target_directory)
        target_directory.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_directory, target_directory, dirs_exist_ok=True)

    def resolve_launcher_path(self, script_id: str) -> Path:
        script = self._get_script(script_id)
        client_exe = Path(str(client_executable_path(script) or "").strip())
        if not client_exe.is_file():
            raise ValueError("请先选择终末地客户端 Endfield.exe，再自动识别启动器")
        launcher_path = _service_endfield_launcher.discover_launcher_exe(client_exe)
        if launcher_path is None:
            raise ValueError(
                "未能从游戏客户端路径识别到终末地官方启动器, "
                "请手动选择终末地启动器的可执行文件（.exe）"
            )
        return launcher_path

    async def resolve_log_bundle(
        self, *, output_directory: Path | None = None
    ) -> "LogBundleSelection":
        """筛选 MaaEnd 安装配置，再查询已有归档或保存当前日志。"""
        from .tools.log_bundle import resolve_log_bundles

        scripts = [
            script
            for script in self._scripts.values()
            if isinstance(script, RuntimeMaaEndConfig)
        ]
        return await resolve_log_bundles(scripts, output_directory)
