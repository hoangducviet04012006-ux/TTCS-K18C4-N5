/* =====================================================================
   Frontend demo - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản
   JavaScript thuần (không framework, không thư viện ngoài).
   Cấu trúc: cấu hình -> tiện ích -> gọi API -> trạng thái -> render -> sự kiện.
   ===================================================================== */

"use strict";

/* ---------------------------------------------------------- 1. Cấu hình --- */
// Địa chỉ backend FastAPI (đổi ở đây nếu chạy cổng khác).
const API_BASE_URL = "http://127.0.0.1:8000";

// Khoá lưu phiên đăng nhập trong sessionStorage (tự mất khi đóng tab).
const SESSION_STORAGE_KEY = "ttcs.session";

// Tên vai trò admin do backend quy định (dùng để phân quyền ở giao diện).
const ROLE_ADMIN = "admin";

/* ---------------------------------------------------------- 2. Tiện ích --- */
/** Lấy element theo id cho ngắn gọn. */
const $ = (id) => document.getElementById(id);

/**
 * Bật/tắt hiển thị của phần tử theo id (dùng trong `applySessionToUi`).
 *
 * Vì sao không viết thẳng `$(id).hidden = ...`: nếu index.html thiếu id đó -
 * thường do trình duyệt còn cache bản `app.js` cũ hoặc bản HTML cũ, tức HTML
 * và app.js lệch phiên bản - thì `$(id)` là null và câu lệnh sẽ ném lỗi làm
 * `applySessionToUi` dừng giữa đường: các mục phía sau (trong đó có
 * "3. Lịch sử thao tác") không bao giờ được bật mà cũng không thấy báo lỗi.
 * Hàm này chỉ cảnh báo trong Console rồi bỏ qua để giao diện còn lại vẫn chạy.
 */
function setHidden(id, hidden) {
  const element = $(id);
  if (element === null) {
    console.warn(
      `[frontend] Không tìm thấy #${id} trong index.html — HTML và app.js có thể ` +
      "lệch phiên bản (nhấn Ctrl+F5 để tải lại bản mới)."
    );
    return;
  }
  element.hidden = hidden;
}

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

/**
 * "2026-09-30T14:20:05.123456" (backend lưu UTC, **không** kèm múi giờ) ->
 * "30/09/2026 21:20:05" (giờ của máy người dùng, Sprint 7).
 *
 * Cách làm: đọc các thành phần ngày/giờ của chuỗi bằng regex (tránh việc mỗi
 * trình duyệt parse phần giây lẻ `.123456` một kiểu), dựng `Date` theo **UTC**
 * rồi lấy các thành phần theo giờ địa phương. Chuỗi lạ -> trả về nguyên bản.
 */
