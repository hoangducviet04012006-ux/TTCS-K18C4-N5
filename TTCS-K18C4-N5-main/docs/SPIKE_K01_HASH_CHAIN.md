# SPIKE K-01: Phân Tích Kiến Trúc Bất Biến – Lựa Chọn Append-Only Hash Chain Thay Vì Blockchain Trong Chuỗi Lạnh Nông Sản

> **Mã tài liệu:** SPIKE-K01  
> **Dự án:** Hệ thống Truy xuất nguồn gốc và Giám sát Chuỗi lạnh Nông sản (TTCS)  
> **Sprint:** Sprint 1  
> **Trạng thái:** Đã phê duyệt (Approved Architecture Spike)  
> **Tác giả:** Đội ngũ Kiến trúc Hệ thống TTCS  

---

## 1. Tóm Tắt & Bối Cảnh Nghiên Cứu (Executive Summary)

Trong bài toán truy xuất nguồn gốc nông sản và chuỗi lạnh (*Cold Chain Logistics*), tính toàn vẹn dữ liệu (*Data Integrity*) và tính chống chối bỏ (*Non-repudiation*) là yếu tố sống còn. Dữ liệu nhiệt độ kho lạnh, xe tải đông lạnh, nhật ký canh tác của hợp tác xã (HTX) không được phép bị sửa đổi hay xoá bỏ hồi tố.

Khi đặt vấn đề xây dựng cơ chế lưu vết bất biến (*Tamper-evident Audit Trail*), có hai hướng tiếp cận chính:
1. **Triển khai Blockchain phân tán** (Public Blockchain như Ethereum/Polygon hoặc Private/Consortium Blockchain như Hyperledger Fabric, Quorum).
2. **Triển khai Chuỗi băm nối tiếp (Append-only Cryptographic Hash Chain)** kết hợp cấu trúc cây Merkle (*Merkle Tree*) trên nền tảng cơ sở dữ liệu quan hệ được cô lập.

Tài liệu này trình bày các phân tích kỹ thuật, chi phí vận hành, độ trễ hệ thống và tính khả thi trong thực tế nhằm lý giải vì sao dự án quyết định chọn **Append-only Hash Chain** làm kiến trúc cốt lõi thay vì Blockchain.

---

## 2. Bảng So Sánh Toàn Diện Giữa Hash Chain và Blockchain

| Tiêu chí | Append-only Hash Chain (SHA-256 + Merkle) | Private / Consortium Blockchain (Hyperledger Fabric) | Public Blockchain (Ethereum / L2 Rollups) |
| :--- | :--- | :--- | :--- |
| **Độ phức tạp hạ tầng** | **Rất thấp**: Chạy trực tiếp trên PostgreSQL/SQLite sẵn có, không cần duy trì mạng node P2P. | **Rất cao**: Cần Orderer, Peer, CA, MSP, CouchDB, mạng lưới Raft/Kafka. | **Trung bình - Cao**: Cần RPC Node, quản lý private key, cầu nối layer-2. |
| **Chi phí vận hành ($/tháng)** | **~ 0 USD phụ trội**: Tích hợp trực tiếp vào cụm Backend/Database hiện hữu. | **Cao**: Tối thiểu 4–6 node VPS để duy trì tính phân tán (tốn 100–300$/tháng). | **Biến động theo giao dịch**: Phí gas tăng vọt theo lưu lượng gửi dữ liệu cảm biến. |
| **Thông lượng (Throughput)** | **Rất cao**: Đạt 5.000 – 20.000 events/giây tuỳ cấu hình DB. | **Trung bình**: 500 – 2.000 TPS phụ thuộc vào block time và commit phase. | **Thấp**: 15 – 100 TPS (L1) hoặc ~1.000 TPS (L2), bị nghẽn mạng lúc cao điểm. |
| **Độ trễ ghi (Write Latency)** | **Tức thì (< 10ms)**: Tính toán băm SHA-256 diễn ra trong cùng transaction DB. | **1 – 3 giây**: Chờ đóng block, đồng thuận (consensus) giữa các peer. | **12 giây – vài phút**: Chờ block confirmation trên chuỗi. |
| **Khả năng chịu tải cảm biến IoT** | **Cực tốt**: Tiếp nhận chuỗi nhiệt độ 10–30 giây/lần từ hàng trăm container lạnh dễ dàng. | **Kém**: Ghi liên tục từng nhịp IoT gây phình to Ledger rất nhanh, chi phí I/O cao. | **Không khả thi**: Chi phí giao dịch sẽ vượt quá giá trị của lô nông sản. |
| **Bảo mật & Toàn vẹn** | **Toàn vẹn tuyệt đối**: Sai lệch 1 bit phá vỡ toàn bộ chuỗi băm $H_n = \text{SHA256}(H_{n-1} \parallel D_n)$. | **Toàn vẹn phân tán**: Chống giả mạo thông qua đa số nút đồng thuận. | **Toàn vẹn phi tập trung**: Bảo vệ bởi cơ chế PoS/PoW toàn cầu. |
| **Năng lực vận hành của HTX** | **Phù hợp thực tế**: HTX nông nghiệp chỉ cần truy cập web/app, không cần kỹ sư blockchain. | **Rất khó**: Đòi hỏi kỹ sư chuyên môn cao để bảo trì chứng chỉ TLS, MSP cert expiration. | **Khó**: Nguy cơ mất Private Key, vướng mắc pháp lý về tiền mã hoá/gas fee. |

