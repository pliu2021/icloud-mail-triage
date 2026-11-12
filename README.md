# iCloud 邮件审阅与清理 Skill

> 一条可复用的流水线：**连接邮箱 → 模型逐封阅读正文判断 → 拿不准的交人工 → 安全地以「可恢复文件夹间移动」方式清理**。
>
> 设计铁律：**读正文而非关键词；只做可恢复的文件夹间移动，绝不永久删除。**

---

## 1. 它能做什么 / 不能做什么

**能做的**
- 把一整个邮箱（几千封乃至上万封）批量分类为 **保留 / 清理 / 待定** 三类。
- 用大模型**逐封阅读正文**做判断，而不是用关键词或域名统计（后者会误杀订单、账单、录取通知等）。
- 把「模型拿不准」的邮件自动收集到一个**本地人工审阅板**，你在浏览器里点两下就能判定。
- 按判定结果**安全地搬运邮件**（INBOX ↔ 已删除），全程可恢复。
- 执行前、执行中、执行后都有校验与独立核对，杜绝误伤。

**不能 / 不会做的**
- **不会永久删除**：只会把邮件在文件夹之间移动，从不 `EXPUNGE` 已删除邮件（回收站里随时能找回）。
- **不碰你点名「保留」的邮件**：可配置排除清单，这些邮件一律不动。
- **不依赖邮箱服务商的特殊能力**：iCloud 没有原生「MOVE」，本 skill 用 IMAP 标准「复制到目标 + 标记源删除」来等价实现。
- 不处理加密邮件、不读取附件内容、不发送邮件。

---

## 2. 适用场景

- 邮箱爆满、想批量清理垃圾但怕误删重要邮件。
- 需要把成百上千封邮件分类（保留 / 删除 / 待定）。
- 你希望「先让模型读一遍、拿不准的再由我亲自把关」。

**当前默认针对 iCloud / me.com 邮箱**（`imap.mail.me.com`）。若用于其它 IMAP 邮箱，只需改凭据里的 `host`/`port` 即可，正文阅读与判定逻辑完全通用。

---

## 3. 目录结构

```
icloud-mail-triage/
├── README.md                 # 本文件
├── SKILL.md                  # 给 AI Agent 看的触发条件与流程摘要
├── references/
│   ├── workflow.md           # 端到端步骤、命令、数据契约
│   └── gotchas.md            # 10 条实战踩坑教训
└── scripts/
    ├── scan.cjs             # 只读全量元数据扫描
    ├── fetch_bodies.cjs     # 批量取正文（大批量审阅用）
    ├── review_board.py      # 生成人工审阅工作台 HTML
    ├── build_actions.py     # 合并模型+人工+规则，产出并校验动作清单
    ├── apply_actions.cjs    # 安全移动执行器（dry-run / limit / 分批 / 校验）
    ├── verify.cjs           # 执行后独立双重核对
    └── serve.py             # 本地静态服务器，便于系统浏览器打开审阅板
```

---

## 4. 安装

### 方式 A：解压 zip（推荐分享用）
1. 解压 `icloud-mail-triage.zip`，得到 `icloud-mail-triage/` 文件夹。
2. 把整个文件夹拖入：
   - macOS / Linux：`~/.workbuddy/skills/`
   - Windows：`%USERPROFILE%\.workbuddy\skills\`
3. 最终路径应为 `~/.workbuddy/skills/icloud-mail-triage/SKILL.md`。

### 方式 B：直接复制文件夹
把 `icloud-mail-triage/` 整个目录放进上述 `skills/` 目录即可。

### 启用 MCP（必需）
本 skill 的「连接 / 读取」阶段依赖 `icloud-mail` MCP（只读）。请先在 WorkBuddy 的 MCP 配置里连接它。
> 读取阶段用 MCP，但**清理阶段用脚本直接连 IMAP**（MCP 是只读的，没有移动/删除工具）。

安装完成后，在对话里说「整理邮箱 / 清理邮件 / 用模型判断哪些该删」，skill 就会被触发。

---

## 5. 前置准备（一次性）

### 5.1 依赖
- **Node.js ≥ 18**（运行 `.cjs` 脚本）
- **Python 3.8+**（运行 `.py` 脚本）
- **npm 包**（仅清理阶段需要）：在**工作目录**执行
  ```bash
  npm install imapflow iconv-lite
  ```
- **icloud-mail MCP** 已连接（只读读取用）

### 5.2 凭据 `cred.json`
新建工作目录（例如 `~/mail-triage`），在里面放 `cred.json`：

```json
{
  "host": "imap.mail.me.com",
  "port": 993,
  "user": "你的账号@icloud.com",
  "pass": "App 专用密码"
}
```

```bash
chmod 600 cred.json        # 务必收紧权限，切勿提交到 git
```

> ⚠️ iCloud **必须使用 App 专用密码**（appleid.apple.com → 登录与安全 → App 专用密码），不能用 Apple ID 登录密码。
> 所有脚本读取环境变量 `ICLOUD_CRED`（默认 `./cred.json`）。换邮箱/换路径时设 `export ICLOUD_CRED=/path/to/cred.json`。

### 5.3 工作目录约定
所有脚本都从**当前工作目录**解析 `node_modules` 与默认 `cred.json`，因此一律先 `cd` 到工作目录再运行命令。

```bash
mkdir -p ~/mail-triage && cd ~/mail-triage
npm init -y && npm install imapflow iconv-lite
# 把 cred.json 放进这里，并把本 skill 的 scripts/ 复制或软链过来
```

---

## 6. 快速上手（端到端 6 步）

下面是最短可用路径。每条命令都在**工作目录**下执行。

```bash
# ① 连接 & 扫描（只读，产出 scan-result.json 供模型读）
node scripts/scan.cjs --out=scan-result.json --folders="INBOX,Deleted Messages"

