"""Strict, source-bound response framing. Error details contain no input values."""
import json
import re

VERSION=2
LIMIT=8192
DERIVED={'PROBE_GROUP_CONTEXT_DIFFERENCE','PRODUCER_TRAVERSAL_MODE_DENIED','PRODUCER_TRAVERSAL_OS_POLICY_DENIED'}
# Exact additional outputs of the immutable V1 child_result(), not arbitrary
# exceptions or success aliases. Each is necessarily a BLOCKED observation.
SUPERVISOR_RESULTS={'PRODUCER_PROBE_TIMEOUT','PRODUCER_PROBE_OUTPUT_LIMIT','PRODUCER_INTERPRETER_EXECUTION_FAILED','PRODUCER_PRIVILEGE_DROP_FAILED','PRODUCER_PYTHON_STARTUP_FAILED','PRODUCER_PROBE_OUTPUT_UNVERIFIED'}
FIELDS={'FRAME','REPORT','status','changed','reason','stage','errno','producer_probe','failed_path_id','worker_primary_identity','worker_groups_match_cleared_probe','worker_api_reader_group_present','directories','DIAGNOSTIC_ID','PROTOCOL_VERSION','EXIT_STATUS'}
STAGES={'BYTES','UTF8','JSON','FRAME','REPORT','DIRECTORY','CONSISTENCY','EXIT_STATUS'}
CODES={'INVALID_BYTES','EMPTY_STDOUT','OUTPUT_BOUND','INVALID_UTF8','INVALID_JSON','DUPLICATE_JSON_KEY','NONFINITE_JSON','JSON_DEPTH','FRAME_FIELDS','FRAME_VERSION','FRAME_BINDING','REPORT_FIELDS','STATUS','CHANGED','REASON','STAGE','ERRNO','PRODUCER_RESULT','PATH_ID','PRIMARY_IDENTITY','GROUP_FLAGS','DIRECTORY_COUNT','DIRECTORY_FIELDS','DIRECTORY_ORDER','DIRECTORY_OWNER','DIRECTORY_GROUP','DIRECTORY_MODE','DIRECTORY_SEARCH_FLAG','STATUS_CONSISTENCY','PRODUCER_CONSISTENCY','GROUP_CONSISTENCY','PATH_CONSISTENCY','DENIAL_CONSISTENCY','EXIT_STATUS_MISMATCH'}

class Rejected(ValueError):
    def __init__(self,stage,code,field='REPORT'):
        # Only constants/approved identifiers are ever constructed here.
        super().__init__('DIAGNOSTIC_OUTPUT_UNVERIFIED')
        self.stage=stage if stage in STAGES else'REPORT'
        self.code=code if code in CODES else'REPORT_FIELDS'
        approved=field in FIELDS or bool(re.fullmatch(r'(FILESYSTEM_ROOT|SERVICE_DATA_PARENT|REPORT_STORE_PARENT)\.(path_id|owner|group|mode|cleared_producer_mode_allows_search)',field))
        self.field=field if approved else'REPORT'
    def safe(self):return {'stage':self.stage,'code':self.code,'field':self.field}

def check(ok,stage,code,field='REPORT'):
    if not ok:raise Rejected(stage,code,field)