function formatDateTime(value) {
  if (!value) return "—";

  const text = String(value);
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
  if (match === null) {
    return text;
  }

  const [, year, month, day, hour, minute, second] = match;
  const date = new Date(
    Date.UTC(Number(year), Number(month) - 1, Number(day),
             Number(hour), Number(minute), Number(second || 0))
  );
  if (Number.isNaN(date.getTime())) {
    return text;
  }

  const pad = (number) => String(number).padStart(2, "0");
  return (
    `${pad(date.getDate())}/${pad(date.getMonth() + 1)}/${date.getFullYear()} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
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
 * Mặc định gửi kèm tài khoản đang đăng nhập (xác thực HTTP Basic);
 * truyền `auth: false` cho request không cần xác thực (VD: đăng nhập).
 * Ném Error với thông điệp tiếng Việt dễ đọc nếu request thất bại.
 */
async function apiRequest(path, { method = "GET", body, auth = true } = {}) {
  const headers = {};
  if (body) {
    headers["Content-Type"] = "application/json";
  }
  if (auth) {
    Object.assign(headers, authHeader());
  }

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    // `status = 0`: không có phản hồi HTTP (backend chưa chạy hoặc sai cổng).
    const offline = new Error(
      `Không kết nối được backend (${API_BASE_URL}). Hãy chắc chắn uvicorn đang chạy.`
    );
    offline.status = 0;
    throw offline;
  }

  const data = await readJson(response);
  if (!response.ok) {
    // Sprint 7: gắn mã HTTP vào Error để nơi gọi xử lý riêng 401/403 (xem
    // `loadAuditLogs`). Các đoạn `catch` cũ chỉ đọc `error.message` nên không
    // bị ảnh hưởng.
    const error = new Error(describeError(data, response.status));
    error.status = response.status;
    throw error;
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
// Dữ liệu đang hiển thị trên giao diện.
let farms = [];
let batches = [];
let users = [];
// Sprint 7: lịch sử thao tác (chỉ admin tải được - xem `loadAuditLogs`).
let auditLogs = [];

// ID bản ghi đang được SỬA trên form (null = form đang ở chế độ "thêm mới").
// Sprint 5: bấm nút "Sửa" ở bảng -> form phía trên đổ sẵn dữ liệu và nút submit
// gọi PUT thay vì POST.
let editingFarmId = null;
let editingBatchId = null;

// Phiên đăng nhập hiện tại: { username, role, password } hoặc null (chưa đăng nhập).
// Sprint 4 không dùng JWT: client giữ lại thông tin đăng nhập để gửi kèm header
// `Authorization: Basic ...` trong mỗi request.
let session = null;

/* --------------------------------------------------------- 5. Đăng nhập --- */
/**
 * Mã hoá chuỗi "username:password" sang Base64 theo chuẩn HTTP Basic.
 * Dùng TextEncoder để hỗ trợ tiếng Việt (btoa chỉ nhận ký tự Latin-1).
 */
function encodeBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

/** Header xác thực của tài khoản đang đăng nhập (rỗng nếu chưa đăng nhập). */
function authHeader() {
  if (session === null) {
    return {};
  }
  const token = encodeBase64(`${session.username}:${session.password}`);
  return { Authorization: `Basic ${token}` };
}

/** POST /auth/login - kiểm tra tài khoản; ném Error nếu sai (backend trả 401). */
function requestLogin(username, password) {
  return apiRequest("/auth/login", {
    method: "POST",
    body: { username, password },
    auth: false, // request đăng nhập không gửi kèm header của phiên cũ
  });
}

/** Lưu phiên đăng nhập vào bộ nhớ + sessionStorage (giữ được khi F5 trong tab). */
function startSession({ username, role, password, organization_id, organization_name }) {
  session = { username, role, password, organization_id, organization_name };
  window.sessionStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({ username, password, organization_id, organization_name })
  );
  applySessionToUi();
}

/** Đọc phiên đăng nhập đã lưu trong tab; trả null nếu chưa có hoặc dữ liệu hỏng. */
function restoreSession() {
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    const saved = raw ? JSON.parse(raw) : null;
    if (saved && saved.username && saved.password) {
      return saved;
    }
  } catch (error) {
    // Dữ liệu lưu không hợp lệ -> coi như chưa đăng nhập.
  }
  return null;
}

/** Xoá phiên đăng nhập khỏi bộ nhớ và sessionStorage. */
function clearSession() {
  session = null;
  window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
}

/**
 * Cập nhật giao diện theo trạng thái đăng nhập, vai trò (role) và tổ chức:
 * - chưa đăng nhập: chỉ hiện màn hình login;
 * - farmer: hiện chức năng quản lý nông sản (thửa đất, lô nông sản) của tổ chức mình;
 * - admin: hiện toàn bộ, thêm mục quản trị tài khoản;
 * - hiển thị logo/tên tổ chức của user đang hoạt động.
 */
function applySessionToUi() {
  const isLoggedIn = session !== null;
  const adminUser = isAdmin();

  setHidden("login-view", isLoggedIn);
  setHidden("app-view", !isLoggedIn);
  setHidden("btn-reload", !isLoggedIn);
  setHidden("btn-logout", !isLoggedIn);
  setHidden("user-badge", !isLoggedIn);
  setHidden("org-badge", !isLoggedIn || !session?.organization_name);

  const orgBadge = $("org-badge");
  if (orgBadge !== null && isLoggedIn && session?.organization_name) {
    orgBadge.textContent = `🏢 ${session.organization_name}`;
  }

  const badge = $("user-badge");
  if (badge !== null && isLoggedIn) {
    const roleText = adminUser ? "Quản trị viên" : "Chủ nông hộ / Nông dân";
    badge.textContent = `👤 ${session.username} (${roleText})`;
    badge.className = adminUser ? "badge badge--ok" : "badge badge--muted";
  }

  const orgContext = $("farm-org-context");
  if (orgContext !== null && isLoggedIn) {
    orgContext.textContent = `Các thửa đất thuộc: ${session.organization_name || "Tổ chức của bạn"}`;
  }

  setHidden("users-card", !adminUser);
  setHidden("audit-card", !adminUser);
  setHidden("stat-audit-card", !adminUser);
}

/** Phiên hiện tại có phải tài khoản **admin** không (dùng cho chức năng chỉ admin). */
function isAdmin() {
  return session !== null && session.role === ROLE_ADMIN;
}

/**
 * Quyền xoá dữ liệu ở giao diện: **chỉ admin** (Sprint 5).
 * Farmer dùng giao diện sẽ không thấy nút Xoá; nếu cố gọi API xoá thì backend
 * trả `403 Forbidden` (`require_admin`) - đây chỉ là lớp bảo vệ ở UI.
 */
function canDelete() {
  return isAdmin();
}

/** Xử lý submit form đăng nhập -> POST /auth/login. */
async function handleLoginSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  const username = $("login-username").value.trim();
  const password = $("login-password").value; // không trim mật khẩu

  const button = $("login-submit");
  setButtonLoading(button, true, "Đang kiểm tra…", "Đăng nhập");

  try {
    const data = await requestLogin(username, password);
    startSession({
      username: data.username,
      role: data.role,
      password,
      organization_id: data.organization_id,
      organization_name: data.organization_name,
    });
    form.reset();
    const orgGreeting = data.organization_name ? ` · ${data.organization_name}` : "";
    toast(`Đăng nhập thành công! Xin chào ${data.username}${orgGreeting}.`, "success");
    await reloadAll({ silent: true });
  } catch (error) {
    if (error.status === 401) {
      toast("Sai tên đăng nhập hoặc mật khẩu. Vui lòng kiểm tra lại!", "error");
    } else {
      toast(error.message, "error");
    }
    $("login-password").select();
  } finally {
    setButtonLoading(button, false, "Đang kiểm tra…", "Đăng nhập");
  }
}

/** Đăng xuất: xoá phiên, xoá dữ liệu đang hiển thị và quay về màn hình login. */
function handleLogout() {
  const username = session ? session.username : "";
  clearSession();

  farms = [];
  batches = [];
  users = [];
  auditLogs = [];
  resetFarmForm();
  resetBatchForm();
  renderFarms();
  renderFarmOptions();
  renderBatches();
  renderUsers();
  renderAuditLogs();

  applySessionToUi();
  toast(username ? `Đã đăng xuất tài khoản ${username}.` : "Đã đăng xuất.", "info");
  $("login-username").focus();
}

/* ------------------------------------------- 6. Kiểm tra backend sống --- */
async function checkHealth() {
  const badge = $("health-badge");
  try {
    const data = await apiRequest("/health");
    badge.textContent = "Hệ thống trực tuyến";
    badge.className = "badge badge--ok";
  } catch (error) {
    badge.textContent = "Mất kết nối máy chủ";
    badge.className = "badge badge--error";
    toast("Không kết nối được tới máy chủ API: " + error.message, "error");
  }
}

/* ------------------------------------------------------- 7. Vùng trồng --- */
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

let farmViewMode = "cards"; // "cards" | "table"

/** Chuyển đổi giữa chế độ xem Dạng Thẻ và Dạng Bảng */
function setFarmViewMode(mode) {
  farmViewMode = mode;
  const isCards = mode === "cards";
  const btnCards = $("btn-view-cards");
  const btnTable = $("btn-view-table");

  if (btnCards && btnTable) {
    btnCards.className = isCards ? "btn btn--sm btn--active" : "btn btn--sm btn--light";
    btnTable.className = !isCards ? "btn btn--sm btn--active" : "btn btn--sm btn--light";
  }

  setHidden("farm-cards-container", !isCards);
  setHidden("farm-table-wrap", isCards);
}

/** Vẽ danh sách thửa đất (cả dạng thẻ trực quan và dạng bảng chi tiết). */
function renderFarms() {
  const cardsContainer = $("farm-cards-container");
  const tableBody = $("farm-table-body");

  // 1. Dạng Thẻ (Cards) - trực quan, tối ưu cho nông dân
  if (cardsContainer) {
    cardsContainer.innerHTML = farms
      .map(
        (farm) => `
        <article class="farm-card ${farm.id === editingFarmId ? "is-editing" : ""}">
          <div class="farm-card__header">
            <div class="farm-card__title-group">
              <span class="farm-card__icon">🌾</span>
              <h4 class="farm-card__name">${escapeHtml(farm.name)}</h4>
            </div>
            <span class="farm-card__area-badge">${formatNumber(farm.area)} ha</span>
          </div>
          <div class="farm-card__body">
            <div class="farm-card__meta">
              <span class="meta-label">📍 Vị trí:</span>
              <span class="meta-value">${escapeHtml(farm.location)}</span>
            </div>
            <div class="farm-card__meta">
              <span class="meta-label">🌐 Tọa độ GPS:</span>
              <span class="meta-value">${farm.coordinates ? escapeHtml(farm.coordinates) : '<em style="color:#9ca3af">Chưa cập nhật</em>'}</span>
            </div>
            <div class="farm-card__meta">
              <span class="meta-label">👤 Nông hộ phụ trách:</span>
              <span class="meta-value">${escapeHtml(farm.owner)}</span>
            </div>
          </div>
          <div class="farm-card__footer">
            <button class="btn btn--primary btn--sm" type="button"
                    data-action="edit" data-entity="farm"
                    data-id="${escapeHtml(farm.id)}">✏️ Sửa</button>
            ${
              canDelete()
                ? `<button class="btn btn--danger btn--sm" type="button"
                    data-action="delete" data-entity="farm"
                    data-id="${escapeHtml(farm.id)}">🗑️ Xoá</button>`
                : ""
            }
          </div>
        </article>`
      )
      .join("");
  }

  // 2. Dạng Bảng (Table)
  if (tableBody) {
    tableBody.innerHTML = farms
      .map(
        (farm) => `
        <tr class="${farm.id === editingFarmId ? "is-editing" : ""}">
          <td><strong>${escapeHtml(farm.name)}</strong></td>
          <td>${escapeHtml(farm.location)}</td>
          <td>${farm.coordinates ? escapeHtml(farm.coordinates) : '<em style="color:#9ca3af">—</em>'}</td>
          <td class="is-right">${formatNumber(farm.area)}</td>
          <td>${escapeHtml(farm.owner)}</td>
          <td>
            <div class="table__actions">
              <button class="btn btn--primary btn--sm" type="button"
                      data-action="edit" data-entity="farm"
                      data-id="${escapeHtml(farm.id)}">Sửa</button>
              ${
                canDelete()
                  ? `<button class="btn btn--danger btn--sm" type="button"
                      data-action="delete" data-entity="farm"
                      data-id="${escapeHtml(farm.id)}">Xoá</button>`
                  : ""
              }
            </div>
          </td>
        </tr>`
      )
      .join("");
  }

  $("farm-empty").hidden = farms.length > 0;
  setFarmViewMode(farmViewMode);
  renderStats();
}

/** Đổ danh sách vùng trồng vào select `farm_id` của form tạo lô. */
function renderFarmOptions() {
  const select = $("batch-farm-id");
  const selected = select.value;

  if (farms.length === 0) {
    select.innerHTML = '<option value="">— Chưa có thửa đất nào, hãy thêm thửa đất trước —</option>';
    select.disabled = true;
    return;
  }

  select.disabled = false;
  select.innerHTML = farms
    .map(
      (farm) =>
        `<option value="${escapeHtml(farm.id)}">${escapeHtml(farm.name)} (${formatNumber(farm.area)} ha)</option>`
    )
    .join("");

  // Giữ lại lựa chọn cũ nếu vùng trồng đó vẫn còn.
  if (selected && farms.some((farm) => String(farm.id) === selected)) {
    select.value = selected;
  }
}

/** Nhãn nút submit form vùng trồng theo chế độ hiện tại (thêm mới / sửa). */
function farmSubmitLabel() {
  return editingFarmId === null ? "Thêm thửa đất" : "Cập nhật thửa đất";
}

/**
 * Xử lý submit form vùng trồng:
 * - chế độ thêm mới (`editingFarmId === null`) -> POST /farms;
 * - chế độ sửa (đã bấm nút "Sửa" ở bảng)       -> PUT /farms/{id}.
 */
async function handleFarmSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  const area = Number($("farm-area").value);
  if (isNaN(area) || area <= 0) {
    toast("Diện tích thửa đất bắt buộc phải lớn hơn 0 ha!", "error");
    $("farm-area").focus();
    return;
  }

  const payload = {
    name: $("farm-name").value.trim(),
    location: $("farm-location").value.trim(),
    area: area,
    coordinates: $("farm-coordinates").value.trim() || null,
    owner: $("farm-owner").value.trim(),
  };

  const isEditing = editingFarmId !== null;
  const button = $("farm-submit");
  setButtonLoading(button, true, "Đang lưu…", farmSubmitLabel());

  try {
    if (isEditing) {
      const updated = await apiRequest(`/farms/${editingFarmId}`, { method: "PUT", body: payload });
      toast(`Đã cập nhật thửa đất: ${updated.name}`, "success");
    } else {
      const created = await apiRequest("/farms", { method: "POST", body: payload });
      toast(`Thêm thành công thửa đất: ${created.name}`, "success");
    }
    resetFarmForm(); // về lại chế độ "thêm mới"
    await loadFarms(); // cập nhật danh sách thửa đất và select lô nông sản
    await loadBatches();
    await refreshAuditLogsIfAdmin();
    $("farm-name").focus();
  } catch (error) {
    toast(`${isEditing ? "Cập nhật" : "Thêm"} thửa đất thất bại: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Đang lưu…", farmSubmitLabel());
  }
}

