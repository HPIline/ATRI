#!/usr/bin/env bash
# 出图（grok-imagine-image-2.0 通道，带退避重试）
#
# 用法： bash ppt/gen_image.sh <输出png> <提示词文件> [宽高比] [分辨率]
#   例： bash ppt/gen_image.sh ppt/assets/cover-hero.png ppt/prompts/cover-hero.txt 16:9 2k
set -uo pipefail

OUT="$1"
PROMPT_FILE="$2"
RATIO="${3:-16:9}"
RES="${4:-2k}"
TRIES="${TRIES:-8}"
WAIT="${WAIT:-20}"

source "$HOME/.config/xbcl-imagegen.env"
GEN="/Users/hpi/.agents/skills/xbcl-imagegen/scripts/generate_grok_image.py"

for i in $(seq 1 "$TRIES"); do
  echo "[$(date +%H:%M:%S)] 第 $i/$TRIES 次 -> $(basename "$OUT")"
  # --no-prompt-prefix：不用技能自带的越狱前缀，保证画面风格完全由我们的提示词控制
  out=$(python3 "$GEN" "$(cat "$PROMPT_FILE")" --no-prompt-prefix \
        --aspect-ratio "$RATIO" --resolution "$RES" --out "$OUT" 2>&1 | tail -2)
  echo "$out"
  if [ -f "$OUT" ]; then
    echo "✓ 成功：$OUT"
    exit 0
  fi
  [ "$i" -lt "$TRIES" ] && { echo "   … 等待 ${WAIT}s"; sleep "$WAIT"; }
done

echo "✗ $TRIES 次均失败：$(basename "$OUT")"
exit 1
