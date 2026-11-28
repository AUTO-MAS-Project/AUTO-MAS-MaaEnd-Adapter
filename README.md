# MaaEnd Adapter

AUTO-MAS 的 MaaEnd 专项适配插件，把 MaaEnd 接入 AUTO-MAS 的托管、账号、计划与执行体系。

MaaEnd 是《明日方舟：终末地》的 MaaFramework PI V2 项目，外置图形界面由 MXU 承载。
本插件负责安装目录、`config/mxu-MaaEnd.json` 读写、启动方式、账号切换、更新接管、
备份恢复、日志采集与通知；游戏内识别与任务执行由上游 MaaEnd 完成。

## 功能

- 托管：安装目录、控制器协议、LaunchMode（Launcher / MaaEnd / MAS）与运行参数。
- 账号：共享、独立、原生三种配置来源，支持账号切换与配置写回。
- 计划：周计划、任务选项、难度、采集与理智配置。
- 更新：MaaEnd 程序更新接管、全量/增量更新与启动器更新。
- 备份恢复：MAS 账号配置与 MaaEnd 原生 `config/` 的归档、预览、恢复。
- 运行：日志采集、失败截图、通知、奖励与库存统计。
- 桌面分身：Win32 控制器的托管可保存「单独启动时使用的 Windows 会话」
  （`Run.ExecutionSession` 取 `main` / `desktop`），队列仍按整条派发。

## 环境

- Python 3.12。
- 已安装的 MaaEnd（MXU）及其 `config/mxu-MaaEnd.json`。
- 游戏、模拟器、窗口与账号切换相关功能需要 Windows；配置读写与单元测试可在 Linux 运行。

## 安装

请在已迁移 MaaEnd 的 AUTO-MAS 中通过插件中心安装 `auto-mas-maaend-adapter`。
插件 ID 为 `maaend_adapter`。从 `v5.10.0-beta.2` 起，包含 MaaEnd 迁移的 5.x 版本
可以加载此插件。已发行的 `v5.9.0` 和 `v5.10.0-beta.1` 仍内置 MaaEnd，无法安装此插件。

MaaEnd 与新版 MaaFW、M9A、MSS 适配器共用 `auto-mas-maafw-interface` 的 `0.3.x` 版本，
插件中心会一起安装所需的库。配套的 AUTO-MAS 提供原有 MaaEnd 页面、备份入口和
`res/MaaFW/image/EndFieldPC/` 下用于账号切换的图像模板。

### 恢复接管前的配置

已经升级到配置格式 `v2.2` 的用户，首次接管前会保留 `scripts.yaml`、`plans.yaml` 和 `queues.yaml`
的原件，备份位于用户数据目录的 `config/legacy-maaend-plugin/`。更早格式的原件仍备份到
`config/legacy-json/pre-upgrade/`。

适配器保存的账号仍用旧版能读的 `UserData` 字段。要还原首次接管前的 `v2.2` 数据，退出新版并另存
当前三份文件，再从 `legacy-maaend-plugin/` 把同名文件复制回 `config/`。

## 目录

```text
src/auto_mas_maaend_adapter/
├── plugin.py              # 插件入口与生命周期
├── api.py                 # /api/scripts/maaend/* 路由
├── auto_proxy.py          # MaaEnd 任务执行与账号切换
├── expander.py            # 托管级编排
├── config_service.py      # 动态选项、启动器识别、日志包服务
├── config_session.py      # 脚本配置/查看会话
├── config/                # 托管/账号/计划三类配置模型与旧载荷迁移
├── resource_loader.py     # interface.json、任务定义与词表解析
├── manual_update.py       # 手动检查终末地客户端更新
├── update_takeover.py     # MXU 自身更新会话接管
├── notifications.py       # 通知图片与统计/库存负载
├── push_log.py            # 日志采集规则
├── inventory_report.py    # 奖励与库存展示
└── tools/                 # 安装更新、启动器、登录、备份恢复、日志包等原语
```

## 构建

使用 `uv` 管理构建，构建后端是 `uv_build`：

```bash
uv build                 # 同时生成 sdist 和 wheel
uv build --sdist         # 只生成源码包
uv build --wheel         # 只生成 wheel
```

产物在 `dist/`。`auto-mas-core` 由 AUTO-MAS 宿主在运行时以合成发行版提供，不是 PyPI 包，
所以本仓库不生成 `uv.lock`，也不建议直接 `uv sync`。

## 开发与测试

单元测试使用已包含 MaaEnd 迁移的 AUTO-MAS 源码。即使该源码还显示 `v5.10.0-beta.1`，
测试仍可直接引用源码提供的接口。以下命令从插件仓库运行，并把测试数据放在临时目录。

```bash
host=/path/to/AUTO-MAS
adapter="$(pwd)"
test_dir="$(mktemp -d -t maaend-adapter-tests-XXXXXX)"
UV_PROJECT_ENVIRONMENT="$test_dir/.venv" uv sync --project "$host" --locked --group dev
uv pip install --python "$test_dir/.venv/bin/python" "auto-mas-maafw-interface>=0.3.0,<0.4"
(cd "$test_dir" && AUTO_MAS_HOST_SOURCE="$host" \
  "$test_dir/.venv/bin/python" -m pytest -q "$adapter/tests")
"$test_dir/.venv/bin/ruff" check src tests
```

用完整应用联调时，把插件源码放在兼容宿主的 `plugins/maaend_adapter` 下。
宿主启动时也会检查本地源码插件的依赖，版本仍是 `v5.10.0-beta.1` 时会拒绝加载。
从 `v5.10.0-beta.1` 准备下一次发版时，可在独立的宿主副本内运行
`python scripts/changelog.py release --kind beta --offline` 生成 `v5.10.0-beta.2` 的版本信息，
再用该副本加载源码或验证构建出的插件包。

插件通过 `auto-mas-core` 和 `auto-mas-maafw-interface` 提供的接口访问宿主和解析库。

## 许可

AGPL-3.0-or-later。
