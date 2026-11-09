"""Pure ACL policy: one named user, unchanged mask and every unrelated entry."""
import hashlib
import json
import re

UID=1000;GID=1000;OWNER=0;READER_GID=992;MODE=0o750
ROOT_PATH='/srv/powerflow'
CHILDREN=('published','forecast-publications','operational-publications')
PHASE='READ_ONLY';CHANGED=False
class Stop(ValueError):pass

def need(ok,code):
    if not ok:raise Stop(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encode(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def permissions(value):
    need(type(value)is str and re.fullmatch('[r-][w-][x-]',value)is not None,'ACL_TEXT_INVALID')
    return (4 if value[0]=='r'else 0)|(2 if value[1]=='w'else 0)|(1 if value[2]=='x'else 0)
def permtext(value):return ''.join(c if value&b else'-'for b,c in [(4,'r'),(2,'w'),(1,'x')])

def parse(text):
    need(type(text)is str and 0<len(text)<=8192 and '\x00'not in text,'ACL_TEXT_INVALID')
    rows=text.splitlines();need(3<=len(rows)<=128,'ACL_ENTRY_BOUND');out={}
    for line in rows:
        parts=line.split(':');need(len(parts)==3,'ACL_TEXT_INVALID');tag,qualifier,rights=parts
        need(tag in {'user','group','mask','other'},'ACL_TEXT_INVALID')
        need(not qualifier or tag in {'user','group'}and re.fullmatch('0|[1-9][0-9]{0,9}',qualifier)is not None and int(qualifier)<2**32-1,'ACL_QUALIFIER_INVALID')
        key=(tag,qualifier);need(key not in out,'ACL_DUPLICATE_ENTRY');out[key]=permissions(rights)
    need({('user',''),('group',''),('other','')}<=set(out),'ACL_BASE_ENTRIES_MISSING')
    if any(q for _,q in out):need(('mask','')in out,'ACL_MASK_MISSING')
    return out

def render(entries):
    order={'user':0,'group':1,'mask':2,'other':3}
    return ''.join(tag+':'+q+':'+permtext(entries[(tag,q)])+'\n'for tag,q in sorted(entries,key=lambda k:(order[k[0]],-1 if not k[1]else int(k[1]))))

def effective(entries,uid,gids,owner=OWNER,group=READER_GID):
    # Bitwise single-permission rights, sufficient for separate R_OK/W_OK/X_OK
    # probes. No claims about combining rights across separate group entries.
    if uid==owner:return entries[('user','')]
    mask=entries.get(('mask',''),7)
    if ('user',str(uid))in entries:return entries[('user',str(uid))]&mask
    matching=[]
    if group in gids:matching.append(entries[('group','')])
    matching.extend(p for(tag,q),p in entries.items()if tag=='group'and q and int(q)in gids)
    if matching:
        rights=0
        for p in matching:rights|=p
        return rights&mask
    return entries[('other','')]

def mode_of(entries):
    return entries[('user','')]<<6|entries.get(('mask',''),entries[('group','')])<<3|entries[('other','')]

def plan(text,worker_groups=()):
    old=parse(text);need(mode_of(old)==MODE,'ACL_MODE_MISMATCH')
    need(effective(old,UID,{GID})==0 and effective(old,UID,{GID,*worker_groups})==0,'PRODUCER_EXISTING_ACCESS_NOT_DENIED')
    need(('user',str(UID))not in old or old[('user',str(UID))]==0,'ACL_TARGET_ENTRY_UNSUPPORTED')
    new=dict(old);new[('user',str(UID))]=1
    # If minimal ACL had no mask, use its existing owning-group bits exactly.
    new.setdefault(('mask',''),old[('group','')])
    need(new[('mask','')]==old.get(('mask',''),old[('group','')])and mode_of(new)==MODE,'ACL_MASK_OR_MODE_CHANGE')
    need(effective(new,UID,{GID})==1,'ACL_SEARCH_ONLY_PLAN_INVALID')
    need(all(new[key]==value for key,value in old.items()if key!=('user',str(UID))),'ACL_UNRELATED_ENTRY_CHANGE')
    need(set(new)-set(old)<={('user',str(UID)),('mask','')},'ACL_SCOPE')
    return render(new)

def verify_plan(before,after,worker_groups=()):
    need(parse(after)==parse(plan(before,worker_groups)),'ACL_NOT_EXACT_PLANNED_STATE')


def deny_boundary(text,worker_groups=()):
    entries=parse(text)
    need(effective(entries,UID,{GID})==effective(entries,UID,{GID,*worker_groups})==0,'PROTECTED_BOUNDARY_PERMISSIONS_EXPOSE_PRODUCER')


def deny_default(text,worker_groups=()):
    if text is not None:
        entries=parse(text)
        need(effective(entries,UID,{GID})==effective(entries,UID,{GID,*worker_groups})==0,'DEFAULT_ACL_ISOLATION_UNPROVEN')
