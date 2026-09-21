import io,threading,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import netshort_tool as engine
import gateway_client
from studio_providers import movie_rows,series_id
from test_studio import APP,wait_until
from studio_qt import MainWindow

class ProviderTests(unittest.TestCase):
    def test_catalog_raw_and_normalized(self):
        raw={'data':{'tabPageResponse':{'bannerResponseList':[{'bannerId':14,'title':'Popular','shortPlayResponseList':[{'shortPlayCode':864283,'id':34949,'shortPlayName':'Phim','picUrl':'https://example.test/p.jpg','totalEpisodes':125}]}]}}}
        rows=movie_rows(raw,'shortmax');self.assertEqual([r['id'] for r in rows],['864283'])
        box=movie_rows({'data':{'items':[{'id':'42000003101','title':'Phim','image':'https://example.test/x.jpg','extra':{'introduction':'Mô tả'}}]}},'dramabox')
        self.assertEqual(box[0]['description'],'Mô tả')
        self.assertFalse(movie_rows({'items':[{'id':'123','title':'EP 1','episodeNumber':1}]},'dramabox'))

    def test_hls_referer_is_forwarded(self):
        with patch('dramawave_hls.download_hls') as downloader:
            engine.download({'url':'https://example.test/video.m3u8','type':'m3u8','referer':'https://www.shorttv.live/'},Path('unused.mp4'),threading.Event(),lambda *a:None)
            self.assertEqual(downloader.call_args.kwargs['referer'],'https://www.shorttv.live/')

    def test_transport_and_ids(self):
        for provider in ('shortmax','dramabox'):
            with patch.object(gateway_client,'request_json',return_value={}) as request:
                api=engine.API('https://example.test','fixture','vi',threading.Event(),provider)
                api.get(f'/api/{provider}/home')
                self.assertIn('/proxy/'+provider+'/home?'+('lang' if provider=='dramabox' else 'language')+'=vi',request.call_args.args[1])
            self.assertEqual(series_id('12345',provider),'12345')
            self.assertIsNone(series_id('https://evil.test/drama/12345',provider))
        self.assertEqual(series_id('https://www.dramabox.com/drama/42000003101-title','dramabox'),'42000003101')

    def test_partial_episode_total_and_cursor(self):
        api=engine.API('https://example.test','fixture','vi',threading.Event(),'shortmax')
        data={'data':{'items':[{'id':'1','episodeNumber':1,'sources':[]}],'total':125,'meta':{'title':'Phim'}}}
        with patch.object(api,'get',return_value=data):
            title,items=api.episodes('12345');self.assertEqual(items[0]['_series_total'],125)
        data['data']['nextCursor']='same'
        with patch.object(api,'get',return_value=data):
            with self.assertRaises(engine.ToolError):api.episodes('12345')

    def test_both_provider_scan_download_and_srt(self):
        for provider in ('shortmax','dramabox'):
            w=MainWindow();w.ensure_movie_card=lambda:None
            try:
                w.switch_provider(provider);self.assertEqual(w.backend.language.get(),'vi')
                self.assertEqual(len(w.provider_buttons),4)
                episodes=[{'id':'101','episodeNumber':1,'sources':[{'type':'mp4','url':'https://example.test/video.mp4'}],'subtitles':[{'language':'vi_VN','url':'https://example.test/s.srt'}]}]
                class FakeAPI:
                    def __init__(self,*args):pass
                    def episodes(self,sid):return 'Phim',episodes
                with tempfile.TemporaryDirectory() as td:
                    w.history_path=Path(td)/'history.json';w.backend.folder.set(td)
                    with patch.object(engine,'API',FakeAPI):
                        w.open_movie({'id':'12345','title':'Phim'})
                        wait_until(lambda:not w.backend.busy and bool(w.language_checks))
                    self.assertEqual(w.backend.scanned_provider,provider)
                    w.content_mode.setCurrentIndex(2)
                    with patch.object(engine,'API',FakeAPI),patch.object(engine,'download') as download,patch.object(engine,'fetch',side_effect=lambda *a,**k:io.BytesIO(b'1\n00:00:00,100 --> 00:00:00,900\nHi\n')):
                        w.start_download();wait_until(lambda:not w.backend.busy);download.assert_not_called()
                    self.assertTrue(list(Path(td).rglob('*.vi.srt')))
            finally:w.close();w.deleteLater();APP.processEvents()

if __name__=='__main__':unittest.main(verbosity=2)
