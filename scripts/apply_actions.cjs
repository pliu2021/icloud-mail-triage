'use strict';
/*
 * apply_actions.cjs — 按 JSON 清单精确移动邮件（可恢复，非永久删除）。
 * 设计要点（血泪教训）:
 *   - 幂等: 每个分组重新 FETCH 1:* 取真实 UID，只动"清单内且仍存在"的邮件；已不在源的自动跳过。
 *   - iCloud 无原生 MOVE，用 messageMove（COPY→源侧 UID EXPUNGE，需 UIDPLUS）。
 *   - 分批 ≤200，每批后校验源残留: 若 >0 立即停机，绝不继续。
 *   - 每批写入 actions-log.jsonl，便于事后核对/回滚。
 *   - 只做文件夹间移动，绝不 EXPUNGE 回收站本身 → 一切可恢复。
 *
 * 用法:
 *   node apply_actions.cjs --actions=actions.json [--dry-run] [--limit=N] [--batch=200] [--log=actions-log.jsonl]
 * 凭据: ICLOUD_CRED 环境变量（默认 ./cred.json） 依赖: npm install imapflow
 */
const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

const req = createRequire(path.join(process.cwd(), 'node_modules/imapflow/package.json'));
const { ImapFlow } = req('imapflow');

const A = process.argv.slice(2);
const has = k => A.includes(k);
const getArg = (k, d) => { const x = A.find(a => a.startsWith(k + '=')); return x ? x.slice(k.length + 1) : d; };
const DRY = has('--dry-run');
const FILE = getArg('--actions', './actions.json');
const LIMIT = (() => { const x = A.find(a => a.startsWith('--limit=')); return x ? parseInt(x.split('=')[1], 10) : 0; })();
const BATCH = parseInt(getArg('--batch', '200'), 10);
const LOG = getArg('--log', 'actions-log.jsonl');
const CRED_PATH = process.env.ICLOUD_CRED || './cred.json';
const cred = JSON.parse(fs.readFileSync(CRED_PATH, 'utf8'));
const log = (...a) => process.stderr.write('[apply] ' + a.join(' ') + '\n');

const plan = JSON.parse(fs.readFileSync(FILE, 'utf8'));

(async () => {
  const groups = {};
  for (const a of plan.actions) {
    const k = a.folder + '|' + a.dest;
    (groups[k] = groups[k] || []).push(a.uid);
  }
  const cl = new ImapFlow({ host: cred.host, port: cred.port || 993, secure: true, auth: { user: cred.user, pass: cred.pass }, logger: false });
  cl.on('error', e => log('client err:', e.message));
  await cl.connect();
  log('plan:', FILE, '| 动作', plan.actions.length, '| DRY:', DRY, '| LIMIT:', LIMIT || 'all', '| BATCH:', BATCH);

  for (const [k, uids] of Object.entries(groups)) {
    const [src, dest] = k.split('|');
    await cl.mailboxOpen(src, { readOnly: true });
    const real = new Set();
    for await (const m of cl.fetch('1:*', { uid: true }, { uid: true })) real.add(m.uid);
    const valid = uids.filter(u => real.has(u));
    log(`[${src} -> ${dest}] 计划 ${uids.length} | 仍存在 ${valid.length} | 已不在源 ${uids.length - valid.length}`);
    if (DRY) continue;
    const use = LIMIT ? valid.slice(0, LIMIT) : valid;
    for (let i = 0; i < use.length; i += BATCH) {
      const b = use.slice(i, i + BATCH);
      await cl.mailboxOpen(src);
      try {
        await cl.messageMove(b.join(','), dest, { uid: true });
      } catch (e) {
        log('批次失败:', e.responseText || e.message);
        process.exit(2);
      }
      let left = 0;
      try { for await (const m of cl.fetch(b.join(','), { uid: true }, { uid: true })) left++; } catch (e) {}
      log(`  批次 ${Math.floor(i / BATCH) + 1} | ${b.length} 封 | 源残留 ${left}`);
      fs.appendFileSync(LOG, JSON.stringify({ at: new Date().toISOString(), src, dest, count: b.length, left }) + '\n');
      if (left > 0) { log('源仍有残留，停止执行以防误伤'); process.exit(3); }
    }
  }
  log('=== DONE ===');
  await cl.logout();
  process.exit(0);
})().catch(e => { log('FATAL ' + (e.responseText || e.message || String(e))); process.exit(1); });
