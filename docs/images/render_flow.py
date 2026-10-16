"""Render the private Media 17.0.2 flow illustration with Pillow; no product UI or user data."""
from pathlib import Path
import os
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
font_candidates = [os.environ.get("MEDIA_DIAGRAM_FONT", ""),
                   "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "/System/Library/Fonts/PingFang.ttc"]
font_path = next((p for p in font_candidates if p and Path(p).is_file()), None)
if font_path is None:
    raise SystemExit("Set MEDIA_DIAGRAM_FONT to a local Chinese font file.")

W, H = 1680, 1040
img = Image.new("RGB", (W, H), "#F5F3EE")
d = ImageDraw.Draw(img)
ink, muted, teal, border = "#183039", "#50646C", "#16645B", "#D6DED9"
def font(size):
    return ImageFont.truetype(font_path, size)
def text(x, y, value, size=24, fill=ink):
    d.text((x, y), value, font=font(size), fill=fill)
def line_text(x, y, lines, size=23, fill=muted, step=39):
    for line in lines:
        text(x, y, line, size, fill)
        y += step

text(64, 48, "Media@Missher", 56)
text(65, 126, "17.0.2  /  从明确目标到私有导出", 29, muted)
d.rounded_rectangle((1225, 60, 1616, 117), radius=28, fill="#DEEAE4")
text(1251, 72, "流程示意（非产品界面）", 25, teal)

cards = [
    ("01", "明确目标", ["用户指定平台与账号", "核对完整主页与范围", "只处理明确授权目标"], "明确目标 ≠ 切换登录账号"),
    ("02", "检查准备", ["检查目标与配置状态", "明确要求后开启浏览器", "用户手动登录并核对"], "连接成功 ≠ 已登录"),
    ("03", "顺序采集", ["仅使用 Chrome CDP", "单一浏览器所有者", "分页、数量和节奏有界"], "风险、挑战、登录墙即停"),
    ("04", "保存证据", ["保存已验证记录与清单", "保留缺失字段和时间", "报告真实数量与停止原因"], "部分结果不冒充完整结果"),
    ("05", "选择导出", ["按目标、字段和格式选择", "只读取已有私有结果", "可重新筛选并再次导出"], "Excel / CSV / JSON 等"),
]
card_w, gap, start_x, top, bottom = 288, 28, 64, 237, 636
for i, (number, title, lines, note) in enumerate(cards):
    x = start_x + i * (card_w + gap)
    d.rounded_rectangle((x, top, x + card_w, bottom), radius=20, fill="#FFFFFF", outline=border, width=2)
    d.rounded_rectangle((x + 22, top + 24, x + 82, top + 76), radius=12, fill="#E6EFEB")
    text(x + 34, top + 31, number, 28, teal)
    text(x + 22, top + 98, title, 32)
    line_text(x + 22, top + 168, lines, size=21, step=40)
    d.line((x + 22, bottom - 78, x + card_w - 22, bottom - 78), fill=border, width=2)
    text(x + 22, bottom - 61, note, 17, teal)
    if i < len(cards) - 1:
        a, b, y = x + card_w + 5, x + card_w + gap - 5, 428
        d.line((a, y, b, y), fill=teal, width=3)
        d.polygon([(b, y), (b - 6, y - 5), (b - 6, y + 5)], fill=teal)

d.rounded_rectangle((64, 688, 1616, 838), radius=20, fill="#E7EEE8")
text(92, 709, "遇到阻断：立即停止，保留已验证结果", 30, teal)
text(92, 767, "不自动重试  ·  不自动恢复  ·  不清除风险状态  ·  不绕过验证挑战", 25, ink)
text(65, 882, "采集与导出分开：缺失字段如实说明，离线导出不会静默补抓。", 25)
text(65, 936, "本图仅说明流程；不代表真实平台成功率、安装状态或原生界面验收。", 22, muted)
text(65, 981, "私有仓库文档  ·  2026-10-14  ·  本地 Pillow 绘制 / 无账号、路径或真实采集数据", 18, muted)
out = ROOT / "media-flow-17.0.2.png"
img.save(out, optimize=True)
print(out)
