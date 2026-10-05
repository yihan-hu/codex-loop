import { randomUUID } from 'node:crypto';
import { readFileSync, realpathSync, statSync, lstatSync, existsSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
const canonicalLocation = file => {
  const parts = []; let parent = path.resolve(file);
  while (!existsSync(parent)) { parts.unshift(path.basename(parent)); parent = path.dirname(parent); }
  return path.join(realpathSync(parent), ...parts);
};
const inside = (child, parent) => child === parent || child.startsWith(parent + '/');
export const defaultProjectsFile = path.join(homedir(), '.config/codex-loop-wsl/projects.json');

// Local registration is outside the shell sandbox. Grant IDs are bearer
// capabilities; a task label is not authenticated ChatGPT identity.
export function createGrants({ projectsFile = defaultProjectsFile, now = Date.now } = {}) {
  const grants = new Map();
  function projects() {
    let file;
    try { file = lstatSync(projectsFile); if (file.isSymbolicLink()) throw new Error('Registry must not be a symlink.'); } catch (error) { if (error.code === 'ENOENT') return {}; throw error; }
    if ((file.mode & 0o077) || (process.getuid && file.uid !== process.getuid())) throw new Error('Project registry must be owner-only (chmod 600).');
    const value = JSON.parse(readFileSync(projectsFile, 'utf8'));
    if (!value.projects || Array.isArray(value.projects) || typeof value.projects !== 'object') throw new Error('Invalid project registry.');
    return value.projects;
  }
  function rootFor(project) {
    if (!project || !path.isAbsolute(project.path || '')) throw new Error('Project is not registered locally.');
    const root = realpathSync(project.path);
    if (!statSync(root).isDirectory() || ['/', '/home', homedir(), '/mnt', '/mnt/c', '/etc', '/usr', '/proc', '/dev', '/tmp'].includes(root)) throw new Error('Register a narrow existing project directory.');
    if (inside(canonicalLocation(projectsFile), root) || inside(canonicalLocation(path.join(homedir(), '.config')), root)) throw new Error('Project must not expose private connector configuration.');
    if (!['read-only', 'read-write'].includes(project.access)) throw new Error('Invalid project access.');
    return root;
  }
  function finish(id) {
    const grant = grants.get(id);
    if (!grant) return Promise.resolve();
    grants.delete(id); clearTimeout(grant.timer);
    return Promise.all([...grant.jobs].map(stop => stop()));
  }
  function get({ grant_id, task_id }) {
    const grant = grants.get(grant_id);
    if (!grant || grant.task_id !== task_id) throw new Error('Unknown grant or task mismatch; request authorization again.');
    if (now() >= grant.expires_at) { finish(grant_id); throw new Error('Grant expired; request authorization again.'); }
    try {
      const current = projects()[grant.project_id];
      if (rootFor(current) !== grant.root || current.access !== grant.registered_access) throw new Error('Local project registration changed; request authorization again.');
    } catch (error) { finish(grant_id); throw error; }
    return grant;
  }
  const view = grant => ({ grant_id: grant.grant_id, task_id: grant.task_id, project_id: grant.project_id,
    root: grant.root, access: grant.access, expires_at: new Date(grant.expires_at).toISOString() });
  return {
    list() { return Object.entries(projects()).map(([project_id, value]) => ({ project_id, access: value.access })); },
    assertHidden(roots) {
      if (roots.some(root => inside(canonicalLocation(projectsFile), realpathSync(root)))) throw new Error('Private project registry must be outside all sandbox roots.');
    },
    grant({ project_id, task_id, ttl_seconds = 3600, access = 'read-only' }) {
      if (!/^[A-Za-z0-9_-]{1,100}$/.test(project_id || '') || !/^[A-Za-z0-9_-]{1,128}$/.test(task_id || '')) throw new Error('Invalid project or task ID.');
      if (!Number.isInteger(ttl_seconds) || ttl_seconds < 1 || ttl_seconds > 86400) throw new Error('Grant lifetime must be 1–86400 seconds.');
      const project = projects()[project_id], root = rootFor(project);
      if (!['read-only', 'read-write'].includes(access) || (access === 'read-write' && project.access !== 'read-write')) throw new Error('Requested access exceeds local registration.');
      const grant = { grant_id: randomUUID(), project_id, task_id, root, access, registered_access: project.access,
        expires_at: now() + ttl_seconds * 1000, jobs: new Set() };
      grant.timer = setTimeout(() => finish(grant.grant_id), ttl_seconds * 1000); grant.timer.unref();
      grants.set(grant.grant_id, grant); return view(grant);
    },
    resolve: get,
    attach(grant, stop) { grant.jobs.add(stop); return () => grant.jobs.delete(stop); },
    async revoke(args) { get(args); await finish(args.grant_id); return { revoked: true, grant_id: args.grant_id }; },
    async close() { await Promise.all([...grants.keys()].map(finish)); },
  };
}
