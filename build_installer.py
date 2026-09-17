"""Compile the first-install Setup EXE from the same verified standalone build."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from boom_update_core import VERSION, APP_ID

def main():
    root=Path(__file__).resolve().parent
    source=root/'build'/'netshort_studio.dist'
    marker=json.loads((source/'boom-release.json').read_text(encoding='utf-8-sig'))
    if marker!={'app':APP_ID,'version':VERSION}:raise ValueError('Installer version differs from standalone build')
    for name in ('BOOM miniapp.exe','ffmpeg.exe','boom_update_public.json'):
        if not (source/name).is_file():raise ValueError('Missing standalone file: '+name)
    compiler=shutil.which('ISCC.exe')
    if not compiler:
        candidate=Path(os.environ.get('ProgramFiles(x86)',r'C:\Program Files (x86)'))/'Inno Setup 6'/'ISCC.exe'
        if candidate.is_file():compiler=str(candidate)
    if not compiler:raise RuntimeError('Inno Setup 6 ISCC.exe is missing from the Windows runner')
    output=root/'release-assets';output.mkdir(exist_ok=True)
    subprocess.run([compiler,'/DSourceDir='+str(source),'/DAppVersion='+VERSION,'/O'+str(output),str(root/'BOOM_miniapp_Setup.iss')],check=True)
    setup=output/('BOOM-miniapp-Setup-'+VERSION+'.exe')
    if not setup.is_file() or setup.stat().st_size==0:raise RuntimeError('Installer was not created')
    print('Installer ready: '+setup.name)

if __name__=='__main__':main()
