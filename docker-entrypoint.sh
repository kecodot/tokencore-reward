#!/bin/sh
set -e

echo "========================================="
echo "  TokenCore 奖励平台 (Docker)"
echo "========================================="

# 1. 启动 TokenCore Bridge (后台，不等待)
echo "[1/2] 启动 TokenCore Bridge (Node.js)..."
cd /app/wallet-bridge
node --experimental-wasm-stringref server.js &
BRIDGE_PID=$!

# 后台等待 Bridge 就绪（不阻塞 Flask 启动）
(
    i=0
    while [ $i -lt 30 ]; do
        if curl -s http://localhost:5001/api/wallet/health > /dev/null 2>&1; then
            echo "[Bridge] 就绪 (耗时 ${i}s)"
            exit 0
        fi
        if ! kill -0 $BRIDGE_PID 2>/dev/null; then
            echo "[Bridge] 进程异常退出!"
            exit 1
        fi
        sleep 1
        i=$((i + 1))
    done
    echo "[Bridge] 启动超时"
) &

# 2. 立即启动 Flask（不等待 Bridge，Railway 健康检查需要快速响应）
echo "[2/2] 启动 Flask (gunicorn)..."
cd /app
exec gunicorn app:app \
    -w 2 \
    -b 0.0.0.0:${PORT:-5000} \
    --access-logfile - \
    --error-logfile - \
    --timeout 120
