"""Extract explicit subtitle tracks and convert ordinary WebVTT cues to SRT."""
import html
import re


def tracks(payload):
    result, seen = [], set()
    def walk(node, subtitle=False):
        if isinstance(node, list):
            for item in node:
                walk(item, subtitle)
        elif isinstance(node, dict):
            if subtitle:
                url = next((node.get(k) for k in ('subtitleUrl', 'url', 'subtitlePath', 'filePath', 'src')
                            if isinstance(node.get(k), str) and node[k].startswith('https://')), None)
                if url and url not in seen:
                    seen.add(url)
                    result.append({'url': url, 'language': str(node.get('subtitleLanguage') or
                        node.get('language') or node.get('lang') or node.get('srclang') or 'und')})
            for key, value in node.items():
                if isinstance(value, (dict, list)):
                    walk(value, subtitle or key.lower() in ('subtitles', 'subtitlelist', 'subtitle', 'captionlist', 'captions'))
                elif key == 'subtitleUrl' and isinstance(value, str) and value.startswith('https://'):
                    walk(dict(node, url=value), True) if not subtitle else None
    walk(payload)
    return result


def as_srt(raw):
    text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text.startswith('WEBVTT'):
        if re.search(r'\d{2}:\d{2}:\d{2},\d{3}\s+-->\s+\d{2}:\d{2}:\d{2},\d{3}', text):
            return text + '\n'
        raise ValueError('Không phải SRT hoặc WebVTT UTF-8 hợp lệ.')
    def stamp(value):
        parts = value.split(':')
        if len(parts) == 2:
            value = '00:' + value
        return value.replace('.', ',')
    cues = []
    for block in re.split(r'\n\s*\n', text):
        lines = block.splitlines()
        if not lines or lines[0].startswith(('WEBVTT', 'NOTE', 'STYLE', 'REGION')):
            continue
        for i, line in enumerate(lines):
            timing = re.match(r'((?:\d{2,}:)?\d{2}:\d{2}\.\d{3})\s+-->\s+((?:\d{2,}:)?\d{2}:\d{2}\.\d{3})(?:\s.*)?$', line)
            if timing:
                body = '\n'.join(lines[i + 1:])
                body = re.sub(r'<(?:\d[^>]*|/?(?:c|v|lang)(?:[ .][^>]*)?)>', '', body)
                body = html.unescape(body).strip()
                if body:
                    cues.append(f'{len(cues)+1}\n{stamp(timing[1])} --> {stamp(timing[2])}\n{body}')
                break
    if not cues:
        raise ValueError('WebVTT không có đoạn phụ đề hợp lệ.')
    return '\n\n'.join(cues) + '\n'


def language_matches(actual, requested):
    if ',' in requested:
        return any(language_matches(actual, item.strip()) for item in requested.split(','))
    actual, requested = actual.lower().replace('_','-'), requested.lower().replace('_','-')
    if requested == 'all':
        return True
    return actual == requested if '-' in requested else actual.split('-')[0] == requested


LANGUAGE_NAMES = {'vi':'Tiếng Việt', 'en':'Tiếng Anh', 'zh':'Tiếng Trung', 'th':'Tiếng Thái',
    'id':'Tiếng Indonesia', 'ja':'Tiếng Nhật', 'ko':'Tiếng Hàn', 'fr':'Tiếng Pháp',
    'de':'Tiếng Đức', 'es':'Tiếng Tây Ban Nha', 'pt':'Tiếng Bồ Đào Nha', 'ru':'Tiếng Nga',
    'ms':'Tiếng Mã Lai', 'ar':'Tiếng Ả Rập', 'hi':'Tiếng Hindi', 'it':'Tiếng Ý',
    'tr':'Tiếng Thổ Nhĩ Kỳ', 'tl':'Tiếng Philippines', 'und':'Không rõ ngôn ngữ'}


def coverage(results):
    """Each episode contributes at most once per language; None means scan failed."""
    counts = {}
    for entries in results.values():
        if entries is not None:
            for lang in {t['language'].replace('_','-').lower() for t in entries}:
                counts[lang] = counts.get(lang, 0) + 1
    return sorted(counts.items(), key=lambda item:(not item[0].startswith('vi'),item[0]))


def language_name(code):
    return LANGUAGE_NAMES.get(code.replace('_','-').split('-')[0].lower(),code)
