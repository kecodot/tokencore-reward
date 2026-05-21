"""
TokenCore + Claude AI + Bitrefill 奖励平台
===========================================
用户注册自动生成钱包(通过TokenCore WASM) → AI生成任务 → 完成任务领取Token/NFT/礼品卡奖励

TokenCore 集成方式:
  钱包创建 & 交易签名 → 调用 wallet-bridge (Node.js, 封装 @consenlabs/tcx-wasm)
  链上交互 & 余额查询 → 使用 web3.py
"""
import os
import re
import json
import sqlite3
import datetime
from functools import wraps

import requests
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, request, jsonify, session, send_from_directory, g
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from web3 import Web3
from openai import OpenAI

# ---------- 配置 ----------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-in-production")

FERNET_KEY = os.getenv("FERNET_KEY", "")
try:
    fernet = Fernet(FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY)
except (ValueError, Exception):
    FERNET_KEY = Fernet.generate_key().decode()
    fernet = Fernet(FERNET_KEY.encode())
    print(f"[WARN] FERNET_KEY 无效或未设置，已生成新密钥: {FERNET_KEY}")
    print("      请将此密钥写入 .env 文件的 FERNET_KEY= 行，否则重启后无法解密已有私钥")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

BITREFILL_API_KEY = os.getenv("BITREFILL_API_KEY", "")
BITREFILL_BASE = "https://api.bitrefill.com/v2"

WEB3_PROVIDER_URI = os.getenv("WEB3_PROVIDER_URI", "https://sepolia.infura.io/v3/demo")
w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URI))

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reward_platform.db")

# TokenCore 钱包桥接服务地址（Node.js wallet-bridge）
TOKENCORE_BRIDGE = os.getenv("TOKENCORE_BRIDGE", "http://localhost:5001")

# 平台发奖钱包（用于给用户发 Token/NFT）
# 优先使用 PLATFORM_KEYSTORE_JSON（TokenCore keystore），
# 兼容旧的 PLATFORM_PRIVATE_KEY 方式
PLATFORM_KEYSTORE_JSON = os.getenv("PLATFORM_KEYSTORE_JSON", "")
PLATFORM_KEYSTORE_PASSWORD = os.getenv("PLATFORM_KEYSTORE_PASSWORD", "")
PLATFORM_PRIVATE_KEY = os.getenv("PLATFORM_PRIVATE_KEY", "")
PLATFORM_ADDRESS = os.getenv("PLATFORM_ADDRESS", "")

# ERC-20 代币合约地址（测试网 USDT 示例）
USDT_CONTRACT = "0x7169D38820dfd117C3FA1f22a697dBA58d90BA06"

# ERC-721 NFT 合约地址（占位，需部署自己的合约）
NFT_CONTRACT = os.getenv("NFT_CONTRACT_ADDRESS", "0x0000000000000000000000000000000000000000")


