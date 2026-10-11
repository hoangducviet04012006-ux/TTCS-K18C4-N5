# Demo AgriTrace Sprint 1–3

Một bộ code chính: `D:\TTCS_K23C_N5\TTCS-K18C4-N5`. Backend và frontend được phục vụ cùng origin bởi launcher hiện có. Không cần chạy riêng `run_backend.bat`, `run_frontend.bat` hoặc launcher Recall.

## Chạy demo đã chuẩn bị

```powershell
cd D:\TTCS_K23C_N5\TTCS-K18C4-N5
.\start_demo.bat
```

Launcher bắt đầu tìm cổng tại 8765; database `.sprint123-trial/demo_sprint123.db`. Launcher in profile, đường dẫn code, database, URL và PID. Giao diện lấy profile/database từ `/demo-scope`. Không đưa mật khẩu vào màn hình khởi động hoặc log.

Nếu cổng bị chiếm, launcher báo PID và tự thử cổng tiếp theo (tối đa 100 cổng), không tắt hoặc dùng lại tiến trình. URL thực tế luôn được in ra và tự mở trong trình duyệt khi nhấp đúp start_demo.bat. Có thể chỉ định cổng bắt đầu tìm:

```powershell
.\start_demo.bat -Port 8769
```

Phiên kiểm thử mật khẩu/chọn nhanh đang dùng http://127.0.0.1:8766/ vì 8765 thuộc server cũ. Cùng một code và một database demo, không phải ứng dụng khác. Swagger ở `/docs`. Dừng đúng PID của demo vừa khởi chạy bằng `Stop-Process -Id <PID>`; không dừng PID server khác. Chế độ kiểm tra rồi dừng: `start_demo.bat -NoBrowser -StopAfterCheck -Port 8770`.

## Mật khẩu local và đăng nhập

Tám tài khoản demo hiện có đã được chuyển sang mật khẩu chung theo yêu cầu chủ dự án; không ghi giá trị vào tài liệu, giao diện hay mã ứng dụng. Cấu hình local đã được đồng bộ ở `.sprint123-trial/credentials.local`. File bị Git bỏ qua và ACL Windows chỉ cấp quyền cho người dùng đã tạo file. Mở riêng bằng Notepad, không chép vào Git, ảnh chụp, terminal ghi log hoặc tài liệu chia sẻ:

```powershell
notepad .\.sprint123-trial\credentials.local
```

Chọn nhanh một trong 8 tài khoản theo vai trò ngay trên màn hình đăng nhập; selector chỉ điền email, để trống mật khẩu. Nhập mật khẩu chung đã cấu hình; ô mật khẩu luôn được che. Có thể đối chiếu khóa `farm`, `packing`, ... trong file local với tài khoản dưới đây. Đăng xuất trước khi đổi vai trò; dùng cửa sổ riêng nếu cần hai bên bàn giao đồng thời.

| Khóa mật khẩu | Email | Vai trò | Tổ chức |
|---|---|---|---|
| farm | s123_farm@demo.local | farmer | HTX-DT |
| packing | s123_packing@demo.local | processor | HTX-DT |
| receiver | s123_receiver@demo.local | processor | HTX-TG |
| transport | s123_transport@demo.local | transporter | HTX-TG |
| distribution | s123_distribution@demo.local | distributor | DN-XNK |
| inspector | s123_inspector@demo.local | inspector | Toàn cảnh nghiệp vụ |
| admin | s123_admin@demo.local | system_admin | HTX-DT |
| org_admin | s123_org_admin@demo.local | org_admin | HTX-DT |

Đây là **8 tài khoản, 7 vai trò khác nhau**: hai processor cần cho hai tổ chức. `system_admin` không được tự động cấp quyền thu hoạch/tách/gộp. Tài khoản `demo_admin@demo.local` thuộc database gốc, không dùng cho demo này. Actor fixture không hoạt động, không phải tài khoản đăng nhập.

Mật khẩu được băm trong database. Sửa file local sau khi đã tạo database không đổi mật khẩu đăng nhập. Nếu mất file hoặc quên mật khẩu, dừng và yêu cầu phương án xử lý; launcher không reset, đổi mật khẩu hoặc seed lại. Không chạy `scripts/seed_demo.bat` cho môi trường này.

## Chuẩn bị đúng một lần (đã thực hiện)

