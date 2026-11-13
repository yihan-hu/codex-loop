"""Check approval binding, scope and control parsing without touching a UI or model."""
import importlib.util, pathlib, tempfile, json
path=pathlib.Path(__file__).with_name('conversation.py');spec=importlib.util.spec_from_file_location('conversation',path);driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
with tempfile.TemporaryDirectory() as temporary:
    root=pathlib.Path(temporary);(root/'allowed.md').write_text('original')
    config=driver.config_check({'workspace':temporary,'goal':'Write, review and revise this authorized artifact','allowed_files':['allowed.md'],'required_files':['allowed.md'],'allowed_commands':['printf EXACT'],'max_rounds':3,'min_rounds':2})
    state={'task_id':'a'*32,'nonce':'b'*32}
    payload={'task_id':state['task_id'],'path':'allowed.md','content':'model text','request_id':state['nonce']+'-write-1'}
    def approval(value):return driver.approval_payload([json.dumps(value),'Reply yes to proceed or no to cancel.'],state,config)
    assert approval(payload)['kind']=='mac_write'
    accepted=approval(payload)
    later=dict(state,nonce='d'*32,approved=[accepted['sha256']])
    assert driver.approval_payload([json.dumps(payload),'Reply yes to proceed or no to cancel.'],later,config) is None
    for altered in [dict(payload,task_id='c'*32),dict(payload,path='../outside.md'),dict(payload,path='private.md'),dict(payload,request_id='old-round-operation'),{'task_id':state['task_id'],'summary':'premature finish'},{'task_id':state['task_id'],'command':'printf NEW','request_id':state['nonce']+'-cmd'}]:
        try:approval(altered)
        except ValueError:pass
        else:raise AssertionError('Out-of-scope approval was accepted')
    external=root.parent/(root.name+'-outside');external.write_text('outside')
    try:
        (root/'allowed-link.md').symlink_to(external)
        try:driver.allowed_path(dict(config,allowed_files=['**']),'allowed-link.md')
        except ValueError:pass
        else:raise AssertionError('Symlink escaped the workspace')
    finally:external.unlink()
    assert approval({'task_id':state['task_id'],'command':'printf EXACT','request_id':state['nonce']+'-cmd'})['kind']=='mac_command'
    packet={'decision':'CONTINUE','summary':'A concrete model review found an issue','next_prompt':'Revise the actual artifact using that finding'}
    wrapped='PCL_RESULT_'+state['nonce']+'\n'+json.dumps(packet)+'\nPCL_END_'+state['nonce']
    assert driver.result_packet(wrapped,state['nonce'])==packet
    assert driver.result_packet(wrapped.replace('"','“'),state['nonce'])==packet
    assert driver.result_packet(wrapped,'c'*32) is None
    assert driver.result_packet('The file says DONE, but no current-round result exists',state['nonce']) is None
    assert driver.validate_artifacts(config)[0]['bytes']==8
    import shortcut
    before=json.dumps(config,sort_keys=True)
    short=shortcut.task_config(config,'@my mac /write Explain the difference and save allowed.md')
    assert short['goal']=='/write Explain the difference and save allowed.md'
    assert short['allowed_files']==config['allowed_files'] and short['allowed_commands']==config['allowed_commands']
    assert short['max_rounds']==config['max_rounds'] and short['min_rounds']==config['min_rounds']
    assert json.dumps(config,sort_keys=True)==before
    for request in ['', '@my mac @epi prose /write Discussion']:
        try:shortcut.task_config(config,request)
        except ValueError:pass
        else:raise AssertionError('Empty or unsupported full-skill invocation was accepted')
print('PASS: task/round binding, exact command grants, path and symlink scope, no premature finish approval, nonce-specific model result, real artifact checks, saved-project short tasks preserve scope and reject unsupported Epi Prose')
