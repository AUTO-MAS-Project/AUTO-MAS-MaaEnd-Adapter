# MaaEnd 插件化迁移状态

基准：`AUTO-MAS` 仓库 `dev` 分支，插件 SDK `auto_mas_core` 5.9.0b1。
参考：`AUTO-MAS-SRC-Adapter`、`AUTO-MAS-MAA-Adapter`、`AUTO-MAS-Whimbox-Adapter` 的仓库布局与 SDK 用法。

## 一、已完成

### 配置模型

`config/` 包已迁出 `MaaEndConfig`、`MaaEndUserConfig`、`MaaEndPlanConfig` 与两个计划 key：
- 托管/账号保留原 PascalCase 业务字段，基类改为 `ScriptEntry` / `UserEntry`；账号集合为 `users`，
  名称、启用状态、配置目录通过 `Metadata` 虚字段投影给宿主。
- 计划表 `MaaEndPlanConfig` 继承 `PlanEntry`，复制 `PlanDaysConfig` / `WeeklyKeyPlan` 的取组逻辑，
  `normalize_payload` 负责把历史 `Key` 形状收敛为当前模型。
- `MaaEndConfig.normalize_payload` 把旧 `UserData`、`SubConfigsInfo.UserData` 转到 `users`，
  并保留 `RestoreResolution=Fullscreen` 的旧值迁移。
- `tests/test_config_migration.py` 覆盖上述迁移与虚字段投影。

1. 在 `src/auto_mas_maaend_adapter/` 建立包结构，所有模块文件名改为 snake_case。
2. 原 `app/core/notify/formats/maaend.py` 与 `app/services/common/endfield_launcher.py` 属于本专项，
   分别迁入 `notifications.py` 与 `tools/endfield_launcher.py`。
3. 叶子模块的宿主导入改为 `auto_mas_core` 已导出的 host 模块：工具层、资源解析、日志采集规则、
   奖励统计、通知、备份归档与恢复、配置服务、HTTP 路由、安装更新。
4. `auto_mas_core` 还没有导出的少量宿主能力集中在 `compat/`（见 1.1），不向主程序的
   `plugins/auto_mas_core` 添加文件；主仓 SDK 由维护者独立发版。

### 1.1 SDK 边界与 compat 层

插件代码只 import `auto_mas_core` / `auto_mas_core.host.*`、MaaFW 适配器拆出的库和插件自己的模块。
MaaFramework 的 `interface.json` 解析、任务选项、预任务计划与 MXU 标签已经由 `auto-mas-maafw-interface`
库提供（`pyproject.toml` 已依赖），不再走宿主 `app.task.MaaFW`，也不进 compat。

下面这些宿主能力 SDK 5.9.0b1 还没有导出，也没有对应的 MaaFW 库，先放在
`src/auto_mas_maaend_adapter/compat/` 里按需转发；每个文件都写了目标模块与待删条件：

| compat 文件 | 转发目标 | 用途 |
| --- | --- | --- |
| `client.py` | `app.task.client` | 游戏客户端可执行文件、启动器路径、客户端进程 |
| `desktop_session.py` | `app.task.desktop_session_worker` | 桌面分身动作请求 |
| `notify_report.py` | `app.core.notify.report` | 账号结果与推送日志排版 |
| `ocr.py` | `app.tools.common.ocr` | 启动器画面文字识别 |
| `error_screenshot.py` | `app.tools.common.error_screenshot` | 失败截图存档 |
| `game_window.py` | `app.utils.common.game_window` | 窗口查找、激活、截图 |
| `zip_range.py` / `zip_delta.py` | `app.utils.common.zip_*` | 增量包重组与补丁 |
| `maafw_game_resolution.py` | `app.task.MaaFW.tools.embedded.game_resolution` | 读终末地 PC 客户端分辨率与显示模式 |
| `maafw_project_update.py` | `app.task.MaaFW.tools.core.project_update.*` | 区间读取与限速；见下方说明 |

`auto-mas-maafw-project-update` 0.2.0 不能在当前宿主上直接 import：它回退到
`app.utils.common.zip_range` 取 `HealSkip`，而当前 `dev` 的 `zip_range` 还没有这个符号，SDK 5.9.0b1
也没有 `utils_common_zip_range`。等宿主升级到带该导出的版本后，删掉 `maafw_project_update.py`，改为
依赖 `auto-mas-maafw-project-update>=0.2,<0.3` 并从 `maafw_project_update.core.project_update` 取
`RangeHTTPReader` / `RangeSpeedGuard`。

有 SDK 现成入口的能力不要进 compat：`io`、`log_box`、`process`（含 operations/session/manager）、
`log.sources`、`script_install`、`services_common_update.transport`、`devices.task` 都直接从
`auto_mas_core.host.*` / `auto_mas_core.devices.task` 取。

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
| `auto_proxy.py` | `app.models.config`、`app.task.base.ScriptAutoProxyBase`、`app.task.MaaFW.tools.*` | 改写为 `AutoProxyWorker`；MaaFW 依赖先走 `compat/maafw_*.py` |
| `config_session.py` | `app.models.config`、`app.models.task.TaskExecuteBase/ScriptItem` | 改写为 `ScriptConfigWorker` / `ScriptViewWorker` |
| `manual_update.py` | `app.models.config`、`app.models.task.TaskExecuteBase` | 改写为维护任务接口 |
| `config_service.py`、`tools/script_update.py` | `app.models.config.MaaEndConfig` | 配置模型迁出后改为相对导入 |
| `tools/package_download.py` | `app.task.MaaFW.tools.core.project_update.*` | 由 MaaFW 能力提供方或 SDK 补齐后替换 `compat/maafw_project_update.py` |

