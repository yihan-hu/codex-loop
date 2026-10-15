import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {homedir} from 'node:os';
import path from 'node:path';

const run=promisify(execFile);
const cli=process.env.CODEX_LOOP_ACTIVITY_CLI ??
  path.join(homedir(),'.codex-loop/runtime-src/scripts/codex_loop.py');
const seen=new Set();

// This helper runs only the installed fixed Codex Loop CLI with a validated task
// ID. It cannot execute model-supplied shell, and updates a lease at most 1/min.
export async function activityBeforeTool(taskId) {
  if (!taskId || !/^[0-9a-f]{32}$/.test(taskId)) return null;
  const {stdout}=await run('python3',[cli,'collab','activity',
                    '--task-id',taskId,'--interval-seconds','60'],
                    {timeout:5000,maxBuffer:256*1024});
  const response=JSON.parse(stdout);
  if (!response.ok || !response.data) throw Error('Codex Loop activity preflight failed');
  const activity=response.data;
  const stop=activity.messages.filter(m=>m.control_action==='stop_task');
  if (stop.length) throw Error('[CODEX LOOP STOP] No host operation was executed. '+
      stop.map(m=>String(m.body).slice(0,1400)).join(' | '));
  const messages=activity.messages.filter(m=>{
    const id=m.run_id+':'+taskId+':'+m.id;
    if(seen.has(id))return false;
    seen.add(id);return true;
  }).slice(0,5).map(m=>({run_id:m.run_id,id:m.id,
                          sender:m.sender,body:String(m.body).slice(0,1600)}));
  if(seen.size>2000)seen.clear();
  return {messages};
}
