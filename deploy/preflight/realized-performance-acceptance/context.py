"""Read-only adapters around the unchanged, hash-verified Reporting V4 closure."""
import ast
import datetime as dt
import json
import os
from pathlib import Path
import re
import stat
import sys
import types

class Context:
    def __init__(self,r,inspector):
        self.r=r;self.i=inspector;self.record=None;self.op_pointer=None;self.report_pointer=None;self.op_public=None
    def check(self,call,operation=None):
        try:return call()
        except self.i.Rejected as error:
            if operation is not None and 'operation'not in error.detail:error.detail['operation']=operation
            elif operation is None and getattr(self,'operation',None)in self.i.OPERATIONS and 'operation'not in error.detail:error.detail['operation']=self.operation
            raise
        except Exception as error:
            gate=error.args[0]if error.args and type(error.args[0])is str else None
            raise self.i.Rejected('OS_ERROR'if isinstance(error,OSError)else'GUARD_FAILED',operation=operation or getattr(self,'operation',None),gate=gate,cause=type(error).__name__)from None
    def step(self,operation,fn):
        self.operation=operation;return fn()
    def guard(self):
        r=self.r;i=self.i
        def check():
            i.need(sys.platform=='linux'and os.getuid()==os.geteuid()==0,'GUARD_FAILED')
            self.record=self.step('TRANSACTION',r.load_record);i.need(self.record['phase']=='APPLIED'and self.record['activated_at'],'GUARD_FAILED')
            self.step('WINDOW',lambda:r.P.idle(0));self.step('BACKUPS',lambda:r.verify_backups(self.record));self.step('INSTALLED_API',lambda:r.new_trees(self.record,True));self.step('INSTALLED_WORKER',lambda:r.worker_state(True))
            i.need(i.stamp(self.record['activated_at'])<i.stamp(i.SCHEDULED),'IDENTITY')
            # The installed version/source gate is part of the original host gate;
            # it uses approved Prefect 3.7.5 metadata/source hashes, never imports.
            self.operation='PREFECT_IDENTITY'
            sdk=r.WORKER/'.venv-prod/lib/python3.14/site-packages'
            i.need(r.H.OLD_CONFIG['prefect_version']=='3.7.5','GUARD_FAILED')
            for rel,digest in r.H.OLD_CONFIG['worker_sdk'].items():
                path=sdk/'prefect'/rel;r.P.safe(path,(0,1000));i.need(i.sha(r.P.read(path))==digest,'GUARD_FAILED')
            metadata=sdk/'prefect-3.7.5.dist-info/METADATA';r.P.safe(metadata,(0,1000));i.need(i.sha(r.P.read(metadata,262144))==r.H.OLD_CONFIG['prefect_metadata_sha256'],'GUARD_FAILED')
            return {'release':'phase-realized-next24h-performance-20261108-v4','transaction':'8415154bdaf94746a93adf6e380667a8','installed_inventory':'VERIFIED','read_only':True}
        return self.check(check)
    def operational(self):
        r=self.r;i=self.i
        def read():
            pointer=r.P.snap(r.P.STORE/'current',0,992,0o640)[1];digest=pointer.decode().strip();i.need(re.fullmatch('[0-9a-f]{64}',digest)is not None,'CONTRACT_INVALID')
            raw=r.P.snap(r.P.STORE/'releases'/digest/'evidence.json',0,992,0o640)[1];now=dt.datetime.now(dt.timezone.utc)
            doc=r.H.OP.validate(raw,digest,now);self.op_public=r.H.OP.view(raw,digest,now=now)
            i.need(r.P.snap(r.P.STORE/'current',0,992,0o640)[1]==pointer,'POINTER_CHANGED');self.op_pointer=pointer
            execution=doc['execution'];associated=execution['flow_run_id']==i.FLOW and execution['pipeline_run_id']==i.PIPELINE
            if execution['flow_run_id']==i.FLOW:i.need(associated,'IDENTITY')
            return {'sha256':digest,'target_association':'MATCH'if associated else'CURRENT_RECORD_ADVANCED_OR_DIFFERENT','observed_at':doc['observed_at'],'execution_outcome':execution['outcome'],'inference_outcome':doc['inference']['outcome'],'delivery_outcome':doc['delivery']['outcome']}
        return self.check(read,'OPERATIONAL_POINTER')
    def contract(self):
        # Load only the frozen stdlib contract; extract its exact column constant
        # rather than importing the pandas/numpy producer under bootstrap Python.
        r=self.r;prefix='_readonly_report_contract';package=types.ModuleType(prefix);package.__path__=[];sys.modules[prefix]=package
        forecast=types.ModuleType(prefix+'.forecast_publication');forecast.__package__=prefix
        exec(compile(r.raw_file('api/src/shared/forecast_publication.py'),'<bound-contract>','exec'),forecast.__dict__);sys.modules[forecast.__name__]=forecast
        evaluation=types.ModuleType(prefix+'.forecast_evaluation')
        tree=ast.parse(r.raw_file('api/src/shared/forecast_evaluation.py'))
        values=[n.value for n in tree.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='REALIZED_COLUMNS'for t in n.targets)]
        self.i.need(len(values)==1,'CONTRACT_INVALID');evaluation.REALIZED_COLUMNS=ast.literal_eval(values[0]);sys.modules[evaluation.__name__]=evaluation
        contract=types.ModuleType(prefix+'.realized_report');contract.__package__=prefix
        exec(compile(r.raw_file('api/src/shared/realized_report.py'),'<bound-contract>','exec'),contract.__dict__)
        return contract
    def publication(self):
        r=self.r;i=self.i
        def read():
            digest=r.report_metadata(self.record);self.report_pointer=digest
            if digest is None:return {'summary':{'present':False,'state':None}}
            path=r.REPORT/'releases'/digest/'report.json';r.P.safe(path,(0,1000));raw=r.P.read(path,16*1024**2)
            i.need(i.sha(raw)==digest,'CONTRACT_INVALID');doc=self.contract().validate(raw,dt.datetime.now(dt.timezone.utc))
            i.need(r.report_metadata(self.record)==digest,'POINTER_CHANGED')
            return {'summary':{'present':True,'sha256':digest,'state':doc['state'],'reason':doc['reason'],'generated_at':doc['generated_at'],'observed_through':doc['observed_through'],'freshness':'VALID'if dt.datetime.now(dt.timezone.utc)<i.stamp(doc['generated_at'])+dt.timedelta(minutes=90)else'STALE','source_sha256':doc['sources'],'coverage':doc['coverage']},'document':doc,'digest':digest}
        return self.check(read,'REPORT_DOCUMENT')
    def apis(self,bodies):
        i=self.i
        i.need(self.op_public is not None,'DEPENDENCY_UNVERIFIED')
        op_status,op=bodies['OPERATIONS_API'];i.need(op_status==200 and op==self.op_public,'API_MISMATCH')
        forecast_status,forecast=bodies['FORECAST_API'];summary_status,summary=bodies['OPERATIONS_SUMMARY']
        i.need(summary_status==200,'API_MISMATCH')
        if forecast_status==200:
            i.need(summary.get('forecast_status')=='VALID','API_MISMATCH')
            publication=forecast['publication']
            i.need(i.stamp(summary.get('forecast_expires_at'))==i.stamp(publication.get('expires_at')),'API_MISMATCH')
            i.need(i.stamp(summary.get('forecast_refresh_due_at'))==i.stamp(publication.get('refresh_due_at')),'API_MISMATCH')
        else:i.need(forecast_status==503 and summary.get('forecast_status')in{'WITHHELD','EXPIRED','MISSING_PUBLICATION'},'API_MISMATCH')
        return {'operational_public_projection':'EXACT_MATCH','admin_fields_disclosed':False,'forecast_api_consistency':True,'operational_status':op['status']}
    def consistency(self,pub,response,task):
        r=self.r;i=self.i;status,body=response
        i.need(pub['summary']['present'],'MISSING');doc=pub['document']
        i.need(task is not None and task.get('start_time')and task.get('end_time'),'DEPENDENCY_UNVERIFIED')
        i.need(i.stamp(task['start_time'])<=i.stamp(doc['generated_at'])<=i.stamp(task['end_time']),'PUBLICATION_NOT_TARGET')
        if doc['state']!='READY':
            expected='REALIZED_INPUTS_MISSING'if doc['state']=='MISSING_INPUTS'else'REALIZED_REPORT_FAILED'
            i.need(status==503 and body=={'detail':{'code':expected}},'API_MISMATCH')
            return {'publication_matches_api':True,'target_time_association':True,'data_state':doc['state']}
        i.need(status==200 and body.get('report_sha256')==pub['digest'],'API_MISMATCH')
        assessed=i.stamp(body.get('assessed_at'));i.need(abs((dt.datetime.now(dt.timezone.utc)-assessed).total_seconds())<60,'TIMESTAMP')
        # Compare the installed API evaluator at the actual HTTP assessment time,
        # avoiding a threshold/window boundary between two sequential reads.
        script=r.inspected_report_script();needle=b'now=dt.datetime.now(dt.timezone.utc)';i.need(script.count(needle)==1,'CONTRACT_INVALID')
        script=script.replace(needle,('now=dt.datetime.fromisoformat('+repr(assessed.isoformat())+')').encode())
        pid=r.report_environment(True)
        command=['/usr/bin/nsenter','--mount=/proc/'+str(pid)+'/ns/mnt','--','/usr/bin/setpriv','--no-new-privs','--reuid=992','--regid=992','--clear-groups',str(Path(self.record['before']['venv'])/'bin/python'),'-I','-B','-']
        result=r.B['bounded_run'](command,input=script,timeout=20,limit=65536,grace=5)
        i.need(result['returncode']==0 and not result['failure'],'CONTRACT_INVALID')
        expected=i.strict_json(result['stdout']);i.need(set(expected)=={'digest','document_generated_at','response'}and expected['digest']==pub['digest']and expected['response']==body,'API_MISMATCH')
        return {'publication_matches_api':True,'target_time_association':True,'metric_evaluator':'EXACT_INSTALLED_CONSUMER','report_status':body['report_status'],'data_status':body['data_status']}
    def reconstruct(self,pub,task):
        r=self.r;i=self.i;doc=pub['document']
        i.need(task.get('start_time')and task.get('end_time')and i.stamp(task['start_time'])<=i.stamp(doc['generated_at'])<=i.stamp(task['end_time']),'PUBLICATION_NOT_TARGET')
        for key,rel in [('history_sha256','data/reports/next24h_forecast_history.csv'),('prices_sha256','data/raw/entsoe/prices.csv')]:
            path=r.WORKER/rel;r.P.safe(path,(0,1000));i.need(i.sha(r.P.read(path,64*1024**2))==doc['sources'][key],'SOURCE_ADVANCED')
        result=r.B['bounded_run'](['/usr/bin/setpriv','--no-new-privs','--reuid=1000','--regid=1000','--clear-groups',str(r.WORKER/'.venv-prod/bin/python'),'-I','-B','-'],input=r.reconstructed_report_script(doc['generated_at']),timeout=35,limit=1024,grace=5)
        i.need(result['returncode']==0 and not result['failure'],'CONTRACT_INVALID');i.need(i.strict_json(result['stdout'])=={'sha256':pub['digest']},'CONTRACT_INVALID')
        return {'receipt_source_and_metrics':'RECONSTRUCTED_MATCH','completed_hours_only':True,'late_issue_excluded':True,'complete_observations_required':True}
    def protected(self):
        r=self.r;i=self.i
        def check():
            self.step('PROTECTED_SNAPSHOT',lambda:r.protected(self.record,True))
            self.operation='REPORT_ENVIRONMENT'
            i.need(r.P.snap(r.ENV,0,0,0o600)[0]['sha256']==self.record['before']['env_after'],'GUARD_FAILED')
            self.operation='REPORT_POLICY';deployment=r.P.deployment()
            i.need(deployment.get('job_variables',{})==self.record['before']['new_variables']and r.H.OLD_PLAN.stable_projection(deployment)==self.record['before']['projection'],'GUARD_FAILED')
            i.need(deployment.get('job_variables',{}).get('env',{}).get(r.FLAG)=='true','GUARD_FAILED')
            if self.op_pointer is not None:i.need(r.P.snap(r.P.STORE/'current',0,992,0o640)[1]==self.op_pointer,'POINTER_CHANGED')
            if self.report_pointer is not None:i.need(r.report_metadata(self.record)==self.report_pointer,'POINTER_CHANGED')
            self.step('FINAL_WINDOW',lambda:r.P.idle(0))
            return {'protected_state':'VERIFIED','forecast_configuration':'PRESERVED','operational_retention':'VERIFIED','publication_pointers':'STABLE','report_delivery_enabled':True}
        return self.check(check)