# ② 模型逐封读正文，产出 model-verdicts.json
#    （这一步由 AI Agent 调用 MCP get_message / fetch_bodies.cjs 完成，见 §7.2）

# ③ 生成人工审阅板（只含 v=="review" 的拿不准邮件）
python3 scripts/review_board.py \
  --verdicts=model-verdicts.json \
  --rules=review-rules.json \      # 可选
  --out=review-board.html
#    用【系统浏览器】打开 review-board.html（见 §7.3），导出 review-decisions.json

# ④ 汇总 & 校验（只读，产出 actions.json）
python3 scripts/build_actions.py \
  --model=model-verdicts.json \
  --decisions=review-decisions.json \
  --rules=review-rules.json \
  --excluded=excluded.json \        # 可选
  --out=actions.json

# ⑤ 安全清理（可恢复移动）
node scripts/apply_actions.cjs --actions=actions.json --dry-run   # 先看计划
node scripts/apply_actions.cjs --actions=actions.json --limit=5   # 试跑 5 封
node scripts/apply_actions.cjs --actions=actions.json            # 全量

# ⑥ 独立双重核对
node scripts/verify.cjs --actions=actions.json --model=model-verdicts.json
```

---

## 7. 各阶段详解

### 7.1 阶段 0 · 准备工作目录与凭据
见 §5。务必确认 `cred.json` 权限为 600，且 `ICLOUD_CRED` 指向正确。

### 7.2 阶段 1 · 连接 & 扫描（只读）
- **优先用 MCP**（已连接 icloud-mail）：
  - `list_folders` 列出所有文件夹及封数
  - `mailbox_profile` 统计（总数 / 已读 / 发件域名 / 按月）
  - `list_messages` 枚举某文件夹元数据（uid / from / subject / date / flagged…）
  - `get_message` 抽单封正文（抽查用）
- **批量取元数据**用脚本（比反复调 MCP 更快，产出 JSON 供模型读）：
  ```bash
  node scripts/scan.cjs --out=scan-result.json --folders="INBOX,Deleted Messages,Junk"
  ```
  默认扫描 `INBOX,Deleted Messages,Junk,Sent Messages,Archive`。

### 7.3 阶段 2 · 模型逐封审阅（读正文！）
对每封邮件获取**完整正文**，由模型判断三类之一：

| 判定 | 含义 |
|---|---|
| `rescue` | 真人写的 / 具体事务（录用、入职、面试、订单车票、签证、账单发票、成绩文凭、带档案号函件、求职回执）/ 情绪价值 / `\Flagged` / 针对本人的行政通知 |
| `junk` | 群发广告、订阅简报、条款更新、验证码、安全提醒、动帐模板、评价问卷邀请、纯系统自动通知 |
| `review` | 拿不准（如面向全体学生的非商业群发通知）——交给人工 |

**铁律**：必须读 BODY 原文逐封判断，**绝不写正则/关键词/统计脚本代替阅读**。
正文未解析（MIME / base64 残缺）时，依据 `FROM + SUBJECT` 谨慎判 `rescue` 或 `review`，**绝不判 `junk`**（宁可保留，不可错删）。

- 抽查 / 少量：直接用 MCP `get_message`
- 大批量（几千封）：`node scripts/fetch_bodies.cjs --folder=INBOX --uids=all --out=inbox-text.jsonl`
  - 支持 `--uids=file:uids.json`（从文件读取 UID 列表）、`--workers`（默认 3）、`--batch`（默认 100）

产出 `model-verdicts.json`（**数组**）：
```json
[
  {
    "uid": 123,
    "folder": "INBOX",
    "date": "2024-...",
    "from": "张三 <a@x.com>",
    "subject": "...",
    "excerpt": "正文摘要（供人工看）",
    "why": "引用正文的判定理由",
    "body": "纯文本正文，≤4000 字",
    "v": "rescue | junk | review"
  }
]
```
> 同一发件人的多封往往同类，模型可按发件人聚合先判，再逐封确认。

### 7.4 阶段 3 · 人工审阅「拿不准」的邮件
把 `v == "review"` 的邮件做成**本地工作台**，你逐封看正文后点选判定：

```bash
python3 scripts/review_board.py \
  --verdicts=model-verdicts.json \
  --rules=review-rules.json \     # 可选：命中规则的自动处理，不进待审
  --title="我的邮箱审阅" \
  --out=review-board.html
