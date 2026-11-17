"""Read-only diagnostic overlay; original release and all prerequisites unchanged."""
import json

CHILD_FIELDS={'status','stage','category','exception','candidate_module','module','import_name','line','audit_event','cause_exception','errno'}
STAGES={'BOOTSTRAP','RUNTIME_IDENTITY','AUDIT_SETUP','SOURCE_BINDING','LOADER_SETUP','API_IMPORT','POLICY_CHECK','SCHEMA_CHECK','ROUTES_CHECK','COMPLETE'}
CATEGORIES={'IMPORT_PASS','UNCLASSIFIED_FAILURE','MODULE_MISSING','IMPORT_ERROR','PERMISSION_DENIED','FILE_MISSING','ASSERTION_FAILED','ATTRIBUTE_ERROR','TYPE_ERROR','VALUE_ERROR','MEMORY_ERROR','OS_ERROR','UNEXPECTED_EXIT','RUNTIME_VERSION_MISMATCH','IDENTITY_MISMATCH','FILESYSTEM_WRITE_BLOCKED','SIDE_EFFECT_BLOCKED','UNEXPECTED_STDOUT','CHILD_OUTPUT_LIMIT','SCHEMA_ERROR'}
EXCEPTIONS={'ModuleNotFoundError','ImportError','PermissionError','FileNotFoundError','AssertionError','RuntimeError','AttributeError','TypeError','ValueError','OSError','MemoryError','SystemExit','UNCLASSIFIED_EXCEPTION','NameError','SyntaxError','UnicodeDecodeError','RecursionError','PydanticUserError','PydanticSchemaGenerationError','PydanticUndefinedAnnotation','SchemaError','ValidationError','PydanticImportError','FastAPIError','PydanticInvalidForJsonSchema'}
EVENTS={'open','socket.connect','socket.bind','subprocess.Popen','os.system','os.mkdir','os.remove','os.rename','os.chmod','os.chown','os.symlink','os.link'}

def empty(category):
    return dict(status='BLOCKED',stage='CHILD_STARTUP',category=category,exception=None,candidate_module=None,module=None,import_name=None,line=None,audit_event=None,cause_exception=None,errno=None)
def classify(result):
    # Never serialize or persist raw child stderr. Interpret only fixed startup
    # markers if no trustworthy structured child result exists.
    if result['failure']in {'TIMEOUT','OUTPUT_LIMIT'}:return empty('CHILD_'+result['failure'])
    if type(result['returncode'])is int and result['returncode']<0:return empty('CHILD_SIGNAL')
    try:
        need(len(result['stdout'])<=4096,'CHILD_REPORT_BOUND')
        report=json.loads(result['stdout'])
        need(result['stdout']==json.dumps(report,sort_keys=True).encode()+b'\n','CHILD_STDOUT_SHAPE')
        need(type(report)is dict and set(report)==CHILD_FIELDS,'CHILD_REPORT_SCHEMA')
        need(report['status']in {'PASS','BLOCKED'} and report['stage']in STAGES and report['category']in CATEGORIES,'CHILD_REPORT_SCHEMA')
        need(all(report[k]is None or report[k]in EXCEPTIONS for k in ['exception','cause_exception']),'CHILD_REPORT_SCHEMA')
        need(report['audit_event']is None or report['audit_event']in EVENTS,'CHILD_REPORT_SCHEMA')
        need(report['line']is None or type(report['line'])is int and 0<report['line']<100000,'CHILD_REPORT_SCHEMA')
        need(report['errno']is None or type(report['errno'])is int and 0<report['errno']<256,'CHILD_REPORT_SCHEMA')
        for key in ['candidate_module','module','import_name']:
            value=report[key]
            need(value is None or value=='REDACTED_MODULE' or value in MODULES or value in STDLIB or type(value)is str and len(value)<=120 and __import__('re').fullmatch(r'[a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)*',value) and value.split('.')[0]in DEPENDENCIES and not __import__('re').search('token|password|credential|secret|private',value),'CHILD_MODULE_SCOPE')
        need(report['candidate_module']is None or report['candidate_module']in MODULES,'CHILD_CANDIDATE_SCOPE')
        need((result['returncode']==0)==(report['status']=='PASS') and (report['status']!='PASS' or report['stage']=='COMPLETE' and report['category']=='IMPORT_PASS' and report['exception']is None),'CHILD_EXIT_MISMATCH')
        return report
    except Exception:
        stderr=result['stderr']
        if b'nsenter:'in stderr and any(v in stderr for v in [b'Operation not permitted',b'Permission denied']):return empty('NAMESPACE_ENTRY_DENIED')
        if b'setpriv:'in stderr:return empty('IDENTITY_LAUNCH_FAILED')
        if b'No such file or directory'in stderr:return empty('EXECUTABLE_OR_NAMESPACE_MISSING')
        return empty('CHILD_OUTPUT_UNVERIFIED')

def inspect():
    result={}
    def probe(venv):
        pid=int(JOB.B['services']()[JOB.H.OLD_PLAN.UNIT]['MainPID']);need(pid>1,'CANDIDATE_PID')
        argv=['/usr/bin/nsenter','--mount=/proc/'+str(pid)+'/ns/mnt','--','/usr/bin/setpriv','--no-new-privs','--reuid=992','--regid=992','--clear-groups',str(venv/'bin/python'),'-I','-B','-']
        child=JOB.B['bounded_run'](argv,input=CHILD,timeout=20,limit=8192,grace=5)
        result.update(classify(child))
        result['child_exit_status']=child['returncode']
        need(result['status']=='PASS','CANDIDATE_IMPORT_COMPATIBILITY')
    original_probe=JOB.import_probe
    JOB.import_probe=probe # In-memory reporting overlay only; never original code.
    try:
        JOB.fresh() # All original preconditions; no transaction is created.
        return dict(result,changed=False,release=RELEASE,parent_manifest=PARENT_SHA,child_status=result['status'])
    except Exception as error:
        if result and result['status']=='BLOCKED':return dict(result,changed=False,release=RELEASE,parent_manifest=PARENT_SHA,child_status='BLOCKED')
        reason=str(error) if isinstance(error,(PLAN.Stop,GUARD.Stop,HELPER.OP.InvalidEvidence)) else 'UNVERIFIED_PREREQUISITE'
        if not __import__('re').fullmatch('[A-Z0-9_]{1,80}',reason):reason='UNVERIFIED_PREREQUISITE'
        return dict(empty(reason),stage='RELEASE_PREREQUISITE',changed=False,release=RELEASE,parent_manifest=PARENT_SHA,child_status='PASS' if result else 'NOT_REACHED',child_exit_status=result.get('child_exit_status'))
    finally:JOB.import_probe=original_probe
