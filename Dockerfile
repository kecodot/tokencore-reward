# TokenCore 奖励平台 Docker 镜像
# Python Flask + Node.js TokenCore Bridge 双服务容器
FROM python:3.12-slim

# 安装 Node.js 22 + bash（TokenCore WASM 需要 Node 22+）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates bash \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Python 依赖 ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# ---- Node.js 依赖 ----
COPY wallet-bridge/package.json wallet-bridge/package-lock.json* wallet-bridge/
RUN cd wallet-bridge && npm install --production

# ---- 应用代码 ----
COPY . .

# 确保启动脚本可执行
RUN chmod +x /app/docker-entrypoint.sh

# 暴露端口（Railway 会通过 $PORT 覆盖）
EXPOSE 5000

# 环境变量默认值
ENV TOKENCORE_BRIDGE=http://localhost:5001
ENV WEB3_PROVIDER_URI=https://sepolia-infura.io/v3/demo

ENTRYPOINT ["/app/docker-entrypoint.sh"]