/** Đưa form vùng trồng về chế độ "thêm mới" (bỏ dữ liệu đang sửa). */
function resetFarmForm() {
  editingFarmId = null;
  $("farm-form").reset();
  $("farm-form-mode").hidden = true;
  $("farm-cancel").hidden = true;
  $("farm-submit").textContent = farmSubmitLabel();
}

/**
 * Bấm nút "Sửa" ở bảng/thẻ -> đổ dữ liệu vùng trồng lên form và chuyển sang chế độ sửa.
 */
function startEditFarm(farmId) {
  const farm = farms.find((item) => item.id === farmId);
  if (!farm) {
    toast(`Không tìm thấy thửa đất #${farmId} trong dữ liệu đang hiển thị.`, "error");
    return;
  }

  editingFarmId = farm.id;
  $("farm-name").value = farm.name;
  $("farm-location").value = farm.location;
  $("farm-area").value = farm.area;
  $("farm-coordinates").value = farm.coordinates || "";
  $("farm-owner").value = farm.owner;

  const mode = $("farm-form-mode");
  mode.textContent = `Đang sửa thửa đất: ${farm.name}. Bấm "Cập nhật thửa đất" để lưu.`;
  mode.hidden = false;
  $("farm-cancel").hidden = false;
  $("farm-submit").textContent = farmSubmitLabel();

  renderFarms(); // tô viền card/dòng đang sửa
  $("farm-form").scrollIntoView({ behavior: "smooth", block: "start" });
  $("farm-name").focus();
}

