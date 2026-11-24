# MaaEnd 插件化迁移状态

基准：`AUTO-MAS` 仓库 `dev` 分支，插件 SDK `auto_mas_core` 5.9.0b1。
参考：`AUTO-MAS-SRC-Adapter`、`AUTO-MAS-MAA-Adapter`、`AUTO-MAS-Whimbox-Adapter` 的仓库布局与 SDK 用法。

## 一、已完成

1. 在 `src/maaend_adapter/` 建立包结构，所有模块文件名改为 snake_case。
2. 原 `app/core/notify/formats/maaend.py` 与 `app/services/common/endfield_launcher.py` 属于本专项，
   分别迁入 `notifications.py` 与 `tools/endfield_launcher.py`。
3. 叶子模块的宿主导入改为 `auto_mas_core` 门面：工具层、资源解析、日志采集规则、奖励统计、
   通知、备份归档与恢复、配置服务、HTTP 路由、安装更新。
4. 保留 `app.*` 导入的文件只剩执行层与配置模型，见第三节。

## 二、文件名映射

| 原文件 | 新文件 | 改动原因 |
| --- | --- | --- |
| `AutoProxy.py` | `auto_proxy.py` | 模块名统一小写 |
| `ScriptConfig.py` | `config_session.py` | 同时覆盖配置与只读查看会话 |
| `Update.py` | `manual_update.py` | 避免与 `tools/update/` 包同名 |
| `manager.py` | `expander.py` | 对应插件 L3 执行器角色 |
| `api_service.py` | `config_service.py` | 说明它不是 HTTP 层 |
| `registration.py` | 移除 | 宿主注册声明由 `plugin.py` 取代，尚未创建 |
| `push_log.py` 等 | 同名 | 已是 snake_case |
| `app/core/notify/formats/maaend.py` | `notifications.py` | 专项专属格式随插件 |
| `app/services/common/endfield_launcher.py` | `tools/endfield_launcher.py` | 鹰角启动器识别随插件 |

## 三、仍旧依赖宿主内部的文件

| 文件 | 仍然导入 | 迁移去向 |
| --- | --- | --- |
| `expander.py` | `app.models.config`（MaaEnd 配置类）、`app.task.manager_base.ScriptManagerBase` | 配置迁到 `config/`，编排改写为 `UserExpander` |
| `auto_proxy.py` | `app.models.config`、`app.task.base.ScriptAutoProxyBase`、`app.task.MaaFW.tools.*` | 改写为 `AutoProxyWorker`；MaaFW 依赖改走能力门面 |
| `config_session.py` | `app.models.config`、`app.models.task.TaskExecuteBase/ScriptItem` | 改写为 `ScriptConfigWorker` / `ScriptViewWorker` |
| `manual_update.py` | `app.models.config`、`app.models.task.TaskExecuteBase` | 改写为维护任务接口 |
| `config_service.py`、`tools/script_update.py` | `app.models.config.MaaEndConfig` | 配置模型迁出后改为相对导入 |
| `tools/package_download.py` | `app.task.MaaFW.tools.core.project_update.*` | 由 MaaFW 能力提供方或 SDK 门面提供 |

## 四、剩余工作（按依赖顺序）

### 1. 配置模型迁出

- 从 `app/models/config/script.py` 取出 `MaaEndConfig`、`MaaEndUserConfig`，从
  `app/models/config/plan.py` 取出 `MaaEndPlanConfig`，从 `app/models/schema.py` 取出
  `MaaEndProtocolSpacePlanKey`、`MaaEndAutoEssencePlanKey`，放进 `config/script.py`、
  `config/user.py`、`config/plan.py`。
- 基类从 `DomainEntry` 换成 `ScriptEntry` / `UserEntry` / `PlanEntry`：账号集合用 `users`，
  公共字段用 `info.name` / `info.enabled`，业务字段保留原名，避免历史配置改键。
- 旧配置升级：在 `config/migration.py` 把 `UserData` 形状的旧记录转成 `users`，保留 UID、顺序、
  加密字段与备绑定；`legacy_config_class_name` 交给宿主升级入口识别。
- 计划表：`MaaEndPlanConfig` 换成 `PlanEntry` 子类，保留 `Info.Mode/RotateDays` 与 `Day1..Day31`。

### 2. 执行层改写

- `MaaEndManager` → `MaaEndExpander(UserExpander)`：`check()`、`prepare()`、
  `build_worker(user, config)`、`spawn(child)`（每账号跑完恢复安装目录配置）、`finish()`
  （原 `final_task` 的报告、通知、日志包）。
