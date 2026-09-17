"""Bounded concurrent episode downloads using the existing media functions."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path
import re
import threading
import netshort_tool as engine
from studio_files import safe_name, episode_stem


def start(backend):
    if backend.busy:return
    selected=list(dict.fromkeys(int(i) for i in backend.tree.selection()))
    if not selected or not backend.scanned:return
    base,language,sid=backend.scanned
    key=backend.key.get()
    provider=backend.scanned_provider
    folder=backend.folder.get()
    title=safe_name(backend.scanned_title or sid,sid)
    mode=backend.download_mode.get()
    wanted=backend.subtitle_language.get()
    layout=backend.output_layout.get()
    chunk=int(backend.group_size.get())
    total_episodes=max([len(backend.items)]+[ep.get('_series_total',0) for ep in backend.items])
    workers=int(backend.download_workers.get())
    if workers not in (3,5,10):workers=3
    episodes=[(i,dict(backend.items[i])) for i in selected]

    def job():
        target=Path(folder).expanduser()/title
        # Two distinct records must never write the same path concurrently.
        names=[episode_stem(title,ep,i).casefold() for i,ep in episodes]
        if len(set(names))!=len(names):raise engine.ToolError('Danh sách có số tập trùng nhau. Hãy chọn riêng từng tập để tải.')
        target.mkdir(parents=True,exist_ok=True)
        lock=threading.Lock()
        records={}
        fractions={i:0.0 for i,_ in episodes}
        totals={'success':0,'failed':0,'cancelled':0}
        def progress(i,ratio):
            with lock:
                fractions[i]=max(fractions[i],min(1,max(0,ratio)))
                backend.emit('progress',100*sum(fractions.values())/len(episodes))

        def one(i,ep):
            if backend.stop.is_set():return 'cancelled'
            try:
                backend.emit('status',i,'Đang lấy nguồn…')
                api=engine.API(base,key,language,backend.stop,provider)
                payload={'data':ep} if provider!='netshort' else api.get(f'/api/netshort/episodes/{sid}/{ep["id"]}/source')
                if backend.stop.is_set():raise engine.Cancelled('Đã dừng.')
                candidates=engine.source_candidates(payload)
                if not candidates and mode!='Chỉ phụ đề':raise engine.ToolError('Nguồn chưa cấp link video cho tập này.')
                source=candidates[0] if candidates else {}
                backend.emit('status',i,'Đang tải…')
                def on_progress(done,total):
                    # Reserve the last portion for subtitle writes/completion.
                    progress(i,.95*done/total if total else 0)
                    if source.get('type') in ('m3u8','hls') or '.m3u8' in source.get('url',''):
                        state=f'HLS: {done}/{total} đoạn'
                    else:state=f'{done/1048576:.1f} MB'+(f' / {total/1048576:.1f} MB' if total else '')
                    backend.emit('status',i,state)
                stem=episode_stem(title,ep,i)
                video_path=target/(stem+'.mp4')
                if mode!='Chỉ phụ đề':
                    if video_path.exists():backend.emit('log',f'{stem}: video đã có, giữ file hiện tại.')
                    else:engine.download(source,video_path,backend.stop,on_progress)
                if backend.stop.is_set():raise engine.Cancelled('Đã dừng.')
                count=0
                saved_subs={}
                if mode!='Video':
                    chosen=[track for track in engine.subtitle_tracks(payload) if engine.language_matches(track['language'],wanted)]
                    if not chosen:backend.emit('log',f'{stem}: không có phụ đề khớp ngôn ngữ đã chọn.')
                    duplicates={}
                    for track in chosen:
                        if backend.stop.is_set():raise engine.Cancelled('Đã dừng.')
                        tag=('vi' if track['language'].lower().replace('_','-').split('-')[0]=='vi' else re.sub(r'[^A-Za-z0-9_-]','_',track['language'])[:30]) or 'und'
                        if tag=='vi' and tag in saved_subs:continue
                        duplicates[tag]=duplicates.get(tag,0)+1
                        suffix='' if duplicates[tag]==1 else f'.{duplicates[tag]}'
                        sub_path=target/f'{stem}.{tag}{suffix}.srt'
                        try:
                            if not sub_path.exists():
                                with engine.fetch(track['url'],stop=backend.stop) as response:
                                    text=engine.as_srt(engine.limited_read(response))
                                with sub_path.open('x',encoding='utf-8-sig') as output:output.write(text)
                            count+=1
                            saved_subs[tag+suffix]=sub_path
                        except engine.Cancelled:raise
                        except Exception as error:
                            reason=str(error) if isinstance(error,(engine.ToolError,ValueError)) else type(error).__name__
                            backend.emit('log',f'{stem}: lỗi phụ đề {tag}: {reason}')
                    backend.emit('log',f'{stem}: {count} file SRT.')
                if mode=='Chỉ phụ đề' and not count:raise engine.ToolError('Nguồn chưa cấp SRT theo ngôn ngữ đã chọn.')
                raw=payload.get('data',{})
                duration=(raw.get('extra') or {}).get('duration') or raw.get('duration') or (ep.get('extra') or {}).get('duration') or ep.get('duration')
                with lock:records[i]={'video':video_path,'subs':saved_subs,'duration':duration}
                backend.emit('status',i,'Đã tải')
                return 'success'
            except engine.Cancelled:
                backend.emit('status',i,'Đã dừng')
                return 'cancelled'
            except Exception as error:
                message=str(error) if isinstance(error,engine.ToolError) else f'Lỗi {type(error).__name__}; tải chưa hoàn tất.'
                backend.emit('status',i,message)
                backend.emit('log',f'Tập {ep.get("episodeNumber") or ep.get("episodeNo") or i+1}: {message}')
                if any(code in message for code in ('HTTP 401','HTTP 403','HTTP 429')):backend.stop.set()
                return 'failed'

        backend.emit('log',f'Bắt đầu tải {len(episodes)} tập • tối đa {workers} tập đồng thời.')
        remaining=iter(episodes);submitted=set()
        with ThreadPoolExecutor(max_workers=workers,thread_name_prefix='boom-download') as pool:
            pending={}
            def fill():
                while len(pending)<workers and not backend.stop.is_set():
                    try:i,ep=next(remaining)
                    except StopIteration:break
                    submitted.add(i);pending[pool.submit(one,i,ep)]=i
            fill()
            while pending:
                finished,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in finished:
                    i=pending.pop(future)
                    outcome=future.result();totals[outcome]+=1
                    if outcome!='cancelled':progress(i,1)
                fill()
                backend.emit('batch',totals['success'],len(episodes),len(pending),totals['failed'])
        for i,_ in episodes:
            if i not in submitted:backend.emit('status',i,'Chưa tải — đã dừng')
        if layout!='separate' and not backend.stop.is_set():
            from boom_merge import export_groups
            backend.emit('log','Đang gộp video/phụ đề…')
            export_groups(records,episodes,total_episodes,title,target,mode,layout,chunk,backend.stop,backend.emit)
        backend.emit('log',f'Kết thúc: {totals["success"]} thành công, {totals["failed"]} lỗi, {len(episodes)-totals["success"]-totals["failed"]} chưa hoàn tất. Thư mục: {target}')
    backend.launch(job)
