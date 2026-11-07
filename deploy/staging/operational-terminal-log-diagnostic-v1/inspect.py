"""Fixed file/window only; no helper execution, HTTP, database or publisher calls."""
import datetime as dt
import json
import os
import re
import stat
import time

FLOW='01a1b4fd-6f22-7738-8410-7df4e9e73e60'
PIPELINE='3dd2ddfda3b34b1c982a0d7c5342b222'
PREFIX='Operational evidence terminal delivery: '
STATUSES={'PUBLISHED','SKIPPED_DUPLICATE','SKIPPED_OLDER_RUN','FAILED','DISABLED','SKIPPED_NOT_NATURAL'}
REASONS={'CAPTURE_UNVERIFIED','OPERATIONAL_STORE_UNCERTAIN','IMMUTABLE_RUNTIME_UNVERIFIED','EVIDENCE_REJECTED','CAPTURE_OR_STORE_UNVERIFIED','TERMINAL_CAPTURE_UNVERIFIED','HOOK_UNAVAILABLE','UNSUPPORTED_TERMINAL_STATE'}
HEADER=re.compile(rb'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}')
CLASSES={'NameError','AttributeError','TypeError','ImportError','ModuleNotFoundError','PermissionError','FileNotFoundError','TimeoutError','ValueError','RuntimeError'}


def window():
    # Report system-local offset rather than silently asserting the worker timezone.
    start=dt.datetime(2026,11,7,8,47,30,tzinfo=dt.timezone.utc).timestamp()
    end=start+30
    return (dt.datetime.fromtimestamp(start).strftime('%Y-%m-%d %H:%M:%S,000'),dt.datetime.fromtimestamp(end).strftime('%Y-%m-%d %H:%M:%S,000'),time.localtime(start).tm_gmtoff)


def project(raw,start,end):
    out=[];context=False
    for line in raw.splitlines():
        if HEADER.match(line):
            context=False;stamp=line[:23].decode('ascii')
            if not start<=stamp<=end:continue
            text=line.decode('utf8',errors='replace');parts=text.split(' - ',3)
            if len(parts)!=4:continue
            message=parts[3]
            context=PREFIX in message or '_operational_evidence_terminal_hook' in message
            if not context:continue
            item={'log_timestamp':stamp,'kind':'HOOK_EXCEPTION_OR_CONTEXT'}
            if message.startswith(PREFIX):
                try:value=json.loads(message[len(PREFIX):])
                except Exception:value=None
                if type(value)is dict and set(value)<={'status','reason'} and value.get('status')in STATUSES and ('reason'not in value or value['reason']in REASONS):item.update(kind='TERMINAL_RESULT',**value)
                else:item['kind']='UNRECOGNIZED_TERMINAL_RESULT'
            item['exception_classes']=sorted(x for x in CLASSES if re.search(r'\b'+x+r':',message))
            item['approved_symbols']=[x for x in ['json','logger','os','notify'] if "name '"+x+"' is not defined" in message]
            out.append(item)
        elif context and out:
            text=line.decode('utf8',errors='replace')
            out[-1]['exception_classes']=sorted(set(out[-1]['exception_classes'])|{x for x in CLASSES if re.search(r'\b'+x+r':',text)})
            for x in ['json','logger','os','notify']:
                if "name '"+x+"' is not defined" in text and x not in out[-1]['approved_symbols']:out[-1]['approved_symbols'].append(x)
        PLAN.need(len(out)<=16,'RESULT_BOUND')
    return out


def read_window(fd,size,start,end):
    # Bounded timestamp-header seek. Probe messages are never decoded or returned.
    budget=[0];samples={}
    def pread(n,offset):
        budget[0]+=n;PLAN.need(budget[0]<=2*1024*1024,'READ_BOUND')
        return os.pread(fd,n,offset)
    def header(offset):
        data=pread(min(65536,size-offset),offset)
        begin=0 if offset==0 else data.find(b'\n')+1
        PLAN.need(begin>0 or offset==0,'LINE_BOUND')
        for _ in range(100):
            if HEADER.match(data[begin:begin+23]):return offset+begin,data[begin:begin+23].decode('ascii')
            next_=data.find(b'\n',begin)
            if next_<0:return None
            begin=next_+1
        return None
    lo=0;hi=size
    for _ in range(24):
        if hi-lo<=32768:break
        mid=(lo+hi)//2;entry=header(mid)
        PLAN.need(entry is not None,'TIMESTAMP_SEEK_UNVERIFIED')
        pos,stamp=entry;samples[pos]=stamp
        ordered=sorted(samples.items());PLAN.need(all(a[1]<=b[1] for a,b in zip(ordered,ordered[1:])),'TIMESTAMP_ORDER_UNVERIFIED')
        if stamp<start:lo=max(mid+1,pos)
        else:hi=mid
    begin=max(0,lo-65536);stop=min(size,hi+262144)
    raw=pread(stop-begin,begin)
    if begin:raw=raw[raw.find(b'\n')+1:]
    if stop<size:
        final=raw.rfind(b'\n');PLAN.need(final>=0,'LINE_BOUND');raw=raw[:final]
    stamps=[line[:23].decode('ascii') for line in raw.splitlines() if HEADER.match(line)]
    PLAN.need(stamps and stamps[0]<=start and (stamps[-1]>=end or stop==size),'WINDOW_NOT_COVERED')
    return raw,budget[0]


def inspect():
    P=PREFLIGHT;P.safe(P.PRODUCTION/'logs',(0,1000))
    parent=CAPTURE.directory(P.PRODUCTION/'logs')
    fd=None
    try:
        fd=os.open('pipeline.log',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_NOATIME,dir_fd=parent)
        before=os.fstat(fd)
        PLAN.need(stat.S_ISREG(before.st_mode) and before.st_uid==before.st_gid==1000 and before.st_nlink==1 and stat.S_IMODE(before.st_mode) in {0o600,0o640,0o644} and before.st_size<=512*1024*1024,'LOG_METADATA')
        start,end,offset=window();raw,read_bytes=read_window(fd,before.st_size,start,end)
        result=project(raw,start,end)
        PLAN.need(CAPTURE.signature(before)==CAPTURE.signature(os.fstat(fd))==CAPTURE.signature(os.stat('pipeline.log',dir_fd=parent,follow_symlinks=False)),'LOG_CHANGED')
        return {'status':'PASS','changed':False,'run_id':FLOW,'pipeline_run_id':PIPELINE,'window_utc':['2026-11-07T08:47:30Z','2026-11-07T08:48:00Z'],'system_timezone_offset_seconds':offset,'entries':result,'read_bytes_bound':read_bytes,'association':'MATCHED_HOOK_TIME_WINDOW_NO_FLOW_ID_IN_RESULT','result_found':any(x['kind']=='TERMINAL_RESULT' for x in result)}
    finally:
        if fd is not None:os.close(fd)
        os.close(parent)
