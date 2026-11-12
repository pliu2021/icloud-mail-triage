#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「拿不准邮件」人工审阅工作台（纯静态 HTML，无需联网）。

输入:
  --verdicts 模型审阅结论 JSON，数组，每项为
      {uid, folder, date, from, subject, excerpt, why, body?, v:"rescue"|"junk"|"review"}
      其中 v=="review" 的邮件进入待人工审阅列表。
  --rules    (可选) 用户规则 JSON {rules:[{id,label,action,match:{folder?,from_contains:[]}}]}
            action 为 keep_in_place / restore_to_inbox 的邮件自动从待审列表剔除，底部可核对。
  --out     (可选) 输出 HTML 路径，默认 ./review-board.html

输出: 一个本地 HTML 文件。用【系统浏览器】打开它（file:// 或本 skill 的 serve.py），
逐封看正文后判定，进度保存在浏览器 localStorage（系统浏览器持久）。点「导出审阅结果」保存
review-decisions.json；若复制/下载被环境拦截，用「导出为可复制文本」按钮把 JSON 放进文本框手动复制。
"""
import json, glob, os, re, html, sys, argparse, datetime

parser = argparse.ArgumentParser()
parser.add_argument('--verdicts', required=True)
parser.add_argument('--rules', default=None)
parser.add_argument('--out', default='./review-board.html')
parser.add_argument('--title', default='拿不准邮件 · 人工审阅工作台')
args = parser.parse_args()

verdicts = json.load(open(args.verdicts, encoding='utf-8'))
if isinstance(verdicts, dict):
    verdicts = verdicts.get('rows') or verdicts.get('decisions') or verdicts.get('verdicts') or []

rules = {'rules': []}
if args.rules and os.path.exists(args.rules):
    try:
        rules = json.load(open(args.rules, encoding='utf-8'))
    except Exception:
        pass


def sender_addr(r):
    m = re.search(r'<([^>]+)>', r.get('from') or '')
    return (m.group(1) if m else (r.get('from') or '')).lower()


def matched_rule(r):
    a = sender_addr(r)
    for rule in rules.get('rules', []):
        if rule.get('action') not in ('keep_in_place', 'restore_to_inbox'):
            continue
        m = rule.get('match', {})
        if m.get('folder') and m['folder'] != r.get('folder'):
            continue
        toks = m.get('from_contains', [])
        if toks and not any(t.lower() in a for t in toks):
            continue
        return {'label': rule.get('label') or rule.get('id'), 'action': rule.get('action')}
    return None


# 仅 review 进入待审列表
rows = [r for r in verdicts if r.get('v') == 'review']
for r in rows:
    info = matched_rule(r)
    r['rule'] = info['label'] if info else None
    r['rule_action'] = info['action'] if info else None
ruled = [r for r in rows if r.get('rule')]
pending = [r for r in rows if not r.get('rule')]


def addr_key(r):
    a = sender_addr(r)
    return (a.split('@')[-1], a, r.get('date') or '')


pending.sort(key=addr_key)
ruled.sort(key=addr_key)
for i, r in enumerate(pending, 1):
    r['n'] = i
    r['key'] = ('I' if r['folder'] == 'INBOX' else 'D') + str(r['uid'])
for i, r in enumerate(ruled, 1):
    r['n'] = i

rows = pending  # 待审列表 = review 中未被规则命中的部分
seed = json.dumps(rows, ensure_ascii=False).replace('</', '<\\/')
seed_ruled = json.dumps(ruled, ensure_ascii=False).replace('</', '<\\/')
ACTION_CN = {'keep_in_place': '保持现状', 'restore_to_inbox': '放回 INBOX（待执行）'}
c = {}
for r in ruled:
    k = (r['rule'], r['rule_action'])
    c[k] = c.get(k, 0) + 1
rules_text = '；'.join('%s → %d 封%s' % (k[0], v, ACTION_CN.get(k[1], k[1] or ''))
                       for k, v in c.items()) or '（暂无）'

TPL = r'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f6f8;color:#1f2328;font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:20px 20px 60px}
h1{font-size:21px;margin:0 0 4px}.lead{color:#68717b;font-size:13px;margin:0 0 14px}
.bar{position:sticky;top:0;z-index:20;background:#fff;border:1px solid #e1e5ea;border-radius:12px;padding:12px 16px;box-shadow:0 2px 10px rgba(20,30,50,.06);margin-bottom:14px}
.prog{height:7px;background:#e9edf1;border-radius:6px;overflow:hidden;margin:8px 0 6px}.prog i{display:block;height:100%;background:#2f7cf6;width:0;transition:width .25s}
.stats{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:#5b6570}.stats b{color:#1f2328;font-size:14px}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;align-items:center}
input[type=search],select{border:1px solid #d9dee5;border-radius:8px;padding:7px 10px;font:inherit;font-size:13px;background:#fff;color:#1f2328}
input[type=search]{flex:1;min-width:180px}
button{border:1px solid #d9dee5;background:#fff;color:#2b333c;border-radius:8px;padding:7px 12px;font:inherit;font-size:13px;cursor:pointer;transition:.15s}
button:hover{background:#f2f5f9;border-color:#b9c4d2}button.primary{background:#2f7cf6;border-color:#2f7cf6;color:#fff}button.primary:hover{background:#1f68e0}
button.green{border-color:#9ed3b3;color:#1a7f4b}button.red{border-color:#e6b3ac;color:#c0392b}
button:disabled{opacity:.45;cursor:not-allowed}
.card{background:#fff;border:1px solid #e1e5ea;border-radius:14px;padding:22px 24px;box-shadow:0 1px 3px rgba(20,30,50,.05)}
.meta{display:flex;gap:10px;flex-wrap:wrap;font-size:12px;color:#6b7480;margin-bottom:10px}
.pill{background:#eef2f7;border-radius:20px;padding:2px 10px}.pill.del{background:#fdeeee;color:#b0463c}.pill.inb{background:#e8f4ec;color:#1a7f4b}
.subj{font-size:19px;font-weight:650;margin:0 0 12px;line-height:1.4;word-break:break-word}
.kv{font-size:13px;color:#4a535c;margin:3px 0}.kv b{color:#6b7480;font-weight:500;display:inline-block;min-width:62px}
.bodybox{margin-top:14px;background:#f8f9fb;border:1px solid #e8ebef;border-radius:10px;padding:14px 16px;font-size:13px;line-height:1.75;max-height:340px;overflow:auto;white-space:pre-wrap;word-break:break-word}
details{margin-top:12px}summary{cursor:pointer;font-size:13px;color:#2f7cf6}
.why{margin-top:12px;background:#fff8e6;border:1px solid #f0dfae;border-radius:9px;padding:10px 14px;font-size:12.5px;color:#6b5a25}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-top:20px;padding-top:18px;border-top:1px solid #eef0f2;align-items:center}
.actions button{padding:11px 16px;font-size:14px;font-weight:600}
.batch{font-size:12.5px;color:#6b7480;margin-left:auto}
.nav{display:flex;gap:8px;margin-top:14px;align-items:center;font-size:12.5px;color:#6b7480}
.kbd{background:#eef1f5;border:1px solid #d9dee5;border-bottom-width:2px;border-radius:5px;padding:1px 6px;font-size:11px;color:#4a535c}
.listbox{background:#fff;border:1px solid #e1e5ea;border-radius:12px;margin-top:14px;overflow:hidden}
.listbox table{border-collapse:collapse;width:100%;font-size:12.5px}th{background:#f3f5f7;text-align:left;padding:9px 12px;color:#4a535c}
td{padding:7px 12px;border-top:1px solid #eef0f2;cursor:pointer}tr:hover td{background:#f7faff}
.ruledbox{background:#fff;border:1px solid #e1e5ea;border-radius:12px;margin-top:14px;overflow:hidden}
.ruledbox summary{cursor:pointer;padding:12px 16px;font-size:13px;font-weight:600;color:#1a7f4b;list-style:none}
.ruledbox summary::-webkit-details-marker{display:none}
.ruledbox table{border-collapse:collapse;width:100%;font-size:12.5px}
.ruledbox th{background:#f3f5f7;text-align:left;padding:9px 12px;color:#4a535c}
.ruledbox td{padding:6px 12px;border-top:1px solid #eef0f2;cursor:default}
.ruledbox #ruledlist{max-height:420px;overflow:auto}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#d5dbe2;margin-right:6px}
.dot.g{background:#28a35a}.dot.r{background:#d9534f}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1f2328;color:#fff;padding:10px 18px;border-radius:9px;font-size:13px;opacity:0;pointer-events:none;transition:.25s;z-index:50}.toast.on{opacity:1}
.tip{background:#eaf2fe;border:1px solid #c9dcf8;color:#244a80;border-radius:10px;padding:12px 16px;font-size:12.5px;margin-bottom:14px}
.tip b{color:#163a6b}
.mask{position:fixed;inset:0;background:rgba(20,30,50,.55);z-index:80;display:none;align-items:center;justify-content:center}
.mask.on{display:flex}.maskbox{background:#fff;border-radius:12px;max-width:760px;width:92%;padding:18px}
.maskbox textarea{width:100%;height:340px;font:12px/1.5 ui-monospace,Menlo,Consolas,monospace;border:1px solid #d9dee5;border-radius:8px;padding:10px;resize:vertical}
</style></head><body><div class="wrap">
<h1>__TITLE__</h1>
<p class="lead">待你审阅 <b>__TOTAL__</b> 封 ｜ 另有 <b>__RULED_N__</b> 封已按规则处理、无需审阅（合计 __ALL_N__ 封）。逐封看正文后判定，进度自动保存在本浏览器；全部（或部分）判完导出结果交给 WorkBuddy 执行。</p>
<div class="tip"><b>已生效规则：</b>__RULES_TEXT__；可在页面底部展开逐封核对。<br>
<b>怎么把结果同步给我：</b>二选一 —— (1) 点右上角「导出审阅结果」保存为 <code>review-decisions.json</code>，把文件路径告诉我；或 (2) 点「导出为可复制文本」复制 JSON 后直接粘贴到对话里。<br>
<b>重要：</b>请用<b>系统浏览器</b>（Chrome/Safari）打开本文件，不要用 WorkBuddy 内置预览面板——那里的本地存储易丢、复制/下载常被拦截。一次做不完没关系，进度会自动存，可分批导出、分批执行。</div>

<div class="bar">
  <div class="prog"><i id="progbar"></i></div>
  <div class="stats"><span>已判定 <b id="sDone">0</b> / __TOTAL__</span><span>应在 INBOX <b id="sKeep">0</b></span><span>应在已删除 <b id="sJunk">0</b></span><span>仍未判定 <b id="sLeft">__TOTAL__</b></span></div>
  <div class="tools">
    <input type="search" id="q" placeholder="搜索发件人 / 主题 / 正文…">
    <select id="filter"><option value="all">全部</option><option value="todo">仅未判定</option><option value="done">仅已判定</option><option value="INBOX">仅 INBOX 来源</option><option value="Deleted Messages">仅已删除来源</option></select>
    <button id="btnList">列表视图</button>
    <button id="btnImport">导入结果</button>
    <button id="btnCopyText">导出为可复制文本</button>
    <button id="btnExport" class="primary">导出审阅结果</button>
    <input type="file" id="file" accept=".json" hidden>
  </div>
</div>

<div class="card" id="card"></div>
<div class="nav">
  <button id="btnPrev">← 上一封</button><button id="btnNext">下一封 →</button><button id="btnJump">跳到下一未判定</button>
  <span style="margin-left:auto">快捷键：<span class="kbd">1</span> 应在 INBOX　<span class="kbd">2</span> 应在已删除　<span class="kbd">空格</span> 跳过　<span class="kbd">Z</span> 撤销</span>
</div>
<div class="listbox" id="listbox" style="display:none"></div>
<details class="ruledbox" id="ruledbox"><summary>查看已按规则处理、无需审阅的 __RULED_N__ 封（点开逐封核对）</summary><div id="ruledlist"></div></details>
<div class="toast" id="toast"></div>

<div class="mask" id="mask"><div class="maskbox">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px"><b>审阅结果 JSON（全选复制即可）</b><button id="btnCloseMask">关闭</button></div>
  <textarea id="outbox" readonly></textarea>
  <div style="font-size:12px;color:#6b7480;margin-top:6px">在文本框内 Ctrl/Cmd+A 全选 → Ctrl/Cmd+C 复制，粘贴到与 WorkBuddy 的对话里即可。</div>
</div></div>

<script id="seed" type="application/json">__SEED__</script>
<script id="ruledseed" type="application/json">__RULED_SEED__</script>
<script>
const ROWS = JSON.parse(document.getElementById('seed').textContent);
const KEY = 'wb-review-decisions-v1';
let dec = {};
try { dec = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch(e) { dec = {}; }
let idx = 0, view = [], showList = false, lastAction = null;
const $ = id => document.getElementById(id);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function toast(m){ const t=$('toast'); t.textContent=m; t.classList.add('on'); clearTimeout(t._t); t._t=setTimeout(()=>t.classList.remove('on'),2200); }
function save(){ try{ localStorage.setItem(KEY, JSON.stringify(dec)); }catch(e){ toast('本地保存失败，请尽快导出'); } }
function sameSender(r){
  const key = a => { const m=String(a||'').match(/<([^>]+)>/); return (m?m[1]:String(a||'')).toLowerCase(); };
  return ROWS.filter(x => key(x.from) === key(r.from));
}
function refreshView(){
  const q = $('q').value.trim().toLowerCase(), f = $('filter').value;
  view = ROWS.filter(r=>{
    if(f==='todo' && dec[r.key]) return false;
    if(f==='done' && !dec[r.key]) return false;
    if((f==='INBOX'||f==='Deleted Messages') && r.folder!==f) return false;
    if(q && !(String(r.from)+' '+String(r.subject)+' '+String(r.body)+' '+String(r.why)).toLowerCase().includes(q)) return false;
    return true;
  });
  if(idx >= view.length) idx = Math.max(0, view.length-1);
}
function stats(){
  let done=0, keep=0, junk=0;
  ROWS.forEach(r=>{ if(dec[r.key]){ done++; if(dec[r.key]==='rescue') keep++; else junk++; } });
  $('sDone').textContent=done; $('sKeep').textContent=keep; $('sJunk').textContent=junk;
  $('sLeft').textContent=ROWS.length-done;
  $('progbar').style.width=(100*done/ROWS.length).toFixed(1)+'%';
}
function render(){
  refreshView(); stats();
  const c=$('card'), r=view[idx];
  if(!r){ c.innerHTML='<div class="subj">没有符合条件的邮件</div><p class="lead">换个筛选条件，或清空搜索框。</p>'; return; }
  const fromDel = r.folder==='Deleted Messages';
  const cur = dec[r.key];
  const btnKeepTxt = fromDel ? '放回 INBOX' : '留在 INBOX';
  const btnJunkTxt = fromDel ? '留在「已删除」' : '移到「已删除」';
  const batch = sameSender(r).filter(x=>!dec[x.key]).length;
  c.innerHTML =
   '<div class="meta"><span class="pill"># '+r.n+' / '+ROWS.length+'</span>'+
   '<span class="pill '+(fromDel?'del':'inb')+'">'+(fromDel?'当前在「已删除」':'当前在 INBOX')+'</span>'+
   '<span>'+esc(r.date)+'</span><span>UID '+r.uid+'</span>'+
   (cur?'<span class="pill '+(cur==='rescue'?'inb':'del')+'">已判：'+(cur==='rescue'?'应在 INBOX':'应在已删除')+'</span>':'')+'</div>'+
   '<div class="subj">'+esc(r.subject||'(无主题)')+'</div>'+
   '<div class="kv"><b>发件人</b>'+esc(r.from||'(未知)')+'</div>'+
   '<div class="kv"><b>摘要</b>'+esc(r.excerpt||'（正文未解析）')+'</div>'+
   '<div class="why"><b>模型当时拿不准的理由：</b>'+esc(r.why||'—')+'</div>'+
   (r.body?'<details><summary>展开完整正文（'+r.body.length+' 字）</summary><div class="bodybox">'+esc(r.body)+'</div></details>':'')+
   '<div class="actions">'+
     '<button class="green" id="bKeep">'+btnKeepTxt+' <span class="kbd">1</span></button>'+
     '<button class="red" id="bJunk">'+btnJunkTxt+' <span class="kbd">2</span></button>'+
     '<button id="bSkip">跳过 <span class="kbd">空格</span></button>'+
     (batch>1?'<span class="batch">该发件人还有 <b>'+batch+'</b> 封未判定　<button id="bBatchKeep">全部'+btnKeepTxt+'</button> <button id="bBatchJunk">全部'+btnJunkTxt+'</button></span>':'')+
   '</div>';
  $('bKeep').onclick=()=>setVerdict('rescue');
  $('bJunk').onclick=()=>setVerdict('junk');
  $('bSkip').onclick=()=>next();
  if($('bBatchKeep')) $('bBatchKeep').onclick=()=>batchSet('rescue');
  if($('bBatchJunk')) $('bBatchJunk').onclick=()=>batchSet('junk');
  if(showList) renderList();
}
function setVerdict(v){ const r=view[idx]; if(!r) return; dec[r.key]=v; lastAction={key:r.key,prev:null,type:'one'}; save(); next(); }
function batchSet(v){
  const r=view[idx]; if(!r) return;
  const list=sameSender(r).filter(x=>!dec[x.key]); const prev={};
  list.forEach(x=>{ prev[x.key]=dec[x.key]||null; dec[x.key]=v; });
  lastAction={key:r.key,prev,type:'batch'}; save(); toast('已批量判定 '+list.length+' 封'); next();
}
function undo(){
  if(!lastAction){ toast('没有可撤销的操作'); return; }
  const {prev,type}=lastAction;
  if(type==='batch'){ Object.keys(prev).forEach(u=>{ if(prev[u]==null) delete dec[u]; else dec[u]=prev[u]; }); }
  else { delete dec[lastAction.key]; }
  lastAction=null; save(); render(); toast('已撤销');
}
function next(){ if(idx<view.length-1) idx++; else { toast('已到当前筛选的最后一封'); } render(); }
function prev(){ if(idx>0) idx--; render(); }
function jump(){
  refreshView();
  const k=view.findIndex((r,i)=>i>idx && !dec[r.key]);
  if(k>=0) idx=k; else { const k2=view.findIndex(r=>!dec[r.key]); if(k2>=0) idx=k2; else toast('全部判定完成，可以导出啦'); }
  render();
}
function renderList(){
  const box=$('listbox');
  box.innerHTML='<table><thead><tr><th>#</th><th>来源</th><th>日期</th><th>发件人</th><th>主题</th><th>判定</th></tr></thead><tbody>'+
   view.slice(0,400).map((r,i)=>'<tr data-i="'+i+'"><td><span class="dot '+(dec[r.key]==='rescue'?'g':dec[r.key]==='junk'?'r':'')+'"></span>'+r.n+'</td><td>'+(r.folder==='INBOX'?'INBOX':'已删除')+'</td><td>'+esc(r.date)+'</td><td>'+esc(String(r.from).slice(0,34))+'</td><td>'+esc(String(r.subject).slice(0,66))+'</td><td>'+(dec[r.key]==='rescue'?'应在 INBOX':dec[r.key]==='junk'?'应在已删除':'—')+'</td></tr>').join('')+
   '</tbody></table>'+(view.length>400?'<div style="padding:10px 14px;color:#6b7480;font-size:12px">仅显示前 400 条，可用搜索缩小范围</div>':'');
  box.querySelectorAll('tr[data-i]').forEach(tr=>tr.onclick=()=>{ idx=+tr.dataset.i; render(); window.scrollTo({top:0,behavior:'smooth'}); });
}
function exportData(){
  const decisions=ROWS.filter(r=>dec[r.key]).map(r=>({uid:r.uid,folder:r.folder,v:dec[r.key],date:r.date,from:r.from,subject:r.subject}));
  return JSON.stringify({exported_at:new Date().toISOString(),total:ROWS.length,decided:decisions.length,decisions},null,1);
}
$('btnExport').onclick=async()=>{
  const text=exportData(), n=JSON.parse(text).decided;
  if(!n){ toast('还没有判定任何邮件'); return; }
  if(window.showSaveFilePicker){
    try{
      const h=await window.showSaveFilePicker({suggestedName:'review-decisions.json',types:[{description:'JSON',accept:{'application/json':['.json']}}]});
      const w=await h.createWritable(); await w.write(text); await w.close();
      toast('已保存 '+n+' 条结果，把路径告诉 WorkBuddy 即可'); return;
    }catch(e){ if(e.name==='AbortError') return; }
  }
  const a=document.createElement('a'); a.href=URL.createObjectURL(new Blob([text],{type:'application/json'}));
  a.download='review-decisions.json'; a.click(); setTimeout(()=>URL.revokeObjectURL(a.href),1500);
  toast('已下载 review-decisions.json（'+n+' 条）');
};
$('btnCopyText').onclick=()=>{ const t=exportData(); $('outbox').value=t; $('mask').classList.add('on'); };
$('btnCloseMask').onclick=()=>$('mask').classList.remove('on');
$('btnImport').onclick=()=>$('file').click();
$('file').onchange=e=>{
  const f=e.target.files[0]; if(!f) return;
  const rd=new FileReader(); rd.onload=()=>{
    try{ const o=JSON.parse(rd.result); let n=0;
      (o.decisions||[]).forEach(x=>{ if(x&&x.uid!=null&&(x.v==='rescue'||x.v==='junk')){ const k=(x.folder==='INBOX'?'I':'D')+x.uid; dec[k]=x.v; n++; } });
      save(); render(); toast('已导入 '+n+' 条判定');
    }catch(err){ toast('文件格式不对'); }
  }; rd.readAsText(f); e.target.value='';
};
$('btnList').onclick=()=>{ showList=!showList; $('listbox').style.display=showList?'block':'none'; $('btnList').textContent=showList?'收起列表':'列表视图'; if(showList) renderList(); };
$('btnPrev').onclick=prev; $('btnNext').onclick=next; $('btnJump').onclick=jump;
$('q').oninput=()=>{ idx=0; render(); };
$('filter').onchange=()=>{ idx=0; render(); };
document.addEventListener('keydown',e=>{
  if(e.target.tagName==='INPUT'||e.target.tagName==='SELECT'||e.target.tagName==='TEXTAREA') return;
  if(e.key==='1'){ e.preventDefault(); setVerdict('rescue'); }
  else if(e.key==='2'){ e.preventDefault(); setVerdict('junk'); }
  else if(e.key===' '){ e.preventDefault(); next(); }
  else if(e.key==='z'||e.key==='Z'){ e.preventDefault(); undo(); }
  else if(e.key==='ArrowRight'){ e.preventDefault(); next(); }
  else if(e.key==='ArrowLeft'){ e.preventDefault(); prev(); }
});
const RULED = JSON.parse(document.getElementById('ruledseed').textContent);
$('ruledlist').innerHTML='<table><thead><tr><th>#</th><th>原所在位置</th><th>日期</th><th>发件人</th><th>主题</th><th>处理</th></tr></thead><tbody>'+
 RULED.map(r=>'<tr><td>'+r.n+'</td><td>'+(r.folder==='INBOX'?'INBOX':'已删除')+'</td><td>'+esc(r.date)+'</td><td>'+esc(String(r.from).slice(0,38))+'</td><td>'+esc(String(r.subject).slice(0,74))+'</td><td>'+(r.rule_action==='restore_to_inbox'?'<b style="color:#1a7f4b">已放回 INBOX</b>':'保持现状')+'</td></tr>').join('')+'</tbody></table>';
render();
</script></div></body></html>'''

page = (TPL.replace('__TITLE__', html.escape(args.title))
           .replace('__SEED__', seed)
           .replace('__RULED_SEED__', seed_ruled)
           .replace('__RULES_TEXT__', html.escape(rules_text))
           .replace('__ALL_N__', str(len(rows) + len(ruled)))
           .replace('__RULED_N__', str(len(ruled)))
           .replace('__TOTAL__', str(len(rows))))
open(args.out, 'w', encoding='utf-8').write(page)
print('生成:', os.path.abspath(args.out))
print('待审:', len(rows), '| 按规则保留:', len(ruled), '| 合计:', len(rows) + len(ruled))
print('规则:', rules_text)
print('大小:', round(os.path.getsize(args.out) / 1024), 'KB')
print('来源分布: INBOX', sum(1 for r in rows if r['folder'] == 'INBOX'),
      '| 已删除', sum(1 for r in rows if r['folder'] == 'Deleted Messages'))
print('有完整正文:', sum(1 for r in rows if r.get('body')), '| 无正文:', sum(1 for r in rows if not r.get('body')))