# ============================================================
#  数据库
# ============================================================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            wallet_address  TEXT NOT NULL,
            wallet_keystore TEXT NOT NULL,
            wallet_keystore_password TEXT NOT NULL,
            balance         REAL DEFAULT 0,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT NOT NULL,
            description     TEXT NOT NULL,
            reward_type     TEXT NOT NULL CHECK(reward_type IN ('token','nft','giftcard')),
            reward_amount   REAL NOT NULL,
            product_id      TEXT,
            is_active       INTEGER DEFAULT 1,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_tasks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            task_id         INTEGER NOT NULL,
            status          TEXT DEFAULT 'pending' CHECK(status IN ('pending','completed','claimed')),
            completed_at    TIMESTAMP,
            claimed_at      TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (task_id) REFERENCES tasks(id),
            UNIQUE(user_id, task_id)
        );

        CREATE TABLE IF NOT EXISTS rewards (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id             INTEGER NOT NULL,
            task_id             INTEGER NOT NULL,
            reward_type         TEXT NOT NULL,
            amount              REAL NOT NULL,
            status              TEXT DEFAULT 'pending' CHECK(status IN ('pending','processing','completed','failed')),
            tx_hash             TEXT,
            bitrefill_order_id  TEXT,
            redemption_code     TEXT,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         INTEGER NOT NULL,
            type            TEXT NOT NULL CHECK(type IN ('earn','spend')),
            amount          REAL NOT NULL,
            currency        TEXT NOT NULL,
            tx_hash         TEXT,
            description     TEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    db.commit()

    # 数据库迁移：wallet_private_key → wallet_keystore + wallet_keystore_password
    try:
        db.execute("ALTER TABLE users ADD COLUMN wallet_keystore TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("ALTER TABLE users ADD COLUMN wallet_keystore_password TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    # 插入默认任务（如果为空）
    count = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    if count == 0:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        default_tasks = [
            ("关注官方 Twitter", "关注项目官方 Twitter 账号并截图上传", "token", 10, None),
            ("加入 Telegram 社区", "加入官方 Telegram 社群并发言介绍自己", "token", 5, None),
            ("分享项目到朋友圈", "将项目海报分享到微信朋友圈并获得10个赞", "nft", 1, None),
            ("完成新手教程", "阅读项目白皮书并完成新手引导测验", "token", 20, None),
            ("邀请一位好友注册", "通过邀请链接邀请一位好友完成注册", "giftcard", 5, None),
        ]
        db.executemany(
            "INSERT INTO tasks (title, description, reward_type, reward_amount, product_id) VALUES (?,?,?,?,?)",
            default_tasks,
        )
        db.commit()

    db.close()


# ============================================================
#  辅助函数
# ============================================================
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"error": "请先登录"}), 401
        return f(*args, **kwargs)
    return decorated


def encrypt_key(private_key: str) -> str:
    return fernet.encrypt(private_key.encode()).decode()


def decrypt_key(encrypted_key: str) -> str:
    return fernet.decrypt(encrypted_key.encode()).decode()


