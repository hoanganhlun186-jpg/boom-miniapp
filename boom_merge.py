"""Episode grouping, MP4 durations and synchronized SRT output."""
import os,re,shutil,struct,subprocess,tempfile,math
from collections import Counter,namedtuple
from pathlib import Path
from netshort_tool import ToolError,Cancelled

SRT_END_TOLERANCE_MS=2000

def mp4_duration(path):
    with Path(path).open('rb') as f:
        end=f.seek(0,2);f.seek(0)
        def boxes(stop):
            while f.tell()+8<=stop:
                begin=f.tell();size,kind=struct.unpack('>I4s',f.read(8));header=8
                if size==1:size=struct.unpack('>Q',f.read(8))[0];header=16
                if size==0:size=stop-begin
                if size<header or begin+size>stop:raise ValueError('Invalid MP4')
                if kind==b'moov':
                    value=boxes(begin+size)
                    if value:return value
                elif kind==b'mvhd':
                    raw=f.read(min(size-header,40));v=raw[0]
                    scale=struct.unpack('>I',raw[20:24] if v==1 else raw[12:16])[0]
                    duration=struct.unpack('>Q' if v==1 else '>I',raw[24:32] if v==1 else raw[16:20])[0]
                    if scale and duration:return round(duration*1000/scale)
                f.seek(begin+size)
        result=boxes(end)
    if not result:raise ValueError('MP4 has no duration')
    return result

def stamp(ms):
    seconds,milli=divmod(ms,1000);minutes,seconds=divmod(seconds,60);hours,minutes=divmod(minutes,60)
    return f'{hours:02}:{minutes:02}:{seconds:02},{milli:03}'

def merge_srt(paths,durations):
    if not paths or len(paths)!=len(durations):raise ToolError("Danh sách tập và thời lượng không khớp.")
    if any(isinstance(d,bool) or not isinstance(d,(int,float)) or not math.isfinite(d) or d<=0 for d in durations):raise ToolError("Thời lượng tập không hợp lệ.")
    durations=[round(d) for d in durations]
    cues=[];offset=0
    def parse(t):
        h,m,s,ms=map(int,re.split('[:,]',t));return ((h*60+m)*60+s)*1000+ms
    for path,duration in zip(paths,durations):
        text=Path(path).read_text(encoding='utf-8-sig').replace('\r\n','\n')
        found=False
        for block in re.split(r'\n\s*\n',text.strip()):
            match=re.search(r'(\d{2,}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2,}:\d{2}:\d{2},\d{3})[^\n]*\n([\s\S]+)',block)
            if not match:raise ToolError('SRT không hợp lệ; giữ các file tập rời.')
            start,end=parse(match[1]),parse(match[2]);found=True
            if not 0<=start<end:raise ToolError('Mốc thời gian SRT không hợp lệ; giữ các file tập rời.')
            # Providers commonly let the final cue extend slightly beyond the
            # actual MP4 duration. Only trim a small overrun; a larger difference
            # can indicate genuinely mismatched subtitles and must stay visible.
            if start>=duration:
                raise ToolError(f'{Path(path).name}: SRT bắt đầu sau cuối video {start-duration} ms; giữ SRT tập rời để kiểm tra.')
            if end-duration>SRT_END_TOLERANCE_MS:
                raise ToolError(f'{Path(path).name}: SRT dài hơn video {end-duration} ms; giữ SRT tập rời để kiểm tra.')
            cues.append(f'{len(cues)+1}\n{stamp(offset+start)} --> {stamp(offset+min(end,duration))}\n{match[3]}')
        if not found:raise ToolError('SRT rỗng; chưa gộp.')
        offset+=duration
    return '\n\n'.join(cues)+'\n'

def ffmpeg():
    local=Path(__file__).with_name('ffmpeg.exe')
    if local.exists():return str(local)
    found=shutil.which('ffmpeg')
    if found:return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:raise ToolError('Cần FFmpeg để gộp video.')

