---
name: icloud-mail-triage
description: "通过 icloud-mail MCP 连接 iCloud 邮箱，让模型逐封阅读邮件正文、判断保留/清理/拿不准，把拿不准的交给人工在本地审阅板点选，最后安全地以「可恢复文件夹间移动」方式清理邮箱。适用于：邮箱爆满需整理、批量归档/清理垃圾、把上千封邮件分类而不误删重要邮件。当用户说「整理邮箱」「清理邮件」「审阅邮件」「用模型判断哪些该删」「把拿不准的给我看」或涉及 iCloud/IMAP 邮件批量分类与搬运时，应使用本 skill。"
agent_created: true
---

# iCloud 邮件审阅与清理工作流

把一整个邮箱的整理流程固化为可复用步骤：**连接 → 模型逐封读正文判断 → 拿不准的交人工 → 安全清理**。
设计铁律：**读正文而非关键词；只做可恢复的文件夹间移动，绝不永久删除。**

## 何时使用
- 邮箱爆满、想批量清理垃圾但怕误删重要邮件。
- 需要把成百上千封邮件分类（保留/删除/待定）。
- 用户要求「用模型判断哪些该删」「把拿不准的给我看」「整理我的 iCloud 邮箱」。

## 前置
- 已连接 `icloud-mail` MCP（提供 `list_folders` / `list_messages` / `get_message` / `mailbox_profile`，**只读**）。
- 清理阶段需要脚本直接连 IMAP：在工作目录 `npm install imapflow iconv-lite`，并准备 `cred.json`
  `{host:"imap.mail.me.com",port:993,user,pass}`，`pass` 用 iCloud **App 专用密码**，`chmod 600`。
- 所有脚本读环境变量 `ICLOUD_CRED`（默认 `./cred.json`），且从**当前工作目录**解析 `node_modules`，
  故一律在 `cd` 到工作目录后再运行。

## 流程（详见 references/workflow.md）

1. **连接 & 扫描（只读）**：用 MCP `list_folders`/`mailbox_profile`/`list_messages` 摸清结构；
   大批量取元数据用 `scripts/scan.cjs --out=scan-result.json`。

2. **模型逐封审阅**：对每封取**完整正文**，判 `rescue`（应在 INBOX）/ `junk`（应在已删除）/
   `review`（拿不准）。**必须读 BODY 原文，绝不写正则/关键词脚本代替阅读**；正文残缺时保守判
   `rescue`/`review`，绝不判 `junk`。产出 `model-verdicts.json`
   `[{uid,folder,date,from,subject,excerpt,why,body,v}]`。
   - 抽查：`mcp__icloud-mail__get_message`
   - 大批量正文：`node scripts/fetch_bodies.cjs --folder=INBOX --uids=all --out=inbox-text.jsonl`

3. **人工审阅「拿不准」**：`python3 scripts/review_board.py --verdicts=model-verdicts.json
   [--rules=review-rules.json] --out=review-board.html`。
   **务必用系统浏览器打开**（不要用 WorkBuddy 内置预览面板，其内部 localStorage 易丢、复制/下载
   被拦截——见 references/gotchas.md 第 1 条）。用户在页面逐封判定，导出 `review-decisions.json`
   （若被拦，用页面「导出为可复制文本」按钮复制 JSON 粘进对话）。

4. **汇总 & 校验（只读）**：`python3 scripts/build_actions.py --model=model-verdicts.json
   --decisions=review-decisions.json [--rules] [--excluded] --out=actions.json`。
   脚本校验重复/越界/非法值/待审未判，有异常先解决再执行。

5. **安全清理（可恢复移动）**：
   - 先 `node scripts/apply_actions.cjs --actions=actions.json --dry-run`
   - 再 `node scripts/apply_actions.cjs --actions=actions.json --limit=5`（试跑 5 封）
   - 全量 `node scripts/apply_actions.cjs --actions=actions.json`
   脚本分批 ≤200、每批校验源残留、残留>0 即停机、写 `actions-log.jsonl`；只做文件夹间移动，不 EXPUNGE 回收站。

6. **独立双重核对**：`node scripts/verify.cjs --actions=actions.json --model=model-verdicts.json`
   确认源残留 0、不动邮件完好、副本在目标、总数守恒。

## 脚本清单（scripts/）
- `scan.cjs` — 只读全量元数据扫描（替代反复调 MCP）
- `fetch_bodies.cjs` — 批量取正文（大批量审阅用）
- `review_board.py` — 生成人工审阅工作台 HTML（**系统浏览器打开**）
- `build_actions.py` — 合并模型+人工+规则，产出并校验动作清单
- `apply_actions.cjs` — 安全移动执行器（dry-run / limit / 分批 / 校验）
- `verify.cjs` — 执行后独立双重核对
- `serve.py` — 本地静态服务器，便于系统浏览器打开审阅板

## 必读
- **references/workflow.md** — 端到端步骤、命令、数据契约。
- **references/gotchas.md** — 10 条血泪教训：预览面板陷阱、读正文非关键词、iCloud 无原生 MOVE、
  FETCH 1:* 取真实 UID、复合键、分批校验、独立核对、不碰用户保留文件夹、App 专用密码。

## 数据契约
- `model-verdicts.json`：模型产出，`{uid,folder,v,body,why,...}`
- `review-decisions.json`：人工产出，`{decisions:[{uid,folder,v}]}`
- `review-rules.json`：用户规则，`{rules:[{id,action,match}]}`
- `actions.json`：最终执行清单，`{actions:[{uid,folder,dest,v}]}`
- 跨文件夹判定一律用复合键 `I{uid}`/`D{uid}`（两文件夹 UID 空间独立）。
