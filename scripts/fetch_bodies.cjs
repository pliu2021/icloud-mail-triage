'use strict';
/*
 * fetch_bodies.cjs — 批量拉取指定文件夹邮件正文（只读）。
 * 只取第一个文本 part + BODYSTRUCTURE，在 Node 端完成 QP/base64/charset 解码与 HTML 去标签，
 * 输出纯文本 JSONL，每行 {uid, text, part_type}。
 * 用于「模型审阅」阶段大批量取正文；单次抽查可用 MCP get_message 代替。
 *
 * 用法:
 *   node fetch_bodies.cjs --folder=INBOX --uids=all --out=text.jsonl [--workers=3] [--batch=100]
 *   node fetch_bodies.cjs --folder=Deleted Messages --uids=file:uids.json --out=del-text.jsonl
 * uids=all   → 自动 FETCH 1:* 取真实 UID 列表（不要用 SEARCH，会返回已移走邮件的陈旧 UID）
 * 凭据: ICLOUD_CRED 环境变量（默认 ./cred.json） 依赖: npm install imapflow iconv-lite
 */
const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

const req = createRequire(path.join(process.cwd(), 'node_modules/imapflow/package.json'));
const { ImapFlow } = req('imapflow');
let iconv = null;
try { iconv = require(path.join(process.cwd(), 'node_modules/iconv-lite')); } catch (e) {}

const A = process.argv.slice(2);
const getArg = (k, d) => { const x = A.find(a => a.startsWith(k + '=')); return x ? x.slice(k.length + 1) : d; };
const FOLDER = getArg('--folder', 'INBOX');
const OUT = getArg('--out', 'text.jsonl');
const WORKERS = parseInt(getArg('--workers', '3'), 10);
const BATCH = parseInt(getArg('--batch', '100'), 10);
const UIDARG = getArg('--uids', 'all');
const CRED_PATH = process.env.ICLOUD_CRED || './cred.json';
const cred = JSON.parse(fs.readFileSync(CRED_PATH, 'utf8'));
const log = (...a) => process.stderr.write('[text] ' + a.join(' ') + '\n');
const conn = () => new ImapFlow({ host: cred.host, port: cred.port || 993, secure: true, auth: { user: cred.user, pass: cred.pass }, logger: false });

