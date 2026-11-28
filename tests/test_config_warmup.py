"""托管初始化时迁移启动方式，并在首次读取之前预热账号标签。"""

import json

import pytest
from app.core.background_tasks import BackgroundTaskRegistry

from auto_mas_maaend_adapter import config_service as config_service_module
from auto_mas_maaend_adapter.config import MaaEndConfig, MaaEndUserConfig
from auto_mas_maaend_adapter.config_service import MaaEndConfigService
from auto_mas_maaend_adapter.plugin import Plugin


@pytest.mark.parametrize(
    ("launch_mode", "controller", "expected"),
    [
        ("Client", "Win32-Front", "MaaEnd"),
        ("Client", "Win32-Other", "MAS"),
        ("Launcher", "Win32-Front", "Launcher"),
    ],
)
async def test_plugin_initialization_preloads_before_reading_options(
    monkeypatch, tmp_path_factory, launch_mode, controller, expected
):
    install = tmp_path_factory.mktemp("maaend-warmup")
    (install / "interface.json").write_text("{}", encoding="utf-8")
    script = MaaEndConfig.build(
        payload={
            "Info": {"Name": "预热测试", "Path": str(install)},
            "Game": {"LaunchMode": launch_mode, "ControllerType": controller},
        }
    )
    await script.activate()
    uid = script.users.add(
        MaaEndUserConfig,
        payload={
            "Info": {"SanityStrategy": "MAS"},
            "Task": {
                "IfProtocolSpace": True,
                "SanityTaskType": "CrisisDrills",
                "CrisisDrills": "CrisisDrillsTest",
            },
        },
    )
    await script.users.commit()
    user = script.users[uid]

    service = MaaEndConfigService(
        scripts={script.uid: script},
        read_resolution=lambda path: None,
        read_display_type=lambda exe, *, preferred_value_name: None,
    )
    resources = {
        "launchGameControllers": ["Win32-Front"],
        "crisisDrills": [{"value": "CrisisDrillsTest", "label": "测试关卡名称"}],
    }
    monkeypatch.setattr(
        config_service_module, "try_load_maaend_options", lambda path: resources
    )
    monkeypatch.setattr(
        config_service_module, "get_loaded_maaend_options", lambda path: resources
    )
    monkeypatch.setattr(
        config_service_module, "client_executable_path", lambda script: None
    )

    manager = BackgroundTaskRegistry()
    group = manager.register_group("test-maaend", max_running=1, max_retained=1)
    plugin = Plugin()
    plugin.bind_background_tasks(group)
    plugin._config_service = service
    try:
        assert "测试关卡名称" not in user.Info.Tag
        await plugin.initialize(script)
        assert await group.drain(timeout=5)
        assert script.Game.LaunchMode == expected
        assert "详细任务：测试关卡名称" in {
            item["text"] for item in json.loads(user.Info.Tag)
        }
        assert await service.get_options(str(script.uid)) == resources
    finally:
        await manager.unregister_group(group)
