"""Startup update check and detached update worker for Nuitka standalone."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import ctypes
from boom_update_core import VERSION, verify,version,prepare,apply
from gateway_client import SERVER_URL,request_json

class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        from urllib.parse import urlsplit
        parsed=urlsplit(newurl)
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.hostname not in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):
            raise ValueError('Invalid update redirect')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def download(release,directory):
    path=Path(directory)/'release.zip';size=0
    url=release.get('download_url')
    if url:
        import re
        if not re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/boom-miniapp/releases/download/v'+re.escape(release['version'])+r'/BOOM-miniapp-update\.zip',url):raise ValueError('Invalid BOOM release URL')
    else:url=SERVER_URL+'/api/boommini/update/files/'+release['sha256']+'.zip'
    with urllib.request.build_opener(SafeRedirect).open(url,timeout=30) as response,path.open('xb') as output:
        while True:
            block=response.read(1024*1024)
            if not block:break
            size+=len(block)
            if size>release['size']:raise ValueError('Download too large')
            output.write(block)
    if size!=release['size']:raise ValueError('Download incomplete')
    return path

def launch_worker(envelope):
    release=verify(envelope)
    directory=Path(tempfile.mkdtemp(prefix='boom-update-'))
    archive=download(release,directory)
    prepare(archive,directory/'precheck',release)
    install=Path(sys.executable).resolve().parent
    helper=directory/'helper'
    shutil.copytree(install,helper,ignore=shutil.ignore_patterns('poster_cache','__pycache__','boom_history.json','*.boom-update-new'))
    job={'target':str(install),'pid':os.getpid(),'envelope':envelope}
    (directory/'job.json').write_text(json.dumps(job),encoding='utf-8')
    subprocess.Popen([str(helper/'BOOM miniapp.exe'),'--boom-apply-update',str(directory/'job.json')],cwd=helper,creationflags=subprocess.CREATE_NO_WINDOW)

def worker(job_file):
    directory=Path(job_file).resolve().parent
    job=json.loads(Path(job_file).read_text(encoding='utf-8'))
    target=Path(job['target']).resolve()
    try:
        release=verify(job['envelope'])
        names=prepare(directory/'release.zip',directory/'stage',release)
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32];kernel.WaitForSingleObject.restype=ctypes.c_uint32
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x100000,False,job['pid'])
        if handle:
            try:
                if kernel.WaitForSingleObject(handle,60000)!=0:raise RuntimeError('App did not close')
            finally:kernel.CloseHandle(handle)
        if not (target/'BOOM miniapp.exe').is_file():raise ValueError('Invalid installation')
        apply(directory/'stage',target,directory/'backup',names)
        subprocess.Popen([str(target/'BOOM miniapp.exe'),'--boom-updated'],cwd=target)
    except Exception as error:
        (directory/'error.txt').write_text(str(error),encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(None,'Cập nhật chưa hoàn tất. Bản cũ được giữ hoặc phục hồi. Nhật ký: '+str(directory/'error.txt'),'BOOM miniapp',0x10)
    return 0

def startup(app):
    if '__compiled__' not in globals() or '--boom-updated' in sys.argv:return False
    from PyQt6.QtCore import QObject,pyqtSignal
    from PyQt6.QtWidgets import QDialog,QVBoxLayout,QLabel,QMessageBox
    class Signals(QObject):ready=pyqtSignal(object)
    dialog=QDialog();dialog.setWindowTitle('BOOM miniapp • Cập nhật')
    dialog.setFixedWidth(390)
    dialog.setStyleSheet('QWidget{background:#141e2b;color:#edf3fa;font:14px "Segoe UI";} QLabel{padding:18px;}')
    layout=QVBoxLayout(dialog);note=QLabel('Đang kiểm tra phiên bản mới…');note.setWordWrap(True);layout.addWidget(note)
    signals=Signals();state={'install':False,'busy':True}
    # No close while a worker is preparing an install; it must not run behind a new app session.
    dialog.reject=lambda:None
    def finished(result):
        if isinstance(result,Exception):
            if state['install']:QMessageBox.information(dialog,'Cập nhật','Chưa cập nhật được. Bạn vẫn có thể dùng bản hiện tại.')
            state['install']=False;dialog.accept();return
        if result=='launched':dialog.accept();return
        if result is None:dialog.accept();return
        release,envelope=result
        state['install']=True;note.setText('Đang tải và xác thực bản mới… App sẽ tự mở lại khi hoàn tất.')
        def install():
            try:launch_worker(envelope);signals.ready.emit('launched')
            except Exception as error:signals.ready.emit(error)
        threading.Thread(target=install,daemon=True).start()
    signals.ready.connect(finished)
    def check():
        try:
            envelope=request_json(SERVER_URL,'/api/boommini/update/latest',timeout=8)
            if envelope.get('available') is False:signals.ready.emit(None);return
            release=verify(envelope)
            signals.ready.emit((release,envelope) if version(release['version'])>version(VERSION) else None)
        except Exception as error:signals.ready.emit(error)
    threading.Thread(target=check,daemon=True).start();dialog.exec()
    return state['install']
