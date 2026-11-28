"""MaaEnd 面板需要的上下文及宿主操作。"""

import asyncio
from pathlib import Path
from typing import Annotated
from uuid import UUID

from auto_mas_core import Config, Plugin
from auto_mas_core.host.core import GameManager, TaskManager
from auto_mas_core.host.task_client import client_executable_path, client_launcher_path
from auto_mas_core.host.utils import MAAEND_INVENTORY_TARGET_DEFAULTS
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .api import MaaEndOptionsOut, MaaEndService
from .config import MaaEndConfig, MaaEndPlanConfig, MaaEndUserConfig
from .config_service import MaaEndConfigService
from .resource_loader import get_loaded_maaend_options

PLUGIN_ID = "maaend_adapter"
router = APIRouter()


def _authorize(request: Request, entry, page: str) -> None:
    if (
        request.headers.get("x-plugin-ui-provider") != PLUGIN_ID
        or request.headers.get("x-plugin-ui-page") != page
    ):
        raise HTTPException(403, "面板与配置类型不匹配")
    mount = Plugin.frontend_block_pages(entry).get(page)
    if mount is None or mount.activationId != request.headers.get(
        "x-plugin-ui-activation"
    ):
        raise HTTPException(409, "插件界面已失效，请重新打开")


def _script(script_id: UUID) -> MaaEndConfig:
    script = Config.ScriptConfig.get(script_id)
    if not isinstance(script, MaaEndConfig):
        raise HTTPException(404, "找不到 MaaEnd 托管")
    return script


async def _script_panel(request: Request, script_id: UUID) -> MaaEndConfig:
    script = _script(script_id)
    _authorize(request, script, "script")
    return script


async def _user_panel(
    request: Request, script_id: UUID, user_id: UUID
) -> MaaEndUserConfig:
    user = _script(script_id).users.get(user_id)
    if not isinstance(user, MaaEndUserConfig):
        raise HTTPException(404, "找不到 MaaEnd 账号")
    _authorize(request, user, "user")
    return user


async def _plan_panel(request: Request, plan_id: UUID) -> MaaEndPlanConfig:
    plan = Config.PlanConfig.get(plan_id)
    if not isinstance(plan, MaaEndPlanConfig):
        raise HTTPException(404, "找不到 MaaEnd 计划表")
    _authorize(request, plan, "plan")
    return plan


ScriptPanel = Annotated[MaaEndConfig, Depends(_script_panel)]
UserPanel = Annotated[MaaEndUserConfig, Depends(_user_panel)]
PlanPanel = Annotated[MaaEndPlanConfig, Depends(_plan_panel)]


@router.get("/editor/script/{script_id}")
async def script_context(script: ScriptPanel):
    return {
        "path": script.Info.Path,
        "executable": client_executable_path(script),
        "launcher": client_launcher_path(script),
    }


class LauncherPatch(BaseModel):
    path: Path | None


@router.put("/editor/script/{script_id}/launcher")
async def update_launcher(script: ScriptPanel, patch: LauncherPatch):
    if script.is_locked:
        raise HTTPException(409, "托管正在运行")
    if client_executable_path(script) is None:
        raise HTTPException(422, "请先绑定终末地客户端")
    try:
        MaaEndConfigService.validate_update({"Game": {"LauncherPath": patch.path}})
        await GameManager.update(
            script.game.game_id, {"info": {"launch_path": patch.path}}
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return await script_context(script)


@router.get("/editor/user/{script_id}/{user_id}")
async def user_context(script_id: UUID, user: UserPanel):
    script = _script(script_id)
    return {
        "path": script.Info.Path,
        "controller": script.Game.ControllerType,
        "base": user.Info.Base,
        "quickConfig": user.Info.IfQuickConfig,
        "sanityStrategy": user.Info.SanityStrategy,
        "sanityMode": user.Info.SanityMode,
        "essenceMode": user.Info.AutoEssenceMode,
        "inventoryDefaults": MAAEND_INVENTORY_TARGET_DEFAULTS,
        "plans": {
            str(uid): {"name": plan.Info.Name, "key": plan.get_current_key()}
            for uid, plan in Config.PlanConfig.items()
            if isinstance(plan, MaaEndPlanConfig)
            and uid in (user.Info.SanityMode, user.Info.AutoEssenceMode)
        },
    }


@router.post("/editor/user/{script_id}/{user_id}/import")
async def import_config(script_id: UUID, user: UserPanel):
    if user.is_locked or _script(script_id).is_locked:
        raise HTTPException(409, "配置正在使用")
    if user.Info.Base == "native":
        raise HTTPException(422, "原生来源直接使用 MaaEnd 原有配置")
    owner = None if user.Info.Base == "shared" else str(user.uid)
    try:
        await Config.import_script_config_file(str(script_id), owner)
    except (OSError, ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True}


@router.get("/editor/plan/{plan_id}")
async def plan_context(plan: PlanPanel):
    return {"mode": plan.Info.Mode, "rotateDays": plan.Info.RotateDays}


@router.get("/editor/plan/{plan_id}/options")
async def plan_options(_plan: PlanPanel) -> MaaEndOptionsOut:
    paths = dict.fromkeys(
        script.Info.Path
        for script in Config.ScriptConfig.values()
        if isinstance(script, MaaEndConfig) and script.Info.Path is not None
    )
    resources = await asyncio.gather(
        *(asyncio.to_thread(get_loaded_maaend_options, path) for path in paths),
        return_exceptions=True,
    )
    choices = {
        name: {} for name in ("crisisDrills", "essenceLocations", "essenceMenus")
    }
    weapons = {}
    failures = []
    for resource in resources:
        if isinstance(resource, Exception):
            failures.append(str(resource))
            continue
        for name, values in choices.items():
            for item in resource[name]:
                values.setdefault(item["value"], item)
        for group in resource["essenceTargetWeaponGroups"]:
            title, options = weapons.setdefault(group["value"], (group["label"], {}))
            for item in group["options"]:
                options.setdefault(item["value"], item)
    if failures and len(failures) == len(resources):
        raise HTTPException(422, failures[0])
    return MaaEndOptionsOut(
        controllers=[],
        controllerTypes={},
        essenceTargetWeaponGroups=[
            {"value": value, "label": label, "options": list(options.values())}
            for value, (label, options) in weapons.items()
        ],
        **{name: list(values.values()) for name, values in choices.items()},
    )


@router.post("/editor/script/{script_id}/update")
async def start_update(script: ScriptPanel, service: MaaEndService):
    if script.is_locked:
        raise HTTPException(409, "托管正在运行")
    try:
        task_id = await TaskManager.start_maintenance(str(script.uid))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
    service.panel_updates[script.uid] = task_id
    return {"taskId": task_id}


@router.get("/editor/script/{script_id}/update")
async def update_status(script: ScriptPanel, service: MaaEndService):
    task_id = service.panel_updates.get(script.uid)
    if task_id is None:
        return None
    task = TaskManager.get_task(task_id)
    if task is None:
        service.panel_updates.pop(script.uid)
        return None
    return {
        "taskId": task_id,
        "status": task["info"]["status"],
        "log": "\n".join(
            item["current"]["log"] or "" for item in task["scripts"]["data"].values()
        )[-20000:],
    }


@router.post("/editor/script/{script_id}/update/{task_id}/stop")
async def stop_update(script: ScriptPanel, task_id: UUID, service: MaaEndService):
    if task_id == service.panel_updates.get(script.uid):
        await TaskManager.stop(task_id)
    return await update_status(script, service)
