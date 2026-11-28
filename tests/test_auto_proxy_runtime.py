"""从托管运行入口核对账号准入、MaaEnd 写盘队列和游戏收尾。"""

import asyncio
import base64
import json
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.core import History, MaaFWManager
from app.models.emulator import DeviceInfo, DeviceStatus
from app.models.game_maintenance import MaintenanceWindow
from app.models.task import TaskItem, TaskMode, TaskScriptItem, TaskUserItem
from app.services import script_install
from app.task.history_core import TaskHistorySession
from app.utils import MAAEND_TASKS, UTC4
from app.utils.common.io import (
    commit_native_config_snapshot,
    mark_native_config_injected,
)

from auto_mas_maaend_adapter import auto_proxy, expander
from auto_mas_maaend_adapter.config import MaaEndConfig, MaaEndUserConfig

TASK_NAMES = ("SeizeDeliveryJobs", "AutoEssence", "ProtocolSpace", "CloseGamePC")


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def installation(tmp_path_factory):
    root = tmp_path_factory.mktemp("maaend-runtime")
    (root / "resource").mkdir()
    for executable in ("MaaEnd.exe", "Endfield.exe"):
        (root / executable).touch()
    _write_json(
        root / "interface.json",
        {
            "interface_version": 2,
            "name": "MaaEnd",
            "languages": {"zh_cn": "zh.json"},
            "controller": [
                {"name": "Win32-Front", "type": "Win32", "win32": {}},
                {"name": "Adb", "type": "Adb", "adb": {}},
                {"name": "CloudADB", "type": "Adb", "adb": {}},
            ],
            "resource": [{"name": "Default", "path": ["resource"]}],
            "import": ["ProtocolSpace.json"],
        },
    )
    _write_json(
        root / "zh.json",
        {"task.SceneManager.focus.color_match_failed_prefix": "颜色识别失败"},
    )
    options = {
        "ProtocolSpaceMode": {
            "type": "select",
            "cases": [{"name": "TargetInventory"}, {"name": "ByCount"}],
        },
        "SupplyPlanLimits": {
            "type": "input",
            "inputs": [{"name": "material", "label": "测试材料", "verify": "[0-9]+"}],
        },
        "ProtocolSpaceObtainModeClaim": {
            "type": "select",
            "cases": [{"name": "ObtainScaling2"}],
        },
        "ProtocolSpaceUseSpMedication": {
            "type": "select",
            "cases": [{"name": "UseMedication"}, {"name": "EndTask"}],
        },
    }
    _write_json(
        root / "ProtocolSpace.json",
        {
            "task": [
                {
                    "name": name,
                    "label": name,
                    "entry": name,
                    "option": list(options) if name == "ProtocolSpace" else [],
                }
                for name in (*TASK_NAMES, "AccountSwitch", "AndroidOpenGame")
            ],
            "option": options,
            "pretask": [{"name": "LaunchGamePC", "controller": ["Win32-Front"]}],
        },
    )
    return root


async def _build_task(
    root, accounts, *, controller="Win32-Front", close=False, takeover=False
):
    config = MaaEndConfig.build(
        payload={
            "Info": {"Name": "测试托管", "Path": str(root)},
            "Game": {
                "ControllerType": controller,
                "LaunchMode": "MaaEnd",
                "CloseOnFinish": close,
                "SetResolution": False,
            },
            "Run": {"RunTimesLimit": 2, "IfSaveLogBundle": False},
            "Update": {"TakeoverEnabled": takeover},
        }
    )
    await config.activate()
    task = TaskItem(info={"mode": TaskMode.AUTO_PROXY})
    await task.activate()
    script_id = task.scripts.add(
        TaskScriptItem,
        payload={"info": {"script_id": str(config.uid), "name": "测试托管"}},
    )
    await task.scripts.commit()
    script = task.scripts[script_id]
    for i, payload in enumerate(accounts):
        uid = config.users.add(MaaEndUserConfig, payload=payload)
        script.users.add(
            TaskUserItem,
            payload={"info": {"user_id": str(uid), "name": f"账号 {i + 1}"}},
        )
    await config.users.commit()
    await script.users.commit()
    runner = expander.MaaEndExpander(script, config)
    runner.history = TaskHistorySession(task)
    return runner


