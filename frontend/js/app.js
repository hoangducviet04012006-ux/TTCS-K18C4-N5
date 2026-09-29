/* =====================================================================
   Frontend demo - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản
   JavaScript thuần (không framework, không thư viện ngoài).
   Cấu trúc: cấu hình -> tiện ích -> gọi API -> trạng thái -> render -> sự kiện.
   ===================================================================== */

"use strict";

/* ---------------------------------------------------------- 1. Cấu hình --- */
// Địa chỉ backend FastAPI (đổi ở đây nếu chạy cổng khác).
const API_BASE_URL = "http://127.0.0.1:8000";

/* ---------------------------------------------------------- 2. Tiện ích --- */
/** Lấy element theo id cho ngắn gọn. */
const $ = (id) => document.getElementById(id);

/** Chống XSS: escape dữ liệu do người dùng nhập trước khi chèn vào HTML. */
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** 120.5 -> "120,5" (định dạng số kiểu Việt Nam). */
function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("vi-VN").format(number) : "—";
}

/** "2026-01-15" (từ input type=date / API) -> "15/01/2026". */
function formatDate(value) {
  if (!value) return "—";
  const parts = String(value).split("-");
  return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : String(value);
}

const TOAST_DURATION_MS = 4500;

/** Hiển thị thông báo ở góc phải trên: type = "success" | "error" | "info". */
function toast(message, type = "info") {
  const container = $("toast-container");
  const element = document.createElement("div");
  element.className = `toast toast--${type}`;
  element.setAttribute("role", type === "error" ? "alert" : "status");
  element.textContent = message;
  container.appendChild(element);
  window.setTimeout(() => element.remove(), TOAST_DURATION_MS);
}

/** Bật/tắt trạng thái "đang gửi" của nút submit (tránh bấm 2 lần). */
function setButtonLoading(button, isLoading, loadingText, idleText) {
  button.disabled = isLoading;
  button.textContent = isLoading ? loadingText : idleText;
}

/* -------------------------------------------------------- 3. Gọi API --- */
/**
 * Gọi API backend và trả về dữ liệu JSON.
 * Ném Error với thông điệp tiếng Việt dễ đọc nếu request thất bại.
 */
async function apiRequest(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    throw new Error(
      `Không kết nối được backend (${API_BASE_URL}). Hãy chắc chắn uvicorn đang chạy.`
    );
  }

  const data = await readJson(response);
  if (!response.ok) {
    throw new Error(describeError(data, response.status));
  }
  return data;
}

/** Đọc JSON an toàn (response lỗi có thể không phải JSON). */
async function readJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return null;
  }
}

/** Chuyển lỗi của FastAPI (`detail`) thành câu thông báo dễ hiểu. */
function describeError(data, status) {
  const detail = data ? data.detail : null;

  // Lỗi nghiệp vụ: 404 farm không tồn tại, 500 lỗi database...
  if (typeof detail === "string") {
    return detail;
  }

  // Lỗi validate của Pydantic (422): detail là mảng các lỗi.
  if (Array.isArray(detail)) {
    return detail
      .map((item) => `${(item.loc || []).join(".")}: ${item.msg}`)
      .join(" | ");
  }

  return `Yêu cầu thất bại (HTTP ${status}).`;
}

/* ------------------------------------------------------- 4. Trạng thái --- */
let farms = [];
let batches = [];

/* ------------------------------------------- 5. Kiểm tra backend sống --- */
async function checkHealth() {
  const badge = $("health-badge");
  try {
    const data = await apiRequest("/health");
    badge.textContent = `Backend: ${data.status}`;
    badge.className = "badge badge--ok";
  } catch (error) {
    badge.textContent = "Backend: không kết nối được";
    badge.className = "badge badge--error";
    toast(error.message, "error");
  }
}

/* ------------------------------------------------------- 6. Vùng trồng --- */
/** GET /farms -> cập nhật bảng danh sách + select vùng trồng của form lô. */
async function loadFarms() {
  try {
    const data = await apiRequest("/farms");
    farms = Array.isArray(data) ? data : [];
    renderFarms();
    renderFarmOptions();
  } catch (error) {
    toast(`Không tải được danh sách vùng trồng: ${error.message}`, "error");
  }
}

/** Vẽ bảng danh sách vùng trồng. */
function renderFarms() {
  $("farm-table-body").innerHTML = farms
    .map(
      (farm) => `
      <tr>
        <td class="id-cell">${escapeHtml(farm.id)}</td>
        <td>${escapeHtml(farm.name)}</td>
        <td>${escapeHtml(farm.location)}</td>
        <td class="is-right">${formatNumber(farm.area)}</td>
        <td>${escapeHtml(farm.owner)}</td>
      </tr>`
    )
    .join("");

  $("farm-empty").hidden = farms.length > 0;
  $("stat-farms").textContent = farms.length;
}

