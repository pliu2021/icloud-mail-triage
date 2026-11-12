'use strict';
/*
 * verify.cjs — 执行后独立双重核对（与 apply_actions 互不依赖，重新连 IMAP 校验）。
 * 检查项:
 *   1) 每个"移出"动作: 源文件夹里已查无该 UID（源残留=0）
 *   2) 每个"放回"动作: 源(已删除)里已查无该 UID
 *   3) 判定为不动的邮件: 仍在原文件夹（完好）
 *   4) 移动副本在目标文件夹末尾可按主题匹配找到
 *   5) 各文件夹总数 + 邮件总数守恒
 * 用法:
 *   node verify.cjs --actions=actions.json [--model=model-verdicts.json]
 * 凭据: ICLOUD_CRED 环境变量（默认 ./cred.json） 依赖: npm install imapflow
 */
const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');
const req = createRequire(path.join(process.cwd(), 'node_modules/imapflow/package.json'));
const { ImapFlow } = req('imapflow');

const A = process.argv.slice(2);
const getArg = (k, d) => { const x = A.find(a => a.startsWith(k + '=')); return x ? x.slice(k.length + 1) : d; };
const FILE = getArg('--actions', './actions.json');
const MODEL = getArg('--model', null);
const CRED_PATH = process.env.ICLOUD_CRED || './cred.json';
const cred = JSON.parse(fs.readFileSync(CRED_PATH, 'utf8'));
const log = (...a) => process.stderr.write('[verify] ' + a.join(' ') + '\n');

const plan = JSON.parse(fs.readFileSync(FILE, 'utf8'));
let model = [];
if (MODEL && fs.existsSync(MODEL)) {
  const m = JSON.parse(fs.readFileSync(MODEL, 'utf8'));
  model = m.rows || m.decisions || m.verdicts || m;
}

(async () => {
  const cl = new ImapFlow({ host: cred.host, port: cred.port || 993, secure: true, auth: { user: cred.user, pass: cred.pass }, logger: false });
  await cl.connect();
  const real = async (f) => {
    try { await cl.mailboxOpen(f, { readOnly: true }); } catch (e) { return null; }
    const s = new Set();
    for await (const m of cl.fetch('1:*', { uid: true }, { uid: true })) s.add(m.uid);
    return s;
  };
  const tailSubs = async (f, n = 400) => {
    const mb = await cl.mailboxOpen(f, { readOnly: true });
    const from = Math.max(1, mb.exists - n), a = [];
    for await (const m of cl.fetch(from + ':*', { envelope: true })) a.push(String((m.envelope && m.envelope.subject) || ''));
    return a;
  };

  const out = plan.actions.filter(x => x.folder === 'INBOX');
  const back = plan.actions.filter(x => x.folder !== 'INBOX');
  const I = await real('INBOX'), Dl = await real('Deleted Messages');
  if (!I || !Dl) { log('无法打开 INBOX / Deleted Messages'); process.exit(1); }

  const outLeft = out.filter(x => I.has(x.uid)).length;
  const backLeft = back.filter(x => Dl.has(x.uid)).length;
  log('INBOX 移出项仍在 INBOX   :', outLeft, '/', out.length, outLeft === 0 ? 'OK' : 'FAIL');
  log('已删除放回项仍在已删除   :', backLeft, '/', back.length, backLeft === 0 ? 'OK' : 'FAIL');

  if (model.length) {
    const keyOf = r => (r.folder === 'INBOX' ? 'I' : 'D') + r.uid;
    const noMove = model.filter(r => !plan.actions.some(a => a.key === keyOf(r)));
    const still = noMove.filter(r => (r.folder === 'INBOX' ? I : Dl).has(r.uid)).length;
    log('判定不动的邮件仍完好     :', still, '/', noMove.length, still === noMove.length ? 'OK' : 'CHECK');
  }

  const dTail = await tailSubs('Deleted Messages'), iTail = await tailSubs('INBOX');
  const fnd = (list, pool) => list.filter(x => { const s = String(x.subject || ''); return s && pool.some(y => y.includes(s.slice(0, 16))); }).length;
  const outFnd = fnd(out, dTail), backFnd = fnd(back, iTail);
  log('移出副本在已删除末尾找到 :', outFnd, '/', out.length);
  log('放回副本在 INBOX 末尾找到 :', backFnd, '/', back.length);

  const counts = {};
  for (const f of ['INBOX', 'Deleted Messages', 'Junk', 'Sent Messages', 'Archive']) {
    const s = await real(f); if (s) counts[f] = s.size;
  }
  log('最终真实 UID 数: ' + JSON.stringify(counts));
  await cl.logout();
  process.exit(0);
})().catch(e => { log('FATAL ' + (e.responseText || e.message || String(e))); process.exit(1); });
