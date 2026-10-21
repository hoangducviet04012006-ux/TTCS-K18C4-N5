# Thực hành AgriTrace — TH1 và TH2

**Toàn bộ dữ liệu và tổ chức trong hai bộ là mô phỏng**, không xác nhận sản xuất, kiểm định hay chứng nhận có thật.

## Mở và chọn bộ

- TH1: mở `start_practice.bat`.
- TH2: mở `start_practice_TH2.bat`.
- Phần mềm dùng cổng **8772** và database riêng `.sprint123-trial/practice/qa_practice.db`.
- Hai bộ cùng một database thực hành nhưng có sản phẩm, vùng trồng, cửa hàng và mã lô riêng. Chọn sản phẩm có hậu tố TH1 hoặc TH2 trong bộ lọc.
- Trang hướng dẫn mở trước; bấm **Mở phần mềm**. Không có tự động khôi phục dữ liệu.

## Tài khoản

Tám tài khoản gốc giữ nguyên vai trò và mật khẩu. Chọn tài khoản ở danh sách đăng nhập nhanh; không cần nhập mật khẩu. Khi nhập tay, tên đăng nhập là tên trong bảng, email là tên đó cộng `@demo.local`.

| Tài khoản | Vai trò | Dùng để |
|---|---|---|
| s123_farm | Nông dân | Org1: vùng trồng, thu hoạch, tách, bàn giao, nhập thửa đất |
| s123_packing | Sơ chế / đóng gói | Org1: tách, gộp, bàn giao |
| s123_receiver | Tiếp nhận / chế biến | Org2: nhận bàn giao, tách, gộp |
| s123_transport | Vận chuyển | Org2: bàn giao sang Org3 |
| s123_distribution | Phân phối | Org3: địa điểm, phân bổ, tiêu thụ |
| s123_inspector | Cán bộ kiểm tra | Truy xuất liên tổ chức, thu hồi, kiểm toán |
| s123_admin | Quản trị hệ thống | Sản phẩm, tài khoản, tổ chức, CSV sản phẩm, kiểm toán |
| s123_org_admin | Quản trị tổ chức | Org1: thu hồi và xác nhận xử lý |

Để xác nhận thu hồi: **Org1 → Org2 → Org3**. Org1 dùng `s123_org_admin` (đăng nhập nhanh). Hai tài khoản sau chỉ có trong database thực hành; dùng nút điền tài khoản rồi bấm Đăng nhập, hoặc nhập tay:

| Tài khoản | Mật khẩu thực hành | Tổ chức |
|---|---|---|
| practice_org2 | ThucHanh2026!Org2 | Cơ sở chế biến và kho Hà Nội |
| practice_org3 | ThucHanh2026!Org3 | Đơn vị phân phối Bắc Ninh |

**Các trạng thái trong hướng dẫn là trạng thái của snapshot sạch.** Bản đang chạy có thể đã có thao tác thực hành. Phần mềm không tự khôi phục; luôn giữ dữ liệu hiện tại cho đến khi bạn xác nhận.

## Trình tự thực hành

Làm phân bổ, tiêu thụ, CSV và các thao tác thu hoạch/tách/gộp/bàn giao trước khi tạo thu hồi. Lô phân bổ và lô tiêu thụ riêng hoàn toàn với chuỗi thu hồi.

## TH1

| Mục đích | Mã lô / dữ liệu | Trạng thái snapshot sạch |
|---|---|---|
| Truy xuất và tạo thu hồi | **6Z9AGC2R** (ID 1) | Lô gốc 600 kg, còn 0 kg sau tách; chưa có yêu cầu thu hồi |
| Gộp nhiều nguồn | RMSK6VRM | 3 cha, 2 nguồn thu hoạch; tổng ban đầu 500 kg |
| Phân bổ cửa hàng | **ZZCUAEWU** | Org3 đang giữ, còn 180 kg |
| Tiêu thụ hết | **WHXEPWYU** | Org3 đang giữ, còn 30 kg; dùng riêng |
| Tách/gộp/bàn giao bổ sung | **UDJ9N6YP** | Org1 đang giữ, còn 120 kg |
| Tiếp nhận bàn giao | **J2MYZKMX** | Chờ Org2 nhận 70 kg |
| Cửa hàng | TH1-CH1 / TH1-CH2 | Suối Hoa / Từ Sơn, Bắc Ninh |
| Vùng trồng / sản phẩm | Đồi chè Tân Cương – khu TH1 / Chè búp Tân Cương – đợt TH1 | Có hậu tố TH1 |

