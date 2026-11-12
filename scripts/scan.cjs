'use strict';
/*
 * scan.cjs — 只读全量元数据扫描（替代反复调用 MCP list_messages）。
 * 拉取每个文件夹全部邮件的 envelope / flags / date / size，不下载正文、不修改任何邮件。
 * 结果落盘为 scan-result.json，供模型快速枚举与生成概览报告。
 *
 * 用法:
 *   node scan.cjs [--out=scan-result.json] [--folders=INBOX,Deleted Messages,...]
 * 凭据: 读 ICLOUD_CRED 环境变量（默认 ./cred.json），格式 {host,port,user,pass}
 * 依赖: 在工作目录下 npm install imapflow
 */
const fs = require('fs');
const path = require('path');
const { createRequire } = require('module');

const req = createRequire(path.join(process.cwd(), 'node_modules/imapflow/package.json'));
const { ImapFlow } = req('imapflow');

const A = process.argv.slice(2);
const getArg = (k, d) => { const x = A.find(a => a.startsWith(k + '=')); return x ? x.slice(k.length + 1) : d; };
const OUT = getArg('--out', 'scan-result.json');
const FOLDERS = (getArg('--folders') || 'INBOX,Deleted Messages,Junk,Sent Messages,Archive')
  .split(',').map(s => s.trim());

const CRED_PATH = process.env.ICLOUD_CRED || './cred.json';
const cred = JSON.parse(fs.readFileSync(CRED_PATH, 'utf8'));
const log = (...a) => process.stderr.write('[scan] ' + a.join(' ') + '\n');
const norm = s => String(s || '').replace(/\s+/g, ' ').trim();

(async () => {
  const cl = new ImapFlow({
    host: cred.host, port: cred.port || 993, secure: true,
    auth: { user: cred.user, pass: cred.pass }, logger: false
  });
  cl.on('error', e => log('imap-error:', e.message));
  await cl.connect();
  log('connected as', cred.user);

  const result = { scanned_at: new Date().toISOString(), account: cred.user, folders: {}, messages: [] };
  const tree = await cl.list({ statusQuery: { messages: true, unseen: true } });
  const flat = [];
  const walk = xs => (xs || []).forEach(f => { flat.push(f); if (f.children) walk(f.children); });
  walk(tree);
  result.folder_tree = flat.map(f => ({ path: f.path, messages: f.status && f.status.messages, unseen: f.status && f.status.unseen }));

  for (const folder of FOLDERS) {
    if (!flat.some(f => f.path === folder)) { log('skip (不存在):', folder); continue; }
    let mb;
    try { mb = await cl.mailboxOpen(folder, { readOnly: true }); }
    catch (e) { log('skip ' + folder + ': ' + e.message); continue; }
    const t0 = Date.now(); let n = 0;
    try {
      for await (const m of cl.fetch('1:*', { uid: true, envelope: true, flags: true, internalDate: true, size: true }, { uid: true })) {
        const env = m.envelope || {};
        const from = (env.from && env.from[0]) || null;
        const flags = m.flags ? Array.from(m.flags) : [];
        const d = m.internalDate ? new Date(m.internalDate) : (env.date ? new Date(env.date) : null);
        result.messages.push({
          folder,
          uid: m.uid,
          from_name: from && from.name ? norm(from.name) : '',
          from_addr: from ? String(from.address || '').toLowerCase() : '',
          to: (env.to || []).map(x => String(x.address || '')).join(',').toLowerCase(),
          subject: norm(env.subject || ''),
          date: d && !isNaN(d.getTime()) ? d.toISOString() : null,
          seen: flags.includes('\\Seen'),
          flagged: flags.includes('\\Flagged'),
          answered: flags.includes('\\Answered'),
          size: m.size || 0,
          message_id: env.messageId || ''
        });
        n++;
        if (n % 500 === 0) log(folder, n + ' rows');
      }
    } catch (e) { log('partial ' + folder + ': ' + (e.responseText || e.message)); }
    result.folders[folder] = { messages: n, ms: Date.now() - t0 };
    log('DONE ' + folder + ' ' + n + ' in ' + Math.round((Date.now() - t0) / 1000) + 's');
  }
  try { await cl.logout(); } catch (e) {}
  fs.writeFileSync(OUT, JSON.stringify(result));
  log('WROTE ' + OUT + ' total=' + result.messages.length);
  process.exit(0);
})().catch(e => { log('FATAL ' + (e.responseText || e.message || String(e))); process.exit(1); });