Chỉ dùng lệnh dưới đây khi database demo chưa tồn tại:

```powershell
cd backend
.\.venv\Scripts\python.exe -m scripts.run_sprint123_demo --db ..\.sprint123-trial\demo_sprint123.db --prepare-only
```

Dữ liệu tổng hợp được dựng trong RAM rồi ghi vào file mới theo chế độ độc quyền, không sao chép `backend/ttcs.db`. Schema mới có session và hash-chain, không có bảng Recall. Mật khẩu local được tạo một lần; không truyền mật khẩu trong tham số dòng lệnh. Nếu database đã tồn tại, chỉ kiểm tra đọc, không seed/ghi đè. Khởi động bình thường không gọi chuẩn bị dữ liệu: thiếu database, marker sai hoặc schema không tương thích thì báo lỗi và dừng, không migration tự động.

## Demo từng bước

1. Xác nhận banner **DEMO SPRINT 1–3** và đúng `demo_sprint123.db` trước khi đăng nhập.
2. `farm`: tạo vùng trồng (tên, địa điểm, diện tích, tọa độ, chủ vùng), rồi thu hoạch lô 100 kg; kiểm tra mã lô và sự kiện thu hoạch.
3. `farm`: tách lô thành hai lô 30 kg; lô cha còn 40 kg. Xem quan hệ cha/con, không chỉnh sửa sự kiện cũ.
4. `packing`: chọn hai lô con, gộp mỗi lô 20 kg thành lô mới 40 kg; mỗi lô con còn 10 kg.
5. `packing`: mở bàn giao lô gộp sang HTX-TG. `receiver`: nhận trong mục bàn giao chờ xác nhận, kiểm tra chủ sở hữu mới. Lô chỉ chuyển tổ chức sau khi nhận.
6. `receiver`: mở chi tiết lô, tab phả hệ truy ngược về cả hai lô con và lô thu hoạch; tab lịch sử kiểm tra hash-chain hợp lệ.
7. `inspector`: xem lô nhiều tổ chức và truy ngược. Các vai trò hoạt động chỉ thấy dữ liệu trong phạm vi backend cho phép; thử gọi API trái tổ chức sẽ bị từ chối.
8. `admin` / `org_admin`: kiểm tra màn hình quản trị theo quyền. Không đổi mật khẩu/xóa tài khoản chỉ để demo.

Có thể bàn giao trước rồi tách/gộp tại tổ chức nhận nếu dùng đúng vai trò đang giữ lô. Các thao tác demo thêm dữ liệu vào database demo và được giữ qua lần khởi động sau. Không có reset tự động. Recall được giữ nguyên trong code, ẩn trong profile Sprint 1–3 và không triển khai thêm.

## Kiểm thử an toàn

Backend, tại `backend`, đặt `DATABASE_URL=sqlite:///:memory:` và `TTCS_ENV=test` trước khi chạy `.venv/Scripts/python.exe -m pytest -q`; fixtures dùng database thử nghiệm riêng.

Browser: `docs/qa/sprint123_browser_check.cjs`, cần Playwright và Chrome/Edge đã cài, đặt `DEMO_BASE_URL` rõ ràng. Script xác minh profile và tên database trước đăng nhập; đọc mật khẩu từ file local, không in mật khẩu. Nó thêm dữ liệu demo, không dùng database gốc.

`backend/ttcs.db`, các database trial cũ và backup được giữ nguyên. Các hướng dẫn launcher hai cổng, seed hoặc Docker cũ trong tài liệu khác không phải quy trình demo chuẩn này.

## Điều hướng Dashboard

Sau đăng nhập, chọn màn hình ở Sidebar: Tổng quan, Vùng trồng, Lô nông sản, Tiếp nhận bàn giao, Truy xuất nguồn gốc hoặc Nhật ký sự kiện. Chỉ màn hình đang chọn được hiển thị; Back/Forward và URL hash được hỗ trợ. Form vùng trồng nằm ở Vùng trồng; thu hoạch/tách/gộp/bàn giao nằm ở Lô nông sản. Truy xuất và nhật ký có ô chọn lô riêng; modal chi tiết cũ vẫn sử dụng được. Menu quản trị/tiếp nhận được hiển thị theo quyền. Xem [báo cáo và ảnh giao diện](FRONTEND_DASHBOARD_REPORT.md).
