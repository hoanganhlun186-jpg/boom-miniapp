"""NetShort / Ezvid Tkinter prototype. Python 3.10+, standard library only.

This client uses authenticated BOOM server sessions; no upstream key is included.
Downloads direct video files; HLS/DASH/DRM are deliberately unsupported.
"""
import html
import http.client
import json
import os
from pathlib import Path
import queue
import re
import threading
import tkinter as tk
from netshort_subtitles import tracks as subtitle_tracks, as_srt, language_matches
from studio_files import safe_name, episode_stem
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urlparse, urljoin, parse_qs, urlencode, unquote


class ToolError(Exception):
    pass


class Cancelled(ToolError):
    pass


def https_url(url):
    p = urlparse(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ToolError('URL phải dùng HTTPS và không chứa thông tin đăng nhập.')
    return p


def error_detail(raw, headers=None):
    """Show a bounded server explanation, never credentials or signed URLs."""
    text = raw.decode('utf-8', 'replace')
    try:
        data = json.loads(text)
        parts = []
        def collect(node):
            if isinstance(node, dict):
                for name in ('message', 'error', 'detail', 'reason', 'code'):
                    value = node.get(name)
                    if isinstance(value, (str, int)):
                        parts.append(str(value))
                    elif isinstance(value, dict):
                        collect(value)
        collect(data)
        text = ' | '.join(parts) or 'Máy chủ trả JSON lỗi nhưng không có lời giải thích.'
    except ValueError:
        if '<html' in text.lower() or '<!doctype' in text.lower():
            match = re.search(r'<title[^>]*>(.*?)</title>', text, re.I | re.S)
            title = html.unescape(re.sub(r'<[^>]+>', '', match.group(1))) if match else ''
            text = 'Máy chủ trả trang HTML' + (': ' + title if title else ', không có JSON giải thích lỗi.')
        else:
            text = 'Máy chủ không trả JSON giải thích lỗi.'
    for name, value in (headers or {}).items():
        if name.lower() in ('x-api-key', 'authorization') and value:
            text = text.replace(value, '[đã ẩn key]')
    text = re.sub(r'ak_[A-Za-z0-9_-]+', '[đã ẩn key]', text)
    text = re.sub(r'https?://\S+', '[đã ẩn URL]', text)
    return ' '.join(text.split())[:500]


class Response:
    """Own the connection until the caller finishes streaming the response."""
    def __init__(self, connection, response, url):
        self.connection, self.response, self.url = connection, response, url
        self.headers = response.headers

    def read(self, size=-1):
        return self.response.read(size)

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.response.close()
        finally:
            self.connection.close()


def fetch(url, headers=None, stop=None, api=False, timeout=25):
    """Use the documented http.client transport; no retries on HTTP errors."""
    for _ in range(8):
        if stop and stop.is_set():
            raise Cancelled('Đã dừng.')
        parsed = https_url(url)
        connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout)
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        try:
            connection.request('GET', path, headers=headers or {})
            response = connection.getresponse()
            code = response.status
            if 200 <= code < 300:
                return Response(connection, response, url)
            location = response.headers.get('Location')
            try:
                detail = error_detail(response.read(16384), headers)
            except Exception:
                detail = 'Không đọc được lời giải thích của máy chủ.'
            finally:
                response.close()
                connection.close()
            if code in (301, 302, 303, 307, 308) and location:
                if api:
                    raise ToolError('API chuyển hướng. Hãy nhập Base URL chính xác; key chưa được gửi tiếp.')
                url = urljoin(url, location)
                continue
            labels = {401: 'API key không hợp lệ', 403: 'không được phép truy cập; không thử vượt khóa',
                      404: 'không tìm thấy', 429: 'hết hạn mức hoặc quá nhiều yêu cầu; hãy thử lại sau'}
            raise ToolError(f'HTTP {code}: {labels.get(code, "máy chủ trả lỗi")}. Máy chủ: {detail}') from None
        except (http.client.HTTPException, TimeoutError, OSError):
            connection.close()
            raise ToolError('Lỗi kết nối HTTPS hoặc hết thời gian chờ (25 giây).') from None
        except Exception:
            connection.close()
            raise
    raise ToolError('Link chuyển hướng quá nhiều lần.')


def limited_read(response, limit=8 * 1024 * 1024):
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ToolError('Phản hồi quá lớn.')
    return raw


