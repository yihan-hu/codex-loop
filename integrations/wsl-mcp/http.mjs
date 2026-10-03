import http from 'node:http';
import { randomUUID, timingSafeEqual } from 'node:crypto';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { createExecutor, createServer } from './server.mjs';

export async function startHttp({ roots, runtime, authorization, port = 0, maxRequests = 64,
  discoveryIdleMs = 120000, toolIdleMs = 1800000, cleanupMs = 30000 }) {
  if (!authorization?.startsWith('Bearer ') || authorization.length < 32) throw new Error('A private local bearer header is required.');
  if (!Number.isInteger(maxRequests) || maxRequests < 1 || maxRequests > 256) throw new Error('Invalid HTTP request limit.');
  const budget = { active: 0, limit: 4 };
  const executor = () => createExecutor({ roots, runtime, budget, transport: 'streamable-http' });
  const shared = executor();
  await shared.probe();
  const sessions = new Map();
  let activeRequests = 0, closing = false;
  const metrics = () => ({ transport: 'streamable-http', max_concurrent_requests: maxRequests,
    active_requests: activeRequests, sessions: sessions.size, executors: 1 + [...sessions.values()].filter(s => s.executor).length,
    running_jobs: budget.active, max_running_jobs: budget.limit, ui: 'plain-text' });
  const send = (res, status, value) => { res.writeHead(status, { 'content-type': 'application/json' }); res.end(JSON.stringify(value)); };
  const authorized = value => {
    const a = Buffer.from(value || ''), b = Buffer.from(authorization);
    return a.length === b.length && timingSafeEqual(a, b);
  };
  const closeSession = async (id, session) => {
    sessions.delete(id);
    await session.server.close();
    if (session.executor) await session.executor.close();
  };
  async function sweep() {
    const now = Date.now();
    for (const [id, s] of sessions) {
      if (s.active || now - s.last < (s.used ? toolIdleMs : discoveryIdleMs)) continue;
      if (s.executor?.status().running_jobs.length) continue;
      // No asynchronous gap between the final activity check and removal.
      await closeSession(id, s);
    }
  }
  const listener = http.createServer(async (req, res) => {
    let acquired = false, ephemeral;
    try {
      const host = req.headers.host;
      if (!host || host !== `127.0.0.1:${listener.address().port}`) return send(res, 403, { error: 'Invalid Host' });
      if (req.headers.origin && req.headers.origin !== `http://${host}`) return send(res, 403, { error: 'Invalid Origin' });
      if (!['/mcp', '/healthz'].includes(req.url)) return send(res, 404, { error: 'Not found' });
      if (!authorized(req.headers.authorization)) return send(res, 401, { error: 'Unauthorized' });
      if (req.url === '/healthz' && req.method === 'GET') return send(res, closing ? 503 : 200, metrics());
      if (req.url !== '/mcp') return send(res, 404, { error: 'Not found' });
      if (closing) return send(res, 503, { error: 'Service stopping' });
      // SSE streams do not consume execution slots.
      if (req.method !== 'GET') {
        if (activeRequests >= maxRequests) return send(res, 429, { error: 'Concurrent request limit reached' });
        activeRequests++; acquired = true;
      }
      let body;
      if (req.method === 'POST') {
        let size = 0; const chunks = [];
        for await (const chunk of req) {
          size += chunk.length;
          if (size > 1024 * 1024) return send(res, 413, { error: 'Request too large' });
          chunks.push(chunk);
        }
        try { body = JSON.parse(Buffer.concat(chunks).toString()); }
        catch { return send(res, 400, { error: 'Invalid JSON' }); }
        if (Array.isArray(body)) return send(res, 400, { error: 'Batch requests are unsupported' });
      }
      const id = req.headers['mcp-session-id'];
      let session;
      if (id) {
        session = sessions.get(id);
        if (!session) return send(res, 404, { error: 'Session expired; initialize again' });
      } else if (body?.method === 'initialize') {
        // Discovery sessions stay lightweight: no job executor until tools/call.
        session = { last: Date.now(), used: false, active: 0, executor: null };
        const facade = {};
        for (const method of ['status', 'execute', 'poll', 'stop']) facade[method] = (...args) => {
          session.executor ||= executor(); return session.executor[method](...args);
        };
        session.server = createServer(facade);
        session.transport = new StreamableHTTPServerTransport({ sessionIdGenerator: randomUUID, enableJsonResponse: true,
          onsessioninitialized: newId => sessions.set(newId, session) });
        await session.server.connect(session.transport);
      } else {
        if (req.method !== 'POST') return send(res, 405, { error: 'No stateless stream or session to delete' });
        // Tunnel probes/tool calls may omit a session ID. Share the job registry,
        // but close only this request's protocol context afterwards.
        ephemeral = createServer(shared);
        const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined, enableJsonResponse: true });
        await ephemeral.connect(transport);
        await transport.handleRequest(req, res, body);
        return;
      }
      const executing = req.method !== 'GET';
      if (executing) session.active++;
      session.last = Date.now();
      if (body?.method === 'tools/call') session.used = true;
      try {
        if (req.method === 'DELETE') {
          if (session.active > 1) return send(res, 409, { error: 'Session has an active request' });
          await session.transport.handleRequest(req, res);
          await closeSession(id, session);
        } else await session.transport.handleRequest(req, res, body);
      } finally { if (executing) { session.active--; session.last = Date.now(); } }
    } catch {
      if (!res.headersSent) send(res, 500, { error: 'MCP request failed' });
      else if (!res.writableEnded) res.end();
    } finally {
      if (ephemeral) await ephemeral.close();
      if (acquired) activeRequests--;
    }
  });
  listener.requestTimeout = 15000;
  await new Promise((resolve, reject) => { listener.once('error', reject); listener.listen(port, '127.0.0.1', resolve); });
  const timer = setInterval(() => sweep().catch(() => {}), cleanupMs); timer.unref();
  return { url: `http://127.0.0.1:${listener.address().port}`, metrics, sweep,
    async close() {
      closing = true; clearInterval(timer);
      for (const [id, s] of sessions) await closeSession(id, s);
      await shared.close();
      listener.closeAllConnections();
      await new Promise(resolve => listener.close(resolve));
    } };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const app = await startHttp({ roots: process.env.CODEX_LOOP_WSL_ROOTS?.split(':').filter(Boolean),
    authorization: readFileSync(process.env.CODEX_LOOP_WSL_AUTH_FILE, 'utf8').trim(),
    port: Number(process.env.CODEX_LOOP_WSL_HTTP_PORT || 18790), maxRequests: Number(process.env.MCP_MAX_CONCURRENT_REQUESTS || 64) });
  console.log(JSON.stringify({ ready: true, url: app.url, ...app.metrics() }));
  const close = async () => { await app.close(); process.exit(0); };
  process.on('SIGTERM', close); process.on('SIGINT', close);
}
