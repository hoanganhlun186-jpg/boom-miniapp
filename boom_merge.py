"""Episode grouping, MP4 durations and synchronized SRT output."""
import os,re,shutil,struct,subprocess,tempfile,math
from pathlib import Path
from netshort_tool import ToolError,Cancelled

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
            if not (0<=start<min(end,duration) and end<=duration+100):raise ToolError('Thời gian SRT vượt video; chưa gộp để tránh lệch phụ đề.')
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

def join_video(paths,durations,output,stop):
    if stop.is_set():raise Cancelled('Đã dừng gộp.')
    if not paths or len(paths)!=len(durations):raise ToolError('Danh sách tập và thời lượng không khớp.')
    if output.exists():raise ToolError('File gộp đã tồn tại, giữ nguyên: '+output.name)
    with tempfile.TemporaryDirectory(prefix='boom-merge-',dir=output.parent) as td:
        temp=Path(td);listing=temp/'concat.txt'
        lines=['ffconcat version 1.0']
        for p,d in zip(paths,durations):
            escaped=p.resolve().as_posix().replace("'","'\\''")
            lines.extend(["file '"+escaped+"'",f'duration {d/1000:.6f}'])
        listing.write_text('\n'.join(lines)+'\n',encoding='utf-8')
        result=temp/'merged.mp4'
        with (temp/'ffmpeg.log').open('wb') as log:
            process=subprocess.Popen([ffmpeg(),'-nostdin','-v','error','-f','concat','-safe','0','-i',str(listing),'-map','0:v:0','-map','0:a?','-c','copy','-movflags','+faststart',str(result)],stdout=subprocess.DEVNULL,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                while process.poll() is None:
                    if stop.wait(.15):raise Cancelled('Đã dừng gộp.')
                if process.returncode:raise ToolError('Không gộp được video; các tập có thể khác định dạng. File tập rời vẫn được giữ.')
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
            subtitles=[]
            if mode!='Video':
                tags=set().union(*(r['subs'] for r in data))
                if not tags:raise ToolError('Không có SRT để gộp; giữ file rời.')
                for tag in sorted(tags):
                    if any(tag not in r['subs'] for r in data):raise ToolError(f'Thiếu SRT {tag} ở một số tập; giữ file rời.')
                    merged=merge_srt([r['subs'][tag] for r in data],durations)
                    destination=target/(stem+'.'+tag+'.srt')
                    if destination.exists() and destination.read_text(encoding='utf-8-sig')!=merged:
                        raise ToolError(f'SRT gộp đã có nhưng nội dung không khớp: {destination.name}; giữ file rời.')
                    subtitles.append((destination,merged))
            if mode!='Chỉ phụ đề':
                video_output=target/(stem+'.mp4')
                if video_output.exists():
                    if abs(mp4_duration(video_output)-sum(durations))>250:raise ToolError('Video gộp đã có nhưng thời lượng không khớp; chưa gộp SRT.')
                    emit('log','Giữ file đã có: '+video_output.name)
                else:join_video([r['video'] for r in data],durations,video_output,stop)
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
