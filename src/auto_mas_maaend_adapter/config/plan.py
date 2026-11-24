#   AUTO-MAS: A Multi-Script, Multi-Config Management and Automation Software
#   Copyright © 2025-2026 AUTO-MAS Team
#
#   This file is part of AUTO-MAS.
#
#   AUTO-MAS is free software: you can redistribute it and/or modify
#   it under the terms of the GNU Affero General Public License as
#   published by the Free Software Foundation, either version 3 of
#   the License, or (at your option) any later version.
#
#   AUTO-MAS is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#   GNU Affero General Public License for more details.
#
#   You should have received a copy of the GNU Affero General Public License
#   along with AUTO-MAS. If not, see <https://www.gnu.org/licenses/>.

"""MaaEnd 计划表配置与专项计划 key。"""

from __future__ import annotations

import calendar
from copy import deepcopy
from datetime import datetime
from typing import Annotated, Literal, Optional

from auto_mas_core import PlanEntry
from auto_mas_core.host.config import ConfigGroup, Virtual, virtual_field
from auto_mas_core.host.models_config_shared import (
    normalize_maaend_plan_key,
    schema_model,
)
from auto_mas_core.host.utils import constants as _utils_constants
from pydantic import BaseModel, ConfigDict, Field


class PlanDaysConfig(PlanEntry):
    """计划槽位以星期和 DayN 配置分组保存，按当前模式选择生效槽位。"""

    @staticmethod
    def day_group_of(day: str) -> str | None:
        if day in calendar.day_name:
            return day
        if day.isdigit() and 1 <= int(day) <= schema_model.PLAN_ROTATE_DAYS_MAX:
            return f"Day{int(day)}"
        return None

    def rotate_days(self) -> int:
        return getattr(self, "Info").RotateDays

    def rotate_group(self, now: datetime) -> str:
        return f"Day{now.date().toordinal() % self.rotate_days() + 1}"

    def current_group(self, now: datetime) -> str:
        mode = getattr(self, "Info").Mode
        if mode == "ALL":
            return "ALL"
        if mode == "Weekly":
            return now.strftime("%A")
        if mode == "Rotate":
            return self.rotate_group(now)
        raise ValueError("非法的计划表模式")


class WeeklyKeyPlan(PlanDaysConfig):
    def get_current_key(self):
        key = getattr(
            self, self.current_group(datetime.now(tz=_utils_constants.UTC4))
        ).Key
        return key.model_dump(exclude_none=True)

class MaaEndAutoEssencePlanKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    SanityTaskType: Literal["Essence"] = Field(
        default="Essence", description="基质刷取任务类型"
    )
    AutoEssenceSpecifiedLocation: str = Field(
        default="", description="基质刷取指定地点"
    )
    AutoEssenceMenu: Optional[Literal["Random", "Location", "Target"]] = Field(
        default=None, description="基质刷取模式"
    )
    AutoEssenceTargetWeapons: list[str] = Field(
        default_factory=list, description="基质目标武器 ID 列表"
    )


class MaaEndProtocolSpacePlanKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    SanityTaskType: Literal[
        "OperatorProgression", "WeaponProgression", "CrisisDrills"
    ] = Field(default="OperatorProgression", description="协议空间任务类型")
    OperatorProgression: Literal["OperatorEXP", "Promotions", "T-Creds", "SkillUp"] = (
        Field(default="OperatorEXP", description="干员养成任务")
    )
    WeaponProgression: Literal["WeaponEXP", "WeaponTune"] = Field(
        default="WeaponEXP", description="武器养成任务"
    )
    CrisisDrills: str = Field(
        default="AdvancedProgression1",
        description="危境预演任务，由 MaaEnd 声明",
        min_length=1,
    )
    RewardsSetOption: Literal["RewardsSetA", "RewardsSetB"] = Field(
        default="RewardsSetA", description="奖励组选项"
    )


# 未提供任务类型时使用协议空间模型的默认值；显式类型仍由各分支的 Literal 校验。
MaaEndPlanKey = MaaEndProtocolSpacePlanKey | MaaEndAutoEssencePlanKey

