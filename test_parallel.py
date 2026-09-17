"""Regression checks for bounded parallelism and cancellation."""
import tempfile
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


if __name__=='__main__':unittest.main(verbosity=2)
