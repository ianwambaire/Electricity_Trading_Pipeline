"""Pure instrumentation of the exact approved child script; no host operations."""
import ast

STAGES={'BOOTSTRAP','RUNTIME_IDENTITY','AUDIT_SETUP','SOURCE_BINDING','LOADER_SETUP','API_IMPORT','POLICY_CHECK','SCHEMA_CHECK','ROUTES_CHECK','COMPLETE'}
CLASSES={'ModuleNotFoundError','ImportError','PermissionError','FileNotFoundError','AssertionError','RuntimeError','AttributeError','TypeError','ValueError','OSError','MemoryError','SystemExit','NameError','SyntaxError','UnicodeDecodeError','RecursionError','PydanticUserError','PydanticSchemaGenerationError','PydanticUndefinedAnnotation','SchemaError','ValidationError','PydanticImportError','FastAPIError','PydanticInvalidForJsonSchema'}
EVENTS={'open','socket.connect','socket.bind','subprocess.Popen','os.system','os.mkdir','os.remove','os.rename','os.chmod','os.chown','os.symlink','os.link'}
DEPENDENCIES={'fastapi','starlette','pydantic','pydantic_core','httpx','httpcore','h11','anyio','sniffio','joserfc','cryptography','cffi','_cffi_backend','pycparser','numpy','pandas','dateutil','pytz','tzdata','six','certifi','idna','uvicorn','click','annotated_types','annotated_doc','typing_extensions','typing_inspection'}

