"""从旧手动更新入口验证迁移后的调度、日志与停止。"""

import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from app.api.scripts import operations
from app.config import ConfigCollection
from app.core import Config, Publisher
from app.core import Plugin as Plugins
from app.core.task_manager import _TaskManager
from app.core.ws import protocol
from app.models.config import PluginRecord
from app.utils.common.game_update import GameUpdateResult

from auto_mas_maaend_adapter import manual_update
from auto_mas_maaend_adapter.plugin import Plugin


@pytest_asyncio.fixture
async def scheduler(monkeypatch, isolated_host):
    decl = Plugin().decl
    scripts = ConfigCollection.build([decl.script_type])
    await scripts.activate()
    manager = _TaskManager(plugin_expander=Plugins.resolve_script_expander)
    monkeypatch.setattr(Config, "ScriptConfig", scripts)
    monkeypatch.setattr(Publisher, "send", AsyncMock(return_value=True))
    monkeypatch.setattr(operations, "TaskManager", manager)
    yield manager, scripts
    await manager.stop("ALL")


@pytest.mark.parametrize(
    ("outcome", "task_status", "user_status"),
    [
        ("UpToDate", "success", "完成"),
        ("Skipped", "success", "跳过"),
        ("NeedManualUpdate", "error", "异常"),
        ("cancelled", "cancelled", "异常"),
    ],
)
async def test_manual_update_uses_managed_script_without_accounts(
    scheduler, monkeypatch, tmp_path_factory, outcome, task_status, user_status
):
    manager, scripts = scheduler
    decl = Plugin().decl
    record = PluginRecord.build(
        info={"plugin_name": "maaend_adapter", "state": "enabled"}
    )
    await record.activate()
    monkeypatch.setattr(Plugins, "script_types", {record.uid: decl})
    monkeypatch.setattr(Plugins, "list_plugins", lambda: [record])
    monkeypatch.setattr(
        manual_update, "load_maaend_controller_protocol", lambda *_: "Win32"
    )
    install = tmp_path_factory.mktemp("maaend-manual-update")
    executable = install / "Endfield.exe"
    executable.touch()
    (install / "MaaEnd.exe").touch()
    monkeypatch.setattr(manual_update, "client_executable_path", lambda _: executable)
    script_id = scripts.add(
        decl.script_type,
        payload={
            "Info": {"Path": str(install)},
            "Game": {"ControllerType": "Win32", "IfAutoUpdate": False},
        },
    )
    await scripts.commit()
    assert not scripts[script_id].users and not scripts[script_id].Game.IfAutoUpdate

    entered = asyncio.Event()
    stopped = asyncio.Event()
    ended = asyncio.Event()
    conclusion = "测试更新结论"

    async def update(path, *, time_limit_minutes, progress, entry):
        assert path == executable and entry == "手动"
        assert time_limit_minutes == scripts[script_id].Game.UpdateTimeLimit
        await progress("读取更新清单")
        entered.set()
        if outcome == "cancelled":
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        return GameUpdateResult(outcome, conclusion)

    async def on_ended(*_, **__):
        ended.set()

    monkeypatch.setattr(manual_update, "ensure_game_updated", update)
    manager.task_ended.connect(on_ended, sender=manager)
    try:
        result = await operations.start_operation(
            operations.ScriptOperationIn(targetId=str(script_id))
        )
        assert result.code == 200, result.message
        if outcome == "cancelled":
            await asyncio.wait_for(entered.wait(), timeout=4)
            assert not manager.get_runtime_snapshot().tasks
            await asyncio.wait_for(manager.stop(result.taskId), timeout=4)
            assert stopped.is_set()
        await asyncio.wait_for(ended.wait(), timeout=4)
    finally:
        manager.task_ended.disconnect(on_ended, sender=manager)

    status = manager.get_task_status(result.taskId)
    assert status.status == task_status
    tree = manager.get_task(result.taskId)
    (script,) = tree["scripts"]["data"].values()
    assert "读取更新清单" in script["current"]["log"]
    if outcome != "cancelled":
        assert conclusion in script["current"]["log"]
    (user,) = script["users"]["data"].values()
    assert user["info"]["user_id"] == "default"
    assert user["info"]["name"] == "终末地客户端更新"
    assert user["info"]["status"] == user_status
    if outcome == "NeedManualUpdate":
        assert any(
            call.kwargs["id"] == result.taskId
            and call.kwargs["type"] == protocol.TASK_NOTICE
            and call.kwargs["data"].sourceScriptType == "MaaEnd"
            and call.kwargs["data"].message == conclusion
            for call in Publisher.send.call_args_list
        )