ID_KEYS = ('shortPlayId', 'dramaId', 'seriesId', 'short_play_id', 'drama_id', 'series_id')


def ids_in_url(url):
    p = urlparse(html.unescape(url))
    query = parse_qs(p.query)
    found = set()
    for name in ID_KEYS:
        found.update(v for v in query.get(name, []) if re.fullmatch(r'\d{8,25}', v))
    # NetShort public drama/episode URLs end their title slug with the series ID.
    if p.hostname and (p.hostname == 'netshort.com' or p.hostname.endswith('.netshort.com')):
        for segment in p.path.split('/'):
            m = re.search(r'(?:^|-)(\d{15,25})(?:-ep-\d+)?$', unquote(segment), re.I)
            if m:
                found.add(m.group(1))
    return found


def choose_id(ids):
    if len(ids) == 1:
        return next(iter(ids))
    if len(ids) > 1:
        raise ToolError('Link/trang chứa nhiều ID bộ phim. Hãy nhập Series ID thủ công để tránh chọn nhầm.')
    return None


def resolve_series(value, stop):
    value = value.strip()
    if re.fullmatch(r'\d{8,25}', value):
        return value
    match = re.search(r'https://[^\s<>"\u201d]+', value)
    if not match:
        raise ToolError('Dán link HTTPS NetShort/share link hoặc Series ID dạng số.')
    url = match.group().rstrip(').,')
    p = https_url(url)
    allowed = ('netshort.com', 'netshortvip.com', 'fnetshare.com')
    if not any(p.hostname == d or p.hostname.endswith('.' + d) for d in allowed):
        raise ToolError('Link đầu vào phải thuộc NetShort, NetShortVIP hoặc fnetshare.com.')
    direct = choose_id(ids_in_url(url))
    if direct:
        return direct
    with fetch(url, stop=stop) as response:
        final_url = response.geturl()
        direct = choose_id(ids_in_url(final_url))
        if direct:
            return direct
        body = limited_read(response, 3 * 1024 * 1024).decode('utf-8', 'replace')
    body = html.unescape(unquote(body)).replace('\\"', '"').replace('\\/', '/')
    # Named IDs only: never mistake an opaque share token or an episode ID for a series ID.
    names = '|'.join(ID_KEYS)
    ids = set(re.findall(r'(?:' + names + r')["\s]*[:=]["\s]*(\d{8,25})', body))
    for link in re.findall(r'https://[^\s"<>]+', body):
        ids.update(ids_in_url(link))
    result = choose_id(ids)
    if not result:
        raise ToolError('Không tìm được series ID trong trang share công khai (có thể cần JavaScript). '
                        'Nhập ID vào ô Series ID thủ công rồi quét lại.')
    return result


from gateway_client import GatewayTransport

class API(GatewayTransport):
    def episodes(self, sid):
        result, seen, cursors = [], set(), set()
        params = {}
        title = sid
        series_total=0
        for _ in range(100):
            payload = self.get(f'/api/{self.provider}/episodes/{sid}', params)
            data = payload.get('data', payload)
            items = data.get('items', data.get('episodes')) if isinstance(data, dict) else data
            if not isinstance(items, list):
                raise ToolError('Full Episodes không có data.items/data.episodes dạng danh sách.')
            if isinstance(data,dict):
                try:series_total=max(series_total,int(data.get('total') or 0))
                except (ValueError,TypeError):pass
            meta = data.get('meta', {}) if isinstance(data, dict) else {}
            if not isinstance(meta, dict):
                meta = {}
            title = meta.get('title') or title
            for ep in items:
                if not isinstance(ep, dict):
                    continue
                eid = str(ep.get('id') or ep.get('episodeId') or '')
                if re.fullmatch(r'[A-Za-z0-9_-]{1,80}' if self.provider != 'netshort' else r'\d{1,25}', eid) and eid not in seen:
                    seen.add(eid)
                    result.append(dict(ep, id=eid))
            paging = data.get('pagination', {}) if isinstance(data, dict) else {}
            paging = paging if isinstance(paging, dict) else {}
            cursor = (data.get('nextCursor') if isinstance(data, dict) else None) or meta.get('nextCursor') or paging.get('nextCursor') or payload.get('nextCursor')
            if not cursor:
                if paging.get('hasMore') or meta.get('hasMore'):
                    raise ToolError('API báo còn trang nhưng không có nextCursor; chưa thể xác nhận đủ tập.')
                break
            cursor = str(cursor)
            if cursor in cursors:
                raise ToolError('API lặp cursor phân trang; chưa thể xác nhận đủ tập.')
            cursors.add(cursor)
            params = {'cursor': cursor}
        else:
            raise ToolError('Vượt giới hạn 100 trang; dừng quét.')
        def number(ep):
            try:
                return int(ep.get('episodeNumber') or ep.get('episodeNo') or 0)
            except (ValueError, TypeError):
                return 0
        result.sort(key=number)
        for ep in result:ep['_series_total']=max(series_total,len(result))
        return str(title), result



