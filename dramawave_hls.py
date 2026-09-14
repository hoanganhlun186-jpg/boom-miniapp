"""Download unencrypted VOD HLS to local files, then remux with FFmpeg."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urljoin


def download_hls(url, destination, stop, progress):
    from netshort_tool import fetch, limited_read, ToolError, Cancelled
    ffmpeg = shutil.which('ffmpeg')
    bundled = Path(__file__).resolve().parent / 'ffmpeg.exe'
    if not ffmpeg and bundled.exists():
        ffmpeg = str(bundled)
    if not ffmpeg:
        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            pass
    if not ffmpeg:
        raise ToolError('Video HLS cần FFmpeg. Chạy: py -m pip install imageio-ffmpeg. Hoặc đặt ffmpeg.exe cạnh tool. Vẫn có thể chọn Chỉ phụ đề.')
    if destination.exists():
        raise ToolError('File MP4 đã tồn tại.')
    def manifest(link):
        with fetch(link, stop=stop) as response:
            effective = response.geturl()
            text = limited_read(response, 2*1024*1024).decode('utf-8-sig')
        if not text.startswith('#EXTM3U'):
            raise ToolError('Nguồn không trả playlist HLS hợp lệ.')
        if any(line.startswith(('#EXT-X-KEY:', '#EXT-X-SESSION-KEY:')) and 'METHOD=NONE' not in line for line in text.splitlines()):
            raise ToolError('HLS có mã hóa; tool không xử lý nguồn này.')
        return effective, text
    def attrs(line):
        return dict((k, v.strip('"')) for k,v in re.findall(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)',line))
    with tempfile.TemporaryDirectory(prefix='dw_hls_',dir=destination.parent) as tmp:
        root = Path(tmp)
        base, text = manifest(url)
        lines = text.splitlines()
        variants = []
        for i,line in enumerate(lines):
            if line.startswith('#EXT-X-STREAM-INF:'):
                info = attrs(line)
                next_uri = next((l.strip() for l in lines[i+1:] if l.strip() and not l.startswith('#')), None)
                if next_uri:
                    variants.append((int(info.get('BANDWIDTH','0')),info,urljoin(base,next_uri)))
        inputs = []
        if variants:
            _, info, video = max(variants,key=lambda x:x[0])
            inputs.append(video)
            audio = [attrs(line) for line in lines if line.startswith('#EXT-X-MEDIA:')]
            audio = [a for a in audio if a.get('TYPE')=='AUDIO' and a.get('GROUP-ID')==info.get('AUDIO') and a.get('URI')]
            if audio:
                chosen = next((a for a in audio if a.get('DEFAULT')=='YES'),audio[0])
                inputs.append(urljoin(base,chosen['URI']))
        else:
            inputs.append(base)
        local_inputs = []
        for index, link in enumerate(inputs):
            base, text = manifest(link)
            if '#EXT-X-ENDLIST' not in text:
                raise ToolError('Chỉ hỗ trợ HLS video hoàn chỉnh, không tải luồng trực tiếp.')
            if '#EXT-X-BYTERANGE' in text:
                raise ToolError('Playlist dùng byte-range chưa được hỗ trợ.')
            folder = root / str(index)
            folder.mkdir()
            count = 0
            total = sum(1 for line in text.splitlines() if line.strip() and not line.startswith('#'))
            output = []
            def save(uri):
                nonlocal count
                if stop.is_set():
                    raise Cancelled('Đã dừng tải HLS.')
                file = folder / f'{count:05d}.bin'
                with fetch(urljoin(base,uri),stop=stop) as response, file.open('xb') as target:
                    while True:
                        if stop.is_set():
                            raise Cancelled('Đã dừng tải HLS.')
                        block = response.read(256*1024)
                        if not block:
                            break
                        target.write(block)
                if not file.stat().st_size:
                    raise ToolError('Đoạn HLS rỗng.')
                count += 1
                progress(count,total)
                return file.name
            for line in text.splitlines():
                if line.startswith('#EXT-X-MAP:'):
                    if 'BYTERANGE' in line:
                        raise ToolError('HLS init byte-range chưa được hỗ trợ.')
                    uri = attrs(line).get('URI')
                    if not uri:
                        raise ToolError('HLS thiếu init URI.')
                    output.append('#EXT-X-MAP:URI="'+save(uri)+'"')
                elif line.strip() and not line.startswith('#'):
                    output.append(save(line.strip()))
                else:
                    output.append(line)
            local = folder / 'local.m3u8'
            local.write_text('\n'.join(output),encoding='utf-8')
            local_inputs.append(local)
        result = root / 'result.mp4'
        command = [ffmpeg,'-nostdin','-v','error']
        for local in local_inputs:
            command += ['-protocol_whitelist','file,crypto,data','-allowed_extensions','ALL','-i',str(local)]
        command += ['-map','0:v:0','-map','1:a:0' if len(local_inputs)>1 else '0:a:0?', '-c','copy','-movflags','+faststart',str(result)]
        with (root/'ffmpeg.log').open('wb') as log:
            process = subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            try:
                while process.poll() is None:
                    if stop.wait(.2):
                        raise Cancelled('Đã dừng ghép MP4.')
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
        if process.returncode or not result.exists() or not result.stat().st_size:
            raise ToolError('FFmpeg không ghép được MP4; chưa lưu video hoàn chỉnh.')
        os.link(result,destination)