```

**打开方式（极重要）**：用**系统浏览器**打开 `review-board.html`。
- 推荐：`python3 scripts/serve.py --file=review-board.html`（自动打开默认浏览器）
- 也可直接双击文件用 `file://` 打开

> ⚠️ **不要用 WorkBuddy 内置预览面板打开审阅板！** 其内部的 `localStorage` 易丢失、复制/下载常被沙箱拦截——一次就丢过 300+ 封的判定结果（教训见 `references/gotchas.md` 第 1 条）。

**页面操作**
- 逐封看正文，按 `1`（保留 / rescue）或 `2`（清理 / junk）判定，进度自动存浏览器本地。
- 完成后点「导出审阅结果」保存 `review-decisions.json`。
- **若复制/下载被环境拦截**：点「导出为可复制文本」按钮，把文本框里的 JSON 全选复制，直接粘进对话即可。

导出文件结构：
```json
{
  "exported_at": "2026-...",
  "total": 1058,
  "decided": 1058,
  "decisions": [
    {"uid": 99, "folder": "Deleted Messages", "v": "rescue"},
    {"uid": 88, "folder": "INBOX", "v": "junk"}
  ]
}
```

### 7.5 规则捷径 `review-rules.json`（可选，最省事）
若你能给出「某类发件人一律保持 / 放回」的规则，可跳过人工，直接自动处理：

```json
{
  "rules": [
    {
      "id": "school",
      "label": "学校群发",
      "action": "keep_in_place",
      "match": {"folder": "INBOX", "from_contains": ["ec-nantes.fr"]}
    },
    {
      "id": "restore",
      "label": "发票系统",
      "action": "restore_to_inbox",
      "match": {"folder": "Deleted Messages", "from_contains": ["billing@"]}
    }
  ]
}
```
- `keep_in_place`：判定为「保持现状」，从待审剔除。
- `restore_to_inbox`：判定为「放回 INBOX」，从待审剔除。
- `from_contains` 任一子串命中即匹配（大小写不敏感）。

### 7.6 阶段 4 · 汇总 & 校验（只读）
合并 **模型判定 + 人工决策 + 规则**，生成可执行动作清单并做防越界校验：

```bash
python3 scripts/build_actions.py \
  --model=model-verdicts.json \
  --decisions=review-decisions.json \
  --rules=review-rules.json \
  --excluded=excluded.json \     # 可选：永不触及的文件夹/邮件
  --out=actions.json
```

脚本会打印校验报告：`重复 / 越界（人工判了非 review 邮件）/ 落在排除清单 / 非法值 / 待审未判`。
**任一异常都要先解决再执行。**

语义规则：
- `rescue` = 最终应在 **INBOX**
- `junk` = 最终应在 **Deleted Messages**（可恢复，非永久删除）
- 模型判 `rescue`/`junk` 的邮件自动执行；`review` 的需人工 `decision` 覆盖
- 规则命中且 `action` 为 `keep_in_place` / `restore_to_inbox` 的从待审剔除

