"""Native Perplexity actor contexts. Code transports paths; the model judges content."""
import json
import pathlib
import time
import uuid


def actor_prompt(state, config, instruction, first=False):
    actor = config['_actor']
    prefix = (state['marker']+'\n' if first else '')+f"[PCL_TURN:{state['nonce']}]\n"
    return prefix+f'''你是独立 Perplexity 阶段会话，真实 actor_id={actor['actor_id']}。你没有父会话历史，也不得请求父会话的科学结论。
当前角色：{actor['role']}。本轮 task_id={state['task_id']}，工作目录={config['workspace']}。
只读取并执行这个完整规范输入：{actor['input_path']}。
使用 skill_read(location=workspace) 完整读取规范 packet，跟随 next_offset。若 manifest_path={actor.get('manifest_path')} 非空，先读取该 manifest，再按顺序读完全部分块，以无损分块接收完整 packet，无需重复读取整份原文件；记录实际读过的 part 文件名。packet 内 artifact_ref.read_full=true 的文件仍必须逐个读完。不得把输入摘要当作完整材料。
只按 packet 的 instruction、output_contract 和 result_contract 判断，不读取 SKILL.md、ARCHITECTURE.md、其他阶段结果或父会话。即使你可以搜索到此前会话，也不得用它们代替指定材料。文献检索使用 Perplexity 当前搜索能力，并遵守 packet 的来源、全文与存档要求；不足时如实报告，不编造已读全文。
真实结果仅保存到预留路径 {actor['result_path']}，或 packet 明确要求的候选文件/文献快照。使用 mac_write/mac_edit 或已登记的 skill_run。所有修改 request_id 以 {state['nonce']}- 开头；重试保持原 ID。不得调用 loop_submit、loop_start、loop_finish，不得派生其他 actor。
如果 packet 要求 check-work 且提供了 state_path，先把候选写到 run 内另一文件，再用 skill_run 调用 epi_prose_runtime_v3.py check-work；最多三次检查，保留其真实状态，最终仍由 submit-work 权威校验。当前 state_path={actor.get('state_path')}。
这次续接指令（首次为空；只用于同一阶段修复）：{instruction}
保存后，回答末尾只给控制代码块，不回传科学正文给父会话。第一行仅为 PCL_RESULT_{state['nonce']}，中间为单个 JSON 对象，末行仅为 PCL_END_{state['nonce']}。
JSON 含 decision=DONE、summary="WROTE {actor['result_path']}"、artifacts（实际保存的路径列表）、parts_read（实际读过的分块文件名列表）。
若本阶段还需要一次问答继续读取或修复，可返回 CONTINUE 和具体 next_prompt；无法完成则 NEEDS_USER。标记只用于回答，不写进结果文件。'''


def request_metadata(driver, config, request):
    if not config.get('allowed_skills'):
        raise ValueError('No local Skill actor capability was granted')
    if not isinstance(request, dict):
        raise ValueError('SPAWN requires actor metadata')
    for key in ['input_path', 'result_path']:
        driver.allowed_path(config, request[key])
    root = pathlib.Path(config['workspace'])
    source = (root/request['input_path']).resolve(strict=True)
    target = (root/request['result_path']).resolve()
    if source == target or not source.is_file():
        raise ValueError('Actor input and output must be distinct files')
    if target.exists():
        raise ValueError('A new actor cannot adopt an already-existing result as its own work')
    packet = json.loads(source.read_text())  # Transport validation only; never sent to parent.
    submission = packet.get('semantic_result_submission') or {}
    reserved = submission.get('result_path')
    if reserved and pathlib.Path(reserved).resolve() != target:
        raise ValueError('Actor output differs from the runtime-reserved path')
    state_path = request.get('state_path')
    if state_path:
        driver.allowed_path(config, state_path)
        state_path=str((root/state_path).resolve(strict=True))
    manifest_path=request.get('manifest_path')
    if manifest_path:
        driver.allowed_path(config,manifest_path)
        manifest_path=str((root/manifest_path).resolve(strict=True))
    return {'input_path': str(source), 'result_path': str(target),
            'state_path': state_path,'manifest_path':manifest_path,'role': submission.get('role') or packet.get('stage') or 'isolated-task',
            'reuse_actor_id': submission.get('reuse_subagent_id'),
            'isolation': submission.get('logical_isolation', 'FRESH_SUBAGENT_REQUIRED')}


