"""Build on Windows with Python 3.11 and MSVC installed."""
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build this app on Windows.')
    root=Path(__file__).resolve().parent
    os.chdir(root)
    for path in root.glob('*.py'):
        ast.parse(path.read_text(encoding='utf-8-sig'))
    subprocess.run([sys.executable,'-c','from studio_qt import MainWindow; from boom_login import LoginDialog; import parallel_downloads'],check=True)
    command=[sys.executable,'-m','nuitka','--mode=standalone',
        '--enable-plugin=pyqt6','--enable-plugin=tk-inter',
        '--include-qt-plugins=sensible','--windows-console-mode=disable',
        '--msvc=latest','--assume-yes-for-downloads','--output-dir=build',
        '--output-filename=BOOM miniapp.exe','--include-data-dir=icons=icons',
        '--include-data-files=boom.svg=boom.svg','--include-data-files=check.svg=check.svg',
        '--report=build/compilation-report.xml','netshort_studio.py']
    subprocess.run(command,check=True)
    output=root/'build'/'netshort_studio.dist'
    import imageio_ffmpeg
    shutil.copy2(imageio_ffmpeg.get_ffmpeg_exe(),output/'ffmpeg.exe')
    (output/'HUONG_DAN.txt').write_text('Giai nen toan bo thu muc. Mo BOOM miniapp.exe de dang nhap. Khong tach rieng file EXE. Khong can cai Python.\n',encoding='utf-8')
    for name in ('BOOM miniapp.exe','ffmpeg.exe','boom.svg','check.svg'):
        if not (output/name).is_file():raise RuntimeError('Missing build output: '+name)
    subprocess.run([str(output/'ffmpeg.exe'),'-version'],check=True,stdout=subprocess.DEVNULL)
    print('Ready:',output)

if __name__=='__main__':main()
