"""MaaEnd 插件对宿主能力的兼容层。

这里只放 auto_mas_core 还没有导出的宿主模块。其它能力一律直接走
``auto_mas_core.host.*``，不要在本包重复转发。主仓 SDK 补齐后逐个删除。
"""

__all__: list[str] = []

