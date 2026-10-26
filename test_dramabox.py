"""DramaBox transport contract checks; no GUI or network credentials required."""
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs
import gateway_client
from netshort_tool import API, source_candidates
from studio_providers import catalog_endpoint


class DramaBoxTests(unittest.TestCase):
    def api(self):
        return API('https://example.test','fixture','vi',threading.Event(),'dramabox')

    def test_catalog_and_search_contract(self):
        self.assertEqual(catalog_endpoint('dramabox','home'),'foryou')
        with patch.object(gateway_client,'request_json',return_value={}) as request:
            self.api().get('/api/dramabox/search',{'q':'love','limit':30})
        url=urlsplit(request.call_args.args[1])
        self.assertEqual(url.path,'/api/boommini/proxy/dramabox/search')
        self.assertEqual(parse_qs(url.query),{'q':['love'],'limit':['30'],'language':['vi']})

    def test_allepisode_contract_and_raw_chapters(self):
        payload={'success':True,'data':{'items':[
            {'id':'2','episodeNumber':2},{'id':'1','episodeNumber':1}],
            'total':2,'meta':{'title':'Phim'}}}
        with patch.object(gateway_client,'request_json',return_value=payload) as request:
            title,episodes=self.api().episodes('41000102982')
        url=urlsplit(request.call_args.args[1])
        self.assertEqual(url.path,'/api/boommini/proxy/dramabox/episodes/41000102982')
        self.assertEqual(parse_qs(url.query),{'language':['vi']})
        self.assertEqual([ep['id'] for ep in episodes],['1','2'])
        self.assertEqual([ep['episodeNumber'] for ep in episodes],[1,2])

    def test_other_provider_contract_unchanged(self):
        with patch.object(gateway_client,'request_json',return_value={}) as request:
            API('https://example.test','fixture','vi',threading.Event(),'shortmax').get('/api/shortmax/search',{'q':'love','limit':30})
        self.assertEqual(parse_qs(urlsplit(request.call_args.args[1]).query),
                         {'q':['love'],'limit':['30'],'language':['vi']})

    def test_live_dramabox_video_url_fields(self):
        episode={'chapterId':'1','videoUrl':'https://example.test/default.mp4',
                 'videoUrl540':'https://example.test/540.mp4',
                 'videoUrl720':None,'videoUrl1080':'https://example.test/1080.mp4'}
        sources=source_candidates({'data':episode})
        self.assertEqual([s['quality'] for s in sources],[1080,540,0])
        self.assertEqual(sources[0]['url'],episode['videoUrl1080'])


if __name__=='__main__':unittest.main()
