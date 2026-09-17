"""BOOM Qt offline integration tests. Uses mocked API responses only."""
import io
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PyQt6.QtWidgets import QApplication
from studio_qt import MainWindow
from studio_files import safe_name, episode_stem
from netshort_subtitles import coverage, as_srt
import netshort_tool as engine

APP = QApplication.instance() or QApplication([])


def wait_until(condition, timeout=4):
    until=time.monotonic()+timeout
    while not condition() and time.monotonic()<until:
        APP.processEvents(); time.sleep(.01)
    APP.processEvents()
    assert condition(), 'Timed out waiting for worker'


class Tests(unittest.TestCase):
    def test_unicode_poster_url(self):
        from PIL import Image
        from studio_catalog import load_poster
        import threading
        data=io.BytesIO()
        Image.new('RGB',(20,30),'teal').save(data,format='PNG')
        class Reply(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        with tempfile.TemporaryDirectory() as directory:
            with patch('studio_catalog.fetch',return_value=Reply(data.getvalue())) as fetch:
                result=load_poster('https://example.test/ảnh（越南）%20cover.webp?x=1&y=2',threading.Event(),Path(directory))
                url=fetch.call_args.args[0]
                self.assertTrue(url.isascii())
                self.assertIn('%20cover.webp?x=1&y=2',url)
                self.assertNotIn('%2520',url)
                self.assertEqual(result.size,(160,220))

    def test_safe_names(self):
        self.assertEqual(safe_name(' CON. '),'_CON')
        self.assertEqual(safe_name('A/B: C?'),'A_B_ C_')
        self.assertEqual(safe_name('...'),'Phim')
        self.assertEqual(episode_stem('Tên phim',{'episodeNo':8},0),'Tên phim_tập 8')

    def test_subtitles(self):
        self.assertIn('00:00:01,000 --> 00:00:02,000',as_srt(b'WEBVTT\n\n00:01.000 --> 00:02.000\nHello\n'))
        self.assertEqual(coverage({0:[{'language':'en'},{'language':'vi_VN'}],1:None})[0],('vi-vn',1))

    def test_qt_scan_select_download_and_switch(self):
        window=MainWindow()
        window.ensure_movie_card=lambda:None
        b=window.backend
        episodes=[dict(id=str(i+10),episodeNumber=i+1) for i in range(60)]
        payload={'sources':[{'url':'https://example.test/video.mp4','type':'mp4'}],
                 'subtitles':[{'url':'https://example.test/vi.vtt','language':'vi'},
                              {'url':'https://example.test/en.vtt','language':'en'}]}
        class FakeAPI:
            def __init__(self,*args):pass
            def episodes(self,sid):return 'Tên phim',episodes
            def get(self,*args):return payload
        class Reply(io.BytesIO):
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        try:
            with tempfile.TemporaryDirectory() as directory:
                window.history_path=Path(directory)/'history.json'
                b.folder.set(directory)
                with patch.object(engine,'API',FakeAPI),patch.object(engine,'resolve_series',return_value='123456789012345'):
                    window.open_movie({'id':'123456789012345','title':'Tên phim'})
                    wait_until(lambda:not b.busy and bool(window.language_checks))
                self.assertEqual(len(window.episode_checks),60)
                self.assertEqual(len(b.tree.selected),60)
                self.assertEqual(b.subtitle_language.get(),'vi')
                self.assertEqual(list(window.language_checks),['vi','en'])
                window.clear_selection()
                window.episode_checks[0].click()
                self.assertEqual(b.tree.selected,[0])
                window.render_subtitles({0:[{'language':'th'}]})
                self.assertEqual(b.subtitle_language.get(),'')
                window.render_subtitles({0:[{'language':'vi'}]})
                window.show_page(1); window.show_page(2); window.show_page(0)
                window.show()
                for width,height in ((1160,780),(1480,960)):
                    window.resize(width,height); APP.processEvents()
                    self.assertTrue(window.download_button.isVisible())
                    self.assertLessEqual(window.download_button.mapTo(window,window.download_button.rect().bottomRight()).y(),window.height())
                calls=[]
                def fake_download(source,path,stop,progress):
                    calls.append(path); path.write_bytes(b'fixture-video'); progress(1,1)
                with patch.object(engine,'API',FakeAPI),patch.object(engine,'download',fake_download),patch.object(engine,'fetch',lambda *a,**k:Reply(b'WEBVTT\n\n00:01.000 --> 00:02.000\nHello\n')):
                    window.start_download(); wait_until(lambda:not b.busy)
                    target=Path(directory)/'Tên phim'
                    self.assertEqual((target/'Tên phim_tập 1.mp4').read_bytes(),b'fixture-video')
                    self.assertTrue((target/'Tên phim_tập 1.vi.srt').exists())
                    window.start_download(); wait_until(lambda:not b.busy)
                    self.assertEqual(len(calls),1,'Existing video must not be overwritten')
                    window.with_subtitles.setChecked(False)
                    window.start_download(); wait_until(lambda:not b.busy)
                    self.assertEqual(b.download_mode.get(),'Video')
                    self.assertEqual(len(calls),1)
                self.assertEqual(window.history[0]['title'],'Tên phim')
                window.switch_provider('dramawave')
                self.assertEqual(b.fixed_provider,'dramawave')
                self.assertIsNone(b.scanned)
                self.assertEqual(b.tree.selected,[])
                self.assertEqual(window.pages.currentIndex(),0)
        finally:
            window.close(); window.deleteLater(); APP.processEvents()

    def test_direct_link_card_and_thumbnail(self):
        from PIL import Image
        window=MainWindow()
        try:
            window.switch_provider('dramawave')
            window.art_stop.clear()
            window.current_movie={'id':'test123','title':'Test movie'}
            window.backend.items=[{'id':'ep1','image':'https://example.test/frame.jpg'}]
            class FakeAPI:
                def __init__(self,*args):pass
                def get(self,path,*args):
                    assert path=='/api/dramawave/detail/test123',path
                    return {'data':{'items':[{'id':'test123','title':'Test movie','image':'https://example.test/cover.jpg','extra':{'episodeCount':1}}]}}
            with patch('studio_qt.API',FakeAPI),patch('studio_qt.load_poster',return_value=Image.new('RGB',(160,220),'teal')) as load:
                window.ensure_movie_card()
                wait_until(lambda:bool(window.mini_poster.pixmap()) and not window.mini_poster.pixmap().isNull())
                self.assertEqual(len(window.cards),1)
                self.assertEqual(load.call_args.args[0],'https://example.test/cover.jpg')
                self.assertFalse(window.cards[0].poster.pixmap().isNull())
                window.ensure_movie_card()
                self.assertEqual(len(window.cards),1)
        finally:
            window.close();window.deleteLater();APP.processEvents()


if __name__=='__main__':unittest.main(verbosity=2)
