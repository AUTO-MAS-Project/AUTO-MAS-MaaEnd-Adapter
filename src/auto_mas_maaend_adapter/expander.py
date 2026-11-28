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
"""MaaEnd 托管级展开器：在 L2 已锁的托管配置里准备安装与原生配置，逐账号派发执行器。

TODO(插件化)：手动「检查更新」（旧 execution_mode == "Update" 分支、EndfieldUpdateTask）
在插件 L3 不再可达——宿主 TaskManager.start_maintenance 只走旧 manager 维护链，插件挂载时
没有对应入口，因此本模块不再派发该任务。待宿主提供标准维护任务入口后接回。
"""

import asyncio
from contextlib import ExitStack, suppress
from datetime import datetime
from functools import partial
from pathlib import Path
from time import time_ns

from auto_mas_core import TaskMode, UserExpander
from auto_mas_core.adapters.script import game_update_result, point
from auto_mas_core.devices.task import game_device_id, game_target_id
from auto_mas_core.host import core_notify_report as _node_report
from auto_mas_core.host.config import ConfigCollection, config_manager
from auto_mas_core.host.core import Config, GameMaintenance, Notify, Publisher
from auto_mas_core.host.core_notify_task_content import (
    push_maintenance_notice,
    screenshot_entries,
)
from auto_mas_core.host.core_script_update import (
    ScriptUpdateRequest,
    auto_recover_script_install,
    run_script_update,
)
from auto_mas_core.host.core_ws import protocol
from auto_mas_core.host.models_notification_report import (
    TaskResultReport,
    UserReportText,
)
from auto_mas_core.host.models_schema import DownloadRequest, WSTaskNoticeData
from auto_mas_core.host.services import script_install
from auto_mas_core.host.task_client import client_executable_path, client_launcher_path
from auto_mas_core.host.task_emulator_core import close_emulator
from auto_mas_core.host.task_maintenance import get_user_maintenance
from auto_mas_core.host.task_proxy_helpers import push_dispatch_log
from auto_mas_core.host.utils import (
    BASE_NATIVE,
    BASE_SOURCE_LABELS,
    LOG_TYPE_ERROR,
    TASK_MODE_ZH,
    get_logger,
    log_box,
)
from auto_mas_core.host.utils import io as _utils_io
from auto_mas_core.host.utils_common_fluxdown_cli import FluxdownCancelUnconfirmed

from . import notifications as _format_maaend
from .auto_proxy import AutoProxyTask
from .config import MaaEndConfig, MaaEndUserConfig
from .config_session import ScriptConfigTask, ScriptViewTask, maaend_config_base
from .resource_loader import MaaEndResourceLoader, load_maaend_controller_protocol
from .tools import endfield_launcher as _service_endfield_launcher
from .tools import script_update
from .tools.backup_archive import archive_native_backup
from .tools.managed_recovery import MaaEndInstallAdapter
from .tools.update import ensure_game_updated

logger = get_logger("MaaEnd 调度器")

_SUPPORTED_MODES = (
    TaskMode.AUTO_PROXY,
    TaskMode.SCRIPT_CONFIG,
    TaskMode.SCRIPT_VIEW,
)
"""本专项能派发执行器的任务模式；其余模式由宿主其它入口处理。"""


