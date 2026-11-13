// Registered local Skill code is trusted; this is argv pinning, not an OS sandbox.
import {readFileSync,realpathSync,mkdirSync,statSync,existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

export function registration(config, task, name) {
 if(!task.conversation_scope?.allowed_skills?.includes(name))throw Error('Skill is not granted to this conversation task');
 const registered=config.localSkills?.[name];if(!registered)throw Error('Local Skill is not registered');
 return {...registered,root:realpathSync(registered.root)};
}
function within(root, target) {
 const relative=path.relative(root,target);
 if(relative==='..'||relative.startsWith('../')||path.isAbsolute(relative))throw Error('Path escapes the selected Skill or workspace');
 return relative.split(path.sep).join('/');
}
export function resource(config,task,a) {
 let filename;
 if(a.location==='skill') {
  const registered=registration(config,task,a.skill);
  const requested=path.resolve(registered.root,a.path);within(registered.root,requested);
  filename=realpathSync(requested);
  let allowed=false;
  try{within(registered.root,filename);allowed=true;}catch{}
  // Installed source archives may be symlinks. Only registration-pinned targets
  // are readable, not arbitrary links added or retargeted by a model later.
  for(const [alias,target] of Object.entries(registered.resource_links??{})){
   try{within(path.join(registered.root,alias),requested);within(target,filename);allowed=true;}catch{}
  }
  if(!allowed)throw Error('Path escapes the registered Skill resources');
 }else {
  filename=realpathSync(path.resolve(task.root,a.path));const relative=within(task.root,filename);
  if(!task.conversation_scope?.allowed_files?.some(g=>g==='**'||g===relative||g.endsWith('/**')&&relative.startsWith(g.slice(0,-2))))throw Error('File is outside the conversation task grant');
 }
 if(!statSync(filename).isFile())throw Error('Select a text file');
 const raw=readFileSync(filename);if(raw.length>20*1024*1024)throw Error('Use a Skill parser or split this text file before reading');
 const text=Array.from(new TextDecoder('utf-8',{fatal:true}).decode(raw)),offset=a.offset??0,limit=a.limit??60000;
 return {path:a.path,location:a.location,offset,text:text.slice(offset,offset+limit).join(''),total_characters:text.length,next_offset:offset+limit<text.length?offset+limit:null};
}
const quote=value=>"'"+value.replaceAll("'","'\\''")+"'";
export function invocation(config,task,a) {
 const registered=registration(config,task,a.skill),root=realpathSync(path.join(registered.root,'scripts'));
 if(!registered.scripts.includes(a.script))throw Error('Skill script is not in the locally registered production entrypoints');
 if(!Array.isArray(a.arguments)||a.arguments.some(x=>typeof x!=='string'||x.includes('\0')))throw Error('Skill arguments must be literal strings');
 let script,argv=a.arguments;
 if(['@fetch','@extract'].includes(a.script)){
  if(argv.length!==2)throw Error('Source helpers need exactly source and destination');
  script=fileURLToPath(new URL('./source_io.py',import.meta.url));argv=[a.script.slice(1),...argv];
 }else {
  if(typeof a.script!=='string'||path.isAbsolute(a.script)||a.script.split('/').includes('..')||!a.script.endsWith('.py'))throw Error('Select a registered Skill Python entrypoint');
  script=realpathSync(path.resolve(root,a.script));within(root,script);
 }
 const values=[];
 for(let i=0;i<a.arguments.length;i++){
  if(a.arguments[i]==='--native-subagent-id')values.push(a.arguments[i+1]??'');
  else if(a.arguments[i].startsWith('--native-subagent-id='))values.push(a.arguments[i].slice('--native-subagent-id='.length));
 }
 if(a.skill==='epi-prose'&&a.script==='epi_prose_runtime_v3.py'&&a.arguments[0]==='submit-work'&&!values.length)throw Error('This host submits only actual independent actor identities');
 for(const value of values){
  const id=value.split('=').at(-1),binding=task.native_actor_results?.[id];
  if(!binding)throw Error('native-subagent-id was not issued by a completed actor in this lifecycle');
  const index=a.arguments.indexOf('--state');
  const state=index>=0?a.arguments[index+1]:a.arguments.find(x=>x.startsWith('--state='))?.slice(8);
  if(state&&binding.state_path&&path.resolve(task.root,state)!==binding.state_path)throw Error('Actor identity belongs to another Skill state');
 }
 // Text output stays in the project and is read with explicit character pagination.
 if(!task.conversation_scope.allowed_files.includes('**'))throw Error('Running a complete local Skill requires an explicitly granted whole-project scope');
 const directory=path.join(task.root,'.perplexity-loop','commands');
 within(task.root,realpathSync(task.root));
 // Check an existing ancestor too: a project symlink must not redirect this output.
 let ancestor=directory;while(true){try{within(task.root,realpathSync(ancestor));break;}catch(e){if(e.code!=='ENOENT')throw e;ancestor=path.dirname(ancestor);}}
 const identifier=createHash('sha256').update(a.request_id).digest('hex');
 const output=path.join(directory,identifier+'.txt');
 if(existsSync(output))within(task.root,realpathSync(output));
 return {command:[registered.python,script,...argv].map(quote).join(' ')+' > '+quote(output)+' 2>&1',
  output_path:path.relative(task.root,output),prepare(){mkdirSync(directory,{recursive:true});}};
}
