"""Pure validation of a future private rollback record. No I/O or operations.

Actual targets and environment backup must be captured during an authorized
preflight/deployment. This module does not claim that any recorded path exists.
"""
from pathlib import PurePosixPath
import re


def valid_target(value, prefix):
    if not isinstance(value,str):raise ValueError('target_type')
    path=PurePosixPath(value)
    if str(path)!=value or path.parent!=PurePosixPath(prefix) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}',path.name) or path.name in ('.','..'):
        raise ValueError('target_scope')
    return value


def validate(record):
    expected={'schema_version','previous_backend','previous_static','installed_backend','installed_static',
              'original_env_sha256','installed_env_sha256','environment_backup','environment_uid','environment_gid','environment_mode'}
    if not isinstance(record,dict) or set(record)!=expected or type(record['schema_version']) is not int or record['schema_version']!=1:raise ValueError('rollback_schema')
    for key in ['previous_backend','installed_backend']:valid_target(record[key],'/opt/powerflow/releases')
    for key in ['previous_static','installed_static']:valid_target(record[key],'/var/www/powerflow-staging/releases')
    for key in ['original_env_sha256','installed_env_sha256']:
        if not isinstance(record[key],str) or not re.fullmatch('[a-f0-9]{64}',record[key]):raise ValueError('environment_digest')
    backup='/var/lib/powerflow-staging/forecast-consistency-20261101-v1/previous-api.env'
    if record['environment_backup']!=backup:raise ValueError('backup_scope')
    if type(record['environment_uid']) is not int or type(record['environment_gid']) is not int or record['environment_uid']!=0 or record['environment_gid']!=0 or record['environment_mode']!='0600':raise ValueError('environment_permissions')
    if record['previous_backend']==record['installed_backend'] or record['previous_static']==record['installed_static']:raise ValueError('unchanged_target')
    return dict(record)


def restore_targets(record):
    record=validate(record)
    return {'backend':record['previous_backend'],'static':record['previous_static'],
            'environment_backup':record['environment_backup'],'environment_sha256':record['original_env_sha256']}
