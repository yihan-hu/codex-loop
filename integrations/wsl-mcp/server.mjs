import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync, mkdirSync, realpathSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

const OUTPUT_LIMIT = 128 * 1024;
const MAX_RUNNING = 4;
const MAX_HISTORY = 32;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const result = value => ({ content: [{ type: 'text', text: JSON.stringify(value) }] });

export function createExecutor({ roots, runtime = path.join(homedir(), '.codex-loop'), budget = { active: 0, limit: MAX_RUNNING }, transport = 'stdio' }) {
  if (process.platform !== 'linux') throw new Error('Run this server inside WSL/Linux.');
  if (!roots?.length) throw new Error('Set CODEX_LOOP_WSL_ROOTS to explicit colon-separated Linux workspace roots.');
  roots = roots.map(root => {
    const canonical = realpathSync(root);
    if (!path.isAbsolute(root) || !statSync(canonical).isDirectory()) throw new Error('Workspace roots must be existing absolute directories.');
    if (['/', '/home', homedir(), '/mnt', '/etc', '/usr', '/proc', '/dev', '/tmp'].includes(canonical)) {
      throw new Error(`Choose a narrower workspace root: ${canonical}`);
    }
    return canonical;
  });
  mkdirSync(runtime, { recursive: true, mode: 0o700 });
  runtime = realpathSync(runtime);
  // Codex Loop keeps routing sessions in tempfile.gettempdir(). Preserve a private
  // /tmp across tool calls; a fresh tmpfs would lose route-init/workspace grants.
  const privateTemp = path.join(runtime, 'wsl-sandbox-tmp');
  mkdirSync(privateTemp, { recursive: true, mode: 0o700 });
  const jobs = new Map();
  const env = { PATH: '/usr/bin:/bin', HOME: homedir(), LANG: 'C.UTF-8' };
  const authorized = cwd => {
    if (!path.isAbsolute(cwd)) throw new Error('cwd must be an absolute Linux path.');
    const canonical = realpathSync(cwd);
    if (!statSync(canonical).isDirectory() || !roots.some(root => canonical === root || canonical.startsWith(root + '/')) ) {
      throw new Error('cwd is outside the configured workspace roots.');
    }
    return canonical;
  };
  const sandboxArgs = cwd => {
    // spawn(detached) already creates an isolated session/process group. A second
    // --new-session inside bwrap would detach descendants from cancellation.
    const args = ['--unshare-user', '--unshare-pid', '--unshare-ipc', '--unshare-uts', '--die-with-parent', '--cap-drop', 'ALL'];
    for (const dir of ['/usr', '/bin', '/sbin', '/lib', '/lib64']) {
      if (existsSync(dir)) args.push('--ro-bind', dir, dir);
    }
    args.push('--proc', '/proc', '--dev', '/dev', '--bind', privateTemp, '/tmp', '--dir', '/etc');
    for (const file of ['/etc/ssl', '/etc/passwd', '/etc/group', '/etc/hosts', '/etc/resolv.conf', '/etc/nsswitch.conf', '/etc/gitconfig']) {
      if (existsSync(file)) args.push('--ro-bind', realpathSync(file), file);
    }
    for (const root of [...new Set([...roots, runtime])]) args.push('--bind', root, root);
    args.push('--clearenv', '--setenv', 'HOME', homedir(), '--setenv', 'PATH', env.PATH,
      '--setenv', 'LANG', env.LANG, '--setenv', 'npm_config_cache', '/tmp/npm-cache',
      '--setenv', 'CODEX_LOOP_HOME', runtime,
      '--chdir', cwd, '--', '/bin/bash', '--noprofile', '--norc', '-c');
    return args;
  };
  const snapshot = (job, offset = 0) => {
    const start = Math.max(job.base, Math.min(offset, job.total));
    return { job_id: job.id, cwd: job.cwd, state: job.state, exit_code: job.exitCode,
      signal: job.signal, output: job.output.subarray(start - job.base).toString('utf8'),
      output_offset: start, next_offset: job.total, output_truncated: offset < job.base,
      timed_out: job.timedOut };
  };
  const kill = (job, signal) => {
    try { process.kill(-job.child.pid, signal); } catch (error) { if (error.code !== 'ESRCH') throw error; }
  };
  const terminate = job => {
    if (job.state !== 'running') return;
    kill(job, 'SIGTERM');
    job.killTimer = setTimeout(() => { if (job.state === 'running') kill(job, 'SIGKILL'); }, 1000);
    job.killTimer.unref();
  };
  async function execute({ command, cwd, timeout_seconds = 120, wait_ms = 1000 }) {
    if (!command || command.length > 65536 || command.includes('\0')) throw new Error('Invalid command.');
    if (!Number.isInteger(timeout_seconds) || timeout_seconds < 1 || timeout_seconds > 3600) throw new Error('Invalid timeout.');
    if (!Number.isInteger(wait_ms) || wait_ms < 0 || wait_ms > 5000) throw new Error('Invalid wait.');
    cwd = authorized(cwd);
    if (budget.active >= budget.limit) throw new Error(`${budget.limit} jobs are already running across connections. Poll or stop one first.`);
    for (const [id, job] of jobs) {
      if (jobs.size < MAX_HISTORY) break;
      if (job.state !== 'running') jobs.delete(id);
    }
    const child = spawn('/usr/bin/bwrap', [...sandboxArgs(cwd), command], { env, detached: true, stdio: ['ignore', 'pipe', 'pipe'] });
    budget.active++;
    const job = { id: randomUUID(), child, cwd, state: 'running', exitCode: null, signal: null,
      output: Buffer.alloc(0), base: 0, total: 0, timedOut: false };
    jobs.set(job.id, job);
    const append = chunk => {
      job.total += chunk.length;
      job.output = Buffer.concat([job.output, chunk]);
      if (job.output.length > OUTPUT_LIMIT) job.output = job.output.subarray(job.output.length - OUTPUT_LIMIT);
      job.base = job.total - job.output.length;
    };
    child.stdout.on('data', append);
    child.stderr.on('data', append);
    job.done = new Promise(resolve => {
      child.on('error', error => append(Buffer.from(`Failed to start sandbox: ${error.message}\n`)));
      child.on('close', (code, signal) => {
        job.state = 'finished'; job.exitCode = code; job.signal = signal;
        budget.active--;
        clearTimeout(job.timer); clearTimeout(job.killTimer); resolve();
      });
    });
    job.timer = setTimeout(() => { job.timedOut = true; terminate(job); }, timeout_seconds * 1000);
    await Promise.race([job.done, sleep(wait_ms)]);
    return snapshot(job);
  }
  const lookup = id => { const job = jobs.get(id); if (!job) throw new Error('Unknown or expired job_id; do not re-run an ambiguous write automatically.'); return job; };
  return {
    roots, runtime,
    async probe() {
      const value = await execute({ command: 'printf SANDBOX_READY', cwd: roots[0], wait_ms: 5000 });
      if (value.exit_code !== 0 || value.output !== 'SANDBOX_READY') throw new Error(`Bubblewrap unavailable; no unsandboxed fallback: ${value.output}`);
    },
    status() { return { platform: 'linux', host: 'WSL/Linux', workspace_roots: roots, runtime_root: runtime,
      transport, max_running_jobs: budget.limit, sandbox: 'bubblewrap', network: 'enabled', windows_mounts: 'not exposed unless explicitly configured as roots',
      running_jobs: [...jobs.values()].filter(job => job.state === 'running').map(job => ({ job_id: job.id, cwd: job.cwd })) }; },
    execute,
    async poll({ job_id, offset = 0, wait_ms = 1000 }) {
      if (!Number.isInteger(offset) || offset < 0 || !Number.isInteger(wait_ms) || wait_ms < 0 || wait_ms > 5000) throw new Error('Invalid offset or wait.');
      const job = lookup(job_id); await Promise.race([job.done, sleep(wait_ms)]); return snapshot(job, offset);
    },
    async stop({ job_id }) { const job = lookup(job_id); terminate(job); await Promise.race([job.done, sleep(2000)]); return snapshot(job); },
    async close() { const active = [...jobs.values()].filter(job => job.state === 'running'); active.forEach(terminate); await Promise.all(active.map(job => job.done)); },
  };
}

