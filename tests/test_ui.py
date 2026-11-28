"""托管、账号和计划编辑器的宿主契约。"""

from email import message_from_bytes
from html.parser import HTMLParser
from pathlib import Path
from shutil import copy2, copytree
from zipfile import ZipFile

import pytest
from app.api import plan_router, plugin_router
from app.api._config_editors import config_detail_ui
from app.config import ConfigCollection, config_manager
from app.core import Config, Plugin
from app.core.i18n import I18nManager
from app.models.config import PluginRecord, PluginRegistryCollection
from app.models.schema import DeclarativeBlockOut, HostBlockOut, PluginBlockOut
from app.plugin.calls import CallGate
from app.plugin.frontend import MountedFrontend
from app.plugin.http import HttpRegistry
from app.plugin.runtime.metadata import parse_to_plugin_record
from app.plugin.types import PluginState
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

NAME = "maaend_adapter"
MODULE = "auto_mas_maaend_adapter"
SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE / "src" / MODULE
PAGES = {"script", "user", "plan"}
LOCALES = ("zh-CN", "en-US", "ja-JP")
ASSETS = {
    "script-src": ["_host/panel-sdk.js", "assets/main.js"],
    "style-src": ["_host/panel-base.css", "assets/main.css"],
}


class PanelAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.files = {"script-src": [], "style-src": []}

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        assert tag != "style"
        assert not any(name == "style" or name.startswith("on") for name in fields)
        if tag == "script":
            assert fields.get("type") != "module" and "crossorigin" not in fields
            assert fields["src"].startswith("./")
            if fields["src"] != "./_host/panel-sdk.js":
                assert "defer" in fields
            self.files["script-src"].append(fields["src"][2:])
        if tag == "link" and fields.get("rel") == "stylesheet":
            assert fields["href"].startswith("./")
            self.files["style-src"].append(fields["href"][2:])


def frontend_mount():
    gate = CallGate()
    frontend = MountedFrontend.load(
        PACKAGE, NAME, "MaaEnd", "MaaEndPlanConfig", gate, block_pages=PAGES
    )
    assert frontend is not None
    assert frontend.diagnostics == []
    assert frontend.block_pages == PAGES
    return frontend


async def register_enabled_plugin(monkeypatch):
    registry = PluginRegistryCollection.build()
    await registry.activate()
    record_id = registry.add(
        PluginRecord,
        payload={"info": {"plugin_name": NAME, "state": PluginState.ENABLED}},
    )
    await registry.commit()
    monkeypatch.setattr(Config, "plugin_registry", registry)
    return registry[record_id]


@pytest.mark.asyncio
async def test_built_panels_served_under_host_csp(monkeypatch, tmp_path):
    frontend = frontend_mount()
    await register_enabled_plugin(monkeypatch)
    app = FastAPI()
    app.include_router(plugin_router)
    http = HttpRegistry()
    monkeypatch.setattr(Plugin, "http", http)
    http.bind_app(app)
    http.mount(NAME, [], frontend=frontend, gate=frontend.gate)
    root = f"/api/plugin/{NAME}/ui/{frontend.revision}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for page in sorted(PAGES):
            response = await client.get(f"{root}/{page}.html")
            assert response.status_code == 200
            policy = dict(
                directive.split(" ", 1)
                for directive in response.headers["Content-Security-Policy"].split("; ")
            )
            assert policy["default-src"] == "'none'"
            assert policy["sandbox"] == "allow-scripts allow-forms"
            parser = PanelAssets()
            parser.feed(response.text)
            assert parser.files == ASSETS
            for directive, mime in (
                ("script-src", "text/javascript"),
                ("style-src", "text/css"),
            ):
                assert "'unsafe-inline'" not in policy[directive].split()
                for path in parser.files[directive]:
                    url = f"http://test{root}/{path}"
                    assert url in policy[directive].split()
                    asset = await client.get(url)
                    assert asset.status_code == 200
                    assert asset.headers["Content-Type"].startswith(mime)

    for filename in ("zh_CN.json", "en.json", "ja.json"):
        (tmp_path / filename).write_text('{"core.test": "host"}', encoding="utf-8")
    manager = I18nManager(tmp_path)
    manager.set_package_roots({NAME: PACKAGE})
    for locale in LOCALES:
        messages, _ = await manager.get_messages(locale)
        panel = messages["plugins"][NAME]["panel"]
        assert (
            panel["ControllerType"] and panel["DailyOnceTasks"] and panel["planConfig"]
        )