def _write_queue(root, runner, enabled=TASK_NAMES, *, use_native=False):
    native_path = root / "config/mxu-MaaEnd.json"
    installed_config = {
        "instances": [{"id": "automas", "tasks": []}],
        "settings": {"language": "zh-CN"},
    }
    _write_json(native_path, installed_config)
    queue_path = (
        native_path
        if use_native
        else (
            Path("data")
            / runner.script_info.script_id
            / "Default/ConfigFile/mxu-MaaEnd.json"
        )
    )
    _write_json(
        queue_path,
        {
            **installed_config,
            "instances": [
                {
                    "id": "automas",
                    "name": "AUTO-MAS",
                    "tasks": [
                        {
                            "id": name,
                            "taskName": name,
                            "enabled": name in enabled,
                            "optionValues": {
                                "preserved": {"type": "switch", "value": True}
                            },
                        }
                        for name in TASK_NAMES
                    ],
                }
            ],
        },
    )
    return native_path


@pytest.fixture
def runtime(monkeypatch, installation):
    """MaaEnd 安装与写盘保持真实，只替换终末地及 MaaEnd 进程、网络和截图。"""
    launches = []
    attached_devices = []
    start_game, close_game = AsyncMock(), AsyncMock()
    monkeypatch.setattr(
        expander, "client_executable_path", lambda _: installation / "Endfield.exe"
    )
    monkeypatch.setattr(expander, "client_launcher_path", lambda _: None)
    monkeypatch.setattr(auto_proxy.AutoProxyTask, "_start_game", start_game)
    monkeypatch.setattr(
        auto_proxy.AutoProxyTask, "_capture_failure_shot", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        auto_proxy, "ClientProcess", lambda: SimpleNamespace(kill=close_game)
    )
    monkeypatch.setattr(auto_proxy.process, "kill_process", AsyncMock())
    monkeypatch.setattr(
        auto_proxy, "update_maaend_after_stage", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        expander.GameMaintenance, "get_active", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(expander.Notify, "send_notice", AsyncMock())
    monkeypatch.setattr(expander.Notify, "push_proxy_result", AsyncMock())
    monkeypatch.setattr(History, "record", AsyncMock())
    sleep = asyncio.sleep

    async def fast_sleep(delay, result=None):
        return await sleep(0 if delay in (1, 3) else delay, result)

    monkeypatch.setattr(auto_proxy.asyncio, "sleep", fast_sleep)

    async def launch(*args, **kwargs):
        settings = json.loads((installation / "config/mxu-MaaEnd.json").read_text())
        instance = settings["instances"][0]
        launches.append([task for task in instance["tasks"] if task["enabled"]])
        attached_devices.append(instance.get("savedDevice"))

    monkeypatch.setattr(
        auto_proxy,
        "ProcessManager",
        lambda: SimpleNamespace(
            open_process=launch, kill=AsyncMock(), launched_process=None
        ),
    )

    async def run_maaend_output(worker, offsets):
        lines = [
            line
            for task in launches[-1]
            for line in (
                f"任务开始: {task['taskName']}\n",
                f"任务完成: {task['taskName']}\n",
            )
        ]
        await worker.check_log(lines, datetime.now().astimezone(), if_stream_end=True)

    monkeypatch.setattr(
        auto_proxy.AutoProxyTask, "_wait_maaend_stage", run_maaend_output
    )
    return SimpleNamespace(
        launches=launches,
        attached_devices=attached_devices,
        start_game=start_game,
        close_game=close_game,
    )


@pytest.mark.parametrize(
    ("scenario", "routine"),
    [
        ("both", ["ProtocolSpace", "AutoEssence"]),
        ("stock_completed", ["AutoEssence"]),
        ("essence_off", ["ProtocolSpace"]),
        ("native", ["ProtocolSpace", "AutoEssence"]),
        ("essence_retry", ["ProtocolSpace", "AutoEssence"]),
        ("delivery_failure", []),
    ],
)
async def test_stage_queue_keeps_each_task_independent(
    installation, runtime, monkeypatch, scenario, routine
):
    """送货失败阻断日常，已完成的日常节点即使同阶段重试也不再入队。"""
    runner = await _build_task(
        installation,
        [
            {
                "Info": {
                    "SanityStrategy": "Native" if scenario == "native" else "Inventory",
                    "AutoEssenceMode": "Native" if scenario == "native" else "Fixed",
                },
                "Task": {
                    **{f"If{name}": False for name in MAAEND_TASKS},
                    "IfSanity": True,
                    "IfSeizeDeliveryJobs": True,
                    "IfProtocolSpace": True,
                    "IfAutoEssence": scenario != "essence_off",
                    "IfAutoCollect": False,
                    "AutoEssenceSpecifiedLocation": "test_location",
                    "SupplyPlanLimits": '{"material":"10"}',
                    "DailyOnceTasks": '["ProtocolSpace", "AutoEssence"]',
                },
                "Data": {
                    "PeriodTaskRecords": json.dumps(
                        {
                            "daily": {
                                "ProtocolSpace": datetime.now(tz=UTC4).strftime(
                                    "%Y-%m-%d"
                                )
                            }
                        }
                    )
                }
                if scenario == "stock_completed"
                else {},
            }
        ],
    )
    native_path = _write_queue(installation, runner)
    original_native = native_path.read_bytes()

    async def upstream_result(worker, offsets):
        lines = []
        for task in runtime.launches[-1]:
            name = task["taskName"]
            failure = (
                scenario == "delivery_failure" and name == "SeizeDeliveryJobs"
            ) or (
                scenario == "essence_retry"
                and len(runtime.launches) == 2
                and name == "AutoEssence"
            )
            result = "失败" if failure else "完成"
            lines.extend([f"任务开始: {name}\n", f"任务{result}: {name}\n"])
        await worker.check_log(lines, datetime.now().astimezone(), if_stream_end=True)

    monkeypatch.setattr(auto_proxy.AutoProxyTask, "_wait_maaend_stage", upstream_result)
    await asyncio.wait_for(runner.run(), timeout=5)

    expected = [["SeizeDeliveryJobs"]]
    if scenario == "delivery_failure":
        expected.append(["SeizeDeliveryJobs"])
    else:
        expected.append(routine)
    if scenario == "essence_retry":
        expected.append(["AutoEssence"])
    assert [[t["taskName"] for t in queue] for queue in runtime.launches] == expected
    assert runner.script_info.user_list[0].status == (
        "异常" if scenario == "delivery_failure" else "完成"
    )
    if scenario == "native":
        assert [task["optionValues"] for task in runtime.launches[1]] == [
            {"preserved": {"type": "switch", "value": True}},
            {"preserved": {"type": "switch", "value": True}},
        ]
    elif "ProtocolSpace" in routine:
        assert (
            runtime.launches[1][0]["optionValues"]["ProtocolSpaceMode"]["caseName"]
            == "TargetInventory"
        )
    assert native_path.read_bytes() == original_native


def _bound_emulator(runner, monkeypatch):
    device = DeviceInfo("测试设备", DeviceStatus.ONLINE, "127.0.0.1:5555")
    emulator = SimpleNamespace(open=AsyncMock(return_value=device), close=AsyncMock())
    runner.game_session = SimpleNamespace(
        control=object(),
        emulator=emulator,
        select=AsyncMock(),
        release_account=AsyncMock(),
        cleanup_failed=False,
    )
    monkeypatch.setattr(expander, "game_target_id", lambda _: "emulator")
    monkeypatch.setattr(expander, "game_device_id", lambda _: "device")
    monkeypatch.setattr(auto_proxy, "game_device_id", lambda _: "device")
    monkeypatch.setattr(
        MaaFWManager,
        "convert_adb",
        AsyncMock(return_value=SimpleNamespace(name=device.title)),
    )
    return emulator


@pytest.mark.parametrize("controller", ["Win32-Front", "Adb"])
async def test_empty_queue_leaves_game_and_emulator_untouched(
    controller, installation, runtime, monkeypatch
):
    runner = await _build_task(
        installation, [{"Info": {"IfQuickConfig": False}}], controller=controller
    )
    _write_queue(installation, runner, ())
    emulator = _bound_emulator(runner, monkeypatch) if controller == "Adb" else None

    await asyncio.wait_for(runner.run(), timeout=5)

    runtime.start_game.assert_not_awaited()
    runtime.close_game.assert_not_awaited()
    if emulator is not None:
        emulator.open.assert_not_awaited()
        emulator.close.assert_not_awaited()
    assert runtime.launches == []
    user = runner.script_info.user_list[0]
    assert user.status == "异常"
    assert len(user.logs) == 1
    assert "没有可执行任务" in user.result


@pytest.mark.parametrize(
    ("controller", "package", "tasks"),
    [
        ("Adb", "com.hypergryph.endfield", ["ProtocolSpace"]),
        ("CloudADB", "", ["AndroidOpenGame", "ProtocolSpace"]),
    ],
)
async def test_emulator_uses_bound_device_and_keeps_it_running(
    controller, package, tasks, installation, runtime, monkeypatch
):
    runner = await _build_task(
        installation, [{"Info": {"IfQuickConfig": False}}], controller=controller
    )
    _write_queue(installation, runner, ("ProtocolSpace",))
    emulator = _bound_emulator(runner, monkeypatch)

    await asyncio.wait_for(runner.run(), timeout=5)

    emulator.open.assert_awaited_once_with("device", package)
    assert runtime.attached_devices == [{"adbDeviceName": "测试设备"}]
    assert [[task["taskName"] for task in queue] for queue in runtime.launches] == [
        tasks
    ]
    assert runner.script_info.user_list[0].status == "完成"
    emulator.close.assert_not_awaited()


async def test_trailing_disabled_and_expired_accounts_do_not_run_or_close_game(
    installation, runtime
):
    runner = await _build_task(
        installation,
        [
            {"Info": {"IfQuickConfig": False, "RemainedDay": 1}},
            {"Info": {"IfQuickConfig": False, "Status": False}},
            {"Info": {"IfQuickConfig": False, "RemainedDay": 0}},
        ],
    )
    _write_queue(installation, runner, ("ProtocolSpace",))

    await asyncio.wait_for(runner.run(), timeout=5)

    assert [user.status for user in runner.script_info.user_list] == [
        "完成",
        "跳过",
        "跳过",
    ]
    configs = list(runner.script_config.users.values())
    assert [account.Info.RemainedDay for account in configs] == [0, -1, 0]
    assert runtime.start_game.await_count == 1
    runtime.close_game.assert_not_awaited()


@pytest.mark.parametrize("stopped", [False, True])
async def test_update_progress_queue_finishes_and_keeps_terminal_result(
    installation, runtime, monkeypatch, stopped
):
    runner = await _build_task(installation, [{"Info": {"IfQuickConfig": False}}])
    _write_queue(installation, runner, ("ProtocolSpace",))
    progress_queued = asyncio.Event()

    async def publish_status(root_path, log_offsets, *, on_status, **kwargs):
        on_status("下载完成")
        on_status("开始应用更新")
        progress_queued.set()
        if stopped:
            await asyncio.Future()
        return None

    monkeypatch.setattr(auto_proxy, "update_maaend_after_stage", publish_status)
    if stopped:
        runner.start()
        try:
            await asyncio.wait_for(progress_queued.wait(), timeout=5)
        finally:
            await asyncio.wait_for(runner.stop(), timeout=5)
    else:
        await asyncio.wait_for(runner.run(), timeout=5)

    user = runner.script_info.user_list[0]
    (update_log,) = (
        record for record in user.logs.values() if record.phase == "Update"
    )
    assert update_log.content == ["下载完成\n", "开始应用更新\n"]
    assert update_log.status == ("MaaEnd 更新被中止" if stopped else "跳过更新")
    assert user.status == ("已取消" if stopped else "完成")


@pytest.mark.parametrize("failure", ["swapped_install", "invalid_interface"])
async def test_recovery_restores_install_and_previous_native_queue_before_check(
    installation, runtime, failure
):
    runner = await _build_task(
        installation, [{"Info": {"IfQuickConfig": False, "Base": "native"}}]
    )
    native_path = _write_queue(
        installation, runner, ("ProtocolSpace",), use_native=True
    )
    original_config = native_path.read_bytes()
    script_id = runner.script_info.script_id
    snapshot = Path("data") / script_id / "Temp"
    assert commit_native_config_snapshot(
        snapshot, native_path.parent, script_id=script_id
    )
    _write_json(native_path, {"injected": True})
    mark_native_config_injected(snapshot, native_path.parent, script_id=script_id)

    interface = installation / "interface.json"
    original_interface = interface.read_bytes()
    workspace = script_install.workspace(installation)
    if failure == "swapped_install":
        journal = workspace / "transaction.json"
        _write_json(
            journal,
            {
                "root": str(installation.resolve()),
                "files": {},
                "original_files": script_install.tree_hashes(installation, Event()),
            },
        )
        installation.rename(workspace / "previous")
    else:
        journal = workspace / "runtime-interface.json"
        _write_json(
            journal,
            {
                "original": base64.b64encode(original_interface).decode(),
                "injected": base64.b64encode(b"{}").decode(),
            },
        )
        interface.write_bytes(b"{}")

    await asyncio.wait_for(runner.run(), timeout=5)

    assert (installation / "MaaEnd.exe").is_file()
    assert interface.read_bytes() == original_interface
    assert native_path.read_bytes() == original_config
    assert not journal.exists()
    assert [[task["taskName"] for task in queue] for queue in runtime.launches] == [
        ["ProtocolSpace"]
    ]
    assert runner.script_info.user_list[0].status == "完成"


async def test_all_users_in_maintenance_leave_installation_untouched(
    installation, runtime, monkeypatch
):
    runner = await _build_task(
        installation,
        [{"Info": {"RemainedDay": 1}}, {"Info": {"RemainedDay": 0}}],
        takeover=True,
    )
    # 待恢复的记录无法解析。进入安装恢复会报错，只有在维护检查提前返回时才能保留。
    journal = script_install.workspace(installation) / "runtime-interface.json"
    _write_json(journal, {"interrupted": True})
    before = journal.read_bytes()
    notice = AsyncMock()
    monkeypatch.setattr(expander, "push_maintenance_notice", notice)
    now = datetime.now().astimezone()
    window = MaintenanceWindow(now - timedelta(hours=1), now + timedelta(hours=1))
    monkeypatch.setattr(
        expander.GameMaintenance, "get_active", AsyncMock(return_value=window)
    )

    await asyncio.wait_for(runner.run(), timeout=5)

    assert runner.script_info.status == "跳过"
    maintained, expired = runner.script_info.user_list
    assert (maintained.status, expired.status) == ("跳过", "跳过")
    assert "游戏维护中" in maintained.result
    assert "剩余天数不足" in expired.result
    assert journal.read_bytes() == before
    runtime.start_game.assert_not_awaited()
    runtime.close_game.assert_not_awaited()
    notice.assert_awaited_once()
