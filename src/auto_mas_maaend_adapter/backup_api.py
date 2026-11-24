#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#
#   This file is part of AUTO-MAS.
#
#   AUTO-MAS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 or (at your option)
#   any later version.
#
#   AUTO-MAS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
#   the GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public
#   License along with AUTO-MAS. If not, see <https://www.gnu.org/licenses/>.

"""MaaEnd 插件自有备份恢复接口：把专项恢复池接到插件 HTTP 路由。

宿主通用 `/api/scripts/backup/*` 依赖宿主装配的恢复池解析器，插件世界没有
这个挂钩；这里按同样语义自行构建运行时恢复服务：
`Config.ScriptConfig` 取脚本 → `RestoreContext` → `build_restore_service`
绑定 :data:`auto_mas_maaend_adapter.tools.restore_service.RESTORE_POOLS`。

响应包络与宿主备份端点一致（`code` / `status` / `message` 加业务字段）；
错误按 ValueError/KeyError/TypeError → 400、ConfigCorruptedError → 409（仅恢复）、
其余 → 500。不引入宿主 `app.models.schema` 的备份模型，避免插件依赖宿主
私有传输层。
"""

from __future__ import annotations

import uuid
from typing import Any

from auto_mas_core import Config
from auto_mas_core.host.models_schema import OutBase
from auto_mas_core.host.utils import get_logger
from auto_mas_core.host.utils import io as _utils_io
from auto_mas_core.host.utils_common_config import restore as _utils_config_restore
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from .config import MaaEndConfig
from .tools.restore_service import RESTORE_POOLS

router = APIRouter(prefix="/api/plugin/maaend_adapter", tags=["Backup"])
logger = get_logger("MaaEnd 配置备份 API")


class MaaEndBackupItem(BaseModel):
    """一份备份条目的展示信息。"""

    time: str = Field(..., description="备份时间戳（目录名，如 20260910-104500）")
    base: str | None = Field(
        default=None,
        description="备份时点的配置来源（shared/independent/native）；旧版备份无标注为 null",
    )


class MaaEndBackupListOut(OutBase):
    data: list[MaaEndBackupItem] = Field(
        default_factory=list, description="备份列表（时间倒序）"
    )
    base: str | None = Field(
        default=None, description="当前配置来源；非三态池或读不到时为 null"
    )


class MaaEndBackupEnsureIn(BaseModel):
    """按需归档目标池当前配置。"""

    scriptId: str = Field(..., description="所属托管ID")
    userId: str = Field(..., description="目标账号ID")
    target: str = Field(..., description="归档目标（mas/native）")


class MaaEndBackupEnsureOut(OutBase):
    created: bool = Field(
        default=False, description="本次是否新建归档（False=指纹无变化或无可归档内容）"
    )
    time: str = Field(default="", description="最新备份时间戳（无备份为空串）")


class MaaEndBackupRestoreIn(BaseModel):
    """把指定备份恢复到目标位置。"""

    scriptId: str = Field(..., description="所属托管ID")
    userId: str = Field(..., description="目标账号ID")
    time: str = Field(..., description="备份时间戳")
    target: str = Field(..., description="恢复目标（mas/native）")
    force: bool = Field(
        default=False,
        description="源配置损坏时是否强制恢复（False 时返回 409 由前端二次确认）",
    )


class MaaEndBackupRestoreOut(OutBase):
    target: str = Field(default="", description="实际执行的恢复目标")


class MaaEndBackupPreviewOut(OutBase):
    """备份配置摘要（纯读不恢复，载荷结构由专项池定义）。"""

    time: str = Field(default="", description="备份时间戳")
    target: str = Field(default="", description="备份类别")
    data: dict[str, Any] = Field(
        default_factory=dict, description="专项预览载荷（mas/native 的 fileCards）"
    )


class MaaEndBackupFileOut(OutBase):
    """备份内文本文件内容（只读；路径限归档内相对路径）。"""

    time: str = Field(default="", description="备份时间戳")
    target: str = Field(default="", description="备份类别")
    path: str = Field(default="", description="归档内相对路径")
    size: int = Field(default=0, description="文件字节数")
    content: str = Field(default="", description="文本内容；超限或越界返回 400")


def _error_code(error: Exception) -> int:
    """专项可预期错误统一 400，其余按宿主惯例视为服务端错误。"""

    return 400 if isinstance(error, (ValueError, KeyError, TypeError)) else 500


def backup_service(
    script_id: str, user_id: str, *, force: bool = False
) -> _utils_config_restore.ConfigRestoreService:
    """按脚本/账号上下文构建本插件的运行时恢复服务。

    托管或账号不存在时抛出 KeyError/ValueError，由端点转 400；`force` 随
    上下文下发给会读取的专项池函数。
    """

    script = Config.ScriptConfig[uuid.UUID(script_id)]
    if not isinstance(script, MaaEndConfig):
        raise ValueError("托管不是 MaaEnd 类型")
    script.users[uuid.UUID(user_id)]
    return _utils_config_restore.build_restore_service(
        _utils_config_restore.RestoreContext(
            config=Config,
            script_config=script,
            script_id=script_id,
            user_id=user_id,
            force=force,
        ),
        RESTORE_POOLS,
    )


async def restore_backup(
    script_id: str, user_id: str, time: str, target: str, *, force: bool = False
) -> dict[str, str]:
    """执行恢复；托管正在运行（锁定）时拒绝，避免换目录与回填字段之间撞锁。"""

    service = backup_service(script_id, user_id, force=force)
    if Config.ScriptConfig[uuid.UUID(script_id)].is_locked:
        raise RuntimeError(f"托管 {script_id} 正在运行, 无法恢复配置")
    await service.restore(target, time)
    return {"target": target}


