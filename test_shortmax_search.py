import unittest
from studio_providers import match_movie_titles,series_id

class SearchTests(unittest.TestCase):
    def test_public_episode_listing_link(self):
        self.assertEqual(series_id('https://www.shorttv.live/vi/episodes/yeu-em-giua-song-gio-24421','shortmax'),'24421')
        self.assertEqual(series_id('https://www.shorttv.live/episodes/title-24421/?x=1','shortmax'),'24421')
        self.assertIsNone(series_id('https://evil.test/vi/episodes/title-24421','shortmax'))
        self.assertIsNone(series_id('https://www.shorttv.live/vi/episodes/title-24421/2','shortmax'))

    def test_vietnamese_titles_with_or_without_accents(self):
        rows=[{'id':'1','title':'[Lồng tiếng] Yêu Em Đến Cuối Đời'},
              {'id':'2','title':'Yêu Nhầm Anh Trai Của Bạn Thân'}]
        for query in ('yêu em','YEU EM','  yêu   em  '):
            self.assertEqual(match_movie_titles(rows,query),rows[:1])
        self.assertEqual(match_movie_titles(rows,'den cuoi doi'),rows[:1])
        self.assertEqual(match_movie_titles(rows,'không có'),[])
        self.assertEqual(match_movie_titles(rows,''),[])
