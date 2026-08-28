#!/bin/zsh
set -euo pipefail

REPOSITORY="Missher12/media-missher"
RELEASE_TAG="v15.2.1"
SETUP_ASSET="Media-Missher-Harness-Setup-v15.2.1.zip"
SETUP_CHECKSUM_ASSET="SETUP-SHA256.txt"

fail() {
  /usr/bin/osascript - "$1" <<'APPLESCRIPT'
on run arguments
  display dialog "Media@Missher GitHub 安装失败：" & item 1 of arguments buttons {"好"} default button 1 with icon stop
end run
APPLESCRIPT
  exit 1
}

GH_CLI=""
for candidate in /opt/homebrew/bin/gh /usr/local/bin/gh; do
  if [[ -x "$candidate" ]]; then
    GH_CLI="$candidate"
    break
  fi
done
if [[ -z "$GH_CLI" ]]; then
  GH_CLI="$(command -v gh || true)"
fi
[[ -x "$GH_CLI" ]] || fail "没有找到 GitHub CLI（gh）。请先安装 gh 并登录这个私有仓库。"
"$GH_CLI" auth status --hostname github.com >/dev/null 2>&1 \
  || fail "GitHub CLI 尚未登录。请先运行 gh auth login，并确认可访问私有仓库 $REPOSITORY。"

umask 077
DOWNLOAD_ROOT="$HOME/.dsh/downloads/media-missher"
/bin/mkdir -p "$DOWNLOAD_ROOT"
/bin/chmod 700 "$DOWNLOAD_ROOT"
DOWNLOAD_DIRECTORY="$(/usr/bin/mktemp -d "$DOWNLOAD_ROOT/v15.2.1.XXXXXX")"

# Authenticated equivalent: gh release download v15.2.1 --repo Missher12/media-missher
if ! "$GH_CLI" release download "$RELEASE_TAG" \
  --repo "$REPOSITORY" \
  --pattern "$SETUP_ASSET" \
  --pattern "$SETUP_CHECKSUM_ASSET" \
  --dir "$DOWNLOAD_DIRECTORY"; then
  fail "无法下载私有 Release $RELEASE_TAG。请检查 GitHub 登录权限后重试。"
fi

SETUP_ARCHIVE="$DOWNLOAD_DIRECTORY/$SETUP_ASSET"
SETUP_CHECKSUM="$DOWNLOAD_DIRECTORY/$SETUP_CHECKSUM_ASSET"
[[ -f "$SETUP_ARCHIVE" && ! -L "$SETUP_ARCHIVE" ]] || fail "Release 安装包缺失。"
[[ -f "$SETUP_CHECKSUM" && ! -L "$SETUP_CHECKSUM" ]] || fail "Release 校验文件缺失。"

EXPECTED_SHA="$(/usr/bin/awk -v asset="$SETUP_ASSET" '$2 == asset { print $1 }' "$SETUP_CHECKSUM")"
if [[ -z "$EXPECTED_SHA" || "$EXPECTED_SHA" == *$'\n'* ]] \
  || ! /usr/bin/printf '%s\n' "$EXPECTED_SHA" | /usr/bin/grep -Eq '^[0-9a-f]{64}$'; then
  fail "Release 校验文件格式无效。"
fi
ACTUAL_SHA="$(/usr/bin/shasum -a 256 "$SETUP_ARCHIVE" | /usr/bin/awk '{ print $1 }')"
[[ "$ACTUAL_SHA" == "$EXPECTED_SHA" ]] || fail "安装包 SHA-256 不匹配，安装已安全停止。"

for entry in "${(@f)$(/usr/bin/unzip -Z1 "$SETUP_ARCHIVE")}"; do
  [[ "$entry" == Media-Missher-Harness-Setup/* ]] || fail "安装包包含无效路径。"
  [[ "$entry" != *'/../'* && "$entry" != '../'* && "$entry" != /* ]] \
    || fail "安装包包含越界路径。"
done

EXTRACT_DIRECTORY="$DOWNLOAD_DIRECTORY/extracted"
/bin/mkdir "$EXTRACT_DIRECTORY"
/usr/bin/ditto -x -k "$SETUP_ARCHIVE" "$EXTRACT_DIRECTORY"
SETUP_ROOT="$EXTRACT_DIRECTORY/Media-Missher-Harness-Setup"
[[ -d "$SETUP_ROOT" && ! -L "$SETUP_ROOT" ]] || fail "安装包目录无效。"
[[ -z "$(/usr/bin/find "$SETUP_ROOT" -type l -print -quit)" ]] || fail "安装包不允许符号链接。"

INSTALLER="$SETUP_ROOT/Install Media@Missher Harness Plugin.command"
[[ -f "$INSTALLER" && ! -L "$INSTALLER" ]] || fail "Harness 安装器缺失。"
/bin/chmod 700 "$INSTALLER"

exec /bin/zsh "$INSTALLER"
