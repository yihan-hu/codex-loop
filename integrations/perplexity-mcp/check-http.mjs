import {readFile,writeFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import path from 'node:path';
import {strict as assert} from 'node:assert';
import dns from 'node:dns';
const config=JSON.parse(await readFile(new URL('./config.json',import.meta.url)));
const connection=JSON.parse(await readFile(path.join(config.stateDirectory,'connection.json')));
const key=(await readFile(config.httpAuthFile,'utf8')).trim();
assert(connection.mcp_url,'Start the HTTPS tunnel before this check');
// Resolve the newly issued hostname directly; macOS may retain an initial NXDOMAIN in lookup().
const tunnelHost=new URL(connection.mcp_url).hostname, originalLookup=dns.lookup;
dns.lookup=(host,options,callback)=>{
 if(typeof options==='function'){callback=options;options={};}
 if(host!==tunnelHost)return originalLookup(host,options,callback);
 return dns.resolve4(host,(error,addresses)=>error?callback(error):options?.all?callback(null,addresses.map(address=>({address,family:4}))):callback(null,addresses[0],4));
};
const require=createRequire(path.join(config.myMacDirectory,'package.json'));
const {Client}=require('@modelcontextprotocol/sdk/client/index.js');
const {StreamableHTTPClientTransport}=require('@modelcontextprotocol/sdk/client/streamableHttp.js');
const proof={checks:[]};
for(const base of [`http://127.0.0.1:${config.httpPort}`,connection.mcp_url.replace(/\/mcp$/,'')]) {
 assert.equal((await fetch(base+'/mcp',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})).status,401);
 assert.equal((await fetch(base+'/mcp',{method:'POST',headers:{Authorization:'Bearer wrong','Content-Type':'application/json'},body:'{}'})).status,401);
 const client=new Client({name:'http-verification',version:'1.0'});
 try {
  await client.connect(new StreamableHTTPClientTransport(new URL(base+'/mcp'),{requestInit:{headers:{Authorization:'Bearer '+key}}}));
  assert.equal((await client.listTools()).tools.length,12);
  const state=await client.callTool({name:'loop_status',arguments:{}});assert(!state.isError);assert.match(state.content[0].text,/tasks/);
 }finally{await client.close();}
 proof.checks.push(`${base.startsWith('https')?'HTTPS tunnel':'Loopback HTTP'}: missing/wrong key denied; authenticated MCP discovery and real task-state tool pass`);
}
assert.equal((await fetch(`http://127.0.0.1:${config.httpPort}/mcp`,{method:'POST',headers:{Authorization:'Bearer '+key,Origin:'https://untrusted.example'},body:'{}'})).status,403);
proof.checks.push('untrusted Browser Origin rejected');proof.result='PASS';proof.completed_at=new Date().toISOString();
await writeFile(new URL('./verification-http.json',import.meta.url),JSON.stringify(proof,null,2)+'\n');console.log(JSON.stringify(proof,null,2));