MediaSignature=namedtuple('MediaSignature','vcodec pix_fmt width height fps time_base acodec sample_rate channels')

def _rate(value):
    value=value.lower()
    return round(float(value[:-1])*1000) if value.endswith('k') else round(float(value))

def _parse_media_signature(text):
    video=next((line for line in text.splitlines() if 'Stream #' in line and ': Video:' in line and 'attached pic' not in line),None)
    if not video:raise ToolError('Không đọc được thông số video; giữ tập rời.')
    details=re.search(r'Video:\s*([^,\s]+)[^,]*,\s*([^,\s(]+)(?:\([^)]*\))?,\s*(\d{2,5})x(\d{2,5})',video)
    fps=re.search(r',\s*([0-9.]+)\s+fps',video)
    time_base=re.search(r',\s*([0-9.]+k?)\s+tbn',video,re.I)
    if not (details and fps and time_base):raise ToolError('Thông số FPS/time base không hợp lệ; giữ tập rời.')
    audio=next((line for line in text.splitlines() if 'Stream #' in line and ': Audio:' in line),None)
    acodec='';sample_rate=0;channels=''
    if audio:
        audio_details=re.search(r'Audio:\s*([^,\s]+)[^,]*,\s*(\d+)\s+Hz,\s*([^,]+)',audio)
        if not audio_details:raise ToolError('Không đọc được thông số âm thanh; giữ tập rời.')
        acodec=audio_details[1].lower();sample_rate=int(audio_details[2]);channels=audio_details[3].strip().lower()
    return MediaSignature(details[1].lower(),details[2].lower(),int(details[3]),int(details[4]),float(fps[1]),_rate(time_base[1]),acodec,sample_rate,channels)

