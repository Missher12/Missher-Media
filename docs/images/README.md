# Media 流程图

`media-flow-17.0.2.png` 是 **Media@Missher 17.0.2 流程示意（非产品界面）**，仅用于本私有仓库。

内容来自当前版本的目标确认、准备、Chrome CDP 顺序采集、私有证据和选择导出流程；没有账号、个人路径、凭据、会话或真实采集记录。它不表示安装成功、真实抓取成功率或原生 UI 已验收，也不进入公共桌面画廊。

生成方法：本地 Python + Pillow，画布 1680×1040，使用本机 Noto Sans CJK 或 PingFang 字体。源文件为 `render_flow.py`；可用 `MEDIA_DIAGRAM_FONT` 指定其他中文字体。字体仅用于渲染，不随仓库分发。

```sh
python3 docs/images/render_flow.py
```

生成日期：2026-10-14。兼容证据及边界见 [Host 兼容核验](../HOST_COMPATIBILITY_2026-10-14.md)。