---

## 3. Lý Do Lựa Chọn Append-Only Hash Chain Trong Chuỗi Lạnh

### 3.1. Đặc thù dữ liệu chuỗi lạnh: Lưu lượng cao và liên tục
Trong chuỗi cung ứng lạnh cho nông sản (xoài sấy, xoài tươi xuất khẩu, sầu riêng đông lạnh), nhiệt độ và độ ẩm phải được giám sát liên tục bằng thiết bị IoT/datalogger với tần suất 30 giây đến 1 phút một lần:
- Một container vận chuyển từ Đồng Tháp đến cảng Cát Lái trong 8 giờ tạo ra khoảng **1.000 bản ghi cảm biến**.
- Một HTX với 20 xe tải và 5 kho lạnh sẽ tạo ra hàng chục nghìn điểm dữ liệu mỗi ngày.
- **Nếu dùng Blockchain:** Mỗi lần ghi dữ liệu cảm biến là một transaction. Việc lưu trữ dữ liệu thời gian thực này vào Blockchain là lãng phí tài nguyên cực lớn và làm tắc nghẽn mạng lưới.
- **Với Hash Chain:** Mỗi bản ghi cảm biến hoặc mỗi batch dữ liệu được đóng gói và băm liên kết với khối trước đó:
  $$H_i = \text{SHA-256}(H_{i-1} \parallel \text{Timestamp} \parallel \text{SensorData} \parallel \text{Signature})$$
  Tốc độ tính toán hàm băm SHA-256 chỉ mất vài micro-giây trên CPU thông thường, đáp ứng thoải mái lưu lượng lớn mà không tốn thêm bất kỳ tài nguyên mạng nào.

### 3.2. Chi phí đầu tư và năng lực thực tế của Hợp tác xã (HTX)
- Đối tượng sử dụng của dự án là các hộ nông dân, ban quản trị HTX (như HTX Đồng Tháp, HTX Tiền Giang), các đơn vị kiểm định và người tiêu dùng.
- Việc áp dụng các giải pháp Blockchain đắt đỏ thường dẫn tới "dự án trình diễn" (*pilot trap*) – chạy thử nghiệm thì tốt nhưng khi bàn giao cho địa phương thì chết yểu vì không ai chịu chi trả phí node và không có nhân sự vận hành.
- Hash Chain tận dụng cơ sở dữ liệu mã nguồn mở có sẵn của hệ thống, không yêu cầu thiết lập ví điện tử, không cần mua coin/token để trả gas fee.

### 3.3. Cơ chế xác thực tính toàn vẹn (Tamper-evident Proof)
Mục tiêu cốt lõi của việc chống gian lận là: **"Nếu ai đó xâm nhập vào cơ sở dữ liệu và sửa đổi nhiệt độ của một chuyến xe từ $25^\circ\text{C}$ (hỏng hàng) thành $4^\circ\text{C}$ (đạt chuẩn), hệ thống phải phát hiện ngay lập tức."**

