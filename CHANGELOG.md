# 更新日志

## [未发布]

### 新增

- 桌面分身：Win32 控制器的托管可保存 `Run.ExecutionSession`（`main` / `desktop`），
  启动器、客户端、MaaEnd、失败截图与 MAS 自建账号切换都在分身进程里执行。
- 插件声明 `desktop_session_check`，按托管实际生效的控制器协议判断能否走分身；
  `game_kind` 按控制器收窄可绑定的游戏类型。
- 接上宿主新增的插件钩子：保存托管配置前校验终末地启动器路径、从 MaaEnd
  安装目录导入配置、激活后迁移历史 `LaunchMode` 取值。

### 变更

- 依赖 `auto-mas-core>=5.10.0b1`：分身动作请求接口随该版本提供。

## [0.0.0] - 2026-11-24

### 变更

- 从主程序 `app/task/MaaEnd` 建立插件化迁移工作区，统一文件名为 snake_case。