/**
 * Xoá vùng trồng (chỉ admin) -> ``DELETE /farms/{id}``.
 * Backend xoá kèm mọi lô nông sản của vùng đó nên giao diện phải tải lại cả
 * hai bảng; số lô bị xoá kèm được backend trả về trong ``deleted_batches``.
 */
async function deleteFarm(farmId) {
  const farm = farms.find((item) => item.id === farmId);
  const label = farm ? `#${farm.id} — ${farm.name}` : `#${farmId}`;
  const childCount = batches.filter((batch) => batch.farm_id === farmId).length;

  const question =
    `Bạn có chắc chắn muốn xoá vùng trồng ${label}?` +
    (childCount > 0 ? `\nLưu ý: Toàn bộ ${childCount} lô nông sản trực thuộc vùng này cũng sẽ bị xoá theo.` : "") +
    "\nHành động này không thể hoàn tác.";
  if (!window.confirm(question)) {
    return;
  }

  try {
    const result = await apiRequest(`/farms/${farmId}`, { method: "DELETE" });
    toast(result && result.message ? result.message : `Đã xoá vùng trồng #${farmId}.`, "success");

    if (editingFarmId === farmId) {
      resetFarmForm(); // vùng trồng đang sửa đã bị xoá -> form về chế độ thêm mới
    }
    await loadFarms();
    await loadBatches(); // các lô của vùng trồng vừa xoá cũng biến mất
    await refreshAuditLogsIfAdmin(); // Sprint 7: vừa xoá -> cập nhật lịch sử
  } catch (error) {
    toast(`Xoá vùng trồng thất bại: ${error.message}`, "error");
  }
}