# ============================================================
#  Wallet 模块 — 通过 TokenCore Bridge (基于 @consenlabs/tcx-wasm)
# ============================================================
class WalletModule:
    """
    EVM 钱包操作封装
    核心能力（创建/签名）通过 TokenCore bridge 调用 @consenlabs/tcx-wasm
    链上广播仍使用 web3.py
    """

    @staticmethod
    def _bridge(endpoint: str, payload: dict) -> dict:
        """调用 TokenCore wallet-bridge"""
        try:
            resp = requests.post(
                f"{TOKENCORE_BRIDGE}/api/wallet/{endpoint}",
                json=payload,
                timeout=30,
            )
            return resp.json()
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": f"无法连接 TokenCore bridge ({TOKENCORE_BRIDGE})，请先启动 wallet-bridge 服务"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def generate_wallet(password: str = None, network: str = "TESTNET") -> dict:
        """
        通过 TokenCore bridge 创建新钱包
        调用 @consenlabs/tcx-wasm 的 create_keystore + derive_accounts
        """
        import secrets
        import string
        if not password:
            password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(24))

        result = WalletModule._bridge("create", {
            "password": password,
            "network": network,
        })

        if not result.get("success"):
            return {"success": False, "error": result.get("error", "创建钱包失败")}

        keystore = result.get("keystore", {})
        account = result.get("account", {})

        return {
            "success": True,
            "address": account.get("address", ""),
            "keystore_json": keystore.get("json", ""),
            "keystore_password": password,   # 用户密码，用于解锁 keystore
            "mnemonic": result.get("mnemonic", ""),
        }

    @staticmethod
    def get_eth_balance(address: str) -> float:
        """查询 ETH 余额（Sepolia 测试网）"""
        try:
            wei = w3.eth.get_balance(w3.to_checksum_address(address))
            return float(w3.from_wei(wei, "ether"))
        except Exception:
            return 0.0

    @staticmethod
    def send_token(keystore_json: str, keystore_password: str,
                   to_address: str, amount: float,
                   derivation_path: str = "m/44'/60'/0'/0/0") -> dict:
        """
        通过 TokenCore bridge 签名 + web3.py 广播 ERC-20 转账
        调用 @consenlabs/tcx-wasm 的 sign_tx
        """
        if not w3.is_connected():
            return {"success": False, "error": "Web3 未连接，请检查 WEB3_PROVIDER_URI"}

        try:
            # 先从 keystore 推导地址（核实发送方）
            derive_result = WalletModule._bridge("derive", {
                "keystoreJson": keystore_json,
                "password": keystore_password,
                "derivations": [{
                    "chain": "ETHEREUM",
                    "derivationPath": derivation_path,
                    "chainId": "11155111",
                    "network": "TESTNET",
                }],
            })
            if not derive_result.get("success"):
                return {"success": False, "error": f"推导地址失败: {derive_result.get('error')}"}
            from_address = derive_result.get("accounts", [{}])[0].get("address", "")

            # 获取 nonce
            nonce = w3.eth.get_transaction_count(w3.to_checksum_address(from_address))
            gas_price = w3.eth.gas_price

            # ERC-20 transfer ABI 编码
            amount_wei = int(amount * 10**6)  # USDT 6 decimals
            data = (
                "0xa9059cbb"
                + w3.to_checksum_address(to_address)[2:].lower().rjust(64, "0")
                + hex(amount_wei)[2:].rjust(64, "0")
            )

            # TokenCore: 签名交易
            sign_result = WalletModule._bridge("sign", {
                "keystoreJson": keystore_json,
                "password": keystore_password,
                "chain": "ETHEREUM",
                "derivationPath": derivation_path,
                "input": {
                    "nonce": str(nonce),
                    "gasPrice": str(gas_price),
                    "gasLimit": "100000",
                    "to": USDT_CONTRACT,
                    "value": "0",
                    "data": data,
                    "chainId": "11155111",
                },
            })

            if not sign_result.get("success"):
                return {"success": False, "error": f"TokenCore 签名失败: {sign_result.get('error')}"}

            raw_tx = sign_result.get("signature") or sign_result.get("signedTx")
            if not raw_tx:
                return {"success": False, "error": "签名结果为空"}

            # 广播已签名的交易
            tx_hash = w3.eth.send_raw_transaction(raw_tx)
            return {"success": True, "tx_hash": tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def mint_nft(keystore_json: str, keystore_password: str,
                 to_address: str, token_uri: str,
                 derivation_path: str = "m/44'/60'/0'/0/0") -> dict:
        """
        通过 TokenCore bridge 签名 + web3.py 广播 NFT 铸造
        调用 @consenlabs/tcx-wasm 的 sign_tx
        """
        if not w3.is_connected():
            return {"success": False, "error": "Web3 未连接"}

        try:
            derive_result = WalletModule._bridge("derive", {
                "keystoreJson": keystore_json,
                "password": keystore_password,
                "derivations": [{
                    "chain": "ETHEREUM",
                    "derivationPath": derivation_path,
                    "chainId": "11155111",
                    "network": "TESTNET",
                }],
            })
            if not derive_result.get("success"):
                return {"success": False, "error": f"推导地址失败: {derive_result.get('error')}"}
            from_address = derive_result.get("accounts", [{}])[0].get("address", "")

            nonce = w3.eth.get_transaction_count(w3.to_checksum_address(from_address))
            token_id = int(datetime.datetime.utcnow().timestamp())

            # mint(to, uint256, string) ABI 编码
            uri_hex = token_uri.encode().hex().rjust(128, "0")
            to_hex = w3.to_checksum_address(to_address)[2:].lower().rjust(64, "0")
            tid_hex = hex(token_id)[2:].rjust(64, "0")

            data = (
                "0x50bb4e7f"  # mint(address,uint256,string) selector
                + to_hex
                + tid_hex
                + "0000000000000000000000000000000000000000000000000000000000000060"
                + "0000000000000000000000000000000000000000000000000000000000000000"
                + uri_hex
            )

            sign_result = WalletModule._bridge("sign", {
                "keystoreJson": keystore_json,
                "password": keystore_password,
                "chain": "ETHEREUM",
                "derivationPath": derivation_path,
                "input": {
                    "nonce": str(nonce),
                    "gasPrice": str(w3.eth.gas_price),
                    "gasLimit": "300000",
                    "to": NFT_CONTRACT,
                    "value": "0",
                    "data": data,
                    "chainId": "11155111",
                },
            })

            if not sign_result.get("success"):
                return {"success": False, "error": f"TokenCore 签名失败: {sign_result.get('error')}"}

            raw_tx = sign_result.get("signature") or sign_result.get("signedTx")
            if not raw_tx:
                return {"success": False, "error": "签名结果为空"}

            tx_hash = w3.eth.send_raw_transaction(raw_tx)
            return {"success": True, "tx_hash": tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash),
                    "token_id": token_id}
        except Exception as e:
            return {"success": False, "error": str(e)}