/** Đổ danh sách vùng trồng vào select `farm_id` của form tạo lô. */
function renderFarmOptions() {
  const select = $("batch-farm-id");
  const selected = select.value;

  if (farms.length === 0) {
    select.innerHTML = '<option value="">— Chưa có vùng trồng, hãy thêm ở mục 1 —</option>';
    select.disabled = true;
    return;
  }

  select.disabled = false;
  select.innerHTML = farms
    .map(
      (farm) =>
        `<option value="${escapeHtml(farm.id)}">#${escapeHtml(farm.id)} — ${escapeHtml(farm.name)}</option>`
    )
    .join("");

  // Giữ lại lựa chọn cũ nếu vùng trồng đó vẫn còn.
  if (selected && farms.some((farm) => String(farm.id) === selected)) {
    select.value = selected;
  }
}

/** Xử lý submit form "Thêm vùng trồng" -> POST /farms. */
async function handleFarmSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  const payload = {
    name: $("farm-name").value.trim(),
    location: $("farm-location").value.trim(),
    area: Number($("farm-area").value),
    owner: $("farm-owner").value.trim(),
  };

  const button = $("farm-submit");
  setButtonLoading(button, true, "Đang lưu…", "Thêm vùng trồng");

  try {
    const created = await apiRequest("/farms", { method: "POST", body: payload });
    form.reset();
    toast(`Thêm thành công vùng trồng #${created.id}: ${created.name}`, "success");
    await loadFarms();
    $("farm-name").focus();
  } catch (error) {
    toast(`Thêm vùng trồng thất bại: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Đang lưu…", "Thêm vùng trồng");
  }
}

/* ------------------------------------------------------ 7. Lô nông sản --- */
/** GET /batches -> cập nhật bảng danh sách lô. */
async function loadBatches() {
  try {
    const data = await apiRequest("/batches");
    batches = Array.isArray(data) ? data : [];
    renderBatches();
  } catch (error) {
    toast(`Không tải được danh sách lô nông sản: ${error.message}`, "error");
  }
}

/** Nhãn vùng trồng cho bảng lô (dùng lại dữ liệu đã tải từ GET /farms). */
function farmLabel(farmId) {
  const farm = farms.find((item) => item.id === farmId);
  return farm ? `#${farmId} — ${farm.name}` : `#${farmId}`;
}

/** Vẽ bảng danh sách lô nông sản. */
function renderBatches() {
  $("batch-table-body").innerHTML = batches
    .map(
      (batch) => `
      <tr>
        <td class="id-cell">${escapeHtml(batch.id)}</td>
        <td>${escapeHtml(farmLabel(batch.farm_id))}</td>
        <td>${escapeHtml(batch.product_name)}</td>
        <td class="is-right">${formatNumber(batch.quantity)}</td>
        <td>${escapeHtml(formatDate(batch.harvest_date))}</td>
      </tr>`
    )
    .join("");

  $("batch-empty").hidden = batches.length > 0;
  $("stat-batches").textContent = batches.length;
}

/** Xử lý submit form "Tạo lô nông sản" -> POST /batches. */
async function handleBatchSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  const farmSelect = $("batch-farm-id");
  if (!farmSelect.value) {
    toast("Chưa có vùng trồng nào. Hãy thêm vùng trồng ở mục 1 trước khi tạo lô.", "error");
    return;
  }

  const payload = {
    farm_id: Number(farmSelect.value),
    product_name: $("batch-product-name").value.trim(),
    quantity: Number($("batch-quantity").value),
    harvest_date: $("batch-harvest-date").value,
  };

  const button = $("batch-submit");
  setButtonLoading(button, true, "Đang lưu…", "Tạo lô nông sản");

  try {
    const created = await apiRequest("/batches", { method: "POST", body: payload });
    form.reset();
    farmSelect.value = String(created.farm_id); // giữ lại vùng trồng vừa chọn
    toast(
      `Tạo thành công lô #${created.id} "${created.product_name}" cho vùng trồng #${created.farm_id}`,
      "success"
    );
    await loadBatches();
  } catch (error) {
    toast(`Tạo lô nông sản thất bại: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Đang lưu…", "Tạo lô nông sản");
  }
}

/* ----------------------------------------------------------- 8. Sự kiện --- */
function bindEvents() {
  $("farm-form").addEventListener("submit", handleFarmSubmit);
  $("batch-form").addEventListener("submit", handleBatchSubmit);
  $("btn-reload").addEventListener("click", reloadAll);
}

/** Tải lại toàn bộ dữ liệu: trạng thái backend + vùng trồng + lô nông sản. */
async function reloadAll() {
  const button = $("btn-reload");
  setButtonLoading(button, true, "Đang tải…", "Tải lại dữ liệu");

  await checkHealth();
  await loadFarms(); // phải chạy trước để bảng lô hiển thị được tên vùng trồng
  await loadBatches();

  setButtonLoading(button, false, "Đang tải…", "Tải lại dữ liệu");
  toast(`Đã tải lại: ${farms.length} vùng trồng, ${batches.length} lô nông sản.`, "info");
}

/* --------------------------------------------------------- 9. Khởi động --- */
async function init() {
  $("stat-api").textContent = API_BASE_URL;
  bindEvents();
  await checkHealth();
  await loadFarms();
  await loadBatches();
}

document.addEventListener("DOMContentLoaded", init);