/* ------------------------------------------------------ 8. Lô nông sản --- */
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

/** Vẽ bảng danh sách lô nông sản (kèm cột "Thao tác": Sửa/Xoá). */
function renderBatches() {
  $("batch-table-body").innerHTML = batches
    .map(
      (batch) => `
      <tr class="${batch.id === editingBatchId ? "is-editing" : ""}">
        <td class="id-cell">#${escapeHtml(batch.id)}</td>
        <td>${escapeHtml(farmLabel(batch.farm_id))}</td>
        <td><strong>${escapeHtml(batch.product_name)}</strong></td>
        <td class="is-right">${formatNumber(batch.quantity)}</td>
        <td>${escapeHtml(formatDate(batch.harvest_date))}</td>
        <td>
          <div class="table__actions">
            <button class="btn btn--primary btn--sm" type="button"
                    data-action="edit" data-entity="batch"
                    data-id="${escapeHtml(batch.id)}">Sửa</button>
            ${
              canDelete()
                ? `<button class="btn btn--danger btn--sm" type="button"
                    data-action="delete" data-entity="batch"
                    data-id="${escapeHtml(batch.id)}">Xoá</button>`
                : ""
            }
          </div>
        </td>
      </tr>`
    )
    .join("");

  $("batch-empty").hidden = batches.length > 0;
  renderStats(); // thẻ "Tổng lô nông sản" + "Tổng sản lượng" lấy từ mảng `batches`
}

/** Nhãn nút submit form lô nông sản theo chế độ hiện tại (tạo mới / sửa). */
function batchSubmitLabel() {
  return editingBatchId === null ? "Tạo lô nông sản" : "Cập nhật lô nông sản";
}

/**
 * Xử lý submit form lô nông sản:
 * - chế độ tạo mới (`editingBatchId === null`) -> POST /batches;
 * - chế độ sửa (đã bấm nút "Sửa" ở bảng)       -> PUT /batches/{id}.
 */
