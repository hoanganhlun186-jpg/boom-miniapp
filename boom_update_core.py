"""BOOM-only signed release validation and rollback-capable file installation."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

APP_ID='boom-miniapp-windows-x64'
VERSION='1.0.7'
MAX_ZIP=1024*1024*1024
MAX_UNPACKED=3*MAX_ZIP
RESERVED={'boom_history.json','login.dat','poster_cache','__pycache__'}

def version(value):
    if not isinstance(value,str) or not re.fullmatch(r'(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})',value):
        raise ValueError('Invalid version')
    return tuple(map(int,value.split('.')))

def verify(envelope,public_file=None):
    payload=base64.b64decode(envelope['payload'],validate=True)
    signature=base64.b64decode(envelope['signature'],validate=True)
    if len(payload)>32768:raise ValueError('Manifest too large')
    key=json.loads(Path(public_file or Path(__file__).with_name('boom_update_public.json')).read_text(encoding='utf-8-sig'))
    n=int.from_bytes(base64.b64decode(key['n']),'big');e=int.from_bytes(base64.b64decode(key['e']),'big')
    size=(n.bit_length()+7)//8
    if len(signature)!=size or int.from_bytes(signature,'big')>=n:raise ValueError('Invalid signature')
    digest_info=bytes.fromhex('3031300d060960864801650304020105000420')+hashlib.sha256(payload).digest()
    expected=b'\x00\x01'+b'\xff'*(size-len(digest_info)-3)+b'\x00'+digest_info
    actual=pow(int.from_bytes(signature,'big'),e,n).to_bytes(size,'big')
    if not hmac.compare_digest(expected,actual):raise ValueError('Invalid signature')
    result=json.loads(payload)
    if result.get('app')!=APP_ID:raise ValueError('Wrong application')
    version(result.get('version'))
    if not re.fullmatch('[0-9a-f]{64}',result.get('sha256','')):raise ValueError('Invalid checksum')
    if type(result.get('size')) is not int or not 0<result['size']<=MAX_ZIP:raise ValueError('Invalid size')
    return result

def archive_files(archive):
    entries=[];seen=set();size=0
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name=info.filename
            path=PurePosixPath(name)
            if any(p in ('.','..','') for p in name.rstrip('/').split('/')) or '\\' in name or ':' in name or path.is_absolute() or not path.parts or any(p in ('.','..') or p.endswith((' ','.')) for p in path.parts):raise ValueError('Unsafe archive path')
            if stat.S_ISLNK(info.external_attr>>16):raise ValueError('Archive contains link')
            if path.parts[0].lower() in RESERVED:raise ValueError('Archive overwrites user data')
            if any(re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',p,re.I) for p in path.parts):raise ValueError('Reserved Windows name')
            if info.is_dir():continue
            folded=name.casefold()
            if folded in seen:raise ValueError('Duplicate file')
            seen.add(folded);size+=info.file_size
            if size>MAX_UNPACKED or len(seen)>30000:raise ValueError('Archive too large')
            entries.append(name)
    if 'BOOM miniapp.exe' not in entries or 'boom-release.json' not in entries:raise ValueError('Not a BOOM standalone release')
    return entries

def prepare(archive,stage,release):
    archive=Path(archive)
    if archive.stat().st_size!=release['size']:raise ValueError('Size mismatch')
    h=hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    if h.hexdigest()!=release['sha256']:raise ValueError('Checksum mismatch')
    names=archive_files(archive)
    stage=Path(stage);stage.mkdir(parents=True,exist_ok=False)
    with zipfile.ZipFile(archive) as z:
        for name in names:
            target=stage/name;target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(name) as source,target.open('xb') as output:shutil.copyfileobj(source,output)
    marker=json.loads((stage/'boom-release.json').read_text(encoding='utf-8'))
    if marker!={'app':APP_ID,'version':release['version']}:raise ValueError('Release metadata mismatch')
    return names

def apply(stage,target,backup,names):
    stage,target,backup=map(lambda p:Path(p).resolve(),(stage,target,backup))
    backup.mkdir(parents=True,exist_ok=False)
    changed=[]
    try:
        for name in names:
            dst=target/name
            if not dst.resolve().is_relative_to(target):raise ValueError('Destination escapes app directory')
            old=backup/name
            existed=dst.exists()
            if existed:
                old.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dst,old)
            changed.append((name,existed))
            dst.parent.mkdir(parents=True,exist_ok=True)
            temporary=dst.with_name(dst.name+'.boom-update-new')
            shutil.copy2(stage/name,temporary);os.replace(temporary,dst)
    except Exception:
        for name,existed in reversed(changed):
            dst=target/name
            if existed:shutil.copy2(backup/name,dst)
            else:dst.unlink(missing_ok=True)
        raise
