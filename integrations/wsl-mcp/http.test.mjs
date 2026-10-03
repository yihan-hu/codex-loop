import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { startHttp } from './http.mjs';

const delay = ms => new Promise(r => setTimeout(r, ms));
test('HTTP sessions isolate handles, stay lazy, expire safely and support stateless Tunnel calls', async () => {
  const base = mkdtempSync(path.join(tmpdir(), 'wsl-http-')); const root = path.join(base, 'projects'); mkdirSync(root);
  const authorization = 'Bearer local-test-only-not-a-real-secret';
  const app = await startHttp({ roots: [root], runtime: path.join(base, 'runtime'), authorization, discoveryIdleMs: 30, toolIdleMs: 30 });
  const headers = { authorization, 'content-type': 'application/json', accept: 'application/json, text/event-stream' };
  const raw = async (method, params = {}, extra = {}) => {
    const response = await fetch(app.url + '/mcp', { method: 'POST', headers: { ...headers, ...extra },
      body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) });
    return { response, body: await response.json() };
  };
  const clients = [];
  try {
    assert.equal((await fetch(app.url + '/healthz')).status, 401);
    assert.equal((await fetch(app.url + '/.well-known/oauth-protected-resource/mcp')).status, 404);
    assert.equal((await fetch(app.url + '/healthz', { headers: { authorization, origin: 'https://evil.example' } })).status, 403);
    for (let i = 0; i < 25; i++) {
      const { response } = await raw('initialize', { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'probe', version: '1' } });
      assert.equal(response.status, 200);
    }
    assert.equal(app.metrics().sessions, 25); assert.equal(app.metrics().executors, 1);
    await delay(40); await app.sweep(); assert.equal(app.metrics().sessions, 0);
    for (let i = 0; i < 2; i++) {
      const client = new Client({ name: 'real-session', version: '1' });
      await client.connect(new StreamableHTTPClientTransport(new URL(app.url + '/mcp'), { requestInit: { headers: { authorization } } })); clients.push(client);
    }
    const tools = (await clients[0].listTools()).tools;
    assert.equal(tools.length, 4);
    assert.ok(tools.every(t => !t._meta));
    const call = async (client, name, args = {}) => {
      const r = await client.callTool({ name, arguments: args });
      assert.equal(r.structuredContent, undefined); return { r, value: JSON.parse(r.content[0].text) };
    };
    const heavy = [];
    for (let i = 0; i < 4; i++) heavy.push({ client: clients[i % 2], job: (await call(clients[i % 2], 'wsl_exec', { command: 'sleep 30', cwd: root, wait_ms: 0 })).value });
    assert.equal(app.metrics().running_jobs, 4);
    assert.equal((await call(clients[0], 'wsl_exec', { command: 'true', cwd: root, wait_ms: 0 })).r.isError, true);
    await call(heavy[0].client, 'wsl_stop', { job_id: heavy[0].job.job_id });
    assert.equal((await call(clients[1], 'wsl_exec', { command: 'printf SLOT_RELEASED', cwd: root, wait_ms: 1000 })).value.output, 'SLOT_RELEASED');
    for (const h of heavy.slice(1)) await call(h.client, 'wsl_stop', { job_id: h.job.job_id });
    assert.equal(app.metrics().running_jobs, 0);
    const job = (await call(clients[0], 'wsl_exec', { command: 'sleep 0.4; printf HTTP_OK', cwd: root, wait_ms: 0 })).value;
    assert.equal((await call(clients[1], 'wsl_poll', { job_id: job.job_id, wait_ms: 0 })).r.isError, true);
    await delay(50); await app.sweep(); assert.equal(app.metrics().sessions, 1); assert.equal(app.metrics().running_jobs, 1);
    const finished = (await call(clients[0], 'wsl_poll', { job_id: job.job_id, wait_ms: 1000 })).value;
    assert.equal(finished.output, 'HTTP_OK'); assert.equal(finished.exit_code, 0);
    await delay(40); await app.sweep(); assert.equal(app.metrics().sessions, 0);
    const started = await raw('tools/call', { name: 'wsl_exec', arguments: { command: 'printf STATELESS_OK', cwd: root, wait_ms: 1000 } });
    assert.equal(started.response.status, 200);
    assert.equal(JSON.parse(started.body.result.content[0].text).output, 'STATELESS_OK');
    const listed = await raw('tools/list'); assert.equal(listed.body.result.tools.length, 4);
  } finally { for (const c of clients) await c.close(); await app.close(); rmSync(base, { recursive: true, force: true }); }
});

test('64 execution requests consume slots, the 65th is rejected, completion releases all slots', async () => {
  const base = mkdtempSync(path.join(tmpdir(), 'wsl-http-limit-')); const root = path.join(base, 'projects'); mkdirSync(root);
  const authorization = 'Bearer local-test-only-not-a-real-secret';
  const app = await startHttp({ roots: [root], runtime: path.join(base, 'runtime'), authorization });
  const held = [];
  try {
    for (let i = 0; i < 64; i++) {
      const r = http.request(app.url + '/mcp', { method: 'POST', headers: { authorization, 'content-type': 'application/json', 'content-length': 2 } });
      const done = new Promise((resolve, reject) => { r.on('response', res => { res.resume(); res.on('end', resolve); }); r.on('error', reject); });
      r.write('{'); held.push({ r, done });
    }
    for (let i = 0; i < 50 && app.metrics().active_requests !== 64; i++) await delay(10);
    assert.equal(app.metrics().active_requests, 64);
    assert.equal((await fetch(app.url + '/mcp', { method: 'POST', headers: { authorization }, body: '{}' })).status, 429);
    for (const h of held) h.r.end('}'); await Promise.all(held.map(h => h.done));
    assert.equal(app.metrics().active_requests, 0);
    assert.equal((await fetch(app.url + '/healthz', { headers: { authorization } })).status, 200);
  } finally { for (const h of held) h.r.destroy(); await app.close(); rmSync(base, { recursive: true, force: true }); }
});