async function handleBatchSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  const farmSelect = $("batch-farm-id");
  if (!farmSelect.value) {
    toast("Chưa có vùng trồng nào. Vui lòng thêm vùng trồng trước khi tạo lô nông sản.", "error");
    return;
  }

  const payload = {
    farm_id: Number(farmSelect.value),
    product_name: $("batch-product-name").value.trim(),
    quantity: Number($("batch-quantity").value),
    harvest_date: $("batch-harvest-date").value,
  };

  const isEditing = editingBatchId !== null;
  const button = $("batch-submit");
  setButtonLoading(button, true, "Đang lưu…", batchSubmitLabel());

  try {
    if (isEditing) {
      const updated = await apiRequest(`/batches/${editingBatchId}`, { method: "PUT", body: payload });
      toast(`Đã cập nhật lô #${updated.id} "${updated.product_name}"`, "success");
    } else {
      const created = await apiRequest("/batches", { method: "POST", body: payload });
      toast(
        `Tạo thành công lô #${created.id} "${created.product_name}" cho vùng trồng #${created.farm_id}`,
        "success"
      );
    }
    resetBatchForm(); // về lại chế độ "tạo mới"
    farmSelect.value = String(payload.farm_id); // giữ lại vùng trồng vừa chọn
    await loadBatches();
    await refreshAuditLogsIfAdmin(); // Sprint 7: vừa ghi dữ liệu -> cập nhật lịch sử
  } catch (error) {
    toast(`${isEditing ? "Cập nhật" : "Tạo"} lô nông sản thất bại: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Đang lưu…", batchSubmitLabel());
  }
}

/** Đưa form lô nông sản về chế độ "tạo mới" (bỏ dữ liệu đang sửa). */
function resetBatchForm() {
  editingBatchId = null;
  $("batch-form").reset();
  $("batch-form-mode").hidden = true;
  $("batch-cancel").hidden = true;
  $("batch-submit").textContent = batchSubmitLabel();
}

/**
 * Bấm nút "Sửa" ở bảng lô -> đổ dữ liệu lên form và chuyển sang chế độ sửa
 * (nút submit sẽ gọi ``PUT /batches/{id}``).
 */
function startEditBatch(batchId) {
  const batch = batches.find((item) => item.id === batchId);
  if (!batch) {
    toast(`Không tìm thấy lô nông sản #${batchId} trong dữ liệu đang hiển thị.`, "error");
    return;
  }

  editingBatchId = batch.id;
  $("batch-farm-id").value = String(batch.farm_id); // select đã được đổ ở loadFarms()
  $("batch-product-name").value = batch.product_name;
  $("batch-quantity").value = batch.quantity;
  $("batch-harvest-date").value = batch.harvest_date; // API trả sẵn dạng yyyy-MM-dd

  const mode = $("batch-form-mode");
  mode.textContent = `Đang sửa lô #${batch.id} — ${batch.product_name}. Bấm "Cập nhật lô nông sản" để lưu.`;
  mode.hidden = false;
  $("batch-cancel").hidden = false;
  $("batch-submit").textContent = batchSubmitLabel();

  renderBatches(); // tô nền dòng đang sửa trong bảng
  $("batch-form").scrollIntoView({ behavior: "smooth", block: "start" });
  $("batch-product-name").focus();
}

/** Xoá lô nông sản (chỉ admin) -> ``DELETE /batches/{id}``. */
async function deleteBatch(batchId) {
  const batch = batches.find((item) => item.id === batchId);
  const label = batch ? `#${batch.id} — ${batch.product_name}` : `#${batchId}`;

  if (!window.confirm(`Bạn có chắc chắn muốn xoá lô nông sản ${label}?\nHành động này không thể hoàn tác.`)) {
    return;
  }

  try {
    const result = await apiRequest(`/batches/${batchId}`, { method: "DELETE" });
    toast(result && result.message ? result.message : `Đã xoá lô nông sản #${batchId}.`, "success");

    if (editingBatchId === batchId) {
      resetBatchForm(); // lô đang sửa đã bị xoá -> form về chế độ tạo mới
    }
    await loadBatches();
    await refreshAuditLogsIfAdmin(); // Sprint 7: vừa xoá -> cập nhật lịch sử
  } catch (error) {
    toast(`Xoá lô nông sản thất bại: ${error.message}`, "error");
  }
}

/* ------------------------------------------------------- 9. Thống kê --- */
/**
 * Cập nhật các thẻ thống kê trên dashboard từ dữ liệu đang hiển thị:
 * - **Tổng vùng trồng**: số phần tử của `farms` (nguồn: `GET /farms`);
 * - **Tổng lô nông sản**: số phần tử của `batches` (nguồn: `GET /batches`);
 * - **Tổng sản lượng (kg)**: cộng `quantity` của mọi lô (làm tròn 2 chữ số);
 * - **Lịch sử thao tác** (Sprint 7, chỉ admin thấy): số phần tử của `auditLogs`
 *   (nguồn: `GET /audit-logs`) - farmer không tải được nên thẻ này bị ẩn.
 *
 * Hàm được gọi lại mỗi khi vẽ xong bảng (`renderFarms` / `renderBatches` /
 * `renderAuditLogs`) nên số liệu luôn khớp với dữ liệu vừa tải.
 */
function renderStats() {
  const totalYield = batches.reduce((sum, batch) => sum + Number(batch.quantity || 0), 0);

  $("stat-farms").textContent = formatNumber(farms.length);
  $("stat-batches").textContent = formatNumber(batches.length);
  $("stat-yield").textContent = formatNumber(Math.round(totalYield * 100) / 100);
  $("stat-audit").textContent = formatNumber(auditLogs.length);
}

/* ------------------------------------------ 10. Tài khoản (chỉ admin) --- */
/** GET /users (chỉ admin) -> cập nhật bảng tài khoản; farmer gọi sẽ nhận 403. */
async function loadUsers() {
  try {
    const data = await apiRequest("/users");
    users = Array.isArray(data) ? data : [];
    renderUsers();
  } catch (error) {
    users = [];
    renderUsers();
    toast(`Không tải được danh sách tài khoản: ${error.message}`, "error");
  }
}

/** Vẽ bảng tài khoản (hiển thị username + vai trò tiếng Việt dạng badge). */
function renderUsers() {
  $("user-table-body").innerHTML = users
    .map((user) => {
      const isAdminRole = user.role === ROLE_ADMIN;
      const roleLabel = isAdminRole ? "Quản trị viên" : "Chủ nông hộ / HTX";
      const roleClass = isAdminRole ? "role-badge role-badge--admin" : "role-badge role-badge--farmer";
      return `
      <tr>
        <td class="id-cell">#${escapeHtml(user.id)}</td>
        <td><strong>${escapeHtml(user.username)}</strong></td>
        <td><span class="${roleClass}">${roleLabel}</span></td>
      </tr>`;
    })
    .join("");

  $("user-empty").hidden = users.length > 0;
}

