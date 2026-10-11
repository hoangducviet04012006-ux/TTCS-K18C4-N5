# Rà soát phân quyền UI/API Sprint 1–3 — 10/10/2026

Chỉ rà soát và đề xuất. Không sửa code, RBAC, Recall, launcher hoặc database hiện hữu. Kết luận: Sidebar tương tự nhau không tự nó là lỗi quyền, nhưng có lỗi thực tế trong kiểm tra quyền API, modal chi tiết và phạm vi audit log.

## Nguồn quyền thực tế

Đọc `backend/app/services/rbac.py`, `security.py`, các router farms/batches/events/handovers/users/products/audit và `services/permissions.py`; đối chiếu `frontend/index.html`, `frontend/js/app.js`. Không coi mô tả Swagger hoặc tên dependency `require_farmer` là chính sách cuối cùng: dependency này thực tế cho phép cả farmer, processor, transporter, distributor, org_admin và system_admin có tổ chức.

`ROLE_PERMISSIONS` quy định HARVEST chỉ farmer; FARM_MANAGE chỉ farmer/org_admin; SPLIT farmer/processor/distributor; MERGE chỉ processor; HANDOVER_INIT/RESPOND farmer/processor/transporter/distributor. Inspector đọc liên tổ chức và không ghi nghiệp vụ. Quyền xem dữ liệu không đồng nghĩa quyền thao tác.

## Ma trận theo 8 tài khoản

Tất cả tên dưới đây có hậu tố `@demo.local`. Có **8 tài khoản nhưng 7 vai trò**, hai tài khoản processor ở hai tổ chức khác nhau. Dấu ✓/— phản ánh ma trận chính sách, không phải mọi router đã thực thi đúng.

| Tài khoản | Vai trò / tổ chức | Xem vùng/lô/BFS/sự kiện | Tạo/sửa vùng | Thu hoạch | Tách | Gộp | Gửi/nhận bàn giao | Tài khoản | Audit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s123_farm | farmer / 1 | Phạm vi tổ chức, phả hệ/lịch sử hợp lệ | ✓ | ✓ | ✓ | — | ✓ | — | — |
| s123_packing | processor / 1 | Như trên | — | — | ✓ | ✓ | ✓ | — | — |
| s123_receiver | processor / 2 | Như trên | — | — | ✓ | ✓ | ✓ | — | — |
| s123_transport | transporter / 2 | Như trên | — | — | — | — | ✓ | — | — |
| s123_distribution | distributor / 3 | Như trên | — | — | ✓ | — | ✓ | — | — |
| s123_inspector | inspector / không gán tổ chức | Toàn hệ thống, chỉ xem | — | — | — | — | — | — | ✓ toàn hệ thống |
| s123_admin | system_admin / 1 | Danh sách vùng/lô hiện lọc tổ chức 1 | — | — | — | — | — | ✓ toàn hệ thống | ✓ toàn hệ thống |
| s123_org_admin | org_admin / 1 | Phạm vi tổ chức/phả hệ hợp lệ | ✓ | — | — | — | — | ✓ tổ chức 1 | Có quyền đọc; phạm vi hiện sai |

Điều kiện giữ lô, trạng thái, khối lượng, bàn giao đang chờ và các kiểm tra nghiệp vụ vẫn áp dụng ngoài quyền vai trò. Danh sách lô chủ yếu là lô tổ chức đang giữ; quyền đọc chi tiết còn có lịch sử giữ lô và quyền đọc tổ tiên để truy ngược. Không được coi việc đọc tổ tiên khác tổ chức là rò rỉ nếu Backend cho phép theo phả hệ. System_admin không được router danh sách vùng/lô tự động cấp toàn cảnh; router sự kiện/integrity lại có ngoại lệ đọc cho system_admin — cần mô tả rõ sự khác nhau giữa endpoint, không suy diễn quyền toàn hệ thống từ tên vai trò.

## Điểm đúng