def report(value,schema):
    base={'status','changed','reason','stage','errno'}
    normal=base|{'producer_probe','failed_path_id','worker_primary_identity','worker_groups_match_cleared_probe','worker_api_reader_group_present','directories'}
    check(type(value)is dict and set(value)in [base,normal],'REPORT','REPORT_FIELDS')
    check(type(value['status'])is str and value['status']in {'PASS','BLOCKED'},'REPORT','STATUS','status')
    check(value['changed']is False,'REPORT','CHANGED','changed')
    check(type(value['reason'])is str and value['reason']in schema.REASONS,'REPORT','REASON','reason')
    check(type(value['stage'])is str and value['stage']in schema.STAGES,'REPORT','STAGE','stage')
    check(value['errno']is None or type(value['errno'])is int and value['errno']in {1,2,13,20,40,95},'REPORT','ERRNO','errno')
    if set(value)==base:
        check(value['status']=='BLOCKED'and value['reason']!='TRAVERSAL_PASS','CONSISTENCY','STATUS_CONSISTENCY','status')
        return value
    check(type(value['producer_probe'])is str and value['producer_probe']in schema.CHILD_CODES|SUPERVISOR_RESULTS,'REPORT','PRODUCER_RESULT','producer_probe')
    check(type(value['failed_path_id'])is str and value['failed_path_id']in {*schema.LABELS,'NONE'},'REPORT','PATH_ID','failed_path_id')
    check(value['worker_primary_identity']=='MATCH','REPORT','PRIMARY_IDENTITY','worker_primary_identity')
    match=value['worker_groups_match_cleared_probe'];reader=value['worker_api_reader_group_present']
    check(type(match)is bool and type(reader)is bool,'REPORT','GROUP_FLAGS','worker_groups_match_cleared_probe')
    check(not(match and reader),'CONSISTENCY','GROUP_CONSISTENCY','worker_api_reader_group_present')
    dirs=value['directories'];check(type(dirs)is list and len(dirs)==3,'DIRECTORY','DIRECTORY_COUNT','directories')
    for label,row in zip(schema.LABELS,dirs):
        check(type(row)is dict and set(row)=={'path_id','owner','group','mode','cleared_producer_mode_allows_search'},'DIRECTORY','DIRECTORY_FIELDS',label+'.path_id')
        check(row['path_id']==label,'DIRECTORY','DIRECTORY_ORDER',label+'.path_id')
        check(row['owner']=='ROOT','DIRECTORY','DIRECTORY_OWNER',label+'.owner')
        check(type(row['group'])is str and row['group']in {'ROOT_GROUP','PRODUCER_GROUP','API_READER_GROUP','OTHER'},'DIRECTORY','DIRECTORY_GROUP',label+'.group')
        check(type(row['mode'])is str and re.fullmatch('[0-7]{4}',row['mode'])is not None,'DIRECTORY','DIRECTORY_MODE',label+'.mode')
        mode=int(row['mode'],8);check(not mode&0o022,'DIRECTORY','DIRECTORY_MODE',label+'.mode')
        # Mode-bit prediction is distinct from actual X_OK (ACLs can grant access).
        expected=bool(mode&(0o010 if row['group']=='PRODUCER_GROUP'else 0o001))
        check(type(row['cleared_producer_mode_allows_search'])is bool and row['cleared_producer_mode_allows_search']==expected,'DIRECTORY','DIRECTORY_SEARCH_FLAG',label+'.cleared_producer_mode_allows_search')
    success=value['reason']=='TRAVERSAL_PASS'
    check((value['status']=='PASS')==success,'CONSISTENCY','STATUS_CONSISTENCY','status')
    check(value['stage']=='COMPLETE','CONSISTENCY','STATUS_CONSISTENCY','stage')
    if success:
        check(value['producer_probe']=='TRAVERSAL_PASS'and value['failed_path_id']=='NONE'and value['errno']is None,'CONSISTENCY','PRODUCER_CONSISTENCY','producer_probe')
    elif value['reason']in DERIVED:
        check(value['producer_probe']=='PRODUCER_TRAVERSAL_DENIED'and value['failed_path_id']in schema.LABELS,'CONSISTENCY','PRODUCER_CONSISTENCY','producer_probe')
        row=dirs[schema.LABELS.index(value['failed_path_id'])];allows=row['cleared_producer_mode_allows_search']
        check(allows==(value['reason']=='PRODUCER_TRAVERSAL_OS_POLICY_DENIED'),'CONSISTENCY','DENIAL_CONSISTENCY','reason')
        if value['reason']=='PROBE_GROUP_CONTEXT_DIFFERENCE':check(match is False,'CONSISTENCY','GROUP_CONSISTENCY','worker_groups_match_cleared_probe')
    else:check(value['reason']==value['producer_probe']and value['producer_probe']!='TRAVERSAL_PASS','CONSISTENCY','PRODUCER_CONSISTENCY','producer_probe')
    return value

def decode(raw,returncode,schema,expected_id):
    check(type(raw)is bytes,'BYTES','INVALID_BYTES','FRAME')
    check(bool(raw),'BYTES','EMPTY_STDOUT','FRAME');check(len(raw)<=LIMIT,'BYTES','OUTPUT_BOUND','FRAME')
    try:text=raw.decode('utf-8','strict')
    except UnicodeError:raise Rejected('UTF8','INVALID_UTF8','FRAME')from None
    def unique(items):
        out={}
        for key,value in items:
            check(key not in out,'JSON','DUPLICATE_JSON_KEY','FRAME');out[key]=value
        return out
    def constant(_):raise Rejected('JSON','NONFINITE_JSON','FRAME')
    try:frame=json.loads(text,object_pairs_hook=unique,parse_constant=constant)
    except Rejected:raise
    except RecursionError:raise Rejected('JSON','JSON_DEPTH','FRAME')from None
    except (ValueError,TypeError):raise Rejected('JSON','INVALID_JSON','FRAME')from None
    check(type(frame)is dict and set(frame)=={'protocol_version','diagnostic_id','report'},'FRAME','FRAME_FIELDS','FRAME')
    check(type(frame['protocol_version'])is int and frame['protocol_version']==VERSION,'FRAME','FRAME_VERSION','PROTOCOL_VERSION')
    check(type(frame['diagnostic_id'])is str and re.fullmatch('[0-9a-f]{64}',frame['diagnostic_id'])is not None and frame['diagnostic_id']==expected_id,'FRAME','FRAME_BINDING','DIAGNOSTIC_ID')
    accepted=report(frame['report'],schema)
    if type(returncode)is not int or returncode!=(0 if accepted['status']=='PASS'else 1):
        error=Rejected('EXIT_STATUS','EXIT_STATUS_MISMATCH','EXIT_STATUS');error.candidate=accepted;raise error
    return accepted