| Story | Tài khoản và thao tác |
|---|---|
| S-26 | s123_inspector → Lô nông sản → tìm 6Z9AGC2R → Chi tiết → Nguồn gốc & Phả hệ → Phả hệ hậu duệ. |
| S-27 | Chọn lô con trong sơ đồ; đối chiếu tổ chức, vị trí hiện tại, sản phẩm và lượng còn lại. |
| S-28 | Thu gọn về lô gốc → Mở tất cả → mở/thu từng nhánh; lô gộp có hai cha trong cây truy xuôi của gốc này, ba cha trong nguồn gốc của lô gộp. |
| S-29 | s123_distribution → tìm WHXEPWYU → Thao tác → Tiêu thụ → xác nhận. Sau tải lại: đã tiêu thụ, còn 0 kg. |
| S-30 | s123_distribution → Lô nông sản → lọc sản phẩm TH1, chọn 20 lô/trang → Địa điểm phân phối → chọn ZZCUAEWU. Phân bổ 80 kg vào TH1-CH1 và 100 kg vào TH1-CH2. Ghi lại hai mã con được sinh. |
| S-31 | s123_inspector hoặc s123_admin → Nhật ký kiểm toán → lọc mã đối tượng là Lô, ID lô 1 (hoặc ID lô phân bổ 11); xem người thao tác, thời gian, lượng/vị trí liên quan. |
| S-32 | s123_admin nhập TH1-san-pham.csv (Sản phẩm); s123_farm nhập TH1-thua-dat.csv (Thửa đất). Mỗi tệp có hai dòng mới, không trùng bộ còn lại. |
| S-33 | s123_inspector hoặc s123_org_admin → Thu hồi → Tạo yêu cầu thu hồi → mã 6Z9AGC2R → lý do ít nhất 20 ký tự → kiểm tra → xác nhận. Ví dụ: Diễn tập thu hồi chè TH1 do nghi ngờ chất lượng nguyên liệu; dữ liệu mô phỏng. |
| S-34 | s123_inspector → Chi tiết yêu cầu → sơ đồ ảnh hưởng và lô gộp nhiều nguồn. Không đưa lô gốc thứ hai vào hậu duệ nếu nó không phát sinh từ gốc thu hồi. |
| S-35 | Đối chiếu theo kg: tồn kho có thể thu hồi 600 kg (200 ở Org1, 400 ở Org3), đã tiêu thụ có chứng cứ 100 kg. Có 100 kg từ nguồn gộp thứ hai nên tổng ảnh hưởng là 700 kg. |
| S-36 | Đăng nhập quản trị Org1/Org2/Org3 và mở Thu hồi; xem cảnh báo trong phạm vi tổ chức. |
| S-37 | Xác nhận theo thứ tự s123_org_admin → practice_org2 → practice_org3; tiến độ 1/3 → 2/3 → 3/3; cuối cùng đã đủ xác nhận, vẫn cách ly. |
| S-38 | Thử thao tác trên lô đang giữ bị cách ly: Org1 HW5FEXXX (200 kg), Org3 8CCX54A9 (240 kg). Tách, bàn giao và tiêu thụ bị chặn; Org2 không thể gộp các cha bị cách ly. Không đổi vai trò để thử. |
| S-39 | Đáp án chuỗi: 9 lô bị ảnh hưởng, 9 quan hệ, tầng 0–4 (4 tầng hậu duệ), 3 tổ chức, lô gộp chéo nguồn. Lô nguồn thứ hai không bị coi là hậu duệ. |

**Thao tác Sprint 1–2 bổ sung:** Nông dân có thể thu hoạch mới 80 kg trên vùng/sản phẩm của bộ, sơ chế tách 30/50 kg rồi gộp 80 kg; bàn giao sang Org2 và tiếp nhận. Ghi lại các mã do hệ thống sinh, không sửa mã lô.

## TH2

| Mục đích | Mã lô / dữ liệu | Trạng thái snapshot sạch |
|---|---|---|
| Truy xuất và tạo thu hồi | **BCSH7JUV** (ID 15) | Lô gốc 600 kg, còn 0 kg sau tách; chưa có yêu cầu thu hồi |
| Gộp nhiều nguồn | FCNQHBQU | 3 cha, 2 nguồn thu hoạch; tổng ban đầu 500 kg |
| Phân bổ cửa hàng | **VHD63M8Z** | Org3 đang giữ, còn 180 kg |
| Tiêu thụ hết | **A25DT8DT** | Org3 đang giữ, còn 30 kg; dùng riêng |
| Tách/gộp/bàn giao bổ sung | **7JT5DWZ6** | Org1 đang giữ, còn 120 kg |
| Tiếp nhận bàn giao | **TGXBMCR6** | Chờ Org2 nhận 70 kg |
| Cửa hàng | TH2-CH1 / TH2-CH2 | Suối Hoa / Từ Sơn, Bắc Ninh |
| Vùng trồng / sản phẩm | Đồi chè Tân Cương – khu TH2 / Chè búp Tân Cương – đợt TH2 | Có hậu tố TH2 |

