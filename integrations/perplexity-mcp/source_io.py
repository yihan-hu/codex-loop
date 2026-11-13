#!/usr/bin/env python3
"""Fetch public source bytes or extract local PDF/DOCX text; never generate source prose."""
import argparse
import datetime
from html.parser import HTMLParser
import ipaddress
import json
import pathlib
import socket
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET


def project_path(raw):
    root=pathlib.Path.cwd().resolve();path=(root/raw).resolve()
    if not path.is_relative_to(root):raise ValueError('Source path escapes the current project')
    return path


def public_url(url):
    parsed=urllib.parse.urlsplit(url)
    if parsed.scheme not in ['http','https'] or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a public HTTP(S) source without embedded credentials')
    addresses=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):raise ValueError('Local/private network source URLs are not allowed')
    return url


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,request,fp,code,msg,headers,newurl):
        public_url(newurl)
        return super().redirect_request(request,fp,code,msg,headers,newurl)


class VisibleText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.skip=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ['script','style']:self.skip+=1
    def handle_endtag(self,tag):
        if tag in ['script','style']:self.skip=max(0,self.skip-1)
    def handle_data(self,data):
        if not self.skip and data.strip():self.parts.append(data.strip())


def extract(source,destination):
    source=project_path(source);destination=project_path(destination)
    if source==destination or destination.name.endswith('_Current.md'):raise ValueError('Extraction cannot replace its source or runtime-owned Current prose')
    raw=source.read_bytes()
    if raw.startswith(b'%PDF'):
        from pypdf import PdfReader
        reader=PdfReader(source);text='\n\n'.join(page.extract_text() or '' for page in reader.pages)
    elif source.suffix.lower()=='.docx':
        with zipfile.ZipFile(source) as archive:
            root=ET.fromstring(archive.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text='\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p',ns))
    else:
        text=raw.decode('utf-8-sig')
        if source.suffix.lower() in ['.html','.htm','.xml']:
            parser=VisibleText();parser.feed(text);text='\n'.join(parser.parts)
    if not text.strip():raise ValueError('Source preserved, but no extractable text is available; do not claim full-text reading')
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(text,encoding='utf-8')
    return {'source':str(source),'text_path':str(destination),'text_characters':len(text),'basis':'Actual local source extraction, not model-authored source text'}


def fetch(url,destination):
    destination=project_path(destination)
    relative=destination.relative_to(pathlib.Path.cwd().resolve())
    if not (relative.parts[:2] in [('.epi-prose','literature-sources'),('.epi-prose','plan-literature')] or relative.parts[:1] in [('plan-literature',),('.perplexity-sources',)]):raise ValueError('Public snapshots belong in a project source-archive directory')
    opener=urllib.request.build_opener(PublicRedirect)
    request=urllib.request.Request(public_url(url),headers={'User-Agent':'CodexLoop-LocalSkillSource/1.0'})
    with opener.open(request,timeout=45) as response:
        raw=response.read(50*1024*1024+1)
        if len(raw)>50*1024*1024:raise ValueError('Public source exceeds the 50 MiB transfer limit; no partial source was saved')
        final=response.url;content_type=response.headers.get('Content-Type','')
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
    result={'requested_url':url,'final_url':final,'raw_source':str(destination),'bytes':len(raw),'content_type':content_type,'fetched_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    manifest=destination.with_name(destination.name+'.source.json');manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    result['manifest']=str(manifest)
    if raw.startswith(b'%PDF') or destination.suffix.lower() in ['.html','.htm','.xml','.txt']:
        result.update(extract(str(destination),str(destination)+'.txt'))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['fetch','extract']);parser.add_argument('source');parser.add_argument('destination');args=parser.parse_args()
    print(json.dumps(fetch(args.source,args.destination) if args.action=='fetch' else extract(args.source,args.destination),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