@pytest.mark.asyncio
async def test_editor_blocks_and_scoped_routes(monkeypatch, isolated_host):
    from auto_mas_maaend_adapter.config import MaaEndConfig, MaaEndPlanConfig
    from auto_mas_maaend_adapter.plugin import Plugin as Adapter

    config = isolated_host
    scripts = ConfigCollection.build([MaaEndConfig])
    plans = ConfigCollection.build([MaaEndPlanConfig])
    await scripts.activate()
    await plans.activate()
    record = await register_enabled_plugin(monkeypatch)
    adapter = Adapter()
    record._plugin_cls = Adapter
    record._plugin = adapter
    monkeypatch.setattr(config, "ScriptConfig", scripts)
    monkeypatch.setattr(config, "PlanConfig", plans)
    monkeypatch.setitem(config_manager._collections, "ScriptConfig", scripts)
    monkeypatch.setitem(config_manager._collections, "PlanConfig", plans)
    monkeypatch.setattr(Plugin, "script_types", {record.uid: Adapter.decl})
    await adapter.pre_enable()
    frontend = frontend_mount()
    monkeypatch.setitem(Plugin._calls, record.uid, frontend.gate)
    app = FastAPI()
    app.include_router(plugin_router)
    app.include_router(plan_router)
    http = HttpRegistry()
    monkeypatch.setattr(Plugin, "http", http)
    http.bind_app(app)
    http.mount(
        NAME, [], router=Adapter.api_router, frontend=frontend, gate=frontend.gate
    )

    script_id, script = await config.add_script("MaaEnd")
    user_id, user = await config.add_user(str(script_id))
    plan_id, plan = await config.add_plan("MaaEndPlanConfig")
    _, script_docs = await config.get_script(str(script_id))
    _, user_docs = await config.get_user(str(script_id), str(user_id))
    _, plan_docs = await config.get_plan(str(plan_id))
    script_mount = frontend.surface_mount(name=NAME, page="script")
    user_mount = frontend.surface_mount(name=NAME, page="user")
    plan_mount = frontend.surface_mount(name=NAME, page="plan")
    assert config_detail_ui(script, script_docs).blocks == [
        DeclarativeBlockOut(groups=["Info"]),
        HostBlockOut(name="native_session"),
        PluginBlockOut(
            pageId="script",
            fallbackGroups=["Game", "Run", "Update"],
            mount=script_mount,
        ),
        HostBlockOut(name="game_binding"),
    ]
    user_ui = config_detail_ui(user, user_docs)
    assert user_ui.blocks == [
        HostBlockOut(name="config_restore"),
        HostBlockOut(name="native_session"),
        DeclarativeBlockOut(groups=["Info"]),
        PluginBlockOut(pageId="user", fallbackGroups=["Task"], mount=user_mount),
        DeclarativeBlockOut(groups=["Notify"]),
        HostBlockOut(name="webhooks"),
    ]
    assert user_ui.nativeSession == "config"
    assert [(pool.key, pool.kind) for pool in user_ui.backupTargets] == [
        ("mas", "user"),
        ("native", "script"),
    ]
    plan_ui = config_detail_ui(plan, plan_docs)
    assert plan_ui.frontendSurfaces["plan"] == plan_mount
    assert plan_ui.blocks == [
        DeclarativeBlockOut(groups=["Info"]),
        PluginBlockOut(
            pageId="plan",
            fallbackGroups=[
                "ALL",
                "Monday",
                "Tuesday",
                "Wednesday",
                "Thursday",
                "Friday",
                "Saturday",
                "Sunday",
                *(f"Day{i}" for i in range(1, 32)),
            ],
            mount=plan_mount,
        ),
    ]
    assert any(
        hint["field"] == "Key" and hint["editable"] for hint in plan_ui.hints["ALL"]
    )

    prefix = f"/api/plugin/{NAME}"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = {
            "X-Plugin-Ui-Provider": NAME,
            "X-Plugin-Ui-Activation": frontend.activation_id,
            "X-Plugin-Ui-Page": "script",
        }
        response = await client.get(
            f"{prefix}/editor/script/{script_id}", headers=headers
        )
        assert response.json() == {"path": None, "executable": None, "launcher": None}
        assert (
            await client.get(
                f"{prefix}/editor/script/{script_id}/update", headers=headers
            )
        ).json() is None
        user_url = f"{prefix}/editor/user/{script_id}/{user_id}"
        assert (await client.get(user_url, headers=headers)).status_code == 403
        headers["X-Plugin-Ui-Page"] = "user"
        assert (await client.get(user_url, headers=headers)).json()[
            "quickConfig"
        ] is True
        headers["X-Plugin-Ui-Page"] = "plan"
        plan_url = f"{prefix}/editor/plan/{plan_id}"
        assert (await client.get(plan_url, headers=headers)).json()["mode"] == "ALL"
        assert (await client.get(f"{plan_url}/options", headers=headers)).json()[
            "crisisDrills"
        ] == []
        response = await client.post(
            "/api/plan/update",
            headers=headers,
            json={
                "planId": str(plan_id),
                "data": {
                    "ALL": {
                        "Key": {
                            "SanityTaskType": "Essence",
                            "AutoEssenceMenu": "Random",
                        }
                    }
                },
            },
        )
        assert response.status_code == response.json()["code"] == 200, response.text
        assert plan.ALL.Key.SanityTaskType == "Essence"
        headers["X-Plugin-Ui-Activation"] = "stale"
        assert (await client.get(plan_url, headers=headers)).status_code == 409
        for root in ("/api/scripts", prefix):
            reply = await client.post(
                f"{root}/maaend/options", json={"scriptId": str(script_id)}
            )
            assert reply.status_code == 200 and reply.json()["code"] != 200
    api_paths = app.openapi()["paths"]
    assert "/api/scripts/maaend/options" in api_paths
    assert not any(path.startswith(prefix) for path in api_paths)
    await adapter.on_disable()