| Story | Tài khoản và thao tác |
|---|---|
| S-26 | s123_inspector → Lô nông sản → tìm BCSH7JUV → Chi tiết → Nguồn gốc & Phả hệ → Phả hệ hậu duệ. |
| S-27 | Chọn lô con trong sơ đồ; đối chiếu tổ chức, vị trí hiện tại, sản phẩm và lượng còn lại. |
| S-28 | Thu gọn về lô gốc → Mở tất cả → mở/thu từng nhánh; lô gộp có hai cha trong cây truy xuôi của gốc này, ba cha trong nguồn gốc của lô gộp. |
| S-29 | s123_distribution → tìm A25DT8DT → Thao tác → Tiêu thụ → xác nhận. Sau tải lại: đã tiêu thụ, còn 0 kg. |
| S-30 | s123_distribution → Lô nông sản → lọc sản phẩm TH2, chọn 20 lô/trang → Địa điểm phân phối → chọn VHD63M8Z. Phân bổ 80 kg vào TH2-CH1 và 100 kg vào TH2-CH2. Ghi lại hai mã con được sinh. |
| S-31 | s123_inspector hoặc s123_admin → Nhật ký kiểm toán → lọc mã đối tượng là Lô, ID lô 15 (hoặc ID lô phân bổ 25); xem người thao tác, thời gian, lượng/vị trí liên quan. |
| S-32 | s123_admin nhập TH2-san-pham.csv (Sản phẩm); s123_farm nhập TH2-thua-dat.csv (Thửa đất). Mỗi tệp có hai dòng mới, không trùng bộ còn lại. |
| S-33 | s123_inspector hoặc s123_org_admin → Thu hồi → Tạo yêu cầu thu hồi → mã BCSH7JUV → lý do ít nhất 20 ký tự → kiểm tra → xác nhận. Ví dụ: Diễn tập thu hồi chè TH2 do nghi ngờ chất lượng nguyên liệu; dữ liệu mô phỏng. |
| S-34 | s123_inspector → Chi tiết yêu cầu → sơ đồ ảnh hưởng và lô gộp nhiều nguồn. Không đưa lô gốc thứ hai vào hậu duệ nếu nó không phát sinh từ gốc thu hồi. |
| S-35 | Đối chiếu theo kg: tồn kho có thể thu hồi 600 kg (200 ở Org1, 400 ở Org3), đã tiêu thụ có chứng cứ 100 kg. Có 100 kg từ nguồn gộp thứ hai nên tổng ảnh hưởng là 700 kg. |
| S-36 | Đăng nhập quản trị Org1/Org2/Org3 và mở Thu hồi; xem cảnh báo trong phạm vi tổ chức. |
| S-37 | Xác nhận theo thứ tự s123_org_admin → practice_org2 → practice_org3; tiến độ 1/3 → 2/3 → 3/3; cuối cùng đã đủ xác nhận, vẫn cách ly. |
| S-38 | Thử thao tác trên lô đang giữ bị cách ly: Org1 T9KQ8DJT (200 kg), Org3 YD3Y72SB (240 kg). Tách, bàn giao và tiêu thụ bị chặn; Org2 không thể gộp các cha bị cách ly. Không đổi vai trò để thử. |
| S-39 | Đáp án chuỗi: 9 lô bị ảnh hưởng, 9 quan hệ, tầng 0–4 (4 tầng hậu duệ), 3 tổ chức, lô gộp chéo nguồn. Lô nguồn thứ hai không bị coi là hậu duệ. |

**Thao tác Sprint 1–2 bổ sung:** Nông dân có thể thu hoạch mới 80 kg trên vùng/sản phẩm của bộ, sơ chế tách 30/50 kg rồi gộp 80 kg; bàn giao sang Org2 và tiếp nhận. Ghi lại các mã do hệ thống sinh, không sửa mã lô.

## Làm lại sau khi dùng hết hai bộ

1. Mở `stop_practice.bat` để dừng đúng server thực hành 8772.
2. Mở `restore_practice.bat`. Đọc phạm vi và nhập chính xác **KHOI PHUC** để xác nhận. Nhập khác sẽ hủy.
3. Công cụ lưu bản thực hành hiện tại vào `before-restore-*.db`, kiểm tra snapshot rồi khôi phục **chỉ** `qa_practice.db`.
4. Mở launcher TH1 hoặc TH2. Database gốc, bản miền Bắc và bản tích hợp 8771 không bị thay thế.

Snapshot được kiểm tra SHA-256 trước khi dùng; không tự khôi phục khi mở phần mềm.

## Giới hạn cần biết

- Số lô và lượng trên Tổng quan được ghi rõ là số của trang đang xem; không giả làm tổng toàn hệ thống.
- Chọn lô phân bổ theo trang đang tải: lọc đúng sản phẩm TH1/TH2 và tăng 20 lô/trang trước khi mở Địa điểm.
- Quản trị hệ thống không có quyền sản xuất; OrgAdmin không có quyền tách/gộp/bàn giao. Phân quyền giữ nguyên.
- Thông báo thu hồi hiển thị trong phần mềm; chưa gửi email/SMS.
- Cây truy xuôi chỉ hiển thị các cha nằm trong phạm vi hậu duệ và quyền xem; xem nguồn gốc của lô gộp để đối chiếu cả ba cha.
