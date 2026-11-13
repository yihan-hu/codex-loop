#!/usr/bin/env python3
"""Reuse an explicitly saved project scope; the user supplies only the next task."""
import argparse
import json
import pathlib
import re
import uuid

import conversation as driver

PROFILES = pathlib.Path(driver.BRIDGE['stateDirectory']) / 'conversation-projects.json'


def task_config(profile, request):
    request = request.strip()
    if not request:
        raise ValueError('Please enter a task')
    # This alias denotes the saved Mac transport, not a native Perplexity mention.
    request = re.sub(r'^@my\s+mac\s+', '', request, flags=re.I)
    if re.search(r'@epi\s*prose\b', request, re.I):
        raise ValueError('Full Epi Prose is not connected to this Q&A driver. Use its installed ChatGPT/Codex skill; do not substitute a generic writing loop.')
    config = driver.config_check(profile)
    config['goal'] = request
    config['first_prompt'] = (
        '执行这条用户任务：\n' + request +
        '\n/write 表示撰写，/revise 表示修改已有文件；其余自然语言按原意理解。'
        '先读取任务真正需要的授权材料，再实际保存产物。'
        '需要另一次模型审查或修订就返回 CONTINUE，并提出具体下一步；'
        '不能用空泛的“已检查”替代实际阅读和判断。'
        '完整达到用户目标后才能返回 DONE。缺少关键材料或需要用户决定则返回 NEEDS_USER。'
        '这不是完整 Epi Prose 技能，不能声称已执行其专门生产路线或独立角色审查。'
    )
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    save = commands.add_parser('save', help='Save the explicitly authorized config once')
    save.add_argument('name'); save.add_argument('config'); save.add_argument('--default', action='store_true')
    commands.add_parser('list')
    run = commands.add_parser('run'); run.add_argument('request'); run.add_argument('--project')
    args = parser.parse_args()
    settings = json.loads(PROFILES.read_text()) if PROFILES.exists() else {'projects': {}}
    if args.command == 'save':
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.name):
            raise ValueError('Use a short project name containing letters, digits, _ or -')
        config = driver.config_check(json.loads(pathlib.Path(args.config).read_text()))
        settings['projects'][args.name] = config
        if args.default:
            settings['default'] = args.name
        driver.write_json(PROFILES, settings)
        answer = {'saved': args.name, 'default': settings.get('default'), 'workspace': config['workspace'], 'allowed_files': config['allowed_files']}
    elif args.command == 'list':
        answer = {'default': settings.get('default'), 'projects': {name: {'workspace': c['workspace'], 'allowed_files': c['allowed_files']} for name, c in settings['projects'].items()}}
    else:
        project = args.project or settings.get('default')
        if not project or project not in settings['projects']:
            raise ValueError('First save an authorized project: shortcut.py save NAME CONFIG --default')
        config = task_config(settings['projects'][project], args.request)
        state = driver.ui('snapshot')
        if state['busy'] or state['text'] or state['input'] or not any(s in ['新建会话', 'New thread', 'New Thread'] for s in state['selected']):
            raise ValueError('Open an empty new Perplexity Q&A chat before starting')
        if config['connector'] not in state['connectors']:
            raise ValueError('Select '+config['connector']+' in the empty chat first')
        driver.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = driver.ROOT / ('request-'+uuid.uuid4().hex+'.json')
        driver.write_json(path, config)
        try:
            answer = driver.start(path, background=True)
        finally:
            path.unlink(missing_ok=True)
        answer['project'] = project
    print(json.dumps(answer, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
