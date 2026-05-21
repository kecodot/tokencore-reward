/**
 * TokenCore Wallet Bridge Service
 * ================================
 * Wraps @consenlabs/tcx-wasm (TokenCore WebAssembly) behind REST endpoints.
 * 所有 Token Core 核心能力（钱包创建、账户推导、交易签名）通过此服务暴露。
 * Flask 后端通过 HTTP 调用此服务。
 */
import express from 'express';
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// 直接引用 tcx-wasm ES 模块文件（npm 包的 package.json 缺少 "exports" 字段，
// 无法通过包名 import，改用文件路径直接加载）
const WASM_DIR = join(__dirname, 'node_modules', '@consenlabs', 'tcx-wasm');
const tcxModule = await import(join(WASM_DIR, 'tcx_wasm.js'));
const {
    initSync,
    create_keystore,
    derive_accounts,
    sign_tx,
    export_mnemonic,
    cache_keystore,
    clear_cached_keystore,
} = tcxModule;

// 加载并初始化 WASM 二进制
const wasmBuffer = readFileSync(join(WASM_DIR, 'tcx_wasm_bg.wasm'));
initSync(wasmBuffer);
console.log('[TokenCore] WASM module initialized');

const app = express();
app.use(express.json());

// ======================== 路由 ========================

// 健康检查
app.get('/api/wallet/health', (_req, res) => {
    res.json({ status: 'ok', module: 'TokenCore @consenlabs/tcx-wasm v0.9.1' });
});

// 创建钱包（Token Core 核心能力：keystore 生成 + 账户推导）
app.post('/api/wallet/create', (req, res) => {
    try {
        const { password, mnemonic, entropy, network } = req.body || {};
        if (!password) return res.status(400).json({ error: 'password is required' });

        const params = { password, network: network || 'TESTNET' };
        if (mnemonic) params.mnemonic = mnemonic;
        if (entropy) params.entropy = entropy;

        // TokenCore: create_keystore
        const keystoreJson = create_keystore(JSON.stringify(params));
        const parsed = JSON.parse(keystoreJson);

        // TokenCore: derive_accounts (ETH)
        const accountResult = JSON.parse(derive_accounts(JSON.stringify({
            keystoreJson,
            key: password,
            derivations: [{
                chain: 'ETHEREUM',
                derivationPath: "m/44'/60'/0'/0/0",
                chainId: '11155111',
                network: params.network,
            }],
        })));
        const account = accountResult[0] || {};

        // TokenCore: export_mnemonic
        const mnemonicData = mnemonic
            ? { mnemonic }
            : JSON.parse(export_mnemonic(JSON.stringify({ keystoreJson, key: password })));

        res.json({
            success: true,
            keystore: {
                id: parsed?.id,
                version: parsed?.version,
                json: keystoreJson,
            },
            account: {
                address: account?.address || '',
                publicKey: account?.publicKey || '',
                chain: account?.chain || 'ETHEREUM',
                derivationPath: "m/44'/60'/0'/0/0",
            },
            mnemonic: mnemonicData?.mnemonic || '',
        });
    } catch (e) {
        console.error('[TokenCore] create error:', e);
        res.status(500).json({ success: false, error: e.message });
    }
});

// 推导账户
app.post('/api/wallet/derive', (req, res) => {
    try {
        const { keystoreJson, password, derivations } = req.body || {};
        if (!keystoreJson) return res.status(400).json({ error: 'keystoreJson is required' });
        if (!password) return res.status(400).json({ error: 'password is required' });

        // TokenCore: derive_accounts
        const result = JSON.parse(derive_accounts(JSON.stringify({
            keystoreJson,
            key: password,
            derivations: derivations || [{
                chain: 'ETHEREUM',
                derivationPath: "m/44'/60'/0'/0/0",
                chainId: '11155111',
                network: 'TESTNET',
            }],
        })));

        res.json({ success: true, accounts: result });
    } catch (e) {
        console.error('[TokenCore] derive error:', e);
        res.status(500).json({ success: false, error: e.message });
    }
});

// 签名交易（Token Core 核心能力：链上交易签名）
app.post('/api/wallet/sign', (req, res) => {
    try {
        const { keystoreJson, password, chain, derivationPath, input } = req.body || {};
        if (!keystoreJson) return res.status(400).json({ error: 'keystoreJson is required' });
        if (!password) return res.status(400).json({ error: 'password is required' });
        if (!chain) return res.status(400).json({ error: 'chain is required' });
        if (!input) return res.status(400).json({ error: 'input is required' });

        // TokenCore: sign_tx
        const result = JSON.parse(sign_tx(JSON.stringify({
            keystoreJson,
            key: password,
            chain,
            derivationPath: derivationPath || "m/44'/60'/0'/0/0",
            input,
        })));

        res.json({ success: true, ...result });
    } catch (e) {
        console.error('[TokenCore] sign error:', e);
        res.status(500).json({ success: false, error: e.message });
    }
});

// 导出助记词
app.post('/api/wallet/export-mnemonic', (req, res) => {
    try {
        const { keystoreJson, password } = req.body || {};
        if (!keystoreJson) return res.status(400).json({ error: 'keystoreJson is required' });
        if (!password) return res.status(400).json({ error: 'password is required' });

        // TokenCore: export_mnemonic
        const result = JSON.parse(export_mnemonic(JSON.stringify({
            keystoreJson,
            key: password,
        })));

        res.json({ success: true, mnemonic: result.mnemonic });
    } catch (e) {
        console.error('[TokenCore] export error:', e);
        res.status(500).json({ success: false, error: e.message });
    }
});

// 缓存管理
app.post('/api/wallet/cache', (req, res) => {
    try {
        const { keystoreJson } = req.body || {};
        if (!keystoreJson) {
            clear_cached_keystore();
            res.json({ success: true, cached: false });
        } else {
            cache_keystore(keystoreJson);
            res.json({ success: true, cached: true });
        }
    } catch (e) {
        res.status(500).json({ success: false, error: e.message });
    }
});

const PORT = process.env.WALLET_BRIDGE_PORT || 5001;
app.listen(PORT, () => {
    console.log(`[TokenCore] Wallet bridge listening on http://localhost:${PORT}`);
});