function qpDecode(buf) {
  const out = [];
  for (let i = 0; i < buf.length; i++) {
    if (buf[i] === 0x3D && i + 2 < buf.length) {
      const h = buf.slice(i + 1, i + 3).toString('ascii');
      if (/^[0-9A-Fa-f]{2}$/.test(h)) { out.push(parseInt(h, 16)); i += 2; continue; }
      if (buf[i + 1] === 0x0D && buf[i + 2] === 0x0A) { i += 2; continue; }
      if (buf[i + 1] === 0x0A) { i += 1; continue; }
    }
    out.push(buf[i]);
  }
  return Buffer.from(out);
}
function autoDecode(buf) {
  const s = buf.toString('latin1');
  const head = s.slice(0, 6000);
  if (/=[0-9A-Fa-f]{2}/.test(head) || /=\r?\n/.test(head)) return qpDecode(buf);
  const compact = s.replace(/\s/g, '');
  if (compact.length > 80 && /^[A-Za-z0-9+/=]+$/.test(compact) && compact.length % 4 === 0
      && !/\b(the|and|vous|bonjour|de|la|le|this|your|http|hello)\b/i.test(head)) {
    try { return Buffer.from(compact, 'base64'); } catch (e) {}
  }
  return buf;
}
function html2text(s) {
  return String(s || '')
    .replace(/<(script|style|head)[\s\S]*?<\/\1>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&')
    .replace(/&[a-z#0-9]+;/gi, ' ').replace(/\s+/g, ' ').trim();
}
function findPart(bs, id) {
  if (!bs) return null;
  if (bs.childNodes && bs.childNodes.length) {
    for (const c of bs.childNodes) { const r = findPart(c, id); if (r) return r; }
    return null;
  }
  if (bs.part === id || (!bs.part && id === '1')) return bs;
  return null;
}
function decodePart(buf, info) {
  const enc = String((info && info.encoding) || '8bit').toLowerCase();
  let b = buf;
  if (enc === 'quoted-printable') b = qpDecode(buf);
  else if (enc === 'base64') { try { b = Buffer.from(buf.toString('ascii').replace(/\s/g, ''), 'base64'); } catch (e) {} }
  const cs = String((info && info.parameters && info.parameters.charset) || 'utf-8').toLowerCase();
  let s;
  if (cs.includes('1252') || cs.includes('8859-1') || cs === 'latin1') s = iconv ? iconv.decode(b, 'windows-1252') : b.toString('latin1');
  else if (cs.includes('2312') || cs.includes('gbk') || cs.includes('gb18030')) s = iconv ? iconv.decode(b, 'gbk') : b.toString('utf8');
  else if (cs.includes('big5')) s = iconv ? iconv.decode(b, 'big5') : b.toString('utf8');
  else s = b.toString('utf8');
  const tagCount = (s.match(/<[a-z][^>]*>/gi) || []).length;
  if ((info && info.type) === 'text/html' || /^\s*<(!doctype|html|div|meta|table|body|span|p|center|font)/i.test(s) || tagCount > 5) s = html2text(s);
  return s.replace(/\s+/g, ' ').trim().slice(0, 4000);
}

async function realUids(folder) {
  const c = conn(); await c.connect(); await c.mailboxOpen(folder, { readOnly: true });
  const u = [];
  for await (const m of c.fetch('1:*', { uid: true }, { uid: true })) u.push(m.uid);
  try { await c.logout(); } catch (e) {}
  u.sort((a, b) => a - b);
  return u;
}
async function worker(id, uids) {
  const cl = conn();
  cl.on('error', e => log('w' + id + ' err:', e.message));
  await cl.connect();
  await cl.mailboxOpen(FOLDER, { readOnly: true });
  const file = OUT.replace(/(\.jsonl)?$/, id + '.jsonl');
  const out = fs.createWriteStream(file, { flags: 'w' });
  const t0 = Date.now(); let fetched = 0;
  for (let i = 0; i < uids.length; i += BATCH) {
    const batch = uids.slice(i, i + BATCH);
    try {
      for await (const m of cl.fetch(batch.join(','), { uid: true, bodyParts: ['1'], bodyStructure: true, envelope: true }, { uid: true })) {
        const bp = m.bodyParts && m.bodyParts.get('1');
        const info = findPart(m.bodyStructure, '1');
        const text = bp ? decodePart(bp, info) : '';
        out.write(JSON.stringify({ uid: m.uid, text, part_type: (info && info.type) || '' }) + '\n');
        fetched++;
      }
    } catch (e) { log('w' + id, 'batch', i, 'ERR', e.message); }
    if (Math.round(i / BATCH) % 6 === 0) log('w' + id, Math.min(i + BATCH, uids.length) + '/' + uids.length, '| got', fetched, '|', Math.round((Date.now() - t0) / 1000) + 's');
  }
  await new Promise(r => out.end(r));
  try { await cl.logout(); } catch (e) {}
  log('w' + id, 'DONE got', fetched);
}

(async () => {
  let uids;
  if (UIDARG === 'all') uids = await realUids(FOLDER);
  else if (UIDARG.startsWith('file:')) uids = JSON.parse(fs.readFileSync(UIDARG.slice(5), 'utf8')).map(x => typeof x === 'object' ? x.uid : x);
  else uids = UIDARG.split(',').map(Number);
  log('FOLDER=' + FOLDER + ' REAL uids:', uids.length);
  const shards = Array.from({ length: WORKERS }, () => []);
  uids.forEach((u, i) => shards[i % WORKERS].push(u));
  await Promise.all(shards.map((s, i) => worker(i, s)));
  log('ALL DONE → ' + OUT.replace(/(\.jsonl)?$/, '{0..' + (WORKERS - 1) + '}.jsonl'));
  process.exit(0);
})().catch(e => { log('FATAL', e.responseText || e.message || String(e)); process.exit(1); });
