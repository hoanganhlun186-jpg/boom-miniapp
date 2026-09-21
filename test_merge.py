import io
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import boom_merge as m
import netshort_tool as engine
import test_parallel

class MergeTests(unittest.TestCase):
    def test_offsets_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a.srt';p.write_text('1\n00:00:00,100 --> 00:00:00,900\nXin chào\n',encoding='utf-8')
            text=m.merge_srt([p,p],[1000,2000])
            self.assertIn('00:00:01,100 --> 00:00:01,900',text)
            for durations in ([1000], [1000,0], [1000,float('nan')]):
                with self.assertRaises(engine.ToolError):m.merge_srt([p,p],durations)
            with self.assertRaises(engine.ToolError):m.merge_srt([p],[500])

    def test_parts_missing_episode_and_existing_video(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);records={};episodes=[];events=[]
            for i in range(3):
                p=root/f'{i}.srt';p.write_text('1\n00:00:00,100 --> 00:00:00,900\nHi\n')
                records[i]={'video':root/f'{i}.mp4','subs':{'vi':p},'duration':1}
                episodes.append((i,{'episodeNumber':i+1}))
            args=(records,episodes,3,'Phim',root)
            m.export_groups(*args,'Chỉ phụ đề','parts',2,threading.Event(),lambda *e:events.append(e))
            self.assertIn('00:00:01,100',(root/'Phim_Phần 1.vi.srt').read_text(encoding='utf-8-sig'))
            self.assertTrue((root/'Phim_Phần 2.vi.srt').exists())
            self.assertFalse(list(root.glob('[0-9].srt')))
            for i in range(3):
                (root/f'{i}.srt').write_text('1\n00:00:00,100 --> 00:00:00,900\nHi\n')
            records.pop(1)
            m.export_groups(*args,'Chỉ phụ đề','all',2,threading.Event(),lambda *e:events.append(e))
            self.assertFalse((root/'Phim_Trọn bộ.vi.srt').exists())
            records[1]={'video':root/'1.mp4','subs':{'vi':root/'1.srt'},'duration':1}
            output=root/'Phim_Trọn bộ.mp4';output.write_bytes(b'keep')
            with patch.object(m,'mp4_duration',return_value=3000),patch.object(m,'join_video') as join:
                m.export_groups(*args,'Video + phụ đề','all',2,threading.Event(),lambda *e:events.append(e))
                join.assert_not_called()
            self.assertTrue((root/'Phim_Trọn bộ.vi.srt').exists())
            self.assertEqual(output.read_bytes(),b'keep')

    def test_cancel_propagates(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);records={0:{'video':root/'x.mp4','subs':{},'duration':1}}
            with patch.object(m,'join_video',side_effect=engine.Cancelled('stop')):
                with self.assertRaises(engine.Cancelled):m.export_groups(records,[(0,{})],1,'X',root,'Video','all',2,threading.Event(),lambda *e:None)

    def test_srt_only_without_video_source_normalizes_vi(self):
        with tempfile.TemporaryDirectory() as td:
            b,events,idle=test_parallel.Tests().backend(td,3,2)
            b.scanned_provider='dramawave';b.download_mode.set('Chỉ phụ đề');b.subtitle_language.set('vi');b.output_layout.set('all')
            for ep in b.items:
                ep['duration']=2
                ep['subtitles']=[{'language':'vi_VN','url':'https://example.test/vi.srt'}]
            with patch.object(engine,'download') as download,patch.object(engine,'fetch',side_effect=lambda *a,**k:io.BytesIO(b'1\n00:00:00,100 --> 00:00:00,900\nHi\n')):
                b.start_download();self.assertTrue(idle.wait(5));download.assert_not_called()
            paths=list(Path(td).rglob('*.srt'))
            self.assertEqual(len(paths),1,events)
            self.assertTrue(all(p.name.endswith('.vi.srt') for p in paths))
            self.assertFalse(list(Path(td).rglob('*.mp4')))

    def test_combined_merge_cleans_only_after_complete_success(self):
        for failure in ('none','missing','invalid','existing','video'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as td:
                root=Path(td);records={};episodes=[(0,{}),(1,{})]
                for i in range(2):
                    video=root/f'{i}.mp4';video.write_bytes(b'video')
                    sub=root/f'{i}.srt';sub.write_text('1\n00:00:00,100 --> 00:00:00,900\nHi\n')
                    records[i]={'video':video,'subs':{'vi':sub},'duration':1}
                if failure=='missing':records[1]['subs']={}
                if failure=='invalid':(root/'1.srt').write_text('invalid')
                if failure=='existing':(root/'X_Trọn bộ.vi.srt').write_text('different')
                def join(paths,durations,output,stop):
                    if failure=='video':raise engine.ToolError('failed')
                    output.write_bytes(b'merged')
                with patch.object(m,'mp4_duration',return_value=1000),patch.object(m,'join_video',side_effect=join):
                    m.export_groups(records,episodes,2,'X',root,'Video + phụ đề','all',2,threading.Event(),lambda *e:None)
                for i in range(2):
                    self.assertEqual((root/f'{i}.mp4').exists(),failure!='none')
                    self.assertEqual((root/f'{i}.srt').exists(),failure!='none')
                if failure=='none':
                    self.assertTrue((root/'X_Trọn bộ.mp4').exists())
                    self.assertIn('00:00:01,100',(root/'X_Trọn bộ.vi.srt').read_text(encoding='utf-8-sig'))

if __name__=='__main__':unittest.main(verbosity=2)
