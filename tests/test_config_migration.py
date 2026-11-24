"""配置模型迁移：旧字段形状与插件基类投影。"""

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
    assert plan.normalize_payload(
        {"ALL": {"SanityTaskType": "OperatorProgression", "OperatorProgression": "OperatorEXP"}}
    )["ALL"]["Key"]["SanityTaskType"] == "OperatorProgression"
