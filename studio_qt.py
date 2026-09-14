from datetime import datetime
import time
"""Modern Qt presentation; networking and media logic stay in original modules."""
import io
import json
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QIcon
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, QPushButton,
    QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QFrame, QComboBox,
    QCheckBox, QProgressBar, QTextEdit, QStackedWidget, QListWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QDialog, QFormLayout, QDialogButtonBox)
from studio_backend import Backend, original_key
from studio_catalog import catalog_rows, next_cursor, load_poster, dramawave_rows
from netshort_tool import API, ToolError
from netshort_subtitles import coverage, language_name, language_matches
from studio_files import safe_name

STYLE = '''
QWidget {background:#0c121b; color:#edf3fa; font-family:"Segoe UI"; font-size:13px;}
QFrame#sidebar {background:#090f17; border-right:1px solid #202c3b;}
QFrame#inspector {background:#141e2b; border-left:1px solid #263243;}
QFrame#sidebar QLabel {background:transparent;}
QFrame#inspector QLabel, QWidget#panelContent {background:#141e2b;}
QFrame#inspector QLabel#poster {background:#192535;}
QLabel#brand {color:#47dcca; font-size:32px; font-weight:800;}
QLabel#heading {font-size:28px; font-weight:700;}
QLabel#movieTitle {font-size:23px; font-weight:700;}
QLabel#section {font-size:17px; font-weight:650;}
QLabel#muted {color:#93a4b9; font-size:12px;}
QLabel#accent {color:#47dcca; font-size:12px;}
QPushButton {background:#192535; border:1px solid #2a394b; border-radius:8px; padding:10px 13px;}
QPushButton:hover {background:#24374a; border-color:#47dcca;}
QPushButton:disabled {color:#617185; background:#17212d; border-color:#202d3c;}
QPushButton[primary="true"], QPushButton:checked {background:#47dcca; color:#0b1820; border-color:#47dcca; font-weight:700;}
QPushButton[primary="true"]:hover {background:#72eadb;}
QPushButton#nav {text-align:left; padding:13px; border:0; background:transparent; color:#9baec2;}
QPushButton#nav:checked {background:#15312f; color:#47dcca;}
QPushButton#episode {padding:8px 0; min-width:36px;}
QPushButton#link {background:transparent; border:0; color:#47dcca; padding:3px;}
QLineEdit, QComboBox {background:#141e2b; border:1px solid #2e4052; border-radius:8px; padding:11px; selection-background-color:#26776c;}
QLineEdit:focus {border-color:#47dcca;}
QComboBox QAbstractItemView {background:#192535; selection-background-color:#26776c;}
QCheckBox {spacing:10px; padding:4px 0; background:transparent;}
QCheckBox::indicator {width:19px; height:19px; border:1px solid #66768a; border-radius:5px; background:#172432;}
QCheckBox::indicator:checked {background:#47dcca; border-color:#47dcca; image:url(check.svg);}
QScrollArea {border:0; background:transparent;}
QScrollBar:vertical {background:transparent; width:7px; margin:0;}
QScrollBar::handle:vertical {background:#334558; border-radius:3px; min-height:24px;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical {height:0;}
QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical {background:transparent;}
QFrame#card {border:2px solid transparent; border-radius:10px;}
QFrame#card:hover {border-color:#314b5e;}
QFrame#card[selected="true"] {border-color:#47dcca;}
QLabel#poster {background:#192535; border-radius:8px; color:#6d8799;}
QProgressBar {background:#202d3d; border:0; border-radius:4px; height:7px; text-align:center;}
QProgressBar::chunk {background:#47dcca; border-radius:4px;}
QTextEdit,QTableWidget,QListWidget {background:#141e2b; border:1px solid #263749; border-radius:8px; padding:8px; selection-background-color:#225e59;}
QHeaderView::section {background:#192535; color:#93a4b9; border:0; padding:10px;}
'''


class Events(QObject):
    event = pyqtSignal(object)


def label(text='', name='', wrap=False):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def button(text, callback=None, primary=False, name=''):
    icons = {'▣':'library', '◷':'history', '⚙':'settings', '⌕':'search', '↓':'download'}
    icon_name = icons.get(text[:1])
    widget = QPushButton(text[1:].strip() if icon_name else text)
    if icon_name:widget.setIcon(QIcon(str(Path(__file__).parent/'icons'/(icon_name+'.svg'))))
    widget.setObjectName(name)
    widget.setProperty('primary', primary)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if callback: widget.clicked.connect(callback)
    return widget


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget(): item.widget().hide(); item.widget().deleteLater()


