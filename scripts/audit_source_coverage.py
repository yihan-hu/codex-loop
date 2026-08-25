#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,re
from pathlib import Path
MOD_RE=re.compile(r"(?m)^\s*(?:pub(?:\([^\n)]*\))?\s+)?mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;")
PATHS={
 'core/src/lib.rs':'codex-rs/core/src/lib.rs',
 'core/src/tools/mod.rs':'codex-rs/core/src/tools/mod.rs',
 'core/src/session/mod.rs':'codex-rs/core/src/session/mod.rs',
 'core/src/tasks/mod.rs':'codex-rs/core/src/tasks/mod.rs',
 'core/src/unified_exec/mod.rs':'codex-rs/core/src/unified_exec/mod.rs',
}
def parse(path:Path): return sorted(set(MOD_RE.findall(path.read_text(encoding='utf-8'))))
def main():
 p=argparse.ArgumentParser(); p.add_argument('--upstream'); args=p.parse_args(); skill=Path(__file__).resolve().parents[1]; data=json.loads((skill/'references/source-map.yaml').read_text()); errors=[]
 for scope,mapping in data['coverage_scopes'].items():
  if not mapping: errors.append(f'{scope}: empty mapping')
  if args.upstream:
   actual=parse(Path(args.upstream)/PATHS[scope]); expected=sorted(mapping)
   missing=sorted(set(actual)-set(expected)); stale=sorted(set(expected)-set(actual))
   if missing: errors.append(f'{scope}: unclassified upstream modules: {missing}')
   if stale: errors.append(f'{scope}: mapped modules absent upstream: {stale}')
 local_ports=[x['local'] for x in data.get('ports',[])]
 exact_resources=[x['local'] for x in data.get('exact_resources',[])]
 runtime_modules=data.get('runtime_modules',{})
 runtime_dir=skill/'scripts/codex_loop_runtime'
 actual_runtime=sorted(str(p.relative_to(skill)) for p in runtime_dir.glob('*.py') if p.name!='__init__.py')
 mapped_runtime=sorted(runtime_modules)
 missing_runtime=sorted(set(actual_runtime)-set(mapped_runtime)); stale_runtime=sorted(set(mapped_runtime)-set(actual_runtime))
 if missing_runtime: errors.append(f'unclassified local runtime modules: {missing_runtime}')
 if stale_runtime: errors.append(f'mapped local runtime modules absent from tree: {stale_runtime}')
 for rel in local_ports+exact_resources:
  if not (skill/rel).is_file(): errors.append(f'mapped local implementation missing: {rel}')
 contract=set(data.get('classification_contract',{}))
 for rel,mode in runtime_modules.items():
  if mode not in contract: errors.append(f'{rel}: unknown runtime module classification mode {mode}')
 for scope,mapping in data['coverage_scopes'].items():
  for module,mode in mapping.items():
   if mode not in contract: errors.append(f'{scope}:{module}: unknown classification mode {mode}')
 for entry in data.get('ports',[]):
  mode=entry.get('mode')
  local=entry.get('local')
  if mode not in contract: errors.append(f"{local}: unknown port mode {mode}")
  runtime_mode=runtime_modules.get(local)
  if runtime_mode is not None and runtime_mode != mode:
   errors.append(f"{local}: port mode {mode} conflicts with runtime_modules mode {runtime_mode}")
  tests=entry.get('tests',{})
  if not isinstance(tests,dict):
   errors.append(f"{entry.get('local')}: tests must separate local/upstream lineage")
   continue
  for rel in tests.get('local',[]):
   if not (skill/rel).is_file(): errors.append(f"{entry.get('local')}: local compatibility test missing: {rel}")
  for rel in tests.get('upstream',[]):
   if not str(rel).startswith('codex-rs/'):
    errors.append(f"{entry.get('local')}: invalid upstream test lineage: {rel}")
 result={'ok':not errors,'audited_commit':data['upstream']['audited_commit'],'scopes':{k:len(v) for k,v in data['coverage_scopes'].items()},'mapped_ports':len(local_ports),'runtime_modules':len(mapped_runtime),'exact_resources':len(exact_resources),'errors':errors}
 print(json.dumps(result,sort_keys=True))
 raise SystemExit(0 if not errors else 1)
if __name__=='__main__': main()
