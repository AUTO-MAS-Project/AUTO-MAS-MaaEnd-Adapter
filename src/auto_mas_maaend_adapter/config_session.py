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
"""MaaEnd 原生配置会话：配置模式与只读查看共用一个 MXU 会话基类。

配置会话把所选账号的 MAS 配置下发进 MaaEnd 安装目录 config/，起 MXU 本体让用户
在原生界面里编辑，结束（用户在 MAS 界面点「保存配置」，即本轮任务被取消）时把安装
目录的配置回写成新的 MAS 配置。查看会话（TaskMode.SCRIPT_VIEW）走同一套下发与进程
管理，但只读：结束不回写，安装目录现场由展开器的任务前快照还原。
"""

import asyncio
import shutil
from pathlib import Path
from typing import Any

from auto_mas_core import ScriptConfigWorker, ScriptViewWorker, TaskMode
from auto_mas_core.host.core import Publisher
from auto_mas_core.host.core_ws import protocol
from auto_mas_core.host.models_schema import WSTaskNoticeData
from auto_mas_core.host.utils import (
    BASE_NATIVE,
    BASE_SHARED,
    ProcessManager,
    get_logger,
    process,
)
from auto_mas_core.host.utils import constants as _utils_constants
from auto_mas_core.host.utils import io as _utils_io

from .tools.backup_archive import archive_mas_runtime_backup, read_overlay_values

logger = get_logger("MaaEnd 脚本设置")


def maaend_config_base(raw: object) -> str:
    """读取 MaaEnd 配置来源（base 三态），并兼容旧版字面量。"""

    return _utils_constants.normalize_base_source(raw) or _utils_constants.BASE_SHARED


def maaend_mas_config_dir(script_id: str, user_id: str, base: str) -> Path:
    """返回脚本共享或独立配置目录。"""

    base = maaend_config_base(base)
    if base == _utils_constants.BASE_NATIVE:
        raise ValueError("原生来源配置不使用 MAS 配置目录")
    owner = "Default" if base == _utils_constants.BASE_SHARED else user_id
    return Path.cwd() / "data" / script_id / owner / "ConfigFile"