# ============================================================
#  Bitrefill 模块
# ============================================================
class BitrefillModule:
    """Bitrefill 礼品卡 API 封装"""

    @staticmethod
    def _headers() -> dict:
        return {
            "Authorization": f"Bearer {BITREFILL_API_KEY}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def create_invoice(product_id: str, value_usd: float, webhook_url: str = "") -> dict:
        """
        创建 Bitrefill 发票
        POST /invoices
        """
        payload = {
            "products": [{"product_id": product_id, "value": value_usd}],
            "payment_method": "balance",
            "auto_pay": True,
        }
        if webhook_url:
            payload["webhook_url"] = webhook_url

        try:
            resp = requests.post(
                f"{BITREFILL_BASE}/invoices",
                json=payload,
                headers=BitrefillModule._headers(),
                timeout=30,
            )
            data = resp.json()
            if resp.status_code in (200, 201):
                orders = []
                for inv_order in data.get("orders", []):
                    order_id = inv_order.get("order_id") or inv_order.get("id")
                    orders.append({
                        "order_id": order_id,
                        "status": inv_order.get("status", "unknown"),
                    })

                # 获取赎回信息（如果已完成）
                redemption_codes = []
                for o in orders:
                    if o["order_id"]:
                        rd = BitrefillModule.get_order(o["order_id"])
                        if rd.get("redemption_code"):
                            redemption_codes.append(rd["redemption_code"])

                return {
                    "success": True,
                    "invoice_id": data.get("id"),
                    "orders": orders,
                    "redemption_codes": redemption_codes,
                }
            return {"success": False, "error": data.get("message", str(data))}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_order(order_id: str) -> dict:
        """GET /orders/{id} — 获取订单详情和兑换码"""
        try:
            resp = requests.get(
                f"{BITREFILL_BASE}/orders/{order_id}",
                headers=BitrefillModule._headers(),
                timeout=30,
            )
            data = resp.json()
            if resp.status_code == 200:
                ri = data.get("redemption_info", {}) or {}
                return {
                    "order_id": order_id,
                    "status": data.get("status"),
                    "redemption_code": ri.get("code"),
                    "redemption_link": ri.get("link"),
                    "redemption_pin": ri.get("pin"),
                    "raw": data,
                }
            return {"order_id": order_id, "status": "error", "error": data.get("message")}
        except Exception as e:
            return {"order_id": order_id, "status": "error", "error": str(e)}

    @staticmethod
    def process_webhook(payload: dict) -> dict:
        """处理 Bitrefill webhook 回调"""
        invoice_id = payload.get("id", "unknown")
        status = payload.get("status", "unknown")
        orders = payload.get("orders", [])
        return {"invoice_id": invoice_id, "status": status, "orders": orders}


# ============================================================
#  AI 任务生成
# ============================================================
def generate_tasks(count: int = 3) -> list[dict]:
    """使用 OpenAI API 生成微任务"""
    if not openai_client:
        return []

    prompt = f"""你是一个Web3任务平台的任务设计师。请生成{count}个有趣的微任务。
每个任务包含：标题、描述、奖励类型(token/nft/giftcard)、奖励数量。
token: 1-50个平台积分
nft: 1个NFT
giftcard: 价值1-10美元

严格按JSON数组格式返回，不要markdown代码块：
[{{"title":"...","description":"...","reward_type":"token","reward_amount":10}},...]"""

    try:
        resp = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=1000,
        )
        text = resp.choices[0].message.content.strip()
        text = re.sub(r"^```(json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        tasks = json.loads(text)
        return tasks
    except Exception as e:
        print(f"[AI] 任务生成失败: {e}")
        return []


# ============================================================
#  路由
# ============================================================
@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


# ---- 认证 ----
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供 JSON 数据"}), 400

    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    if not username or not password:
        return jsonify({"error": "用户名和密码不能为空"}), 400
    if len(username) < 3 or len(username) > 30:
        return jsonify({"error": "用户名需 3-30 个字符"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少 6 个字符"}), 400

    db = get_db()
    exists = db.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if exists:
        return jsonify({"error": "用户名已存在"}), 409

    wallet_result = WalletModule.generate_wallet()
    if not wallet_result.get("success"):
        return jsonify({"error": f"TokenCore 钱包创建失败: {wallet_result.get('error')}"}), 500

    enc_ks = encrypt_key(wallet_result["keystore_json"])
    enc_pw = encrypt_key(wallet_result["keystore_password"])

    db.execute(
        "INSERT INTO users (username, password_hash, wallet_address, wallet_keystore, wallet_keystore_password) VALUES (?,?,?,?,?)",
        (username, generate_password_hash(password), wallet_result["address"], enc_ks, enc_pw),
    )
    db.commit()

    return jsonify({
        "success": True,
        "username": username,
        "wallet_address": wallet_result["address"],
        "message": "注册成功！钱包已通过 TokenCore @consenlabs/tcx-wasm 自动创建",
    })


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    if not data:
        return jsonify({"error": "请提供 JSON 数据"}), 400

    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "用户名或密码错误"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"success": True, "username": user["username"]})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/me", methods=["GET"])
def api_me():
    if "user_id" not in session:
        return jsonify({"logged_in": False})
    return jsonify({
        "logged_in": True,
        "user_id": session["user_id"],
        "username": session["username"],
    })


# ---- 任务 ----
@app.route("/api/tasks", methods=["GET"])
def api_tasks():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM tasks WHERE is_active=1 ORDER BY created_at DESC"
    ).fetchall()

    user_id = session.get("user_id")
    tasks = []
    for r in rows:
        task = dict(r)
        if user_id:
            ut = db.execute(
                "SELECT status FROM user_tasks WHERE user_id=? AND task_id=?",
                (user_id, r["id"]),
            ).fetchone()
            task["user_status"] = ut["status"] if ut else None
        else:
            task["user_status"] = None
        tasks.append(task)

    return jsonify({"tasks": tasks})


