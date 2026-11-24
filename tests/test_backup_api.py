"""插件自有备份端点：归档、列表、预览、恢复与错误包络。

用 tmp_path 造假的 MaaEnd 安装目录和脚本配置，不依赖 Windows、真机或网络。
"""

import json

import httpx
import pytest
from fastapi import FastAPI

from auto_mas_maaend_adapter.config import MaaEndConfig, MaaEndUserConfig
from auto_mas_maaend_adapter.plugin import Plugin

PREFIX = "/api/plugin/maaend_adapter/backup"


async def _make_host(monkeypatch, tmp_path, tmp_path_factory):
    """装配一个已激活的 MaaEnd 脚本集合，并返回带数据的 HTTP 客户端。"""

    from app.config import ConfigCollection
    from app.core import Config

    scripts = ConfigCollection.build([MaaEndConfig])
    await scripts.activate()
    monkeypatch.setattr(Config, "ScriptConfig", scripts)

    # 安装目录必须落在工作目录之外：FolderPath 的 APP 阻止规则会拒掉 cwd 子树。
    install = tmp_path_factory.mktemp("maaend-install")
    (install / "config").mkdir(parents=True)
    (install / "config" / "mxu-MaaEnd.json").write_text(
        '{"Config": {"Name": "install"}}', encoding="utf-8"
    )
    script_id = scripts.add(
        MaaEndConfig,
        payload={"Info": {"Name": "备份测试", "Path": str(install)}},
    )
    await scripts.commit()
    user_id = scripts[script_id].users.add(
        MaaEndUserConfig,
        payload={"Info": {"Name": "测试账号", "Base": "shared"}},
    )
    await scripts[script_id].users.commit()

    mas_dir = tmp_path / "data" / str(script_id) / "Default" / "ConfigFile"
    mas_dir.mkdir(parents=True)
    source = mas_dir / "mxu-MaaEnd.json"
    source.write_text('{"Config": {"Name": "before"}}', encoding="utf-8")

    app = FastAPI()
    app.include_router(Plugin.api_router)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )
    return client, source, install, str(script_id), str(user_id)


@pytest.mark.asyncio
async def test_mas_pool_round_trip_and_error_envelopes(
    monkeypatch, tmp_path, tmp_path_factory
):
    """mas 池：ensure → list → preview → restore 主路径，非法参数返回 400。"""

    client, source, _install, script_id, user_id = await _make_host(
        monkeypatch, tmp_path, tmp_path_factory
    )
    context = {"scriptId": script_id, "userId": user_id, "target": "mas"}

    async with client:
        saved = (await client.post(f"{PREFIX}/ensure", json=context)).json()
        assert saved["code"] == 200 and saved["created"] is True, saved
        time = saved["time"]
        assert time

        listed = (await client.get(f"{PREFIX}/list", params=context)).json()
        assert listed["code"] == 200 and listed["base"] == "shared", listed
        assert listed["data"] == [{"time": time, "base": "shared"}], listed

        selected = {**context, "time": time}
        preview = (await client.get(f"{PREFIX}/preview", params=selected)).json()
        assert preview["code"] == 200, preview
        assert preview["data"]["fileCards"], preview

        source.write_text('{"Config": {"Name": "after"}}', encoding="utf-8")
        restored = (await client.post(f"{PREFIX}/restore", json=selected)).json()
        assert restored["code"] == 200 and restored["target"] == "mas", restored
        assert json.loads(source.read_text(encoding="utf-8"))["Config"]["Name"] == (
            "before"
        )

        bad_target = (
            await client.get(
                f"{PREFIX}/list",
                params={**context, "target": "unknown"},
            )
        ).json()
        assert bad_target["code"] == 400, bad_target

        missing = (
            await client.get(
                f"{PREFIX}/preview",
                params={**selected, "time": "20000101-000000"},
            )
        ).json()
        assert missing["code"] == 400, missing

        traversal = (
            await client.get(
                f"{PREFIX}/file",
                params={**selected, "path": "../outside.json"},
            )
        ).json()
        assert traversal["code"] == 400, traversal


@pytest.mark.asyncio
async def test_native_pool_round_trip(monkeypatch, tmp_path, tmp_path_factory):
    """native 池：归档安装目录 config/，改坏后可按备份恢复。"""

    client, _source, install, script_id, user_id = await _make_host(
        monkeypatch, tmp_path, tmp_path_factory
    )
    native = install / "config" / "mxu-MaaEnd.json"
    context = {"scriptId": script_id, "userId": user_id, "target": "native"}

    async with client:
        saved = (await client.post(f"{PREFIX}/ensure", json=context)).json()
        assert saved["code"] == 200 and saved["created"] is True, saved
        selected = {**context, "time": saved["time"]}

        listed = (await client.get(f"{PREFIX}/list", params=context)).json()
        assert listed["code"] == 200 and listed["data"], listed

        preview = (await client.get(f"{PREFIX}/preview", params=selected)).json()
        assert preview["code"] == 200, preview
        assert "fileCards" in preview["data"], preview

        native.write_text('{"Config": {"Name": "broken"}}', encoding="utf-8")
        restored = (await client.post(f"{PREFIX}/restore", json=selected)).json()
        assert restored["code"] == 200 and restored["target"] == "native", restored
        assert json.loads(native.read_text(encoding="utf-8"))["Config"]["Name"] == (
            "install"
        )
