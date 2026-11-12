# iCloud 邮件审阅与清理 · 工作流详解

本 skill 把「连上邮箱 → 模型逐封阅读正文判断 → 拿不准的交人工 → 安全清理」整条流程固化。
核心原则：**读正文、不靠关键词；只做可恢复的文件夹间移动、不永久删除。**

---

## 0. 准备工作目录

```bash
mkdir -p ~/mail-triage && cd ~/mail-triage
npm init -y
npm install imapflow iconv-lite        # 仅清理阶段需要
```

创建凭据文件 `cred.json`（chmod 600，切勿提交）：

```json
{ "host": "imap.mail.me.com", "port": 993, "user": "你的@icloud.com", "pass": "App 专用密码" }
```

> iCloud 必须用 **App 专用密码**（appleid.apple.com → 登录与安全 → App 专用密码），不能用登录密码。
> 之后所有脚本读环境变量 `ICLOUD_CRED`（默认 `./cred.json`）。

---

## 1. 连接 & 扫描（只读）

**优先用 MCP**（已连接 icloud-mail）：
- `mcp__icloud-mail__list_folders` — 列出所有文件夹及封数
- `mcp__icloud-mail__mailbox_profile` — 统计（总数/已读/发件域名/按月）
- `mcp__icloud-mail__list_messages` — 枚举某文件夹元数据（uid/from/subject/date/flagged…）
- `mcp__icloud-mail__get_message` — 抽单封正文（抽查用）

**批量取元数据**可用脚本（比反复调 MCP 更快，产出 JSON 供模型读）：

```bash
node scripts/scan.cjs --out=scan-result.json --folders="INBOX,Deleted Messages"
```

---

## 2. 模型逐封审阅（读正文！）

对每封邮件获取**完整正文**，由模型判断三类之一：

| 判定 | 含义 |
|---|---|
| `rescue` | 真人写的 / 具体事务（录用、入职、面试、订单车票、签证、账单发票、成绩文凭、带档案号函件、求职回执）/ 情绪价值 / `\Flagged` / 针对本人的行政通知 |
| `junk` | 群发广告、订阅简报、条款更新、验证码、安全提醒、动帐模板、评价问卷邀请、纯系统自动通知 |
| `review` | 拿不准（如面向全体学生的非商业群发通知）——交给人工 |

**铁律**：必须读 BODY 原文逐封判断，**绝不写正则/关键词/统计脚本代替阅读**。
正文未解析（MIME/base64 残缺）时，依据 FROM+SUBJ 谨慎判 `rescue` 或 `review`，**绝不判 `junk`**。

- 抽查/少量：直接用 MCP `get_message`
- 大批量（几千封）：`node scripts/fetch_bodies.cjs --folder=INBOX --uids=all --out=inbox-text.jsonl`

产出 `model-verdicts.json`（数组）：

```json
[
  {"uid": 123, "folder": "INBOX", "date": "2024-...", "from": "人和 <a@x.com>",
   "subject": "...", "excerpt": "正文摘要", "why": "引用正文的判定理由", "body": "纯文本正文≤4000字", "v": "rescue|junk|review"}
]
```

> 同一发件人的多封往往同类，模型可按发件人聚合先判，再逐封确认。

---

## 3. 人工审阅「拿不准」的邮件

把 `v=="review"` 的邮件做成本地工作台，交给用户点选：

```bash
python3 scripts/review_board.py \
  --verdicts=model-verdicts.json \
  --rules=review-rules.json \          # 可选：命中规则的自动处理、不进待审
  --out=review-board.html
```

**打开方式（重要）**：用**系统浏览器**打开 `review-board.html`（或 `python3 scripts/serve.py --file=review-board.html`）。
**不要用 WorkBuddy 内置预览面板**——那里的 localStorage 易丢、复制/下载常被沙箱拦截（详见 gotchas.md）。

用户在页面里逐封看正文，按 `1`/`2` 判定，进度自动存浏览器。导出的 `review-decisions.json` 结构：

```json
{"exported_at":"...", "total": 1058, "decided": 1058,
 "decisions":[{"uid": 99, "folder": "Deleted Messages", "v": "rescue"}, ...]}
```

若复制/下载被拦，点页面里的「导出为可复制文本」按钮，把文本框里的 JSON 全选复制，直接粘进对话。

### 规则捷径 `review-rules.json`（可选，最省事）

若用户能给出「某类发件人一律保持/放回」的规则，可跳过人工：

```json
{"rules":[
  {"id":"school","label":"学校群发","action":"keep_in_place",
   "match":{"folder":"INBOX","from_contains":["ec-nantes.fr"]}},
  {"id":"restore","label":"发票系统","action":"restore_to_inbox",
   "match":{"folder":"Deleted Messages","from_contains":["billing@"]}}
]}
```

---

## 4. 汇总 & 校验（只读）

合并模型判定 + 人工决策 + 规则，生成可执行的动作清单并做防越界校验：

```bash
python3 scripts/build_actions.py \
  --model=model-verdicts.json \
  --decisions=review-decisions.json \
  --rules=review-rules.json \
  --excluded=excluded.json \      # 可选：永不触及的文件夹/邮件
  --out=actions.json
```

脚本会打印校验结果：重复、越界（人工判了非 review 邮件）、落在排除清单、非法值、待审未判。
**任一异常都要先解决再执行。**

---

## 5. 安全清理（可恢复移动）

```bash
# 1) 先 dry-run 看计划
node scripts/apply_actions.cjs --actions=actions.json --dry-run

# 2) 试跑 5 封验证方向
node scripts/apply_actions.cjs --actions=actions.json --limit=5

# 3) 全量（每批 ≤200，逐批校验源残留、失败即停，日志写入 actions-log.jsonl）
node scripts/apply_actions.cjs --actions=actions.json
```

执行前把完整清单与风险提示列给用户确认。

---

## 6. 独立双重核对

```bash
node scripts/verify.cjs --actions=actions.json --model=model-verdicts.json
```

确认：移出项源残留 0、放回项源残留 0、不动的邮件完好、副本在目标文件夹末尾、各文件夹总数守恒。

---

## 数据契约速查

| 文件 | 生产者 | 消费者 | 关键字段 |
|---|---|---|---|
| `model-verdicts.json` | 模型（阶段2） | review_board / build_actions | `{uid,folder,v,body,why}` |
| `review-decisions.json` | 人工（阶段3） | build_actions | `{decisions:[{uid,folder,v}]}` |
| `review-rules.json` | 用户 | review_board / build_actions | `{rules:[{id,action,match}]}` |
| `actions.json` | build_actions（阶段4） | apply_actions / verify | `{actions:[{uid,folder,dest,v}]}` |

> 两个文件夹的 UID 空间相互独立，跨文件夹判定一律用复合键 `I{uid}` / `D{uid}`，避免互相覆盖。
