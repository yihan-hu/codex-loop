import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, chmodSync, symlinkSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { createGrants } from './grants.mjs';
import { createExecutor } from './server.mjs';
import { startHttp } from './http.mjs';
const delay = ms => new Promise(r => setTimeout(r, ms));
function fixture() {
  const base = mkdtempSync(path.join(tmpdir(), 'wsl-grants-'));
  const root = path.join(base, 'default'), project = path.join(base, 'extra'), other = path.join(base, 'other');
  for (const p of [root, project, other]) mkdirSync(p);
  const projectsFile = path.join(base, 'private-projects.json');
  writeFileSync(projectsFile, JSON.stringify({ projects: { example: { path: project, access: 'read-write' }, readonly: { path: other, access: 'read-only' } } }), { mode: 0o600 });
  return { base, root, project, other, projectsFile };
}

test('grant capabilities require local registration, task match, expiry and private configuration', async () => {
  const f = fixture(); let time = 0;
  const g = createGrants({ projectsFile: f.projectsFile, now: () => time });
  try {
    assert.throws(() => g.grant({ project_id: 'unknown', task_id: 'task-a' }), /not registered/);
    assert.throws(() => g.assertHidden([f.base]), /outside/);
    assert.throws(() => g.grant({ project_id: 'readonly', task_id: 'task-a', access: 'read-write' }), /exceeds/);
    const grant = g.grant({ project_id: 'example', task_id: 'task-a', ttl_seconds: 1 });
    assert.equal(g.resolve(grant).root, realpathSync(f.project)); assert.equal(grant.access, 'read-only');
    assert.throws(() => g.resolve({ ...grant, task_id: 'task-b' }), /mismatch/);
    assert.ok(!JSON.stringify(g.list()).includes(grant.grant_id));
    let stopped = false; g.attach(g.resolve(grant), () => { stopped = true; });
    time = 1001; assert.throws(() => g.resolve(grant), /expired/); assert.equal(stopped, true);
    const removed = g.grant({ project_id: 'example', task_id: 'task-remove' });
    let removalStopped = false; g.attach(g.resolve(removed), () => { removalStopped = true; });
    const original = (await import('node:fs')).readFileSync(f.projectsFile, 'utf8');
    writeFileSync(f.projectsFile, JSON.stringify({ projects: {} }));
    assert.throws(() => g.resolve(removed), /not registered/); assert.equal(removalStopped, true);
    writeFileSync(f.projectsFile, original);
    const second = g.grant({ project_id: 'example', task_id: 'task-b' });
    await g.revoke(second); assert.throws(() => g.resolve(second), /Unknown/);
    chmodSync(f.projectsFile, 0o644); assert.throws(() => g.list(), /owner-only/);
    chmodSync(f.projectsFile, 0o600);
    const link = path.join(f.base, 'link'); symlinkSync(f.projectsFile, link);
    assert.throws(() => createGrants({ projectsFile: link }).list(), /symlink/);
    const configLink = path.join(f.root, 'registry-dir'); symlinkSync(f.base, configLink);
    assert.throws(() => createGrants({ projectsFile: path.join(configLink, 'private-projects.json') }).assertHidden([f.base]), /outside/);
  } finally { await g.close(); rmSync(f.base, { recursive: true, force: true }); }
});