export function createServer(executor) {
  const server = new McpServer({ name: 'codex-loop-wsl', version: '0.1.0' }, {
    instructions: 'This connection executes on the user\'s local WSL computer. Use this host only when selected by the user and authorized for the current task. Call wsl_status to observe roots; scope each command to the task\'s bound repository. Shells have network access and can mutate authorized roots. Never read credentials. If the task uses a lifecycle runtime, keep its commands and state on this same WSL host. Poll existing job IDs; never duplicate ambiguous writes. This is a terminal adapter, not browser or Windows desktop control.',
  });
  const guarded = fn => async args => { try { return result(await fn(args)); } catch (error) { return { ...result({ error: error.message }), isError: true }; } };
  server.registerTool('wsl_status', { description: 'Read WSL workspace roots and active job IDs. Does not execute a shell.',
    inputSchema: {}, annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } }, guarded(() => executor.status()));
  server.registerTool('wsl_exec', { description: 'Execute an authorized Bash command in the local WSL sandbox. Can read/write files and access the network. Returns a job ID; use wsl_poll if still running.',
    inputSchema: { command: z.string().min(1).max(65536), cwd: z.string().min(1),
      timeout_seconds: z.number().int().min(1).max(3600).default(120), wait_ms: z.number().int().min(0).max(5000).default(1000) },
    annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: true } }, guarded(executor.execute));
  server.registerTool('wsl_poll', { description: 'Observe a previously started job without restarting it. Use next_offset from the previous result to read new output. Offsets are bytes; truncated output is reported.',
    inputSchema: { job_id: z.string().uuid(), offset: z.number().int().min(0).default(0), wait_ms: z.number().int().min(0).max(5000).default(1000) },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false } }, guarded(executor.poll));
  server.registerTool('wsl_stop', { description: 'Stop only a job started by this MCP server. Terminates its sandbox and child processes.',
    inputSchema: { job_id: z.string().uuid() }, annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false } }, guarded(executor.stop));
  return server;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const executor = createExecutor({ roots: process.env.CODEX_LOOP_WSL_ROOTS?.split(':').filter(Boolean) });
  await executor.probe();
  const server = createServer(executor);
  const close = async () => { await executor.close(); await server.close(); process.exit(0); };
  process.on('SIGTERM', close); process.on('SIGINT', close);
  process.stdin.on('end', close);
  await server.connect(new StdioServerTransport());
}