@app.route("/api/tasks/generate", methods=["POST"])
@login_required
def api_tasks_generate():
    data = request.get_json() or {}
    count = min(int(data.get("count", 3)), 10)

    new_tasks = generate_tasks(count)
    if not new_tasks:
        return jsonify({"error": "AI 任务生成失败，请检查 OPENAI_API_KEY"}), 500

    db = get_db()
    inserted = []
    for t in new_tasks:
        rt = t.get("reward_type", "token")
        if rt not in ("token", "nft", "giftcard"):
            rt = "token"
        ra = max(1, float(t.get("reward_amount", 5)))
        db.execute(
            "INSERT INTO tasks (title, description, reward_type, reward_amount) VALUES (?,?,?,?)",
            (t["title"], t["description"], rt, ra),
        )
        inserted.append({"title": t["title"], "reward_type": rt, "reward_amount": ra})
    db.commit()

    return jsonify({"success": True, "generated": len(inserted), "tasks": inserted})


@app.route("/api/tasks/<int:task_id>/complete", methods=["POST"])
@login_required
def api_complete_task(task_id):
    db = get_db()
    user_id = session["user_id"]

    task = db.execute("SELECT * FROM tasks WHERE id=? AND is_active=1", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    existing = db.execute(
        "SELECT * FROM user_tasks WHERE user_id=? AND task_id=?", (user_id, task_id)
    ).fetchone()

    if existing:
        if existing["status"] == "claimed":
            return jsonify({"error": "该奖励已领取"}), 400
        if existing["status"] == "completed":
            return jsonify({"message": "任务已完成，可以领取奖励", "status": "completed"})

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if existing:
        db.execute(
            "UPDATE user_tasks SET status='completed', completed_at=? WHERE id=?",
            (now, existing["id"]),
        )
    else:
        db.execute(
            "INSERT INTO user_tasks (user_id, task_id, status, completed_at) VALUES (?,?,?,?)",
            (user_id, task_id, "completed", now),
        )
    db.commit()

    return jsonify({"success": True, "message": "任务已完成！请领取奖励", "status": "completed"})


# ---- 奖励领取 ----
@app.route("/api/claim/<int:task_id>", methods=["POST"])
@login_required
def api_claim(task_id):
    db = get_db()
    user_id = session["user_id"]

    task = db.execute("SELECT * FROM tasks WHERE id=? AND is_active=1", (task_id,)).fetchone()
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    # 防重复领取（优先检查）
    existing_reward = db.execute(
        "SELECT id FROM rewards WHERE user_id=? AND task_id=?",
        (user_id, task_id),
    ).fetchone()
    if existing_reward:
        return jsonify({"error": "该奖励已发放"}), 400

    ut = db.execute(
        "SELECT * FROM user_tasks WHERE user_id=? AND task_id=? AND status='completed'",
        (user_id, task_id),
    ).fetchone()

    if not ut:
        return jsonify({"error": "请先完成任务再领取奖励"}), 400

    user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    reward_type = task["reward_type"]
    reward_amount = task["reward_amount"]

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Token 奖励
    if reward_type == "token":
        db.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (reward_amount, user_id),
        )
        db.execute(
            "INSERT INTO rewards (user_id, task_id, reward_type, amount, status, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, task_id, "token", reward_amount, "completed", now),
        )
        db.execute(
            "INSERT INTO transactions (user_id, type, amount, currency, description, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, "earn", reward_amount, "TOKEN", f"完成任务: {task['title']}", now),
        )
        db.execute(
            "UPDATE user_tasks SET status='claimed', claimed_at=? WHERE id=?",
            (now, ut["id"]),
        )
        db.commit()
        return jsonify({
            "success": True,
            "reward_type": "token",
            "amount": reward_amount,
            "new_balance": round(user["balance"] + reward_amount, 2),
        })

    # NFT 奖励
    elif reward_type == "nft":
        ks = decrypt_key(user["wallet_keystore"])
        ks_pw = decrypt_key(user["wallet_keystore_password"])
        token_uri = f"https://metadata.reward-platform.local/nft/{user_id}/{task_id}"
        result = WalletModule.mint_nft(ks, ks_pw, user["wallet_address"], token_uri)

        status = "completed" if result["success"] else "failed"
        db.execute(
            "INSERT INTO rewards (user_id, task_id, reward_type, amount, status, tx_hash, created_at) VALUES (?,?,?,?,?,?,?)",
            (user_id, task_id, "nft", 1, status, result.get("tx_hash"), now),
        )
        db.execute(
            "INSERT INTO transactions (user_id, type, amount, currency, tx_hash, description, created_at) VALUES (?,?,?,?,?,?,?)",
            (user_id, "earn", 1, "NFT", result.get("tx_hash"), f"NFT奖励: {task['title']}", now),
        )
        if status == "completed":
            db.execute(
                "UPDATE user_tasks SET status='claimed', claimed_at=? WHERE id=?",
                (now, ut["id"]),
            )
        db.commit()
        return jsonify({"success": result["success"], "reward_type": "nft", "tx_hash": result.get("tx_hash"), "error": result.get("error")})

    # 礼品卡奖励（Bitrefill）
    elif reward_type == "giftcard":
        product_id = task["product_id"]
        if not product_id or not BITREFILL_API_KEY:
            db.execute(
                "INSERT INTO rewards (user_id, task_id, reward_type, amount, status, created_at) VALUES (?,?,?,?,?,?)",
                (user_id, task_id, "giftcard", reward_amount, "failed", now),
            )
            db.commit()
            return jsonify({
                "success": False,
                "error": "礼品卡功能需要 BITREFILL_API_KEY 和有效的 product_id",
            })

        webhook_url = request.host_url.rstrip("/") + "/api/webhook/bitrefill"
        result = BitrefillModule.create_invoice(product_id, reward_amount, webhook_url)

        rc = None
        if result.get("redemption_codes"):
            rc = result["redemption_codes"][0]

        status = "completed" if result["success"] else "failed"
        order_id = ""
        if result.get("orders"):
            order_id = result["orders"][0].get("order_id", "")

        db.execute(
            "INSERT INTO rewards (user_id, task_id, reward_type, amount, status, bitrefill_order_id, redemption_code, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, task_id, "giftcard", reward_amount, status, str(order_id), rc, now),
        )
        db.execute(
            "INSERT INTO transactions (user_id, type, amount, currency, description, created_at) VALUES (?,?,?,?,?,?)",
            (user_id, "earn", reward_amount, "USD", f"礼品卡: {task['title']}", now),
        )
        if status == "completed":
            db.execute(
                "UPDATE user_tasks SET status='claimed', claimed_at=? WHERE id=?",
                (now, ut["id"]),
            )
        db.commit()
        return jsonify({
            "success": result["success"],
            "reward_type": "giftcard",
            "amount": reward_amount,
            "order_id": order_id,
            "redemption_code": rc,
            "error": result.get("error"),
        })

    return jsonify({"error": "未知奖励类型"}), 400