- Sidebar Vùng trồng, Lô nông sản, Truy xuất nguồn gốc, Nhật ký sự kiện có thể chung cho bốn vai trò nghiệp vụ vì Backend cho phép đọc. Processor/transporter/distributor đọc vùng thuộc tổ chức không đồng nghĩa được khai báo/sửa vùng.
- Form tạo vùng chỉ hiện farmer/org_admin; form thu hoạch chỉ farmer; nút gộp chỉ processor. Nút hành động ở bảng lô xét vai trò và tổ chức giữ lô.
- HARVEST bị từ chối 403 cho mọi tài khoản ngoài farmer; farmer MERGE bị 403; transporter SPLIT/MERGE bị 403; system_admin và org_admin HARVEST/SPLIT/MERGE/HANDOVER bị 403.
- Inspector đọc danh sách liên tổ chức, BFS, sự kiện, integrity; các thao tác ghi đã kiểm tra trả 403.
- Quản trị tài khoản của org_admin lọc đúng tổ chức 1. Lọc tổ chức 2 hoặc PATCH tài khoản thuộc tổ chức 2 trả 403. Router còn kiểm tra quyền cấp vai trò và tài khoản đặc quyền.
- Farm/batch của một lô thu hoạch mới, chưa liên quan tổ chức 2/3: receiver/transporter/distributor GET trả 403; inspector GET trả 200. Các tài khoản tổ chức 1 GET trả 200 đúng phạm vi.

## Điểm sai và đề xuất, chưa áp dụng

| Ưu tiên | Phát hiện đã kiểm chứng | Nguyên nhân / vị trí | Đề xuất cần phê duyệt |
| --- | --- | --- | --- |
| Cao | Processor, transporter, distributor và system_admin POST vùng trồng trả **201**, PUT vùng trả **200**, dù UI ẩn form/nút | `routers/farms.py:50,145` chỉ dùng `require_farmer`, không gọi FARM_MANAGE; ma trận ở `services/rbac.py:75` chỉ farmer/org_admin | Áp dụng FARM_MANAGE tại cả hai API. Giữ giao diện chỉ xem cho các vai trò khác. Chỉ sửa UI sẽ không bảo vệ API |
| Cao | System_admin PUT lô trả **200**, POST sự kiện PROCESS trả **201**; processor/transporter/distributor/org_admin cũng PUT lô được khi đúng tổ chức | `routers/batches.py:386` và `routers/events.py:84` dùng nhóm nghiệp vụ rộng; thiếu quyền hành động riêng. UI chỉ cho farmer sửa lô | Đối với yêu cầu system_admin không sản xuất: chặn ghi nghiệp vụ. Chốt quyền BATCH_UPDATE và EVENT_CREATE cụ thể trước khi sửa; không tự cho rằng PROCESS trong payload tương đương quyền PROCESS đã được kiểm tra |
| Cao | Org_admin GET audit log có dữ liệu actor thuộc **tổ chức 1,2,3**; lọc đích `user_id` của receiver vẫn **200**, trả **14 dòng** trong DB tạm | `routers/audit.py:108` gọi `fetch_audit_logs` không truyền phạm vi; `app/audit.py:74` không lọc tổ chức | Lọc Backend theo phạm vi tổ chức cho org_admin, kể cả khi dùng bộ lọc user/entity; UI không thể sửa lỗi này chỉ bằng ẩn menu |
| Cao | Modal chi tiết bật nút **Tách** cho transporter và bật **Tách/Bàn giao** cho system_admin/org_admin; API từ chối 403 | `routers/batches.py:1080–1082` tính can_split/can_merge/can_handover theo giữ lô/trạng thái nhưng không xét vai trò. `app.js:2529–2547` tin trực tiếp các cờ này | Frontend kết hợp quyền vai trò với cờ Backend; ẩn hành động không có quyền, chỉ disable khi có quyền nhưng trạng thái lô chưa hợp lệ. Backend summary phải tính thêm quyền vai trò khi được duyệt |
| Vừa | Org_admin tạo sản phẩm dùng chung toàn hệ thống: POST products **201** | `routers/products.py:54` dùng require_admin; danh mục không có phạm vi tổ chức | Hiện phù hợp route cũ nhưng không phù hợp yêu cầu quản trị chỉ trong tổ chức nếu hiểu tuyệt đối. Đề xuất org_admin chỉ xem danh mục dùng chung; cần chốt chính sách trước khi đổi Backend |
| Vừa | Tiêu đề Vùng trồng nói quản lý/khai báo/chỉnh sửa; mô tả Lô nông sản nói thu hoạch/tách/gộp cho cả vai trò chỉ xem | `app.js:3801` mô tả màn hình chung; inspector có ngữ cảnh vùng “Tổ chức của bạn” dù xem toàn hệ thống | Hiển thị nhãn “Chỉ xem” và mô tả theo vai trò/phạm vi. Không cần loại bỏ quyền xem đã được Backend cấp |

