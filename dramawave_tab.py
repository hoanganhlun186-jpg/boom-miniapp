"""DramaWave tab backed by the Ezvid DramaWave API."""
import queue
import threading
import re
import tkinter as tk
from tkinter import ttk
from urllib.parse import urlparse


def series_id(value):
    value = value.strip()
    link = re.search(r'https?://[^\s<>\]]+', value)
    if link:
        value = link.group().rstrip(').,').replace('\\&', '&')
    if re.fullmatch(r'[A-Za-z0-9_-]{6,80}', value):
        return value
    from urllib.parse import parse_qs
    p = urlparse(value)
    if p.hostname and any(p.hostname == d or p.hostname.endswith('.'+d) for d in ('dramawave.com','mydramawave.com')):
        query = parse_qs(p.query)
        for name in ('drama_id','dramaId','id','book_id'):
            candidate = query.get(name,[''])[0]
            if re.fullmatch(r'[A-Za-z0-9_-]{1,80}',candidate):
                return candidate
        match = re.search(r'/(?:share/episode|drama|detail|video)/([A-Za-z0-9_-]+)(?:/|$)',p.path)
        if match:
            return match[1]
    return None


def movies(payload):
    rows, seen = [], set()
    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            sid = str(node.get('season_id') or node.get('seasonId') or node.get('id') or '')
            title = node.get('title') or node.get('name')
            if re.fullmatch(r'[A-Za-z0-9_-]{1,80}', sid) and title and sid not in seen:
                seen.add(sid)
                rows.append((sid, str(title), str(node.get('episodeCount') or (node.get('extra') or {}).get('episodeCount') or node.get('totalEpisodes') or '—')))
            for val in node.values():
                if isinstance(val, (list, dict)):
                    walk(val)
    walk(payload.get('data', payload))
    return rows


class DramaWaveTab(ttk.Frame):
    def __init__(self, owner):
        super().__init__(owner.outer_tabs, padding=12)
        from netshort_tool import DownloadPanel
        self.local_tabs = ttk.Notebook(self)
        self.local_tabs.pack(fill='both', expand=True)
        catalog = ttk.Frame(self.local_tabs, padding=12)
        self.local_tabs.add(catalog, text='Thư viện DramaWave')
        self.downloader = DownloadPanel(parent=self.local_tabs, fixed_provider='dramawave')
        self.local_tabs.add(self.downloader, text='Chọn tập / Cài đặt DramaWave')
        self.downloader.base.set(owner.base.get())
        self.downloader.key.set(owner.key.get())
        self.downloader.language.set('vi-VN')
        self.downloader.log.configure(bg='#1e293b', fg='#94a3b8', relief='flat', borderwidth=0)
        self.downloader.scan_button.configure(style='Primary.TButton')
        self.downloader.download_button.configure(style='Primary.TButton')
        self.events = queue.Queue()
        self.busy = False
        self.stop = threading.Event()
        self.query = tk.StringVar()
        self.language = tk.StringVar(value='vi-VN')
        ttk.Label(catalog, text='DramaWave', font=('Segoe UI', 24, 'bold')).pack(anchor='w')
        ttk.Label(catalog, text='Phim ngắn • DramaWave API', foreground='#94a3b8').pack(anchor='w', pady=(0,16))
        bar = ttk.Frame(catalog)
        bar.pack(fill='x')
        entry = ttk.Entry(bar, textvariable=self.query)
        entry.pack(side='left', fill='x', expand=True)
        entry.bind('<Return>', lambda e: self.search())
        ttk.Button(bar, text='Tìm tên / Mở link', command=self.search, style='Primary.TButton').pack(side='left', padx=8)
        ttk.Combobox(bar, textvariable=self.language, values=('vi-VN','en-US','id-ID','th-TH','zh-CN'), width=8, state='readonly').pack(side='left')
        actions = ttk.Frame(catalog)
        actions.pack(fill='x', pady=12)
        for label, endpoint in [('Phim nổi bật','search/hot-list')]:
            ttk.Button(actions, text=label, command=lambda ep=endpoint: self.load(ep)).pack(side='left', padx=(0,8))
        ttk.Button(actions, text='Mở phim đã chọn', command=self.open_selected).pack(side='right')
        self.info = tk.StringVar(value='Nhập tên hoặc dán link share DramaWave. Nhấp đôi kết quả để chọn tập và phụ đề.')
        ttk.Label(catalog, textvariable=self.info, wraplength=1000).pack(fill='x', pady=8)
        self.table = ttk.Treeview(catalog, columns=('title','count','id'), show='headings')
        for col, label, width in [('title','Tên phim',650),('count','Số tập',100),('id','Series ID',200)]:
            self.table.heading(col,text=label)
            self.table.column(col,width=width)
        self.table.pack(fill='both',expand=True)
        self.table.bind('<Double-Button-1>',lambda e:self.open_selected())
        self.after(100,self.pump)

    def search(self):
        value = self.query.get().strip()
        link = re.search(r'https?://[^\s<>\]]+', value)
        if link:
            value = link.group().rstrip(').,')
        sid = series_id(value) if link or (re.search(r'[0-9]', value) and re.search(r'[A-Za-z]', value) and ' ' not in value) else None
        if sid:
            self.open(sid)
        elif value.startswith(('http://', 'https://')):
            self.info.set('Chưa nhận diện được link này. Dùng link DramaWave có ID hoặc nhập tên phim để tìm.')
        elif value:
            self.load('search', value)

    def open_selected(self):
        selected = self.table.selection()
        if selected:
            self.open(selected[0])

    def open(self, sid):
        owner = self.downloader
        if owner.busy:
            self.info.set('Chờ lượt quét/tải hiện tại kết thúc.')
            return
        owner.source_provider = 'dramawave'
        owner.provider_choice.set('DramaWave')
        owner.language.set(self.language.get())
        owner.sid.set('')
        owner.link.set(sid)
        self.local_tabs.select(self.downloader)
        owner.scan()

    def load(self, endpoint, query=''):
        if self.busy:
            return
        from netshort_tool import API, ToolError
        self.busy = True
        settings = (self.downloader.base.get().strip(), self.downloader.key.get(), self.language.get())
        self.info.set('Đang lấy dữ liệu DramaWave…')
        def worker():
            try:
                api = API(*settings,self.stop)
                p = api.get('/api/dramawave/'+endpoint, {'q':query} if query else {})
                self.events.put(('rows',movies(p)))
            except Exception as e:
                self.events.put(('error',str(e) if isinstance(e,ToolError) else type(e).__name__))
        threading.Thread(target=worker,daemon=True).start()

    def pump(self):
        try:
            kind, value = self.events.get_nowait()
            self.busy = False
            if kind=='error':
                self.info.set(value)
            else:
                self.table.delete(*self.table.get_children())
                for sid,title,count in value:
                    self.table.insert('', 'end', iid=sid, values=(title,count,sid))
                self.info.set(f'API trả {len(value)} phim. Nhấp đôi để lấy danh sách tập.' if value else 'Chưa có phim hoặc cấu trúc dữ liệu chưa được hỗ trợ.')
        except queue.Empty:
            pass
        self.after(100,self.pump)
