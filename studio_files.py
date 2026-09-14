"""Human-readable, Windows-compatible movie output names."""
import re


def safe_name(value, fallback='Phim'):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:90].rstrip(' .')
    if not name:
        name = fallback
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
        name = '_' + name
    return name


def episode_stem(title, episode, index):
    number = episode.get('episodeNumber') or episode.get('episodeNo') or index + 1
    return f'{safe_name(title)}_tập {safe_name(number)}'
