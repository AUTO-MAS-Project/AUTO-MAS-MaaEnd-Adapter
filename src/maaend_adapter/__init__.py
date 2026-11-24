"""MaaEnd 专项适配的插件化迁移工作区。

本包是从 ``app/task/MaaEnd`` 迁出的源码：文件布局按插件仓库习惯整理，文件名统一为
Python 习惯的 snake_case。执行层（``expander`` / ``auto_proxy`` / ``config_session`` /
``manual_update``）当前仍依赖宿主旧执行基类，尚未接入 ``UserExpander`` 与
``AutoProxyWorker`` 等插件执行接口，因此本包还没有 ``plugin.py`` 入口，不能被插件中心加载。
迁移进度与剩余工作见 ``docs/migration-status.md``。
"""

__all__: list[str] = []