### 7.7 阶段 5 · 安全清理（可恢复移动）
```bash
# 1) 先 dry-run 看计划（不连邮箱、不改动）
node scripts/apply_actions.cjs --actions=actions.json --dry-run

# 2) 试跑 5 封验证方向
node scripts/apply_actions.cjs --actions=actions.json --limit=5

# 3) 全量（每批 ≤200，逐批校验源残留、残留>0 即停机，日志写入 actions-log.jsonl）
node scripts/apply_actions.cjs --actions=actions.json
```

执行前请把完整清单与风险提示列给用户确认。
- `--batch=N` 可调整每批封数（默认 200）
- `--log=path.jsonl` 指定回滚日志路径（默认 `actions-log.jsonl`）
- **全程只做文件夹间移动，不 EXPUNGE 回收站**，因此任何一封都可在回收站找回。

### 7.8 阶段 6 · 独立双重核对
```bash
node scripts/verify.cjs --actions=actions.json --model=model-verdicts.json
```
确认：移出项源残留 0、放回项源残留 0、不动的邮件完好、副本在目标文件夹末尾、各文件夹总数守恒。

---

## 8. 数据契约速查

| 文件 | 生产者 | 消费者 | 关键字段 |
|---|---|---|---|
| `model-verdicts.json` | 模型（阶段 2） | review_board / build_actions | `{uid, folder, v, body, why}` |
| `review-decisions.json` | 人工（阶段 3） | build_actions | `{decisions:[{uid, folder, v}]}` |
| `review-rules.json` | 用户 | review_board / build_actions | `{rules:[{id, action, match}]}` |
| `actions.json` | build_actions（阶段 4） | apply_actions / verify | `{actions:[{uid, folder, dest, key, v}]}` |
| `actions-log.jsonl` | apply_actions（阶段 5） | 撤销 / 核对 | 每批执行回滚记录 |

> **复合键**：两个文件夹（INBOX / Deleted Messages）的 UID 空间相互独立，跨文件夹判定一律用复合键 `I{uid}` / `D{uid}`，避免互相覆盖。

---

## 9. 安全与撤销

- **不永久删除**：所有清理都是「复制到目标文件夹 + 在源文件夹标记删除」，已删除邮件仍在「已删除」文件夹（回收站）中，随时可手动移回。
- **可回滚日志**：`actions-log.jsonl` 记录每批执行的（uid, 源文件夹, 目标文件夹），需要撤销时按日志反向移动即可。
- **分批校验**：每批移动后立刻回查源文件夹残留，残留 > 0 立即停机，绝不静默漏判。
- **独立核对**：`verify.cjs` 用与执行器不同的逻辑通道复核，确认总数守恒、无邮件凭空消失。
- **排除清单**：`--excluded=excluded.json` 指定 `{items:[{key:"I123"}]}` 等，这些邮件一律不触及。

---

## 10. 常见问题（FAQ）

**Q：审阅板在 WorkBuddy 预览面板里打开，结果丢了怎么办？**
A：这就是 §7.4 强调的坑。务必用**系统浏览器**打开（`serve.py` 最省事）。若已丢失，只能重做该部分——所以导出 `review-decisions.json` 后请立即保存备份。

**Q：iCloud 连不上 / 认证失败？**
A：确认用的是 **App 专用密码**，不是 Apple ID 登录密码；确认 `cred.json` 的 `host`/`port` 正确，且 `ICLOUD_CRED` 指向它。

**Q：能用于 Gmail / 企业邮箱吗？**
A：可以。改 `cred.json` 的 `host`/`port`/`user`/`pass` 即可（Gmail 需用应用专用密码 / OAuth 依服务商而定）。读取与判定逻辑通用。

**Q：脚本报 `Cannot find module 'imapflow'`？**
A：在**工作目录**执行 `npm install imapflow iconv-lite`，且运行命令前先 `cd` 到该目录。

**Q：执行到一半想停？**
A：直接 Ctrl+C。已执行的批次记录在 `actions-log.jsonl`，未执行的不会动。停后可用 `verify.cjs` 核对现状，再决定是否续跑。

**Q：误移到「已删除」的重要邮件怎么找回？**
A：登录邮箱网页端，进入「已删除」文件夹，手动移回 INBOX 即可（本 skill 从不 EXPUNGE）。

---

## 11. 自定义与扩展

- **判定标准**：阶段 2 的 `rescue/junk/review` 三类划分可按你的偏好调整（改模型 prompt 即可，脚本只认这三个枚举值）。
- **规则文件**：用 `review-rules.json` 把「某发件人保持 / 放回」固化，跳过人工，最省事。
- **排除清单**：`excluded.json` 保护你永远不想动的邮件（如某些存档文件夹）。
- **批大小 / 并发**：`apply_actions.cjs --batch`、`fetch_bodies.cjs --workers/--batch` 可调。

