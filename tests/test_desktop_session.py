"""分身详情读取和共享游戏安装目录的进程保护。"""

import json
from threading import get_ident
from unittest.mock import AsyncMock, Mock

import pytest
from app.api.scripts.management import ScriptGetIn, get_script
from app.config import ConfigCollection
from app.core import Config, Plugin
from app.core.desktop_session.lifecycle import task_unavailable_reason
from app.models.config import PluginRecord
from app.plugin.calls import CallGate
from app.utils import process as process_api
from app.utils.common.process import operations, session

from auto_mas_maaend_adapter import plugin as maaend_plugin
from auto_mas_maaend_adapter.tools.update.checks import _release_install_dir


@pytest.mark.parametrize(
    ("controller", "supported"), [("Desktop", True), ("Android", False)]
)
async def test_script_detail_reads_controller_off_event_loop(
    monkeypatch, tmp_path_factory, controller, supported
):
    install = tmp_path_factory.mktemp("maaend-desktop-support")
    (install / "zh_cn.json").write_text("{}", encoding="utf-8")
    (install / "interface.json").write_text(
        json.dumps(
            {
                "languages": {"zh_cn": "zh_cn.json"},
                "import": [],
                "controller": [
                    {"name": "Desktop", "type": "Win32"},
                    {"name": "Android", "type": "Adb"},
                ],
            }
        ),
        encoding="utf-8",
    )
    decl = maaend_plugin.Plugin().decl
    scripts = ConfigCollection.build([decl.script_type])
    await scripts.activate()
    script_id = scripts.add(
        decl.script_type,
        payload={
            "Info": {"Path": str(install)},
            "Game": {"ControllerType": controller},
        },
    )
    await scripts.commit()
    record = PluginRecord.build(
        info={"plugin_name": "maaend_adapter", "state": "enabled"}
    )
    await record.activate()
    monkeypatch.setattr(Config, "ScriptConfig", scripts)
    monkeypatch.setattr(Plugin, "list_plugins", lambda: [record])
    monkeypatch.setattr(Plugin, "script_types", {record.uid: decl})
    monkeypatch.setattr(Plugin, "_calls", {record.uid: CallGate()})

    caller = get_ident()
    reads = []
    load = maaend_plugin.load_maaend_controller_protocol

    def observe_read(path, name):
        reads.append(get_ident())
        return load(path, name)

    monkeypatch.setattr(maaend_plugin, "load_maaend_controller_protocol", observe_read)
    detail = await get_script(ScriptGetIn(scriptId=str(script_id)))
    assert detail.code == 200, detail.message
    (item,) = detail.index
    assert item.desktopSessionSupported is supported
    assert item.desktopSessionReason == (None if supported else "unsupported_config")
    assert reads and caller not in reads
    assert task_unavailable_reason(scripts[script_id]) == item.desktopSessionReason


async def test_update_leaves_other_session_process_and_installation_alone(
    monkeypatch, tmp_path
):
    game = tmp_path / "game" / "Endfield.exe"
    process = Mock(pid=100)
    info = {"name": game.name, "exe": str(game)}
    process.as_dict.side_effect = lambda *, attrs: {attr: info[attr] for attr in attrs}
    monkeypatch.setattr(operations.psutil, "process_iter", lambda: iter([process]))
    monkeypatch.setattr(
        operations, "matches_session", lambda _, session_id: session_id in (None, 1)
    )
    kill = AsyncMock()
    monkeypatch.setattr(process_api, "kill_process", kill)
    token = session.desktop_process_target.set(
        session.DesktopProcessTarget(7, tmp_path, tmp_path)
    )
    try:
        assert await _release_install_dir(game) is not None
        other_installation = tmp_path / "other" / game.name
        assert await _release_install_dir(other_installation) is None
        info["exe"] = None
        assert await _release_install_dir(game) is not None
        kill.assert_not_awaited()
    finally:
        session.desktop_process_target.reset(token)
