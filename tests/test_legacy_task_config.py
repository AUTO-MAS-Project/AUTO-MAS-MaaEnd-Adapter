"""把原宿主管的旧任务开关、计划引用的回归交给适配器。"""

import json

import pytest
from app.config import ConfigCollection, config_manager

from auto_mas_maaend_adapter.config import MaaEndPlanConfig, MaaEndUserConfig
from auto_mas_maaend_adapter.config.plan import MaaEndProtocolSpacePlanKey
from auto_mas_maaend_adapter.tools.backup_archive import group_overlay


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "strategy,kind,enabled,expected",
    [
        ("Inventory", "Essence", True, (True, False)),
        ("MAS", "Essence", True, (False, True)),
        ("MAS", "OperatorProgression", True, (True, False)),
        ("Native", "Essence", True, (True, True)),
        ("Inventory", "Essence", False, (False, False)),
    ],
)
async def test_old_switch_migrates_without_enabling_extra_tasks(
    strategy, kind, enabled, expected
):
    users = ConfigCollection.build([MaaEndUserConfig])
    await users.activate()
    uid = users.add(
        MaaEndUserConfig,
        payload={
            "Info": {"SanityStrategy": strategy},
            "Task": {
                "IfSanity": enabled,
                "SanityTaskType": kind,
                "DailyOnceTasks": '["Sanity"]',
            },
            "Data": {"PeriodTaskRecords": '{"daily":{"Sanity":"2026-11-16"}}'},
        },
    )
    await users.commit()
    user = users[uid]
    assert (user.Task.IfProtocolSpace, user.Task.IfAutoEssence) == expected
    assert json.loads(user.Task.DailyOnceTasks) == ["ProtocolSpace", "AutoEssence"]
    assert json.loads(user.Data.PeriodTaskRecords)["daily"] == {
        "ProtocolSpace": "2026-11-16",
        "AutoEssence": "2026-11-16",
    }
    restored = group_overlay(
        {"SanityStrategy": strategy, "IfSanity": enabled, "SanityTaskType": kind}
    )
    assert (
        restored["Task"]["IfProtocolSpace"],
        restored["Task"]["IfAutoEssence"],
    ) == expected


@pytest.mark.asyncio
async def test_old_plan_routes_each_native_task_and_unbinds_on_delete(
    isolated_host, monkeypatch
):
    plans = ConfigCollection.build([MaaEndPlanConfig])
    monkeypatch.setitem(config_manager._collections, "PlanConfig", plans)
    await plans.activate()
    plan_id = plans.add(
        MaaEndPlanConfig,
        payload={
            "ALL": {
                "Key": {
                    "SanityTaskType": "Essence",
                    "AutoEssenceSpecifiedLocation": "test_location",
                }
            }
        },
    )
    await plans.commit()
    monkeypatch.setattr(
        MaaEndUserConfig,
        "related_config",
        {"PlanConfig": plans, "games": isolated_host.GameConfig},
    )
    users = ConfigCollection.build([MaaEndUserConfig])
    await users.activate()
    uid = users.add(
        MaaEndUserConfig,
        payload={
            "Info": {"SanityStrategy": "MAS", "SanityMode": str(plan_id)},
            "Task": {"IfSanity": True},
        },
    )
    await users.commit()
    user = users[uid]
    assert str(user.Info.AutoEssenceMode) == str(plan_id)
    assert (
        user.get_effective_essence_task_key()["AutoEssenceSpecifiedLocation"]
        == "test_location"
    )
    assert user.get_effective_sanity_task_key()[0]["SanityTaskType"] == "Essence"
    plans[plan_id].ALL.Key = MaaEndProtocolSpacePlanKey()
    await plans[plan_id].commit()
    assert user.get_effective_essence_task_key() is None
    assert (
        user.get_effective_sanity_task_key()[0]["SanityTaskType"]
        == "OperatorProgression"
    )
    plans.remove(plan_id)
    await plans.commit()
    assert user.Info.SanityMode == "Fixed"
    assert user.Info.AutoEssenceMode == "Fixed"
