// TokenCore 奖励平台 — 前端交互逻辑
// 钱包相关操作由 @consenlabs/tcx-wasm (TokenCore) 提供核心能力

// ---- TokenCore WASM 客户端初始化 ----
let tcxWasmReady = false;
const TOKENCORE_MODULE = {};

async function initTokenCoreWasm() {
    try {
        // 动态加载 @consenlabs/tcx-wasm (浏览器端 ES Module)
        const tcx = await import('https://cdn.jsdelivr.net/npm/@consenlabs/tcx-wasm@0.9.1/tcx_wasm.js');
        await tcx.default();  // 初始化 WASM
        Object.assign(TOKENCORE_MODULE, {
            create_keystore: tcx.create_keystore,
            derive_accounts: tcx.derive_accounts,
            sign_tx: tcx.sign_tx,
            export_mnemonic: tcx.export_mnemonic,
            cache_keystore: tcx.cache_keystore,
            clear_cached_keystore: tcx.clear_cached_keystore,
        });
        tcxWasmReady = true;
        console.log('[TokenCore] Browser WASM ready');
    } catch (e) {
        console.warn('[TokenCore] Browser WASM load failed (will use bridge API):', e.message);
    }
}
initTokenCoreWasm();

const API = {
    async req(method, url, body) {
        showLoading(true);
        try {
            const opts = {
                method,
                headers: { 'Content-Type': 'application/json' },
            };
            if (body) opts.body = JSON.stringify(body);
            const resp = await fetch(url, opts);
            const data = await resp.json();
            return { status: resp.status, data };
        } catch (e) {
            return { status: 0, data: { error: '网络错误: ' + e.message } };
        } finally {
            showLoading(false);
        }
    },
    get(url) { return this.req('GET', url); },
    post(url, body) { return this.req('POST', url, body || {}); },
};

function showLoading(show) {
    document.getElementById('loading').style.display = show ? 'block' : 'none';
}

function showToast(msg, isError) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.style.display = 'block';
    t.style.background = isError ? '#fbe9e7' : '#e8f5e9';
    t.style.color = isError ? '#c62828' : '#2e7d32';
    t.style.padding = '.75rem 1rem';
    t.style.borderRadius = '8px';
    setTimeout(() => { t.style.display = 'none'; }, 4000);
}

// ---- Auth ----
async function handleAuth(e) {
    e.preventDefault();
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value.trim();
    const { status, data } = await API.post('/api/login', { username, password });
    if (status === 200 && data.success) {
        showToast('登录成功');
        updateUserBar(data.username);
        switchTab('tasks');
    } else {
        showToast(data.error || '登录失败', true);
    }
}

async function doRegister() {
    const username = document.getElementById('auth-username').value.trim();
    const password = document.getElementById('auth-password').value.trim();
    if (!username || !password) {
        showToast('请填写用户名和密码', true);
        return;
    }
    const { status, data } = await API.post('/api/register', { username, password });
    if (status === 200 && data.success) {
        const div = document.getElementById('register-result');
        div.style.display = 'block';
        let mnemonicHtml = '';
        if (data.mnemonic) {
            mnemonicHtml = `<div style="margin-top:.5rem;padding:.5rem;background:#fff3e0;border-radius:8px">
                <strong>助记词（请立即抄写保存！）</strong>
                <p class="wallet-addr" style="margin:.25rem 0">${escHtml(data.mnemonic)}</p>
                <small style="color:#e65100">助记词仅显示一次，丢失后无法恢复钱包</small>
            </div>`;
        }
        div.innerHTML = `<p>注册成功！</p>
            <p>钱包地址: <code>${data.wallet_address}</code></p>
            ${mnemonicHtml}
            <p class="badge badge-success">TokenCore @consenlabs/tcx-wasm 已创建 HD 钱包</p>
            <p style="font-size:.85em; color:var(--pico-muted-color)">Keystore 已加密存储，使用 PBKDF2 密钥派生</p>`;
        document.getElementById('auth-password').value = '';
        showToast('注册成功！请登录');
    } else {
        showToast(data.error || '注册失败', true);
    }
}

async function logout() {
    await API.post('/api/logout');
    updateUserBar(null);
    switchTab('account');
    showToast('已登出');
}

async function checkLogin() {
    const { data } = await API.get('/api/me');
    if (data.logged_in) {
        updateUserBar(data.username);
    }
}

function updateUserBar(username) {
    document.getElementById('user-info').style.display = username ? 'inline' : 'none';
    document.getElementById('guest-info').style.display = username ? 'none' : 'inline';
    if (username) document.getElementById('display-username').textContent = username;
}

// ---- Tabs ----
function switchTab(name) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + name).classList.add('active');

    if (name === 'tasks') loadTasks();
    if (name === 'wallet') loadWallet();
    if (name === 'rewards') loadRewards();
}

// ---- Tasks ----
async function loadTasks() {
    const { data } = await API.get('/api/tasks');
    const container = document.getElementById('tasks-list');
    if (!data.tasks || data.tasks.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无任务，点击"AI 生成任务"创建新任务</div>';
        return;
    }
    container.innerHTML = data.tasks.map(t => {
        const badge = `<span class="reward-tag ${t.reward_type}">${rewardLabel(t.reward_type)}</span>
                       <span class="reward-tag amount">${rewardAmount(t)}</span>`;
        let actionBtn = '';
        if (t.user_status === 'claimed') {
            actionBtn = '<span class="badge badge-success">已领取</span>';
        } else if (t.user_status === 'completed') {
            actionBtn = `<button class="small" onclick="claimReward(${t.id})">领取奖励</button>`;
        } else if (t.user_status === 'pending') {
            actionBtn = `<button class="small secondary" onclick="completeTask(${t.id})">标记完成</button>`;
        } else {
            actionBtn = `<button class="small outline" onclick="completeTask(${t.id})">接受任务</button>`;
        }
        return `<div class="card">
            <strong>${escHtml(t.title)}</strong>
            <p style="margin:.25rem 0; color: var(--pico-muted-color);">${escHtml(t.description)}</p>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:.5rem;">
                <span>${badge}</span>
                ${actionBtn}
            </div>
        </div>`;
    }).join('');
}