Nút Xóa vùng/lô hiện xuất hiện cho system_admin/org_admin và các API DELETE dùng require_admin cùng kiểm tra tổ chức; lô có lịch sử bị chặn xóa. Đây là quyền đã có ở router, không nên tự bỏ hay mở rộng dựa riêng vào HARVEST. Đề xuất xác nhận riêng quyền xóa dữ liệu nghiệp vụ của quản trị và ưu tiên ẩn thao tác này trong demo nếu mentor không yêu cầu. Không thực hiện DELETE trong lượt rà soát này.

Modal mở Tách/Bàn giao chưa có kiểm tra vai trò ngay trong hàm mở (`openSplitModal`, `openHandoverModal`). API SPLIT/HANDOVER vẫn chặn vai trò trái quyền, nhưng trải nghiệm hiện gây hiểu lầm. Những cờ `can_merge` sai vai trò trong summary cũng cần sửa dù modal không có nút Gộp.

## Sidebar đề xuất

| Vai trò | Cách hiển thị |
| --- | --- |
| Farmer | Giữ sáu menu Sprint 1–3; Vùng trồng quản lý; Lô có thu hoạch/tách/bàn giao; không Gộp |
| Processor | Giữ đọc vùng, có nhãn Chỉ xem; Lô có tách/gộp/bàn giao; không form thu hoạch |
| Transporter | Ưu tiên Lô đang giữ và Tiếp nhận bàn giao. Vùng trồng chỉ xem hoặc chuyển thông tin vùng vào chi tiết lô; không tạo/sửa vùng, thu hoạch, tách/gộp |
| Distributor | Vùng chỉ xem; Lô có tách/bàn giao theo Backend; không thu hoạch/gộp |
| Inspector | Đọc toàn cảnh vùng/lô/BFS/sự kiện/audit; ẩn toàn bộ nút ghi nghiệp vụ, không Tiếp nhận bàn giao |
| System_admin | Ưu tiên Tài khoản/Nhật ký quản trị; vùng/lô/BFS/sự kiện chỉ xem theo phạm vi thực tế endpoint; không nghiệp vụ sản xuất |
| Org_admin | Tài khoản trong tổ chức, quản lý vùng, đọc lô/BFS/sự kiện; audit chỉ tổ chức sau khi Backend được sửa; không thu hoạch/tách/gộp/bàn giao |

Có thể giữ các menu đọc chung với nhãn rõ ràng để demo dễ hiểu. Không đề xuất tước quyền đọc Backend chỉ vì Sidebar tương tự nhau. Nếu muốn ẩn Vùng trồng cho transporter/distributor, đó là thay đổi ưu tiên UX, không phải sửa một quyền xem trái Backend.

## Dashboard: phạm vi và ý nghĩa

| Chỉ số | Hiện trạng | Đánh giá / đề xuất |
| --- | --- | --- |
| Tổng vùng trồng | `farms.length`; inspector toàn cảnh, các tài khoản khác theo tổ chức | Phạm vi đúng với GET farms. Nhãn “Cơ sở canh tác đang hoạt động” chưa có điều kiện lọc trạng thái hoạt động; đổi thành số vùng đã tải, thêm phạm vi |
| Lô trên trang hiện tại | `batches.length`, trang tối đa 20, chịu bộ lọc màn hình Lô | Nhãn đã đúng là số trên trang, không phải tổng toàn tổ chức. Hiển thị rõ trang/bộ lọc và tránh dùng như KPI tổng |
| Khối lượng trên trang | Cộng **remaining_quantity**, fallback quantity; nhóm theo đơn vị | Không phải tổng sản lượng thu hoạch. Đổi nhãn “Khối lượng còn lại của lô trên trang”; không cộng chung các đơn vị. Cách nhóm đơn vị hiện đúng |
| Lô chờ xác nhận | GET handovers/pending lọc tổ chức; UI tải cho mọi vai trò | Inspector GET bị 403 nhưng UI hiển thị **0**, không thể hiểu là không có yêu cầu. System_admin/org_admin GET 200 nhưng menu bị ẩn, link thẻ dẫn về Tổng quan. Ẩn thẻ khi không có phạm vi/quyền phù hợp hoặc cung cấp màn hình chỉ xem; 0 phải phân biệt lỗi/không được phép |
| Nhật ký hoạt động | `auditLogs.length`, API mặc định tối đa **100** | Số dòng đã tải, không phải tổng. Inspector thấy thẻ nhưng lúc đăng nhập không tự load audit vì `loadAllData` chỉ load khi isAdmin; kết quả **0** dù API có dữ liệu. Đề xuất tải khi canViewAuditLogs, ghi rõ “Bản ghi gần nhất đã tải”; org_admin cần sửa phạm vi Backend trước |
| Hoạt động gần đây | Lấy sự kiện từ **tối đa 5 lô đầu trên trang**, chọn 5 sự kiện gần nhất trong mẫu | Không bảo đảm 5 hoạt động mới nhất toàn tổ chức/toàn hệ thống. Ghi rõ phạm vi mẫu; chỉ đề xuất API tổng hợp nếu thật sự cần và được duyệt |

