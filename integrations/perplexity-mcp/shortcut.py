#!/usr/bin/env python3
"""Reuse an explicitly saved project scope; the user supplies only the next task."""
import argparse
import json
import pathlib
import re
import os
import uuid

import conversation as driver

PROFILES = pathlib.Path(driver.BRIDGE['stateDirectory']) / 'conversation-projects.json'


def task_config(profile, request):
    request = request.strip()
    if not request:
        raise ValueError('Please enter a task')
    # This alias denotes the saved Mac transport, not a native Perplexity mention.
    request = re.sub(r'^@my\s+mac(?=\s|@|/)\s*', '', request, flags=re.I)
    config = driver.config_check(profile)
    selected=re.match(r'^(?:@epi\s*prose\b|/skill:([a-z0-9-]+)\b)\s*',request,re.I)
    if selected:
        name=(selected.group(1) or 'epi-prose').lower()
        if name not in config.get('allowed_skills',[]):
            raise ValueError('Register the local Skill and grant it in this saved project before invocation')
        config['active_skill']=name
        config['skill_request']=request[selected.end():].strip()
        config['goal']=request
        config['first_prompt']=f'按实际本地 {name} 入口处理这条用户请求；首次完整读取当前 SKILL.md、ARCHITECTURE.md 及当前路线必需引用，再执行其原始路线。'
        return config
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
    register=commands.add_parser('register-skill');register.add_argument('name');register.add_argument('root');register.add_argument('--python',required=True)
    run = commands.add_parser('run'); run.add_argument('request'); run.add_argument('--project')
    args = parser.parse_args()
    settings = json.loads(PROFILES.read_text()) if PROFILES.exists() else {'projects': {}}
    if args.command == 'register-skill':
        root=pathlib.Path(args.root).expanduser().resolve(strict=True)
        interpreter=pathlib.Path(args.python).expanduser().absolute()
        if not re.fullmatch(r'[a-z0-9-]{1,64}',args.name) or not (root/'SKILL.md').is_file() or not (root/'ARCHITECTURE.md').is_file():
            raise ValueError('A named Skill with its actual entry and architecture is required')
        if not os.access(interpreter,os.X_OK):raise ValueError('Select the Skill registered Python interpreter')
        scripts=sorted(p.name for p in (root/'scripts').glob('*.py') if p.is_file() and p.resolve().is_relative_to(root))
        if not scripts:raise ValueError('No Python Skill entrypoints found')
        updated=dict(driver.BRIDGE)
        links={p.relative_to(root).as_posix():str(p.resolve(strict=True)) for p in root.rglob('*') if p.is_symlink() and p.exists()}
        updated.setdefault('localSkills',{})[args.name]={'root':str(root),'python':str(interpreter),'scripts':scripts+['@fetch','@extract'],'resource_links':links}
        driver.write_json(driver.HERE/'config.json',updated)
        answer={'registered_skill':args.name,'root':str(root),'python':str(interpreter),'script_count':len(scripts),'next':'Grant allowed_skills in the saved project and reload only this bridge HTTP service'}
    elif args.command == 'save':
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