# ---- 钱包 ----
@app.route("/api/wallet", methods=["GET"])
@login_required
def api_wallet():
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    eth_balance = WalletModule.get_eth_balance(user["wallet_address"])

    return jsonify({
        "wallet_address": user["wallet_address"],
        "eth_balance": eth_balance,
        "platform_balance": round(user["balance"], 2),
    })


# ---- 交易记录 ----
@app.route("/api/transactions", methods=["GET"])
@login_required
def api_transactions():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM transactions WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (session["user_id"],),
    ).fetchall()
    return jsonify({"transactions": [dict(r) for r in rows]})


# ---- 奖励记录 ----
@app.route("/api/rewards", methods=["GET"])
@login_required
def api_rewards():
    db = get_db()
    rows = db.execute(
        """SELECT r.*, t.title as task_title
           FROM rewards r JOIN tasks t ON r.task_id = t.id
           WHERE r.user_id=?
           ORDER BY r.created_at DESC""",
        (session["user_id"],),
    ).fetchall()
    return jsonify({"rewards": [dict(r) for r in rows]})


# ---- Bitrefill Webhook ----
@app.route("/api/webhook/bitrefill", methods=["POST"])
def api_bitrefill_webhook():
    """接收 Bitrefill 支付回调"""
    payload = request.get_json()
    if not payload:
        return jsonify({"error": "no payload"}), 400

    result = BitrefillModule.process_webhook(payload)
    print(f"[Webhook] Bitrefill callback received: invoice={result['invoice_id']} status={result['status']}")

    # 更新对应 reward 记录
    db = get_db()
    for order in result.get("orders", []):
        oid = order.get("order_id") or order.get("id")
        if oid:
            order_info = BitrefillModule.get_order(str(oid))
            new_status = "completed" if order_info.get("redemption_code") else "processing"
            db.execute(
                "UPDATE rewards SET status=?, redemption_code=? WHERE bitrefill_order_id=?",
                (new_status, order_info.get("redemption_code"), str(oid)),
            )
    db.commit()

    return jsonify({"received": True})


# ============================================================
#  入口
# ============================================================
# 初始化数据库（模块导入时执行，兼容 gunicorn）
init_db()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("=" * 55)
    print("  TokenCore + Claude AI + Bitrefill 奖励平台")
    print("  TokenCore Bridge: " + TOKENCORE_BRIDGE)
    print("  Wallet 核心: @consenlabs/tcx-wasm v0.9.1")
    print(f"  运行地址: http://0.0.0.0:{port}")
    print("=" * 55)
    app.run(debug=False, host="0.0.0.0", port=port)