Nguồn: `app.js:1546` renderStats, `3765` loadAllData, `3918` refreshScreenData; `index.html` các thẻ thống kê. Giá trị ghi trong bằng chứng thuộc **database tạm đã có các thao tác kiểm thử**, không phải số liệu database demo chính để nghiệm thu sản lượng.

## Kiểm thử và bảo toàn

- Chrome và Edge cài trên máy, chạy headless: **16 phiên kiểm tra tài khoản/trình duyệt**, đủ cả 8 tài khoản trên mỗi trình duyệt; không lỗi JavaScript.
- Ghi nhận **270 kết quả API** trong bộ rà soát browser, gồm **91 HTTP 403**. Đây là kết quả quan sát, không tuyên bố tất cả kiểm tra quyền đều đạt: các phản hồi 200/201 trái ma trận được báo rõ ở trên.
- Ma trận thao tác API đầy đủ của cả 8 tài khoản được thực hiện ở lượt Chrome. Lượt Edge đăng nhập/menu đủ 8; tài khoản distributor không còn lô phù hợp điều kiện fixture để lặp lại nhóm thao tác trên lô, nên nhóm đó chỉ có kết quả Chrome. Không coi trường hợp bỏ qua là kiểm tra đã đạt.
- Bổ sung GET lô/vùng mới chưa có liên hệ phả hệ theo cả 8 tài khoản và truy vấn audit có bộ lọc actor tổ chức khác.
- Các chặn FARMS trái tổ chức, USER filter/PATCH trái tổ chức và HARVEST/SPLIT/MERGE trái vai trò đều được gọi với payload hợp lệ để chứng minh 403, không lấy lỗi 422 làm bằng chứng RBAC.
- Không rerun toàn bộ 263 test Backend trong lượt đọc/rà soát này; kết quả 263 pass thuộc nhiệm vụ tổ chức thư mục trước đó, không thay thế các kiểm tra lỗ hổng mới.
- Mọi login và request có thể ghi, kể cả GET pending có tác dụng đánh dấu quá hạn, đều chạy trên bản sao riêng trong TEMP: `C:\Users\Hoang\AppData\Local\Temp\agritrace_rbac_audit_8ssug8pq\rbac_audit.db`, cổng 8778, dùng cùng code Backend/Frontend chính. Không chạy seed/migration/reset. Chỉ thêm fixture và thao tác trên DB tạm. Đã dừng server tạm; giữ lại dữ liệu/bằng chứng.
- So SHA-256 trước/sau: **13 database hiện hữu và 54 file nguồn Backend/Frontend/script đều giữ nguyên**. So byte toàn DB bao gồm schema, tất cả bản ghi, tài khoản, password và hash-chain; không chỉ so số lượng. Không thay đổi database gốc hoặc database demo chính.

Bằng chứng ngoài repository: [kết quả browser](C:/Users/Hoang/AppData/Local/Temp/agritrace_rbac_audit_8ssug8pq/results.json), [kiểm tra bổ sung](C:/Users/Hoang/AppData/Local/Temp/agritrace_rbac_audit_8ssug8pq/supplemental.json), [đối chiếu file](C:/Users/Hoang/AppData/Local/Temp/agritrace_rbac_audit_8ssug8pq/verification.json). Ảnh từng tài khoản ở cùng thư mục TEMP. Test driver cũng chỉ ở TEMP, không sửa test/code dự án. Driver được hiệu chỉnh theo tên hàm/route/schema thực tế trước lượt kiểm tra hoàn chỉnh; lỗi khởi tạo driver không được tính là lỗi ứng dụng.

Chỉ tạo báo cáo này trong repository. Đề xuất thứ tự phê duyệt: (1) sửa phạm vi audit và enforce FARM_MANAGE; (2) chốt/sửa quyền cập nhật lô và ghi sự kiện; (3) đồng bộ cờ summary/modal và UI chỉ xem; (4) chỉnh nhãn/phạm vi KPI và Sidebar. Không áp dụng bất kỳ đề xuất nào trong nhiệm vụ này; dừng chờ phê duyệt, không sửa Recall hoặc phát triển Sprint 4–8.
