# BOOM miniapp — Nuitka standalone và cập nhật tự động

Upload nội dung bộ này vào gốc repository boom-miniapp, gồm .github. Không upload bộ OWNER hoặc khóa riêng.

## Một lần đầu
Thêm GitHub Actions Secret BOOM_SIGNING_KEY_XML theo hướng dẫn trong bộ OWNER. Trên VPS cài bộ SERVER và cấu hình repository BOOM. Link ZIP GitHub Release phải tải công khai được.

## Publish
Clone repository về máy bằng GitHub Desktop; thư mục giải nén ZIP không phải repository Git. Chép mã mới vào bản clone, giữ VERSION hiện hành trong boom_update_core.py. Chạy publish_tool_boom.py: bấm Publish để tăng số cuối, commit, tạo tag và push. Workflow build theo tag v*, ký và đưa ZIP lên Releases. Chạy thủ công lần đầu bằng Actions > Run workflow cũng được.

GitHub giữ ZIP, server chỉ cập nhật link/phiên bản khoảng 2 phút/lần. Khách mở app: tự tải bản mới từ GitHub, giải nén và mở lại. Không có bước ký/phát hành VPS thủ công sau khi đã cấu hình.

Kết quả standalone gồm BOOM miniapp.exe, FFmpeg và thư viện; giữ nguyên cả thư mục. VERSION cũng hiển thị trong app. Source và cấu hình đã kiểm thử; chưa có EXE build thực tế trong bộ ZIP này.
