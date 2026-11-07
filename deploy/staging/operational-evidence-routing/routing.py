"""Pure, staging-only allowlist patch proposal. No remote/configuration writes."""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[3]
BASE=ROOT/'data/backups/private-staging-releases/phase-api-body-bound-20261102-v2/release'
MANIFEST_SHA='dc2fd9aa9cb0e961fd3859aa63b946a307c43f8a31ed6d8ac0ef4529c32f2045'
SOURCE='proposals/staging.powerflowenergy.dev.conf'
ROUTES=('/api/operations/current','/api/pipeline/current','/api/admin/operations/current')
PATTERN=r'if \(\$uri !~ "([^"\r\n]+)"\) \{ return 404; \}'

def need(ok,code):
    if not ok:raise ValueError(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def rule(raw):
    need(type(raw)is bytes and len(raw)<=65536 and b'\x00'not in raw,'CONFIG_BOUND')
    text=raw.decode('utf-8');matches=list(re.finditer(PATTERN,text))
    need(len(matches)==1 and text.count('server_name staging.powerflowenergy.dev;')==1 and text.count('location /api/ {')==1,'CONFIG_SCOPE')
    value=matches[0].group(1);need(value.startswith('^/api/') and value.endswith('$'),'RULE_ANCHOR')
    re.compile(value)
    return value
def approved():
    raw=(BASE/'release-manifest.json').read_bytes();need(sha(raw)==MANIFEST_SHA,'APPROVED_MANIFEST_HASH')
    m=json.loads(raw);source=(BASE/SOURCE).read_bytes()
    need(sha(source)==m['files'][SOURCE]['sha256'] and len(source)==m['files'][SOURCE]['bytes'],'APPROVED_CONFIG_HASH')
    rule(source);return source
def patch(raw):
    old=rule(approved());current=rule(raw)
    need(current==old,'UNEXPECTED_OR_ALREADY_UPDATED_ALLOWLIST')
    new=old
    for before,after in [('pipeline/status','pipeline/(status|current)'),('operations/summary','operations/(summary|current)'),('admin/(operations|','admin/(operations|operations/current|')]:
        need(new.count(before)==1,'ALLOWLIST_AMBIGUOUS');new=new.replace(before,after,1)
    result=raw.replace(old.encode(),new.encode(),1)
    need(rule(result)==new and all(re.fullmatch(new,path) for path in ROUTES),'ROUTING_PATCH_VERIFY')
    return result
