# Sprint 3 — Giai đoạn B
Phạm vi: S-26, S-27, S-28. Không thay đổi RBAC, schema SQLite hoặc dữ liệu chính thức.

## Response truy xuôi
GET /batches/{id}/trace-forward giữ target_batch, descendants_by_level, terminal_batches, total_descendants và mọi trường node cũ. Thêm edges, mặc định [] khi parse response cũ:

```json
{"parent_batch_id":1,"child_batch_id":2,"relation_type":"SPLIT","transferred_quantity":40.0}
```

Edges lấy BatchRelation thật giữa những node đã được trả về. Không thêm cha ngoài phạm vi truy xuôi để hoàn thành lô gộp. Router chỉ trả cạnh khi cả hai đầu được can_view_batch cho phép, kể cả SystemAdmin; Inspector xem liên tổ chức. Node masking cũ giữ nguyên. Không sửa response cache khi mask; frontend không suy cạnh từ parent_batch_id khi edges thiếu.

## UI
Trong modal chi tiết → Nguồn gốc xuất xứ → Xem các lô liên quan: sơ đồ DAG có mũi tên, lô gốc, split/merge, nhiều cha, chọn node xem thông tin trong panel, mở/thu từng nhánh hoặc tất cả. Merge còn đường cha đang mở vẫn hiển thị. Keyboard native buttons và focus; scroll trong khung trên mobile. Node/edge counts là phần hiển thị trong phạm vi response, không đại diện cho cha ngoài phạm vi.

Location cũ là vị trí nguồn gốc. Vị trí hiện tại ghi rõ chưa có dữ liệu/phụ thuộc S-30. Không đổi tên trường API, tạo store/GPS hoặc suy vị trí từ tên organization. Unknown quantity ở UI không đổi thành 0.

Launcher Sprint123 chỉ bỏ gate nút trace-forward. maxSprint=3, Recall và Consume giữ gate hiện hữu. Không triển khai S-29–S-39.

## Giới hạn
Giới hạn truy xuôi hiện hữu 1.000 descendants, cờ is_truncated được hiển thị khi kết quả cắt. Phần cycle-check dùng stack lặp; bulk BFS và tests S-26 hiện hữu được giữ. Không có zoom/pan bằng gesture; dùng scroll. Chọn node mở thông tin đã được API trả về, không tự gọi detail của lô bị hạn chế.

Kiểm thử: full pytest 319 PASS; tests mới depth5000/cycle/shared child, chain1000 qua service và HTTP, edges thật nhiều cha, không thêm nguồn ngoài,8 vai trò,mask/cache isolation,response cũ không edges. Browser IAB QA kiểm tra4tầng5node5edges,collapse2cha,click/Enter,mobile390px,empty,cycleerror,recovery,backward và mở graph cho8account. Chrome/Edge độc lập chưa kiểm trong đợt này.

S-27 chưa hoàn tất vị trí hiện tại vì phụ thuộc S-30. Chi tiết kết quả và evidence ở báo cáo Giai đoạn B ngoài repository.
