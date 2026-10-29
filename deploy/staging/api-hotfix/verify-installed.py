"""Read-only installed-candidate verification; executed through SSH stdin only."""
import hashlib,json,os,pathlib,subprocess
BASE=pathlib.Path('/opt/powerflow/releases/phase-staging-https-ready-20261026')
def main():
 expected={'requirements/api.lock': 'b1d8bbbec84a08b651b7bdc0b96e5bb94bf6c527297e037357702de00bcc84e3', 'src/api/__init__.py': 'd7842be76c9c978de666675161f35a3bd24c24e732682cb7d76e9401c5d36a85', 'src/api/account_routes.py': '4f74ca84be298f4848059cd8e15900cbd2c22bd7341594fc9bfefbdb4786a88c', 'src/api/account_service.py': '7aae6f7cb2397570bf0daa778f33af5bc19a95fc0b1f23053a8167a1e3da5343', 'src/api/admin_operations.py': '37c7f5dc1794d680580ff69165a3e64035c9282b202cdda141b67bbe106ee2f4', 'src/api/anomalies.py': '9f2957cbc733d61f80b36444033174e69cfe078cafa5d3b721b0f53eb809c7e3', 'src/api/app.py': 'ec2fabd38f91174ba2589a3831f824ee36151d5d622f313e796ded9226639a42', 'src/api/database.py': '962e07dd654cfb06017866a2c98bc553077239f98de9a0698f1eb83db4c6e906', 'src/api/feature_parity.py': '3a0f3c7c027229e4313f0a25e0fe46fde63834b24f712f49fc232892ab107699', 'src/api/market_data.py': '4c9b135d5f97b6e8381688c41fcd4e41047ea36423713c70a655ffa0b503752a', 'src/api/mfa_routes.py': '858b229be48baa668e5f816136db07c94c52310e01cdeac2803ccca4a8785470', 'src/api/mfa_service.py': '8ea67f55d36e4cd6e97fff1c5907ae83f3c48bbb74c948bd82fc424686942715', 'src/api/model_summaries.py': '9e57ce3de689f76e1036a901663c7cc7b7a49fe0f6188f113f203627e7bf2fd4', 'src/api/operations_summary.py': '5989120938501241c84d128c0e86897b3949668fde9d29421b4b79d4cc7a20f9', 'src/api/readiness.py': 'dd3bb8dda2bb3561212915aabdbc55e0a96430331e43e1f0ba0e277842167ff7', 'src/api/restricted_reports.py': '69ae92e3b888cde893946b49ec8acb6e5c117ce7987e27d7ac5cb1e33293c1b0', 'src/api/runtime.py': '8ef6206a373705bcccd06acf25de8cbc31e4e35a05bdb59a3366b630a617b030', 'src/api/security.py': '7e4d05cb476555fd18884212ecfd88357669f8cd9515edf6bcd17152a6175b61', 'src/shared/__init__.py': '4dacb653b07451745e1a3fede7a6901f964c82d90a130aff0d6f95d60994f110', 'src/shared/forecast_evaluation.py': 'f185ccf0c7b503eb529eb25fb95026937e4a8ddd9206bf6890b1d64ca010e28b', 'src/shared/market_context.py': 'ca5a043cc1ef2a427f4e7b5449b59873e6f5ec85b7be7c963e8b8a6dad6825e7', 'src/shared/operational_health.py': '4db26232cab02591c4d8bdd4adbe80694dffb44da7b57346cc17c50930c89108'}
 result={'checks':{},'files':{}}
 for rel,digest in expected.items():
  p=BASE/rel
  ok=p.is_file() and not p.is_symlink() and hashlib.sha256(p.read_bytes()).hexdigest()==digest
  result['files'][rel]={'match':ok}
 result['checks']['current_link']=pathlib.Path('/opt/powerflow/react-current').is_symlink() and pathlib.Path('/opt/powerflow/react-current').resolve()==BASE
 result['checks']['new_release_absent']=not os.path.lexists(str(BASE)+'-context-hotfix-20261029')
 result['checks']['helper_absent']=not os.path.lexists(BASE/'src/shared/price_aggregation.py')
 unit=subprocess.run(['/usr/bin/systemctl','show','powerflow-candidate-api.service','--property=ActiveState,MainPID,User,MemoryMax,MemorySwapMax,WorkingDirectory,EnvironmentFiles,ExecStart'],capture_output=True,text=True,timeout=8,check=True).stdout
 # Do not print ExecStart or environment-file contents.
 values=dict(line.split('=',1) for line in unit.splitlines() if '=' in line)
 result['service']={k:values.get(k) for k in ['ActiveState','MainPID','User','MemoryMax','MemorySwapMax','WorkingDirectory']}
 result['checks']['service']=values.get('ActiveState')=='active' and values.get('User')=='powerflow-api' and values.get('MemoryMax')=='536870912' and values.get('MemorySwapMax')=='0'
 def drop():os.setgroups([]);os.setgid(992);os.setuid(992)
 code="import sys,json,importlib.metadata as m; print(json.dumps({'python':sys.version.split()[0],'fastapi':m.version('fastapi'),'pandas':m.version('pandas'),'uvicorn':m.version('uvicorn')}))"
 run=subprocess.run([str(BASE/'.venv-api/bin/python'),'-I','-B','-c',code],capture_output=True,text=True,timeout=15,check=True,preexec_fn=drop,cwd='/',env={'PATH':'/usr/bin:/bin'})
 result['runtime']=json.loads(run.stdout)
 result['checks']['python']=result['runtime']['python']=='3.14.7'
 result['passed']=all(result['checks'].values()) and all(x['match'] for x in result['files'].values())
 print(json.dumps(result,indent=2));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
