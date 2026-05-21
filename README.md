# TokenCore + Claude AI + Bitrefill 奖励平台

用户注册自动生成链上钱包 → AI 智能生成任务 → 用户完成任务 → 领取 Token / NFT / 礼品卡奖励

## 环境要求

- Python 3.10+
- 以太坊 Sepolia 测试网访问（Infura / Alchemy 账号）
- OpenAI API Key（用于 AI 任务生成）
- Bitrefill API Key（用于礼品卡购买，可选）

## 安装与运行

### 1. 创建虚拟环境

```bash
cd /root/reward-platform
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env` 并填写真实密钥：

```bash
cp .env.example .env
nano .env
```

必须填写的变量：

| 变量 | 说明 |
|------|------|
| `FLASK_SECRET_KEY` | Flask 会话签名密钥（随机字符串） |
| `FERNET_KEY` | 私钥加密密钥，生成方式见下方 |
| `OPENAI_API_KEY` | OpenAI API 密钥 |
| `BITREFILL_API_KEY` | Bitrefill API 密钥（Bearer token） |
| `WEB3_PROVIDER_URI` | Sepolia 测试网 RPC 地址 |

**生成 FERNET_KEY：**

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 4. 启动服务

```bash
python app.py
```

访问 `http://localhost:5000`

## 功能模块

| 模块 | 说明 |
|------|------|
| 用户系统 | 注册自动创建 ETH 钱包，私钥 Fernet 加密存储 |
| 任务系统 | 5 个默认任务 + AI 动态生成（OpenAI） |
| Token 奖励 | 平台积分即时到账 |
| NFT 奖励 | 通过智能合约铸造 ERC-721 NFT（Sepolia 测试网） |
| 礼品卡 | 调用 Bitrefill API 自动购买发放 |

## 数据库

自动创建 `reward_platform.db`（SQLite），包含 5 张表：

- `users` — 用户与钱包
- `tasks` — 任务列表
- `user_tasks` — 用户任务状态
- `rewards` — 奖励发放记录
- `transactions` — 交易流水

## 技术栈

- **后端：** Flask + SQLite
- **钱包：** web3.py + eth-account（替代 TokenCore SDK）
- **AI：** OpenAI API (GPT-3.5-turbo)
- **支付：** Bitrefill REST API v2
- **前端：** Pico.css + Vanilla JavaScript
