"""Transport-only unit check with simulated UI/model callbacks; not a production writing benchmark."""
import json
import pathlib
import tempfile
import types

import actors
import conversation as driver

with tempfile.TemporaryDirectory() as temporary:
    root=pathlib.Path(temporary).resolve();registry=root/'registry';registry.mkdir()
    parent={'run_id':'a'*32,'marker':'[PCL:'+'a'*32+']','task_id':'b'*32,'round':1}
    folder=registry/parent['run_id'];folder.mkdir()
    config={'workspace':str(root),'allowed_files':['**'],'allowed_skills':['epi-prose'],
            'connector':'Codex Loop Mac Skills','round_timeout_seconds':60,'goal':'PARENT-SCIENCE-MUST-NOT-ENTER-CHILD'}
    source=root/'packet.json';target=root/'result.json'
    packet={'stage':'probe','inputs':{'secret':'PACKET-CONTENT-MUST-STAY-OUT-OF-PARENT-RECEIPT'},
            'semantic_result_submission':{'role':'B','result_path':str(target),'logical_isolation':'FRESH_SUBAGENT_REQUIRED'}}
    source.write_text(json.dumps(packet))
    selection={'marker':parent['marker'],'new_count':0}
    def ui(mode,request=None):
        if mode=='snapshot':return {'selected':[selection['marker']]}
        assert selection['marker']==request['from_marker']
        if mode=='new':selection.update(marker='New thread',new_count=selection['new_count']+1);return {'incognito_verified':True}
        selection['marker']=request['session_marker'];return {'selected':[selection['marker']]}
    def model(run_id,ui_owned=False):
        assert ui_owned
        child_folder=registry/run_id;state=json.loads((child_folder/'state.json').read_text());c=json.loads((child_folder/'config.json').read_text())
        assert 'PARENT-SCIENCE-MUST-NOT-ENTER-CHILD' not in state['pending_prompt']
        assert 'PACKET-CONTENT-MUST-STAY-OUT-OF-PARENT-RECEIPT' not in state['pending_prompt']
        assert c['_actor']['input_path']==str(source)
        selection['marker']=state['marker']
        # This is an explicitly simulated callback, not model-quality evidence.
        pathlib.Path(c['_actor']['result_path']).write_text('{"unit_simulated_result":true}')
        state.update(status='actor_complete',rounds=[{'parts_read':['part_001_of_001.txt']}]);driver.write_json(child_folder/'state.json',state);return state
    fake=types.SimpleNamespace(ROOT=registry,allowed_path=driver.allowed_path,write_json=driver.write_json,event=driver.event,now=driver.now,ui=ui,run_driver=model,record_actor=lambda *args:None)
    receipt=actors.dispatch(fake,folder,parent,config,{'input_path':str(source),'result_path':str(target)})
    assert receipt['status']=='WROTE' and receipt['incognito_verified']
    assert 'unit_simulated_result' not in json.dumps(receipt)
    assert receipt['actor_id'].startswith('perplexity:') and selection['marker']==parent['marker']
    assert selection['new_count']==1 and 'pending_actor' not in parent and parent['actor_receipt']==receipt
    for request in [{'input_path':str(source),'result_path':'../escape.json'}, {'input_path':str(source),'result_path':str(target)}]:
        try:actors.request_metadata(fake,config,request)
        except ValueError:pass
        else:raise AssertionError('Invalid or already-existing actor output was accepted')
    next_target=root/'other.json';packet['semantic_result_submission'].update(role='T',result_path=str(next_target),logical_isolation='ROLE_SCOPED_REUSE',reuse_subagent_id=receipt['actor_id']);source.write_text(json.dumps(packet))
    try:actors.dispatch(fake,folder,parent,config,{'input_path':str(source),'result_path':str(next_target)})
    except ValueError as e:assert 'roles' in str(e)
    else:raise AssertionError('B actor was reused as T')
print('PASS (unit only): child input excludes parent science, metadata-only receipt, explicit Incognito evidence, same task identity, parent return, reserved output/path checks, B/T role separation')