/* -------------------------------------- 11. Nhật ký hoạt động (chỉ admin) --- */
/**
 * GET /audit-logs (chỉ admin) -> vẽ bảng "Nhật ký hoạt động" và
 * cập nhật thẻ thống kê "Nhật ký hoạt động" trên dashboard.
 */
async function loadAuditLogs({ silent = false } = {}) {
  const button = $("btn-load-audit");
  const errorBox = $("audit-error");

  // --- trạng thái đang tải ---
  setButtonLoading(button, true, "Đang tải…", "Làm mới nhật ký");
  errorBox.hidden = true;
  $("audit-empty").hidden = true;
  $("audit-table-body").innerHTML =
    '<tr class="is-loading"><td class="is-center" colspan="6">Đang tải nhật ký hoạt động…</td></tr>';

  try {
    const data = await apiRequest("/audit-logs");
    auditLogs = Array.isArray(data) ? data : [];
    renderAuditLogs();

    if (!silent) {
      toast(
        auditLogs.length > 0
          ? `Đã tải ${formatNumber(auditLogs.length)} bản ghi nhật ký hoạt động.`
          : "Chưa có hoạt động nào được ghi nhận.",
        auditLogs.length > 0 ? "success" : "info"
      );
    }
  } catch (error) {
    auditLogs = [];
    renderAuditLogs();
    $("audit-empty").hidden = true;

    const denied = error.status === 401 || error.status === 403;
    errorBox.textContent = denied
      ? `Không có quyền xem nhật ký hoạt động - mục này chỉ dành cho Quản trị viên (${error.message})`
      : `Không tải được nhật ký hoạt động: ${error.message}`;
    errorBox.hidden = false;

    if (!silent || denied) {
      toast(errorBox.textContent, "error");
    }
  } finally {
    setButtonLoading(button, false, "Đang tải…", "Làm mới nhật ký");
  }
}

/** Vẽ bảng nhật ký hoạt động (mới nhất trước) + cập nhật thẻ thống kê. */
function renderAuditLogs() {
  const actionLabels = {
    create: "Thêm mới",
    update: "Cập nhật",
    delete: "Xóa",
  };
  const entityLabels = {
    farm: "Vùng trồng",
    batch: "Lô nông sản",
  };

  $("audit-table-body").innerHTML = auditLogs
    .map(
      (log) => `
      <tr>
        <td class="id-cell">#${escapeHtml(log.id)}</td>
        <td class="is-nowrap" title="UTC: ${escapeHtml(log.created_at)}">${escapeHtml(
          formatDateTime(log.created_at)
        )}</td>
        <td><strong>${escapeHtml(auditUserLabel(log))}</strong></td>
        <td><span class="action-badge action-badge--${escapeHtml(log.action)}">${escapeHtml(
          actionLabels[log.action] || log.action
        )}</span></td>
        <td><span class="entity-badge">${escapeHtml(entityLabels[log.entity] || log.entity)}</span></td>
        <td class="is-right">#${escapeHtml(log.entity_id)}</td>
      </tr>`
    )
    .join("");

  $("audit-empty").hidden = auditLogs.length > 0;
  $("audit-error").hidden = true;
  renderStats();
}

/** Nhãn người thực hiện: ưu tiên `username`, thiếu thì hiển thị `#user_id`. */
function auditUserLabel(log) {
  return log.username ? log.username : `#${log.user_id}`;
}

/**
 * Sau mỗi thao tác ghi thành công (tạo/sửa/xoá vùng trồng hoặc lô nông sản),
 * admin thấy lịch sử mới ngay mà không cần bấm nút: gọi im lặng để bảng log và
 * thẻ thống kê không bị cũ. Farmer không gọi được `GET /audit-logs` nên bỏ qua.
 */
async function refreshAuditLogsIfAdmin() {
  if (!isAdmin()) {
    return;
  }
  await loadAuditLogs({ silent: true });
}

