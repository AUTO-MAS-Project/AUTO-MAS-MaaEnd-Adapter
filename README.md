# MaaEnd Adapter

AUTO-MAS 的 MaaEnd 专项适配器，从主程序 `app/task/MaaEnd` 迁出的插件化工作区。

MaaEnd 是终末地的 MaaFramework PI V2 项目，外置图形界面由 MXU 承载。适配器负责进程、
安装目录、`config/mxu-MaaEnd.json` 读写、日志判态、配置备份恢复与 MAS 侧账号编排；
游戏内识别与任务成败由上游 MaaEnd 完成。

## 当前状态

这是迁移基线，不是可直接安装的插件：

- 已完成：目录与包结构、文件名规范化、叶子模块（工具层、资源解析、日志采集、通知、
  备份恢复、配置服务、HTTP 路由）的宿主导入改为 `auto_mas_core` 门面。
- 未完成：配置模型仍引用宿主 `app.models.config`；执行层仍基于宿主旧执行基类
  （`ScriptManagerBase` / `TaskExecuteBase`），尚未接入 `UserExpander` 与
  `AutoProxyWorker` 等插件执行接口；因此仓库还没有 `plugin.py` 入口。

详细进度、文件映射和剩余工作见 [`docs/migration-status.md`](docs/migration-status.md)。

## 目录

```text
src/maaend_adapter/
├── auto_proxy.py          # 自动代理执行（原 AutoProxy.py）
├── config_service.py      # 动态选项、启动器识别、日志包服务（原 api_service.py）
├── config_session.py      # 脚本配置/查看会话（原 ScriptConfig.py）
├── expander.py            # 托管级编排（原 manager.py）
├── manual_update.py       # 手动更新终末地客户端（原 Update.py）
├── api.py                 # /api/scripts/maaend/* 路由
├── notifications.py       # 通知图片与统计/库存负载（原 app/core/notify/formats/maaend.py）
├── resource_loader.py     # 解析 interface.json、任务定义与词表
├── push_log.py            # log_box 采集规则
├── inventory_report.py    # 奖励与库存展示
├── update_takeover.py     # MXU 自身更新会话接管
└── tools/                 # 安装更新、启动器、登录、备份恢复、日志包等原语
```

## 开发

主程序源码开发时把本仓库放在 `AUTO-MAS/plugins/maaend_adapter`，或设置 `AUTO_MAS_HOST_SOURCE`
指向主程序检出目录后运行测试。插件仓库的提交与发版在独立仓库完成，主程序只保留 SDK。
