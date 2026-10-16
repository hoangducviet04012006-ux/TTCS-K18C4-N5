# Demo AgriTrace Sprint 1–3 — Bối cảnh Miền Bắc

Một bộ code chính: `D:\TTCS_K23C_N5\TTCS-K18C4-N5`. Backend và frontend được phục vụ cùng origin bởi launcher hiện có.

## Chạy demo đã chuẩn bị

```powershell
cd D:\TTCS_K23C_N5\TTCS-K18C4-N5
.\start_demo.bat
```

Launcher khởi động tìm cổng tại 8765; database mặc định chính thức: `.sprint123-trial/demo_sprint123_north.db`. Launcher in profile, đường dẫn code, database, URL và PID. Giao diện lấy profile/database từ `/demo-scope`. Không đưa mật khẩu vào màn hình khởi động hoặc log.

Nếu cổng bị chiếm, launcher báo PID và tự thử cổng tiếp theo (tối đa 100 cổng), không tắt hoặc dùng lại tiến trình. URL thực tế luôn được in ra và tự mở trong trình duyệt khi chạy `start_demo.bat`. Có thể chỉ định cổng bắt đầu tìm:

```powershell
.\start_demo.bat -Port 8769
```

Dừng đúng PID của demo vừa khởi chạy bằng `Stop-Process -Id <PID>`; không dừng PID server khác. Chế độ kiểm tra rồi dừng: `start_demo.bat -NoBrowser -StopAfterCheck -Port 8770`.

## Mật khẩu local và đăng nhập

Tám tài khoản demo được cấu hình bảo mật ở `.sprint123-trial/credentials.local`. File bị Git bỏ qua và ACL Windows chỉ cấp quyền cho người dùng đã tạo file. Mở riêng bằng Notepad:

```powershell
notepad .\.sprint123-trial\credentials.local
```

Chọn nhanh một trong 8 tài khoản theo vai trò ngay trên màn hình đăng nhập (Quick Login selector):

| Khóa mật khẩu | Email | Vai trò | Tổ chức | Đơn vị đại diện |
|---|---|---|---|---|
| farm | s123_farm@demo.local | farmer | HTX-TC | HTX Nông nghiệp Tân Cương – Thái Nguyên |
| packing | s123_packing@demo.local | processor | HTX-TC | HTX Nông nghiệp Tân Cương – Thái Nguyên |
| receiver | s123_receiver@demo.local | processor | LOG-HN | Công ty Chế biến & Logistics Hà Nội |
| transport | s123_transport@demo.local | transporter | LOG-HN | Công ty Chế biến & Logistics Hà Nội |
| distribution | s123_distribution@demo.local | distributor | NPP-BN | Trung tâm Phân phối Nông sản Bắc Ninh |
| inspector | s123_inspector@demo.local | inspector | Toàn cảnh | Toàn cảnh nghiệp vụ chuỗi cung ứng |
| admin | s123_admin@demo.local | system_admin | HTX-TC | Quản trị hệ thống AgriTrace |
| org_admin | s123_org_admin@demo.local | org_admin | HTX-TC | Quản trị nội bộ HTX Tân Cương |

Đây là **8 tài khoản, 7 vai trò khác nhau**: hai processor phân bổ cho hai tổ chức riêng biệt (HTX-TC và LOG-HN).

## Bối cảnh Dữ liệu Miền Bắc

- **Sản phẩm chính:** Chè búp tươi Tân Cương (đơn vị: `kg`, chuẩn VietGAP).
- **Sản phẩm bổ sung:** Rau an toàn Gia Lâm (đơn vị: `kg`).
- **3 Vùng trồng tại Thái Nguyên:** Đồi Chè Tân Cương 1, Đồi Chè Phúc Trìu, Đồi Chè Phúc Xuân.
- **16 Lô hàng chuẩn thực tế:**
  - 3 Lô thu hoạch gốc: `CHE-TC-01`, `CHE-PT-02`, `CHE-PX-03`
  - 6 Lô sau phân loại (Tách): `CHE-LO-A1`, `CHE-LO-B1`, `CHE-LO-A2`, `CHE-LO-B2`, `CHE-LO-A3`, `CHE-LO-B3`
  - 3 Lô gộp chuẩn đóng gói: `CHE-GOP-HN01`, `CHE-GOP-ND02`, `CHE-GOP-CB03`
  - 2 Lô thành phẩm bàn giao: `CHE-TP-HN01` (sang LOG-HN), `CHE-TP-BN02` (sang NPP-BN)
  - 1 Lô đang chờ tiếp nhận bàn giao: `CHE-CHO-TIEP-NHAN` (PENDING)
  - 1 Lô đã tiêu thụ hết: `CHE-TIEU-THU-HET` (CONSUMED)

## Demo từng bước

1. Xác nhận banner **DEMO SPRINT 1–3** và đúng database `demo_sprint123_north.db` trước khi đăng nhập.
2. `farm`: tạo vùng trồng hoặc xem 3 đồi chè Tân Cương, thu hoạch lô chè búp tươi; kiểm tra mã lô và sự kiện thu hoạch SHA-256.
3. `farm`: tách lô; xem quan hệ cha/con và theo dõi bàn giao.
4. `packing`: gộp các lô chè đạt phẩm cấp thành lô chuẩn chế biến.
5. `packing`: gửi bàn giao sang `LOG-HN`. `receiver`: đăng nhập nhận lô trong mục tiếp nhận bàn giao (hoặc nhận lô `CHE-CHO-TIEP-NHAN` đang chờ sẵn).
6. `receiver`: mở chi tiết lô, tab phả hệ truy ngược về đồi chè gốc; tab lịch sử kiểm tra chuỗi hash-chain SHA-256 hợp lệ.
7. `inspector`: xem lô của cả 3 tổ chức (`HTX-TC`, `LOG-HN`, `NPP-BN`) và truy xuất toàn cảnh.
8. `admin` / `org_admin`: kiểm tra danh mục và quản trị người dùng.

## Điều hướng Dashboard

Sau đăng nhập, chọn màn hình ở Sidebar: Tổng quan, Vùng trồng, Lô nông sản, Tiếp nhận bàn giao (hoặc Theo dõi bàn giao với Nông dân), Truy xuất nguồn gốc hoặc Nhật ký sự kiện.