function rewardLabel(type) {
    return { token: 'Token', nft: 'NFT', giftcard: '礼品卡' }[type] || type;
}

function rewardAmount(t) {
    if (t.reward_type === 'nft') return 'x' + t.reward_amount;
    if (t.reward_type === 'giftcard') return '$' + t.reward_amount;
    return '+' + t.reward_amount + ' TOKEN';
}

async function completeTask(taskId) {
    const { status, data } = await API.post('/api/tasks/' + taskId + '/complete');
    if (status === 200 && data.success) {
        showToast('任务已完成！请领取奖励');
        loadTasks();
    } else {
        showToast(data.error || '操作失败', true);
    }
}

async function claimReward(taskId) {
    const { status, data } = await API.post('/api/claim/' + taskId);
    if (status === 200 && data.success) {
        let msg = `奖励已发放: ${data.reward_type}`;
        if (data.redemption_code) msg += ` | 兑换码: ${data.redemption_code}`;
        if (data.tx_hash) msg += ` | 交易: ${data.tx_hash.slice(0, 12)}...`;
        showToast(msg);
        loadTasks();
    } else {
        showToast(data.error || '领取失败', true);
    }
}

async function generateTasks() {
    const count = prompt('生成多少个任务？(1-10)', '3');
    if (!count) return;
    const { status, data } = await API.post('/api/tasks/generate', { count: parseInt(count) });
    if (status === 200 && data.success) {
        showToast(`AI 生成了 ${data.generated} 个新任务`);
        loadTasks();
    } else {
        showToast(data.error || '生成失败，请检查 API Key', true);
    }
}

// ---- Wallet ----
async function loadWallet() {
    const { data } = await API.get('/api/wallet');
    document.getElementById('wallet-addr').textContent = data.wallet_address || '请先登录';
    document.getElementById('eth-balance').textContent = data.eth_balance || '0';
    document.getElementById('platform-balance').textContent = data.platform_balance || '0';

    // TokenCore 状态
    const tcStatus = document.getElementById('tokencore-status');
    if (tcStatus) {
        const bridgeOk = data.wallet_address ? true : false;
        tcStatus.innerHTML = tcxWasmReady
            ? '<span class="badge badge-success">TokenCore WASM (浏览器) ✓</span>'
            : (bridgeOk
                ? '<span class="badge badge-info">TokenCore Bridge (服务端) ✓</span>'
                : '<span class="badge badge-warning">TokenCore 连接中...</span>');
    }

    const { data: txData } = await API.get('/api/transactions');
    const container = document.getElementById('tx-list');
    if (!txData.transactions || txData.transactions.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无交易记录</div>';
        return;
    }
    container.innerHTML = txData.transactions.map(tx => {
        const cls = tx.type === 'earn' ? 'badge-success' : 'badge-warning';
        return `<div class="card" style="padding:.5rem 1rem;">
            <span class="badge ${cls}">${tx.type === 'earn' ? '+' : '-'}</span>
            ${tx.amount} ${tx.currency}
            <small style="color:var(--pico-muted-color)">${tx.description || ''}</small>
            <small style="float:right;color:var(--pico-muted-color)">${(tx.created_at || '').slice(0, 16)}</small>
        </div>`;
    }).join('');
}

// ---- Mnemonic Export ----
async function exportMnemonic() {
    const password = document.getElementById('mnemonic-password').value.trim();
    if (!password) {
        showToast('请输入 Keystore 密码', true);
        return;
    }
    const { status, data } = await API.post('/api/wallet/mnemonic', { password });
    const div = document.getElementById('mnemonic-result');
    if (status === 200 && data.success) {
        document.getElementById('mnemonic-words').textContent = data.mnemonic;
        div.style.display = 'block';
        showToast('助记词已导出，请安全保管');
    } else {
        div.style.display = 'none';
        showToast(data.error || '导出失败', true);
    }
}

// ---- Rewards ----
async function loadRewards() {
    const { data } = await API.get('/api/rewards');
    const container = document.getElementById('rewards-list');
    if (!data.rewards || data.rewards.length === 0) {
        container.innerHTML = '<div class="empty-state">暂无奖励记录，去完成任务吧！</div>';
        return;
    }
    container.innerHTML = data.rewards.map(r => {
        const statusBadge = {
            completed: '<span class="badge badge-success">已完成</span>',
            pending: '<span class="badge badge-warning">处理中</span>',
            processing: '<span class="badge badge-info">处理中</span>',
            failed: '<span class="badge badge-error">失败</span>',
        }[r.status] || r.status;
        let extra = '';
        if (r.redemption_code) extra += `<br>兑换码: <code>${r.redemption_code}</code>`;
        if (r.tx_hash) extra += `<br>交易哈希: <code>${r.tx_hash.slice(0, 20)}...</code>`;
        return `<div class="card" style="padding:.5rem 1rem;">
            <strong>${escHtml(r.task_title)}</strong> ${statusBadge}
            <span class="reward-tag ${r.reward_type}">${rewardLabel(r.reward_type)}</span>
            <span>${rewardAmount(r)}</span>
            ${extra}
            <small style="float:right;color:var(--pico-muted-color)">${(r.created_at || '').slice(0, 16)}</small>
        </div>`;
    }).join('');
}

// ---- Helpers ----
function escHtml(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}

// ---- Init ----
checkLogin();
