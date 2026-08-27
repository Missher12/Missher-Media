#!/bin/zsh
set -euo pipefail

SCRIPT_DIRECTORY="$(cd -- "$(dirname -- "$0")" && pwd)"
ARCHIVE="$SCRIPT_DIRECTORY/harness-plugin/dist/dsh-media-missher-0.1.0.tgz"
HARNESS_RUNTIME="/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness"
HARNESS_CLI="/Applications/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/node_modules/@deepseek-ai/dsh/lib/bin.js"
HARNESS_PNPM="/Applications/DeepSeek Harness.app/Contents/Resources/app.asar.unpacked/node_modules/pnpm/bin/pnpm.cjs"
INSTALLER="$SCRIPT_DIRECTORY/harness-plugin/scripts/install-current-profile.mjs"

fail() {
  /usr/bin/osascript -e "display dialog \"Media@Missher 安装失败：$1\" buttons {\"好\"} default button 1 with icon stop"
  exit 1
}

[[ -f "$ARCHIVE" ]] || fail "安装包缺失，请重新下载完整项目。"
[[ -x "$HARNESS_RUNTIME" ]] || fail "没有找到 DeepSeek Harness.app，请先安装桌面版。"
[[ -f "$HARNESS_CLI" ]] || fail "DeepSeek Harness CLI 不完整，请重新安装桌面版。"
[[ -f "$HARNESS_PNPM" ]] || fail "DeepSeek Harness 内置依赖管理器缺失，请重新安装桌面版。"
[[ -f "$INSTALLER" ]] || fail "安装脚本缺失，请重新下载完整项目。"

export ELECTRON_RUN_AS_NODE=1
export DSH_DESKTOP_PNPM_ENTRY="$HARNESS_PNPM"
export DSH_TELEMETRY_MODE=DISABLED

if ! "$HARNESS_RUNTIME" "$INSTALLER" \
  --archive "$ARCHIVE" \
  --profile web \
  --runtime "$HARNESS_RUNTIME" \
  --cli "$HARNESS_CLI" \
  --pnpm "$HARNESS_PNPM"; then
  fail "安装程序已停止，原 profile 备份保留在 ~/.dsh/backups。"
fi

/usr/bin/osascript -e 'display dialog "Media@Missher 已安装。Harness 将重新打开并载入插件；默认直接抓取四个平台，每个平台 10 条，并生成 Excel 表格。" buttons {"重启 Harness"} default button 1 with icon note'

HARNESS_IS_RUNNING="$(/usr/bin/osascript -e 'application "DeepSeek Harness" is running')"
if [[ "$HARNESS_IS_RUNNING" == "true" ]]; then
  /usr/bin/osascript -e 'tell application "DeepSeek Harness" to quit'
  for _attempt in {1..40}; do
    HARNESS_IS_RUNNING="$(/usr/bin/osascript -e 'application "DeepSeek Harness" is running')"
    [[ "$HARNESS_IS_RUNNING" == "false" ]] && break
    /bin/sleep 0.25
  done
  [[ "$HARNESS_IS_RUNNING" == "false" ]] || fail "插件已安装，但 Harness 未能自动退出；请手动重启 Harness。"
fi
/usr/bin/open -a "DeepSeek Harness"
