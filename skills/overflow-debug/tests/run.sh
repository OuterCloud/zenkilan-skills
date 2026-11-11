#!/usr/bin/env bash
# 回归测试：用两个 fixture 验证 probe 能区分「被裁」和「可滚」。
# 需要本机 Chrome（或 CHROME_PATH 环境变量指向可执行文件）。
set -uo pipefail
cd "$(dirname "$0")/.."
PROBE="scripts/overflow-probe.mjs"
FAIL=0

check() {
  local name="$1" expect_clipped="$2" expect_scroll="$3" file="$4"
  local out
  out="$(node "$PROBE" "file://$PWD/tests/fixtures/$file" --viewport 700x900 --wait-ms 0 2>&1)"
  local code=$?
  if [ $code -ne 0 ]; then
    echo "FAIL $name: 脚本退出码 $code"; echo "$out"; FAIL=1; return
  fi
  local clipped scroll
  clipped="$(printf '%s' "$out" | sed -n 's/.*其中 \([0-9]\{1,\}\) 个被裁切.*/\1/p')"
  scroll="$(printf '%s' "$out" | grep -c '→ 可滚动')"
  if [ "$clipped" != "$expect_clipped" ] || [ "$scroll" != "$expect_scroll" ]; then
    echo "FAIL $name: 期望 clipped=$expect_clipped scrollable=$expect_scroll，实际 clipped=$clipped scrollable=$scroll"
    echo "$out"; FAIL=1; return
  fi
  echo "ok   $name (clipped=$clipped, scrollable=$scroll)"
}

check "shell 写死 900px 时应报被裁" "1" "0" "shell-clipped.html"
check "外壳放开后应只剩可滚动" "0" "1" "shell-fixed.html"

exit $FAIL
