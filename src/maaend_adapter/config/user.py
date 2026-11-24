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

"""MaaEnd 账号配置，保留原字段名并投影插件基类字段。"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Annotated, Any, ClassVar, Literal
from uuid import UUID

from auto_mas_core import UserEntry
from auto_mas_core.host.config import (
    ConfigCollection,
    ConfigGroup,
    Virtual,
    collection,
    encrypted,
    legacy,
    ref,
    virtual_field,
)
from auto_mas_core.host.config_types import JsonDictString, JsonListString
from auto_mas_core.host.models_config_queue import Webhook
from auto_mas_core.host.models_config_shared import (
    AccountCredentialFields,
    AccountNameFields,
    AccountRunFields,
    AccountRunStatusFields,
    AccountScriptHookFields,
    _normalize_maaend_sanity_task_type,
    _tag_last_status,
    _tag_notes,
    _tag_proxy,
    _tag_remained_days,
    migrate_maaend_sanity_tasks,
    normalize_maaend_plan_key,
)
from auto_mas_core.host.utils import constants as _utils_constants
from pydantic import Field, PrivateAttr

from .plan import MaaEndPlanConfig


class MaaEndUserConfig(UserEntry):
    related_config: ClassVar = {}

    class DataFields(AccountRunFields, AccountRunStatusFields):
        PeriodTaskRecords: JsonDictString = Field(
            default_factory=lambda: "{ }",
            description="MaaEnd 每日任务完成记录，结构为 daily -> task name -> 日期",
        )

    Data: DataFields = Field(default_factory=DataFields)

    class InfoFields(
        AccountNameFields, AccountCredentialFields, AccountScriptHookFields
    ):
        Base: Annotated[
            Literal["shared", "independent", "native"],
            legacy(
                group="Info",
                name="Mode",
                convert=_utils_constants.normalize_base_source,
            ),
        ] = Field(
            default_factory=lambda: "shared",
            description="base 来源（shared=共享/independent=独立/native=原生）",
        )

        Id: Annotated[str, encrypted()] = Field(
            default_factory=lambda: "", description="账号ID"
        )

        IfQuickConfig: bool = Field(
            default_factory=lambda: True, description="是否启用覆写常规配置"
        )

        Password: Annotated[str, encrypted()] = Field(
            default_factory=lambda: "", description="密码"
        )

        Resource: str = Field(
            default_factory=lambda: "官服",
            description="MaaEnd 启动服务器选项原值，官服为旧配置兼容值",
        )

        SanityStrategy: Literal["MAS", "Native", "Inventory"] = Field(
            default="Inventory",
            description="协议空间策略：库存保持、指定任务或原生配置",
        )

        SanityMode: Annotated[
            UUID | str,
            ref(
                "PlanConfig",
                default="Fixed",
                allow_values=("Fixed",),
                entry_types=(MaaEndPlanConfig,),
                display_field="Info.Name",
            ),
        ] = Field(default_factory=lambda: "Fixed", description="理智任务配置模式")

        AutoEssenceMode: Annotated[
            UUID | str,
            ref(
                "PlanConfig",
                default="Fixed",
                allow_values=("Fixed", "Native"),
                entry_types=(MaaEndPlanConfig,),
                display_field="Info.Name",
            ),
        ] = Field(default_factory=lambda: "Fixed", description="基质刷取配置模式")

    Info: InfoFields = Field(default_factory=InfoFields)

    class NotifyFields(ConfigGroup):
        Enabled: bool = Field(default_factory=lambda: False, description="是否启用通知")

        IfSendMail: bool = Field(
            default_factory=lambda: False, description="是否发送邮件"
        )

        IfSendInventory: bool = Field(
            default=False, description="是否推送本轮养成材料状态"
        )

        IfSendStatistic: bool = Field(
            default_factory=lambda: False, description="是否发送统计信息"
        )

        IfServerChan: bool = Field(
            default_factory=lambda: False, description="是否启用 Server 酱"
        )

        PushLogMode: Literal["关闭", "逐条", "汇总"] = Field(
            default_factory=lambda: "汇总",
            description="任务报告节点详情的推送模式（log_box 采集的关键节点）： 关闭 = 不采集；逐条 = 采集并逐条带回时间戳；汇总 = 采集并按状态聚合",
        )

        ServerChanKey: str = Field(
            default_factory=lambda: "", description="Server 酱密钥"
        )

        ToAddress: str = Field(default_factory=lambda: "", description="收件地址")

    Notify: NotifyFields = Field(default_factory=NotifyFields)

    class TaskFields(ConfigGroup):
        SupplyPlanLimits: JsonDictString = Field(
            default_factory=lambda: json.dumps(
                _utils_constants.MAAEND_INVENTORY_TARGET_DEFAULTS
            ),
            description="上游库存目标输入值，原字段名与字符串值透传",
        )
        ProtocolSpaceObtainModeClaim: str = Field(
            default="ObtainScaling2", description="库存任务领取方式，由 MaaEnd 声明"
        )

        AutoCollectCommonRoutes: Any = Field(
            description="自动采集通用资源路线", default_factory=lambda: None
        )

        AutoCollectMode: Literal["Distributed", "Concentrated"] = Field(
            description="自动采集路线安排：分散或集中",
            default_factory=lambda: "Distributed",
        )

        AutoCollectRoutes: Any = Field(
            description="自动采集区域资源路线", default_factory=lambda: None
        )

        AutoEssenceMenu: Literal["Random", "Location", "Target"] = Field(
            description="基质刷取模式", default_factory=lambda: "Location"
        )

        AutoEssenceSpecifiedLocation: str = Field(
            description="基质刷取指定地点", default_factory=lambda: ""
        )

        AutoEssenceTargetWeapons: list[str] = Field(
            description="基质目标武器 ID 列表", default_factory=lambda: []
        )

        CrisisDrills: str = Field(
            description="危境预演任务，由 MaaEnd 声明",
            default="AdvancedProgression1",
            min_length=1,
        )

        DailyOnceTasks: JsonListString = Field(
            description="每日正常完成一次后当天跳过的 MaaEnd 任务名列表（JSON 字符串）",
            default_factory=lambda: "[ ]",
        )

        IfAutoCollect: bool = Field(
            description="自动采集", default_factory=lambda: True
        )

        IfAutoEcoFarm: bool = Field(
            description="生态农场", default_factory=lambda: True
        )

        IfAutoSell: bool = Field(
            description="售卖弹性物资", default_factory=lambda: True
        )

        IfAutoStockStaple: bool = Field(
            description="购买稳定物资", default_factory=lambda: True
        )

        IfAutoStockpile: bool = Field(
            description="自动囤货", default_factory=lambda: True
        )

        IfAutoUseSpMedication: bool = Field(
            description="应急理智加强剂", default_factory=lambda: True
        )

        IfCreditShoppingN2: bool = Field(
            description="信用点购物", default_factory=lambda: True
        )

        IfDailyRewards: bool = Field(
            description="日常奖励领取", default_factory=lambda: True
        )

        IfDeliveryJobs: bool = Field(
            description="转交委托", default_factory=lambda: True
        )

        IfDijiangRewards: bool = Field(
            description="基建任务", default_factory=lambda: True
        )

        IfEnvironmentMonitoring: bool = Field(
            description="环境监测", default_factory=lambda: True
        )

        IfPullCountCalculator: bool = Field(
            description="抽数计算", default_factory=lambda: False
        )

        IfResourceRecycleStation: bool = Field(
            description="资源回收站", default_factory=lambda: True
        )

        IfProtocolSpace: Annotated[bool, legacy(group="Task", name="IfSanity")] = Field(
            default=True, description="协议空间（库存保持）"
        )

        IfAutoEssence: bool = Field(default=False, description="基质刷取")

        IfSeizeDeliveryJobs: bool = Field(
            description="抢委托送货", default_factory=lambda: True
        )

        IfSellProduct: bool = Field(
            description="售卖产品", default_factory=lambda: True
        )

        IfTrialOfSwordmancy: bool = Field(
            description="选剑演武", default_factory=lambda: True
        )

        IfVisitFriends: bool = Field(
            description="拜访好友", default_factory=lambda: True
        )

        OperatorProgression: Literal[
            "OperatorEXP", "Promotions", "T-Creds", "SkillUp"
        ] = Field(description="干员养成任务", default_factory=lambda: "OperatorEXP")

        RewardsSetOption: Literal["RewardsSetA", "RewardsSetB"] = Field(
            description="奖励组选项", default_factory=lambda: "RewardsSetA"
        )

        SanityTaskType: Literal[
            "OperatorProgression", "WeaponProgression", "CrisisDrills", "Essence"
        ] = Field(
            description="理智任务类型", default_factory=lambda: "OperatorProgression"
        )

        SeizeDeliveryJobsCommissionSource: Literal[
            "Unlimited", "WulingCity", "TestArea"
        ] = Field(
            description="抢委托送货委托接收点", default_factory=lambda: "Unlimited"
        )

        SeizeDeliveryJobsReward: Annotated[float, Field(ge=0, le=9999)] = Field(
            description="抢委托送货最低接取价格（万）",
            default_factory=lambda: 15.9,
        )

        WeaponProgression: Literal["WeaponEXP", "WeaponTune"] = Field(
            description="武器养成任务", default_factory=lambda: "WeaponEXP"
        )

    Task: TaskFields = Field(default_factory=TaskFields)
    Notify_CustomWebhooks: ConfigCollection[Webhook] = collection(Webhook)
    _maaend_essence_location_labels: dict = PrivateAttr(default_factory=dict)
    _maaend_crisis_drills_labels: dict[str, str] = PrivateAttr(default_factory=dict)

    def cache_maaend_resource(self, resource: dict[str, Any]) -> None:
        """缓存 MaaEnd 动态资源的展示文本。"""
        self._maaend_essence_location_labels = {
            str(item["value"]): str(item["label"])
            for item in resource.get("essenceLocations", [])
            if isinstance(item, dict) and item.get("value") is not None
        }
        self._maaend_crisis_drills_labels = {
            str(item["value"]): str(item["label"])
            for item in resource.get("crisisDrills", [])
        }

    def _get_maaend_location_label(self, value: str) -> str:
        if not value:
            return ""
        return self._maaend_essence_location_labels.get(value, value)

    def get_effective_sanity_task_key(self) -> tuple[dict[str, Any], str]:
        """获取当前生效的完整 MaaEnd key。"""
        mode = self.Info.SanityMode
        if mode == "Fixed":
            return (
                normalize_maaend_plan_key(
                    {
                        field: getattr(self.Task, field)
                        for field in _utils_constants.MAAEND_SANITY_TASK_FIELDS
                    }
                ),
                "Fixed",
            )
        try:
            plan = self.related_config["PlanConfig"][mode]
        except (KeyError, ValueError) as e:
            raise ValueError("引用的理智任务计划表不存在") from e
        return (plan.get_current_key(), str(mode))

    def get_effective_essence_task_key(self) -> dict[str, Any] | None:
        """读取独立基质配置，计划表当天为协议空间时不执行基质。"""
        mode = self.Info.AutoEssenceMode
        if mode == "Native":
            return None
        if mode == "Fixed":
            return normalize_maaend_plan_key(
                {
                    "SanityTaskType": "Essence",
                    "AutoEssenceMenu": self.Task.AutoEssenceMenu,
                    "AutoEssenceSpecifiedLocation": self.Task.AutoEssenceSpecifiedLocation,
                    "AutoEssenceTargetWeapons": self.Task.AutoEssenceTargetWeapons,
                }
            )
        try:
            plan = self.related_config["PlanConfig"][mode]
        except (KeyError, ValueError) as error:
            raise ValueError("引用的基质刷取计划表不存在") from error
        key = plan.get_current_key()
        return key if key["SanityTaskType"] == "Essence" else None

    def getTags(self) -> str:
        """生成账号标签列表，返回JSON字符串格式的TagItem列表"""
        tags = []
        tags.append(
            {
                "text": f"上次：{_tag_last_status(self.Data.LastProxyStatus)}",
                "color": "red" if self.Data.LastProxyStatus == "失败" else "green",
            }
        )
        tags.append(_tag_proxy(self))
        tags.append(_tag_remained_days(self))
        if not self.Info.IfQuickConfig:
            tags.append(_tag_notes(self))
            return json.dumps(tags, ensure_ascii=False)

        if self.Task.IfProtocolSpace and self.Info.SanityStrategy in (
            "Native",
            "Inventory",
        ):
            label = (
                "库存目标"
                if self.Info.SanityStrategy == "Inventory"
                else "MaaEnd 原生策略"
            )
            tags.append({"text": f"协议空间：{label}", "color": "blue"})
        elif self.Task.IfProtocolSpace:
            task_key, _ = self.get_effective_sanity_task_key()
            sanity_task_type = task_key["SanityTaskType"]
            if sanity_task_type != "Essence":
                tags.append(
                    {
                        "text": f"协议空间：{_utils_constants.MAAEND_SANITY_TASK_LABELS[sanity_task_type]}",
                        "color": "blue",
                    }
                )
                detail_key = task_key[sanity_task_type]
                detail_label = self._maaend_crisis_drills_labels.get(
                    detail_key,
                    _utils_constants.MAAEND_SANITY_TASK_DETAIL_LABELS.get(
                        detail_key, detail_key
                    ),
                )
                tags.append({"text": f"详细任务：{detail_label}", "color": "blue"})
                if detail_key in _utils_constants.MAAEND_STAGE_WITH_AB:
                    label = (
                        "奖励组 A"
                        if task_key["RewardsSetOption"] == "RewardsSetA"
                        else "奖励组 B"
                    )
                    tags.append({"text": f"奖励组：{label}", "color": "blue"})
        if self.Task.IfAutoEssence:
            tags.append({"text": "基质刷取", "color": "blue"})
        tags.append(_tag_notes(self))
        return json.dumps(tags, ensure_ascii=False)

    @classmethod
    def normalize_payload(cls, data):
        data = migrate_maaend_sanity_tasks(deepcopy(data))
        info_data = data.get("Info")
        if isinstance(info_data, dict):
            legacy_base = str(info_data.get("Mode") or "")
            # 旧 Mode 同时决定来源和覆写常规配置开关；已给出的新来源始终优先。
            if "Base" not in info_data and legacy_base == "自定义":
                info_data["Base"] = "independent"
                info_data["IfQuickConfig"] = False
            elif (
                "Base" not in info_data
                and legacy_base in ("简洁", "详细")
                and "SanityMode" not in info_data
            ):
                info_data["Base"] = "shared"
                info_data.pop("IfQuickConfig", None)
        task_data = data.get("Task")
        if isinstance(task_data, dict):
            _normalize_maaend_sanity_task_type(task_data)
        return data

    @virtual_field("Info.Tag")
    def compute_Info_Tag(self):
        try:
            return self.getTags()
        except Exception as exc:
            return str(exc)

    class Metadata(UserEntry.Info):
        config_path: Virtual[str] = None  # pyright: ignore[reportIncompatibleVariableOverride]
        name: Virtual[str] = None  # pyright: ignore[reportIncompatibleVariableOverride]
        enabled: Virtual[bool] = None  # pyright: ignore[reportIncompatibleVariableOverride]

    info: Metadata = Field(default_factory=Metadata)  # pyright: ignore[reportIncompatibleVariableOverride]

    @virtual_field("info.name")
    def plugin_name(self):
        return self.Info.Name

    @virtual_field("info.enabled")
    def plugin_enabled(self):
        return self.Info.Status

    @virtual_field("info.config_path")
    def plugin_config_path(self) -> str:
        from auto_mas_core import Config

        from .script import MaaEndConfig

        parent = self.parent
        script = parent.parent if parent is not None else None
        if not isinstance(script, MaaEndConfig):
            return ""
        if self.Info.Base == "native":
            return str(script.Info.Path / "config") if script.Info.Path else ""
        owner = self.uid if self.Info.Base == "independent" else "Default"
        return str(Config.data_path / str(script.uid) / str(owner) / "ConfigFile")
