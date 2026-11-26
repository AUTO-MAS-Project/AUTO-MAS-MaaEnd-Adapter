"""插件声明与执行器接线检查（不启动真实任务）。"""

from auto_mas_core import (
    AutoProxyWorker,
    ScriptConfigWorker,
    ScriptViewWorker,
    TaskMode,
)

from auto_mas_maaend_adapter.auto_proxy import AutoProxyTask
from auto_mas_maaend_adapter.config_session import ScriptConfigTask, ScriptViewTask
from auto_mas_maaend_adapter.expander import MaaEndExpander
from auto_mas_maaend_adapter.plugin import Plugin


def test_decl_covers_three_modes_and_configs():
    plugin = Plugin()
    assert plugin.script_type_key == "MaaEnd"
    assert plugin.decl.script_type.__name__ == "MaaEndConfig"
    assert plugin.decl.user_type.__name__ == "MaaEndUserConfig"
    assert plugin.decl.plan_type.__name__ == "MaaEndPlanConfig"
    assert plugin.decl.expander_class is MaaEndExpander
    assert set(plugin.decl.supported_modes) == {
        TaskMode.AUTO_PROXY,
        TaskMode.SCRIPT_CONFIG,
        TaskMode.SCRIPT_VIEW,
    }


def test_decl_declares_desktop_session_capability():
    """分身能力按控制器协议声明，游戏类型也按控制器动态收窄。"""
    decl = Plugin().decl
    assert decl.desktop_session_check is not None
    assert decl.game_kind is not None
    assert decl.game_kinds == ("emulator", "client")


def test_script_config_keeps_execution_session_field():
    """内置实现里 Run.ExecutionSession 随 MaaEndConfig 一起存在，插件版要保留。"""
    from auto_mas_maaend_adapter.config import MaaEndConfig

    config = MaaEndConfig.model_validate({})
    assert config.Run.ExecutionSession == "main"


def test_api_routes_keep_host_paths():
    paths = {route.path for route in Plugin().api_router.routes}
    assert "/api/scripts/maaend/options" in paths
    assert "/api/scripts/maaend/launcher-path" in paths
    assert "/api/scripts/maaend/log-bundle" in paths


def test_workers_use_plugin_bases():
    assert issubclass(AutoProxyTask, AutoProxyWorker)
    assert AutoProxyTask.mode is TaskMode.AUTO_PROXY
    assert issubclass(ScriptConfigTask, ScriptConfigWorker)
    assert ScriptConfigTask.mode is TaskMode.SCRIPT_CONFIG
    assert issubclass(ScriptViewTask, ScriptViewWorker)
    assert ScriptViewTask.mode is TaskMode.SCRIPT_VIEW
