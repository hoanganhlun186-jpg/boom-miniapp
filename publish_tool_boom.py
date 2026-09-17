"""BOOM-only version bump and atomic GitHub push. Run from a cloned BOOM repo."""
import ast
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog,messagebox

PATTERN=re.compile(r"(?m)^VERSION\s*=\s*(['\"])(\d+\.\d+\.\d+)\1\s*$")

def git(root,*args,check=True):
    result=subprocess.run(['git','-C',str(root),*args],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if check and result.returncode:raise RuntimeError((result.stderr or result.stdout).strip())
    return result.stdout.strip() if check else result

def info(root):
    root=Path(root).resolve()
    if git(root,'rev-parse','--show-toplevel',check=False).returncode:
        raise ValueError('Thư mục này chỉ là bản giải nén, chưa kết nối GitHub. Clone boom-miniapp bằng GitHub Desktop rồi chọn thư mục đã clone.')
    if Path(git(root,'rev-parse','--show-toplevel')).resolve()!=root:raise ValueError('Chọn đúng thư mục gốc repository BOOM đã clone.')
    text=(root/'boom_update_core.py').read_text(encoding='utf-8-sig')
    tree=ast.parse(text)
    appid=next((ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='APP_ID' for t in n.targets)),None)
    if appid!='boom-miniapp-windows-x64':raise ValueError('Đây không phải CLIENT BOOM.')
    matches=list(PATTERN.finditer(text))
    if len(matches)!=1:raise ValueError('Không tìm thấy một VERSION hợp lệ trong boom_update_core.py.')
    if not (root/'.github/workflows/build.yml').is_file():raise ValueError('Thiếu .github/workflows/build.yml')
    remote=git(root,'remote','get-url','origin')
    if not re.fullmatch(r'(?:https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/boom-miniapp(?:\.git)?/?',remote,re.I):
        raise ValueError('origin phải là repository boom-miniapp trên GitHub. Không dùng repository Hongguo/Riview.')
    branch=git(root,'branch','--show-current')
    if branch not in ('main','master'):raise ValueError('Chuyển sang main hoặc master trước khi Publish.')
    state=Path(git(root,'rev-parse','--absolute-git-dir'))/'boom-publish-pending.json'
    return text,matches[0].group(2),branch,state,remote

def allowed(name):
    p=Path(name);low=name.lower()
    if any(part in ('poster_cache','__pycache__','build','.venv') for part in p.parts):return False
    if name=='sign_release.ps1':return True  # Public signing code, never a key.
    if any(word in low for word in ('private','secret','.env','login.dat','boom_history','server.py','boom_gateway','boom_updates','publish_boom','sign_release')):return False
    if name.startswith('.github/workflows/'):return p.suffix in ('.yml','.yaml')
    if name.startswith('icons/'):return p.suffix=='.svg'
    return len(p.parts)==1 and (p.suffix in ('.py','.svg','.bat','.md') or name in ('requirements.txt','.gitignore','boom_update_public.json'))

