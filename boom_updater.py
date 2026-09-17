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

def download(release,directory,progress=lambda *args:None):
    path=Path(directory)/'release.zip';size=0
    progress('Đang tải bản cập nhật…',0,release['size'])
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
            progress("Đang tải bản cập nhật…",size,release["size"])
    if size!=release['size']:raise ValueError('Download incomplete')
    return path

def launch_worker(envelope,progress=lambda *args:None):
    release=verify(envelope)
    directory=Path(tempfile.mkdtemp(prefix='boom-update-'))
    archive=download(release,directory,progress)
    progress('Đang kiểm tra và giải nén bản cập nhật…',0,0)
    prepare(archive,directory/'precheck',release)
    progress('Đang chuẩn bị thay thế ứng dụng…',0,0)
    install=Path(sys.executable).resolve().parent
    helper=directory/'helper'
    shutil.copytree(install,helper,ignore=shutil.ignore_patterns('poster_cache','__pycache__','boom_history.json','*.boom-update-new'))
    job={'target':str(install),'pid':os.getpid(),'envelope':envelope}
    (directory/'job.json').write_text(json.dumps(job),encoding='utf-8')
    subprocess.Popen([str(helper/'BOOM miniapp.exe'),'--boom-apply-update',str(directory/'job.json')],cwd=helper,creationflags=subprocess.CREATE_NO_WINDOW)

def apply_job(job_file,progress):
    directory=Path(job_file).resolve().parent
    job=json.loads(Path(job_file).read_text(encoding='utf-8'))
    target=Path(job['target']).resolve()
    try:
        progress('Đang xác thực và giải nén…',0,0)
        release=verify(job['envelope'])
        names=prepare(directory/'release.zip',directory/'stage',release)
        progress('Đang chờ ứng dụng cũ đóng…',0,0)
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
        progress('Đang sao lưu và thay file chương trình…',0,0)
        apply(directory/'stage',target,directory/'backup',names)
        progress('Đang mở BOOM phiên bản mới…',0,0)
        subprocess.Popen([str(target/'BOOM miniapp.exe'),'--boom-updated'],cwd=target)
    except Exception as error:
        (directory/'error.txt').write_text(str(error),encoding='utf-8')
        raise RuntimeError('Cập nhật chưa hoàn tất. Nhật ký: '+str(directory/'error.txt')) from error
    return 0

def progress_dialog():
    from PyQt6.QtCore import QObject,pyqtSignal
    from PyQt6.QtWidgets import QDialog,QVBoxLayout,QLabel,QProgressBar
    class Signals(QObject):
        ready=pyqtSignal(object)
        progress=pyqtSignal(str,object,object)
    dialog=QDialog();dialog.setWindowTitle('BOOM miniapp • Cập nhật')
    dialog.setFixedWidth(460)
    dialog.setStyleSheet('QWidget{background:#141e2b;color:#edf3fa;font:14px "Segoe UI";} QProgressBar{border:1px solid #34465b;border-radius:5px;min-height:24px;text-align:center;} QProgressBar::chunk{background:#24bca9;}')
    layout=QVBoxLayout(dialog);layout.setContentsMargins(24,24,24,24)
    title=QLabel('Đang cập nhật BOOM miniapp');title.setStyleSheet('font-size:19px;font-weight:bold;');layout.addWidget(title)
    note=QLabel('Đang kiểm tra phiên bản mới…');note.setWordWrap(True);layout.addWidget(note)
    bar=QProgressBar();bar.setRange(0,0);layout.addWidget(bar)
    detail=QLabel('Vui lòng chờ. Ứng dụng sẽ tự mở khi hoàn tất.');detail.setWordWrap(True);layout.addWidget(detail)
    signals=Signals()
    def update(text,done,total):
        note.setText(text)
        if total>0:
            bar.setRange(0,100);bar.setValue(min(100,int(done*100/total)))
            detail.setText(f'{done/1048576:.1f} / {total/1048576:.1f} MB')
        else:
            bar.setRange(0,0);detail.setText('Đang xử lý, vui lòng chờ…')
    signals.progress.connect(update)
    dialog.reject=lambda:None
    return dialog,signals

def worker(job_file):
    from PyQt6.QtWidgets import QApplication,QMessageBox
    app=QApplication.instance() or QApplication([])
    dialog,signals=progress_dialog();state={'code':0}
    def done(result):
        if isinstance(result,Exception):
            state['code']=1;QMessageBox.warning(dialog,'Cập nhật chưa hoàn tất',str(result))
        dialog.accept()
    signals.ready.connect(done)
    def run():
        try:apply_job(job_file,signals.progress.emit);signals.ready.emit(None)
        except Exception as error:signals.ready.emit(error)
    threading.Thread(target=run,daemon=True).start();dialog.exec()
    return state['code']

def startup(app):
    if '__compiled__' not in globals() or '--boom-updated' in sys.argv:return False
    from PyQt6.QtWidgets import QMessageBox
    dialog,signals=progress_dialog();state={'install':False}
    def finished(result):
        if isinstance(result,Exception):
            if state['install']:QMessageBox.information(dialog,'Cập nhật','Chưa cập nhật được. Bạn vẫn có thể dùng bản hiện tại.')
            state['install']=False;dialog.accept();return
        if result=='launched':dialog.accept();return
        if result is None:dialog.accept();return
        release,envelope=result
        state['install']=True
        signals.progress.emit('Chuẩn bị cập nhật lên v'+release['version']+'…',0,0)
        def install():
            try:launch_worker(envelope,signals.progress.emit);signals.ready.emit('launched')
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
