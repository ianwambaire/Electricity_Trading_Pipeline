"""Read-only Linux x86_64 BPF_PROG_QUERY; never loads/attaches/modifies BPF."""
import ctypes
import os
import platform
from pathlib import Path


class Query(ctypes.Structure):
    _fields_=[('target_fd',ctypes.c_uint32),('attach_type',ctypes.c_uint32),
              ('query_flags',ctypes.c_uint32),('attach_flags',ctypes.c_uint32),
              ('prog_ids',ctypes.c_uint64),('prog_cnt',ctypes.c_uint32),
              ('prog_attach_flags',ctypes.c_uint64)]


def attachments(path,call=None):
    if platform.system()!='Linux' or platform.machine()!='x86_64':raise RuntimeError('BPF_query_requires_Linux_x86_64')
    assert ctypes.sizeof(Query)==40
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        invoke=call or ctypes.CDLL(None,use_errno=True).syscall
        result={}
        for name,attach in (('ingress',0),('egress',1)):
            ids=(ctypes.c_uint32*64)()
            # query_flags1 requests effective attachments, including ancestors.
            attr=Query(target_fd=fd,attach_type=attach,query_flags=1,
                       prog_ids=ctypes.addressof(ids),prog_cnt=64)
            code=invoke(321,16,ctypes.byref(attr),ctypes.sizeof(attr))
            if code!=0:raise RuntimeError('BPF_query_not_available_errno_'+str(ctypes.get_errno()))
            if attr.prog_cnt>64:raise RuntimeError('BPF_query_result_limit')
            result[name]=list(ids[:attr.prog_cnt])
        return result
    finally:os.close(fd)
