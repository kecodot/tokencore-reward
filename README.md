# TokenCore + Claude AI + Bitrefill 奖励平台

用户注册自动生成链上钱包(TokenCore HD Keystore) → AI 智能生成任务 → 用户完成任务 → 领取 Token / NFT / 礼品卡奖励

## Token Core 集成

本项目**必须使用 [TokenCore](https://github.com/consenlabs/token-core-monorepo)** 核心能力（钱包创建、账户推导、交易签名），满足 imToken 10周年 AI 共创大赛参赛要求。

### 集成架构

```
浏览器前端 (TokenCore WASM 可选)
     │
     ▼
Flask 后端 (Python) ──HTTP──▶ Wallet Bridge (Node.js)
                                  │
                                  ├─ @consenlabs/tcx-wasm (TokenCore)
                                  │    • create_keystore     钱包创建
                                  │    • derive_accounts     账户推导
                                  │    • sign_tx            交易签名
                                  │    • export_mnemonic    助记词导出
                                  │
                                  └─ 链上广播仍由 web3.py 完成
```

### Token Core API 使用说明

| Token Core 函数 | 调用位置 | 说明 |
|---|---|---|
| `create_keystore` | wallet-bridge POST /api/wallet/create | 用户注册时创建 HD 钱包 (PBKDF2) |
| `derive_accounts` | wallet-bridge POST /api/wallet/derive | 推导 ETH 账户地址 |
| `sign_tx` | wallet-bridge POST /api/wallet/sign | NFT/Token 奖励上链前签名 |
| `export_mnemonic` | wallet-bridge POST /api/wallet/export-mnemonic | 导出助记词 |

## 环境要求

- Python 3.10+
- Node.js 22+ (必需，低版本不支持 TokenCore WASM)
- 以太坊 Sepolia 测试网访问（Infura / Alchemy）
- OpenAI API Key（用于 AI 任务生成）
- Bitrefill API Key（用于礼品卡，可选）

## 快速开始

### 一键启动

```bash
cd /root/reward-platform
bash start.sh
```

### 手动安装与运行

#### 1. Python 环境

```bash
cd /root/reward-platform
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 2. 配置环境变量

```bash
cp .env.example .env
nano .env
```

必须配置的变量：

| 变量 | 说明 |
|------|------|
| `FLASK_SECRET_KEY` | Flask 会话签名密钥 |
| `FERNET_KEY` | Keystore 加密密钥 |
| `OPENAI_API_KEY` | OpenAI API 密钥 |
| `WEB3_PROVIDER_URI` | Sepolia RPC 地址 |

#### 3. 启动 Wallet Bridge (TokenCore)

```bash
cd wallet-bridge
npm install
node --experimental-wasm-stringref server.js
# 监听 http://localhost:5001
```

#### 4. 启动 Flask

```bash
source venv/bin/activate
python app.py
# 监听 http://localhost:5000
```

访问 `http://localhost:5000`

## 功能模块

| 模块 | 说明 | Token Core 使用 |
|------|------|----------------|
| 用户系统 | 注册时通过 TokenCore bridge 创建 HD 钱包 | `create_keystore` + `derive_accounts` |
| 任务系统 | 5 个默认任务 + AI 动态生成（OpenAI） | — |
| Token 奖励 | 平台积分即时到账 | — |
| NFT 奖励 | TokenCore 签名 + web3.py 广播 ERC-721 | `sign_tx` |
| 礼品卡 | 调用 Bitrefill API 自动购买发放 | — |

## 数据库

自动创建 `reward_platform.db`（SQLite），包含 5 张表：

- `users` — 用户与 TokenCore Keystore
- `tasks` — 任务列表
- `user_tasks` — 用户任务状态
- `rewards` — 奖励发放记录
- `transactions` — 交易流水

## 技术栈

- **钱包核心:** TokenCore @consenlabs/tcx-wasm v0.9.1（Node.js Wallet Bridge）
- **后端:** Flask + SQLite
- **链上交互:** web3.py（查询余额、广播已签名交易）
- **AI:** OpenAI API (GPT-3.5-turbo)
- **支付:** Bitrefill REST API v2
- **前端:** Pico.css + Vanilla JavaScript + TokenCore WASM (CDN)

## 验证 Token Core 使用

```bash
# 检查 Bridge 健康状态
curl http://localhost:5001/api/wallet/health
# → {"status":"ok","module":"TokenCore @consenlabs/tcx-wasm v0.9.1"}

# 测试钱包创建
curl -X POST http://localhost:5001/api/wallet/create \
  -H 'Content-Type: application/json' \
  -d '{"password":"demo","network":"TESTNET"}'
```

## 项目结构

```
reward-platform/
├── app.py                  # Flask 后端
├── templates/index.html    # 前端页面
├── static/main.js          # 前端交互逻辑 (含 TokenCore WASM CDN)
├── wallet-bridge/          # TokenCore 钱包桥接服务
│   ├── package.json
│   ├── server.js           # Node.js Express + @consenlabs/tcx-wasm
│   └── node_modules/
├── requirements.txt
├── start.sh                # 一键启动
└── .env
```