/* --------------------------------------------------------- 12. Sự kiện --- */
function bindEvents() {
  $("login-form").addEventListener("submit", handleLoginSubmit);
  $("btn-logout").addEventListener("click", handleLogout);
  $("farm-form").addEventListener("submit", handleFarmSubmit);
  $("batch-form").addEventListener("submit", handleBatchSubmit);
  $("farm-cancel").addEventListener("click", () => cancelEdit("farm"));
  $("batch-cancel").addEventListener("click", () => cancelEdit("batch"));
  $("btn-reload").addEventListener("click", () => reloadAll());
  $("btn-load-audit").addEventListener("click", () => loadAuditLogs());

  // Đăng nhập nhanh cho tài khoản demo (Quản trị viên & Chủ nông hộ)
  const quickAdmin = $("btn-quick-admin");
  if (quickAdmin) {
    quickAdmin.addEventListener("click", () => {
      $("login-username").value = "admin";
      $("login-password").value = "123456";
      $("login-submit").focus();
    });
  }
  const quickFarmer = $("btn-quick-farmer");
  if (quickFarmer) {
    quickFarmer.addEventListener("click", () => {
      $("login-username").value = "farmer";
      $("login-password").value = "123456";
      $("login-submit").focus();
    });
  }
  const quickFarmerTg = $("btn-quick-farmer-tg");
  if (quickFarmerTg) {
    quickFarmerTg.addEventListener("click", () => {
      $("login-username").value = "farmer_tg";
      $("login-password").value = "123456";
      $("login-submit").focus();
    });
  }

  // Chuyển đổi hiển thị Thẻ / Bảng cho Thửa đất
  const btnViewCards = $("btn-view-cards");
  if (btnViewCards) {
    btnViewCards.addEventListener("click", () => setFarmViewMode("cards"));
  }
  const btnViewTable = $("btn-view-table");
  if (btnViewTable) {
    btnViewTable.addEventListener("click", () => setFarmViewMode("table"));
  }

  // Cột "Thao tác" (Sửa / Xoá) trên thẻ và bảng dùng event delegation
  const cardsContainer = $("farm-cards-container");
  if (cardsContainer) {
    cardsContainer.addEventListener("click", handleTableAction);
  }
  $("farm-table-body").addEventListener("click", handleTableAction);
  $("batch-table-body").addEventListener("click", handleTableAction);
}

/** Huỷ chế độ sửa của form vùng trồng / lô nông sản (nút "Huỷ sửa"). */
function cancelEdit(entity) {
  if (entity === "farm") {
    resetFarmForm();
    renderFarms();
    toast("Đã huỷ chế độ sửa vùng trồng.", "info");
    return;
  }

  resetBatchForm();
  renderBatches();
  toast("Đã huỷ chế độ sửa lô nông sản.", "info");
}

/**
 * Xử lý click ở cột "Thao tác" của cả 2 bảng (nút Sửa / Xoá).
 *
 * Đọc dữ liệu từ chính nút được bấm: `data-action` (edit|delete),
 * `data-entity` (farm|batch) và `data-id`.
 */
function handleTableAction(event) {
  const button = event.target.closest("button[data-action]");
  if (button === null) {
    return;
  }

  const id = Number(button.dataset.id);
  const entity = button.dataset.entity;
  const action = button.dataset.action;

  if (action === "edit") {
    if (entity === "farm") {
      startEditFarm(id);
    } else {
      startEditBatch(id);
    }
    return;
  }

  if (action === "delete") {
    if (!canDelete()) {
      toast("Chỉ tài khoản Quản trị viên mới có quyền xoá dữ liệu.", "error");
      return;
    }
    if (entity === "farm") {
      deleteFarm(id);
    } else {
      deleteBatch(id);
    }
  }
}

/** Tải dữ liệu dùng chung cho giao diện sau khi đăng nhập (theo phân quyền). */
async function loadAllData() {
  await checkHealth();
  await loadFarms();
  await loadBatches();
  if (isAdmin()) {
    await loadUsers();
    await loadAuditLogs({ silent: true });
  }
}

/** Tải lại toàn bộ dữ liệu; `silent = true` để bỏ toast tổng kết. */
async function reloadAll({ silent = false } = {}) {
  const button = $("btn-reload");
  setButtonLoading(button, true, "Đang tải…", "Tải lại dữ liệu");

  await loadAllData();

  setButtonLoading(button, false, "Đang tải…", "Tải lại dữ liệu");
  if (!silent) {
    const parts = [`${farms.length} vùng trồng`, `${batches.length} lô nông sản`];
    if (isAdmin()) {
      parts.push(`${auditLogs.length} nhật ký hoạt động`);
    }
    toast(`Đã cập nhật dữ liệu: ${parts.join(", ")}.`, "info");
  }
}

/* ------------------------------------------------------- 13. Khởi động --- */
/**
 * Khởi động ứng dụng:
 * 1. gắn sự kiện + kiểm tra backend đang chạy;
 * 2. nếu tab còn phiên đăng nhập cũ (sessionStorage) thì xác thực lại với
 *    backend rồi vào thẳng giao diện;
 * 3. ngược lại, hiện màn hình đăng nhập.
 */
async function init() {
  const apiEl = $("stat-api");
  if (apiEl) {
    apiEl.textContent = API_BASE_URL;
  }
  bindEvents();
  resetFarmForm();
  resetBatchForm();
  await checkHealth();

  const saved = restoreSession();
  if (saved !== null) {
    try {
      const data = await requestLogin(saved.username, saved.password);
      startSession({ username: data.username, role: data.role, password: saved.password });
      toast(`Đã khôi phục phiên đăng nhập: ${data.username}.`, "info");
      await reloadAll({ silent: true });
      return;
    } catch (error) {
      clearSession();
    }
  }

  applySessionToUi();
  $("login-username").focus();
}

document.addEventListener("DOMContentLoaded", init);
