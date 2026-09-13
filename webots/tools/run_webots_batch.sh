#!/usr/bin/env bash
# 无人值守地跑一遍 A.T.R.I. 的 Webots 联调（Linux/x86）。
#
# Webots 的 --batch 跑完之后不会自己退出：控制器按 --exit-on-done 退出了，
# 但仿真还在继续，Webots 进程一直挂着，控制台输出也一直不 flush。
# 所以这个脚本负责：后台启动 Webots → 等控制器写出联调报告 JSON →
# 结束 Webots → 打印结论。退出码 0 表示五项任务全过，2 表示没过。
# 找不到 webots 或世界文件：退出 3。
#
# 参数名与 run_webots_batch.ps1 对齐：
#   -World / -Report / -Log / -Webots / -Mapping / -TimeoutSec
#
# 用法：
#   bash webots/tools/run_webots_batch.sh
#   bash webots/tools/run_webots_batch.sh -Mapping joint_mapping_nao.json

set -uo pipefail

WORLD=""
REPORT=""
LOG=""
WEBOTS=""
MAPPING=""
TIMEOUT_SEC=300

usage() {
    cat <<'EOF'
用法: run_webots_batch.sh [-World 路径] [-Report 路径] [-Log 路径]
                          [-Webots 路径] [-Mapping 路径] [-TimeoutSec 秒]

退出码: 0 联调通过 / 2 未通过或超时 / 3 找不到 webots 或世界文件
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        -World|--World|--world)
            WORLD="${2:-}"
            shift 2
            ;;
        -Report|--Report|--report)
            REPORT="${2:-}"
            shift 2
            ;;
        -Log|--Log|--log)
            LOG="${2:-}"
            shift 2
            ;;
        -Webots|--Webots|--webots)
            WEBOTS="${2:-}"
            shift 2
            ;;
        -Mapping|--Mapping|--mapping)
            MAPPING="${2:-}"
            shift 2
            ;;
        -TimeoutSec|--TimeoutSec|--timeout-sec)
            TIMEOUT_SEC="${2:-}"
            shift 2
            ;;
        *)
            echo "未知参数: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ -z "$WORLD" ]]; then
    WORLD="$REPO_ROOT/webots/worlds/atri_v2.wbt"
fi
if [[ -z "$REPORT" ]]; then
    REPORT="$REPO_ROOT/atri_report.json"
fi
if [[ -z "$LOG" ]]; then
    LOG="$REPO_ROOT/atri_console.log"
fi

# 控制器的 cwd 是 webots/controllers/atri_controller/，相对路径会写到那里。
abspath() {
    python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$1"
}
WORLD="$(abspath "$WORLD")"
REPORT="$(abspath "$REPORT")"
LOG="$(abspath "$LOG")"
if [[ -n "$MAPPING" ]]; then
    MAPPING="$(abspath "$MAPPING")"
fi

RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[0;33m'
NC=$'\033[0m'

kill_webots() {
    pkill -KILL -x webots 2>/dev/null || true
    pkill -KILL -x webots-bin 2>/dev/null || true
}

if [[ -z "$WEBOTS" ]]; then
    if command -v webots >/dev/null 2>&1; then
        WEBOTS="$(command -v webots)"
    else
        for cand in \
            /usr/local/webots/webots \
            /usr/local/bin/webots \
            /opt/webots/webots \
            /usr/bin/webots \
            "$HOME/webots/webots" \
            /snap/bin/webots
        do
            if [[ -x "$cand" ]]; then
                WEBOTS="$cand"
                break
            fi
        done
    fi
fi

if [[ -z "$WEBOTS" || ! -e "$WEBOTS" ]]; then
    echo "${RED}找不到 webots，请用 -Webots 指定路径。${NC}" >&2
    exit 3
fi
if [[ ! -f "$WORLD" ]]; then
    echo "${RED}找不到世界文件: $WORLD${NC}" >&2
    exit 3
fi

rm -f "$REPORT" "$LOG"

# Webots 没有向控制器透传命令行参数的机制，只能靠环境变量
export ATRI_WEBOTS_EXIT_ON_DONE=1
export ATRI_WEBOTS_REPORT="$REPORT"
export ATRI_WEBOTS_LOG="$LOG"
if [[ -n "$MAPPING" ]]; then
    export ATRI_WEBOTS_MAPPING="$MAPPING"
fi

echo "Webots  : $WEBOTS"
echo "世界    : $WORLD"
echo "报告    : $REPORT"
echo "日志    : $LOG"
printf '%s\n' "------------------------------------------------------------"

kill_webots
sleep 1

"$WEBOTS" --batch --mode=fast --no-rendering --minimize --stdout --stderr "$WORLD" &
PROC=$!
disown "$PROC" 2>/dev/null || true

deadline=$((SECONDS + TIMEOUT_SEC))
appeared=0
while (( SECONDS < deadline )); do
    if [[ -f "$REPORT" ]]; then
        appeared=1
        break
    fi
    if ! kill -0 "$PROC" 2>/dev/null; then
        break
    fi
    sleep 0.5
done

if [[ -f "$REPORT" ]]; then
    appeared=1
fi

# 给控制器一点时间把日志 flush 完
sleep 2
if kill -0 "$PROC" 2>/dev/null; then
    kill -KILL "$PROC" 2>/dev/null || true
    wait "$PROC" 2>/dev/null || true
fi
kill_webots

if [[ "$appeared" -ne 1 ]]; then
    echo "${RED}超时 ${TIMEOUT_SEC}s，控制器没有写出报告——仿真没跑起来或控制器没启动。${NC}" >&2
    if [[ -f "$LOG" ]]; then
        echo "${YELLOW}控制台日志尾部:${NC}" >&2
        tail -n 40 "$LOG" || true
    fi
    exit 2
fi

PY=""
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "${RED}需要 python3 解析报告 JSON。${NC}" >&2
    exit 2
fi

"$PY" - "$REPORT" <<'PY'
import json
import sys
from pathlib import Path

report = Path(sys.argv[1])
result = json.loads(report.read_text(encoding="utf-8"))

unbound = result.get("unbound_joints") or []
print("")
print("=" * 60)
print("Webots 闭环: {0}/{1} 项任务通过".format(result["passed"], result["total"]))
print("  关节绑定  : {0}/{1}（映射应绑定 {2}，未绑定 {3} 个）".format(
    result["bound_joints"], result["expected_joints"],
    result["mapped_joints"], len(unbound)))
print("  有行程关节: {0}/{1}".format(result["moved_joints"], result["expected_joints"]))
print("  仿真时间  : {0} s（{1} 步，墙钟 {2} s）".format(
    result["sim_seconds"], result["sim_steps"], result["wall_seconds"]))
print("  报告      : {0}".format(report))
print("=" * 60)

travel = result.get("joint_travel_deg") or {}
zero = [name for name, val in travel.items() if val <= 1.0]
if zero:
    print("这轮没有任何行程的关节（当前任务卡用不到的自由度）:")
    for name in zero:
        print("  {0}".format(name))

# 绑定判据：实际绑定数 == 映射中非空条目数，且 > 0。
binding_ok = (result["bound_joints"] > 0) and (
    result["bound_joints"] == result["mapped_joints"]
)
if not binding_ok:
    print("绑定不完整：映射应绑定 {0} 个关节，实际绑定 {1} 个，联调结果不可信。".format(
        result["mapped_joints"], result["bound_joints"]))

if (
    result["passed"] == result["total"]
    and result["total"] > 0
    and result["simulation_alive"]
    and binding_ok
):
    print("联调通过。")
    sys.exit(0)

print("联调未通过。")
sys.exit(2)
PY
status=$?
exit "$status"
