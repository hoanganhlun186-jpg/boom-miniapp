"""Qt login and heartbeat, Windows-encrypted remembered credentials."""
import socket
import threading
from PyQt6.QtCore import QObject, pyqtSignal, QTimer
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QFormLayout,QLineEdit,QLabel,QPushButton,QCheckBox,QMessageBox
import login_store
from gateway_client import SERVER_URL,request_json


class Result(QObject):
    ready=pyqtSignal(object)


class LoginDialog(QDialog):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setWindowTitle('BOOM miniapp • Đăng nhập')
        self.resize(420,290)
        self.setStyleSheet('QWidget{background:#141e2b;color:#edf3fa;font:14px "Segoe UI";} QLineEdit{padding:10px;border:1px solid #405365;border-radius:7px;} QPushButton{padding:12px;background:#47dcca;color:#0c121b;border-radius:8px;font-weight:bold;}')
        layout=QVBoxLayout(self)
        heading=QLabel('BOOM miniapp');heading.setStyleSheet('font-size:28px;font-weight:bold;color:#47dcca;');layout.addWidget(heading)
        form=QFormLayout()
        self.username=QLineEdit();self.password=QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('Tài khoản',self.username);form.addRow('Mật khẩu',self.password)
        layout.addLayout(form)
        self.remember=QCheckBox('Ghi nhớ tài khoản và mật khẩu trên máy này')
        self.remember.setChecked(True);layout.addWidget(self.remember)
        saved=login_store.load()
        self.username.setText(saved.get('username',''));self.password.setText(saved.get('password',''))
        self.remember.toggled.connect(self.remember_changed)
        self.info=QLabel('Dùng tài khoản BOOM miniapp do quản trị cấp.');self.info.setWordWrap(True);layout.addWidget(self.info)
        self.submit=QPushButton('Đăng nhập');self.submit.clicked.connect(self.login);layout.addWidget(self.submit)
        self.password.returnPressed.connect(self.login)
        self.signals=Result();self.signals.ready.connect(self.finish)
        self.account=None;self.busy=False

    def remember_changed(self,checked):
        if not checked:
            try:login_store.clear()
            except OSError:self.info.setText('Không xóa được thông tin đã lưu trên máy.')

    def login(self):
        if self.busy:return
        base=SERVER_URL;username=self.username.text().strip();password=self.password.text()
        if not username or not password:self.info.setText('Nhập tài khoản và mật khẩu.');return
        self.busy=True;self.submit.setEnabled(False);self.info.setText('Đang đăng nhập…')
        self.pending_credentials=(username,password)
        self.username.setEnabled(False);self.password.setEnabled(False)
        def work():
            try:
                result=request_json(base,'/api/boommini/login',body={'username':username,'password':password,'device':socket.gethostname()[:100]})
                self.signals.ready.emit((base,result,None))
            except Exception as error:self.signals.ready.emit((base,None,str(error)))
        threading.Thread(target=work,daemon=True).start()

    def finish(self,result):
        base,account,error=result
        self.busy=False;self.submit.setEnabled(True)
        self.username.setEnabled(True);self.password.setEnabled(True)
        if error:self.info.setText(error);return
        if not account.get('token'):self.info.setText('Chưa đăng nhập được. Vui lòng thử lại.');return
        try:
            if self.remember.isChecked():login_store.save(*self.pending_credentials)
            else:login_store.clear()
        except OSError:
            QMessageBox.information(self,'Ghi nhớ đăng nhập','Đã đăng nhập, nhưng Windows chưa cho phép lưu thông tin trên máy này. Lần sau bạn cần nhập lại.')
        self.pending_credentials=None
        self.account=dict(account,base=base);self.password.clear();self.accept()

    def reject(self):
        if not self.busy:super().reject()


class SessionMonitor(QObject):
    lost=pyqtSignal(str)
    result=pyqtSignal(object)
    def __init__(self,window,account):
        super().__init__(window)
        self.window=window;self.account=account;self.busy=False;self.stopped=False
        self.timer=QTimer(self);self.timer.setInterval(25000);self.timer.timeout.connect(self.ping)
        self.result.connect(self.finish);self.timer.start();self.ping()

    def ping(self):
        if self.busy or self.stopped:return
        self.busy=True
        action=('Đang xử lý: '+self.window.movie_title.text()) if self.window.backend.busy else 'Sẵn sàng'
        account=dict(self.account)
        def work():
            try:
                response=request_json(account['base'],'/api/boommini/heartbeat',account['token'],{'action':action[:160]});self.result.emit(response)
            except Exception as error:self.result.emit(str(error))
        threading.Thread(target=work,daemon=True).start()

    def finish(self,error):
        self.busy=False
        if self.stopped:return
        if isinstance(error,dict):
            for key in ('expiry','plan'):
                if key in error:self.account[key]=error[key]
            self.window.update_account_card();return
        if error and ('HTTP 401' in error or 'HTTP 403' in error):
            self.timer.stop();self.stopped=True;self.lost.emit(error)

    def logout(self):
        self.stopped=True;self.timer.stop();account=dict(self.account)
        def work():
            try:request_json(account['base'],'/api/boommini/logout',account['token'],{},timeout=3)
            except Exception:pass
        threading.Thread(target=work,daemon=False).start()