Hash Chain giải quyết trọn vẹn yêu cầu này:
1. Khi bản ghi thứ $k$ bị sửa đổi, hash $H_k$ sẽ thay đổi hoàn toàn (hiệu ứng tuyết lở - *Avalanche Effect* của hàm băm mật mã học).
2. Khi xác thực lại chuỗi, $H_{k+1} \neq \text{SHA-256}(H_k \parallel D_{k+1})$, toàn bộ chuỗi từ vị trí $k+1$ đến cuối sẽ bị vô hiệu và phát hiện được vị trí bị sửa đổi.
3. Để tăng cường tính khách quan, định kỳ cuối ngày hoặc khi hoàn thành một lô hàng, giá trị Merkle Root ($H_{\text{root}}$) của ngày đó có thể được ký số (Digital Signature) bằng chứng thư số của HTX hoặc đẩy lên một máy chủ thời gian độc lập (*RFC 3161 Timestamping Authority*) hoặc Public Anchor miễn phí.

---

## 4. Kiến Trúc Triển Khai Trong Dự Án TTCS

```
+-----------------------------------------------------------------------------------+
|                            ỨNG DỤNG WEB / DI ĐỘNG                                 |
|          (Nông dân khai báo thửa đất / Tài xế ghi nhận nhiệt độ lô hàng)           |
+-----------------------------------------------------------------------------------+
                                         |
                                    REST API (FastAPI)
                                         |
+----------------------------------------v------------------------------------------+
|                              CORE ENGINE DỰ ÁN                                    |
|                                                                                   |
|  +---------------------------+             +-----------------------------------+  |
|  |     Multi-tenant Core     |             |         Hash Chain Service        |  |
|  | (Cách ly HTX-DT / HTX-TG) |             |       (Append-only Logger)        |  |
|  +---------------------------+             +-----------------------------------+  |
|                |                                             |                    |
|                +--------------------+  +---------------------+                    |
|                                     |  |                                          |
|                                     v  v                                          |
|  +-----------------------------------------------------------------------------+  |
|  | CƠ SỞ DỮ LIỆU QUAN HỆ (SQLAlchemy / PostgreSQL / SQLite)                     |  |
|  |                                                                             |  |
|  |  +-----------------------+     +-----------------------------------------+  |  |
|  |  | audit_logs / chain    |     | farms / batches                         |  |  |
|  |  | - id                  |     | - id                                    |  |  |
|  |  | - prev_hash           |     | - organization_id (khóa ngoại cô lập)   |  |  |
|  |  | - record_hash         |     | - coordinates, area > 0                 |  |  |
|  |  | - payload_json        |     +-----------------------------------------+  |  |
|  |  | - created_at          |                                                  |  |
|  |  +-----------------------+                                                  |  |
|  +-----------------------------------------------------------------------------+  |
+-----------------------------------------------------------------------------------+
```

### Công thức tính toán của mỗi Node trong chuỗi:
$$\text{payload} = \{\text{entity}, \text{action}, \text{entity\_id}, \text{user\_id}, \text{org\_id}, \text{timestamp}\}$$
$$\text{current\_hash} = \text{SHA-256}(\text{prev\_hash} \parallel \text{JSON}(\text{payload}))$$

Bản ghi đầu tiên (*Genesis Record*) có `prev_hash = "0" * 64`.

---

## 5. Kết Luận & Quyết Định Kỹ Thuật (Architecture Decision)

- **Quyết định:** Sử dụng **Append-only Hash Chain (SHA-256)** cho toàn bộ mô-đun ghi nhật ký kiểm toán (*Audit Trail*) và giám sát chuỗi lạnh của dự án TTCS.
- **Lợi ích:**
  1. Đáp ứng 100% mục tiêu bảo vệ tính toàn vẹn dữ liệu, chống chỉnh sửa dữ liệu kho lạnh/nhật ký canh tác.
  2. Thời gian triển khai nhanh, độ tin cậy cao, dễ bảo trì, chi phí hạ tầng = 0.
  3. Dễ dàng tích hợp với kiểm thử tự động (Unit Test / Integration Test) trong CI/CD.
  4. Mở đường cho việc tích hợp Public Timestamping trong các sprint sau nếu thị trường xuất khẩu yêu cầu.