---

## 12. 许可与致谢

本 skill 按 WorkBuddy 用户级 skill 规范打包，可自由复制、修改、二次分发。
核心方法论来自一次真实的大规模邮箱整理实践（7,000+ 封逐封阅读、1,100+ 封人工复核），踩坑经验沉淀于 `references/gotchas.md`。

*愿你的收件箱从此清爽，且重要邮件一封不少。*

---

# English Version

# iCloud Mail Triage & Cleanup Skill

> A reusable pipeline: **Connect mailbox → Model reads each email body to decide → Uncertain ones go to human → Safely clean up via "recoverable folder-to-folder move".**
>
> Design principles: **Read the body, not keywords; only do recoverable folder moves, never permanent deletion.**

---

## 1. What it can / cannot do

**Can do**
- Batch-classify an entire mailbox (thousands to tens of thousands of emails) into three categories: **keep / clean / pending**.
- Use an LLM to **read each email body** and decide, instead of using keywords or domain statistics (which would wrongly delete orders, bills, admission letters, etc.).
- Automatically collect "uncertain" emails into a **local human review board** where you decide with a couple of clicks in the browser.
- **Safely move emails** (INBOX ↔ Deleted) based on decisions, fully recoverable.
- Validation and independent verification before, during, and after execution, to prevent accidental damage.

**Cannot / will not do**
- **Will not permanently delete**: only moves emails between folders, never `EXPUNGE`s deleted emails (always recoverable from Trash).
- **Will not touch emails you marked "keep"**: configurable exclusion list; those emails are never touched.
- **Does not depend on provider-specific capabilities**: iCloud has no native "MOVE", so this skill uses the IMAP-standard "copy to target + mark source deleted" to achieve the equivalent.
- Does not process encrypted emails, does not read attachment contents, does not send emails.

---

## 2. Use cases

- Mailbox is overflowing, want to batch-clean junk but afraid of deleting important emails.
- Need to classify hundreds to thousands of emails (keep / delete / pending).
- You want "let the model read first, then I personally review the uncertain ones".

**Currently defaults to iCloud / me.com mailboxes** (`imap.mail.me.com`). For other IMAP mailboxes, just change `host`/`port` in credentials; the body-reading and decision logic is fully generic.

---

## 3. Directory structure

```
icloud-mail-triage/
├── README.md                 # This file
├── SKILL.md                  # Trigger conditions & workflow summary for the AI Agent
├── references/
│   ├── workflow.md           # End-to-end steps, commands, data contracts
│   └── gotchas.md            # 10 hard-won lessons from real use
└── scripts/
    ├── scan.cjs             # Read-only full metadata scan
    ├── fetch_bodies.cjs     # Batch fetch bodies (for large-scale review)
    ├── review_board.py      # Generate the human review board HTML
    ├── build_actions.py     # Merge model+human+rules, produce & validate action list
    ├── apply_actions.cjs    # Safe move executor (dry-run / limit / batch / verify)
    ├── verify.cjs           # Independent double-check after execution
    └── serve.py             # Local static server for opening the review board in a browser
```

---

## 4. Installation

