#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总模型审阅结论 + 人工决策 + 规则，生成最终动作清单（只读，不动邮件）。

输入:
  --model      模型审阅结论 JSON，数组，每项 {uid, folder, v:"rescue"|"junk"|"review", ...}
               （folder 为邮件当前所在文件夹；v 为模型判定）
  --decisions  (可选) 人工在审阅板导出的 review-decisions.json
               {decided, decisions:[{uid, folder, v:"rescue"|"junk"}]}
  --rules      (可选) 规则 JSON，匹配到的 review 邮件按 action 处理、不再需要人工
  --excluded   (可选) 排除清单 JSON {items:[{key:"I123"/"D456"}]}，这些邮件一律不动
  --out        (可选) 输出动作清单，默认 ./actions.json

语义:
  rescue = 最终应在 INBOX；junk = 最终应在 Deleted Messages（可恢复，非永久删除）
  模型判定 rescue/junk 的邮件自动执行；review 的邮件需人工 decision 覆盖；
  规则命中且 action 为 keep_in_place/restore_to_inbox 的从待审剔除。

输出 actions.json:
  {created_at, source_file, decided, validation:{...}, actions:[{uid,folder,dest,key,v,subject,from}]}
"""
import json, re, collections, datetime, argparse, os

ap = argparse.ArgumentParser()
ap.add_argument('--model', required=True)
ap.add_argument('--decisions')
ap.add_argument('--rules')
ap.add_argument('--excluded')
ap.add_argument('--out', default='./actions.json')
args = ap.parse_args()

model = json.load(open(args.model, encoding='utf-8'))
if isinstance(model, dict):
    model = model.get('rows') or model.get('decisions') or model.get('verdicts') or []
rules = {'rules': []}
if args.rules and os.path.exists(args.rules):
    try: rules = json.load(open(args.rules, encoding='utf-8'))
    except Exception: pass
excluded = {'items': []}
if args.excluded and os.path.exists(args.excluded):
    try: excluded = json.load(open(args.excluded, encoding='utf-8'))
    except Exception: pass
human = {'decisions': []}
if args.decisions and os.path.exists(args.decisions):
    try: human = json.load(open(args.decisions, encoding='utf-8'))
    except Exception: pass


def addr(r):
    m = re.search(r'<([^>]+)>', r.get('from') or '')
    return (m.group(1) if m else (r.get('from') or '')).lower()


def matched_rule(r):
    a = addr(r)
    for rule in rules.get('rules', []):
        if rule.get('action') not in ('keep_in_place', 'restore_to_inbox'):
            continue
        m = rule.get('match', {})
        if m.get('folder') and m['folder'] != r.get('folder'):
            continue
        toks = m.get('from_contains', [])
        if toks and not any(t.lower() in a for t in toks):
            continue
        return rule['id']
    return None


def key_of(x):
    return ('I' if x.get('folder') == 'INBOX' else 'D') + str(x['uid'])


# 全集：模型判定的所有邮件
universe = {key_of(r): r for r in model}
# review 集合（待人工）
review_keys = {key_of(r) for r in model if r.get('v') == 'review'}
# 规则命中的 review → 自动处理，移出待审
ruled_keys = {key_of(r) for r in model if r.get('v') == 'review' and matched_rule(r)}
excluded_keys = {x['key'] for x in excluded.get('items', [])}

human_map = {}
for x in human.get('decisions', []):
    human_map[key_of(x)] = x.get('v')

# 校验
all_keys = list(human_map.keys())
dup = [k for k, c in collections.Counter(all_keys).items() if c > 1]
not_in_review = [k for k in human_map if k not in review_keys]            # 越界：人工判了不该判的
illegal = [k for k, v in human_map.items() if v not in ('rescue', 'junk')]
in_excluded = [k for k in human_map if k in excluded_keys]
missing = review_keys - ruled_keys - set(human_map.keys())                # 待审但未判

print('=== 校验 ===')
print('全集:', len(universe), '| review:', len(review_keys),
      '| 规则处理:', len(ruled_keys), '| 排除:', len(excluded_keys))
print('人工决策条数:', len(human_map))
print('重复:', len(dup), '| 越界(非 review):', len(not_in_review),
      '| 落在排除清单:', len(in_excluded), '| 非法值:', len(illegal), '| 待审未判:', len(missing))
if not_in_review[:8]: print('  越界示例:', not_in_review[:8])
if illegal[:8]:       print('  非法示例:', illegal[:8])

# 合并最终 v
final = {}
for k, r in universe.items():
    v = r.get('v')
    if v in ('rescue', 'junk'):
        final[k] = v
    elif k in ruled_keys:
        final[k] = 'rescue' if (rules_action := next((ru['action'] for ru in rules['rules'] if ru['id'] == matched_rule(r)), None)) == 'restore_to_inbox' else 'keep'
    elif k in human_map:
        final[k] = human_map[k]
    else:
        final[k] = None  # 未决，保持不动

# 生成动作
TRASH = 'Deleted Messages'
actions = []
by_dir = collections.Counter()
for k, r in universe.items():
    v = final.get(k)
    src = r.get('folder')
    if v == 'rescue' and src != 'INBOX':
        dest = 'INBOX'
    elif v == 'junk' and src not in (TRASH, 'Junk'):
        dest = TRASH
    else:
        continue
    actions.append({'uid': r['uid'], 'folder': src, 'dest': dest, 'key': k, 'v': v,
                    'subject': r.get('subject'), 'from': r.get('from')})
    by_dir[src + ' -> ' + dest] += 1

print('\n=== 将执行的动作 ===')
for kk, c in by_dir.items():
    print(' ', kk, ':', c)
print(' 合计移动:', len(actions), '| 保持不动:', len(universe) - len(actions))

out = {
    'created_at': datetime.datetime.now().isoformat(timespec='seconds'),
    'source_model': args.model,
    'source_decisions': args.decisions,
    'total_emails': len(universe),
    'validation': {'duplicate': len(dup), 'not_in_review': len(not_in_review),
                   'in_excluded': len(in_excluded), 'illegal_v': len(illegal),
                   'undecided_review': len(missing)},
    'actions': actions,
}
json.dump(out, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('\n动作清单已写:', os.path.abspath(args.out))