class Card(QFrame):
    clicked = pyqtSignal(object)
    def __init__(self, movie):
        super().__init__()
        self.movie = movie
        self.setObjectName('card')
        self.setFixedWidth(224)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6,6,6,8)
        layout.setSpacing(5)
        self.poster = label('BOOM\nminiapp', 'poster')
        self.poster.setFixedSize(208,286)
        self.poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.poster)
        title = label(movie['title'], wrap=True)
        title.setFixedHeight(38)
        title.setStyleSheet('font-weight:600;')
        layout.addWidget(title)
        layout.addWidget(label(f"{movie.get('total') or '—'} tập", 'muted'))
        self.setToolTip(movie['title'])

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self.clicked.emit(self.movie)
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self,account=None):
        super().__init__()
        self.setWindowTitle('BOOM miniapp')
        self.setWindowIcon(QIcon(str(Path(__file__).with_name('boom.svg'))))
        self.resize(1480,960)
        self.setMinimumSize(1160,780)
        self.setStyleSheet(STYLE.replace('url(check.svg)', 'url(' + Path(__file__).with_name('check.svg').as_posix() + ')'))
        self.events = Events()
        self.events.event.connect(self.on_event)
        self.backend = Backend(self.events.event.emit, original_key())
        self.account=account
        if account:
            self.backend.base.set(account['base'])
            self.backend.key.set(account['token'])
        self.provider = 'netshort'
        self.catalog_busy = False
        self.catalog_stop = threading.Event()
        self.generation = 0
        self.cursor = self.query_state = None
        self.cards = []
        self.current_movie = None
        self.auto_subtitles = False
        self.language_checks = {}
        self.episode_checks = {}
        self.closing = False
        self.art_generation = 0
        self.art_stop = threading.Event()
        self.history_path = Path(__file__).with_name('boom_history.json')
        try:
            value = json.loads(self.history_path.read_text(encoding='utf-8'))
            self.history = [x for x in value if isinstance(x,dict) and all(k in x for k in ('id','title','episodes'))] if isinstance(value,list) else []
        except (OSError,ValueError): self.history = []
        self._build()
        self.refresh_history()
        self.monitor=None
        if account:
            from boom_login import SessionMonitor
            self.monitor=SessionMonitor(self,account)
            self.monitor.lost.connect(self.session_lost)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0,0,0,0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(185)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(18,27,18,22)
        nav.addWidget(label('BOOM','brand'))
        nav.addWidget(label('m i n i a p p','muted'))
        nav.addSpacing(35)
        self.nav_buttons = []
        for index,text in enumerate(('▣  Thư viện','↓  Đang tải','◷  Lịch sử')):
            item = button(text,lambda _,i=index:self.show_page(i),name='nav')
            item.setCheckable(True)
            nav.addWidget(item)
            self.nav_buttons.append(item)
        nav.addStretch()
        nav.addWidget(label('NHÀ CUNG CẤP','muted'))
        self.provider_buttons = {}
        for code,title in (('netshort','NetShort'),('dramawave','DramaWave')):
            item = button(title,lambda _,p=code:self.switch_provider(p))
            item.setCheckable(True)
            item.setChecked(code==self.provider)
            nav.addWidget(item)
            self.provider_buttons[code] = item
        nav.addSpacing(22)
        self.settings_button = button('⚙  Cài đặt',self.settings,name='nav')
        nav.addWidget(self.settings_button)
        if self.account:
            card=QFrame()
            card.setStyleSheet('QFrame {background:#142630;border:1px solid #244650;border-radius:10px;} QLabel {border:0;background:transparent;}')
            details=QVBoxLayout(card);details.setContentsMargins(10,12,10,12)
            self.account_name=label(self.account['username'],'accent',True)
            details.addWidget(self.account_name)
            self.plan_label=label('','muted');details.addWidget(self.plan_label)
            self.remaining_label=label('','accent',True);details.addWidget(self.remaining_label)
            self.expiry_label=label('','muted',True);details.addWidget(self.expiry_label)
            self.clock_label=label('','muted',True);details.addWidget(self.clock_label)
            nav.addWidget(card)
            self.account_timer=QTimer(self);self.account_timer.timeout.connect(self.update_account_card)
            self.account_timer.start(1000);self.update_account_card()
            nav.addWidget(button('Đăng xuất',self.close,name='nav'))
        shell.addWidget(sidebar)
        self.pages = QStackedWidget()
        shell.addWidget(self.pages,1)
        library = QWidget()
        layout = QVBoxLayout(library)
        layout.setContentsMargins(26,26,24,18)
        layout.setSpacing(12)
        layout.addWidget(label('Thư viện phim','heading'))
        layout.addWidget(label('Chọn một bộ phim để bắt đầu','muted'))
        row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Tìm tên phim hoặc dán link…')
        self.search_input.returnPressed.connect(self.search)
        row.addWidget(self.search_input,1)
        row.addWidget(button('⌕  Tìm phim',self.search,True))
        layout.addLayout(row)
        filters = QHBoxLayout()
        filters.addWidget(button('Đề xuất',lambda:self.load_catalog('home')))
        filters.addWidget(button('Thịnh hành',lambda:self.load_catalog('trending')))
        self.more = button('Xem thêm',self.load_more)
        self.more.setEnabled(False)
        filters.addWidget(self.more)
        filters.addStretch()
        filters.addWidget(button('Dừng quét',self.catalog_stop.set,name='link'))
        layout.addLayout(filters)
        self.library_info = label('Bấm Đề xuất hoặc tìm phim để mở thư viện.','muted',True)
        layout.addWidget(self.library_info)
        self.poster_scroll = QScrollArea()
        self.poster_scroll.setWidgetResizable(True)
        self.poster_content = QWidget()
        self.poster_grid = QGridLayout(self.poster_content)
        self.poster_grid.setAlignment(Qt.AlignmentFlag.AlignTop|Qt.AlignmentFlag.AlignLeft)
        self.poster_grid.setContentsMargins(0,0,0,0)
        self.poster_grid.setSpacing(14)
        self.empty = label('THƯ VIỆN CỦA BẠN\n\nPoster phim sẽ xuất hiện tại đây.','muted')
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setMinimumHeight(300)
        self.poster_grid.addWidget(self.empty,0,0)
        self.poster_scroll.setWidget(self.poster_content)
        layout.addWidget(self.poster_scroll,1)
        self.pages.addWidget(library)

        downloads = QWidget()
        dl = QVBoxLayout(downloads)
        dl.setContentsMargins(26,26,24,22)
        dl.addWidget(label('Tiến trình tải','heading'))
        self.download_info = label('Trạng thái từng tập và nhật ký xử lý.','muted',True)
        dl.addWidget(self.download_info)
        self.table = QTableWidget(0,2)
        self.table.setHorizontalHeaderLabels(['Tập','Trạng thái'])
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        dl.addWidget(self.table,1)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(200)
        dl.addWidget(self.log)
        self.pages.addWidget(downloads)
        history = QWidget()
        hl = QVBoxLayout(history)
        hl.setContentsMargins(26,26,24,22)
        hl.addWidget(label('Lịch sử tải','heading'))
        hl.addWidget(label('Nhấp đôi để mở lại bộ phim.','muted'))
        self.history_list = QListWidget()
        self.history_list.itemDoubleClicked.connect(self.open_history)
        hl.addWidget(self.history_list)
        self.pages.addWidget(history)
        self.show_page(0)

        inspector = QFrame()
        inspector.setObjectName('inspector')
        inspector.setFixedWidth(405)
        il = QVBoxLayout(inspector)
        il.setContentsMargins(22,26,22,20)
        il.setSpacing(10)
        summary = QHBoxLayout()
        self.mini_poster = label('B','poster')
        self.mini_poster.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mini_poster.setFixedSize(72,98)
        summary.addWidget(self.mini_poster)
        titles = QVBoxLayout()
        self.movie_title = label('Chọn một bộ phim','movieTitle',True)
        self.movie_title.setMaximumHeight(85)
        self.movie_meta = label('Mở poster hoặc dán link','muted',True)
        titles.addWidget(self.movie_title)
        titles.addWidget(self.movie_meta)
        summary.addLayout(titles,1)
        il.addLayout(summary)
        self.description = label('Thư viện, chọn tập và tải về trong một nơi.','muted',True)
        self.description.setMaximumHeight(52)
        il.addWidget(self.description)
        il.addSpacing(8)
        episode_head = QHBoxLayout()
        episode_head.addWidget(label('Chọn tập','section'),1)
        episode_head.addWidget(button('Tất cả',self.select_all,name='link'))
        episode_head.addWidget(button('Bỏ chọn',self.clear_selection,name='link'))
        il.addLayout(episode_head)
        self.selection_info = label('Đã chọn 0 / 0 tập','muted')
        il.addWidget(self.selection_info)
        self.episode_scroll = QScrollArea()
        self.episode_scroll.setWidgetResizable(True)
        self.episode_scroll.setMinimumHeight(90)
        episode_content = QWidget()
        episode_content.setObjectName('panelContent')
        self.episode_grid = QGridLayout(episode_content)
        self.episode_grid.setContentsMargins(0,0,5,0)
        self.episode_grid.setSpacing(7)
        self.episode_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.episode_scroll.setWidget(episode_content)
        il.addWidget(self.episode_scroll,1)
        sub_head = QHBoxLayout()
        sub_head.addWidget(label('Phụ đề','section'),1)
        self.rescan_button = button('Quét lại',self.scan_subtitles,name='link')
        sub_head.addWidget(self.rescan_button)
        il.addLayout(sub_head)
        self.sub_note = label('Tự quét ngôn ngữ khi mở phim','muted',True)
        il.addWidget(self.sub_note)
        sub_scroll = QScrollArea()
        sub_scroll.setWidgetResizable(True)
        sub_scroll.setFixedHeight(110)
        sub_content = QWidget()
        sub_content.setObjectName('panelContent')
        self.sub_layout = QVBoxLayout(sub_content)
        self.sub_layout.setContentsMargins(0,0,0,0)
        self.sub_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.sub_layout.setSpacing(1)
        sub_scroll.setWidget(sub_content)
        il.addWidget(sub_scroll)
        self.with_subtitles = QCheckBox('Tải kèm phụ đề SRT')
        self.with_subtitles.setChecked(True)
        self.with_subtitles.toggled.connect(self.subtitle_option_changed)
        il.addWidget(self.with_subtitles)
        il.addWidget(label('Video luôn được tải cùng các tập đã chọn.','muted',True))
        concurrency=QHBoxLayout()
        concurrency.addWidget(label('Số tập tải cùng lúc'),1)
        self.worker_count=QComboBox()
        self.worker_count.addItems(['3','5','10'])
        self.worker_count.setToolTip('Số tập tải song song. Mặc định 3 tập.')
        concurrency.addWidget(self.worker_count)
        il.addLayout(concurrency)
        folder_row = QHBoxLayout()
        folder_row.addWidget(label('Thư mục lưu'),1)
        self.folder_button = button('Đổi thư mục',self.pick_folder,name='link')
        folder_row.addWidget(self.folder_button)
        il.addLayout(folder_row)
        self.folder_label = label('','muted',True)
        self.folder_label.setMaximumHeight(50)
        il.addWidget(self.folder_label)
        self.download_button = button('↓  Tải tập đã chọn',self.start_download,True)
        self.download_button.setMinimumHeight(48)
        il.addWidget(self.download_button)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0,100)
        self.progress.setValue(0)
        il.addWidget(self.progress)
        bottom = QHBoxLayout()
        self.status = label('●  Sẵn sàng','accent')
        bottom.addWidget(self.status,1)
        bottom.addWidget(button('Dừng',self.stop_work,name='link'))
        il.addLayout(bottom)
        shell.addWidget(inspector)
        self.update_path()

    def update_account_card(self):
        self.clock_label.setText(datetime.now().strftime('%H:%M:%S  •  %d/%m/%Y'))
        self.plan_label.setText('VIP' if self.account.get('plan')=='vip' else 'TEST')
        expiry=self.account.get('expiry')
        if not isinstance(expiry,(int,float)):
            self.remaining_label.setText('Chưa có hạn sử dụng');return
        seconds=max(0,int(expiry-time.time()))
        days,rest=divmod(seconds,86400);hours,rest=divmod(rest,3600);minutes,secs=divmod(rest,60)
        self.remaining_label.setText(f'Còn {days} ngày\n{hours:02d}:{minutes:02d}:{secs:02d}' if seconds else 'Đã hết hạn')
        self.remaining_label.setStyleSheet('color:#47dcca;font-weight:bold;font-size:15px;' if seconds>=86400 else 'color:#ffc477;font-weight:bold;font-size:15px;')
        self.expiry_label.setText('Hết hạn: '+datetime.fromtimestamp(expiry).strftime('%d/%m/%Y %H:%M'))

    def show_page(self,index):
        self.pages.setCurrentIndex(index)
        for i,item in enumerate(self.nav_buttons):item.setChecked(i==index)

    def note(self,text):
        self.status.setText(text)
        self.log.append(text)

    def update_path(self):
        name = self.backend.scanned_title or (self.current_movie or {}).get('title','Tên phim')
        path = str(Path(self.backend.folder.get())/safe_name(name))
        self.folder_label.setText(path)
        self.folder_label.setToolTip(path)

    def pick_folder(self):
        if self.backend.busy:return
        folder = QFileDialog.getExistingDirectory(self,'Chọn thư mục lưu',self.backend.folder.get())
        if folder:self.backend.folder.set(folder); self.update_path()

    def settings(self):
        if self.backend.busy or self.catalog_busy:
            self.note('Chờ tác vụ hiện tại hoàn tất trước khi đổi cài đặt.'); return
        dialog = QDialog(self)
        dialog.setWindowTitle('BOOM miniapp • Cài đặt')
        dialog.resize(570,260)
        form = QFormLayout(dialog)
        lang = QLineEdit(self.backend.language.get())
        form.addRow('Tài khoản',label((self.account or {}).get('username','Chưa đăng nhập')))
        form.addRow('Ngôn ngữ nội dung',lang)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec():
            self.backend.language.set(lang.text().strip())

    def switch_provider(self,provider):
        if self.backend.busy or self.catalog_busy:
            self.note('Dừng hoặc chờ tác vụ hiện tại hoàn tất trước khi đổi nguồn.')
            for code,item in self.provider_buttons.items():item.setChecked(code==self.provider)
            return
        self.art_generation += 1
        self.art_stop.set()
        self.provider=provider
        self.backend.fixed_provider=provider
        self.backend.provider_choice.set('NetShort' if provider=='netshort' else 'DramaWave')
        self.backend.language.set('vi_VN' if provider=='netshort' else 'vi-VN')
        self.backend.scanned=None; self.backend.items=[]; self.backend.scanned_title=''
        self.current_movie=None
        self.cursor=None
        self.query_state=None
        self.generation+=1
        self.clear_cards()
        self.render_episodes()
        self.render_subtitles({})
        self.movie_title.setText('Chọn một bộ phim')
        self.movie_meta.setText(self.backend.provider_choice.get())
        self.mini_poster.clear(); self.mini_poster.setText('B')
        self.more.setEnabled(False)
        for code,item in self.provider_buttons.items():item.setChecked(code==provider)
        self.library_info.setText('Đã chọn '+self.backend.provider_choice.get()+'. Bấm Đề xuất hoặc tìm phim.')
        self.update_path(); self.show_page(0)

    def search(self):
        value=self.search_input.text().strip()
        from dramawave_tab import series_id
        if 'http://' in value or 'https://' in value or value.isdigit() or (self.provider=='dramawave' and series_id(value) and any(c.isdigit() for c in value)):
            self.open_movie({'id':'','title':'Phim từ link','link':value})
        else:self.load_catalog('search' if value else 'home',value)

    def clear_cards(self):
        clear_layout(self.poster_grid)
        self.cards=[]

    def load_more(self):
        if self.cursor and self.query_state:self.load_catalog(*self.query_state,cursor=self.cursor)

    def load_catalog(self,action,query='',cursor=None):
        if self.catalog_busy or self.backend.busy:
            self.library_info.setText('Đang xử lý yêu cầu trước.'); return
        self.catalog_busy=True
        self.catalog_stop.clear()
        self.more.setEnabled(False)
        if not cursor:self.generation+=1; self.clear_cards(); self.cursor=None
        generation=self.generation
        self.query_state=(action,query)
        provider=self.provider
        settings=self.backend.base.get(),self.backend.key.get(),self.backend.language.get()
        self.library_info.setText('Đang lấy danh sách phim…')
        def work():
            try:
                api=API(*settings,self.catalog_stop)
                params={'limit':30}
                if query:params['q']=query
                if cursor:params['cursor']=cursor
                endpoint=action if provider=='netshort' else ('search' if action=='search' else 'search/hot-list')
                payload=api.get('/api/'+provider+'/'+endpoint,params)
                if provider=='netshort':rows=catalog_rows(payload)
                else:rows=dramawave_rows(payload)
                nxt=next_cursor(payload)
                self.events.event.emit(('catalog',generation,rows,nxt if nxt!=cursor else None))
                groups={}
                for movie in rows:
                    url=movie.get('poster')
                    if isinstance(url,str) and url.startswith('https://'):groups.setdefault(url,[]).append(movie['id'])
                with ThreadPoolExecutor(max_workers=6) as pool:
                    jobs={pool.submit(load_poster,url,self.catalog_stop,Path(__file__).with_name('poster_cache')):ids for url,ids in groups.items()}
                    for job in as_completed(jobs):
                        if self.catalog_stop.is_set():break
                        try:
                            image=job.result()
                            if image is not None:
                                data=io.BytesIO(); image.save(data,format='PNG')
                                self.events.event.emit(('poster',generation,jobs[job],data.getvalue()))
                        except Exception as error:
                            self.events.event.emit(('poster_error',generation,jobs[job],type(error).__name__))
            except Exception as error:
                self.events.event.emit(('catalog_error',generation,str(error) if isinstance(error,ToolError) else type(error).__name__))
            finally:self.events.event.emit(('catalog_idle',generation))
        threading.Thread(target=work,daemon=True).start()

    def relayout_cards(self):
        columns=max(1,min(3,self.poster_scroll.viewport().width()//238))
        for i,card in enumerate(self.cards):self.poster_grid.addWidget(card,i//columns,i%columns)

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self,'poster_scroll'):QTimer.singleShot(0,self.relayout_cards)

    def open_movie(self,movie):
        if self.backend.busy:self.note('Chờ hoặc dừng tác vụ hiện tại trước khi đổi phim.'); return
        self.art_generation += 1
        self.art_stop.set()
        self.art_stop = threading.Event()
        self.current_movie=dict(movie)
        self.backend.scanned_title=''
        self.movie_title.setText(movie['title'])
        self.movie_title.setToolTip(movie['title'])
        self.movie_title.setStyleSheet('font-size:17px;font-weight:700;' if len(movie['title'])>45 else 'font-size:23px;font-weight:700;')
        self.movie_meta.setText('Đang quét danh sách tập…')
        self.description.setText(str(movie.get('description') or ''))
        self.backend.sid.set(''); self.backend.link.set(movie.get('link') or movie['id'])
        self.backend.subtitle_language.set('')
        self.auto_subtitles=False
        self.mini_poster.clear(); self.mini_poster.setText('B')
        for card in self.cards:
            selected=card.movie['id']==movie['id']
            card.setProperty('selected',selected)
            card.style().unpolish(card); card.style().polish(card)
            if selected and card.poster.pixmap() and not card.poster.pixmap().isNull():
                self.mini_poster.setPixmap(card.poster.pixmap().scaled(72,98,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        self.backend.scan()
        self.render_episodes(); self.render_subtitles({})
        self.sub_note.setText('Đang chờ danh sách tập…')
        self.update_path(); self.set_busy(True)

    def render_episodes(self):
        clear_layout(self.episode_grid)
        self.episode_checks={}
        self.table.setRowCount(len(self.backend.items))
        for i,ep in enumerate(self.backend.items):
            number=ep.get('episodeNumber') or ep.get('episodeNo') or i+1
            item=button(str(number).zfill(2),lambda:self.selection_changed(),name='episode')
            item.setCheckable(True)
            item.setChecked(True)
            self.episode_grid.addWidget(item,i//6,i%6)
            self.episode_checks[i]=item
            self.table.setItem(i,0,QTableWidgetItem(str(number)))
            self.table.setItem(i,1,QTableWidgetItem('Sẵn sàng'))
        self.selection_changed()

    def selection_changed(self):
        self.backend.tree.selected=[i for i,check in self.episode_checks.items() if check.isChecked()]
        count=len(self.backend.tree.selected)
        self.selection_info.setText(f'Đã chọn {count} / {len(self.backend.items)} tập')
        self.download_button.setText(f'Tải {count} tập đã chọn')

    def select_all(self):
        if self.backend.busy:return
        for item in self.episode_checks.values():item.setChecked(True)
        self.selection_changed()

    def clear_selection(self):
        if self.backend.busy:return
        for item in self.episode_checks.values():item.setChecked(False)
        self.selection_changed()

    def scan_subtitles(self):
        if self.backend.busy:return
        if not self.backend.scanned or not self.backend.tree.selected:self.note('Chọn tập trước khi quét phụ đề.'); return
        self.sub_note.setText('Đang quét ngôn ngữ có thật…')
        self.backend.scan_subtitles()
        self.set_busy(self.backend.busy)

    def render_subtitles(self,results):
        clear_layout(self.sub_layout)
        self.language_checks={}
        wanted=self.backend.subtitle_language.get() or 'vi'
        languages=coverage(results)
        for code,count in languages:
            item=QCheckBox(f'{language_name(code)}  ·  {count}/{len(results)} tập')
            item.setToolTip(code)
            item.setChecked(language_matches(code,wanted))
            item.stateChanged.connect(self.commit_languages)
            self.language_checks[code]=item
            self.sub_layout.addWidget(item)
        failed=sum(x is None for x in results.values())
        self.sub_note.setText(f'Đã quét {len(results)} tập • {len(languages)} ngôn ngữ' + (f' • {failed} tập chưa rõ' if failed else ''))
        if not languages:self.sub_layout.addWidget(label('Chưa thấy phụ đề riêng.\nBỏ tick tải kèm SRT để tải video.','muted',True))
        self.commit_languages()

    def commit_languages(self):
        self.backend.subtitle_language.set(','.join(code for code,item in self.language_checks.items() if item.isChecked()))

    def subtitle_option_changed(self):
        enabled = self.with_subtitles.isChecked() and not self.backend.busy
        for item in self.language_checks.values():item.setEnabled(enabled)

    def set_busy(self,busy):
        for widget in [self.download_button,self.rescan_button,self.settings_button,self.folder_button,self.with_subtitles,self.worker_count,*self.episode_checks.values()]:widget.setEnabled(not busy)
        self.subtitle_option_changed()
        self.status.setText('●  Đang xử lý…' if busy else '●  Sẵn sàng')

    def start_download(self):
        b=self.backend
        if b.busy:return
        if not b.scanned or not b.tree.selected:self.note('Chọn ít nhất một tập để tải.'); return
        if (b.base.get().strip(),b.language.get().strip())!=b.scanned[:2]:self.note('Cài đặt đã đổi. Hãy mở lại phim để quét lại.'); return
        b.download_mode.set('Video + phụ đề' if self.with_subtitles.isChecked() else 'Video')
        if self.with_subtitles.isChecked() and not b.subtitle_language.get():self.note('Chọn ngôn ngữ phụ đề hoặc bỏ tick Tải kèm phụ đề SRT.'); return
        if not b.folder.get().strip():self.note('Chọn thư mục lưu trước.'); return
        self.progress.setValue(0)
        b.download_workers.set(int(self.worker_count.currentText()))
        b.start_download()
        self.set_busy(b.busy)
        self.show_page(1)

    def stop_work(self):
        self.auto_subtitles=False
        self.backend.stop.set()
        self.note('Đang yêu cầu dừng an toàn…' if self.backend.busy else '●  Sẵn sàng')

    def on_event(self,event):
        kind,*args=event
        b=self.backend
        if kind=='movie_art':
            token,sid,data,metadata=args
            if token!=self.art_generation or not self.current_movie or self.current_movie['id']!=sid:return
            self.current_movie.update(metadata)
            self.description.setText(str(metadata.get('description') or self.description.text()))
            pixmap=QPixmap();pixmap.loadFromData(data)
            if not pixmap.isNull():
                self.mini_poster.setPixmap(pixmap.scaled(72,98,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
                for card in self.cards:
                    if card.movie['id']==sid:
                        card.movie.update(metadata)
                        card.poster.setPixmap(pixmap.scaled(208,286,Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation))
            return
        if kind.startswith('catalog') or kind in ('poster','poster_error'):
            if args[0]!=self.generation:return
            if kind=='catalog':
                _,rows,self.cursor=args
                seen={card.movie['id'] for card in self.cards}
                for movie in rows:
                    if movie['id'] in seen:continue
                    card=Card(movie); card.clicked.connect(self.open_movie)
                    self.cards.append(card); seen.add(movie['id'])
                self.relayout_cards()
                self.library_info.setText(f'{len(self.cards)} phim • Bấm poster để chọn tập' if self.cards else 'Không có kết quả phù hợp. Thử tên khác hoặc dán link.')
            elif kind=='poster':
                _,ids,data=args
                pixmap=QPixmap(); pixmap.loadFromData(data)
                for card in self.cards:
                    if card.movie['id'] in ids:
                        card.poster.setPixmap(pixmap.scaled(208,286,Qt.AspectRatioMode.KeepAspectRatioByExpanding,Qt.TransformationMode.SmoothTransformation))
                        if self.current_movie and self.current_movie['id']==card.movie['id']:self.mini_poster.setPixmap(pixmap.scaled(72,98,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            elif kind=='poster_error':
                _,ids,reason=args
                for card in self.cards:
                    if card.movie['id'] in ids:
                        card.poster.setText('Chưa tải được ảnh\nBấm Đề xuất để thử lại')
                        card.poster.setToolTip('Lỗi tải poster: '+reason)
                self.log.append('Một số poster tải thất bại ('+reason+'). Có thể tải lại thư viện.')
            elif kind=='catalog_error':self.library_info.setText(args[1])
            elif kind=='catalog_idle':self.catalog_busy=False; self.more.setEnabled(bool(self.cursor))
            return
        if kind=='episodes':
            title,sid,items,config=args
            if title==sid and self.current_movie and self.current_movie['title']!='Phim từ link':title=self.current_movie['title']
            b.items=items; b.scanned=(*config,sid); b.scanned_title=title
            self.current_movie.update(id=sid,title=title)
            self.movie_title.setText(title)
            self.movie_title.setToolTip(title)
            self.movie_title.setStyleSheet('font-size:17px;font-weight:700;' if len(title)>45 else 'font-size:23px;font-weight:700;')
            self.movie_meta.setText(f'{len(items)} tập • {b.provider_choice.get()}')
            self.render_episodes(); self.update_path()
            self.ensure_movie_card()
            self.auto_subtitles=not b.stop.is_set()
        elif kind=='subtitles':
            b.subtitle_results.update(args[0]); self.render_subtitles(args[0])
        elif kind=='idle':
            b.busy=False; self.set_busy(False)
            if self.auto_subtitles:
                self.auto_subtitles=False
                self.scan_subtitles()
            if self.closing:QTimer.singleShot(100,self.close)
        elif kind=='status':
            index,state=args
            if 0<=index<self.table.rowCount():self.table.setItem(index,1,QTableWidgetItem(state))
            if state=='Đã tải':self.record_history(index)
        elif kind=='progress':self.progress.setValue(int(args[0]))
        elif kind=='batch':
            done,total,active,failed=args
            self.download_info.setText(f'Đã tải {done}/{total} tập • Đang xử lý {active} • Lỗi {failed}')
        elif kind in ('log','error'):
            self.log.append(args[0])
            self.download_info.setText(args[0])
            if kind=='error':self.movie_meta.setText(args[0]); self.auto_subtitles=False; self.sub_note.setText('Chưa quét được. Xem nhật ký trong Đang tải.')

    def record_history(self,index):
        b=self.backend
        if not b.scanned:return
        sid=b.scanned[2]
        item=next((x for x in self.history if x['id']==sid and x.get('provider','netshort')==self.provider),None)
        if item:self.history.remove(item)
        else:item={'id':sid,'title':b.scanned_title,'provider':self.provider,'episodes':[]}
        eid=b.items[index]['id']
        if eid not in item['episodes']:item['episodes'].append(eid)
        self.history.insert(0,item); self.history=self.history[:100]
        try:
            temp=self.history_path.with_suffix('.tmp'); temp.write_text(json.dumps(self.history,ensure_ascii=False),encoding='utf-8'); temp.replace(self.history_path)
        except OSError:self.log.append('Không lưu được lịch sử vào thư mục ứng dụng.')
        self.refresh_history()

    def refresh_history(self):
        self.history_list.clear()
        for item in self.history:self.history_list.addItem(f"{item['title']}   ·   {len(item['episodes'])} tập   ·   {item.get('provider','netshort')}")

    def open_history(self,item):
        if self.backend.busy or self.catalog_busy:return
        movie=self.history[self.history_list.row(item)]
        provider=movie.get('provider','netshort')
        if provider!=self.provider:self.switch_provider(provider)
        self.open_movie(movie); self.show_page(0)

    def closeEvent(self,event):
        self.auto_subtitles=False
        self.art_stop.set()
        self.catalog_stop.set(); self.backend.stop.set()
        if self.backend.busy or self.catalog_busy:
            self.closing=True; self.status.setText('Đang dừng an toàn…'); event.ignore(); QTimer.singleShot(250,self.close)
        else:
            if self.monitor:self.monitor.logout()
            event.accept()

    def session_lost(self,reason):
        from PyQt6.QtWidgets import QMessageBox
        self.auto_subtitles=False
        self.backend.stop.set();self.catalog_stop.set();self.art_stop.set()
        self.backend.key.set('')
        self.centralWidget().setEnabled(False)
        self.status.setText('Phiên đã kết thúc')
        QMessageBox.information(self,'BOOM miniapp',reason+'\nĐóng ứng dụng rồi mở lại để đăng nhập.')

    def ensure_movie_card(self):
        """Direct share links also deserve a library card and a cover."""
        movie=dict(self.current_movie,total=len(self.backend.items))
        existing=next((card for card in self.cards if card.movie['id']==movie['id']),None)
        if existing is None:
            if not self.cards:clear_layout(self.poster_grid)
            existing=Card(movie);existing.clicked.connect(self.open_movie)
            self.cards.append(existing);self.relayout_cards()
            self.library_info.setText('Đã mở phim từ link • Bấm poster để mở lại')
        if existing.poster.pixmap() and not existing.poster.pixmap().isNull():return
        token=self.art_generation
        stop=self.art_stop
        provider=self.provider
        settings=self.backend.base.get(),self.backend.key.get(),self.backend.language.get()
        def work():
            metadata=dict(movie)
            url=movie.get('poster')
            if not url and not stop.is_set():
                try:
                    api=API(*settings,stop)
                    payload=(api.get('/api/dramawave/detail/'+movie['id']) if provider=='dramawave'
                             else api.get('/api/netshort/search',{'q':movie['title']}))
                    rows=dramawave_rows(payload) if provider=='dramawave' else catalog_rows(payload)
                    match=next((r for r in rows if r['id']==movie['id']),None)
                    if match:metadata.update(match);url=match.get('poster')
                except Exception:
                    if not stop.is_set():self.events.event.emit(('log','Chưa lấy được poster phim. Kiểm tra server đã cập nhật API chi tiết phim.'))
            if not url or stop.is_set():return
            try:
                image=load_poster(url,stop,Path(__file__).with_name('poster_cache'))
                if image is not None:
                    data=io.BytesIO();image.save(data,format='PNG')
                    metadata['poster']=url
                    self.events.event.emit(('movie_art',token,movie['id'],data.getvalue(),metadata))
            except Exception:pass
        threading.Thread(target=work,daemon=True).start()
