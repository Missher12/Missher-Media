# 第三方组件

本导出仅包含 Media CDP 的 Python 源码、测试、文档与合成示例，不打包 Chrome、Python 解释器、Playwright 或 openpyxl 的实现。

`runtime/requirements.lock` 固定以下直接运行依赖；安装的发行包及其传递依赖保留各自的许可证和版权声明：

| 依赖 | 固定版本 | 项目许可证 | 项目 |
| --- | --- | --- | --- |
| Playwright for Python | 1.45.0 | Apache-2.0 | [v1.45.0 许可证](https://github.com/microsoft/playwright-python/blob/v1.45.0/LICENSE) |
| openpyxl | 3.1.5 | MIT | [3.1.5 PyPI 许可证元数据](https://pypi.org/project/openpyxl/3.1.5/) |

测试使用 pytest、pytest-asyncio、pytest-socket，需单独安装，不包含在此源码导出内。后续若分发包含依赖的二进制或安装包，应按该实际分发内容保留相应声明。

Media CDP 的 MIT 许可证仅适用于作者有权授权的原创部分，不改变第三方组件、平台内容或用户数据的权利。
