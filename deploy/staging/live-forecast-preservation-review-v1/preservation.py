"""Local reporting candidate, not assembled or authorized for remote execution.

Execute in the existing acceptance namespace so need() retains its original
sanitized Stop exception type. Values, digests, paths and exceptions never enter
error messages. Equality is intentionally unchanged, including dynamic fields:
reported drift must not be silently accepted without verified provenance.
"""
COMPONENTS = ('production', 'forecast', 'store', 'helper', 'policy', 'environment', 'nginx')

def preservation_differences(before, after):
    need(type(before) is dict and type(after) is dict
         and set(before) == set(after) == set(COMPONENTS), 'PRESERVATION_SCHEMA')
    return tuple(key for key in COMPONENTS if before[key] != after[key])

def same(before, after):
    differences = preservation_differences(before, after)
    if differences:
        need(False, 'PRESERVATION_DRIFT_' + differences[0].upper())
