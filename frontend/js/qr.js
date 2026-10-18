/**
 * AgriTrace - Chức năng sinh và in mã QR truy xuất nguồn gốc (Task S-46 / Epic E-08)
 *
 * Tính năng:
 * 1. Tự động tích hợp nút "In mã QR" vào modal chi tiết lô nông sản (#modal-batch-details).
 * 2. Gọi API backend `/batches/{id}/qr` nhận dữ liệu ảnh Base64 / PNG / SVG.
 * 3. Hiển thị modal trực quan với kích thước tem in tiêu chuẩn 3cm x 3cm theo S-46.
 * 4. Hỗ trợ tải tệp PNG độ nét cao, vector SVG cho thiết kế bao bì, và in tem nhãn trực tiếp.
 * 5. Cung cấp API window.agriTraceQr cho các module khác sử dụng linh hoạt.
 */
(function () {
  "use strict";

  const getApiBase = () => window.AGRITRACE_CONFIG?.apiBase || "http://127.0.0.1:8000";

  // State
  let currentQrData = null;

  /**
   * Gọi API sinh mã QR cho một lô nông sản theo ID
   */
  async function fetchBatchQr(batchId, format = "base64", baseUrl = null) {
    const params = new URLSearchParams({ format });
    if (baseUrl) params.append("base_url", baseUrl);

    const path = `/batches/${encodeURIComponent(batchId)}/qr?${params.toString()}`;

    if (typeof window.apiRequest === "function") {
      return await window.apiRequest(path);
    }

    // Fallback fetch nếu gọi ngoài môi trường app.js
    const response = await fetch(`${getApiBase()}${path}`, {
      credentials: "include",
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Lỗi khi sinh mã QR (${response.status})`);
    }
    return await response.json();
  }

  /**
   * Gọi API sinh mã QR tùy biến từ chuỗi dữ liệu bất kỳ
   */
  async function fetchCustomQr(data, format = "base64", options = {}) {
    const payload = {
      data: String(data).trim(),
      format,
      box_size: options.box_size || 10,
      border: options.border || 4,
      error_correction: options.error_correction || "M",
    };

    if (typeof window.apiRequest === "function") {
      return await window.apiRequest("/batches/qr/generate", {
        method: "POST",
        body: payload,
      });
    }

    const response = await fetch(`${getApiBase()}/batches/qr/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      credentials: "include",
    });
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || `Lỗi khi sinh mã QR (${response.status})`);
    }
    return await response.json();
  }

  /**
   * Tạo và chèn giao diện Modal Mã QR vào body (nếu chưa có)
   */
  function ensureQrModalDom() {
    if (document.getElementById("modal-batch-qr")) return;

    const modalHtml = `
      <div id="modal-batch-qr" class="modal-backdrop" hidden>
        <div class="modal" role="dialog" aria-modal="true" aria-labelledby="qr-modal-title" style="max-width: 540px; border-radius: 12px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);">
          <header class="modal__header" style="border-bottom: 1px solid #e2e8f0; padding: 14px 20px; display: flex; align-items: center; justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 8px;">
              <span style="display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border-radius: 8px; background: #ecfdf5; color: #059669;">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="3" width="7" height="7"></rect>
                  <rect x="14" y="3" width="7" height="7"></rect>
                  <rect x="14" y="14" width="7" height="7"></rect>
                  <rect x="3" y="14" width="7" height="7"></rect>
                </svg>
              </span>
              <h3 id="qr-modal-title" class="modal__title" style="font-size: 1.15rem; font-weight: 700; margin: 0; color: #1e293b;">
                Mã QR truy xuất nguồn gốc
              </h3>
            </div>
            <button id="btn-close-qr-modal" class="modal__close" type="button" aria-label="Đóng" style="font-size: 1.5rem; background: none; border: none; cursor: pointer; color: #64748b;">&times;</button>
          </header>

          <div class="modal__body" style="padding: 20px; text-align: center;">
            <!-- Trạng thái đang tải -->
            <div id="qr-modal-loading" style="padding: 30px; color: #64748b;">
              <div class="spinner" style="display: inline-block; width: 36px; height: 36px; border: 3px solid #e2e8f0; border-top-color: #059669; border-radius: 50%; animation: spin 0.8s linear infinite; margin-bottom: 12px;"></div>
              <div>Đang khởi tạo mã QR từ hệ thống...</div>
            </div>

            <!-- Nội dung chính sau khi sinh QR -->
            <div id="qr-modal-content" hidden>
              <!-- Thông tin lô tóm tắt -->
              <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px; margin-bottom: 16px; text-align: left;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                  <span style="font-size: 0.85rem; color: #64748b;">Mã lô nông sản:</span>
                  <span id="qr-batch-code-badge" style="font-family: monospace; font-size: 1rem; font-weight: 700; color: #0f172a; background: #e2e8f0; padding: 2px 8px; border-radius: 4px;">—</span>
                </div>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <span style="font-size: 0.85rem; color: #64748b;">Sản phẩm:</span>
                  <strong id="qr-product-name" style="color: #059669; font-size: 0.95rem;">—</strong>
                </div>
              </div>

              <!-- Thẻ hiển thị ảnh QR (Mô phỏng tem in 3cm x 3cm theo S-46) -->
              <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; margin: 16px 0;">
                <div style="background: #ffffff; padding: 12px; border: 2px dashed #cbd5e1; border-radius: 12px; display: inline-block; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                  <img id="qr-image-display" src="" alt="Mã QR Truy xuất nguồn gốc" style="width: 180px; height: 180px; display: block; image-rendering: pixelated;" />
                </div>
                <div style="margin-top: 8px; font-size: 0.8rem; color: #64748b; display: flex; align-items: center; gap: 4px;">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 14 14"></polyline></svg>
                  Kích thước in khuyến nghị: <strong style="color: #334155;">3.0 cm &times; 3.0 cm</strong> (quét rõ bằng camera điện thoại)
                </div>
              </div>

              <!-- Hộp hiển thị URL truy xuất công khai -->
              <div style="margin-bottom: 20px; text-align: left;">
                <label style="display: block; font-size: 0.85rem; font-weight: 600; color: #475569; margin-bottom: 6px;">
                  Đường dẫn công khai mã hóa trong QR:
                </label>
                <div style="display: flex; gap: 6px;">
                  <input id="qr-target-url-input" type="text" readonly style="flex: 1; padding: 8px 12px; font-size: 0.85rem; border: 1px solid #cbd5e1; border-radius: 6px; background: #f1f5f9; color: #334155;" />
                  <button id="btn-copy-qr-url" class="btn btn--sm btn--light" type="button" style="white-space: nowrap; padding: 6px 12px;">
                    Sao chép
                  </button>
                </div>
              </div>

              <!-- Các nút hành động: Tải PNG, Tải SVG, In tem -->
              <div class="modal__actions" style="display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; border-top: 1px solid #e2e8f0; padding-top: 16px;">
                <button id="btn-download-qr-png" class="btn btn--primary" type="button" style="display: inline-flex; align-items: center; gap: 6px; background-color: #059669; border-color: #059669;">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                  Tải ảnh PNG
                </button>
                <button id="btn-download-qr-svg" class="btn btn--outline-primary" type="button" style="display: inline-flex; align-items: center; gap: 6px; border: 1px solid #059669; color: #059669;">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>
                  Tải vector SVG
                </button>
                <button id="btn-print-qr-label" class="btn btn--light" type="button" style="display: inline-flex; align-items: center; gap: 6px;">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 6 2 18 2 18 9"></polyline><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"></path><rect x="6" y="14" width="12" height="8"></rect></svg>
                  In tem (3cm)
                </button>
                <button id="btn-close-qr-footer" class="btn btn--ghost" type="button">
                  Đóng
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;

    document.body.insertAdjacentHTML("beforeend", modalHtml);

    // Gắn sự kiện đóng modal
    const modal = document.getElementById("modal-batch-qr");
    const closeBtn = document.getElementById("btn-close-qr-modal");
    const closeFooter = document.getElementById("btn-close-qr-footer");

    const closeModal = () => { if (modal) modal.hidden = true; };
    if (closeBtn) closeBtn.onclick = closeModal;
    if (closeFooter) closeFooter.onclick = closeModal;
    modal.onclick = (e) => { if (e.target === modal) closeModal(); };

    // Sự kiện sao chép URL
    const btnCopy = document.getElementById("btn-copy-qr-url");
    if (btnCopy) {
      btnCopy.onclick = async () => {
        const input = document.getElementById("qr-target-url-input");
        if (input && input.value) {
          try {
            await navigator.clipboard.writeText(input.value);
            notify("Đã sao chép liên kết truy xuất nguồn gốc!", "success");
          } catch {
            input.select();
            document.execCommand("copy");
            notify("Đã sao chép liên kết!", "success");
          }
        }
      };
    }

    // Sự kiện tải PNG
    const btnPng = document.getElementById("btn-download-qr-png");
    if (btnPng) {
      btnPng.onclick = () => {
        if (!currentQrData) return;
        const code = currentQrData.batch_code || "qrcode";
        downloadFile(`${getApiBase()}/batches/${currentQrData.batch_id}/qr?format=png&download=true`, `qr_${code}.png`);
      };
    }

    // Sự kiện tải SVG
    const btnSvg = document.getElementById("btn-download-qr-svg");
    if (btnSvg) {
      btnSvg.onclick = () => {
        if (!currentQrData) return;
        const code = currentQrData.batch_code || "qrcode";
        downloadFile(`${getApiBase()}/batches/${currentQrData.batch_id}/qr?format=svg&download=true`, `qr_${code}.svg`);
      };
    }

    // Sự kiện in tem QR kích cỡ 3cm
    const btnPrint = document.getElementById("btn-print-qr-label");
    if (btnPrint) {
      btnPrint.onclick = () => {
        if (!currentQrData) return;
        printQrLabelWindow(currentQrData);
      };
    }
  }

  /**
   * Helper tải tệp an toàn qua JavaScript
   */
  function downloadFile(url, filename) {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  /**
   * Thông báo (toast notification)
   */
  function notify(message, type = "info") {
    if (typeof window.toast === "function") {
      window.toast(message, type);
    } else {
      alert(message);
    }
  }

  /**
   * Cửa sổ in tem nhãn chuẩn 3cm x 3cm cho bao bì nông sản (S-46)
   */
  function printQrLabelWindow(qrData) {
    const printWindow = window.open("", "_blank", "width=450,height=500");
    if (!printWindow) {
      notify("Vui lòng cho phép popup để in tem nhãn.", "error");
      return;
    }

    const html = `
      <!DOCTYPE html>
      <html lang="vi">
      <head>
        <meta charset="utf-8">
        <title>In tem QR - ${qrData.batch_code || ""}</title>
        <style>
          @page {
            size: auto;
            margin: 0;
          }
          body {
            margin: 0;
            padding: 10px;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            background: #f8fafc;
          }
          /* Khối tem chuẩn 3cm x 3cm (tương đương khoảng 113px ở 96DPI, in ấn 300DPI) */
          .label-card {
            width: 30mm;
            height: 30mm;
            border: 1px solid #94a3b8;
            padding: 1.5mm;
            box-sizing: border-box;
            background: #fff;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: space-between;
            text-align: center;
          }
          .label-header {
            font-size: 6.5pt;
            font-weight: 700;
            text-transform: uppercase;
            color: #0f172a;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            width: 100%;
          }
          .label-qr {
            width: 18mm;
            height: 18mm;
            display: block;
            image-rendering: pixelated;
          }
          .label-footer {
            font-size: 6pt;
            font-weight: 700;
            font-family: monospace;
            color: #334155;
            letter-spacing: 0.5px;
          }
          @media print {
            body {
              background: transparent;
              height: auto;
              padding: 0;
            }
            .label-card {
              border: 1px dashed #cbd5e1;
            }
          }
        </style>
      </head>
      <body>
        <div class="label-card">
          <div class="label-header">${qrData.product_name || "AgriTrace"}</div>
          <img class="label-qr" src="${qrData.qr_base64}" alt="QR" />
          <div class="label-footer">${qrData.batch_code || ""}</div>
        </div>
        <script>
          window.onload = function() {
            setTimeout(function() {
              window.print();
              window.close();
            }, 300);
          };
        </script>
      </body>
      </html>
    `;

    printWindow.document.open();
    printWindow.document.write(html);
    printWindow.document.close();
  }

  /**
   * Mở modal và tải mã QR cho một lô cụ thể
   */
  async function openBatchQrModal(batchId) {
    if (!batchId) return;
    ensureQrModalDom();

    const modal = document.getElementById("modal-batch-qr");
    const loading = document.getElementById("qr-modal-loading");
    const content = document.getElementById("qr-modal-content");

    modal.hidden = false;
    loading.hidden = false;
    content.hidden = true;

    try {
      const data = await fetchBatchQr(batchId, "base64");
      currentQrData = data;

      document.getElementById("qr-batch-code-badge").textContent = data.batch_code || `#${batchId}`;
      document.getElementById("qr-product-name").textContent = data.product_name || "Nông sản sạch";
      document.getElementById("qr-image-display").src = data.qr_base64;
      document.getElementById("qr-target-url-input").value = data.target_url;

      loading.hidden = true;
      content.hidden = false;
    } catch (err) {
      modal.hidden = true;
      notify(`Không thể tạo mã QR: ${err.message}`, "error");
    }
  }

  /**
   * Tự động kiểm tra và gắn nút "In mã QR" vào modal chi tiết lô nếu có
   */
  function attachQrButtonToBatchDetailModal() {
    const actionGroup = document.getElementById("detail-action-buttons-group");
    if (!actionGroup) return;

    if (document.getElementById("btn-detail-qr")) return;

    const qrBtn = document.createElement("button");
    qrBtn.id = "btn-detail-qr";
    qrBtn.className = "btn btn--outline-primary";
    qrBtn.type = "button";
    qrBtn.style.cssText = "border: 1px solid #059669; color: #059669; display: inline-flex; align-items: center; gap: 6px;";
    qrBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="7" height="7"></rect>
        <rect x="14" y="3" width="7" height="7"></rect>
        <rect x="14" y="14" width="7" height="7"></rect>
        <rect x="3" y="14" width="7" height="7"></rect>
      </svg>
      In mã QR
    `;

    qrBtn.onclick = () => {
      const batchId = window.currentDetailBatchId;
      if (batchId) {
        openBatchQrModal(batchId);
      } else {
        notify("Vui lòng chọn lô nông sản để sinh mã QR.", "warning");
      }
    };

    // Chèn nút vào nhóm hành động trong modal chi tiết
    actionGroup.appendChild(qrBtn);
  }

  // Lắng nghe DOM để gắn nút khi modal chi tiết được mở
  document.addEventListener("DOMContentLoaded", () => {
    attachQrButtonToBatchDetailModal();

    // Quan sát MutationObserver phòng khi giao diện render lại
    const observer = new MutationObserver(() => {
      attachQrButtonToBatchDetailModal();
    });

    const target = document.getElementById("modal-batch-details") || document.body;
    observer.observe(target, { childList: true, subtree: true });
  });

  // Xuất API toàn cục
  window.agriTraceQr = {
    openBatchQr: openBatchQrModal,
    fetchBatchQr,
    fetchCustomQr,
    printQrLabel: printQrLabelWindow,
  };
})();