- `AutoProxyTask` → `AutoProxyTask(AutoProxyWorker)`：构造参数改为 `(expander, user, config)`，
  `main_task` → `main_logic`，`final_task` → `finish`；阶段循环、启动方式、账号切换、
  写 `mxu-MaaEnd.json`、等待 MXU、日志判态、失败截图与更新接管都保留。
- `ScriptConfigTask` → `ScriptConfigWorker` 与 `ScriptViewWorker` 共用一个会话基类，
  保留 `view_only` 语义：查看结束不写回 MAS 配置。
- `EndfieldUpdateTask` → 维护任务接口；宿主 `app/task/legacy.py` 的 `maintenance_requirements`
  只认内置类型名，插件化后要换成标准任务要求树。
- 关卡点：去掉 `app.task.base`、`app.task.manager_base`、`app.task.client`、`app.task.game`
  的直接导入，改用 `auto_mas_core.adapters.script`、`auto_mas_core.host.task_game`、
  `ModeWorker` 提供的设备与会话能力。

### 3. 插件入口

执行层改写完成后新增 `plugin.py`，形状与其他专项一致：

```python
class Plugin(ScriptAdapterPlugin):
    script_type_key = "MaaEnd"
    api_router = router
    decl = ScriptTypeDecl(
        script_type=MaaEndConfig,
        user_type=MaaEndUserConfig,
        expander_class=MaaEndExpander,
        plan_type=MaaEndPlanConfig,
        supported_modes=(
            TaskMode.AUTO_PROXY,
            TaskMode.SCRIPT_CONFIG,
            TaskMode.SCRIPT_VIEW,
        ),
        prefetch_check=check_prefetch,
        activity_game="endfield",
        game_kinds=("emulator", "client"),
    )
```

同时要保留宿主现在的三条前置判断：`MaaEnd.exe` 是否存在、控制器协议（Adb/Win32/CloudADB）、
以及 `config/mxu-MaaEnd.json` 是否可用；这些判断目前分别写在 `expander.check()` 与
`auto_proxy.check()` 里，迁移时不要合并成一条。

### 4. HTTP 与前端

- `api.py` 现在由宿主 `app/api/scripts/__init__.py` 直接 include；插件化后改为在 `plugin.py`
  里 `router.include_router(..., prefix="/api/scripts")`，路径保持 `/api/scripts/maaend/*`。
- 前端账号编辑页的 11 个分区（另有页头）、托管编辑页、计划表、配置会话遮罩、恢复面板仍在宿主
  `frontend/src/views/`，按 MAA / SRC / 奇想盒的方式用静态 `entry.ts` 注册，迁移时只搬页面与
  `useMaaEnd*` 组合式函数，路由后缀保持 `MaaEnd`。

### 5. 宿主切换

- 从 `app/task/builtin_registration.py` 移除 MaaEnd 注册，从 `main.py` 移除
  `MaaEndConfigService` 装配，从 `app/api/scripts/__init__.py` 移除路由。
- 删除内置 `MaaEndConfig` / `MaaEndUserConfig` / `MaaEndPlanConfig` 与调用点，或保留只读兼容层。
- 旧配置自动补装：按 `app/core/config/plugin_upgrade.py` 现有机制，在激活领域配置前识别
  `MaaEndConfig` 并安本插件。

### 6. 验证

- 静态：`uv run --no-sync python -m compileall src`、`ruff check`。
- 导入：把主程序源码与 `plugins/auto_mas_core/src` 加入 `sys.path`，导入每个模块。
- 真机：Windows + MaaEnd + 模拟器与 PC 客户端两种控制器；覆盖启动三种方式、账号切换两条路、
  配置会话保存与只读查看、程序更新接管、游戏客户端差量更新、备份恢复与通知。

## 五、已知风险

1. MaaEnd 目前直接复用 MaaFW 的 `interface` 解析、任务选项映射、`run_plan` 与
   `RangeHTTPReader` / `RangeSpeedGuard`。插件化后要么由 MaaFW 插件提供能力，要么抽到 SDK；
   不要复制一份 MaaFW 内部实现。
2. MAS 自建账号切换依赖 `res/MaaFW/image/EndFieldPC` 下 4 张模板图（登出、确认、退出、退出确认）。
   插件化后要么随插件分发，要么由 SDK 提供资源目录，不能继续读宿主 `res`。
3. `update_takeover.py` 按 MXU 日志文本判断更新状态，属于上游私有格式透传；上游改文案会静默失效，
   迁移时保留现有注释与版本核对点。
4. 日志包导出规则复刻 MXU `export_logs_blocking`，同样随上游变化。
