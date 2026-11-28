"""配置模型迁移：旧字段形状与插件基类投影。"""

from uuid import UUID

import pytest
from app.config import ConfigCollection, config_manager
from app.models.config import MaaEndConfig as BuiltinMaaEndConfig
from app.utils import io

from auto_mas_maaend_adapter.config import (
    MaaEndConfig,
    MaaEndPlanConfig,
    MaaEndUserConfig,
)


def test_script_payload_moves_user_data_to_users():
    payload = {
        "Info": {"Name": "测试托管"},
        "UserData": {"u1": {"Info": {"Name": "账号一"}}},
        "SubConfigsInfo": {"UserData": {"u2": {"Info": {"Name": "账号二"}}}},
    }
    normalized = MaaEndConfig.normalize_payload(payload)
    assert "UserData" not in normalized
    assert set(normalized["users"]) == {"u1"}
    assert "UserData" not in MaaEndConfig.model_fields
    assert set(normalized["SubConfigsInfo"]["users"]) == {"u2"}


@pytest.mark.asyncio
async def test_saved_accounts_can_still_be_read_by_the_builtin_adapter(tmp_path):
    """同一份磁盘配置可供插件版和旧内置版读取，接口仍用 users。"""
    script_id = UUID("1a79b6d8-11c1-4c8b-b729-13247f019cc4")
    user_id = UUID("6b45f422-3276-4853-989f-22b7cc2d9e2a")
    path = tmp_path / "scripts.yaml"
    io.write_file(
        path,
        {
            "order": [{"uid": str(script_id), "type": "MaaEndConfig"}],
            "data": {
                str(script_id): {
                    "UserData": {
                        "order": [{"uid": str(user_id), "type": "MaaEndUserConfig"}],
                        "data": {str(user_id): {"Info": {"Name": "旧账号"}}},
                    },
                },
            },
        },
    )
    scripts = ConfigCollection.build([MaaEndConfig], file=path)
    await scripts.activate()
    script = scripts[script_id]
    assert script.users[user_id].Info.Name == "旧账号"
    script.users[user_id].Info.Name = "在新版改名"
    await script.users[user_id].commit()
    await config_manager.flush()

    api = script.model_dump()
    assert api["users"]["data"][str(user_id)]["Info"]["Name"] == "在新版改名"
    assert "UserData" not in api
    old_scripts = ConfigCollection.build(
        [BuiltinMaaEndConfig], payload=io.read_dict_file(path)
    )
    await old_scripts.activate()
    assert list(old_scripts[script_id].UserData.keys()) == [user_id]
    assert old_scripts[script_id].UserData[user_id].Info.Name == "在新版改名"


@pytest.mark.asyncio
async def test_maaend_plan_http_supports_both_create_names_and_legacy_consumer(
    isolated_host, monkeypatch
):
    """部署插件后，旧客户端仍可创建 MaaEnd 计划和列出原计划。"""
    from app.api import info, plan
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    plan_id = UUID("5924194a-fcc0-49b6-8a2b-f1d1875def93")
    plans = ConfigCollection.build([MaaEndPlanConfig])
    await plans.activate()
    plans.add(MaaEndPlanConfig, uid=plan_id, payload={"Info": {"Name": "原计划"}})
    await plans.commit()
    monkeypatch.setattr(isolated_host, "PlanConfig", plans)
    app = FastAPI()
    app.include_router(plan.router)
    app.include_router(info.router)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for create_type in ("MaaEndPlan", "MaaEndPlanConfig"):
            created = await client.post("/api/plan/add", json={"type": create_type})
            assert created.json()["status"] == "success", created.json()
            assert isinstance(plans[created.json()["planId"]], MaaEndPlanConfig)
        selected = await client.post(
            "/api/info/combox/plan", json={"consumer": "maaend"}
        )
        assert {"label": "原计划", "value": str(plan_id)} in selected.json()["data"]


def test_script_payload_migrates_fullscreen_restore():
    normalized = MaaEndConfig.normalize_payload(
        {"Game": {"RestoreResolution": "Fullscreen"}}
    )
    assert normalized["Game"]["RestoreDisplayType"] == "Fullscreen"
    assert normalized["Game"]["RestoreResolution"] == "1920x1080"


def test_user_virtual_fields_follow_legacy_info():
    user = MaaEndUserConfig.model_validate(
        {"Info": {"Name": "账号一", "Status": False}}
    )
    assert user.info.name == "账号一"
    assert user.info.enabled is False


def test_user_legacy_mode_maps_to_base():
    user = MaaEndUserConfig.model_validate({"Info": {"Mode": "自定义"}})
    assert user.Info.Base == "independent"


def test_plan_name_projects_to_info():
    plan = MaaEndPlanConfig.model_validate({"Info": {"Name": "计划一"}})
    assert plan.info.name == "计划一"
    assert (
        plan.normalize_payload(
            {
                "ALL": {
                    "SanityTaskType": "OperatorProgression",
                    "OperatorProgression": "OperatorEXP",
                }
            }
        )["ALL"]["Key"]["SanityTaskType"]
        == "OperatorProgression"
    )


def test_plan_payload_expands_legacy_days_container():
    """旧计划表的 Days 容器展开到日期分组，与已有字段冲突时以 Days 为准。"""
    normalized = MaaEndPlanConfig.normalize_payload(
        {
            "Days": {
                "Monday": {"SanityTaskType": "Essence", "AutoEssenceMenu": "Random"},
                "Friday": {"SanityTaskType": "Essence", "AutoEssenceMenu": "Location"},
                "3": {
                    "SanityTaskType": "OperatorProgression",
                    "OperatorProgression": "Promotions",
                },
            },
            "Monday": {"Key": {"SanityTaskType": "OperatorProgression"}},
        }
    )
    assert "Days" not in normalized
    assert normalized["Monday"]["Key"]["SanityTaskType"] == "Essence"
    assert normalized["Friday"]["Key"]["SanityTaskType"] == "Essence"
    assert normalized["Day3"]["Key"]["OperatorProgression"] == "Promotions"
    plan = MaaEndPlanConfig.model_validate(normalized)
    assert plan.Monday.Key.SanityTaskType == "Essence"
    assert plan.Day3.Key.OperatorProgression == "Promotions"


def test_plan_payload_ignores_unknown_days_names():
    """Days 里认不出的日期名直接忽略，不凭空造分组。"""
    normalized = MaaEndPlanConfig.normalize_payload(
        {"Days": {"Mon": {"SanityTaskType": "Essence"}, "32": {}}}
    )
    assert "Days" not in normalized
    assert "Mon" not in normalized
    assert "Day32" not in normalized
    assert "Monday" not in normalized


def test_script_payload_keeps_execution_session():
    """分身会话偏好属于托管配置，迁移后要保留，不能顺手删掉。"""
    normalized = MaaEndConfig.normalize_payload(
        {"Run": {"ExecutionSession": "desktop", "HardTimeLimit": 30}}
    )
    assert normalized["Run"]["ExecutionSession"] == "desktop"
    assert normalized["Run"]["HardTimeLimit"] == 30


def test_script_payload_defaults_execution_session_to_main():
    """缺字段或写了不认识的值都按主会话处理。"""
    missing = MaaEndConfig.normalize_payload({"Run": {"HardTimeLimit": 30}})
    assert missing["Run"]["ExecutionSession"] == "main"
    unknown = MaaEndConfig.normalize_payload({"Run": {"ExecutionSession": "other"}})
    assert unknown["Run"]["ExecutionSession"] == "main"
