#!/usr/bin/env python3
"""Start/inspect/stop just this connector; never restart the existing My Mac stack."""
import json, os, pathlib, plistlib, re, subprocess, sys, time, urllib.request, urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
CONFIG = json.loads((HERE / 'config.json').read_text())
STATE = pathlib.Path(CONFIG['stateDirectory'])
DOMAIN = f'gui/{os.getuid()}'
LABELS = ['local.yihan.perplexity-codex-loop.http', 'local.yihan.perplexity-codex-loop.tunnel']

def run(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True)

def loaded(label):
    return run('/bin/launchctl', 'print', f'{DOMAIN}/{label}', check=False).returncode == 0

def prepare():
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    commands = [
        [CONFIG['node'], '--disable-warning=ExperimentalWarning', str(HERE/'server.mjs'), '--http'],
        [CONFIG['cloudflared'], 'tunnel', '--url', f"http://127.0.0.1:{CONFIG['httpPort']}",
         '--http-host-header', f"localhost:{CONFIG['httpPort']}", '--no-autoupdate', '--protocol', 'http2'],
    ]
    for label, argv in zip(LABELS, commands):
        data = {'Label':label, 'ProgramArguments':argv, 'RunAtLoad':True, 'KeepAlive':True,
                'WorkingDirectory':str(HERE), 'EnvironmentVariables':{'TMPDIR':CONFIG['backendTempDirectory'], 'PATH':os.environ.get('PATH','/usr/bin:/bin')},
                'StandardOutPath':str(STATE/(label+'.log')), 'StandardErrorPath':str(STATE/(label+'.log'))}
        p = STATE/(label+'.plist'); p.write_bytes(plistlib.dumps(data)); p.chmod(0o600)

def probe(url):
    try:
        key = pathlib.Path(CONFIG['httpAuthFile']).read_text().strip()
        request = urllib.request.Request(url+'/healthz', headers={'Authorization':'Bearer '+key})
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status == 200
    except Exception:
        # A fresh Quick Tunnel name can remain negatively cached by macOS lookup().
        # curl --resolve preserves HTTPS certificate checks and the original Host/SNI.
        if not url.startswith('https://'): return False
        try:
            host = urllib.parse.urlparse(url).hostname
            dns_request = urllib.request.Request('https://cloudflare-dns.com/dns-query?name='+host+'&type=A', headers={'Accept':'application/dns-json'})
            with urllib.request.urlopen(dns_request,timeout=3) as response: dns = json.load(response)
            ip = next(a['data'] for a in dns.get('Answer',[]) if a['type']==1)
            observed = subprocess.run(['/usr/bin/curl','--silent','--show-error','--max-time','4','--resolve',f'{host}:443:{ip}',
                '--config','-','--output','/dev/null','--write-out','%{http_code}',url+'/healthz'],
                input='header = "Authorization: Bearer '+key+'"\n',capture_output=True,text=True)
            return observed.returncode==0 and observed.stdout=='200'
        except Exception: return False

def status():
    p = STATE/(LABELS[1]+'.log')
    urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com', p.read_text(errors='replace')) if p.exists() else []
    url = urls[-1] if urls else None
    ready = all(loaded(label) for label in LABELS) and bool(url) and probe(url)
    state = {'ready':ready, 'services_loaded':{label:loaded(label) for label in LABELS},
             'mcp_url':url+'/mcp' if url else None,
             'local_http_ready':probe(f"http://127.0.0.1:{CONFIG['httpPort']}"),
             'key_file':CONFIG['httpAuthFile'],
             'note':'Quick Tunnel URL changes after tunnel-process restart. Update the Perplexity connector then.'}
    (STATE/'connection.json').write_text(json.dumps(state, indent=2)+'\n')
    return state

def main():
    action = sys.argv[1] if len(sys.argv)>1 else 'status'
    if action == 'start':
        prepare()
        for label in LABELS:
            if not loaded(label): run('/bin/launchctl','bootstrap',DOMAIN,str(STATE/(label+'.plist')))
        for _ in range(45):
            observed = status()
            if observed['ready']: break
            time.sleep(0.5)
        print(json.dumps(observed, indent=2)); return 0 if observed['ready'] else 1
    if action == 'stop':
        for label in reversed(LABELS):
            if loaded(label): run('/bin/launchctl','bootout',f'{DOMAIN}/{label}')
        print('Stopped only the Perplexity connector HTTP service and HTTPS tunnel.'); return 0
    if action == 'status': print(json.dumps(status(),indent=2)); return 0
    raise SystemExit('Usage: manage.py start|status|stop')

if __name__ == '__main__': sys.exit(main())
