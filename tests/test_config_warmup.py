"""配置服务预热：读取选项时把历史 Client 启动方式迁移到 MaaEnd/MAS。"""

import asyncio

import pytest

from auto_mas_maaend_adapter import config_service as config_service_module
from auto_mas_maaend_adapter.config import MaaEndConfig
from auto_mas_maaend_adapter.config_service import MaaEndConfigService


def _service(script):
    return MaaEndConfigService(
        scripts={script.uid: script},
        read_resolution=lambda path: None,
        read_display_type=lambda exe, *, preferred_value_name: None,
    )


@pytest.mark.asyncio
async def test_get_options_migrates_legacy_client_launch_mode(
    monkeypatch, tmp_path_factory
):
    """历史 Client 值在第一次读选项时按本体资源迁移，后续读取保持不变。"""

    install = tmp_path_factory.mktemp("maaend-warmup")
    (install / "interface.json").write_text("{}", encoding="utf-8")
    script = MaaEndConfig.build(
        payload={
            "Info": {"Name": "预热测试", "Path": str(install)},
            "Game": {"LaunchMode": "Client", "ControllerType": "Win32-Front"},
        }
    )
    await script.activate()
    service = _service(script)

    monkeypatch.setattr(
        config_service_module,
        "try_load_maaend_options",
        lambda path: {
            "launchGameControllers": ["Win32-Front"],
            "essenceLocations": [],
            "crisisDrills": [],
        },
    )
    monkeypatch.setattr(
        config_service_module,
        "get_loaded_maaend_options",
        lambda path: {"marker": "ok"},
    )
    monkeypatch.setattr(
        config_service_module, "client_executable_path", lambda script: None
    )

    first = await service.get_options(str(script.uid))
    await asyncio.sleep(0)
    assert script.Game.LaunchMode == "MaaEnd"
    second = await service.get_options(str(script.uid))
    await asyncio.sleep(0)
    await service.aclose()

    assert first["marker"] == second["marker"] == "ok"
    assert script.Game.LaunchMode == "MaaEnd"
