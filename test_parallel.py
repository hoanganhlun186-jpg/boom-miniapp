"""Regression checks for bounded parallelism and cancellation."""
import tempfile
import io
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from studio_backend import Backend
import netshort_tool as engine


class FakeAPI:
    def __init__(self,*args):pass
    def get(self,*args):return {'sources':[{'url':'https://example.test/video.mp4','type':'mp4'}]}


class Tests(unittest.TestCase):
    def backend(self,directory,workers,count):
        events=[];idle=threading.Event()
        def emit(event):
            events.append(event)
            if event[0]=='idle':idle.set()
        b=Backend(emit,'fixture-token')
        b.scanned=(b.base.get(),b.language.get(),'123456789012345')
        b.scanned_title='Phim thử'
        b.folder.set(directory);b.download_mode.set('Video');b.download_workers.set(workers)
        b.items=[dict(id=str(i+1),episodeNumber=i+1) for i in range(count)]
        b.tree.selected=list(range(count))
        return b,events,idle

    def test_three_five_ten_are_really_parallel(self):
        for workers in (3,5,10):
            with self.subTest(workers=workers),tempfile.TemporaryDirectory() as directory:
                b,events,idle=self.backend(directory,workers,workers*2)
                lock=threading.Lock();state={'active':0,'peak':0}
                barrier=threading.Barrier(workers)
                def download(source,path,stop,progress):
                    with lock:
                        state['active']+=1;state['peak']=max(state['peak'],state['active'])
                    try:
                        barrier.wait(timeout=3)
                        progress(1,2);time.sleep(.02)
                        path.write_bytes(b'fixture');progress(2,2)
                    finally:
                        with lock:state['active']-=1
                with patch.object(engine,'API',FakeAPI),patch.object(engine,'download',download):
                    b.start_download();self.assertTrue(idle.wait(6))
                self.assertEqual(state['peak'],workers)
                self.assertEqual(len(list(Path(directory).rglob('*.mp4'))),workers*2)
                percentages=[e[1] for e in events if e[0]=='progress']
                self.assertEqual(percentages,sorted(percentages))
                self.assertEqual(percentages[-1],100)
                self.assertEqual(sum(e[0]=='status' and e[2]=='Đã tải' for e in events),workers*2)

    def test_stop_prevents_waiting_episodes_starting(self):
        with tempfile.TemporaryDirectory() as directory:
            b,events,idle=self.backend(directory,3,20)
            entered=threading.Barrier(4);release=threading.Event();calls=[]
            def download(source,path,stop,progress):
                calls.append(path);entered.wait(timeout=3);release.wait(3)
                if stop.is_set():raise engine.Cancelled('Đã dừng.')
            with patch.object(engine,'API',FakeAPI),patch.object(engine,'download',download):
                b.start_download();entered.wait(timeout=3);b.stop.set();release.set()
                self.assertTrue(idle.wait(5))
            self.assertEqual(len(calls),3)
            self.assertEqual(len(list(Path(directory).rglob('*.mp4'))),0)
            self.assertEqual(sum(e[0]=='status' and e[2]=='Chưa tải — đã dừng' for e in events),17)

    def test_duplicate_paths_rejected_before_download(self):
        with tempfile.TemporaryDirectory() as directory:
            b,events,idle=self.backend(directory,3,2)
            b.items[1]['episodeNumber']=1
            with patch.object(engine,'download') as download:
                b.start_download();self.assertTrue(idle.wait(3));download.assert_not_called()
            self.assertTrue(any(e[0]=='error' for e in events))

    def test_retry_download_then_success(self):
        with tempfile.TemporaryDirectory() as directory:
            b,events,idle=self.backend(directory,3,1)
            attempts=[]
            def download(source,path,stop,progress):
                attempts.append(path)
                if len(attempts)<3:raise engine.ToolError('HTTP 503')
                path.write_bytes(b'video')
            with patch.object(engine,'API',FakeAPI),patch.object(engine,'download',download):
                b.start_download();self.assertTrue(idle.wait(8))
            self.assertEqual(len(attempts),3)
            self.assertEqual(len(list(Path(directory).rglob('*.mp4'))),1)
            self.assertTrue(any(e[0]=='batch' and e[1]==1 and e[4]==0 for e in events))

    def test_retry_exhausted_and_auth_not_retried(self):
        for message,expected in [('HTTP 503',3),('HTTP 403',1)]:
            with self.subTest(message=message),tempfile.TemporaryDirectory() as directory:
                b,events,idle=self.backend(directory,3,1)
                with patch.object(engine,'API',FakeAPI),patch.object(engine,'download',side_effect=engine.ToolError(message)) as download:
                    b.start_download();self.assertTrue(idle.wait(8))
                self.assertEqual(download.call_count,expected)
                self.assertTrue(any(e[0]=='batch' and e[4]==1 for e in events))

    def test_subtitle_retry_reuses_completed_video(self):
        with tempfile.TemporaryDirectory() as directory:
            b,events,idle=self.backend(directory,3,1)
            b.scanned_provider='dramawave';b.download_mode.set('Video + phụ đề');b.subtitle_language.set('vi')
            b.items[0].update(sources=[{'type':'mp4','url':'https://example.test/a.mp4'}],
                              subtitles=[{'language':'vi','url':'https://example.test/a.srt'}])
            def download(source,path,stop,progress):path.write_bytes(b'video')
            with patch.object(engine,'download',side_effect=download) as downloads,patch.object(engine,'fetch',side_effect=[engine.ToolError('HTTP 503'),io.BytesIO(b'1\n00:00:00,100 --> 00:00:00,900\nHi\n')]) as fetch:
                b.start_download();self.assertTrue(idle.wait(5))
            self.assertEqual(downloads.call_count,1)
            self.assertEqual(fetch.call_count,2)
            self.assertEqual(len(list(Path(directory).rglob('*.srt'))),1)


if __name__=='__main__':unittest.main(verbosity=2)
