"""Create signed update assets on GitHub's Windows runner."""
import base64,hashlib,json,os,subprocess,tempfile,zipfile
from pathlib import Path
from boom_update_core import VERSION,APP_ID,verify,archive_files

def main():
 root=Path(__file__).resolve().parent
 source=root/'build/netshort_studio.dist';out=root/'release-assets';out.mkdir(exist_ok=True)
 marker=json.loads((source/'boom-release.json').read_text())
 if marker!={'app':APP_ID,'version':VERSION}:raise ValueError('Wrong build version')
 ref=os.environ.get('GITHUB_REF','')
 if ref.startswith('refs/tags/') and ref!='refs/tags/v'+VERSION:raise ValueError('Tag and VERSION differ')
 package=out/'BOOM-miniapp-update.zip'
 with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
  for p in sorted(source.rglob('*')):
   if p.is_file():z.write(p,p.relative_to(source))
 archive_files(package)
 with package.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
 repo=os.environ.get('GITHUB_REPOSITORY','')
 import re
 if not re.fullmatch(r'[A-Za-z0-9_.-]+/boom-miniapp',repo):raise ValueError('Wrong BOOM GitHub repository')
 download_url='https://github.com/'+repo+'/releases/download/v'+VERSION+'/BOOM-miniapp-update.zip'
 payload=json.dumps({'download_url':download_url,'app':APP_ID,'version':VERSION,'size':package.stat().st_size,'sha256':digest,'notes':'BOOM miniapp '+VERSION},separators=(',',':')).encode()
 key=os.environ.get('BOOM_SIGNING_KEY_XML','')
 if not key:raise ValueError('Missing GitHub secret BOOM_SIGNING_KEY_XML')
 with tempfile.TemporaryDirectory() as td:
  td=Path(td);(td/'key.xml').write_text(key,encoding='utf-8');(td/'payload').write_bytes(payload)
  subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'sign_release.ps1'),'-Payload',str(td/'payload'),'-Key',str(td/'key.xml'),'-Signature',str(td/'signature')],check=True)
  envelope={'payload':base64.b64encode(payload).decode(),'signature':base64.b64encode((td/'signature').read_bytes()).decode()}
  verify(envelope)
 (out/'boom-manifest.json').write_text(json.dumps(envelope),encoding='utf-8')
 print('Signed release v'+VERSION)

if __name__=='__main__':main()
