"""Pure fixed-scope reporting policy; no filesystem or network calls."""
import copy
import hashlib
import json
import re

FLAG='POWERFLOW_REALIZED_REPORT_ENABLED'
ROOT_KEY='POWERFLOW_REALIZED_REPORT_ROOT'
MARKER=b'powerflow-realized-performance-v1\n'
PHASE='READ_ONLY';CHANGED=False;PREFLIGHT_STAGE='HOST'

def need(ok,code):
    if not ok:raise ValueError(code)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def environment(raw):
    need(type(raw)is bytes and len(raw)<=65536,'ENV_BOUND')
    need(not any(re.match(rb'\s*(?:export\s+)?POWERFLOW_REALIZED_REPORT_ROOT\s*=',line)for line in raw.splitlines()),'REPORT_ENV_ALREADY_CONFIGURED')
    return raw+(b''if raw.endswith(b'\n')else b'\n')+(ROOT_KEY+'='+C['root']+'\n').encode()
def variables(old):
    need(type(old)is dict and len(json.dumps(old))<=16384,'VARIABLE_BOUND')
    env=old.get('env',{});need(type(env)is dict and all(type(k)is str and type(v)is str for k,v in env.items()),'VARIABLE_ENV')
    need(FLAG not in env and ROOT_KEY not in env,'REPORT_FLAG_ALREADY_CONFIGURED')
    need(env.get('POWERFLOW_OPERATIONAL_EVIDENCE_ENABLED')==env.get('POWERFLOW_AUTO_PUBLICATION_ENABLED')=='true','EXISTING_DELIVERY_FLAGS')
    new=copy.deepcopy(old);new.setdefault('env',{}).update({FLAG:'true',ROOT_KEY:C['root']});return new

class ImportProbeFailure(ValueError):
    def __init__(self,code,module,cause):
        super().__init__(code)
        names=set(C.get('worker_closure',{}))|{'UNVERIFIED'}
        for key in C.get('files',{}):
            if key.startswith('api/src/')and key.endswith('.py'):names.add(key[8:-3].replace('/','.').removesuffix('.__init__'))
        self.approved_module=module if module in names else'UNVERIFIED'
        self.cause_class=cause if cause in {'AssertionError','ModuleNotFoundError','ImportError','AttributeError','RuntimeError','PermissionError','FileNotFoundError','TypeError','ValueError'}else'OTHER'


def error_detail(error):
    # Messages are never retained. Only our fixed uppercase gates, exception
    # class, approved module/substep and numeric errno can leave the process.
    reason=str(error)if isinstance(error,(ValueError,OLD.H.OP.InvalidEvidence,OLD.H.OLD_PLAN.Stop))else''
    if reason not in C.get('failure_gates',[]):reason='UNVERIFIED_HOST_OPERATION'
    category=type(error).__name__
    if category not in {'ValueError','Stop','InvalidEvidence','FileNotFoundError','PermissionError','OSError','ImportError','ModuleNotFoundError','AttributeError','AssertionError','TypeError','RuntimeError','DependencyInventoryFailure'}:category='OTHER'
    trace=error.__traceback__;operation='UNVERIFIED';line=0
    while trace:
        if trace.tb_frame.f_code.co_filename.startswith('<verified-realized-'):
            operation=trace.tb_frame.f_code.co_name;line=trace.tb_lineno
        trace=trace.tb_next
    if re.fullmatch('[a-zA-Z_][a-zA-Z_0-9]{0,63}',operation)is None:operation='UNVERIFIED'
    result={'reason':reason,'exception_class':category,'operation':operation,'line':line}
    if isinstance(error,ImportProbeFailure):result.update(approved_module=error.approved_module,cause_class=error.cause_class)
    if isinstance(error,DependencyInventoryFailure):result['dependency_issues']=error.dependency_issues
    if PHASE=='READ_ONLY':result['preflight_stage']=PREFLIGHT_STAGE
    return result
def failure_report(error):
    return {'status':'FAILED'if CHANGED else'BLOCKED','phase':PHASE,'changed':CHANGED,**error_detail(error)}


class DependencyInventoryFailure(ValueError):
    """Fixed manifest-relative issues only; never retain raw OS exception text."""
    def __init__(self,issues):
        allowed=set(C.get('worker_before',{}))|set(C.get('worker_dependencies',{}))|{'src/shared','data/reports/next24h_forecast_history.csv','data/raw/entsoe/prices.csv','data/reports/next24h_inference'}
        allowed.update(v['initializer']for v in C.get('worker_optional_packages',{}).values())
        need(type(issues)is list and 0<len(issues)<=32,'DEPENDENCY_DIAGNOSTIC_BOUND')
        safe=[]
        for item in issues:
            need(set(item)=={'identifier','stage','category','gate'}and item['identifier']in allowed,'DEPENDENCY_DIAGNOSTIC_SCOPE')
            need(item['stage']in{'PACKAGE','PARENT','FILE','BASELINE','DEPENDENCY','INPUT','IMPORT_SOURCE'},'DEPENDENCY_DIAGNOSTIC_STAGE')
            need(item['category']in{'MISSING','PERMISSION_DENIED','SYMLINK_OR_TYPE','FILESYSTEM_ERROR','METADATA_MISMATCH','HASH_OR_SIZE_MISMATCH','HARDLINK','UNEXPECTED_PRESENT','VALIDATION_FAILED'},'DEPENDENCY_DIAGNOSTIC_CATEGORY')
            gate=item['gate'];need(type(gate)is str and re.fullmatch('[A-Z][A-Z0-9_]{0,79}',gate)is not None and gate in C.get('failure_gates',[]),'DEPENDENCY_DIAGNOSTIC_GATE')
            safe.append(dict(item))
        self.dependency_issues=safe
        super().__init__(safe[0]['gate']if len(safe)==1 else'WORKER_DEPENDENCY_INVENTORY')

def dependency_issue(identifier,stage,error=None,category=None,gate=None):
    if category is None:
        category='MISSING'if isinstance(error,FileNotFoundError)else'PERMISSION_DENIED'if isinstance(error,PermissionError)else'SYMLINK_OR_TYPE'if isinstance(error,OSError)and error.errno in{20,40}else'FILESYSTEM_ERROR'if isinstance(error,OSError)else'METADATA_MISMATCH'
    return {'identifier':identifier,'stage':stage,'category':category,'gate':gate or'WORKER_DEPENDENCY_INVENTORY'}
