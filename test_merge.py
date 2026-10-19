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
    def test_signature_parser_reads_losslesscut_mismatch_fields(self):
        text='''
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(progressive), 720x1280, 2500 kb/s, 24 fps, 24 tbr, 12288 tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 128 kb/s (default)
'''
        self.assertEqual(m._parse_media_signature(text),m.MediaSignature('h264','yuv420p',720,1280,24.0,12288,'aac',48000,'stereo'))

    def test_join_video_encodes_fps_outlier_then_stream_copies(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);inputs=[]
            for name in ('30fps-a.mp4','24fps.mp4','30fps-b.mp4'):
                path=root/name;path.write_bytes(b'input');inputs.append(path)
            output=root/'joined.mp4'
            commands=[]
            class Process:
                returncode=0
                def poll(self):return self.returncode
                def terminate(self):self.returncode=1
                def wait(self):return self.returncode
            def popen(command,**kwargs):
                commands.append(command)
                Path(command[-1]).write_bytes(b'normalized')
                return Process()
            common=m.MediaSignature('h264','yuv420p',720,1280,30.0,15360,'aac',48000,'stereo')
            outlier=m.MediaSignature('h264','yuv420p',720,1280,24.0,12288,'aac',48000,'stereo')
            def probe(path,stop):return outlier if Path(path).name=='24fps.mp4' else common
            with patch.object(m,'ffmpeg',return_value='ffmpeg'),patch.object(m.subprocess,'Popen',side_effect=popen),patch.object(m,'_probe_media',side_effect=probe),patch.object(m,'mp4_duration',return_value=3000):
                m.join_video(inputs,[1000,1000,1000],output,threading.Event())
            self.assertEqual(len(commands),2)
            normalize,join=commands
            self.assertEqual(normalize[normalize.index('-c:v')+1],'libx264')
            self.assertEqual(normalize[normalize.index('-vf')+1],'scale=720:1280,fps=30')
            self.assertEqual(normalize[normalize.index('-video_track_timescale')+1],'15360')
            self.assertEqual(join[join.index('-c')+1],'copy')
            self.assertTrue(output.exists())

    def test_fps_only_mismatch_requires_normalization(self):
        common=m.MediaSignature('h264','yuv420p',720,1280,30.0,15360,'aac',48000,'stereo')
        other_fps=common._replace(fps=24.0)
        self.assertFalse(m._concat_compatible(other_fps,common))

    def test_resolution_mismatch_still_requires_video_encode(self):
        common=m.MediaSignature('h264','yuv420p',720,1280,30.0,15360,'aac',48000,'stereo')
        other_size=common._replace(width=1080,height=1920)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.mp4';destination=root/'fixed.mp4';source.write_bytes(b'input')
            commands=[]
            class Process:
                returncode=0
                def poll(self):return self.returncode
                def terminate(self):self.returncode=1
                def wait(self):return self.returncode
            def popen(command,**kwargs):commands.append(command);destination.write_bytes(b'encoded');return Process()
            with patch.object(m,'ffmpeg',return_value='ffmpeg'),patch.object(m.subprocess,'Popen',side_effect=popen):
                m._prepare_video(source,other_size,common,destination,threading.Event())
            self.assertEqual(commands[0][commands[0].index('-c:v')+1],'libx264')

    def test_time_base_only_mismatch_is_remuxed_without_video_encode(self):
        common=m.MediaSignature('h264','yuv420p',720,1280,30.0,15360,'aac',48000,'stereo')
        outlier=common._replace(time_base=12288)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'source.mp4';destination=root/'fixed.mp4';source.write_bytes(b'input')
            commands=[]
            class Process:
                returncode=0
                def poll(self):return self.returncode
                def terminate(self):self.returncode=1
                def wait(self):return self.returncode
            def popen(command,**kwargs):
                commands.append(command);destination.write_bytes(b'remuxed');return Process()
            with patch.object(m,'ffmpeg',return_value='ffmpeg'),patch.object(m.subprocess,'Popen',side_effect=popen):
                m._prepare_video(source,outlier,common,destination,threading.Event())
            command=commands[0]
            self.assertEqual(command[command.index('-c:v')+1],'copy')
            self.assertNotIn('libx264',command)
            self.assertEqual(command[command.index('-video_track_timescale')+1],'15360')

    def test_offsets_and_invalid_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'a.srt';p.write_text('1\n00:00:00,100 --> 00:00:00,900\nXin chào\n',encoding='utf-8')
            text=m.merge_srt([p,p],[1000,2000])
            self.assertIn('00:00:01,100 --> 00:00:01,900',text)
            for durations in ([1000], [1000,0], [1000,float('nan')]):
                with self.assertRaises(engine.ToolError):m.merge_srt([p,p],durations)
            clipped=m.merge_srt([p],[500])
            self.assertIn('00:00:00,100 --> 00:00:00,500',clipped)

    def test_srt_cue_after_video_is_rejected_as_possible_mismatch(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);late=root/'late.srt';normal=root/'normal.srt'
            late.write_text('1\n00:00:01,100 --> 00:00:01,900\nQuá cuối video\n',encoding='utf-8')
            normal.write_text('1\n00:00:00,100 --> 00:00:00,900\nTập sau\n',encoding='utf-8')
            with self.assertRaisesRegex(engine.ToolError,'late.srt'):
                m.merge_srt([late,normal],[1000,1000])

    def test_large_srt_overrun_is_not_silently_trimmed(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'wrong.srt'
            path.write_text('1\n00:00:00,100 --> 00:00:05,000\nCó thể sai tập\n',encoding='utf-8')
            with self.assertRaisesRegex(engine.ToolError,'4000 ms'):
                m.merge_srt([path],[1000])

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
                def join(paths,durations,output,stop,emit=None):
                    if failure=='video':raise engine.ToolError('failed')
                    output.write_bytes(b'merged')
                with patch.object(m,'mp4_duration',return_value=1000),patch.object(m,'join_video',side_effect=join):
                    m.export_groups(records,episodes,2,'X',root,'Video + phụ đề','all',2,threading.Event(),lambda *e:None)
                for i in range(2):
                    self.assertEqual((root/f'{i}.mp4').exists(),failure!='none')
                    self.assertEqual((root/f'{i}.srt').exists(),failure!='none')
                if failure in ('missing','invalid','existing'):
                    self.assertTrue((root/'X_Trọn bộ.mp4').exists())
                if failure=='none':
                    self.assertTrue((root/'X_Trọn bộ.mp4').exists())
                    self.assertIn('00:00:01,100',(root/'X_Trọn bộ.vi.srt').read_text(encoding='utf-8-sig'))

if __name__=='__main__':unittest.main(verbosity=2)
