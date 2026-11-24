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

## 环境

- AUTO-MAS 5.9.0b1 及以上，Python 3.12。
- 已安装的 MaaEnd（MXU）及其 `config/mxu-MaaEnd.json`。
- 游戏、模拟器、窗口与账号切换相关功能需要 Windows；配置读写与单元测试可在 Linux 运行。

## 安装

作为 AUTO-MAS 插件安装。发行包名 `auto-mas-maaend-adapter`，插件 ID 为 `maaend_adapter`，
插件发现关键字为 `auto-mas-plugin` 与 `auto-mas-id:maaend_adapter`。

GUI 继续由主程序内置的 MaaEnd 页面提供，本插件不包含前端文件。

## 目录

```text
src/auto_mas_maaend_adapter/
├── plugin.py              # 插件入口与生命周期
├── api.py                 # /api/scripts/maaend/* 路由
├── backup_api.py          # /api/plugin/maaend_adapter/backup/* 路由
├── auto_proxy.py          # MaaEnd 任务执行与账号切换
├── expander.py            # 托管级编排
├── config_service.py      # 动态选项、启动器识别、日志包服务
├── config_session.py      # 脚本配置/查看会话
├── resource_loader.py     # interface.json、任务定义与词表解析
├── manual_update.py       # 手动检查更新
├── update_takeover.py     # MXU 自身更新会话接管
├── notifications.py       # 通知图片与统计/库存负载
├── push_log.py            # 日志采集规则
├── inventory_report.py    # 奖励与库存展示
├── compat/                # SDK 尚未导出的宿主能力转发
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

主程序源码开发时把本仓库放在 `AUTO-MAS/plugins/maaend_adapter`，或设置 `AUTO_MAS_HOST_SOURCE`
指向主程序检出目录。测试使用主程序解释器运行：

```bash
AUTO_MAS_HOST_SOURCE=/path/to/AUTO-MAS \
  /path/to/AUTO-MAS/.venv/bin/python -m pytest -q
/path/to/AUTO-MAS/.venv/bin/ruff check src tests
```

插件只依赖 `auto-mas-core` 与 `auto-mas-maafw-interface` 已导出的接口，不修改主程序的
`plugins/auto_mas_core`；宿主尚未导出的能力集中在 `compat/`，待 SDK 补齐后删除。

## 许可

AGPL-3.0-or-later。
