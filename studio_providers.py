"""Provider names and catalog normalization from Ezvid responses."""
import re
from urllib.parse import urlsplit, parse_qs
NAMES={'netshort':'NetShort','dramawave':'DramaWave','shortmax':'ShortMax','dramabox':'DramaBox'}
LANGUAGES={'netshort':'vi_VN','dramawave':'vi-VN','shortmax':'vi','dramabox':'vi'}
NEW_PROVIDERS=('shortmax','dramabox')

def catalog_endpoint(provider,action):
    if provider=='dramawave':return 'search' if action=='search' else 'search/hot-list'
    if provider=='dramabox':return 'search' if action=='search' else 'foryou'
    if provider in NEW_PROVIDERS:return 'search' if action=='search' else 'home'
    return action

def series_id(value,provider):
    value=value.strip()
    if re.fullmatch(r'\d{1,25}',value):return value
    p=urlsplit(value)
    domains=('shorttv.live','shortmax.com') if provider=='shortmax' else ('dramabox.com','dramaboxapp.com','dramaboxdb.com')
    if p.scheme not in ('http','https') or not any(p.hostname==d or (p.hostname or '').endswith('.'+d) for d in domains):return None
    q=parse_qs(p.query)
    for key in ('shortPlayCode','bookId','dramaId','id'):
        candidate=q.get(key,[''])[0]
        if re.fullmatch(r'\d{1,25}',candidate):return candidate
    # Only explicit series/detail URLs; never mistake an episode number for a series.
    match=re.search(r'/(?:drama|book|detail|short-play)/[^/?]*?(\d{5,25})(?:[-/]|$)',p.path)
    return match[1] if match else None

def movie_rows(payload,provider):
    result=[];seen=set()
    def walk(node):
        if isinstance(node,list):
            for child in node:walk(child)
        elif isinstance(node,dict):
            extra=node.get('extra') if isinstance(node.get('extra'),dict) else {}
            sid=str(node.get('shortPlayCode') or node.get('bookId') or node.get('id') or '')
            title=node.get('shortPlayName') or node.get('bookName') or node.get('title')
            if title and re.fullmatch(r'\d{1,25}',sid) and not any(k in node for k in ('episodeNumber','episodeId','tabId','bannerId','chapterId')) and sid not in seen:
                seen.add(sid)
                result.append({'id':sid,'title':str(title),'poster':node.get('picUrl') or node.get('coverWap') or node.get('image') or node.get('cover'),
                  'total':node.get('totalEpisodes') or node.get('chapterCount') or extra.get('totalEpisodes'),
                  'description':node.get('summary') or node.get('introduction') or node.get('description') or extra.get('description') or extra.get('introduction') or ''})
            for key,child in node.items():
                if key not in ('extra','sources','labelList','tags','tagV3s','episodeList') and isinstance(child,(list,dict)):walk(child)
    walk(payload)
    return result