test('sandbox grant exposes only its project, enforces read-only, revokes running jobs and expires', { skip: process.platform !== 'linux' }, async () => {
  const f = fixture(), grants = createGrants({ projectsFile: f.projectsFile });
  const e = createExecutor({ roots: [f.root], runtime: path.join(f.base, 'runtime'), grants });
  try {
    await e.probe();
    await assert.rejects(e.execute({ command: 'pwd', cwd: f.project }), /outside/);
    const a = grants.grant({ project_id: 'example', task_id: 'task-a', access: 'read-write' });
    await assert.rejects(e.execute({ command: 'pwd', cwd: f.project, ...a, task_id: 'task-b' }), /mismatch/);
    symlinkSync(f.other, path.join(f.project, 'escape'));
    await assert.rejects(e.execute({ command: 'pwd', cwd: path.join(f.project, 'escape'), ...a }), /outside/);
    const written = await e.execute({ command: `printf OK > result.txt; test ! -e '${f.projectsFile}'; test ! -e '${f.other}'; cat result.txt`, cwd: f.project, ...a, wait_ms: 5000 });
    assert.equal(written.exit_code, 0); assert.equal(written.output, 'OK');
    const without = await e.execute({ command: `test ! -e '${f.project}/result.txt'`, cwd: f.root, wait_ms: 5000 });
    assert.equal(without.exit_code, 0);
    const ro = grants.grant({ project_id: 'readonly', task_id: 'task-b' });
    const denied = await e.execute({ command: 'printf NO > denied.txt', cwd: f.other, ...ro, wait_ms: 5000 });
    assert.notEqual(denied.exit_code, 0);
    const running = await e.execute({ command: 'sleep 60 & wait', cwd: f.project, ...a, wait_ms: 10 });
    await grants.revoke(a);
    assert.equal((await e.poll({ job_id: running.job_id, wait_ms: 0 })).state, 'finished');
    await assert.rejects(e.execute({ command: 'pwd', cwd: f.project, ...a }), /Unknown/);
    const timed = grants.grant({ project_id: 'example', task_id: 'task-a', ttl_seconds: 1 });
    const job = await e.execute({ command: 'sleep 60 & wait', cwd: f.project, ...timed, wait_ms: 10 });
    await delay(2200);
    assert.equal((await e.poll({ job_id: job.job_id, wait_ms: 0 })).state, 'finished');
    assert.throws(() => grants.resolve(timed), /Unknown|expired/);
  } finally { await grants.close(); await e.close(); rmSync(f.base, { recursive: true, force: true }); }
});

test('HTTP task grants survive protocol reconnection without appearing in another session status', { skip: process.platform !== 'linux' }, async () => {
  const f = fixture(), authorization = 'Bearer local-test-only-not-a-real-secret';
  const app = await startHttp({ roots: [f.root], runtime: path.join(f.base, 'runtime'), authorization, projectsFile: f.projectsFile });
  const headers = { authorization, 'content-type': 'application/json', accept: 'application/json, text/event-stream' };
  async function raw(method, params, session) {
    const r = await fetch(app.url + '/mcp', { method: 'POST', headers: { ...headers, ...(session ? { 'mcp-session-id': session } : {}) }, body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }) });
    return { r, body: await r.json() };
  }
  const init = async () => (await raw('initialize', { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'grant-test', version: '1' } })).r.headers.get('mcp-session-id');
  async function call(name, args, session) {
    const { body } = await raw('tools/call', { name, arguments: args }, session);
    return { ...body.result, value: JSON.parse(body.result.content[0].text) };
  }
  try {
    const first = await init();
    const grant = (await call('wsl_grant_project', { project_id: 'example', task_id: 'task-a' }, first)).value;
    await fetch(app.url + '/mcp', { method: 'DELETE', headers: { ...headers, 'mcp-session-id': first } });
    const second = await init();
    assert.equal((await call('wsl_exec', { command: 'printf RECONNECTED', cwd: f.project, grant_id: grant.grant_id, task_id: grant.task_id }, second)).value.output, 'RECONNECTED');
    const third = await init();
    assert.equal((await call('wsl_exec', { command: 'pwd', cwd: f.project }, third)).isError, true);
    assert.ok(!JSON.stringify((await call('wsl_status', {}, third)).value).includes(grant.grant_id));
    await call('wsl_revoke_project', { grant_id: grant.grant_id, task_id: grant.task_id }, third);
    assert.equal((await call('wsl_exec', { command: 'pwd', cwd: f.project, grant_id: grant.grant_id, task_id: grant.task_id }, second)).isError, true);
    // The service has no persistent grant store; restart requires explicit reauthorization.
    assert.throws(() => createGrants({ projectsFile: f.projectsFile }).resolve(grant), /Unknown/);
  } finally { await app.close(); rmSync(f.base, { recursive: true, force: true }); }
});