def publish(root):
    root=Path(root).resolve();text,current,branch,state,remote=info(root)
    if state.exists():
        pending=json.loads(state.read_text(encoding='utf-8'))
        if pending['branch']!=branch or pending['remote']!=remote or git(root,'rev-parse','HEAD')!=pending['commit']:
            raise ValueError('Có bản phát hành chờ push nhưng repository đã thay đổi. Không tự tăng phiên bản; kiểm tra commit trước.')
        tag=pending['tag']
        if git(root,'show-ref','--verify','--quiet','refs/tags/'+tag,check=False).returncode!=0:git(root,'tag',tag,pending['commit'])
        if git(root,'rev-parse',tag)!=pending['commit']:raise ValueError('Tag chờ push không khớp.')
    else:
        if git(root,'diff','--cached','--name-only'):raise ValueError('Có file đang staged. Commit hoặc bỏ stage trước khi Publish BOOM.')
        git(root,'fetch','origin',branch)
        if git(root,'rev-list','--count','HEAD..origin/'+branch)!='0':raise ValueError('GitHub có commit mới. Pull trước khi Publish.')
        names=set(filter(None,git(root,'ls-files','-m','-d','-o','--exclude-standard').splitlines()))
        rejected=sorted(n for n in names if not allowed(n))
        if rejected:raise ValueError('Không tự đưa các file này lên GitHub: '+', '.join(rejected))
        parts=list(map(int,current.split('.')));parts[2]+=1
        new='.'.join(map(str,parts));tag='v'+new
        if git(root,'show-ref','--verify','--quiet','refs/tags/'+tag,check=False).returncode==0:raise ValueError('Tag '+tag+' đã tồn tại.')
        if git(root,'ls-remote','--tags','origin','refs/tags/'+tag):raise ValueError('GitHub đã có tag '+tag)
        path=root/'boom_update_core.py';original=path.read_bytes()
        path.write_text(PATTERN.sub("VERSION='"+new+"'",text),encoding='utf-8')
        names.add('boom_update_core.py')
        committed=False
        try:
            git(root,'add','--',*sorted(names))
            git(root,'commit','-m','Release BOOM '+tag);committed=True
            commit=git(root,'rev-parse','HEAD')
            # Save retry state before tagging/pushing; never rewind a published commit.
            state.write_text(json.dumps({'branch':branch,'remote':remote,'tag':tag,'commit':commit}),encoding='utf-8')
            git(root,'tag',tag)
        except Exception:
            if not committed:
                git(root,'reset','--quiet','HEAD','--',*sorted(names));path.write_bytes(original)
            raise
    pending=json.loads(state.read_text(encoding='utf-8'))
    git(root,'push','--atomic','origin',pending['commit']+':refs/heads/'+branch,'refs/tags/'+tag+':refs/tags/'+tag)
    state.unlink()
    return tag

def main():
    window=tk.Tk();window.title('Publish — BOOM miniapp');window.geometry('430x230')
    root=Path(__file__).resolve().parent
    status=tk.StringVar()
    tk.Label(window,text='PHÁT HÀNH BOOM MINIAPP',font=('Segoe UI',14,'bold')).pack(pady=16)
    def refresh():
        try:
            _,version,_,pending,_=info(root)
            status.set('Phiên bản hiện tại: v'+version+(' • Đang chờ đẩy lại' if pending.exists() else ''))
        except Exception:
            status.set('Đặt file này cạnh studio_qt.py trong repository boom-miniapp đã kết nối GitHub.')
    tk.Label(window,textvariable=status,wraplength=390).pack(pady=8)
    results=__import__('queue').Queue()
    def start():
        button.config(state='disabled');status.set('Đang tăng phiên bản và đẩy lên GitHub…')
        def work():
            try:results.put((True,publish(root)))
            except Exception as error:results.put((False,str(error)))
        threading.Thread(target=work,daemon=True).start()
        window.after(100,poll)
    def poll():
        try:ok,value=results.get_nowait()
        except __import__('queue').Empty:
            window.after(100,poll);return
        button.config(state='normal');refresh()
        if ok:messagebox.showinfo('BOOM miniapp','Đã đẩy '+value+' lên GitHub. GitHub Actions sẽ build bản cập nhật.')
        else:messagebox.showerror('Chưa phát hành được',value+'\n\nNếu push lỗi sau khi tạo commit, bấm lại để thử cùng phiên bản.')
    button=tk.Button(window,text='Nâng cấp & Phát hành ngay',bg='#10b981',fg='white',font=('Segoe UI',11,'bold'),command=start)
    button.pack(pady=15)
    window.protocol('WM_DELETE_WINDOW',lambda:window.destroy() if str(button['state'])!='disabled' else None)
    refresh();window.mainloop()

if __name__=='__main__':main()
