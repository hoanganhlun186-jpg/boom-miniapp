# BOOM miniapp — build EXE bằng Nuitka

Bộ CLIENT v2.4, build Windows x64 dạng thư mục standalone, không onefile.

## Đưa lên GitHub
1. Giải nén ZIP nguồn này.
2. Upload toàn bộ nội dung vào gốc repository, gồm cả thư mục `.github`. Không upload nguyên ZIP và không đặt code trong thư mục con.
3. Kiểm tra trên GitHub có `.github/workflows/build.yml` và `netshort_studio.py` ở đúng vị trí.
4. Mở Actions → Build BOOM miniapp Windows → Run workflow. Khi push lên main/master cũng tự build.
5. Khi build xanh, mở lượt chạy → Artifacts → tải BOOM-miniapp-Windows-x64.
6. Giải nén toàn bộ ZIP tải về, chạy BOOM miniapp.exe. Giữ tất cả DLL, thư mục và ffmpeg.exe cạnh EXE.

Không cần API key hoặc mật khẩu trong GitHub Secrets để build. Người dùng đăng nhập khi chạy app. Server phải được cập nhật đường detail của bản v2.4 để lấy đúng poster DramaWave.

Đây là bộ nguồn và cấu hình build, chưa phải EXE đã biên dịch. Build lỗi thì gửi phần log màu đỏ trong Actions để kiểm tra.

## Build trên máy Windows
Cài Python 3.11 x64 và Visual Studio Build Tools (Desktop development with C++).
Chạy `python -m pip install -r requirements.txt nuitka ordered-set zstandard`, sau đó `python build_standalone.py`.
Kết quả: `build/netshort_studio.dist/`.
