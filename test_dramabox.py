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
        self.assertEqual(parse_qs(url.query),{'query':['love'],'lang':['vi']})

    def test_allepisode_contract_and_raw_chapters(self):
        payload={'ok':True,'data':{'data':[
            {'chapterId':'102','chapterIndex':1,'cdnList':[{'videoPathList':[
                {'videoPath':'https://example.test/720.mp4','quality':720},
                {'videoPath':'https://example.test/1080.mp4','quality':1080}]}]},
            {'chapterId':'101','chapterIndex':0}]}}
        with patch.object(gateway_client,'request_json',return_value=payload) as request:
            title,episodes=self.api().episodes('41000102982')
        url=urlsplit(request.call_args.args[1])
        self.assertEqual(url.path,'/api/boommini/proxy/dramabox/allepisode')
        self.assertEqual(parse_qs(url.query),{'bookId':['41000102982']})
        self.assertEqual([ep['id'] for ep in episodes],['101','102'])
        self.assertEqual([ep['episodeNumber'] for ep in episodes],[1,2])
        self.assertEqual(source_candidates({'data':episodes[1]})[0]['url'],'https://example.test/1080.mp4')

    def test_other_provider_contract_unchanged(self):
        with patch.object(gateway_client,'request_json',return_value={}) as request:
            API('https://example.test','fixture','vi',threading.Event(),'shortmax').get('/api/shortmax/search',{'q':'love','limit':30})
        self.assertEqual(parse_qs(urlsplit(request.call_args.args[1]).query),
                         {'q':['love'],'limit':['30'],'language':['vi']})


if __name__=='__main__':unittest.main()
