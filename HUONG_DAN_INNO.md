# BOOM: GitHub tự tạo Setup.exe

Chép toàn bộ nội dung bộ này vào Documents/GitHub/boom-miniapp, chọn thay thế file trùng. Giữ đúng đường dẫn .github/workflows/build.yml, không đặt build.yml ở thư mục gốc.
Mở publish_tool_boom.py tại repository, bấm Nâng cấp & Phát hành ngay.

GitHub build ứng dụng, ký ZIP cập nhật, tạo bộ cài Inno, rồi phát hành cùng Release:
- BOOM-miniapp-Setup-<phiên bản>.exe: gửi khách mới.
- BOOM-miniapp-update.zip và boom-manifest.json: dùng cho updater hiện có.

Khách mở Setup, cài vào LocalAppData/Programs/BOOM miniapp, tạo shortcut Desktop và mở ứng dụng. Không cần Python hoặc quyền quản trị.
Không cần thay server hay nhập lại Secret. Không chạy lại job v1.0.1 cũ để áp dụng workflow mới; cần Publish bản mới.

Đã kiểm tra syntax Python, quy tắc Publish và biên dịch Inno với bộ dữ liệu thử; chưa chạy workflow mới trên GitHub, chưa thử cài bộ EXE BOOM thực tế. Setup.exe chưa có chữ ký Authenticode; chữ ký ZIP cập nhật vẫn theo luồng hiện có.