def _probe_media(path,stop):
    if stop.is_set():raise Cancelled('Đã dừng gộp.')
    completed=subprocess.run([ffmpeg(),'-nostdin','-hide_banner','-i',str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if stop.is_set():raise Cancelled('Đã dừng gộp.')
    return _parse_media_signature(completed.stderr.decode('utf-8',errors='replace'))

def _channel_count(label):
    if label=='mono':return 1
    if label=='stereo':return 2
    match=re.match(r'(\d+)\.(\d+)',label)
    return sum(map(int,match.groups())) if match else None

def _concat_compatible(signature,target):
    # Every stream characteristic, including FPS and MP4 time base, must match so
    # the final stream is CFR and predictable for Telegram/mobile decoders.
    return signature==target

def _prepare_video(source,signature,target,destination,stop):
    video_encode=signature[:5]!=target[:5]
    audio_encode=signature[6:]!=target[6:]
    command=[ffmpeg(),'-nostdin','-v','error','-fflags','+genpts','-i',str(source),'-map','0:v:0']
    if target.acodec:command+=['-map','0:a:0']
    else:command+=['-an']
    if video_encode:
        command+=['-vf',f'scale={target.width}:{target.height},fps={target.fps:g}','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p','-fps_mode','cfr']
    else:command+=['-c:v','copy']
    command+=['-video_track_timescale',str(target.time_base)]
    if target.acodec:
        if audio_encode:
            command+=['-c:a','aac','-b:a','128k','-ar',str(target.sample_rate),'-af','aresample=async=1:first_pts=0']
            channels=_channel_count(target.channels)
            if channels:command+=['-ac',str(channels)]
        else:command+=['-c:a','copy']
    command+=['-avoid_negative_ts','make_zero','-movflags','+faststart',str(destination)]
    with destination.with_suffix('.log').open('wb') as log:
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            while process.poll() is None:
                if stop.wait(.15):raise Cancelled('Đã dừng gộp.')
            if process.returncode:raise ToolError('Không chuẩn hóa được một tập. File tập rời vẫn được giữ.')
        finally:
            if process.poll() is None:process.terminate();process.wait()

def join_video(paths,durations,output,stop,emit=None):
    if stop.is_set():raise Cancelled('Đã dừng gộp.')
    if not paths or len(paths)!=len(durations):raise ToolError('Danh sách tập và thời lượng không khớp.')
    if output.exists():raise ToolError('File gộp đã tồn tại, giữ nguyên: '+output.name)
    with tempfile.TemporaryDirectory(prefix='boom-merge-',dir=output.parent) as td:
        temp=Path(td)
        signatures=[_probe_media(path,stop) for path in paths]
        if emit:emit('log',f'Đã quét {len(paths)} tập; đang đối chiếu thông số ghép.')
        target=Counter(signatures).most_common(1)[0][0]
        # Telegram/mobile compatibility requires H.264 4:2:0 and AAC. If the
        # common source profile is already safe, preserve it and repair only the
        # outliers. Otherwise normalize the whole group to a conservative profile.
        if target.vcodec!='h264' or not target.pix_fmt.startswith('yuv420p') or target.acodec not in ('','aac'):
            dimensions=Counter((item.width,item.height) for item in signatures).most_common(1)[0][0]
            has_audio=any(item.acodec for item in signatures)
            target=MediaSignature('h264','yuv420p',*dimensions,30.0,90000,'aac' if has_audio else '',48000 if has_audio else 0,'stereo' if has_audio else '')
        prepared=[];encoded=remuxed=0
        for index,(path,signature) in enumerate(zip(paths,signatures),1):
            if _concat_compatible(signature,target):
                prepared.append(path)
                continue
            normalized=temp/f'normalized-{index:04}.mp4'
            if signature[:5]!=target[:5]:
                encoded+=1
                if emit:emit('log',f'Tập {index}: khác FPS/codec/khung hình, đang mã hóa lại…')
            else:
                remuxed+=1
                if emit:emit('log',f'Tập {index}: chỉ lệch time base/âm thanh, đang chuẩn hóa nhanh…')
            _prepare_video(path,signature,target,normalized,stop)
            if not _concat_compatible(_probe_media(normalized,stop),target):raise ToolError('Tập sau khi chuẩn hóa vẫn khác thông số; giữ tập rời.')
            prepared.append(normalized)
        if emit:emit('log',f'Chuẩn bị ghép: {encoded} tập mã hóa lại, {remuxed} tập chuẩn hóa nhanh, {len(paths)-encoded-remuxed} tập giữ nguyên.')
        listing=temp/'concat.txt'
        lines=['ffconcat version 1.0']
        for p,d in zip(prepared,durations):
            escaped=p.resolve().as_posix().replace("'","'\\''")
            lines.extend(["file '"+escaped+"'",f'duration {d/1000:.6f}'])
        listing.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        result=temp/'merged.mp4'
        with (temp/'ffmpeg.log').open('wb') as log:
            command=[
                ffmpeg(),'-nostdin','-v','error',
                '-f','concat','-safe','0','-i',str(listing),
                '-map','0:v:0','-map','0:a?',
                '-c','copy','-video_track_timescale',str(target.time_base),
                '-movflags','+faststart',str(result),
            ]
            process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                while process.poll() is None:
                    if stop.wait(.15):raise Cancelled('Đã dừng gộp.')
                if process.returncode:raise ToolError('Không gộp được video sau khi chuẩn hóa. File tập rời vẫn được giữ.')
            finally:
                if process.poll() is None:process.terminate();process.wait()
        if stop.is_set():raise Cancelled('Đã dừng gộp.')
        if abs(mp4_duration(result)-sum(durations))>250:raise ToolError('Thời lượng video gộp không khớp; giữ tập rời.')
        # Hard-link makes publishing exclusive and never overwrites an existing output.
        os.link(result,output)

def export_groups(records,episodes,total,title,target,mode,layout,chunk,stop,emit):
    if layout=='separate':return
    if layout not in ('all','parts') or chunk<1:raise ToolError('Kiểu gộp hoặc số tập mỗi phần không hợp lệ.')
    if not episodes:return
    ordered=sorted(episodes,key=lambda pair:int(pair[1].get('episodeNumber') or pair[1].get('episodeNo') or pair[0]+1))
    groups=[ordered] if layout=='all' else [ordered[i:i+chunk] for i in range(0,len(ordered),chunk)]
    for number,group in enumerate(groups,1):
        if stop.is_set():raise Cancelled('Đã dừng gộp.')
        label=('Trọn bộ' if len(ordered)==total else 'Các tập đã chọn') if layout=='all' else f'Phần {number}'
        if any(i not in records for i,_ in group):emit('log',f'{label}: thiếu tập tải thành công, không xuất file gộp.');continue
        data=[records[i] for i,_ in group]
        try:
            durations=[]
            for r in data:
                if r['video'].exists():duration=mp4_duration(r['video'])
                else:
                    raw=r.get('duration')
                    if isinstance(raw,str):
                        try:raw=float(raw)
                        except ValueError:pass
                    if isinstance(raw,bool) or not isinstance(raw,(int,float)) or not math.isfinite(raw) or raw<=0:raise ToolError('Thiếu thời lượng tập để căn SRT. Các file SRT rời được giữ.')
                    duration=round(raw*1000)
                durations.append(duration)
            stem=title+'_'+label
            subtitles=[];subtitle_error=None
            if mode!='Video':
                try:
                    tags=set().union(*(r['subs'] for r in data))
                    if not tags:raise ToolError('Không có SRT để gộp.')
                    for tag in sorted(tags):
                        if any(tag not in r['subs'] for r in data):raise ToolError(f'Thiếu SRT {tag} ở một số tập.')
                        merged=merge_srt([r['subs'][tag] for r in data],durations)
                        destination=target/(stem+'.'+tag+'.srt')
                        if destination.exists() and destination.read_text(encoding='utf-8-sig')!=merged:
                            raise ToolError(f'SRT gộp đã có nhưng nội dung không khớp: {destination.name}.')
                        subtitles.append((destination,merged))
                except (ToolError,ValueError,OSError) as error:
                    subtitle_error=error;subtitles=[]
            if mode!='Chỉ phụ đề':
                video_output=target/(stem+'.mp4')
                if video_output.exists():
                    if abs(mp4_duration(video_output)-sum(durations))>250:raise ToolError('Video gộp đã có nhưng thời lượng không khớp; chưa gộp SRT.')
                    emit('log','Giữ file đã có: '+video_output.name)
                else:join_video([r['video'] for r in data],durations,video_output,stop,emit)
            if subtitle_error:
                prefix='Video đã gộp nhưng SRT không gộp' if mode!='Chỉ phụ đề' else 'SRT không gộp'
                emit('log',f'{label}: {prefix}: {subtitle_error} Toàn bộ file lẻ được giữ nguyên.')
                continue
            for destination,merged in subtitles:
                if stop.is_set():raise Cancelled('Đã dừng gộp.')
                if destination.exists():continue
                with tempfile.TemporaryDirectory(prefix='boom-srt-',dir=target) as td:
                    staged=Path(td)/'merged.srt'
                    staged.write_text(merged,encoding='utf-8-sig')
                    os.link(staged,destination)
            if stop.is_set():raise Cancelled('Đã dừng gộp.')
            sources=set()
            for r in data:
                if mode!='Chỉ phụ đề':sources.add(r['video'])
                if mode!='Video':sources.update(r['subs'].values())
            for path in sources:path.unlink(missing_ok=True)
            emit('log','Đã gộp và xóa file lẻ: '+label)
        except Cancelled:raise
        except (ToolError,ValueError,OSError,struct.error) as error:emit('log',f'{label}: {error}')
