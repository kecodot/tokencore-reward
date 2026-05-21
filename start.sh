#!/bin/bash
# ============================================================
#  TokenCore 奖励平台 — 一键启动脚本
#  ============================================================
#  启动流程:
#    1. 启动 TokenCore Wallet Bridge (Node.js, @consenlabs/tcx-wasm)
#    2. 等待 Bridge 就绪
#    3. 启动 Flask 后端
#  ============================================================
set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BRIDGE_DIR="$ROOT_DIR/wallet-bridge"
BRIDGE_PID=""
FLASK_PID=""

cleanup() {
    echo ""
    echo "[Shutdown] 正在停止服务..."
    [ -n "$FLASK_PID" ] && kill "$FLASK_PID" 2>/dev/null
    [ -n "$BRIDGE_PID" ] && kill "$BRIDGE_PID" 2>/dev/null
    wait 2>/dev/null
    echo "[Shutdown] 已停止所有服务"
}
trap cleanup EXIT INT TERM

# ---- 1. 启动 TokenCore Wallet Bridge ----
echo "========================================="
echo "  TokenCore 奖励平台启动中..."
echo "========================================="
echo ""

if ! command -v node &> /dev/null; then
    echo "[ERROR] 未找到 Node.js，请安装 Node.js 22+"
    exit 1
fi

NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VERSION" -lt 22 ]; then
    echo "[WARN] Node.js 版本: $(node -v)，推荐 22+ 以支持 TokenCore WASM"
fi

echo "[1/3] 安装 wallet-bridge 依赖..."
cd "$BRIDGE_DIR"
npm install --silent 2>/dev/null || npm install
echo ""

echo "[2/3] 启动 TokenCore Wallet Bridge (port 5001)..."
node --experimental-wasm-stringref server.js &
BRIDGE_PID=$!

# 等待 Bridge 就绪
echo -n "  等待 Bridge 就绪"
for i in $(seq 1 30); do
    if curl -s http://localhost:5001/api/wallet/health > /dev/null 2>&1; then
        echo " ✓"
        break
    fi
    echo -n "."
    sleep 1
done
echo ""

# ---- 2. 启动 Flask 后端 ----
echo "[3/3] 启动 Flask 后端 (port 5000)..."
cd "$ROOT_DIR"

if [ ! -d "venv" ]; then
    echo "[ERROR] 未找到 Python 虚拟环境，请先运行: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

source venv/bin/activate
python app.py &
FLASK_PID=$!

echo ""
echo "========================================="
echo "  平台已启动!"
echo "  - 前端:    http://localhost:5000"
echo "  - Bridge:  http://localhost:5001"
echo "  - 健康检查: http://localhost:5001/api/wallet/health"
echo "========================================="
echo "  按 Ctrl+C 停止所有服务"
echo ""

# 保持运行
wait
