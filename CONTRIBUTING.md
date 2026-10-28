# 贡献指南

欢迎提交文档修正、合成复现、解析改进和测试。请先阅读 [README](README.md) 与[架构说明](docs/architecture.md)，保持 Chrome CDP 单一后端和共享核心。

## 报告问题

提供源码版本、操作系统、Python / Chrome 版本、平台和任务类型、预期行为、实际状态及最小复现步骤。日志、截图和样例先脱敏；不要上传 Cookie、令牌、浏览器资料目录、真实账号清单或未经授权的采集数据。安全问题按 [SECURITY.md](SECURITY.md) 处理。

## 本地验证

在独立虚拟环境中安装运行依赖与测试工具：

```bash
python -m pip install -r runtime/requirements.lock
python -m pip install pytest pytest-asyncio pytest-socket
PYTHONPATH=runtime python -m pytest -q -p no:cacheprovider \
  --disable-socket --allow-unix-socket tests/test_runtime*.py
```

上面的测试命令适用于 POSIX shell；`PYTHONPATH=runtime` 确保导入当前源码。测试工具是开发依赖，未加入运行依赖锁；报告结果时同时记录实际安装版本。测试应使用合成夹具，不能连接真实平台或读取日常浏览器资料。

请在单 worker、有限时间和内存下验证，并保留失败原因。离线测试、本地浏览器验证、真实平台采集和宿主接入是不同证据，不相互替代。

## 提交变更

- 一次改动围绕一个清楚的问题，说明触发场景、结果变化和相关验证。
- 保护真实的零、缺失字段、来源、风险状态、共享锁和已保存结果。
- 新增依赖需要说明用途、固定运行版本并更新第三方声明。
- 不提交生成的数据、浏览器状态、旧发行包或内部协作记录。
- 修改原样导出文件后，同步更新来源记录的准确含义；发布前重新生成校验清单，不能继续声称字节未变。

贡献的原创内容按本仓 MIT 许可证提供。第三方代码及依赖须保留原有许可证和必要署名。
