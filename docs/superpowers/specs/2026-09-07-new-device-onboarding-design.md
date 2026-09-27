# Media 新设备名单导入与采集前置检查

用户要求查看已有抓取数据、确认 CDP 启动行为，并让空白设备先提供博主资料再采集。用户明确选择 Excel/CSV 模板导入。现有 15.3.0 / Bundle 0.2.0 候选已经完成测试，位于同一隔离工作树；本轮新增候选使用 runtime 15.4.0 / Bundle 0.3.0，保留旧候选文件与验收记录。

## 目标和页面/接口

新设备流程：生成空模板 -> 导入用户的 Excel/CSV -> 展示本地名单预览 -> 选择本次目标 -> 检查浏览器/登录 -> 用户明确发起采集。未配置目标时禁止采集，不安装采集运行时、不创建空运行目录、不启动浏览器。导入名单本身不抓取、不解析短链接、不访问平台。

Harness 增加 media_missher_setup 工具，使用状态和本地产物引导流程。template 生成 CSV/XLSX；import 读取明确提供的本地文件并返回预览和导入 ID；activate 用导入 ID 和行号选择本次目标，写入兼容既有控制器的私有 profile；status 只报告本地配置状态。多位同平台博主可存在名单中，但一次每平台只能选择一位，禁止默默取第一位。用户当前正式 profile 不在开发测试中改动。

Chrome/CDP 行为：当前采集核心仅 connect_over_cdp，不启动 Chrome。本机另有 RunAtLoad + KeepAlive 的 com.missher.chrome-cdp LaunchAgent，不随 Bundle 安装，也不是空白设备的默认行为。默认采集继续只连接已有浏览器。本轮保持已有 CDP 连接模式，不增加浏览器启动入口；不会复制登录态、自动登录或绕过风险暂停。用户若后续选择专用浏览器按钮，可作为独立增量实现，必须显式操作而非失败回退。

## 数据结构

模板列固定为 platform / creator_name / homepage_url，支持中文标题“平台、博主名称、主页链接”。支持 xhs/bilibili/douyin/weibo 及常用中文名。离线从严格 HTTPS 官方主页路径提取原生 ID，移除查询串与 fragment；拒绝短链、内容详情链接、错平台域名、用户信息、非默认端口、公式单元格、重复身份及缺字段。最多 200 条；限制输入文件、ZIP 展开和单元格大小。最终质量复核补充：在 ExcelJS 构建模型前流式检查 XML 行列坐标、范围、深度与节点/共享字符串/样式数量，拒绝合并单元格和命名范围，使用规范 OOXML 路径白名单及同一部件分类做预检，不支持嵌入对象/Excel 数据表；使用已经锁定的 saxes 5.0.1 作为显式依赖，不引入额外下载。

Creator = { platform, name, homepage, nativeId }。导入保存为版本 1 的私有不可变导入文件（随机值加内容摘要的 ID），在 private setup 目录内；预览只包含行号、平台、名称、规范主页，不包含凭据或页面访问令牌。activate 读取精确导入 ID 和正整数行号，验证规范名单摘要及对应预览原文，拒绝内容变化或同平台多选，备份已有 profile 并原子写入 platform_uids；保留合法既有 cdp_url/data_root 等配置。不会覆盖/删除未选择平台已有目标，除非另有明确操作；首次空白 profile 只包含选中的平台。`creator_targets` 保存名称和规范主页，`active_platforms` 精确保存本次选中的平台；保留的旧 UID 不会默默加入默认采集。每次采集固定私有 profile 快照，避免运行期间切换名单改变目标。

运行时前置检查在 ensureRuntime 前确认当前请求选中平台都有合法非空目标。默认平台范围在未显式指定时使用 `active_platforms`；旧 profile 未含此字段时使用已有平台，避免只配置 XHS 后默认运行四平台；空配置返回 needs-setup。原有已配置四平台行为保留。

## 验收

1. CSV 与 XLSX 往返模板、中文编码、精确 URL/UID、查询令牌剥离、重名与重复、错链接、公式及 ZIP/行数边界。
2. 空机器 template/import/status 无 Python runtime、浏览器或网络依赖；import 后仍不能采集，activate 后仅配置选中平台。
3. 缺 profile/空 profile/缺当前平台目标：ensureRuntime 和 processRunner 调用均为零，无 run 目录。
4. 旧 profile 保留与备份，导入文件不可变，权限 0700/0600、symlink/硬链接/越界拒绝。
5. 原有小红书冷却/暂停、停止和历史续采测试仍通过；真实平台请求 0。
6. Bundle/Setup 新版本逐字节 payload 验证、真实 Harness CLI 临时安装与新设备全流程合成 smoke；区分原生安装证据与真实平台采集。