def source_candidates(payload):
    """Support both normalized Ezvid sources and raw NetShort play lists."""
    found = []
    def visit(node):
        if isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            for name in ('sources', 'episodePlayList'):
                rows = node.get(name)
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            url = row.get('url') or row.get('playVoucher')
                            if isinstance(url, str) and url.startswith('https://'):
                                found.append(dict(row, url=url))
            if isinstance(node.get('source'), dict):
                visit({'sources': [node['source']]})
            for name in ('data', 'items', 'episode'):
                if name in node:
                    visit(node[name])
            if isinstance(node.get('playVoucher'), str):
                found.append(dict(node, url=node['playVoucher']))
            elif isinstance(node.get('url'), str) and any(k in node for k in ('quality', 'type', 'referer')):
                if node['url'].startswith('https://'):
                    found.append(dict(node))
    visit(payload)
    def quality(row):
        m = re.search(r'\d+', str(row.get('quality') or row.get('playClarity') or '0'))
        return int(m.group()) if m else 0
    return sorted(found, key=quality, reverse=True)


def download(source, destination, stop, progress):
    url = source['url']
    kind = str(source.get('type', '')).lower()
    if '.m3u8' in urlparse(url).path.lower() or kind in ('hls', 'm3u8'):
        from dramawave_hls import download_hls
        return download_hls(url, destination, stop, lambda done,total: progress(done,total), referer=source.get('referer'))
    if any(x in urlparse(url).path.lower() for x in ('.m3u8', '.mpd')) or kind in ('hls', 'm3u8', 'dash', 'mpd'):
        raise ToolError('Source HLS/DASH chưa được bản thử nghiệm hỗ trợ; chỉ tải video trực tiếp.')
    headers = {}
    referer = source.get('referer')
    if isinstance(referer, str) and '\r' not in referer and '\n' not in referer:
        https_url(referer)
        headers['Referer'] = referer
    partial = destination.with_suffix('.mp4.part')
    if destination.exists() or partial.exists():
        raise ToolError('File hoặc file .part đã tồn tại; đổi thư mục/tên hoặc xóa file dở trước khi tải lại.')
    created = False
    try:
        with fetch(url, headers, stop) as r:
            ctype = r.headers.get('Content-Type', '').lower()
            if any(x in ctype for x in ('text/', 'json', 'mpegurl', 'dash+xml')):
                raise ToolError('Source trả văn bản/playlist, không phải file video trực tiếp.')
            try:
                total = int(r.headers.get('Content-Length', 0))
            except ValueError:
                total = 0
            done = 0
            with partial.open('xb') as f:
                created = True
                while True:
                    if stop.is_set():
                        raise Cancelled('Đã dừng tải.')
                    block = r.read(256 * 1024)
                    if not block:
                        break
                    if done == 0 and b'ftyp' not in block[:64]:
                        raise ToolError('Dữ liệu không có chữ ký MP4; không lưu thành video giả.')
                    f.write(block)
                    done += len(block)
                    progress(done, total)
            if not done or (total and done != total):
                raise ToolError('Video rỗng hoặc tải chưa đủ dung lượng.')
        # Exclusive final creation avoids overwriting another instance's download.
        os.link(partial, destination)
        partial.unlink()
    finally:
        if created and partial.exists():
            partial.unlink()


