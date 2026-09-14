"""Headless adapters reuse the original AppLogic scan/download operations."""
import threading
from pathlib import Path
from netshort_tool import AppLogic


class Value:
    def __init__(self, value=''): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class Selection:
    def __init__(self): self.selected = []
    def selection(self): return tuple(str(i) for i in self.selected)
    def get_children(self): return ()
    def delete(self, *args): self.selected = []


class Backend(AppLogic):
    def __init__(self, callback, key):
        self.callback = callback
        self.stop = threading.Event()
        self.busy = False
        self.items, self.scanned = [], None
        self.scanned_title = ''
        self.source_provider = self.scanned_provider = self.fixed_provider = 'netshort'
        self.base = Value('http://163.61.182.119:8000')
        self.key = Value(key)
        self.language = Value('vi_VN')
        self.provider_choice = Value('NetShort')
        self.folder = Value(str(Path.home()/'Downloads'/'BOOM miniapp'))
        self.sid, self.link, self.info = Value(), Value(), Value()
        self.download_mode, self.subtitle_language = Value('Video + phụ đề'), Value('')
        self.subtitle_results = {}
        self.download_workers = Value(3)
        self.tree = Selection()

    def start_download(self):
        from parallel_downloads import start
        start(self)

    def emit(self, *event): self.callback(event)

    def launch(self, job):
        if self.busy: return
        self.busy = True
        self.stop.clear()
        def run():
            from netshort_tool import ToolError
            try: job()
            except Exception as error:
                self.emit('error', str(error) if isinstance(error, ToolError) else f'Lỗi {type(error).__name__}; kiểm tra kết nối hoặc quyền ghi.')
            finally: self.emit('idle')
        threading.Thread(target=run, daemon=True).start()

    def show_subtitle_choices(self, results): self.emit('subtitles', results)


def original_key():
    return ''  # No upstream credential belongs in the client.
