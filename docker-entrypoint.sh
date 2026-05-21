#!/bin/bash
set -e

echo "========================================="
echo "  TokenCore 奖励平台 (Docker)"
echo "========================================="

# 1. 启动 TokenCore Wallet Bridge (后台)
echo "[1/2] 启动 TokenCore Bridge (Node.js)..."
cd /app/wallet-bridge
node --experimental-wasm-stringref server.js &
BRIDGE_PID=$!

# 等待 Bridge 就绪
echo -n "  等待 Bridge"
for i in $(seq 1 20); do
    if curl -s http://localhost:5001/api/wallet/health > /dev/null 2>&1; then
        echo " ✓"
        break
    fi
    if ! kill -0 $BRIDGE_PID 2>/dev/null; then
        echo " ✗ Bridge 启动失败，查看日志:"
        cat /tmp/bridge.log 2>/dev/null || true
        exit 1
    fi
    echo -n "."
    sleep 1
done

# 2. 启动 Flask (前台，由 Docker 管理生命周期)
echo "[2/2] 启动 Flask (gunicorn)..."
cd /app
exec gunicorn app:app \
    -w 2 \
    -b 0.0.0.0:${PORT:-5000} \
    --access-logfile - \
    --error-logfile - \
    --timeout 120