def instrument(original):
    tree=ast.parse(original)
    # Exactly the reviewed original statement sequence. A changed parent script
    # requires a new diagnostic review, not silently looser pattern matching.
    assert [type(n).__name__ for n in tree.body]==['Import','Assert','FunctionDef','Expr','Assign','ClassDef','Expr','Import','Assert','Assert','Assert','Expr']
    assert tree.body[2].name=='audit' and tree.body[5].name=='Loader'
    assert tree.body[4].targets[0].id=='SOURCES'
    sources=ast.literal_eval(tree.body[4].value)
    assert type(sources)is dict and all(type(k)is str for k in sources)
    stages=['BOOTSTRAP','RUNTIME_IDENTITY','AUDIT_SETUP','AUDIT_SETUP','SOURCE_BINDING','LOADER_SETUP','LOADER_SETUP','API_IMPORT','POLICY_CHECK','SCHEMA_CHECK','ROUTES_CHECK','COMPLETE']
    body=[]
    for node,stage in zip(tree.body,stages):
        body.append(ast.Assign(targets=[ast.Name(id='__diag_stage',ctx=ast.Store())],value=ast.Constant(stage)))
        body.append(node)
    body.append(ast.Assign(targets=[ast.Name(id='__diag_ok',ctx=ast.Store())],value=ast.Constant(True)))
    instrumented=ast.unparse(ast.fix_missing_locations(ast.Module(body=body,type_ignores=[])))
    # All original AST nodes, guards, imports, policy assertions and PASS marker
    # remain in order. No changes to module __file__, source or compile filenames.
    header="""import sys,os,json,re
__diag_output=sys.stdout
class __DiagSink:
 encoding='utf-8'
 closed=False
 def __init__(self,original,expected=None):self.original=original;self.expected=expected;self.position=0;self.matches=True;self.bytes=0
 def __getattr__(self,name):return getattr(self.original,name)
 def write(self,value):
  self.bytes=min(8193,self.bytes+(8193 if len(value)>8192 else len(value.encode('utf-8'))))
  if self.expected is not None:
   if value!=self.expected[self.position:self.position+len(value)]:self.matches=False
   self.position+=len(value)
  return len(value)
 def flush(self):pass
 def isatty(self):return False
__diag_stdout=__DiagSink(__diag_output,'CANDIDATE_IMPORT_PASS\\n');__diag_stderr=__DiagSink(sys.stderr)
sys.stdout=__diag_stdout;sys.stderr=__diag_stderr
__diag_stage='BOOTSTRAP';__diag_ok=False;__diag_error=None
try:
"""
    tail="""
except BaseException as __caught:
 __diag_error=__caught
def __safe_module(value):
 if type(value)is not str or len(value)>120:return 'REDACTED_MODULE'
 if value in __APPROVED_MODULES:return value
 if not re.fullmatch(r'[a-z_][a-z0-9_]*(?:\\.[a-z_][a-z0-9_]*)*',value):return 'REDACTED_MODULE'
 if re.search(r'token|password|credential|secret|private',value):return 'REDACTED_MODULE'
 if value.split('.')[0] in __DEPENDENCIES or value in sys.stdlib_module_names:return value
 return 'REDACTED_MODULE'
__report={'status':'PASS' if __diag_ok else 'BLOCKED','stage':__diag_stage,'category':'IMPORT_PASS' if __diag_ok else 'UNCLASSIFIED_FAILURE','exception':None,'candidate_module':None,'module':None,'import_name':None,'line':None,'audit_event':None,'cause_exception':None,'errno':None}
if __diag_ok and (not __diag_stdout.matches or __diag_stdout.position!=len(__diag_stdout.expected)):
 __diag_ok=False;__report.update(status='BLOCKED',category='UNEXPECTED_STDOUT')
if __diag_stdout.bytes>8192 or __diag_stderr.bytes>8192:
 __diag_ok=False;__report.update(status='BLOCKED',category='CHILD_OUTPUT_LIMIT')
if __diag_error is not None:
 __kind=type(__diag_error).__name__
 __report['exception']=__kind if __kind in __CLASSES else 'UNCLASSIFIED_EXCEPTION'
 __report['category']={'ModuleNotFoundError':'MODULE_MISSING','ImportError':'IMPORT_ERROR','PermissionError':'PERMISSION_DENIED','FileNotFoundError':'FILE_MISSING','AssertionError':'ASSERTION_FAILED','AttributeError':'ATTRIBUTE_ERROR','TypeError':'TYPE_ERROR','ValueError':'VALUE_ERROR','MemoryError':'MEMORY_ERROR','OSError':'OS_ERROR','SystemExit':'UNEXPECTED_EXIT'}.get(__kind,'UNCLASSIFIED_FAILURE')
 if __kind in {'PydanticUserError','PydanticSchemaGenerationError','PydanticUndefinedAnnotation','SchemaError','ValidationError','PydanticImportError','FastAPIError','PydanticInvalidForJsonSchema'}:__report['category']='SCHEMA_ERROR'
 if __diag_stage=='RUNTIME_IDENTITY':
  __report['category']='RUNTIME_VERSION_MISMATCH' if sys.version_info[:3]!=(3,14,7) else 'IDENTITY_MISMATCH'
 if isinstance(__diag_error,ImportError):__report['import_name']=__safe_module(__diag_error.name)
 if isinstance(__diag_error,OSError) and type(__diag_error.errno)is int and 0<__diag_error.errno<256:__report['errno']=__diag_error.errno
 if __kind=='RuntimeError' and __diag_error.args==('IMPORT_WRITE',):__report['category']='FILESYSTEM_WRITE_BLOCKED'
 if __kind=='RuntimeError' and __diag_error.args==('IMPORT_SIDE_EFFECT',):__report['category']='SIDE_EFFECT_BLOCKED'
 __cause=__diag_error.__cause__ or __diag_error.__context__
 if __cause is not None:
  __name=type(__cause).__name__;__report['cause_exception']=__name if __name in __CLASSES else 'UNCLASSIFIED_EXCEPTION'
 __trace=__diag_error.__traceback__
 while __trace:
  __frame=__trace.tb_frame;__module=__safe_module(__frame.f_globals.get('__name__'))
  if __module!='REDACTED_MODULE':__report['module']=__module
  if __frame.f_code.co_filename=='<verified-candidate>' and __module in __APPROVED_MODULES:
   __report['candidate_module']=__module;__report['line']=__trace.tb_lineno if 0<__trace.tb_lineno<100000 else None
  if __frame.f_code.co_name=='audit':
   __event=__frame.f_locals.get('event');__report['audit_event']=__event if __event in __EVENTS else None
  __trace=__trace.tb_next
__diag_output.write(json.dumps(__report,sort_keys=True)+'\\n');__diag_output.flush()
raise SystemExit(0 if __diag_ok else 1)
"""
    tail=tail.replace('__APPROVED_MODULES',repr(tuple(sorted(sources)))).replace('__DEPENDENCIES',repr(tuple(sorted(DEPENDENCIES)))).replace('__CLASSES',repr(tuple(sorted(CLASSES)))).replace('__EVENTS',repr(tuple(sorted(EVENTS))))
    result=header+'\n'.join(' '+line for line in instrumented.splitlines())+'\n'+tail
    ast.parse(result,feature_version=(3,9))
    return result.encode()
