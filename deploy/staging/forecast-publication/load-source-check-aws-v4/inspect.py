"""Candidate SDK gate around the unchanged reviewed source-check workflow."""
import os
from pathlib import Path


def prepare():
    flow = {'__name__': 'retained_v2_workflow', 'H': H, 'AWS': AWS, 'PROVIDER': PROVIDER,
            'CORE': CORE, 'SDK_LOCK': SDK_LOCK, 'SOURCE_HASHES': SOURCE_HASHES, 'CHILD_SOURCE': CHILD_SOURCE}
    exec(compile(FLOW_SOURCE, '<retained-v2-workflow>', 'exec'), flow)
    verifier = {'__name__': 'retained_v3_verifier', 'H': H, 'SDK_LOCK': SDK_LOCK}
    exec(compile(VERIFIER_SOURCE, '<retained-v3-verifier>', 'exec'), verifier)

    def sdk_files():
        # Reject ambiguous or alternate urllib3 metadata before importing any SDK.
        state = verifier['STATE']
        state.update(stage='CODE_INVENTORY', dependency_id='SDK_INVENTORY', category=None, verified_files=0)
        try:
            site = verifier['directory_fd'](verifier['SITE'], 'SITE_ANCHOR', 'SDK_SITE')
            try:
                verifier['metadata'](os.fstat(site), directory=True)
                verifier['location']('CODE_INVENTORY', 'SDK_INVENTORY')
                names = []
                with os.scandir(site) as entries:
                    for count, entry in enumerate(entries, 1):
                        verifier['require'](count <= 8192, 'SDK_VERSION_OR_LAYOUT_MISMATCH')
                        if entry.name.startswith(('urllib3-', 'urllib3.')):
                            verifier['require'](entry.name == 'urllib3-2.8.0.dist-info', 'SDK_VERSION_OR_LAYOUT_MISMATCH')
                            names.append(entry.name)
                verifier['location']('CODE_INVENTORY', 'urllib3-2.8.0.dist-info')
                verifier['require'](names == ['urllib3-2.8.0.dist-info'], 'FILE_MISSING')
                info = os.stat(names[0], dir_fd=site, follow_symlinks=False)
                verifier['metadata'](info, directory=True)
            finally:
                os.close(site)
            return verifier['sdk_files']()
        except Exception as error:
            if state['category'] is None:
                try:
                    verifier['filesystem_failure'](error)
                except Exception:
                    pass
            cause = 'SDK_INVENTORY_MISMATCH' if state['category'] == 'SDK_VERSION_OR_LAYOUT_MISMATCH' else 'SDK_DEPENDENCY_MISMATCH'
            raise AWS['Blocked'](cause) from None

    original_report = flow['report']

    def report(status, cause=None, comparison=None):
        result = original_report(status, cause, comparison)
        result['sdk_verification'] = dict(verifier['STATE'])
        return result

    flow['sdk_files'] = sdk_files
    flow['report'] = report
    return flow, verifier


FLOW, VERIFIER = prepare()


if __name__ == '__main__':
    raise SystemExit(FLOW['main']())
