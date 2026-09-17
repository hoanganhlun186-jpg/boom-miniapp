"""Client transport. Contains no Ezvid key and only talks to the configured server."""
import http.client
import json
import re
from urllib.parse import urlsplit, urlencode

SERVER_URL = 'http://163.61.182.119:8000'


def request_json(base,path,token='',body=None,stop=None,timeout=35):
    from netshort_tool import ToolError, Cancelled
    parsed=urlsplit(base)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ToolError('Địa chỉ server phải chỉ gồm http(s)://host:port.')
    if stop and stop.is_set():raise Cancelled('Đã dừng.')
    cls=http.client.HTTPSConnection if parsed.scheme=='https' else http.client.HTTPConnection
    conn=cls(parsed.hostname,parsed.port,timeout=timeout)
    headers={'Accept':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    raw=None
    if body is not None:raw=json.dumps(body).encode('utf-8');headers['Content-Type']='application/json'
    try:
        conn.request('POST' if body is not None else 'GET',path,body=raw,headers=headers)
        reply=conn.getresponse();data=reply.read(8*1024*1024+1)
        if len(data)>8*1024*1024:raise ToolError('Dữ liệu server quá lớn.')
        try:payload=json.loads(data)
        except (ValueError,UnicodeDecodeError):raise ToolError('Dịch vụ tạm thời chưa sẵn sàng. Vui lòng liên hệ hỗ trợ.') from None
        if not 200<=reply.status<300:
            detail=payload.get('detail','Yêu cầu server thất bại.') if isinstance(payload,dict) else 'Yêu cầu thất bại.'
            if not isinstance(detail,str):detail='Thông tin nhập chưa hợp lệ.'
            detail=re.sub(r'https?://\S+','[địa chỉ kết nối]',detail)
            detail=re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b','[địa chỉ kết nối]',detail)
            raise ToolError(f'HTTP {reply.status}: {detail}')
        if not isinstance(payload,dict):raise ToolError('Dữ liệu server không hợp lệ.')
        return payload
    except (OSError,http.client.HTTPException):raise ToolError('Không kết nối được server. Kiểm tra mạng hoặc thử lại sau.') from None
    finally:conn.close()


class GatewayTransport:
    def __init__(self,base,key,language,stop,provider='netshort'):
        from netshort_tool import ToolError
        if not key:raise ToolError('Bạn cần đăng nhập BOOM miniapp.')
        self.base,self.key,self.language,self.stop,self.provider=base.rstrip('/'),key,language,stop,provider

    def get(self,path,params=None):
        from netshort_tool import ToolError
        match=re.fullmatch(r'/api/(netshort|dramawave|shortmax|dramabox)/(.+)',path)
        if not match:raise ToolError('Đường dẫn API không hợp lệ.')
        query=dict(params or {})
        if self.language:query['language']=self.language
        target='/api/boommini/proxy/'+match[1]+'/'+match[2]
        if query:target+='?'+urlencode(query)
        return request_json(self.base,target,self.key,stop=self.stop)