class MaaEndPlanConfig(WeeklyKeyPlan):
    class ALLFields(ConfigGroup):
        Key: MaaEndPlanKey = Field(
            description="MaaEnd 计划表专项 key",
            default_factory=MaaEndProtocolSpacePlanKey,
        )

    ALL: ALLFields = Field(default_factory=ALLFields)

    class FridayFields(ConfigGroup):
        Key: MaaEndPlanKey = Field(
            description="MaaEnd 计划表专项 key",
            default_factory=MaaEndProtocolSpacePlanKey,
        )

    Friday: FridayFields = Field(default_factory=FridayFields)

    Day1: ALLFields = Field(default_factory=ALLFields)
    Day2: ALLFields = Field(default_factory=ALLFields)
    Day3: ALLFields = Field(default_factory=ALLFields)
    Day4: ALLFields = Field(default_factory=ALLFields)
    Day5: ALLFields = Field(default_factory=ALLFields)
    Day6: ALLFields = Field(default_factory=ALLFields)
    Day7: ALLFields = Field(default_factory=ALLFields)
    Day8: ALLFields = Field(default_factory=ALLFields)
    Day9: ALLFields = Field(default_factory=ALLFields)
    Day10: ALLFields = Field(default_factory=ALLFields)
    Day11: ALLFields = Field(default_factory=ALLFields)
    Day12: ALLFields = Field(default_factory=ALLFields)
    Day13: ALLFields = Field(default_factory=ALLFields)
    Day14: ALLFields = Field(default_factory=ALLFields)
    Day15: ALLFields = Field(default_factory=ALLFields)
    Day16: ALLFields = Field(default_factory=ALLFields)
    Day17: ALLFields = Field(default_factory=ALLFields)
    Day18: ALLFields = Field(default_factory=ALLFields)
    Day19: ALLFields = Field(default_factory=ALLFields)
    Day20: ALLFields = Field(default_factory=ALLFields)
    Day21: ALLFields = Field(default_factory=ALLFields)
    Day22: ALLFields = Field(default_factory=ALLFields)
    Day23: ALLFields = Field(default_factory=ALLFields)
    Day24: ALLFields = Field(default_factory=ALLFields)
    Day25: ALLFields = Field(default_factory=ALLFields)
    Day26: ALLFields = Field(default_factory=ALLFields)
    Day27: ALLFields = Field(default_factory=ALLFields)
    Day28: ALLFields = Field(default_factory=ALLFields)
    Day29: ALLFields = Field(default_factory=ALLFields)
    Day30: ALLFields = Field(default_factory=ALLFields)
    Day31: ALLFields = Field(default_factory=ALLFields)

    class InfoFields(ConfigGroup):
        RotateDays: Annotated[int, Field(ge=1, le=31)] = Field(
            default=7, description="多天轮换天数"
        )
        Mode: Literal["ALL", "Weekly", "Rotate"] = Field(
            description="计划表模式", default_factory=lambda: "ALL"
        )

        Name: str = Field(
            description="计划表名称", default_factory=lambda: "新 MaaEnd 计划表"
        )

    Info: InfoFields = Field(default_factory=InfoFields)

    class MondayFields(ConfigGroup):
        Key: MaaEndPlanKey = Field(
            description="MaaEnd 计划表专项 key",
            default_factory=MaaEndProtocolSpacePlanKey,
        )

    Monday: MondayFields = Field(default_factory=MondayFields)

    class SaturdayFields(ConfigGroup):
        Key: MaaEndPlanKey = Field(
            description="MaaEnd 计划表专项 key",
            default_factory=MaaEndProtocolSpacePlanKey,
        )

    Saturday: SaturdayFields = Field(default_factory=SaturdayFields)

    class SundayFields(ConfigGroup):
        Key: MaaEndPlanKey = Field(
            description="MaaEnd 计划表专项 key",
            default_factory=MaaEndProtocolSpacePlanKey,
        )

    Sunday: SundayFields = Field(default_factory=SundayFields)

    class ThursdayFields(ConfigGroup):
        Key: MaaEndPlanKey = Field(
            description="MaaEnd 计划表专项 key",
            default_factory=MaaEndProtocolSpacePlanKey,
        )

    Thursday: ThursdayFields = Field(default_factory=ThursdayFields)

    class TuesdayFields(ConfigGroup):
        Key: MaaEndPlanKey = Field(
            description="MaaEnd 计划表专项 key",
            default_factory=MaaEndProtocolSpacePlanKey,
        )

    Tuesday: TuesdayFields = Field(default_factory=TuesdayFields)

    class WednesdayFields(ConfigGroup):
        Key: MaaEndPlanKey = Field(
            description="MaaEnd 计划表专项 key",
            default_factory=MaaEndProtocolSpacePlanKey,
        )

    Wednesday: WednesdayFields = Field(default_factory=WednesdayFields)

    @classmethod
    def normalize_payload(cls, data):
        normalized_data = deepcopy(data)
        for group in ["ALL", *calendar.day_name, *(f"Day{i}" for i in range(1, 32))]:
            group_data = normalized_data.get(group)
            if isinstance(group_data, dict):
                normalized_data[group] = {"Key": normalize_maaend_plan_key(group_data)}
        return normalized_data


    async def _activate_from_payload(self, payload, *, regenerate_uuids=False):
        """先迁移历史载荷，再交给配置框架激活节点与嵌套集合。"""
        await super()._activate_from_payload(
            type(self).normalize_payload(payload), regenerate_uuids=regenerate_uuids
        )
    class Metadata(PlanEntry.Info):
        name: Virtual[str] = None  # pyright: ignore[reportIncompatibleVariableOverride]

    info: Metadata = Field(default_factory=Metadata)  # pyright: ignore[reportIncompatibleVariableOverride]

    @virtual_field("info.name")
    def plugin_name(self):
        return self.Info.Name