def normalize_maaend_config(
    maaend_set: dict[str, Any],
    controller_type: str,
    fallback_set: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """将 MaaEnd 配置收束为 AUTO-MAS 单实例配置"""

    def select_instance(source_set: dict[str, Any]) -> dict[str, Any] | None:
        instances = source_set.get("instances")
        if not isinstance(instances, list) or len(instances) == 0:
            return None

        last_active_instance_id = source_set.get("lastActiveInstanceId")
        for instance in instances:
            if instance.get("id") == "automas" or instance.get("name") == "AUTO-MAS":
                return instance
            if (
                isinstance(instance, dict)
                and instance.get("id") == last_active_instance_id
            ):
                return instance

        for instance in instances:
            if isinstance(instance, dict):
                return instance
        return None

    selected_instance = select_instance(maaend_set)
    if selected_instance is None and fallback_set is not None:
        selected_instance = select_instance(fallback_set)
    if selected_instance is None:
        raise ValueError("MaaEnd 配置文件中未找到可用实例")

    selected_instance["id"] = "automas"
    selected_instance["name"] = "AUTO-MAS"
    selected_instance.pop("customName", None)
    selected_instance["controllerName"] = controller_type
    selected_instance.setdefault("tasks", [])

    maaend_set["instances"] = [selected_instance]
    maaend_set["lastActiveInstanceId"] = "automas"
    return maaend_set


class MaaEndSessionMixin:
    """MaaEnd 脚本设置模式的共用生命周期（配置会话与查看会话）。

    会话包络（下发源 + 回写目标）与运行下发同一套 owner 规则
    （:func:`maaend_mas_config_dir`：shared 来源=Default 共享、independent 来源=独立目录）。
    ``view_only`` 为查看会话：只读预览（如「查看历史备份」）——账号级会话下发的
    owner 目录即刚恢复的备份（所见即备份），托管级会话跳过下发（原生目录即备份）；
    结束不回写 MAS 配置，安装 config/ 由展开器的任务前快照还原（临时注入，看完还原）。
    """

    def __init__(self, expander, user, config):
        """绑定展开器、账号运行节点与已锁账号配置，解析本会话的配置来源与回写目录。"""
        super().__init__(expander, user, config)
        self.script_config = expander.script_config
        self.cur_user_item = user
        self.cur_user_config = config
        # 任务树的共享账号用 default，MAS 配置侧沿用 Default 这个 owner 名
        self.cur_user_uid = (
            "Default" if user.info.user_id == "default" else user.info.user_id
        )
        self.view_only = self.mode == TaskMode.SCRIPT_VIEW
        # 主流程是否已失败：失败时安装目录可能没有可回写的内容，再换入只会盖住原因
        self.crashed = False
        # 原生来源会话结束时由本体自己落盘，展开器据此保留现场（不看账号状态，见 finish）
        self.native_config_saved = False
        self.prepared = False
        self.config_base = BASE_SHARED
        if self.cur_user_uid != "Default" and config is not None:
            self.config_base = maaend_config_base(config.Info.Base)
        self.use_mas_config = self.config_base != BASE_NATIVE
        self.config_file_path = (
            maaend_mas_config_dir(
                self.script_info.info.script_id,
                self.cur_user_uid,
                self.config_base,
            )
            if self.use_mas_config
            else None
        )

    async def check(self) -> str | None:
        """会话前置检查：MaaEnd 路径必填，且要能起本体才能打开原生界面。"""
        root_path = self.script_config.Info.Path
        if root_path is None:
            return "Path未配置，请检查路径设置"
        if not (root_path / "MaaEnd.exe").exists():
            return "MaaEnd.exe文件不存在, 请检查MaaEnd路径设置！"
        return None

    async def prepare(self):
        """建立 MXU 进程管理器，定位安装目录的配置目录与可执行文件。"""

        self.maaend_process_manager = ProcessManager()
        self.wait_event = asyncio.Event()

        maaend_root_path = self.script_config.Info.Path
        if maaend_root_path is None:
            raise ValueError("Path未配置，请检查路径设置")
        self.maaend_root_path = maaend_root_path
        self.maaend_set_path = self.maaend_root_path / "config"
        self.maaend_exe_path = self.maaend_root_path / "MaaEnd.exe"
        self.prepared = True

    async def main_logic(self):
        """下发账号配置后启动 MXU 本体，等用户在原生界面保存并结束会话。"""

        await self.set_maaend()
        logger.info(f"启动 MaaEnd 进程: {self.maaend_exe_path}")
        self.wait_event.clear()
        await self.maaend_process_manager.open_process(self.maaend_exe_path)
        # 配置会话没有自然结束点：wait_event 没有任何设置方，用户在 MAS 界面点
        # 「保存配置」发起的中止就是唯一出口（取消沿 await 链传到本协程）。
        await self.wait_event.wait()

    async def set_maaend(self):
        """配置 MaaEnd 运行参数"""

        logger.info(f"开始配置 MaaEnd 运行参数: 设置账号 {self.cur_user_uid}")

        await self.maaend_process_manager.kill()
        await process.kill_process(self.maaend_exe_path)

        maaend_set_path = self.maaend_set_path / "mxu-MaaEnd.json"

        # 查看会话的托管级入口：原生目录即所选备份，跳过下发与注入
        if self.view_only and self.cur_user_uid == "Default":
            if maaend_set_path.exists():
                maaend_set = _utils_io.read_file(maaend_set_path)
                if not isinstance(maaend_set, dict):
                    raise ValueError("MaaEnd 配置文件不是有效对象")
                settings = maaend_set.get("settings")
                if not isinstance(settings, dict):
                    settings = {}
                    maaend_set["settings"] = settings
                settings["autoRunOnLaunch"] = False
                _utils_io.write_file(maaend_set_path, maaend_set)
            logger.info("MaaEnd 查看会话跳过配置下发: 原生目录即所选备份")
            return

        if (
            self.use_mas_config
            and self.config_file_path
            and (self.config_file_path / "mxu-MaaEnd.json").exists()
        ):
            _utils_io.replace_dir(self.config_file_path, self.maaend_set_path)
            _utils_io.mark_native_config_injected(
                Path.cwd() / f"data/{self.script_info.info.script_id}/Temp",
                self.maaend_set_path,
                script_id=self.script_info.info.script_id,
            )
        elif (
            self.use_mas_config
            and self.config_file_path
            and self.maaend_set_path.exists()
        ):
            shutil.copytree(
                self.maaend_set_path,
                self.config_file_path,
                dirs_exist_ok=True,
            )

        # 下发前归档 MAS 配置到账号池（下发源，会话保存会覆盖它；带快速
        # 配置覆盖层字段侧车，指纹去重，失败不阻断会话）。native 池由
        # 展开器在任务级一次性归档
        if self.use_mas_config and self.config_file_path:
            overlay = (
                read_overlay_values(self.cur_user_config)
                if self.cur_user_uid != "Default" and self.cur_user_config is not None
                else None
            )
            archive_mas_runtime_backup(
                self.script_info.info.script_id,
                self.cur_user_uid,
                self.config_file_path,
                overlay=overlay,
                # 备份标注来源：tri_state 池跨来源恢复靠它切回
                base=self.config_base,
            )

        if not maaend_set_path.exists():
            raise FileNotFoundError(
                "未找到 MaaEnd 配置文件, 请检查 MaaEnd 路径设置或先启动 MaaEnd 完成配置文件生成"
            )

        maaend_set = _utils_io.read_file(maaend_set_path)
        if not isinstance(maaend_set, dict):
            raise ValueError("MaaEnd 配置文件不是有效对象")
        if self.use_mas_config:
            maaend_set = normalize_maaend_config(
                maaend_set, self.script_config.Game.ControllerType
            )
        settings = maaend_set.get("settings")
        if not isinstance(settings, dict):
            settings = {}
            maaend_set["settings"] = settings
        settings["autoRunOnLaunch"] = False
        _utils_io.write_file(maaend_set_path, maaend_set)
        logger.success(
            f"MaaEnd 运行参数配置完成: "
            f"{_utils_constants.BASE_SOURCE_LABELS.get(self.config_base, self.config_base)}配置"
        )

    async def finish(self):
        """进程收尾，并按配置或只读模式决定是否把安装目录配置回写成 MAS 配置。"""

        if not self.prepared:
            return

        await self.maaend_process_manager.kill()
        await process.kill_process(self.maaend_exe_path)

        # 查看会话：只读预览，不把安装 config/ 回写 MAS 目录（安装现场由
        # 展开器的任务前快照还原）；GUI 内的改动一律丢弃
        if self.view_only:
            logger.success("MaaEnd 查看结束（只读，不回写配置）")
            await self.cur_user_item.set_state(status="完成")
            return

        # 配置会话没有自然结束点: 用户在配置窗口点「保存配置」发起的中止就是
        # 唯一出口, 因此这里不能按中止丢弃改动, 否则 MaaEnd GUI 的编辑永远落不回
        # MAS 配置目录。但主流程已经失败(如 MaaEnd 配置目录不存在)时没有任何可回写
        # 的内容, 再换入只会把不存在的目录当源头再报一次错, 盖住真正的原因。
        if self.crashed:
            return

        if self.use_mas_config and self.config_file_path:
            _utils_io.swap_in_dir(self.maaend_set_path, self.config_file_path)
            config_path = self.config_file_path / "mxu-MaaEnd.json"
            maaend_set = _utils_io.read_file(config_path)
            maaend_set = normalize_maaend_config(
                maaend_set, self.script_config.Game.ControllerType
            )
            _utils_io.write_file(config_path, maaend_set)
            logger.success(f"MaaEnd 配置已保存到: {self.config_file_path}")
            await self.cur_user_item.set_state(status="完成")
            return

        # 原生来源会话：MAS 零写入，安装目录配置由本体保存并保留
        self.native_config_saved = True
        logger.success("MaaEnd 原生来源配置已由脚本原生 GUI 保存")
        await self.cur_user_item.set_state(status="完成")

    async def on_crash(self, exc: BaseException):
        """标记会话失败，记录异常并向当前任务发布错误提示。"""
        self.crashed = True
        await self.cur_user_item.set_state(status="异常")
        logger.opt(exception=True).warning(f"脚本设置任务出现异常: {exc}")
        await Publisher.send(
            id=str(self.task_info.uid),
            type=protocol.TASK_NOTICE,
            data=WSTaskNoticeData(
                sourceScriptType="MaaEnd",
                level="error",
                message=f"脚本设置任务出现异常: {exc}",
            ),
        )


class ScriptConfigTask(MaaEndSessionMixin, ScriptConfigWorker):
    """在 MaaEnd 原生 GUI 编辑配置，结束后回写 MAS 配置目录。"""


class ScriptViewTask(MaaEndSessionMixin, ScriptViewWorker):
    """查看备份：只读打开原生 GUI，结束时丢弃改动。"""
