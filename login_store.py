"""Remember login details encrypted for the current Windows user."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def _crypt(data,decrypt=False):
    if os.name!='nt':raise OSError('Windows required')
    buffer=ctypes.create_string_buffer(data)
    source=Blob(len(data),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)))
    output=Blob()
    library=ctypes.WinDLL('crypt32',use_last_error=True)
    function=library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    function.restype=wintypes.BOOL
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(output.data,output.size)
    finally:
        free=ctypes.WinDLL('kernel32').LocalFree
        free.argtypes=[ctypes.c_void_p];free.restype=ctypes.c_void_p
        free(output.data)

def location():
    return Path(os.environ['LOCALAPPDATA'])/'BOOM miniapp'/'login.dat'

def load():
    try:
        value=json.loads(_crypt(location().read_bytes(),True).decode('utf-8'))
        if isinstance(value.get('username'),str) and isinstance(value.get('password'),str):return value
    except (OSError,ValueError,KeyError,AttributeError):pass
    return {}

def clear():
    location().unlink(missing_ok=True)

def save(username,password):
    encrypted=_crypt(json.dumps(dict(username=username,password=password)).encode('utf-8'))
    path=location();path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_bytes(encrypted);temporary.replace(path)