@router.get(
    "/backup/list",
    summary="列出配置备份（时间倒序；target 取值由专项定义，非法值返回 400）",
    response_model=MaaEndBackupListOut,
    status_code=200,
)
async def list_config_backups(
    scriptId: str, userId: str, target: str
) -> MaaEndBackupListOut:
    """返回 `items`（`time` + 备份时点来源标注 `base`）与当前来源。"""

    try:
        service = backup_service(scriptId, userId)
        items = await service.list(target)
        return MaaEndBackupListOut(
            code=200,
            status="success",
            message=f"共 {len(items)} 份备份",
            data=[MaaEndBackupItem(**item) for item in items],
            base=await service.current_base(target),
        )
    except Exception as error:
        logger.opt(exception=True).warning(f"配置备份列表查询失败: {error}")
        return MaaEndBackupListOut(
            code=_error_code(error),
            status="error",
            message=f"{type(error).__name__}: {error}",
            data=[],
        )


@router.post(
    "/backup/ensure",
    summary="按需归档目标池当前配置（指纹去重，无变化跳过）",
    response_model=MaaEndBackupEnsureOut,
    status_code=200,
)
async def ensure_config_backup(
    script: MaaEndBackupEnsureIn = Body(...),
) -> MaaEndBackupEnsureOut:
    """target 为 MaaEnd 定义的 mas（账号配置）或 native（安装目录配置）。"""

    try:
        data = await backup_service(script.scriptId, script.userId).ensure(
            script.target
        )
        return MaaEndBackupEnsureOut(
            code=200, status="success", message="", **data
        )
    except _utils_io.ConfigCorruptedError as error:
        # 源配置损坏：message 用原文（含损坏位置）直达用户，前端编辑页会透传
        logger.opt(exception=True).warning(f"配置按需归档失败（源配置损坏）: {error}")
        return MaaEndBackupEnsureOut(
            code=400, status="error", message=str(error), created=False, time=""
        )
    except Exception as error:
        logger.opt(exception=True).warning(f"配置按需归档失败: {error}")
        return MaaEndBackupEnsureOut(
            code=_error_code(error),
            status="error",
            message=f"{type(error).__name__}: {error}",
            created=False,
            time="",
        )


@router.post(
    "/backup/restore",
    summary="把指定备份恢复到目标位置（恢复前自动存底当前配置）",
    response_model=MaaEndBackupRestoreOut,
    status_code=200,
)
async def restore_config_backup(
    script: MaaEndBackupRestoreIn = Body(...),
) -> MaaEndBackupRestoreOut:
    """恢复语义由专项池定义；跨来源回切、字段回填都在池函数内完成。"""

    try:
        data = await restore_backup(
            script.scriptId,
            script.userId,
            script.time,
            script.target,
            force=script.force,
        )
        return MaaEndBackupRestoreOut(
            code=200,
            status="success",
            message=f"已恢复备份 {script.time}",
            target=data["target"],
        )
    except _utils_io.ConfigCorruptedError as error:
        # 源配置损坏：带损坏位置返回 409，前端二次确认后携带 force 重试
        logger.opt(exception=True).warning(f"配置备份恢复被拦截（源配置损坏）: {error}")
        return MaaEndBackupRestoreOut(
            code=409, status="error", message=str(error), target=script.target
        )
    except Exception as error:
        logger.opt(exception=True).warning(f"配置备份恢复失败: {error}")
        return MaaEndBackupRestoreOut(
            code=_error_code(error),
            status="error",
            message=f"{type(error).__name__}: {error}",
            target=script.target,
        )


@router.get(
    "/backup/preview",
    summary="读取指定备份的配置摘要（纯读不恢复）",
    response_model=MaaEndBackupPreviewOut,
    status_code=200,
)
async def get_config_backup_preview(
    scriptId: str, userId: str, time: str, target: str
) -> MaaEndBackupPreviewOut:
    """data 载荷由专项定义（mas/native 都挂 `fileCards`）。"""

    try:
        data = await backup_service(scriptId, userId).preview(target, time)
        return MaaEndBackupPreviewOut(
            code=200,
            status="success",
            message="",
            time=time,
            target=target,
            data=data,
        )
    except Exception as error:
        logger.opt(exception=True).warning(f"配置备份预览失败: {error}")
        return MaaEndBackupPreviewOut(
            code=_error_code(error),
            status="error",
            message=f"{type(error).__name__}: {error}",
            time=time,
            target=target,
            data={},
        )


@router.get(
    "/backup/file",
    summary="只读读取指定备份内一个文本文件（路径限归档内）",
    response_model=MaaEndBackupFileOut,
    status_code=200,
)
async def get_config_backup_file(
    scriptId: str, userId: str, time: str, target: str, path: str
) -> MaaEndBackupFileOut:
    """路径越界/文件超限/池不支持查看均返回 400，message 说明原因。"""

    try:
        content = await backup_service(scriptId, userId).read_backup_file(
            target, time, path
        )
        return MaaEndBackupFileOut(
            code=200,
            status="success",
            message="",
            time=time,
            target=target,
            path=content["path"],
            size=content["size"],
            content=content["content"],
        )
    except Exception as error:
        logger.opt(exception=True).warning(f"配置备份文件读取失败: {error}")
        return MaaEndBackupFileOut(
            code=_error_code(error),
            status="error",
            message=f"{type(error).__name__}: {error}",
            time=time,
            target=target,
            path=path,
            size=0,
            content="",
        )
