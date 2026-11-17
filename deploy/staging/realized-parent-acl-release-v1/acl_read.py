"""Root-trusted Linux libacl READ/memory interface. No ACL setter is bound here."""
import base64
import ctypes
import os
from pathlib import Path
import stat

ACCESS='system.posix_acl_access';DEFAULT='system.posix_acl_default'
LIBRARY='/usr/lib64/libacl.so.1'
FLAGS=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|getattr(os,'O_NOATIME',0)

def safe_parent(path):
    for item in(Path(path),*Path(path).parents):
        s=item.lstat();need(not stat.S_ISLNK(s.st_mode)and s.st_uid==0 and not s.st_mode&0o022,'TRUSTED_PATH_METADATA')

def root_fd():
    fd=os.open('/',FLAGS)
    try:
        for part in ['srv','powerflow']:
            s=os.stat(part,dir_fd=fd,follow_symlinks=False);need(stat.S_ISDIR(s.st_mode)and s.st_uid==0 and not s.st_mode&0o022,'PARENT_PATH_METADATA')
            nxt=os.open(part,FLAGS,dir_fd=fd)
            current=os.fstat(nxt)
            if (current.st_dev,current.st_ino,current.st_uid,current.st_gid,current.st_mode)!=(s.st_dev,s.st_ino,s.st_uid,s.st_gid,s.st_mode):
                os.close(nxt);raise Stop('PARENT_PATH_CHANGED')
            os.close(fd);fd=nxt
        s=os.fstat(fd);need((s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))==(OWNER,READER_GID,MODE),'VERIFIED_PARENT_BASELINE_DRIFT')
        return fd
    except Exception:os.close(fd);raise

def attr(fd,name):
    need(name in {ACCESS,DEFAULT},'XATTR_READ_SCOPE')
    try:raw=os.getxattr(fd,name)
    except OSError as error:
        if error.errno==61:return None # Linux ENODATA, not ENOTSUP
        if error.errno in {38,95}:raise Stop('POSIX_ACL_NOT_SUPPORTED')from None
        raise Stop('ACL_XATTR_READ_FAILED')from None
    need(0<len(raw)<=16384,'ACL_XATTR_BOUND');return base64.b64encode(raw).decode()

def metadata(fd):
    s=os.fstat(fd);need(stat.S_ISDIR(s.st_mode),'TARGET_NOT_DIRECTORY')
    return {'device':s.st_dev,'inode':s.st_ino,'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode)}

class ACL:
    def __init__(self):
        need(not{'LD_PRELOAD','LD_LIBRARY_PATH','LD_AUDIT'}&set(os.environ),'UNTRUSTED_LOADER_ENVIRONMENT')
        link=Path(LIBRARY);safe_parent(link.parent)
        actual=link.resolve(strict=True);need(actual.parent==link.parent and actual.name.startswith('libacl.so.'),'LIBACL_LAYOUT_UNSUPPORTED');safe_parent(actual)
        self.fd=os.open(actual,os.O_RDONLY|os.O_NOFOLLOW|getattr(os,'O_NOATIME',0));s=os.fstat(self.fd)
        try:
            need(stat.S_ISREG(s.st_mode)and s.st_uid==0 and not s.st_mode&0o022 and s.st_size<=4*1024**2,'LIBACL_METADATA_UNSAFE')
            raw=os.read(self.fd,4*1024**2+1);need(len(raw)==s.st_size,'LIBACL_READ_BOUND')
            after=os.fstat(self.fd);need((s.st_dev,s.st_ino,s.st_size,s.st_mode,s.st_uid,s.st_gid,s.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mode,after.st_uid,after.st_gid,after.st_ctime_ns),'LIBACL_CHANGED_DURING_READ')
            self.identity={'device':s.st_dev,'inode':s.st_ino,'sha256':sha(raw)}
            # Descriptor alias is kernel-controlled and this FD remains open.
            self.lib=ctypes.CDLL('/proc/self/fd/'+str(self.fd),use_errno=True)
            self.bind('acl_get_fd',[ctypes.c_int],ctypes.c_void_p)
            self.bind('acl_get_file',[ctypes.c_char_p,ctypes.c_int],ctypes.c_void_p)
            self.bind('acl_to_any_text',[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_char,ctypes.c_int],ctypes.c_void_p)
            self.bind('acl_from_text',[ctypes.c_char_p],ctypes.c_void_p)
            self.bind('acl_valid',[ctypes.c_void_p],ctypes.c_int)
            self.bind('acl_entries',[ctypes.c_void_p],ctypes.c_int)
            self.bind('acl_free',[ctypes.c_void_p],ctypes.c_int)
        except Exception:os.close(self.fd);self.fd=None;raise
    def bind(self,name,args,result):
        try:f=getattr(self.lib,name)
        except AttributeError:raise Stop('LIBACL_API_UNAVAILABLE')from None
        f.argtypes=args;f.restype=result
    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None
    def text(self,handle):
        need(bool(handle),'ACL_READ_UNSUPPORTED_OR_FAILED')
        pointer=None
        try:
            need(self.lib.acl_valid(handle)==0 and 3<=self.lib.acl_entries(handle)<=128,'ACL_LIBRARY_VALIDATION_FAILED')
            pointer=self.lib.acl_to_any_text(handle,None,b'\n',8) # TEXT_NUMERIC_IDS
            need(bool(pointer),'ACL_NUMERIC_RENDER_FAILED')
            text=ctypes.string_at(pointer).decode('ascii');need(len(text)<=8192,'ACL_TEXT_BOUND');parse(text)
            return text
        finally:
            if pointer:self.lib.acl_free(pointer)
            self.lib.acl_free(handle)
    def get(self,fd):
        ctypes.set_errno(0);handle=self.lib.acl_get_fd(fd)
        if not handle and ctypes.get_errno()in{38,95}:raise Stop('POSIX_ACL_NOT_SUPPORTED')
        return self.text(handle)
    def default(self,fd):
        return self.text(self.lib.acl_get_file(('/proc/self/fd/'+str(fd)).encode(),0x4000)) # ACL_TYPE_DEFAULT
    def prepare(self,text):
        need(type(text)is str and '\x00'not in text and len(text)<=8192,'ACL_SET_TEXT_BOUND');parse(text)
        handle=self.lib.acl_from_text(text.encode('ascii'));need(bool(handle),'ACL_PLAN_PARSE_FAILED')
        try:need(self.lib.acl_valid(handle)==0,'ACL_PLAN_VALIDATION_FAILED')
        except Exception:self.lib.acl_free(handle);raise
        return handle
    def validate_plan(self,text):
        handle=self.prepare(text);self.lib.acl_free(handle)


def snapshot(fd,acl):
    before=os.fstat(fd);info=metadata(fd)
    access=attr(fd,ACCESS);default=attr(fd,DEFAULT)
    text=acl.get(fd);need(mode_of(parse(text))==info['mode']&0o777,'ACL_STAT_MODE_INCONSISTENT')
    default_text=acl.default(fd)if default is not None else None
    need((access,default)==(attr(fd,ACCESS),attr(fd,DEFAULT)),'ACL_CHANGED_DURING_READ')
    after=os.fstat(fd)
    need((before.st_dev,before.st_ino,before.st_uid,before.st_gid,before.st_mode,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_uid,after.st_gid,after.st_mode,after.st_ctime_ns),'ACL_SNAPSHOT_CHANGED')
    return {'metadata':info,'access_raw':access,'default_raw':default,'access_text':text,'default_text':default_text}