## 四、剩余工作（按依赖顺序）

### 1. 已完成

- 配置模型、执行器、插件入口、插件自有备份恢复端点与前端页面已完成。
- 单账号总时限已在 `AutoProxyTask.main_task` 里包 `Run.HardTimeLimit`。
- 静态检查、52 个模块导入与 13 条单元测试通过；前端 33 个文件通过 `vue-tsc`。

### 2. 宿主切换（已在 worktree 跑通，未合并）

- 插件 `pre_enable` 在宿主仍内置 MaaEnd 类型时直接拒绝启用，避免两套同名类型并存。
- 已在 `/home/uy_sun/dev/AUTO-MAS-maaend-cutover-20261124` 实删：`CLASS_BOOK` / `PLAN_BOOK`
  的 MaaEnd、`builtin_registration` 的注册、`main.py` 的服务与预热、内置路由；
  `plugin_upgrade` 增加旧 `MaaEndConfig` / `MaaEndPlanConfig` 自动装插件，并在安装前先发现本地工程。
- 用真实旧 `scripts.yaml` 跑 `Config.init_config()` + `Plugin.initialize()`：插件自动启用，
  `UserData` 迁成 `users` 并落盘；新建托管、账号、计划表都走插件类型。
- 仍未删内置 `app/task/MaaEnd` 包与三个配置类：桌面分身 worker 还直接 import 其中的
  login/launcher 工具，等这些工具迁到插件能力后再删，避免桌面动作断链。

### 3. 手动「检查更新」入口

- 宿主 `TaskManager.start_maintenance` 只走旧 manager 维护链，插件没有标准维护任务入口。
- `manual_update.py`（原 `Update.py`）保留为遗留代码；等宿主提供维护任务接口后再接回。
  现在自动任务里的客户端更新仍可用（`prepare` 的 `_prepare_game_update`）。

### 4. 配置服务与恢复面板（已完成）

- `MaaEndConfigService.get_options()` 首次读取时补做 `initialize`（Client→MaaEnd 启动方式迁移，幂等、
  失败只告警），并调度一次 `preload_resources` 后台任务；插件停用时取消任务。
- 备份恢复改由插件自己的 `/api/plugin/maaend_adapter/backup/{list,ensure,restore,preview,file}`
  提供，使用 `RESTORE_POOLS` + `build_restore_service`，不依赖宿主恢复池解析器；
  错误包络与宿主一致，恢复前检查托管锁。
- 测试覆盖 mas/native 两池的 ensure/list/preview/restore 主路径、非法 target、缺失备份、
  路径穿越；跨 shared/independent/native 的来源切换还没有专门用例。

### 5. 前端页面（继续由主程序提供）

- GUI 仍使用宿主 `frontend/src/views/EditView/` 下的 MaaEnd 编辑页与计划表，插件仓库不包含
  `frontend/`，也不参与宿主动态前端加载。
- 这样插件发行包只负责后端能力，GUI 随主程序版本发布；后续如果宿主动态前端加载上线，再单独迁移。

### 6. 验证

- 已做：compileall、ruff、52 个模块导入、13 条测试；宿主 worktree 里旧配置冷启动、插件
  自动安装/启用、托管/账号/计划创建、备份端点全部跑通。
- 待做：Windows 真机覆盖三种启动方式、两条切号、配置保存/只读查看、程序更新接管、
  终末地差量更新、通知与失败取证；ModAVD 行为、桌面分身动作。

## 五、已知风险

1. MaaEnd 目前直接复用 MaaFW 的 `interface` 解析、任务选项映射、`run_plan` 与
   `RangeHTTPReader` / `RangeSpeedGuard`。插件化后要么由 MaaFW 插件提供能力，要么抽到 SDK；
   不要复制一份 MaaFW 内部实现。
2. MAS 自建账号切换依赖 `res/MaaFW/image/EndFieldPC` 下 4 张模板图（登出、确认、退出、退出确认）。
   插件化后要么随插件分发，要么由 SDK 提供资源目录，不能继续读宿主 `res`。
3. `update_takeover.py` 按 MXU 日志文本判断更新状态，属于上游私有格式透传；上游改文案会静默失效，
   迁移时保留现有注释与版本核对点。
4. 日志包导出规则复刻 MXU `export_logs_blocking`，同样随上游变化。
5. `BoundEmulator.open` 默认拒绝 ModAVD（`allow_mod_avd=False`），旧 `DeviceBase.open` 没有这个限制；
   原来用 ModAVD 的用户会收到「当前专项不支持 ModAVD」，需要实机确认后再决定是否显式放开。
6. 插件声明的 `prefetch_check` 只负责队列预下载；`prefetch_script_update` / `discard_prefetched_update`
   在插件世界没有宿主调用点，运行前安装是否复用预取产物需要实测确认。
7. 配置会话结束时 `ModeWorker.final_task` 会把账号状态改写成「已取消」，所以原生来源是否保留
   GUI 写回改读 `native_config_saved`，不能再用 `status == "完成"`。