#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异议复核维护脚本 —— 离线、人工触发，不在 Web 请求流程里运行。

用户在前端对某条风险判定提出"异议"后，记录会写入 data/disputes.json，
状态默认为 pending。管理员定期运行这个脚本人工复核，决定要不要据此修正规则：

  列出待处理异议：
    python3 manage_disputes.py list
    python3 manage_disputes.py list --status pending

  查看单条异议详情：
    python3 manage_disputes.py show <dispute_id>

  复核后采取的动作（只有人工执行这个命令才会改变规则，程序不会自动改）：
    # 异议成立，关键词太宽泛导致误报，从该规则关键词里删掉
    python3 manage_disputes.py resolve <dispute_id> --action remove-keyword --keyword "明显倾斜" --note "误报，词太泛"

    # 异议反映规则库漏判了一个同义说法，补充关键词
    python3 manage_disputes.py resolve <dispute_id> --action add-keyword --keyword "陪标" --note "漏判，补充同义词"

    # 异议成立，但问题更严重，整条规则都该停用
    python3 manage_disputes.py resolve <dispute_id> --action disable-rule --note "规则设计有问题"

    # 复核后认为异议不成立，判定本来就是对的
    python3 manage_disputes.py resolve <dispute_id> --action reject --note "复核后维持原判"

    # 仅记录复核结果，不改变规则（比如只是态度确认，无需调整关键词）
    python3 manage_disputes.py resolve <dispute_id> --action keep --note "已知晓，暂不调整"

所有"remove-keyword / add-keyword / disable-rule"动作都会写入
data/rule_overrides.json，下次启动 Flask 应用时 RiskRules 会自动加载生效。
"""

import argparse
import json
import os
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DISPUTES_FILE = os.path.join(BASE_DIR, 'data', 'disputes.json')
OVERRIDES_FILE = os.path.join(BASE_DIR, 'data', 'rule_overrides.json')


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cmd_list(args):
    disputes = load_json(DISPUTES_FILE, [])
    if args.status:
        disputes = [d for d in disputes if d.get('status') == args.status]

    if not disputes:
        print('没有符合条件的异议记录。')
        return

    for d in disputes:
        print(f"[{d['status']:>8}] {d['id']}  {d['rule_id']}  {d.get('rule_name', '')}"
              f"  文件: {d.get('filename', '(无)')}  时间: {d['created_at']}")
        print(f"           理由: {d['reason']}")
        for loc in d.get('locations', [])[:3]:
            print(f"           命中: {loc.get('location', '')} 关键词「{loc.get('keyword', '')}」"
                  f" 上下文: ……{loc.get('context', '')}……")


def cmd_show(args):
    disputes = load_json(DISPUTES_FILE, [])
    target = next((d for d in disputes if d['id'] == args.dispute_id), None)
    if target is None:
        print(f"未找到异议记录: {args.dispute_id}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(target, ensure_ascii=False, indent=2))


def cmd_resolve(args):
    disputes = load_json(DISPUTES_FILE, [])
    target = next((d for d in disputes if d['id'] == args.dispute_id), None)
    if target is None:
        print(f"未找到异议记录: {args.dispute_id}", file=sys.stderr)
        sys.exit(1)

    rule_id = target['rule_id']
    overrides = load_json(OVERRIDES_FILE, {
        'removed_keywords': {}, 'added_keywords': {}, 'disabled_rules': []
    })

    if args.action == 'remove-keyword':
        if not args.keyword:
            print('remove-keyword 需要 --keyword 参数', file=sys.stderr)
            sys.exit(1)
        overrides['removed_keywords'].setdefault(rule_id, [])
        if args.keyword not in overrides['removed_keywords'][rule_id]:
            overrides['removed_keywords'][rule_id].append(args.keyword)

    elif args.action == 'add-keyword':
        if not args.keyword:
            print('add-keyword 需要 --keyword 参数', file=sys.stderr)
            sys.exit(1)
        overrides['added_keywords'].setdefault(rule_id, [])
        if args.keyword not in overrides['added_keywords'][rule_id]:
            overrides['added_keywords'][rule_id].append(args.keyword)

    elif args.action == 'disable-rule':
        if rule_id not in overrides['disabled_rules']:
            overrides['disabled_rules'].append(rule_id)

    elif args.action in ('reject', 'keep'):
        pass  # 不改动规则，只更新异议状态

    else:
        print(f"未知 action: {args.action}", file=sys.stderr)
        sys.exit(1)

    if args.action in ('remove-keyword', 'add-keyword', 'disable-rule'):
        save_json(OVERRIDES_FILE, overrides)

    target['status'] = 'resolved' if args.action != 'reject' else 'rejected'
    target['applied_action'] = args.action
    target['applied_keyword'] = args.keyword
    target['review_note'] = args.note or ''
    target['updated_at'] = datetime.now().isoformat(timespec='seconds')

    save_json(DISPUTES_FILE, disputes)
    print(f"已复核 {args.dispute_id}: action={args.action}, rule_id={rule_id}")
    if args.action in ('remove-keyword', 'add-keyword', 'disable-rule'):
        print('规则修正已写入 data/rule_overrides.json，重启 Flask 应用后生效。')


def main():
    parser = argparse.ArgumentParser(description='异议复核维护脚本')
    sub = parser.add_subparsers(dest='command', required=True)

    p_list = sub.add_parser('list', help='列出异议记录')
    p_list.add_argument('--status', choices=['pending', 'resolved', 'rejected'])
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser('show', help='查看单条异议详情')
    p_show.add_argument('dispute_id')
    p_show.set_defaults(func=cmd_show)

    p_resolve = sub.add_parser('resolve', help='复核并应用规则修正')
    p_resolve.add_argument('dispute_id')
    p_resolve.add_argument('--action', required=True,
                            choices=['remove-keyword', 'add-keyword', 'disable-rule', 'reject', 'keep'])
    p_resolve.add_argument('--keyword')
    p_resolve.add_argument('--note')
    p_resolve.set_defaults(func=cmd_resolve)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
