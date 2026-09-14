"""Catalog normalization and poster cache, preserved from the original Studio."""
import io
import hashlib
import os
import re
from urllib.parse import quote
from netshort_tool import fetch, limited_read
try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None

def load_poster(url, stop, cache_dir):
    if stop.is_set() or not Image:
        return None
    key = hashlib.sha256(url.encode('utf-8')).hexdigest()
    cached = cache_dir / (key + '.jpg')
    try:
        with Image.open(cached) as image:
            return image.convert('RGB').copy()
    except (OSError, ValueError):
        pass
    # NetShort cover filenames may contain Unicode. http.client requires ASCII
    # request targets; retain existing percent escapes and URL delimiters.
    request_url = quote(url, safe=":/?#[]@!$&'()*+,;=%")
    with fetch(request_url, stop=stop, timeout=8) as response:
        raw = limited_read(response, 8 * 1024 * 1024)
    with Image.open(io.BytesIO(raw)) as image:
        poster = ImageOps.fit(image.convert('RGB'), (160, 220))
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        temporary = cached.with_suffix('.tmp')
        poster.save(temporary, format='JPEG', quality=85)
        os.replace(temporary, cached)
    except OSError:
        pass
    return poster

def catalog_rows(payload):
    """Read normalized Ezvid cards or nested NetShort home/search records."""
    result, seen = [], set()
    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
        elif isinstance(node, dict):
            sid = str(node.get('shortPlayId') or node.get('dramaId') or node.get('id') or '')
            title = node.get('shortPlayName') or node.get('title') or node.get('name')
            if title and re.fullmatch(r'\d{15,25}', sid) and 'episodeNumber' not in node and 'episodeId' not in node:
                if sid not in seen:
                    seen.add(sid)
                    result.append({'id': sid, 'title': str(title),
                        'poster': node.get('shortPlayCover') or node.get('cover') or node.get('image') or node.get('poster'),
                        'total': node.get('totalEpisode') or node.get('totalEpisodes') or node.get('episodeCount') or node.get('total'),
                        'description': node.get('shotIntroduce') or node.get('description') or node.get('introduce') or ''})
            for key, child in node.items():
                if key not in ('sources', 'episodePlayList') and isinstance(child, (list, dict)):
                    walk(child)
    walk(payload.get('data', payload))
    return result

def next_cursor(payload):
    for node in (payload, payload.get('data', {})):
        if isinstance(node, dict):
            for part in (node, node.get('meta', {}), node.get('pagination', {})):
                if isinstance(part, dict) and part.get('nextCursor'):
                    return str(part['nextCursor'])
    return None


def dramawave_rows(payload):
    """Keep the cover and description attached to each normalized movie."""
    from dramawave_tab import movies
    details = {}
    def walk(node):
        if isinstance(node, list):
            for item in node: walk(item)
        elif isinstance(node, dict):
            sid = str(node.get('season_id') or node.get('seasonId') or node.get('id') or '')
            image = next((node.get(k) for k in ('image','cover','poster','coverUrl','thumbnail')
                          if isinstance(node.get(k),str) and node[k].startswith('https://')), None)
            if sid and image:
                extra = node.get('extra') if isinstance(node.get('extra'),dict) else {}
                details[sid] = {'poster':image,'description':node.get('description') or extra.get('description') or ''}
            for child in node.values():
                if isinstance(child,(dict,list)):walk(child)
    walk(payload)
    return [dict(id=sid,title=title,total=count,**details.get(sid,{'poster':None,'description':''}))
            for sid,title,count in movies(payload)]
