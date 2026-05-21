# 集成测试步骤

## 测试环境准备

```bash
cd /root/reward-platform
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

编辑 `.env` 文件，至少填入有效的 `OPENAI_API_KEY`（其他 Key 可使用默认占位值进行功能验证）。

## 测试步骤

### 1. 启动 Flask

```bash
cd /root/reward-platform
source venv/bin/activate
python app.py
```

预期输出：
```
==================================================
  TokenCore + Claude AI + Bitrefill 奖励平台
  运行地址: http://localhost:5000
==================================================
 * Running on http://0.0.0.0:5000
```

### 2. 用户注册 → 钱包生成

用 curl 或浏览器访问：

```bash
# 注册新用户
curl -X POST http://localhost:5000/api/register \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123456"}'
```

预期返回：
```json
{
  "success": true,
  "username": "testuser",
  "wallet_address": "0x...",
  "message": "注册成功！钱包已自动创建"
}
```

验证：钱包地址应为合法的以太坊地址格式（0x 开头，42 字符）。

### 3. 查看任务

```bash
# 登录
curl -X POST http://localhost:5000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"testuser","password":"test123456"}' \
  -c cookies.txt

# 查看任务列表
curl -s http://localhost:5000/api/tasks -b cookies.txt | python -m json.tool
```

预期：返回 5 个默认任务（关注 Twitter、加入 Telegram 等），每个任务有 `reward_type` 和 `reward_amount`。

### 4. AI 生成任务

```bash
curl -X POST http://localhost:5000/api/tasks/generate \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{"count":3}'
```

预期：返回 3 个 AI 生成的新任务。如果 `OPENAI_API_KEY` 无效，返回错误提示。

### 5. 完成并领取 Token 奖励

```bash
# 先获取任务 ID（假设任务 1 是 token 类型）
# 完成任务
curl -X POST http://localhost:5000/api/tasks/1/complete \
  -H "Content-Type: application/json" \
  -b cookies.txt

# 领取奖励
curl -X POST http://localhost:5000/api/claim/1 \
  -H "Content-Type: application/json" \
  -b cookies.txt
```

预期：返回 `{"success":true,"reward_type":"token","amount":10,"new_balance":10}`

### 6. 查看钱包

```bash
curl -s http://localhost:5000/api/wallet -b cookies.txt | python -m json.tool
```

预期：显示钱包地址、ETH 余额（Sepolia 测试网）、平台积分余额。

### 7. 查看奖励记录

```bash
curl -s http://localhost:5000/api/rewards -b cookies.txt | python -m json.tool
```

预期：列出所有已领取的奖励，含任务标题、类型、金额、状态。

### 8. 查看交易记录

```bash
curl -s http://localhost:5000/api/transactions -b cookies.txt | python -m json.tool
```

预期：显示所有 earn/spend 记录。

### 9. 数据库验证

```bash
sqlite3 /root/reward-platform/reward_platform.db ".tables"
sqlite3 /root/reward-platform/reward_platform.db "SELECT * FROM users;"
sqlite3 /root/reward-platform/reward_platform.db "SELECT * FROM rewards;"
sqlite3 /root/reward-platform/reward_platform.db "SELECT * FROM transactions;"
```

预期：各表有数据，私钥字段为加密后的密文（非明文）。

### 10. 浏览器前端验证

打开 `http://localhost:5000`：

- [ ] 注册新用户 → 显示钱包地址
- [ ] 登录已有用户
- [ ] 进入"任务大厅" → 看到任务列表
- [ ] 点击"AI 生成任务" → 新任务出现
- [ ] 点击"接受任务"/"标记完成" → 状态变更
- [ ] 点击"领取奖励" → Token 到账
- [ ] "我的钱包" → 积分更新
- [ ] "奖励记录" → 显示历史奖励

### 11. Bitrefill 支付回调

```bash
# 模拟 Bitrefill webhook（替换 INVOICE_ID）
curl -X POST http://localhost:5000/api/webhook/bitrefill \
  -H "Content-Type: application/json" \
  -d '{"id":"INVOICE_ID","status":"complete","orders":[]}'
```

预期：返回 `{"received":true}`，服务端日志输出回调信息。

### 12. 错误场景验证

- [ ] 未登录直接访问 `/api/wallet` → 返回 401
- [ ] 不完成任务直接领取奖励 → 返回错误
- [ ] 重复领取同一任务奖励 → 返回错误
- [ ] 已注册用户名再次注册 → 返回 409 冲突

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| `ModuleNotFoundError` | `pip install -r requirements.txt` |
| Web3 连接失败 | 检查 `WEB3_PROVIDER_URI`，确认 Infura/Alchemy 项目 ID 有效 |
| AI 生成失败 | 检查 `OPENAI_API_KEY` 是否有效且有余额 |
| Bitrefill 购买失败 | 检查 `BITREFILL_API_KEY`，确认账号有余额 |
| 数据库锁定 | 重启 Flask，SQLite WAL 模式会自动恢复 |