def dispatch(driver, folder, parent, config, request):
    """Resumable nested dispatch. Parent receives only actor identity/path/read receipts."""
    pending = parent.get('pending_actor')
    if pending:
        child_id = pending['run_id']
        child_folder = driver.ROOT/child_id
        child = json.loads((child_folder/'state.json').read_text())
        child_config = json.loads((child_folder/'config.json').read_text())
    else:
        metadata = request_metadata(driver, config, request)
        actors = parent.setdefault('actors', {})
        if len(actors) >= config.get('max_actors', 256):
            raise ValueError('Configured isolated actor limit reached')
        previous = actors.get(metadata['reuse_actor_id'])
        if previous and previous['role'] != metadata['role']:
            raise ValueError('An actor cannot be reused across different roles')
        reuse = previous and metadata['isolation'] in ['ROLE_SCOPED_REUSE', 'SAME_ACTOR_CONTRACT_REPAIR']
        child_id = previous['run_id'] if reuse else uuid.uuid4().hex
        child_folder = driver.ROOT/child_id
        # A missing tab is a concrete unavailable original context, never an invented reuse.
        if reuse:
            try:
                driver.ui('select', {'from_marker':parent['marker'],'session_marker':'[PCL:'+child_id+']'})
                driver.ui('select', {'from_marker':'[PCL:'+child_id+']','session_marker':parent['marker']})
            except RuntimeError:
                child_id = uuid.uuid4().hex; child_folder = driver.ROOT/child_id; reuse = False
        metadata['actor_id'] = 'perplexity:'+child_id
        child_config = dict(config, goal='Only the runtime-issued isolated task', required_files=[metadata['result_path']],
                            min_rounds=1, max_rounds=12, _actor=metadata,
                            control_run_id=config.get('control_run_id',parent['run_id']))
        child_folder.mkdir(exist_ok=True, mode=0o700)
        old = json.loads((child_folder/'state.json').read_text()) if reuse else {}
        child = {'run_id':child_id,'marker':'[PCL:'+child_id+']','task_id':parent['task_id'],
                 'status':'running','phase':'sending','round':1,'nonce':uuid.uuid4().hex,
                 'created_at':driver.now(),'approvals_this_round':0,'approved':old.get('approved',[]),
                 'rounds':[],'segment':old.get('segment',0)+1,'deadline':time.time()+config['round_timeout_seconds']}
        child['pending_prompt'] = actor_prompt(child,child_config,'',first=not reuse)
        driver.write_json(child_folder/'config.json', child_config)
        driver.write_json(child_folder/'state.json', child)
        driver.event(child_folder,'actor_created',actor_id=metadata['actor_id'],role=metadata['role'],reused=bool(reuse))
        actors[metadata['actor_id']] = {'run_id':child_id,'role':metadata['role']}
        parent['pending_actor'] = {'run_id':child_id,'reused':bool(reuse)}
        driver.write_json(folder/'state.json',parent)
    metadata = child_config['_actor']
    if child['status'] != 'actor_complete':
        if child['status']=='needs_attention':
            child.update(status='running',deadline=time.time()+config['round_timeout_seconds'])
            child.pop('reason',None);driver.write_json(child_folder/'state.json',child)
            visible=driver.ui('snapshot')
            if any(x.startswith(child['marker']) for x in visible['selected']):
                prior=driver.result_packet(driver.answer_text(visible,child['nonce']),child['nonce'])
                if prior and prior['decision']=='NEEDS_USER':
                    child['nonce']=uuid.uuid4().hex;child['phase']='sending';child['round']+=1
                    child['pending_prompt']=actor_prompt(child,child_config,'外层运行时已显式恢复。继续同一个输入和预留结果；没有新增科学决定或权限。若仍需真实作者决定，请再次返回 NEEDS_USER。')
                    driver.write_json(child_folder/'state.json',child)
        selected = driver.ui('snapshot')['selected']
        if not any(x.startswith(child['marker']) for x in selected):
            if parent['pending_actor']['reused'] or child['phase']!='sending':
                driver.ui('select', {'from_marker':parent['marker'],'session_marker':child['marker']})
            else:
                observed=driver.ui('new', {'from_marker':parent['marker'],'connector':config['connector'],'incognito':True})
                if not observed.get('incognito_verified'):raise RuntimeError('Actor Incognito mode was not verified')
                child_config['_actor']['incognito_verified']=True
                driver.write_json(child_folder/'config.json',child_config)
        if child['phase']=='sending':
            child['deadline']=time.time()+config['round_timeout_seconds'];driver.write_json(child_folder/'state.json',child)
        child = driver.run_driver(child_id,ui_owned=True)
    if child['status'] not in ['actor_complete','actor_needs_user']:
        raise RuntimeError('Isolated actor stopped: '+child.get('reason',child['status']))
    if not any(x.startswith(parent['marker']) for x in driver.ui('snapshot')['selected']):
        driver.ui('select', {'from_marker':child['marker'],'session_marker':parent['marker']})
    receipt = {'actor_id':metadata['actor_id'],'result_path':metadata['result_path'],
               'parts_read':child['rounds'][-1].get('parts_read',[]),'status':'WROTE' if child['status']=='actor_complete' else 'NEEDS_USER',
               'reused_context':parent['pending_actor']['reused'],
               'incognito_verified':metadata.get('incognito_verified',False)}
    if child['status']=='actor_needs_user':receipt['question']=child['rounds'][-1]['summary']
    else:driver.record_actor(parent['task_id'],metadata,receipt)
    driver.event(folder,'actor_completed',**receipt)
    parent['actor_receipt']=receipt;parent.pop('pending_actor');driver.write_json(folder/'state.json',parent)
    return receipt
