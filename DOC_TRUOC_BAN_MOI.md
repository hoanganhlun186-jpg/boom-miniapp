# BOOM miniapp — bản hoàn thiện tải và gộp ngày 16/09/2026

Đây là bộ mã nguồn CLIENT tiếp tục từ work/client_bundle, có kèm bộ build/phát hành GitHub của AUTO DIRECT UPDATE. Không phải bản EXE đã build.

## Chạy trên máy
Giải nén vào thư mục mới. Chạy CAI_DAT.bat để cài PyQt6, Pillow và imageio-ffmpeg (cần Internet), rồi chạy BOOM miniapp.bat. FFmpeg được lấy từ imageio-ffmpeg, ffmpeg.exe cạnh ứng dụng hoặc PATH.

## Tải và gộp
1. Mở phim và chọn tập. Bấm Tất cả nếu muốn trọn bộ.
2. Chọn Video + SRT, Chỉ video hoặc Chỉ SRT. Với SRT, chọn ngôn ngữ.
3. Chọn Từng tập rời, Gộp thành một file hoặc Chia phần; nhập số tập mỗi phần.
4. Chọn thư mục và bấm Tải tập đã chọn. Số tải đồng thời vẫn là 3/5/10.

Ví dụ: Tên phim_tập 1.vi.srt; Tên phim_Trọn bộ.vi.srt; Tên phim_Phần 1.vi.srt. Tiếng Việt luôn dùng .vi.srt.

Gộp áp dụng cho các tập đã chọn, sắp theo số tập. Nếu chọn một phần danh sách, file gộp mang tên Các tập đã chọn. Chia phần chia danh sách đã chọn theo số tập mỗi phần. Các tập rời được giữ lại.

SRT gộp cộng thời lượng từng MP4; khi Chỉ SRT và không có MP4, dùng duration (giây) từ dữ liệu nguồn. Nếu thiếu thời lượng, thiếu tập tải thành công hoặc thiếu phụ đề cùng ngôn ngữ, app báo trong nhật ký và giữ file rời. Không tự suy ra thời lượng từ câu phụ đề cuối. Nguồn không cấp video/SRT thì app không tải được nội dung đó.

File đã có được giữ nguyên. Khi video gộp đã có và thời lượng phù hợp, app vẫn có thể bổ sung SRT gộp. Khi nguồn video khác định dạng hoặc thời lượng không khớp, kiểm tra nhật ký; không coi đó là bản gộp hoàn chỉnh.

## GitHub
Bộ này kèm .github/workflows/build.yml, build_standalone.py và các công cụ phát hành cũ. Bản build đóng kèm ffmpeg.exe. Chưa push GitHub, chưa phát hành hoặc đổi server. Số VERSION giữ nguyên từ mã nguồn; khi phát hành tiếp hãy dùng số phiên bản mới hơn bản đang phát hành trong repository của bạn.

## Kiểm thử
Đã qua syntax, import, 12 kiểm thử tự động về giao diện và xử lý tải/gộp, cộng kiểm tra thực tế FFmpeg: tạo hai MP4 1 giây có âm thanh, gộp và giải mã toàn bộ kết quả thành công (2,022 giây). Đã xem bố cục giao diện với Chỉ SRT / Chia phần.
Chưa thử tải qua API thật, build EXE hoặc cập nhật trên VPS/máy khách.