def test_wheel_contains_ui_and_locales(monkeypatch, tmp_path):
    from setuptools.build_meta import build_wheel

    checkout = tmp_path / "sources"
    checkout.mkdir()
    for filename in ("pyproject.toml", "README.md", "LICENSE"):
        copy2(SOURCE / filename, checkout)
    copytree(PACKAGE, checkout / "src" / MODULE)
    monkeypatch.chdir(checkout)
    wheel = tmp_path / build_wheel(str(tmp_path))
    with ZipFile(wheel) as archive:
        metadata = next(
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        )
        record = parse_to_plugin_record(
            message_from_bytes(archive.read(metadata)),
            import_name=MODULE,
            source="installed",
        )
        assert record is not None and record.info.plugin_name == NAME
        required = {
            f"{MODULE}/ui/manifest.json",
            *(f"{MODULE}/ui/{page}.html" for page in PAGES),
            *(
                f"{MODULE}/ui/{asset}"
                for asset in ("assets/main.js", "assets/main.css")
            ),
            *(f"{MODULE}/i18n/{locale}.json" for locale in LOCALES),
        }
        assets = {
            path.relative_to(PACKAGE.parent).as_posix()
            for folder in ("ui", "i18n")
            for path in (PACKAGE / folder).rglob("*")
            if path.is_file()
        }
        assert required <= assets <= set(archive.namelist())
        for asset in assets:
            assert archive.read(asset) == (PACKAGE.parent / asset).read_bytes()