class AppLogic:
    def __init__(self, studio=False, parent=None, fixed_provider=None):
        if parent is None:
            super().__init__()
        else:
            super().__init__(parent)
        self.fixed_provider = fixed_provider
        if parent is None:
            self.title('NetShort — Ezvid thử nghiệm v1.2 — http.client')
            self.geometry('1000x730')
            self.minsize(780, 580)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.busy = False
        self.items, self.scanned = [], None
        self.source_provider = "netshort"
        self.scanned_provider = "netshort"
        self.base = tk.StringVar(value='http://163.61.182.119:8000')
        self.key = tk.StringVar(value='')
        self.link = tk.StringVar()
        self.sid = tk.StringVar()
        self.language = tk.StringVar(value='vi_VN')
        self.folder = tk.StringVar(value=str(Path.home() / 'Downloads' / 'NetShort'))
        container = self
        if studio:
            self.outer_tabs = ttk.Notebook(self)
            self.outer_tabs.pack(fill='both', expand=True, padx=12, pady=12)
            self.netshort_page = ttk.Frame(self.outer_tabs)
            self.outer_tabs.add(self.netshort_page, text='NetShort')
            self.tabs = ttk.Notebook(self.netshort_page)
            self.tabs.pack(fill='both', expand=True, padx=12, pady=12)
            self.download_tab = ttk.Frame(self.tabs)
            self.tabs.add(self.download_tab, text='Chọn tập / Cài đặt tải')
            container = self.download_tab
        top = ttk.Frame(container, padding=12)
        top.pack(fill='x')
        top.columnconfigure(1, weight=1)
        fields = [('Dán link phim hoặc ID', self.link),
                  ('Series ID thủ công (ưu tiên)', self.sid), ('Ngôn ngữ nội dung', self.language), ('Thư mục lưu', self.folder)]
        self.inputs = []
        for i, (label, var) in enumerate(fields):
            ttk.Label(top, text=label).grid(row=i, column=0, sticky='w', pady=4)
            entry = ttk.Entry(top, textvariable=var, show='*' if var is self.key else '')
            entry.grid(row=i, column=1, sticky='ew', padx=8, pady=4)
            self.inputs.append(entry)
        ttk.Button(top, text='Chọn thư mục', command=self.pick_folder).grid(row=3, column=2)
        ttk.Button(top, text='Cài đặt', command=self.connection_settings).grid(row=0, column=2, padx=6)
        buttons = ttk.Frame(container, padding=(12, 0))
        subtitle_options = ttk.Frame(container, padding=(12, 4))
        subtitle_options.pack(fill='x')
        self.provider_choice = tk.StringVar(value='NetShort')
        ttk.Label(subtitle_options, text='Nguồn:').pack(side='left')
        provider_box = ttk.Combobox(subtitle_options, textvariable=self.provider_choice,
                                  state='readonly', width=18, values=('NetShort', 'DramaWave'))
        provider_box.pack(side='left', padx=8)
        if fixed_provider or studio:
            self.fixed_provider = fixed_provider or 'netshort'
            self.provider_choice.set('DramaWave' if self.fixed_provider == 'dramawave' else 'NetShort')
            provider_box.configure(state='disabled')
        self.download_mode = tk.StringVar(value='Video + phụ đề')
        self.subtitle_language = tk.StringVar(value='vi')
        self.subtitle_results = {}
        ttk.Label(subtitle_options, text='Tải:').pack(side='left')
        ttk.Combobox(subtitle_options, textvariable=self.download_mode, state='readonly', width=20,
                     values=('Video', 'Video + phụ đề', 'Chỉ phụ đề')).pack(side='left', padx=8)
        ttk.Label(subtitle_options, text='Sub đã chọn:').pack(side='left')
        ttk.Label(subtitle_options, textvariable=self.subtitle_language, width=16).pack(side='left', padx=8)
        self.subtitles_button = ttk.Button(subtitle_options, text='Quét / Chọn ngôn ngữ SRT', command=self.scan_subtitles)
        self.subtitles_button.pack(side='left', padx=8)
        buttons.pack(fill='x')
        self.scan_button = ttk.Button(buttons, text='1. Quét Full Episodes', command=self.scan)
        self.scan_button.pack(side='left')
        ttk.Button(buttons, text='Chọn tất cả', command=lambda: self.tree.selection_set(self.tree.get_children())).pack(side='left', padx=8)
        ttk.Button(buttons, text='Bỏ chọn', command=lambda: self.tree.selection_remove(self.tree.selection())).pack(side='left')
        self.download_button = ttk.Button(buttons, text='2. Tải tập đã chọn', command=self.start_download)
        self.download_button.pack(side='left', padx=8)
        ttk.Button(buttons, text='Dừng', command=self.stop.set).pack(side='right')
        self.info = tk.StringVar(value='Dán link hoặc chọn phim trong thư viện để quét tập.')
        ttk.Label(container, textvariable=self.info, wraplength=950, padding=12).pack(fill='x')
        pane = ttk.Frame(container, padding=(12, 0))
        pane.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(pane, columns=('no', 'title', 'id', 'locked', 'status'), show='headings', selectmode='extended')
        for name, label, width in [('no', 'Tập', 50), ('title', 'Tên', 240), ('id', 'Episode ID', 190), ('locked', 'Khóa / VIP', 90), ('status', 'Trạng thái', 260)]:
            self.tree.heading(name, text=label)
            self.tree.column(name, width=width, minwidth=40)
        bar = ttk.Scrollbar(pane, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        self.progress = ttk.Progressbar(container, maximum=100)
        self.progress.pack(fill='x', padx=12, pady=8)
        self.log = tk.Text(container, height=7, state='disabled', wrap='word')
        self.log.pack(fill='x', padx=12, pady=(0, 12))
        # Reserve the log area before allocating remaining space to the episode table.
        self.log.pack_configure(side='bottom', before=pane)
        self.progress.pack_configure(side='bottom', before=pane)
        if parent is None:
            self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(100, self.pump)

    def connection_settings(self):
        if self.busy:
            return
        dialog = tk.Toplevel(self)
        dialog.title('Cài đặt — Kết nối API')
        dialog.transient(self.winfo_toplevel())
        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        base = tk.StringVar(master=dialog, value=self.base.get())
        key = tk.StringVar(master=dialog, value=self.key.get())
        for i,(label,var) in enumerate((('API Base URL',base),('X-API-Key',key))):
            ttk.Label(frame,text=label).grid(row=i,column=0,sticky='w',padx=(0,12),pady=8)
            ttk.Entry(frame,textvariable=var,width=52,show='*' if var is key else '').grid(row=i,column=1,sticky='ew',pady=8)
        def apply():
            if self.busy:
                return
            self.base.set(base.get().strip())
            self.key.set(key.get().strip())
            dialog.destroy()
        ttk.Button(frame,text='Lưu',command=apply).grid(row=2,column=1,sticky='e',pady=(12,0))

    def scan_subtitles(self):
        if self.busy:
            return
        if not self.scanned or not self.items:
            messagebox.showinfo('Phụ đề','Quét danh sách tập trước.')
            return
        selected = [int(i) for i in self.tree.selection()]
        if not selected and self.scanned_provider != 'netshort':
            selected = list(range(len(self.items)))
        if not selected:
            messagebox.showinfo('Phụ đề','Chọn các tập cần kiểm tra phụ đề, hoặc bấm Chọn tất cả.')
            return
        if self.scanned_provider != 'netshort':
            self.show_subtitle_choices({i: subtitle_tracks({'data':self.items[i]}) for i in selected})
            return
        base,lang,sid = self.scanned
        key = self.key.get()
        episodes = [(i,self.items[i]['id']) for i in selected]
        def job():
            api = API(base,key,lang,self.stop)
            result = {}
            for i,eid in episodes:
                if self.stop.is_set():
                    break
                self.emit('status',i,'Đang kiểm tra phụ đề…')
                try:
                    payload = api.get(f'/api/netshort/episodes/{sid}/{eid}/source')
                    found = subtitle_tracks(payload)
                    result[i] = found
                    self.emit('status',i,f'{len({t["language"] for t in found})} ngôn ngữ phụ đề')
                except ToolError as err:
                    result[i] = None
                    self.emit('status',i,'Chưa xác định được phụ đề')
                    self.emit('log',f'Tập {i+1}: {err}')
                    if 'HTTP 401' in str(err) or 'HTTP 429' in str(err):
                        break
            for i,_ in episodes:
                result.setdefault(i,None)
            self.emit('subtitles',result)
        self.launch(job)

    def show_subtitle_choices(self, results):
        from netshort_subtitles import coverage, language_name
        languages = coverage(results)
        total = len(results)
        failed = sum(value is None for value in results.values())
        dialog = tk.Toplevel(self)
        dialog.title('Chọn ngôn ngữ phụ đề SRT')
        dialog.transient(self.winfo_toplevel())
        dialog.geometry('550x570')
        frame = ttk.Frame(dialog,padding=18)
        frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=f'{len(languages)} ngôn ngữ • {total} tập được kiểm tra',font=('Segoe UI',14,'bold')).pack(anchor='w')
        note = f'{failed} tập chưa kiểm tra được.' if failed else 'Chỉ liệt kê ngôn ngữ API trả về.'
        ttk.Label(frame,text=note,wraplength=500).pack(anchor='w',pady=8)
        canvas = tk.Canvas(frame,highlightthickness=0,bg='#18212d')
        scroll = ttk.Scrollbar(frame,orient='vertical',command=canvas.yview)
        footer = ttk.Frame(frame)
        footer.pack(side='bottom',fill='x',pady=(12,0))
        scroll.pack(side='right',fill='y')
        canvas.pack(fill='both',expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        content = ttk.Frame(canvas,padding=8)
        window = canvas.create_window((0,0),window=content,anchor='nw')
        content.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        selections = []
        wanted = self.subtitle_language.get()
        for code,count in languages:
            var = tk.BooleanVar(master=dialog,value=language_matches(code,wanted))
            ttk.Checkbutton(content,text=f'{language_name(code)} ({code}) — {count}/{total} tập',variable=var).pack(anchor='w',pady=6)
            selections.append((code,var))
        if not languages:
            ttk.Label(content,text='Không có phụ đề riêng được xác nhận.',wraplength=430).pack(anchor='w')
        elif not any(code.startswith('vi') for code,_ in languages):
            ttk.Label(content,text='Không thấy tiếng Việt. Tool không tự chọn tiếng khác.',wraplength=430).pack(anchor='w',pady=8)
        details = []
        for code,_ in languages:
            if code.startswith('vi'):
                missing = [str(self.items[i].get('episodeNumber') or i+1) for i,entries in results.items()
                           if entries is not None and not any(language_matches(t['language'],'vi') for t in entries)]
                if missing:
                    details.append('Tập thiếu sub Việt: '+', '.join(missing))
        if details:
            ttk.Label(content,text='\n'.join(details),wraplength=430).pack(anchor='w',pady=8)
        def apply():
            chosen = [code for code,var in selections if var.get()]
            if not chosen:
                messagebox.showinfo('Chọn phụ đề','Chọn ít nhất một ngôn ngữ, hoặc đóng cửa sổ để giữ lựa chọn hiện tại.',parent=dialog)
                return
            self.subtitle_language.set(','.join(chosen))
            self.info.set('Phụ đề đã chọn: '+', '.join(language_name(code) for code in chosen))
            dialog.destroy()
        ttk.Button(footer,text='Chọn tất cả',command=lambda:[var.set(True) for _,var in selections]).pack(side='left')
        ttk.Button(footer,text='Áp dụng',command=apply).pack(side='right')

    def pick_folder(self):
        if not self.busy:
            path = filedialog.askdirectory()
            if path:
                self.folder.set(path)

    def emit(self, *event):
        self.events.put(event)

    def launch(self, job):
        if self.busy:
            return
        self.busy = True
        self.stop.clear()
        for widget in self.inputs + [self.scan_button, self.download_button, self.subtitles_button]:
            widget.configure(state='disabled')
        def run():
            try:
                job()
            except ToolError as e:
                self.emit('error', str(e))
            except Exception as e:
                # Do not log exception strings: network libraries can embed signed URLs or credentials.
                self.emit('error', f'Lỗi {type(e).__name__}; kiểm tra kết nối, quyền ghi và cấu trúc API.')
            finally:
                self.emit('idle')
        threading.Thread(target=run, daemon=True).start()

    def scan(self):
        if self.busy:
            return
        base, key, lang = self.base.get().strip(), self.key.get(), self.language.get().strip()
        value = self.sid.get().strip() or self.link.get().strip()
        self.source_provider = 'dramawave' if self.provider_choice.get() == 'DramaWave' else 'netshort'
        if self.fixed_provider:
            self.source_provider = self.fixed_provider
        if self.sid.get().strip() and not re.fullmatch(r'[A-Za-z0-9_-]{1,80}' if self.source_provider != 'netshort' else r'\d{1,25}', self.sid.get().strip()):
            messagebox.showerror('Series ID', 'Series ID thủ công phải là số.')
            return
        self.tree.delete(*self.tree.get_children())
        self.items, self.scanned = [], None
        self.scan_error = False
        self.subtitle_results = {}
        self.info.set('Đang resolve link và quét danh sách tập…')
        def job():
            api = API(base, key, lang, self.stop, self.source_provider)
            if self.source_provider == 'dramawave':
                from dramawave_tab import series_id
                sid = series_id(value)
                if not sid:
                    raise ToolError('Nhập ID bộ phim DramaWave hoặc link có ID rõ ràng.')
            elif self.source_provider in ('shortmax','dramabox'):
                from studio_providers import series_id as new_series_id
                sid=new_series_id(value,self.source_provider)
                if not sid:raise ToolError('Chưa đọc được ID từ link. Hãy tìm theo tên phim hoặc nhập ID bộ phim.')
            else:
                sid = resolve_series(value, self.stop)
            self.scanned_provider = self.source_provider
            self.emit('log', f'Series ID: {sid}')
            title, items = api.episodes(sid)
            self.emit('episodes', title, sid, items, (base, lang))
        self.launch(job)

    def start_download(self):
        selected = [int(i) for i in self.tree.selection()]
        if not selected or not self.scanned:
            messagebox.showinfo('Chọn tập', 'Quét và chọn ít nhất một tập trước.')
            return
        base, lang, sid = self.scanned
        if (self.base.get().strip(), self.language.get().strip()) != (base, lang):
            messagebox.showinfo('Quét lại', 'Base URL hoặc Language đã đổi. Hãy quét lại trước khi tải.')
            return
        key, folder = self.key.get(), self.folder.get().strip()
        mode = self.download_mode.get()
        sub_language = self.subtitle_language.get().strip() or 'all'
        if not folder:
            messagebox.showerror('Thư mục', 'Hãy chọn thư mục lưu.')
            return
        movie_name = safe_name(getattr(self, 'scanned_title', sid), sid)
        episodes = [(i, dict(self.items[i])) for i in selected]
        def job():
            api = API(base, key, lang, self.stop, self.scanned_provider)
            target = Path(folder).expanduser() / movie_name
            target.mkdir(parents=True, exist_ok=True)
            success, failed = 0, 0
            for i, ep in episodes:
                if self.stop.is_set():
                    break
                eid = ep['id']
                self.emit('status', i, 'Đang lấy Episode Source…')
                try:
                    payload = {'data': ep} if self.scanned_provider != 'netshort' else api.get(f'/api/netshort/episodes/{sid}/{eid}/source')
                    candidates = source_candidates(payload)
                    if not candidates and mode != 'Chỉ phụ đề':
                        raise ToolError('Không có source được cấp; bỏ qua.')
                    source = candidates[0] if candidates else None
                    self.emit('status', i, 'Đang tải…')
                    def progress(done, total):
                        self.emit('progress', 100 * done / total if total else 0)
                        if source and (source.get('type') in ('m3u8', 'hls') or '.m3u8' in source.get('url','')):
                            self.emit('status', i, f'HLS: {done}/{total} đoạn')
                            return
                        self.emit('status', i, f'{done / 1048576:.1f} MB' + (f' / {total / 1048576:.1f} MB' if total else ''))
                    stem = episode_stem(movie_name, ep, i)
                    if mode != 'Chỉ phụ đề':
                        video_path = target / (stem + '.mp4')
                        if video_path.exists():
                            self.emit('log', f'Tập {i+1}: MP4 đã có, giữ file hiện tại.')
                        else:
                            download(source, video_path, self.stop, progress)
                    sub_count = 0
                    if mode != 'Video':
                        available = subtitle_tracks(payload)
                        chosen = [t for t in available if language_matches(t['language'], sub_language)]
                        if not chosen:
                            langs = ', '.join(sorted({t['language'] for t in available})) or 'không có'
                            self.emit('log', f'Tập {i+1}: không có sub khớp {sub_language}. API cấp: {langs}.')
                        language_counts = {}
                        for track_index, track in enumerate(chosen, 1):
                            try:
                                with fetch(track['url'], stop=self.stop) as response:
                                    converted = as_srt(limited_read(response))
                                language_tag = re.sub(r'[^A-Za-z0-9_-]', '_', track['language'])[:30] or 'und'
                                language_counts[language_tag] = language_counts.get(language_tag, 0) + 1
                                duplicate = language_counts[language_tag]
                                suffix = '' if duplicate == 1 else f'.{duplicate}'
                                sub_path = target / f'{stem}.{language_tag}{suffix}.srt'
                                if not sub_path.exists():
                                    with sub_path.open('x', encoding='utf-8-sig') as output:
                                        output.write(converted)
                                sub_count += 1
                            except Cancelled:
                                raise
                            except Exception as err:
                                reason = str(err) if isinstance(err, (ToolError, ValueError)) else type(err).__name__
                                self.emit('log', f'Tập {i+1}: lỗi sub {track["language"]}: {reason}')
                        self.emit('log', f'Tập {i+1}: có {sub_count} file SRT trong thư mục tải.')
                    if mode == 'Chỉ phụ đề' and not sub_count:
                        raise ToolError('Không tải được phụ đề phù hợp; xem nhật ký.')
                    success += 1
                    self.emit('status', i, 'Đã tải')
                except Cancelled:
                    self.emit('status', i, 'Đã dừng')
                    break
                except Exception as e:
                    failed += 1
                    msg = str(e) if isinstance(e, ToolError) else f'Lỗi {type(e).__name__}; không tải xong.'
                    self.emit('status', i, msg)
                    self.emit('log', f'Tập {i + 1}: {msg}')
                    if isinstance(e, ToolError) and ('HTTP 401' in msg or 'HTTP 429' in msg):
                        break
            self.emit('log', f'Kết thúc: tải thành công {success}, lỗi/bỏ qua {failed}, chưa xử lý {len(episodes)-success-failed}. Thư mục: {target}')
        self.launch(job)

    def pump(self):
        for _ in range(200):
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break
            kind, *args = event
            if kind in ('log', 'error'):
                if kind == 'error':
                    reason = args[0]
                    if '523' in reason or 'Origin is unreachable' in reason:
                        reason = 'Không quét được: nguồn Bstation phía Ezvid không kết nối được (523). Chưa nhận được danh sách tập.'
                    self.info.set(reason)
                    self.scan_error = True
                self.log.configure(state='normal')
                self.log.insert('end', args[0] + '\n')
                self.log.see('end')
                self.log.configure(state='disabled')
            elif kind == 'idle':
                self.busy = False
                for widget in self.inputs + [self.scan_button, self.download_button, self.subtitles_button]:
                    widget.configure(state='normal')
                if not self.scanned and not getattr(self, 'scan_error', False):
                    self.info.set('Chưa có danh sách tập. Xem thông báo bên dưới.')
            elif kind == 'subtitles':
                self.subtitle_results.update(args[0])
                self.show_subtitle_choices(args[0])
            elif kind == 'episodes':
                title, sid, self.items, config = args
                self.scanned_title = title
                self.scanned = (*config, sid)
                if self.scanned_provider != 'netshort':
                    self.subtitle_results = {i: subtitle_tracks({'data':ep}) for i,ep in enumerate(self.items)}
                for i, ep in enumerate(self.items):
                    extra = ep.get('extra') or {}
                    self.tree.insert('', 'end', iid=str(i), values=(ep.get('episodeNumber') or ep.get('episodeNo') or i + 1,
                        ep.get('title') or f'Tập {i + 1}', ep['id'],
                        'Có' if extra.get('isLocked') or extra.get('isVip') else 'Không', 'Chưa lấy source'))
                self.info.set(f'{title} — Series ID: {sid} — API trả {len(self.items)} tập. Ctrl/Shift để chọn nhiều tập.')
                if self.scanned_provider != 'netshort':
                    from netshort_subtitles import coverage
                    languages = coverage(self.subtitle_results)
                    vi_count = sum(1 for entries in self.subtitle_results.values() if any(language_matches(t['language'],'vi') for t in entries))
                    self.info.set(f'{title} — {len(self.items)} tập • {len(languages)} ngôn ngữ sub • Tiếng Việt: {vi_count}/{len(self.items)} tập. Bấm Quét / Chọn ngôn ngữ SRT.')
            elif kind == 'status':
                self.tree.set(str(args[0]), 'status', args[1])
            elif kind == 'progress':
                self.progress['value'] = args[0]
        self.after(100, self.pump)

    def close(self):
        if self.busy:
            self.stop.set()
            self.info.set('Đang dừng an toàn… chờ yêu cầu mạng kết thúc (tối đa khoảng 25 giây).')
            self.after(150, self.close)
        else:
            self.destroy()


class App(AppLogic, tk.Tk):
    pass


class DownloadPanel(AppLogic, ttk.Frame):
    pass


if __name__ == '__main__':
    App().mainloop()
