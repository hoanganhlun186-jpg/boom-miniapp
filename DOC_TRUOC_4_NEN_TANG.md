# BOOM miniapp — 4 nền tảng — 16/09/2026

NetShort, DramaWave, ShortMax và DramaBox dùng chung giao diện tìm phim, poster, chọn tập, tải MP4/HLS, quét SRT, gộp hoặc chia phần.
Giữ Video + SRT / Chỉ video / Chỉ SRT, tải đồng thời 3/5/10 tập và đuôi .vi.srt.

## Cài đặt
Cập nhật SERVER bằng thư mục SERVER trong ZIP trước, rồi khởi động lại dịch vụ server.
CLIENT: giải nén riêng, chạy CAI_DAT.bat rồi BOOM miniapp.bat. Đây là mã nguồn, chưa phải EXE.
Khi đưa vào repository GitHub, chép nội dung CLIENT (gồm .github) vào gốc repository.
Giữ quy trình tăng phiên bản và Publish hiện có; chưa push hay phát hành tự động từ bộ này.

## Sử dụng
Chọn nền tảng bên trái, bấm Đề xuất hoặc nhập tên phim/ID phim để tìm.
ShortMax và DramaBox dùng mã nội dung vi đã xác nhận từ endpoint langs.
Không phải mọi link chia sẻ đều chứa ID; nếu app không đọc được link, tìm theo tên phim.
Chọn tập và nội dung tải; nếu không có phụ đề riêng từ nguồn, chọn Chỉ video.
API không trả SRT thì app không thể tự tạo SRT từ phụ đề đã chèn trong hình.

## Giới hạn đã xác nhận
- ShortMax: phim mẫu API trả 50/125 tập, không có cursor để lấy tiếp; tăng limit cũng chỉ trả 50. App hiển thị số tập được cấp/tổng số và chỉ gộp thành Các tập đã chọn, không gọi đó là Trọn bộ.
- DramaBox: home, search và một danh sách 50 tập có phản hồi. Tên miền video của phim mẫu không phân giải DNS trên máy kiểm tra. Một phim khác trả lỗi upstream HTTP 502 qua mã HTTP 400; endpoint detail cũng có lỗi upstream. Chưa xác nhận tải video DramaBox thực tế. Các lỗi nguồn này không được bỏ qua hay thay bằng video giả.
- Phim mẫu của hai nền tảng chưa trả track SRT riêng. Luồng SRT đã được kiểm thử bằng dữ liệu mô phỏng đúng cấu trúc, không có nghĩa mọi phim có phụ đề để tải.

## Kiểm thử
17 kiểm thử CLIENT qua; kiểm thử server về tài khoản, đăng nhập, khóa/hết hạn, giới hạn đường dẫn và proxy hai nền tảng qua. Công cụ cập nhật server được thử trên bản sao, kiểm tra sao lưu và chạy lặp không sửa thêm.
Đã tải thực tế một tập ShortMax HLS và remux MP4 thành công (9.328.616 byte).
Đã kiểm tra giao diện 1160x780; giữ bốn nút nền tảng và nút tải nhìn thấy được.
Chưa build EXE, chưa triển khai VPS hoặc phát hành GitHub.

Tài liệu: https://api.ezvid.net/docs#tag/shortmax-api và https://api.ezvid.net/docs#tag/dramabox-api