### Method A: Unzip the zip (recommended for sharing)
1. Unzip `icloud-mail-triage.zip` to get the `icloud-mail-triage/` folder.
2. Drag the whole folder into:
   - macOS / Linux: `~/.workbuddy/skills/`
   - Windows: `%USERPROFILE%\.workbuddy\skills\`
3. The final path should be `~/.workbuddy/skills/icloud-mail-triage/SKILL.md`.

### Method B: Copy the folder directly
Place the entire `icloud-mail-triage/` directory into the `skills/` directory above.

### Enable MCP (required)
The "connect / read" stage depends on the `icloud-mail` MCP (read-only). Please connect it in WorkBuddy's MCP configuration first.
> Reading uses MCP, but **the cleanup stage uses scripts connecting directly to IMAP** (MCP is read-only, with no move/delete tools).

After installation, say "tidy my mailbox / clean up emails / use a model to decide what to delete" in a conversation, and the skill will be triggered.

---

## 5. Prerequisites (one-time)

### 5.1 Dependencies
- **Node.js ≥ 18** (runs `.cjs` scripts)
- **Python 3.8+** (runs `.py` scripts)
- **npm packages** (only needed for the cleanup stage): run in the **working directory**
  ```bash
  npm install imapflow iconv-lite
  ```
- **icloud-mail MCP** connected (for read-only reading)

### 5.2 Credentials `cred.json`
Create a working directory (e.g. `~/mail-triage`) and put `cred.json` in it:

```json
{
  "host": "imap.mail.me.com",
  "port": 993,
  "user": "your-account@icloud.com",
  "pass": "App-Specific Password"
}
```

```bash
chmod 600 cred.json        # Tighten permissions; never commit to git
```

> ⚠️ iCloud **must use an App-Specific Password** (appleid.apple.com → Sign-In and Security → App-Specific Passwords), not your Apple ID login password.
> All scripts read the `ICLOUD_CRED` environment variable (default `./cred.json`). To switch mailbox/path, set `export ICLOUD_CRED=/path/to/cred.json`.

### 5.3 Working directory convention
All scripts resolve `node_modules` and the default `cred.json` from the **current working directory**, so always `cd` into the working directory before running commands.

```bash
mkdir -p ~/mail-triage && cd ~/mail-triage
npm init -y && npm install imapflow iconv-lite
# Put cred.json here, and copy or symlink this skill's scripts/ here
```

---

## 6. Quick start (end-to-end, 6 steps)

Below is the shortest usable path. Each command runs in the **working directory**.

```bash
# ① Connect & scan (read-only, produces scan-result.json for the model to read)
node scripts/scan.cjs --out=scan-result.json --folders="INBOX,Deleted Messages"

# ② Model reads each email body, produces model-verdicts.json
#    (done by the AI Agent via MCP get_message / fetch_bodies.cjs; see §7.2)

# ③ Generate the human review board (only v=="review" uncertain emails)
python3 scripts/review_board.py \
  --verdicts=model-verdicts.json \
  --rules=review-rules.json \      # optional
  --out=review-board.html
#    Open review-board.html in a 【system browser】 (see §7.3), export review-decisions.json

# ④ Merge & validate (read-only, produces actions.json)
python3 scripts/build_actions.py \
  --model=model-verdicts.json \
  --decisions=review-decisions.json \
  --rules=review-rules.json \
  --excluded=excluded.json \        # optional
  --out=actions.json

# ⑤ Safe cleanup (recoverable move)
node scripts/apply_actions.cjs --actions=actions.json --dry-run   # preview plan first
node scripts/apply_actions.cjs --actions=actions.json --limit=5   # trial run of 5
node scripts/apply_actions.cjs --actions=actions.json            # full run

# ⑥ Independent double-check
node scripts/verify.cjs --actions=actions.json --model=model-verdicts.json
```

---

## 7. Stage details

### 7.1 Stage 0 · Prepare working directory & credentials
See §5. Make sure `cred.json` has 600 permissions and `ICLOUD_CRED` points correctly.

### 7.2 Stage 1 · Connect & scan (read-only)
- **Prefer MCP** (icloud-mail connected):
  - `list_folders` lists all folders and counts
  - `mailbox_profile` statistics (total / read / sender domains / by month)
  - `list_messages` enumerates metadata of a folder (uid / from / subject / date / flagged…)
  - `get_message` extracts a single email body (for spot checks)
- **Batch metadata** via script (faster than repeated MCP calls, produces JSON for the model to read):
  ```bash
  node scripts/scan.cjs --out=scan-result.json --folders="INBOX,Deleted Messages,Junk"
  ```
  Default scans `INBOX,Deleted Messages,Junk,Sent Messages,Archive`.

### 7.3 Stage 2 · Model reviews each email (read the body!)
For each email, fetch the **full body** and let the model decide one of three categories:

| Verdict | Meaning |
|---|---|
| `rescue` | Human-written / specific matter (admission, onboarding, interview, order/ticket, visa, bill/invoice, grades/diploma, letter with case number, job-application reply) / emotional value / `\Flagged` / personal administrative notice |
| `junk` | Mass advertising, subscription newsletter, terms update, verification code, security alert, transaction template, survey/feedback invite, pure system auto-notice |
| `review` | Uncertain (e.g. non-commercial mass notice to all students) — hand to human |

**Hard rule**: must read the BODY and decide per email; **never write regex/keyword/statistics scripts to replace reading**.
When the body is unparsed (MIME / base64 broken), judge `rescue` or `review` cautiously from `FROM + SUBJECT`, **never judge `junk`** (better to keep than to wrongly delete).

- Spot check / small batches: use MCP `get_message` directly
- Large batches (thousands): `node scripts/fetch_bodies.cjs --folder=INBOX --uids=all --out=inbox-text.jsonl`
  - Supports `--uids=file:uids.json` (read UID list from file), `--workers` (default 3), `--batch` (default 100)

Produces `model-verdicts.json` (**array**):
```json
[
  {
    "uid": 123,
    "folder": "INBOX",
    "date": "2024-...",
    "from": "Zhang San <a@x.com>",
    "subject": "...",
    "excerpt": "body summary (for human review)",
    "why": "decision reason quoting the body",
    "body": "plain text body, ≤4000 chars",
    "v": "rescue | junk | review"
  }
]
```
> Multiple emails from the same sender are often the same category; the model can cluster by sender first, then confirm per email.

### 7.4 Stage 3 · Human reviews "uncertain" emails
Turn `v == "review"` emails into a **local board** where you view each body and click to decide:

```bash
python3 scripts/review_board.py \
  --verdicts=model-verdicts.json \
  --rules=review-rules.json \     # optional: auto-handle rule-matched, keep out of pending
  --title="My mailbox review" \
  --out=review-board.html