class MaaEndExpander(UserExpander[MaaEndConfig]):
    """MaaEnd 控制器"""

    # 全部账号因维护跳过时不占用游戏，也不进入安装恢复、更新或配置备份。
    defer_game_session = True
    maintenance_message = "终末地正在维护"

    def maintenance_game(self, user_config: MaaEndUserConfig) -> str | None:
        """按账号服务器声明宿主维护公告对应的游戏键，不支持的服务器不参与维护判断。"""
        if isinstance(user_config, MaaEndUserConfig) and user_config.Info.Resource in {
            "官服",
            "CN",
        }:
            return "endfield"
        return None

    def __init__(self, script, config):
        """绑定 L3 上下文并初始化安装访问、原生配置快照、更新准备与报告汇总状态。"""
        super().__init__(script, config)
        self.user_config: ConfigCollection[MaaEndUserConfig] = config.users

        self.controller_protocol = ""
        self.maaend_config_dir: Path | None = None
        self.temp_path: Path | None = None
        self.had_original_script_config = False
        self.prepared = False
        self.has_proxy_run = False
        self._keep_last_game = False
        self.error_image_start_ns: int | None = None
        self.error_screenshot_paths: list[Path] = []
        self._install_access = ExitStack()
        self._program_update_prepared = False
        self._update_candidate: script_update.PreparedUpdate | str | None = None
        # 本轮被维护时段挡下的账号；全部账号都在维护期时报告改成维护提示。
        self._maintenance_skipped: set[str] = set()
        self._maintenance_until: dict[str, datetime] = {}
        self._maintenance_only = False
        # 配置/查看会话要留到 finish() 再决定是否保留 GUI 写回，这里记住最后跑的那个。
        self._active_config_task = None
        # 本轮跑过的自动代理执行器，按账号运行节点索引，收尾报告从它们取节点详情。
        self._proxy_tasks: dict = {}

    @staticmethod
    async def check_prefetch(config) -> list:
        """在允许接管更新且已配置安装目录时检查更新候选，返回文件身份和适用渠道的下载请求。"""
        if (
            not config.Update.TakeoverEnabled
            or config.Info.Path is None
            or config.Update.PackageMode == "incremental"
        ):
            return []
        candidate = await script_update.check_update(config.Info.Path, config)
        if isinstance(candidate, str):
            return []
        return [
            DownloadRequest(
                url=candidate.url,
                content_hash=candidate.digest or None,
                downloader="builtin" if candidate.source == "MirrorChyan" else None,
            )
        ]

    async def prefetch_script_update(self) -> None:
        """在托管锁内准备一次 MaaEnd 程序更新，供随后运行直接安装。"""
        config = self.script_config
        if config.Update.TakeoverEnabled and config.Info.Path is not None:
            self._update_candidate = await script_update.prepare_update(
                config.Info.Path, config
            )

    async def discard_prefetched_update(self) -> None:
        """丢弃尚未消费的预取更新，释放它占用的下载产物。"""
        candidate, self._update_candidate = self._update_candidate, None
        if candidate is not None:
            script_update.discard_update(candidate)

    def can_run_user(self, entry) -> bool:
        """在账号锁内保留 MaaEnd 的到期限制，配置与查看会话不受限制。"""
        return super().can_run_user(entry) and (
            self.task_info.mode != TaskMode.AUTO_PROXY
            or not isinstance(entry, MaaEndUserConfig)
            or entry.Info.RemainedDay != 0
        )

    async def main_task(self) -> None:
        """全部可用账号在维护期时，直接记跳过并保留安装和设备现场。"""
        if (
            self.task_info.mode == TaskMode.AUTO_PROXY
            and await self._skip_all_in_maintenance()
        ):
            return
        await super().main_task()

    async def _skip_all_in_maintenance(self) -> bool:
        users = []
        windows = {}
        for user in self.script_info.users.values():
            config = self.resolve_user(user)
            if not isinstance(config, MaaEndUserConfig):
                return False
            users.append((user, config))
            game = self.maintenance_game(config)
            if game is not None and game not in windows and self.can_run_user(config):
                windows[game] = await self._maintenance_window(config)

        runnable = []
        for user, config in users:
            if self.resolve_user(user) is not config:
                return False
            if self.can_run_user(config):
                window = windows.get(self.maintenance_game(config))
                if window is None:
                    return False
                runnable.append((user, window))
        if not runnable:
            return False

        for user, window in runnable:
            await self._skip_maintenance(user, window)
        for user, _ in users:
            if user.info.user_id not in self._maintenance_skipped:
                await self.record_user_state(
                    user, status="跳过", reason="用户已禁用或剩余天数不足"
                )
        self._maintenance_only = True
        await self.notify_maintenance()
        return True

    async def check(self) -> str | None:
        """恢复旧安装与原生配置，再校验程序和游戏／模拟器配置。"""
        mode = self.task_info.mode
        if mode not in _SUPPORTED_MODES:
            return "不支持的任务模式, 请检查任务配置！"

        script_config = self.script_config
        if not isinstance(script_config, MaaEndConfig):
            return "托管配置类型错误, 不是 MaaEnd 托管类型"

        root_path = script_config.Info.Path
        if root_path is None:
            return "MaaEnd.exe文件不存在, 请检查MaaEnd路径设置！"

        # 安装访问锁要一直持有到收尾：同一目录不能被两个任务同时改写或恢复。
        self._install_access.enter_context(
            script_install.installation_access(root_path)
        )
        self.maaend_config_dir = root_path / "config"
        self.temp_path = Path.cwd() / f"data/{self.script_info.info.script_id}/Temp"
        # 安装事务可能移走了程序或资源；必须恢复之后才能据这些文件决定能否运行。
        await self._recover_install_transactions(root_path, script_config)

        if not (root_path / "MaaEnd.exe").exists():
            return "MaaEnd.exe文件不存在, 请检查MaaEnd路径设置！"

        controller_name = str(script_config.Game.ControllerType or "").strip()
        if not controller_name:
            return "未选择 MaaEnd 控制器，请在托管编辑页选择控制器！"

        try:
            self.controller_protocol = load_maaend_controller_protocol(
                root_path, controller_name
            )
        except (OSError, KeyError, ValueError) as error:
            return f"MaaEnd 控制器配置读取失败: {error}"

        if self.controller_protocol == "Adb" and (
            game_target_id(script_config) == "-"
            or game_device_id(script_config) in ["", "-"]
        ):
            return "未完成模拟器配置, 请检查托管配置中的模拟器设置！"
        if self.controller_protocol == "Win32" and (
            not client_executable_path(script_config)
            or not client_executable_path(script_config).exists()
        ):
            # 与内置实现一致：绑定的游戏目标不是本地客户端时单独提示，别混成“未完成配置”。
            target = Config.GameConfig.get(game_target_id(script_config))
            if (
                client_executable_path(script_config) is None
                and target is not None
                and target.info.type != "client"
            ):
                return "所绑定的游戏目标不是本地游戏客户端，请在托管配置中更换游戏目标"
            return "未完成游戏配置, 请检查托管配置中的游戏设置！"

        if self.controller_protocol == "Win32" and mode == TaskMode.AUTO_PROXY:
            loader = MaaEndResourceLoader.get_loaded(root_path)
            launch_mode = loader.resolve_launch_mode(
                script_config.Game.LaunchMode, controller_name
            )
            if launch_mode == "MaaEnd":
                if controller_name not in loader.pretask_controllers("LaunchGamePC"):
                    return (
                        "当前 MaaEnd 或控制器不支持「MaaEnd 启动」，"
                        "请选择启动器启动或 MAS 启动"
                    )
                if client_launcher_path(script_config):
                    try:
                        _service_endfield_launcher.resolve_launcher_exe(
                            Path(str(client_executable_path(script_config))),
                            str(client_launcher_path(script_config)),
                        )
                    except ValueError as error:
                        return str(error)
            else:
                # MAS 两种启动方式需要有效启动器；原生模式由 MaaEnd 自行定位。
                client_exe = Path(
                    str(client_executable_path(script_config) or "").strip()
                )
                try:
                    launcher = _service_endfield_launcher.resolve_launcher_exe(
                        client_exe, str(client_launcher_path(script_config) or "")
                    )
                except ValueError as error:
                    return str(error)
                if launcher is None:
                    return (
                        "未找到终末地官方启动器, 请选择鹰角官方启动器 "
                        "Launcher.exe 或 Games.exe！"
                    )

        if (
            mode == TaskMode.AUTO_PROXY
            and not (root_path / "config/mxu-MaaEnd.json").exists()
        ):
            return (
                "MaaEnd 配置文件不存在, 请检查 MaaEnd 路径设置"
                "或先启动 MaaEnd 完成配置文件生成！"
            )

        return None

    async def prepare(self) -> None:
        """选定游戏会话，快照归档原生配置，再接管终末地客户端更新。"""
        await self.select_game_session()

        # 与旧实现一致：开始时间在检查通过、进入准备阶段时取，不把等锁与检查算进去。
        self.begin_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # 通知收图使用未取整的时间，避免带入同一秒内上一轮留下的截图。
        self.error_image_start_ns = time_ns()

        assert self.temp_path is not None and self.maaend_config_dir is not None

        if _utils_io.commit_native_config_snapshot(
            self.temp_path,
            self.maaend_config_dir,
            script_id=self.script_info.info.script_id,
        ):
            self.had_original_script_config = True

        # 任务级一次性归档 MaaEnd 原生配置（项目级池，指纹去重，失败不阻断
        # 任务）：原生配置物理上跨账号共享，只代表「本轮任务动手前」的安装
        # 现场，必须在任何下发前归档这一次
        if self.maaend_config_dir.exists():
            with suppress(Exception):
                archive_native_backup(self.maaend_config_dir)

        logger.success(f"{self.script_info.info.script_id}已锁定, MAAEnd配置提取完成")
        self.prepared = True

        failure = await self._prepare_game_update()
        if failure is not None:
            raise RuntimeError(failure)

    async def _recover_install_transactions(
        self, root_path: Path, script_config: MaaEndConfig
    ) -> None:
        """结算上次未完成的 MaaEnd 原生安装事务，并决定本轮是否接管程序更新。"""
        workspace = script_install.workspace(root_path)
        if (workspace / "runtime-interface.json").exists():
            await asyncio.to_thread(script_update.assert_idle, root_path)
            script_update.recover_runtime_interface(root_path)

        journal = workspace / "transaction.json"
        if journal.is_symlink():
            raise script_install.InstallUnsafeError("MaaEnd 原生事务路径不安全")

        takeover = (
            self.task_info.mode == TaskMode.AUTO_PROXY
            and script_config.Update.TakeoverEnabled
        )
        adapter = MaaEndInstallAdapter(
            root_path,
            script_config,
            takeover_enabled=script_config.Update.TakeoverEnabled,
            allow_damaged_repair=takeover,
        )
        request = ScriptUpdateRequest(str(self.script_info.info.script_id), "MaaEnd")
        recovered_automatically = False

        try:
            # 原生事务恢复不能以旧 MAS 收据校验作为前置门槛；
            # MXU 独立更新后的收据可能旧，但本体仍可正确修复。
            await adapter.recover_native()
        except script_install.InstallUnsafeError:
            if not journal.is_file():
                raise

        if journal.is_file():
            # 只有无可回滚目录、原生安装完整且身份可信时，公共层
            # 才允许清理过期 journal；否则重新尝试原生恢复。
            outcome = await auto_recover_script_install(
                request,
                install_root=root_path,
                inspect=adapter.inspect,
                acknowledge=adapter.acknowledge,
                reinstall=adapter.retry_native,
            )
            if outcome not in {"verified", "reinstalled"}:
                raise script_install.InstallUnsafeError(
                    "MaaEnd 原生事务未完成，拒绝启动"
                )
            await self.script_info.set_log(f"MaaEnd 原生事务自动恢复：{outcome}")
            recovered_automatically = True

        # 关闭接管或配置会话不主动覆盖用户自行维护的 MaaEnd。
        # 仅在已开启托管且存在可信安装身份时才自动修复损坏的发行包。
        identity = script_install.record_path(root_path, "program-identity.json")
        if takeover and identity.is_file() and not identity.is_symlink():
            state = await adapter.inspect()
            if not state.healthy:
                if state.pending:
                    raise script_install.InstallUnsafeError(
                        "MaaEnd 尚有未完成原生事务，不能重新安装"
                    )
                outcome = await auto_recover_script_install(
                    request,
                    install_root=root_path,
                    inspect=adapter.inspect_repair,
                    acknowledge=adapter.acknowledge,
                    reinstall=adapter.repair_program,
                )
                if outcome != "reinstalled":
                    raise script_install.InstallUnsafeError(
                        "MaaEnd 完整包自动修复尚未确认成功"
                    )
                await self.script_info.set_log(f"MaaEnd 官方完整包自动修复：{outcome}")
                recovered_automatically = True

        if (
            not takeover
            and script_install.record_path(root_path, "installed.json").exists()
        ):
            # 非接管模式沿用 MXU 自行更新的安装。恢复事务仍须完成，
            # 但旧 MAS 回执不应阻断后续配置或运行，也不重算哈希冒充可信。
            await script_update.confirm_current_install(root_path, verify_receipt=False)

        # 上次中断的快照要在程序更新或读取原生配置之前恢复，否则唯一的原始
        # 配置可能被更新覆盖或被当作缺失。当前任务的快照稍后在 prepare() 建立。
        self._recover_previous_run()
        if takeover:
            # 修复在原有资源预检之前，损坏的旧资源不能堵死恢复入口。
            if recovered_automatically:
                await self._refresh_after_program_install(root_path)
                self._program_update_prepared = True
            else:
                await self._prepare_script_update(root_path)

    async def _prepare_script_update(self, root: Path) -> None:
        """按接管开关准备一次 MaaEnd 程序更新，失败时沿用当前安装继续任务。"""
        if self._program_update_prepared:
            return
        if (
            self.task_info.mode != TaskMode.AUTO_PROXY
            or not self.script_config.Update.TakeoverEnabled
        ):
            return
        await push_dispatch_log(self.script_info, "正在检查 MaaEnd 程序更新…")
        point(self, "script_update")

        async def progress(downloaded: int, total: int, speed: float) -> None:
            await self.script_info.set_log(
                f"MaaEnd 更新下载：{downloaded / 1024**2:.1f} / {total / 1024**2:.1f} MB"
            )

        try:
            request = ScriptUpdateRequest(
                str(self.script_info.info.script_id), "MaaEnd"
            )
            if self._update_candidate is not None and not isinstance(
                self._update_candidate, str
            ):
                result = await run_script_update(
                    request, script_update.apply_update, root, self._update_candidate
                )
            else:
                # A no-update observation is not an install snapshot. Recheck
                # the live version and recovery state before starting MaaEnd.
                result = await run_script_update(
                    request,
                    script_update.update_before_run,
                    root,
                    self.script_config,
                    progress=progress,
                )
        except (script_install.InstallUnsafeError, FluxdownCancelUnconfirmed):
            point(self, "script_update", state="failed")
            raise
        except Exception as error:
            point(self, "script_update", state="failed")
            await script_update.confirm_current_install(root)
            result = f"MaaEnd 更新准备未完成，沿用当前安装继续任务：{error}"
            logger.warning(result)
            await self.script_info.set_log(result)
            with suppress(Exception):
                await Publisher.send(
                    id=self.task_info.task_id,
                    type=protocol.TASK_NOTICE,
                    data=WSTaskNoticeData(
                        sourceScriptType="MaaEnd", level="warning", message=result
                    ),
                )
        else:
            point(self, "script_update", state="succeeded", key="checked")
            await push_dispatch_log(self.script_info, result)
        await self._refresh_after_program_install(root)
        self._program_update_prepared = True

    async def _refresh_after_program_install(self, root: Path) -> None:
        """不重复安装，但必须照常校验资源并清理过时的 MXU 缓存包。"""
        await asyncio.to_thread(
            MaaEndResourceLoader.get_cached, root, force_reload=True
        )
        self.controller_protocol = load_maaend_controller_protocol(
            root, str(self.script_config.Game.ControllerType)
        )
        removed = await script_install.run_worker(
            script_update.discard_obsolete_mxu_packages, root
        )
        if removed:
            await push_dispatch_log(
                self.script_info,
                f"已移除 {len(removed)} 个过期 MXU 更新包；"
                "MXU 启动时将清除对应的待安装记录",
            )

    async def _prepare_game_update(self) -> str | None:
        """任务启动前接管终末地 PC 客户端更新。

        更新对象是托管级的 Game.Path，多账号与重试轮次都只该检查一次，所以要赶在本轮
        游戏被拉起来之前做完——那时才不存在覆盖正被占用文件的竞争。

        跨脚本互斥不在这里做：add_task 按脚本粒度挡重复派发，多账号是同一脚本内的
        账号集合，同一目录不会被两个脚本并发更新。

        配置/查看会话只是打开 MaaEnd 的配置界面，不该被关掉正在运行的游戏、
        再多等几 GB 的下载。

        Returns:
            str | None: 需要阻断本轮任务时返回给用户看的说明；None 表示可以继续。
        """

        if self.task_info.mode != TaskMode.AUTO_PROXY:
            return None
        script_config = self.script_config
        if not isinstance(script_config, MaaEndConfig):
            return None
        if (
            self.controller_protocol == "Win32"
            and str(script_config.Game.LaunchMode or "").strip() == "Launcher"
        ):
            # 启动器启动：游戏更新由官方启动器界面处理（MAS 只负责点按钮与等待），
            # 跳过 API 直下的更新接管，避免两套更新互相打架
            logger.info(
                "启动方式为「启动器启动」，游戏更新交由启动器处理，跳过更新接管"
            )
            return None
        if not script_config.Game.IfAutoUpdate:
            return None
        if self.controller_protocol != "Win32":
            # 改成模拟器后这个勾选会留着；静默跳过会被当成已生效，留一行可查的说明
            logger.info("终末地客户端更新仅支持 PC 控制器，当前控制器已跳过")
            return None
        game_exe = Path(str(client_executable_path(script_config) or "").strip())
        if not game_exe.is_file():
            # 路径填错或客户端被移走时留一行可查的说明，别让这道门静默消失
            logger.info(f"未找到终末地客户端，本轮不检查更新: {game_exe}")
            return None

        async def report(line: str) -> None:
            await push_dispatch_log(self.script_info, line)

        try:
            point(self, "game_update")
            result = await ensure_game_updated(
                game_exe,
                time_limit_minutes=int(script_config.Game.UpdateTimeLimit),
                progress=report,
            )
        except Exception as error:
            # 能走到这里的只剩「已经开始写游戏目录之后」出的岔子：放行等于让脚本
            # 跑在半写入的客户端上，一律阻断。
            point(self, "game_update", state="failed")
            logger.opt(exception=True).error(
                f"终末地客户端更新接管异常，中止本轮任务: {error}"
            )
            return f"终末地客户端更新异常（{error}），已中止本轮任务"

        # 结论也要在调度台留一句：拦住本轮的那句之外，「已更新至 x」与「判不了所以放行」
        # 同样得看得见；UpToDate 每轮任务都会出，重复播没人看
        game_update_result(self, result)
        if result.status != "UpToDate":
            await push_dispatch_log(self.script_info, result.message)
        if result.status == "NeedManualUpdate":
            return result.message
        return None

    def build_worker(self, user, config):
        """按任务模式构造 L4：自动代理 / 脚本配置 / 只读查看会话。"""
        worker = {
            TaskMode.AUTO_PROXY: AutoProxyTask,
            TaskMode.SCRIPT_CONFIG: ScriptConfigTask,
            TaskMode.SCRIPT_VIEW: ScriptViewTask,
        }[self.task_info.mode]
        return worker(self, user, config)

    async def spawn(self, child) -> None:
        """派发单账号执行器：维护状态先判，跑完再还原安装目录的原生配置。"""
        mode = self.task_info.mode
        if mode == TaskMode.AUTO_PROXY:
            window = await self._maintenance_window(child.user_config)
            if window is not None:
                await self._skip_maintenance(child.user_info, window)
                return
            user_config = child.user_config
            config_base = maaend_config_base(
                user_config.Info.Base if user_config is not None else None
            )
            logger.info(
                f"账号 {child.user_info.info.user_id} 配置来源: "
                f"{BASE_SOURCE_LABELS.get(config_base, config_base)}"
            )
            if config_base == BASE_NATIVE:
                # 原生来源直接用安装目录的配置：先还原任务前快照，
                # 别让上一个账号下发过的托管配置留在现场。
                await self._restore_script_config_from_temp()
        else:
            # 配置/查看会话的写回要留到 finish() 判断，先记下当前会话。
            self._active_config_task = child
        try:
            await super().spawn(child)
        finally:
            if mode == TaskMode.AUTO_PROXY:
                if child.game_start_attempted:
                    self.has_proxy_run = True
                    self._keep_last_game = child.keeps_game_on_finish
                # 执行器自持本轮的节点详情素材与诊断截图，收尾报告从这里取。
                self._proxy_tasks[child.user_info.uid] = child
                self.error_screenshot_paths.extend(
                    getattr(child, "error_screenshot_paths", ())
                )
                # 每个账号跑完就把 MaaEnd 原生配置恢复到任务前状态。
                await self._restore_script_config_from_temp()
        if mode == TaskMode.AUTO_PROXY and getattr(child, "update_failed", False):
            # 安装状态未确认时，同一目录上的后续账号也不能继续执行。
            raise RuntimeError("MaaEnd 安装状态未确认，后续账号不再执行")

    def is_last_participating_user(self, current) -> bool:
        """还设备前查看后续账号的准入状态，维护结果复用本轮已查的信息。"""
        now = datetime.now().astimezone()
        users = self.script_info.user_list
        for user in users[users.index(current) + 1 :]:
            config = self.resolve_user(user)
            if not isinstance(config, MaaEndUserConfig) or not self.can_run_user(
                config
            ):
                continue
            maintained_until = self._maintenance_until.get(
                self.maintenance_game(config) or ""
            )
            if maintained_until is None or maintained_until <= now:
                return False
        return True

    async def _maintenance_window(self, user_config):
        """按账号服务器查询宿主维护信息，并记下本轮最近一次查询结果。"""
        game = self.maintenance_game(user_config)
        window = await get_user_maintenance(
            game,
            lookup=partial(GameMaintenance.get_active, proxy=Config.proxy),
        )
        if game is not None:
            if window is None:
                self._maintenance_until.pop(game, None)
            else:
                self._maintenance_until[game] = window.end
        return window

    async def _skip_maintenance(self, user, window) -> None:
        """登记因维护跳过本轮执行的账号，并写入跳过原因。

        与旧实现一致：账号状态与日志记录之外，调度台流水里留一行，并推一条
        info 通知，免得用户只看到托管被跳过却不知道是维护。
        """
        self._maintenance_skipped.add(user.info.user_id)
        await self.record_user_state(user, status="跳过", reason=window.reason)
        line = f"{self.script_info.name} - {user.name}: {window.reason}"
        await self.script_info.set_log(
            f"{self.script_info.log}\n{line}" if self.script_info.log else line
        )
        logger.info(line)
        await Publisher.send(
            id=self.task_info.task_id,
            type=protocol.TASK_NOTICE,
            data=WSTaskNoticeData(
                sourceScriptType="MaaEnd", level="info", message=line
            ),
        )

    @property
    def all_users_maintenance_skipped(self) -> bool:
        """判断本次确有账号，且全部都被维护时段挡下。"""
        users = self.script_info.users.values()
        return bool(self.script_info.users) and all(
            user.info.user_id in self._maintenance_skipped for user in users
        )

    async def notify_maintenance(self) -> None:
        """记录全部账号处于维护期的结论，并通过宿主推送维护提示。"""
        await self.script_info.set_log("所选账号均处于游戏维护时段，本轮跳过")
        try:
            await push_maintenance_notice(
                message=self.maintenance_message, task_info=self.task_info
            )
        except Exception as error:
            logger.opt(exception=True).warning(f"推送维护通知失败: {error}")

    async def final_task(self) -> None:
        """执行 L3 公共收尾；全部账号因维护跳过且无错误或取消时把托管结果记为跳过。"""
        if self._maintenance_only and not self.cancelled and self.error is None:
            await self.script_info.set_state(status="跳过")
            return
        await super().final_task()
        if (
            self.all_users_maintenance_skipped
            and not self.cancelled
            and self.error is None
        ):
            await self.script_info.set_state(status="跳过")

    async def finish(self) -> None:
        """还原原生配置、推送报告与通知，并清理任务前快照。"""
        try:
            if not self.prepared:
                return
            if self._keep_script_config_changes():
                logger.info("原生来源配置会话成功，保留 MaaEnd 原生配置")
            else:
                await self._restore_script_config_from_temp()
            self._cleanup_script_config_temp()

            if self.task_info.mode == TaskMode.AUTO_PROXY:
                # 只关闭本轮打开过的模拟器，并保留最后一个完成账号的游戏设置。
                if self.has_proxy_run and not self._keep_last_game:
                    await close_emulator(self, index=game_device_id(self.script_config))
                await config_manager.flush()
                await self._push_proxy_report()
        finally:
            self._install_access.close()

    async def _push_proxy_report(self) -> None:
        """把账号结果整理成自动代理报告，连同错误截图一起推送。"""
        users = tuple(self.script_info.users.values())
        completed = sum(user.info.status == "完成" for user in users)
        uncompleted = sum(user.info.status in {"异常", "等待"} for user in users)
        error_count = sum(user.info.status == "异常" for user in users)

        title = (
            f"{datetime.now().strftime('%m-%d')} | "
            f"{self.script_info.info.name or '空白'}"
            f"的{TASK_MODE_ZH[TaskMode.AUTO_PROXY]}任务报告"
        )
        user_result_text = self._render_user_results(has_uncompleted=uncompleted > 0)
        # 报告正文整块镜像进调度台，没配推送的用户也能看到账号结果
        if user_result_text:
            await self.script_info.set_log(
                f"{self.script_info.current.log}\n{user_result_text}"
                if self.script_info.current.log
                else user_result_text
            )
        error_images = (
            _format_maaend.collect_recent_error_images(
                self.script_config.Info.Path,
                started_at_ns=self.error_image_start_ns,
                ended_at_ns=time_ns(),
                diagnostic_paths=self.error_screenshot_paths,
            )
            if error_count and self.error_image_start_ns is not None
            else ()
        )
        report = {
            "title": f"{TASK_MODE_ZH[TaskMode.AUTO_PROXY]}任务报告",
            "script_name": self.script_info.info.name or "空白",
            "start_time": self.begin_time,
            "end_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "completed_count": completed,
            "uncompleted_count": uncompleted,
            "result": user_result_text,
        }
        if error_images:
            report["screenshots"] = screenshot_entries(
                [(image.alt, image) for image in error_images]
            )

        try:
            if self.all_users_maintenance_skipped:
                await self.notify_maintenance()
            else:
                await Notify.push_proxy_result(
                    title=title,
                    report=TaskResultReport.from_message(report),
                    task_info=self.task_info,
                    images=error_images,
                )
        except Exception as error:
            logger.opt(exception=True).warning(f"推送代理结果时出现异常: {error}")
            with suppress(Exception):
                await Publisher.send(
                    id=self.task_info.task_id,
                    type=protocol.TASK_NOTICE,
                    data=WSTaskNoticeData(
                        sourceScriptType="MaaEnd",
                        level="error",
                        message=f"推送代理结果时出现异常: {error}",
                    ),
                )

    async def on_crash(self, exc: BaseException) -> None:
        """标记托管异常，尽力还原原生配置并发布错误提示。"""
        await self.script_info.set_state(status="异常")
        logger.opt(exception=True).warning(f"MaaEnd任务出现异常: {exc}")
        if self.prepared:
            with suppress(Exception):
                await self._restore_script_config_from_temp()
            self._cleanup_script_config_temp()
        if self.task_info.mode == TaskMode.AUTO_PROXY and self.user_config:
            with suppress(Exception):
                await config_manager.flush()
        with suppress(Exception):
            await Publisher.send(
                id=self.task_info.task_id,
                type=protocol.TASK_NOTICE,
                data=WSTaskNoticeData(
                    sourceScriptType="MaaEnd",
                    level="error",
                    message=f"MaaEnd任务出现异常: {exc}",
                ),
            )

    def _render_user_results(self, *, has_uncompleted: bool) -> str:
        """本专项选择报告条目和展示模式，公共服务只负责排版。

        节点详情素材由各账号执行器自持（旧基类的 user_state 已移除），这里只按
        账号选条目、选渲染方式，不读任何旧 manager 私有状态。
        """
        rows = []
        for user in self.script_info.users.values():
            task = self._proxy_tasks.get(user.uid)
            entries = [
                item
                if isinstance(item, log_box.LogEntry)
                else log_box.LogEntry.from_legacy(item)
                for item in (task.push_log if task is not None else ())
                if (item.log_type if isinstance(item, log_box.LogEntry) else item[0])
                != LOG_TYPE_ERROR
                or has_uncompleted
            ]
            mode = task.push_log_mode if task is not None else "关闭"
            if mode == "关闭":
                details = []
            elif mode == "汇总":
                details = _node_report.render_aggregate_push_log(entries)
            else:
                details = _node_report.render_scatter_push_log(entries)
            rows.append(
                UserReportText(
                    name=user.info.name,
                    result=user.info.result,
                    detail_lines=tuple(details),
                )
            )
        return _node_report.render_user_result_text(rows)

    def _keep_script_config_changes(self) -> bool:
        """原生来源配置会话成功时保留 MaaEnd GUI 的写回。

        配置会话的唯一正常出口就是用户在配置窗口点「保存配置」发起的中止，因此这里
        不能把取消当作丢弃的依据，否则原生来源模式下 MaaEnd GUI 的写回会被随后的
        配置复原抹掉。查看会话（ScriptView）不保留任何现场改动，结束后恢复任务前快照。
        """

        task = self._active_config_task
        return (
            self.task_info.mode == TaskMode.SCRIPT_CONFIG
            and task is not None
            and bool(getattr(task, "native_config_saved", False))
        )

    async def _restore_script_config_from_temp(self) -> None:
        """恢复任务开始前的 MaaEnd working 配置。"""

        if (
            not self.temp_path
            or not self.temp_path.exists()
            or not self.maaend_config_dir
        ):
            return
        if not self.had_original_script_config:
            _utils_io.force_rmtree(self.maaend_config_dir)
            return

        logger.info(f"复原 MaaEnd 脚本配置文件: {self.temp_path}")
        _utils_io.swap_in_dir(self.temp_path, self.maaend_config_dir)

    def _recover_previous_run(self) -> None:
        """处置上次崩溃残留的原始配置快照。"""

        result = _utils_io.recover_native_config(
            self.temp_path,
            self.maaend_config_dir,
            expected_script_id=self.script_info.info.script_id,
        )
        if result == "restored":
            logger.info("已恢复上次中断前的 MaaEnd 原始配置")
        elif result == "legacy":
            logger.warning(
                "检测到上次中断残留的 MaaEnd 原生配置快照由旧版本生成, "
                "已改名保留以便手动恢复"
            )
        elif result == "skipped":
            logger.warning(
                "检测到 MaaEnd 原生配置在中断后被改动, 已保留当前配置并丢弃旧快照"
            )

    def _cleanup_script_config_temp(self) -> None:
        """清掉任务前快照，避免下一轮把它当成待恢复的现场。"""

        if self.temp_path:
            _utils_io.clear_native_config_snapshot(self.temp_path)
