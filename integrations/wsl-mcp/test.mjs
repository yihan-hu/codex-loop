import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, mkdirSync, writeFileSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { createExecutor } from './server.mjs';

test('sandbox isolates files, credentials and Windows mounts; jobs support polling, cancellation and bounded output', async () => {
  const base = mkdtempSync(path.join(tmpdir(), 'codex-loop-wsl-test-'));
  const root = path.join(base, 'workspace');
  const runtime = path.join(base, 'runtime');
  const { mkdirSync } = await import('node:fs');
  mkdirSync(root);
  const outside = path.join(base, 'private.txt');
  writeFileSync(outside, 'OUTSIDE_SENTINEL');
  symlinkSync(base, path.join(root, 'escape'));
  process.env.CONTROL_PLANE_API_KEY = 'test-key-must-not-leak';
  const executor = createExecutor({ roots: [root], runtime });
  try {
    await executor.probe();
    const command = `printf '%s' "\${CONTROL_PLANE_API_KEY-unset}"; test ! -e /mnt/c; test ! -e '${outside}'; test ! -e '${root}/escape/private.txt'; printf '\nISOLATED'`;
    const isolated = await executor.execute({ command, cwd: root, wait_ms: 5000 });
    assert.equal(isolated.exit_code, 0);
    assert.equal(isolated.output, 'unset\nISOLATED');
    await assert.rejects(executor.execute({ command: 'true', cwd: base }), /outside/);
    await assert.rejects(executor.execute({ command: 'true', cwd: path.join(root, 'escape') }), /outside/);
    const write = await executor.execute({ command: "printf WSL_WRITE_OK > result.txt; cat result.txt", cwd: root, wait_ms: 5000 });
    assert.equal(write.output, 'WSL_WRITE_OK');
    await executor.execute({ command: 'printf ROUTE_STATE > /tmp/routing-test', cwd: root, wait_ms: 5000 });
    const persisted = await executor.execute({ command: 'cat /tmp/routing-test', cwd: root, wait_ms: 5000 });
    assert.equal(persisted.output, 'ROUTE_STATE');
    const running = await executor.execute({ command: 'printf first; sleep 0.3; printf second', cwd: root, wait_ms: 50 });
    assert.equal(running.state, 'running');
    const finished = await executor.poll({ job_id: running.job_id, offset: running.next_offset, wait_ms: 1000 });
    assert.equal(finished.state, 'finished');
    assert.equal(running.output + finished.output, 'firstsecond');
    const long = await executor.execute({ command: 'sleep 60 & wait', cwd: root, wait_ms: 10 });
    assert.equal((await executor.stop({ job_id: long.job_id })).state, 'finished');
    const timeout = await executor.execute({ command: 'sleep 60', cwd: root, timeout_seconds: 1, wait_ms: 2000 });
    assert.equal(timeout.state, 'finished'); assert.equal(timeout.timed_out, true);
    const flood = await executor.execute({ command: "python3 -c 'print(\"x\" * 200000)'", cwd: root, wait_ms: 5000 });
    assert.equal(flood.state, 'finished'); assert.equal(flood.output_truncated, true);
    assert.equal(Buffer.byteLength(flood.output), 128 * 1024);
    await assert.rejects(executor.poll({ job_id: 'unknown' }), /Unknown/);
  } finally {
    delete process.env.CONTROL_PLANE_API_KEY;
    await executor.close(); rmSync(base, { recursive: true, force: true });
  }
});

test('Codex Loop task and routing state survive separate sandboxed tool calls', async () => {
  const base = mkdtempSync(path.join(tmpdir(), 'codex-loop-wsl-lifecycle-'));
  const root = path.join(base, 'workspace'); mkdirSync(root);
  const runtime = path.join(base, 'runtime'); mkdirSync(runtime);
  const source = path.join(runtime, 'runtime-src');
  cpSync(fileURLToPath(new URL('../../scripts', import.meta.url)), path.join(source, 'scripts'), { recursive: true });
  const executor = createExecutor({ roots: [root], runtime });
  const controller = `python3 '${source}/scripts/codex_loop.py'`;
  const run = async command => {
    const value = await executor.execute({ command, cwd: root, wait_ms: 5000 });
    assert.equal(value.exit_code, 0, value.output);
    const payload = JSON.parse(value.output); assert.equal(payload.ok, true); return payload.data;
  };
  try {
    const admitted = await run(`${controller} bootstrap --request-anchor 'MCP lifecycle test'`);
    assert.ok(admitted.task_id);
    const continued = await run(`${controller} next --task-id '${admitted.task_id}'`);
    assert.equal(continued.task.task_id, admitted.task_id);
    const route = await run(`${controller} route-init --host-surface chatgpt_web`);
    const denied = await run(`${controller} route-check --session-id '${route.session_id}' --action wsl_repository`);
    assert.equal(denied.allowed, false);
    await run(`${controller} route-transition --session-id '${route.session_id}' --workspace-mode local --current-user-selection-observed --selection-evidence 'test user selected WSL'`);
    const allowed = await run(`${controller} route-check --session-id '${route.session_id}' --action wsl_repository --workspace-granted`);
    assert.equal(allowed.allowed, true);
  } finally { await executor.close(); rmSync(base, { recursive: true, force: true }); }
});

test('real MCP client initializes, lists tools and executes/polls/stops WSL jobs over stdio', async () => {
  const base = mkdtempSync(path.join(tmpdir(), 'codex-loop-wsl-protocol-'));
  const { mkdirSync } = await import('node:fs');
  const root = path.join(base, 'workspace'); mkdirSync(root);
  // Keep the test lifecycle state under the test directory instead of the user's runtime.
  const transport = new StdioClientTransport({ command: process.execPath,
    args: [fileURLToPath(new URL('server.mjs', import.meta.url))],
    env: { ...process.env, CODEX_LOOP_WSL_ROOTS: root, HOME: base }, stderr: 'pipe' });
  const client = new Client({ name: 'wsl-test-client', version: '1.0.0' });
  const call = async (name, args = {}) => {
    const response = await client.callTool({ name, arguments: args });
    return { response, value: JSON.parse(response.content[0].text) };
  };
  try {
    await client.connect(transport);
    const tools = (await client.listTools()).tools;
    assert.deepEqual(tools.map(tool => tool.name).sort(), ['wsl_exec', 'wsl_poll', 'wsl_status', 'wsl_stop']);
    assert.equal(tools.find(tool => tool.name === 'wsl_exec').annotations.readOnlyHint, false);
    assert.equal((await call('wsl_status')).value.sandbox, 'bubblewrap');
    const executed = await call('wsl_exec', { command: "printf MCP_CONNECTED; uname -s", cwd: root, wait_ms: 5000 });
    assert.equal(executed.value.exit_code, 0);
    assert.equal(executed.value.output, 'MCP_CONNECTEDLinux\n');
    const denied = await call('wsl_exec', { command: 'pwd', cwd: '/etc' });
    assert.equal(denied.response.isError, true);
    const running = (await call('wsl_exec', { command: 'sleep 30', cwd: root, wait_ms: 0 })).value;
    assert.equal((await call('wsl_poll', { job_id: running.job_id, wait_ms: 0 })).value.state, 'running');
    assert.equal((await call('wsl_stop', { job_id: running.job_id })).value.state, 'finished');
  } finally { await client.close(); rmSync(base, { recursive: true, force: true }); }
});