```

**How to open (very important)**: open `review-board.html` in a **system browser**.
- Recommended: `python3 scripts/serve.py --file=review-board.html` (auto-opens default browser)
- Or just double-click to open via `file://`

> ⚠️ **Do NOT open the review board in the WorkBuddy built-in preview panel!** Its internal `localStorage` is easy to lose, and copy/download are often blocked by the sandbox — once over 300 verdicts were lost this way (lesson in `references/gotchas.md` #1).

**Page operations**
- View each body, press `1` (keep / rescue) or `2` (clean / junk) to decide; progress auto-saves in the browser locally.
- After finishing, click "Export review results" to save `review-decisions.json`.
- **If copy/download is blocked**: click "Export as copyable text" button, select-all the JSON in the text box and copy, then paste it directly into the conversation.

Exported file structure:
```json
{
  "exported_at": "2026-...",
  "total": 1058,
  "decided": 1058,
  "decisions": [
    {"uid": 99, "folder": "Deleted Messages", "v": "rescue"},
    {"uid": 88, "folder": "INBOX", "v": "junk"}
  ]
}
```

### 7.5 Rule shortcut `review-rules.json` (optional, most convenient)
If you can specify rules like "a certain sender type always keep / restore", you can skip human review and auto-handle:

```json
{
  "rules": [
    {
      "id": "school",
      "label": "School mass mail",
      "action": "keep_in_place",
      "match": {"folder": "INBOX", "from_contains": ["ec-nantes.fr"]}
    },
    {
      "id": "restore",
      "label": "Billing system",
      "action": "restore_to_inbox",
      "match": {"folder": "Deleted Messages", "from_contains": ["billing@"]}
    }
  ]
}
```
- `keep_in_place`: judged "keep as-is", removed from pending.
- `restore_to_inbox`: judged "restore to INBOX", removed from pending.
- `from_contains` matches if any substring hits (case-insensitive).

### 7.6 Stage 4 · Merge & validate (read-only)
Merge **model verdicts + human decisions + rules**, produce an executable action list and do boundary checks:

```bash
python3 scripts/build_actions.py \
  --model=model-verdicts.json \
  --decisions=review-decisions.json \
  --rules=review-rules.json \
  --excluded=excluded.json \     # optional: folders/emails never touched
  --out=actions.json
```

The script prints a validation report: `duplicate / out-of-bounds (human judged a non-review email) / in exclusion list / invalid value / pending unjudged`.
**Resolve any anomaly before executing.**

Semantic rules:
- `rescue` = should end in **INBOX**
- `junk` = should end in **Deleted Messages** (recoverable, not permanent)
- Model `rescue`/`junk` emails auto-execute; `review` needs human `decision` override
- Rule-matched with `action` `keep_in_place` / `restore_to_inbox` are removed from pending

### 7.7 Stage 5 · Safe cleanup (recoverable move)
```bash
# 1) dry-run first to preview plan (no mailbox connection, no changes)
node scripts/apply_actions.cjs --actions=actions.json --dry-run

# 2) trial run of 5 to verify direction
node scripts/apply_actions.cjs --actions=actions.json --limit=5

# 3) full run (batch ≤200, verify source residue per batch, stop if residue>0, log to actions-log.jsonl)
node scripts/apply_actions.cjs --actions=actions.json
```

Before executing, list the full plan with risk warnings for the user to confirm.
- `--batch=N` adjusts emails per batch (default 200)
- `--log=path.jsonl` specifies rollback log path (default `actions-log.jsonl`)
- **Only folder moves throughout, never EXPUNGE the Trash**, so any email can be recovered from Trash.

### 7.8 Stage 6 · Independent double-check
```bash
node scripts/verify.cjs --actions=actions.json --model=model-verdicts.json
```
Confirm: moved-out source residue 0, restored source residue 0, untouched emails intact, copy at target folder tail, total counts conserved per folder.

---

## 8. Data contract quick reference

| File | Producer | Consumer | Key fields |
|---|---|---|---|
| `model-verdicts.json` | Model (Stage 2) | review_board / build_actions | `{uid, folder, v, body, why}` |
| `review-decisions.json` | Human (Stage 3) | build_actions | `{decisions:[{uid, folder, v}]}` |
| `review-rules.json` | User | review_board / build_actions | `{rules:[{id, action, match}]}` |
| `actions.json` | build_actions (Stage 4) | apply_actions / verify | `{actions:[{uid, folder, dest, key, v}]}` |
| `actions-log.jsonl` | apply_actions (Stage 5) | undo / verify | per-batch rollback record |

> **Composite key**: the two folders (INBOX / Deleted Messages) have independent UID spaces; cross-folder decisions always use composite key `I{uid}` / `D{uid}` to avoid mutual overwrite.

---

## 9. Safety & rollback

- **No permanent deletion**: all cleanup is "copy to target folder + mark source deleted"; deleted emails remain in the "Deleted" folder (Trash), always manually restorable.
- **Rollback log**: `actions-log.jsonl` records each batch's (uid, source folder, target folder); to undo, move back per the log.
- **Batch verification**: after each batch move, immediately re-check source folder residue; if residue > 0, stop immediately, never silently miss.
- **Independent check**: `verify.cjs` re-verifies via a different logic channel than the executor, confirming total conservation and no email vanished.
- **Exclusion list**: `--excluded=excluded.json` specifies `{items:[{key:"I123"}]}` etc.; these emails are never touched.

---

## 10. FAQ

**Q: I opened the review board in the WorkBuddy preview panel and lost the results. What now?**
A: This is the pitfall emphasized in §7.4. Always open it in a **system browser** (`serve.py` is easiest). If already lost, you can only redo that part — so save a backup immediately after exporting `review-decisions.json`.

**Q: iCloud won't connect / auth failed?**
A: Confirm you're using an **App-Specific Password**, not the Apple ID login password; confirm `cred.json`'s `host`/`port` are correct and `ICLOUD_CRED` points to it.

**Q: Can it be used for Gmail / enterprise mail?**
A: Yes. Just change `host`/`port`/`user`/`pass` in `cred.json` (Gmail needs an app password / OAuth per provider). Reading and decision logic are generic.

**Q: Script errors `Cannot find module 'imapflow'`?**
A: Run `npm install imapflow iconv-lite` in the **working directory**, and `cd` into it before running commands.

**Q: Want to stop halfway?**
A: Just Ctrl+C. Executed batches are recorded in `actions-log.jsonl`; unexecuted ones won't move. After stopping, use `verify.cjs` to check status, then decide whether to continue.

**Q: How to recover an important email wrongly moved to "Deleted"?**
A: Log into the webmail, go to the "Deleted" folder, manually move it back to INBOX (this skill never EXPUNGEs).

---

## 11. Customization & extension

- **Decision criteria**: the `rescue/junk/review` three-way split in Stage 2 can be adjusted to your preference (just change the model prompt; scripts only recognize these three enum values).
- **Rule file**: use `review-rules.json` to codify "keep / restore a sender", skipping human review — most convenient.
- **Exclusion list**: `excluded.json` protects emails you never want touched (e.g. certain archive folders).
- **Batch size / concurrency**: `apply_actions.cjs --batch`, `fetch_bodies.cjs --workers/--batch` are adjustable.

---

## 12. License & acknowledgements

This skill is packaged per the WorkBuddy user-level skill spec and may be freely copied, modified, and redistributed.
The core methodology comes from a real large-scale mailbox cleanup (7,000+ emails read one by one, 1,100+ human-reviewed); the lessons are distilled in `references/gotchas.md`.

*May your inbox be tidy from now on, with not a single important email lost.*
