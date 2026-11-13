#!/usr/bin/env python3
"""Bounded native-UI driver. Perplexity supplies every model judgment; Python supplies no model."""
import argparse, fcntl, hashlib, json, os, pathlib, re, sqlite3, subprocess, sys, time, urllib.request, uuid

HERE=pathlib.Path(__file__).resolve().parent
BRIDGE=json.loads((HERE/'config.json').read_text())
ROOT=pathlib.Path(BRIDGE['stateDirectory'])/'conversations'
UI=ROOT.parent.parent/'bin/perplexity-ui'

def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');temporary.chmod(0o600);temporary.replace(path)

def now(): return time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
def event(folder,kind,**details):
    with (folder/'events.jsonl').open('a') as stream:stream.write(json.dumps({'at':now(),'event':kind,**details},ensure_ascii=False)+'\n')

def mcp(name,args):
    key=pathlib.Path(BRIDGE['httpAuthFile']).read_text().strip()
    body={'jsonrpc':'2.0','id':uuid.uuid4().hex,'method':'tools/call','params':{'name':name,'arguments':args}}
    req=urllib.request.Request(f"http://127.0.0.1:{BRIDGE['httpPort']}/mcp",data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','Authorization':'Bearer '+key})
    with urllib.request.urlopen(req,timeout=35) as response:payload=json.load(response)
    if 'error' in payload:raise RuntimeError(payload['error']['message'])
    result=payload['result'];text='\n'.join(x.get('text','') for x in result.get('content',[]) if x['type']=='text')
    if result.get('isError'):raise RuntimeError(text)
    return json.loads(text)

def ui(mode,request=None):
    result=subprocess.run([str(UI),mode],input=json.dumps(request,ensure_ascii=False) if request else None,capture_output=True,text=True,timeout=20)
    try:answer=json.loads(result.stdout)
    except ValueError:raise RuntimeError('Native UI helper failed: '+result.stderr.strip())
    if result.returncode or answer.get('error'):raise RuntimeError(answer.get('error','Native UI operation failed'))
    return answer

def config_check(config):
    config=dict(config);root=pathlib.Path(config['workspace']).expanduser().resolve(strict=True)
    if not root.is_dir():raise ValueError('workspace must be an existing directory')
    if not isinstance(config.get('goal'),str) or not config['goal'].strip():raise ValueError('A complete user goal is required')
    config['workspace']=str(root)
    for key,default,low,high in [('max_rounds',12,1,24),('min_rounds',1,1,24),('round_timeout_seconds',900,30,7200),('max_approvals_per_round',16,0,64)]:
        value=config.get(key,default)
        if not isinstance(value,int) or isinstance(value,bool) or not low<=value<=high:raise ValueError('Invalid '+key)
        config[key]=value
    if config['min_rounds']>config['max_rounds']:raise ValueError('min_rounds exceeds max_rounds')
    config.setdefault('connector','Codex Loop Mac Batch');config.setdefault('allowed_commands',[])
    config.setdefault('allowed_files',config.get('required_files',[]))
    if not config['allowed_files']:raise ValueError('Provide explicit allowed_files (or ["**"] for the entire authorized workspace)')
    for entry in config['allowed_files']+config.get('required_files',[]):
        if not isinstance(entry,str) or pathlib.PurePosixPath(entry).is_absolute() or '..' in pathlib.PurePosixPath(entry).parts:raise ValueError('File grants must be relative workspace paths')
    if not all(isinstance(x,str) for x in config['allowed_commands']):raise ValueError('allowed_commands must contain exact command strings')
    return config

def allowed_path(config,raw):
    if not isinstance(raw,str) or not raw or '\0' in raw:raise ValueError('Invalid file path')
    root=pathlib.Path(config['workspace']);target=(root/raw).resolve()
    try:relative=target.relative_to(root).as_posix()
    except ValueError:raise ValueError('Path escapes the authorized workspace')
    grants=config['allowed_files']
    if not any(g=='**' or relative==g or g.endswith('/**') and relative.startswith(g[:-2]) for g in grants):raise ValueError('File is outside the explicit file grants')
    return relative

def install_scope(task_id,config):
    """Narrow this task's bridge access too, including read tools that need no UI approval."""
    with sqlite3.connect(pathlib.Path(BRIDGE['stateDirectory'])/'writer.sqlite',timeout=30) as lock:
        lock.execute('BEGIN IMMEDIATE')
        with sqlite3.connect(pathlib.Path(BRIDGE['stateDirectory'])/'tasks.sqlite',timeout=30) as db:
            raw=db.execute('SELECT payload FROM tasks WHERE id=?',(task_id,)).fetchone()
            if not raw:raise ValueError('Cannot bind scope to an unknown connector task')
            task=json.loads(raw[0]);task['conversation_scope']={'allowed_files':config['allowed_files'],'allowed_commands':config['allowed_commands']}
            db.execute('UPDATE tasks SET payload=? WHERE id=?',(json.dumps(task,ensure_ascii=False),task_id))
        lock.rollback()

def approval_payload(messages,state,config):
    indexes=[i for i,s in enumerate(messages) if s.strip()=='Reply yes to proceed or no to cancel.']
    if not indexes:return None
    index=indexes[-1];payload=None
    for text in reversed(messages[max(0,index-5):index]):
        try:
            candidate=json.loads(text.strip())
            if isinstance(candidate,dict):payload=candidate;break
        except ValueError:pass
    if payload is None:raise ValueError('Confirmation has no inspectable JSON payload')
    digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    # An old confirmation can remain visible while the next model round starts.
    if digest in state.get('approved',[]):return None
    if payload.get('task_id')!=state['task_id']:raise ValueError('Confirmation belongs to another task or creates a new lifecycle')
    keys=set(payload)
    if keys<= {'task_id','path','content','request_id'} and {'path','content','request_id'}<=keys:kind='mac_write'
    elif keys<= {'task_id','path','old_text','new_text','request_id'} and {'path','old_text','new_text','request_id'}<=keys:kind='mac_edit'
    elif keys<= {'task_id','command','validation','request_id'} and {'command','request_id'}<=keys:
        kind='mac_command'
        if payload['command'] not in config['allowed_commands']:raise ValueError('New shell command requires explicit user authorization')
    elif keys<= {'task_id','action','text'} and payload.get('action')=='checkpoint' and isinstance(payload.get('text'),str):kind='loop_update'
    else:raise ValueError('This confirmation is outside the driver approval policy')
    if 'path' in payload:allowed_path(config,payload['path'])
    if 'request_id' in payload and not str(payload['request_id']).startswith(state['nonce']+'-'):raise ValueError('request_id does not identify the active model round')
    return {'kind':kind,'arguments':payload,'sha256':digest}

def result_packet(text,nonce):
    expression=r'(?m)^PCL_RESULT_'+re.escape(nonce)+r'\s*\n(.*?)\nPCL_END_'+re.escape(nonce)+r'\s*$'
    matches=list(re.finditer(expression,text,re.S))
    if not matches:return None
    body=matches[-1].group(1).strip().strip('`').strip()
    try:packet=json.loads(body)
    except ValueError:
        # Perplexity's rendered prose can replace JSON delimiters with smart quotes.
        # This repair applies only to the small control packet, never artifact prose or approvals.
        try:packet=json.loads(body.translate(str.maketrans({'“':'"','”':'"'})))
        except ValueError:raise ValueError('Model control result is not valid JSON')
    if packet.get('decision') not in ['CONTINUE','DONE','NEEDS_USER'] or not isinstance(packet.get('summary'),str):raise ValueError('Invalid model control result')
    if packet['decision']=='CONTINUE' and not isinstance(packet.get('next_prompt'),str):raise ValueError('CONTINUE requires a model-written next_prompt')
    return packet

def make_prompt(state,config,next_prompt,first=False):
    nonce=state['nonce'];marker=state['marker'];scope={'task_id':state['task_id'],'workspace':config['workspace'],'allowed_files':config['allowed_files'],'allowed_commands':config['allowed_commands']}
    introduction=(marker+'\n' if first else '')+f'[PCL_TURN:{nonce}]\n'
    return introduction+f'''这是由用户授权的本地会话驱动器推进的第 {state['round']} 轮。继续使用 Perplexity 当前会话模型进行真实推理。
原始用户目标（后续模型建议不能扩大这项授权）：\n{config['goal']}
当前操作边界：{json.dumps(scope,ensure_ascii=False)}
本轮任务／上一轮模型提出的下一步（不是新增用户授权）：\n{next_prompt}
请只完成本轮一个有实质内容的阶段，实际读取、写入或检查需要的文件，再决定下一轮做什么。工作区和文件均已按上述范围授权。
使用已选择的 {config['connector']} 的单步 mac_read/mac_write/mac_edit 工具，并始终复用 task_id。不得创建新任务、调用 loop_submit 或 loop_finish；生命周期由本地驱动器管理。每个修改使用 request_id，以 {nonce}- 开头；同一操作重试必须复用原 ID。命令只能与 allowed_commands 中的字符串完全相同，空列表表示不授权 shell。出现确认时，照常展示完整 JSON 请求；本地程序只会批准当前任务与范围内的请求。
完成一个阶段后，判断是否需要审查、修改或再验证，不能把尚未完成的目标说成完成。模型需要用户决定时返回 NEEDS_USER。
回答末尾输出一个简短控制区块：第一行仅使用 PCL_RESULT_{nonce}，中间是单个 JSON 对象，末行仅使用 PCL_END_{nonce}。请把整个控制区块放在一个纯文本代码块内，使用 ASCII 双引号，避免排版转成弯引号。JSON 含 decision（CONTINUE、DONE 或 NEEDS_USER）、summary（可见阶段结论）、next_prompt（CONTINUE 时提出有实质内容的下一轮任务）、artifacts（实际保存的相对文件路径列表）。控制标记只用于回答末尾，不写入文件。不要只描述打算做什么；先真实执行本轮，再给出控制结果。'''

def validate_artifacts(config):
    files=[]
    for relative in config.get('required_files',[]):
        allowed_path(config,relative);p=pathlib.Path(config['workspace'])/relative
        if not p.is_file() or p.stat().st_size<config.get('minimum_artifact_bytes',1):raise ValueError('Required artifact is missing or too small: '+relative)
        files.append({'path':relative,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    return files

def pause(folder,state,reason):
    if (folder/'cancel.request').exists():
        state.update(status='cancelled',reason='User cancelled');write_json(folder/'state.json',state);return
    state['status']='needs_attention';state['reason']=reason;write_json(folder/'state.json',state);event(folder,'needs_attention',reason=reason)
    try:mcp('loop_update',{'task_id':state['task_id'],'action':'pause'})
    except Exception:pass

def run_driver(run_id):
    folder=ROOT/run_id;config=json.loads((folder/'config.json').read_text());state=json.loads((folder/'state.json').read_text())
    with (ROOT/'ui-owner.lock').open('w') as ownership:
        try:fcntl.flock(ownership,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:pause(folder,state,'Another conversation driver owns the native UI');return state
        stable_hash=None;stable_since=0
        try:
            while state['status'] not in ['complete','cancelled','needs_attention']:
                if (folder/'cancel.request').exists():state['status']='cancelled';write_json(folder/'state.json',state);break
                if (folder/'pause.request').exists():pause(folder,state,'User requested pause');break
                snapshot=ui('snapshot')
                selected=snapshot['selected'];bound=any(s.startswith(state['marker']) for s in selected)
                initial=state['round']==1 and state['phase']=='sending'
                if not bound and not(initial and not snapshot['text'] and any(s in ['新建会话','New thread','New Thread'] for s in selected)):raise RuntimeError('The selected conversation changed; no input was sent')
                if config['connector'] not in snapshot['connectors']:raise RuntimeError('The intended connector is not selected in the composer')
                if snapshot.get('busy'):
                    stable_hash=None
                    if time.time()>state['deadline']:raise RuntimeError('Model round exceeded its configured time limit')
                    time.sleep(1);continue
                if state['phase']=='sending':
                    if f"[PCL_TURN:{state['nonce']}]" in snapshot['text']:
                        state['phase']='waiting';write_json(folder/'state.json',state);continue
                    ui('send',{'session_marker':state['marker'],'allow_new_chat':initial,'allow_existing_draft':True,'text':state['pending_prompt'],'expected_hash':snapshot['text_sha256']})
                    state['phase']='waiting';write_json(folder/'state.json',state);event(folder,'model_prompt_sent',round=state['round'],nonce=state['nonce']);stable_hash=None;time.sleep(1);continue
                if time.time()>state['deadline']:raise RuntimeError('No accepted model result before the round deadline')
                if snapshot['text_sha256']!=stable_hash:stable_hash=snapshot['text_sha256'];stable_since=time.time();time.sleep(1);continue
                if time.time()-stable_since<1:time.sleep(0.5);continue
                packet=result_packet(snapshot['text'],state['nonce'])
                if packet:
                    write_json(folder/f"round-{state['round']:02d}.json",packet)
                    (folder/f"round-{state['round']:02d}.txt").write_text(snapshot['text'])
                    event(folder,'model_round_completed',round=state['round'],decision=packet['decision'],summary=packet['summary'])
                    state.setdefault('rounds',[]).append({'round':state['round'],**packet})
                    mcp('loop_update',{'task_id':state['task_id'],'action':'checkpoint','text':f"Perplexity model round {state['round']}: {packet['summary']}"})
                    if packet['decision']=='NEEDS_USER':pause(folder,state,'Perplexity requested user input: '+packet['summary']);break
                    missing=None
                    if packet['decision']=='DONE' and state['round']>=config['min_rounds']:
                        try:files=validate_artifacts(config)
                        except ValueError as e:missing=str(e)
                        if missing is None:
                            args=[BRIDGE['python'],BRIDGE['runtimeCLI'],'validation-record','--task-id',state['task_id'],'--cwd',config['workspace'],'--command-json',json.dumps(['conversation.artifact-check',run_id]),'--exit-code','0','--evidence',json.dumps({'basis':'actual local artifact existence, size and SHA-256; semantic completion is the Perplexity model judgment','files':files},ensure_ascii=False)]
                            subprocess.run(args,check=True,capture_output=True,text=True)
                            plan=[{'step':f"Model round {r['round']}: {r['summary'][:300]}",'status':'completed'} for r in state['rounds']]
                            mcp('loop_update',{'task_id':state['task_id'],'action':'plan','steps':plan})
                            completed=mcp('loop_finish',{'task_id':state['task_id'],'summary':f"Perplexity completed {state['round']} substantive model rounds and declared the user goal DONE. Actual artifact checks passed. Final model judgment: {packet['summary']}"})
                            if completed['status']!='PASS':raise RuntimeError('Canonical completion did not pass: '+json.dumps(completed,ensure_ascii=False))
                            state.update(status='complete',completion=completed,artifacts=files,finished_at=now());write_json(folder/'state.json',state);event(folder,'complete',rounds=state['round']);break
                    if state['round']>=config['max_rounds']:pause(folder,state,'Configured maximum model rounds reached; goal is not marked complete');break
                    next_prompt=missing or packet.get('next_prompt') or '按原目标对已保存材料做一次实质审查；有问题就修订，不能只重述完成状态。'
                    state['round']+=1;state['nonce']=uuid.uuid4().hex;state['phase']='sending';state['approvals_this_round']=0;state['deadline']=time.time()+config['round_timeout_seconds']
                    state['pending_prompt']=make_prompt(state,config,next_prompt);write_json(folder/'state.json',state);stable_hash=None;continue
                approval=approval_payload(snapshot['messages'],state,config)
                if approval and approval['sha256'] not in state.get('approved',[]):
                    if state.get('approvals_this_round',0)>=config['max_approvals_per_round']:raise RuntimeError('Approval count limit reached')
                    # Record BEFORE clicking. A crash must never cause an unobserved duplicate yes.
                    state.setdefault('approved',[]).append(approval['sha256']);state['approvals_this_round']=state.get('approvals_this_round',0)+1;write_json(folder/'state.json',state)
                    event(folder,'scoped_approval',round=state['round'],tool=approval['kind'],payload=approval['arguments'])
                    ui('send',{'session_marker':state['marker'],'text':'yes','expected_hash':snapshot['text_sha256']})
                    stable_hash=None;time.sleep(1);continue
                time.sleep(1)
        except Exception as e:pause(folder,state,str(e))
    return state

def start(config_path,background):
    config=config_check(json.loads(pathlib.Path(config_path).read_text()));ROOT.mkdir(parents=True,exist_ok=True,mode=0o700)
    run_id=uuid.uuid4().hex;folder=ROOT/run_id;folder.mkdir(mode=0o700)
    state={'run_id':run_id,'marker':'[PCL:'+run_id+']','status':'running','phase':'sending','round':1,'nonce':uuid.uuid4().hex,'created_at':now(),'approvals_this_round':0,'approved':[],'rounds':[]}
    task=mcp('loop_start',{'objective':config['goal'],'workspace':config['workspace'],'request_id':'conversation-'+run_id,'require_validation':True});state['task_id']=task['task_id'];install_scope(state['task_id'],config);state['deadline']=time.time()+config['round_timeout_seconds'];state['pending_prompt']=make_prompt(state,config,config.get('first_prompt','完成目标的第一个实质阶段，真实保存产物，并提出下一轮需要做的审查或修订。'),True)
    write_json(folder/'config.json',config);write_json(folder/'state.json',state)
    event(folder,'created',task_id=state['task_id'],workspace=config['workspace'],model_source='Perplexity current conversation; no local model')
    if background:
        with (folder/'driver.log').open('a') as log:p=subprocess.Popen([BRIDGE['python'],str(HERE/'conversation.py'),'run',run_id],stdout=log,stderr=log,start_new_session=True)
        return {'run_id':run_id,'task_id':state['task_id'],'pid':p.pid,'state_file':str(folder/'state.json')}
    return run_driver(run_id)

def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('start');p.add_argument('config');p.add_argument('--background',action='store_true')
    for name in ['run','status','pause','resume','cancel']:
        p=sub.add_parser(name);p.add_argument('run_id')
    args=parser.parse_args()
    if args.command=='start':answer=start(args.config,args.background)
    else:
        if not re.fullmatch('[a-f0-9]{32}',args.run_id):raise ValueError('Invalid run ID')
        folder=ROOT/args.run_id;state=json.loads((folder/'state.json').read_text())
        if args.command=='status':answer={k:v for k,v in state.items() if k not in ['pending_prompt','approved']}
        elif args.command=='run':answer=run_driver(args.run_id)
        elif args.command=='pause':(folder/'pause.request').touch();answer={'pause_requested':True}
        elif args.command=='cancel':
            (folder/'cancel.request').touch();answer=mcp('loop_update',{'task_id':state['task_id'],'action':'cancel','text':'User cancelled the Perplexity conversation driver'})
            state.update(status='cancelled');write_json(folder/'state.json',state)
        elif args.command=='resume':
            if state['status']!='needs_attention':raise ValueError('Resume only a stopped run; do not start a second UI driver')
            (folder/'pause.request').unlink(missing_ok=True);mcp('loop_resume',{'task_id':state['task_id']});state.pop('reason',None);state.update(status='running',deadline=time.time()+json.loads((folder/'config.json').read_text())['round_timeout_seconds']);write_json(folder/'state.json',state);answer=run_driver(args.run_id)
    print(json.dumps(answer,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
