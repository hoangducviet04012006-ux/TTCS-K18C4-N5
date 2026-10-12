/* =====================================================================
   Frontend demo - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản
   JavaScript thuần (không framework, không thư viện ngoài).
   Cấu trúc: cấu hình -> tiện ích -> gọi API -> trạng thái -> render -> sự kiện.
   ===================================================================== */

"use strict";

/* ---------------------------------------------------------- 1. Cấu hình --- */
// Địa chỉ backend FastAPI (đổi ở đây nếu chạy cổng khác).
const API_BASE_URL = window.AGRITRACE_CONFIG?.apiBase || "http://127.0.0.1:8000";

// Khoá lưu phiên đăng nhập trong sessionStorage (tự mất khi đóng tab).
const SESSION_STORAGE_KEY = `ttcs.session:${API_BASE_URL}`;

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

/** Chuẩn hóa nhãn quan hệ phả hệ sang tiếng Việt tự nhiên */
function formatRelationType(type) {
  if (!type) return "—";
  const upper = String(type).toUpperCase();
  if (upper === "SPLIT") return "Tách lô";
  if (upper === "MERGE") return "Gộp lô";
  if (upper === "GỐC") return "Lô gốc";
  if (upper === "CON") return "Lô con";
  return type;
}

/** Chuẩn hóa trạng thái lô nông sản sang tiếng Việt */
function formatBatchStatus(status) {
  if (!status) return "—";
  const upper = String(status).toUpperCase();
  if (upper === "ACTIVE") return "Đang quản lý";
  if (upper === "SPLIT") return "Đã tách";
  if (upper === "MERGED") return "Đã gộp";
  if (upper === "CONSUMED") return "Đã tiêu thụ";
  if (upper === "PENDING") return "Chờ duyệt";
  return status;
}

/** Chuẩn hóa loại sự kiện sang tiếng Việt dễ hiểu */
function formatEventType(type) {
  const map = {
    HARVEST: "🌱 Thu hoạch ban đầu",
    SPLIT: "✂️ Tách lô",
    GENESIS_SPLIT: "✂️ Lô được tạo từ thao tác tách",
    MERGE: "🔀 Gộp lô",
    EXPORT_MERGE: "🔀 Xuất gộp lô",
    HANDOVER_INIT: "🚚 Yêu cầu bàn giao",
    HANDOVER_SENT: "🚚 Yêu cầu bàn giao",
    HANDOVER_ACCEPT: "📥 Đã tiếp nhận",
    HANDOVER_ACCEPTED: "📥 Đã tiếp nhận",
    HANDOVER_REJECT: "❌ Từ chối tiếp nhận",
    HANDOVER_REJECTED: "❌ Từ chối tiếp nhận",
    CONSUMED: "🍽️ Đã tiêu thụ",
  };
  return map[String(type || "").toUpperCase()] || type || "Sự kiện";
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
function getCsrfCookie() {
  const match = document.cookie.match(/(^|;)\s*csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[2]) : "";
}

async function apiRequest(path, { method = "GET", body, auth = true, headers: extraHeaders = {}, timeoutMs = 30000 } = {}) {
  const headers = { "X-Requested-With": "XMLHttpRequest", ...extraHeaders };
  if (body) {
    headers["Content-Type"] = "application/json";
  }
  // Giai đoạn 2: Gửi kèm X-CSRF-Token cho các thao tác thay đổi trạng thái
  if (["POST", "PUT", "PATCH", "DELETE"].includes(method.toUpperCase())) {
    const csrfToken = (session && session.csrf_token) || getCsrfCookie();
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }
  }

  let response;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
      credentials: "include", // Luôn gửi và nhận HttpOnly session cookie
      signal: controller.signal,
    });
  } catch (error) {
    // `status = 0`: không có phản hồi HTTP (backend chưa chạy hoặc sai cổng).
    const offline = new Error(
      `Không kết nối được backend (${API_BASE_URL}). Hãy chắc chắn uvicorn đang chạy.`
    );
    offline.status = 0;
    throw offline;
  } finally {
    window.clearTimeout(timeout);
  }

  const data = await readJson(response);
  if (!response.ok) {
    // Giai đoạn 3A.1: Tự động xử lý khi phiên đăng nhập hết hạn hoặc bị thu hồi (HTTP 401)
    if (response.status === 401 && path !== "/auth/login") {
      handleSessionExpired();
    }
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
  if (detail && !Array.isArray(detail) && typeof detail === "object") {
    return detail.message || detail.code || JSON.stringify(detail);
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
// SCRUM-27/28: Danh sách tổ chức và các bàn giao đang chờ duyệt
let organizations = [];
let pendingHandovers = [];
let products = [];
let batchSearchDebounceTimer = null;
let batchPage = 1;
let batchRequestVersion = 0;

// SPRINT 3: Tách / Gộp lô & Phả hệ BFS & Quá hạn 48h
let selectedBatchIds = new Set();
let currentDetailBatchId = null;
let currentDetailBatchCode = "";
let currentDetailTab = "overview";
let currentSplitBatch = null;

/** Kiểm tra một thời điểm có quá 48 giờ so với hiện tại hay không (T-56, T-57). */
function checkIsOverdue(createdAtStr) {
  if (!createdAtStr) return false;
  try {
    const created = new Date(createdAtStr);
    const now = new Date();
    const diffHours = (now - created) / (1000 * 60 * 60);
    return diffHours >= 48;
  } catch (e) {
    return false;
  }
}

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

/** Header xác thực của tài khoản đang đăng nhập (để trống khi dùng Session Cookie). */
function authHeader() {
  return {};
}

/** POST /auth/login - kiểm tra tài khoản; ném Error nếu sai (backend trả 401). */
function requestLogin(username, password) {
  return apiRequest("/auth/login", {
    method: "POST",
    body: { username, password },
    auth: false, // request đăng nhập không gửi kèm header của phiên cũ
  });
}

/** POST /auth/demo-login - đăng nhập nhanh tài khoản demo Sprint 1–3 (không gửi mật khẩu từ FE). */
function requestDemoLogin(username) {
  return apiRequest("/auth/demo-login", {
    method: "POST",
    body: { username },
    auth: false,
  });
}

/** Lưu phiên đăng nhập vào bộ nhớ + sessionStorage (tuyệt đối KHÔNG lưu mật khẩu hay basic credential). */
function startSession({ username, email, role, csrf_token, organization_id, organization_name }) {
  session = { username, email, role, csrf_token, organization_id, organization_name };
  window.sessionStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({ username, email, role, csrf_token, organization_id, organization_name })
  );
  applySessionToUi();
}

/** Đọc phiên đăng nhập đã lưu trong tab; trả null nếu chưa có hoặc dữ liệu hỏng. */
function restoreSession() {
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    const saved = raw ? JSON.parse(raw) : null;
    if (saved && saved.username) {
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
  farms = []; batches = []; users = []; auditLogs = []; pendingHandovers = [];
  for (const key of Object.keys(dataLoadState)) dataLoadState[key] = "idle";
  screenDataVersion++;
  currentDetailBatchId = null;
  for (const id of ["trace-root-batches-list", "trace-lineage-levels-container", "events-timeline-list", "recent-activity-list"]) $(id).textContent = "";
  for (const id of ["trace-screen-batch", "events-screen-batch"]) $(id).innerHTML = '<option value="">Chọn lô đang hiển thị…</option>';
  for (const id of ["events-timeline-valid-banner", "events-timeline-alert-banner", "trace-lineage-body"]) setHidden(id, true);
  renderFarms(); renderBatches(); renderUsers(); renderAuditLogs(); renderPendingHandovers();
  window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  window.recallUi?.reset();
  document.querySelectorAll(".modal-backdrop").forEach(modal => { modal.hidden = true; });
  document.querySelectorAll("dialog[open]").forEach(dialog => dialog.close());
}

/**
 * Xử lý khi phiên đăng nhập hết hạn hoặc bị thu hồi (HTTP 401).
 * Xóa session trong bộ nhớ và sessionStorage, hiển thị thông báo tiếng Việt
 * và chuyển về màn hình đăng nhập mà KHÔNG xoá dữ liệu đang nhập trên các form.
 */
function handleSessionExpired() {
  if (session !== null) {
    window.sessionStorage.setItem(`ttcs.return:${API_BASE_URL}`, window.location.hash || "#batch-card");
    clearSession();
    applySessionToUi();
    const message = "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.";
    setLoginError(message);
    toast(message, "warning");
  }
}

const ROLE_NAMES = {
  system_admin: "Quản trị hệ thống",
  org_admin: "Quản trị tổ chức",
  farmer: "Nông dân",
  processor: "Nhà chế biến",
  transporter: "Vận chuyển",
  distributor: "Nhà phân phối",
  inspector: "Thanh tra viên",
  admin: "Quản trị viên",
};

const SIDEBAR_ICONS = {
  overview: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>`,
  farms: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 20h10"/><path d="M10 20c5.5-2.5.8-6.4 3-10"/><path d="M9.5 9.4c1.1.8 1.8 2.2 2.3 3.7-2 .4-3.5.4-4.8-.3-1.2-.6-2.3-1.9-3-4.2 2.8-.5 4.4 0 5.5.8z"/><path d="M14.1 6a7 7 0 0 0-1.1 4c1.9-.1 3.3-.6 4.3-1.4 1-1 1.6-2.3 1.7-4.6-2.7.1-4 1-4.9 2z"/></svg>`,
  batches: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7.5 4.27 9 5.15"/><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>`,
  pending: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></svg>`,
  trace: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="6" x2="6" y1="3" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>`,
  events: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>`,
  recall: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" x2="12" y1="9" y2="13"/><line x1="12" x2="12.01" y1="17" y2="17"/></svg>`,
  users: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
  audit: `<svg class="sidebar-nav-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/></svg>`
};

function updateSidebarNavItem(el, iconKey, text, extraHtml = "") {
  if (!el) return;
  const icon = SIDEBAR_ICONS[iconKey] || "";
  el.innerHTML = `${icon}<span class="sidebar-nav-text">${escapeHtml(text)}</span>${extraHtml}`;
}

/**
 * Cập nhật giao diện theo trạng thái đăng nhập, vai trò (role) và tổ chức:
 * - chưa đăng nhập: chỉ hiện màn hình login;
 * - farmer/processor/transporter/distributor/inspector: hiện chức năng theo phân quyền RBAC;
 * - system_admin/org_admin: hiện các công cụ quản trị tương ứng;
 * - hiển thị logo/tên tổ chức của user đang hoạt động.
 */
function applySessionToUi() {
  const isLoggedIn = session !== null;
  const adminUser = isAdmin();

  setHidden("login-view", isLoggedIn);
  setHidden("app-view", !isLoggedIn);
  setHidden("app-sidebar", !isLoggedIn);
  document.body.classList.toggle("authenticated", isLoggedIn);
  setHidden("nav-users", !adminUser);
  setHidden("nav-audit", !canViewAuditLogs());
  setHidden("btn-reload", !isLoggedIn);
  setHidden("btn-logout", !isLoggedIn);
  setHidden("btn-change-password", !isLoggedIn);
  setHidden("user-badge", !isLoggedIn);
  setHidden("header-user-menu", !isLoggedIn);
  setHidden("org-badge", !isLoggedIn || !session?.organization_name);

  // Giai đoạn 3A.1: Đồng bộ Form và Nút nghiệp vụ theo đúng 7 vai trò RBAC
  setHidden("batch-entry", !canHarvest());
  setHidden("farm-entry", !canManageFarms());
  setHidden("btn-open-merge-batches", !canMerge());
  setHidden("th-batch-select", !canMerge());

  // Tối ưu Sidebar theo 7 vai trò RBAC thực tế: Ẩn hẳn menu không cần thiết, bảo toàn icon SVG
  const navFarms = $("nav-farms");
  if (navFarms) {
    const canSeeFarms = ["farmer", "org_admin", "inspector", "system_admin"].includes(session?.role);
    navFarms.hidden = !canSeeFarms;
    updateSidebarNavItem(navFarms, "farms", "Vùng trồng");
  }
  const navBatches = $("nav-batches");
  if (navBatches) {
    navBatches.hidden = false;
    updateSidebarNavItem(navBatches, "batches", "Lô nông sản");
  }
  const navPending = $("nav-pending");
  if (navPending) {
    navPending.hidden = !canHandover();
    const countBadge = (canHandover() && pendingHandovers.length > 0)
      ? `<span class="sidebar-count-badge">${pendingHandovers.length}</span>`
      : "";
    updateSidebarNavItem(navPending, "pending", "Tiếp nhận bàn giao", countBadge);
  }
  const navUsers = $("nav-users");
  if (navUsers) {
    navUsers.hidden = !adminUser;
    updateSidebarNavItem(navUsers, "users", "Tài khoản");
  }
  const navAudit = $("nav-audit");
  if (navAudit) {
    navAudit.hidden = !canViewAuditLogs();
    const auditText = session?.role === "inspector" ? "Nhật ký thanh tra" : "Nhật ký kiểm toán";
    updateSidebarNavItem(navAudit, "audit", auditText);
  }
  const adminSection = document.querySelector(".sidebar-section--admin");
  if (adminSection) {
    adminSection.hidden = !adminUser && !canViewAuditLogs();
  }

  const orgBadge = $("org-badge");
  if (orgBadge !== null && isLoggedIn && session?.organization_name) {
    orgBadge.textContent = `🏢 ${session.organization_name}`;
    orgBadge.title = session.organization_name;
  }

  const badge = $("user-badge");
  if (badge !== null && isLoggedIn) {
    const roleText = ROLE_NAMES[session.role] || (adminUser ? "Quản trị viên" : "Thành viên");
    badge.textContent = `${session.username} · ${roleText}`;
    badge.className = "user-menu-text";
    const dropdownMeta = $("user-dropdown-meta");
    if (dropdownMeta) {
      dropdownMeta.textContent = `${session.organization_name || "Chưa gán tổ chức"} (${roleText})`;
    }
  }

  const orgContext = $("farm-org-context");
  if (orgContext !== null && isLoggedIn) {
    orgContext.textContent = `Các thửa đất thuộc: ${session.organization_name || "Tổ chức của bạn"}`;
  }

  setHidden("users-card", !adminUser);
  setHidden("audit-card", !canViewAuditLogs());
  setHidden("stat-audit-card", !canViewAuditLogs());
  setHidden("btn-open-add-product", !isSystemAdmin());
  setHidden("btn-create-org", !isSystemAdmin());
  window.recallUi?.applySession();
  const scopeText = session?.role === "inspector" ? "Toàn hệ thống" : `Tổ chức: ${session?.organization_name || "chưa được gán"}`;
  $("overview").setAttribute("aria-label", `Thống kê: ${scopeText}`);
  const farmHint = session?.role === "inspector"
    ? "Số vùng đã tải · Toàn hệ thống"
    : session?.role === "transporter"
    ? "Vai trò vận chuyển · Không quản lý thửa đất"
    : `Số vùng đã tải · ${scopeText}`;
  $("stat-farms").closest("article").querySelector(".stat-card__hint").textContent = farmHint;
  $("stat-batches").closest("article").querySelector(".stat-card__hint").textContent = `Trang ${batchPage}, tối đa 20 lô · ${scopeText}`;
  $("stat-yield").closest("article").querySelector(".stat-card__hint").textContent = `Khối lượng còn lại của lô trên trang · ${scopeText}`;
  
  const pendingCard = $("stat-pending-card");
  if (pendingCard) {
    const pendingLink = pendingCard.querySelector("a");
    if (canHandover()) {
      pendingCard.hidden = false;
      if (pendingLink) pendingLink.hidden = false;
    } else {
      pendingCard.hidden = true;
      if (pendingLink) pendingLink.hidden = true;
    }
  }

  const auditCard = $("stat-audit-card");
  if (auditCard && canViewAuditLogs()) {
    const auditLabel = auditCard.querySelector(".stat-card__label");
    if (auditLabel) {
      auditLabel.textContent = session?.role === "inspector" ? "Nhật ký thanh tra" : "Nhật ký hoạt động";
    }
  }

  renderStats();
  renderAppScreen(false);
}

/** Phiên hiện tại có phải tài khoản admin / system_admin / org_admin không. */
function isAdmin() {
  return session !== null && (session.role === "admin" || session.role === "system_admin" || session.role === "org_admin");
}

function isSystemAdmin() {
  return session !== null && (session.role === "system_admin" || session.role === "admin");
}

function isOrgAdmin() {
  return session !== null && session.role === "org_admin";
}

function canViewAuditLogs() {
  return session !== null && (isAdmin() || session.role === "inspector");
}

/** Nông dân canh tác có quyền thu hoạch (HARVEST). */
function canHarvest() {
  return session !== null && session.role === "farmer";
}

/** Quản lý thửa đất / vùng trồng (FARM_MANAGE): nông dân và quản trị tổ chức. */
function canManageFarms() {
  return session !== null && (session.role === "farmer" || session.role === "org_admin");
}

/** Gộp lô (MERGE): chỉ nhà chế biến (processor). */
function canMerge() {
  return session !== null && session.role === "processor";
}

/** Tách lô (SPLIT): nông dân, nhà chế biến, nhà phân phối. */
function canSplit() {
  return session !== null && (session.role === "farmer" || session.role === "processor" || session.role === "distributor");
}

/** Bàn giao (HANDOVER_INIT): nông dân, nhà chế biến, vận chuyển, nhà phân phối. */
function canHandover() {
  return session !== null && (session.role === "farmer" || session.role === "processor" || session.role === "transporter" || session.role === "distributor");
}

/** Ghi nhận đã tiêu thụ (CONSUMED - S-29): nhà phân phối (distributor) hoặc quản trị tổ chức (org_admin). */
function canConsume() {
  return session !== null && (session.role === "distributor" || session.role === "org_admin");
}

/**
 * Quyền xoá dữ liệu ở giao diện: **chỉ admin** (Sprint 5).
 * Farmer dùng giao diện sẽ không thấy nút Xoá; nếu cố gọi API xoá thì backend
 * trả `403 Forbidden` (`require_admin`) - đây chỉ là lớp bảo vệ ở UI.
 */
function canDelete() {
  return isAdmin();
}

/**
 * Hiển thị / xoá cảnh báo đỏ ngay trong form đăng nhập (S-04).
 * Truyền chuỗi rỗng để ẩn cảnh báo.
 */
function setLoginError(message) {
  const box = $("login-error");
  if (!box) {
    return;
  }
  const text = (message || "").trim();
  box.textContent = text;
  box.hidden = text === "";
}

/** Xử lý submit form đăng nhập -> POST /auth/login. */
async function handleLoginSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  // S-04: ô nhập chấp nhận **email hoặc tên đăng nhập**.
  const username = $("login-username").value.trim();
  const password = $("login-password").value; // không trim mật khẩu

  const button = $("login-submit");
  setLoginError(""); // xoá cảnh báo cũ trước mỗi lần thử lại
  setButtonLoading(button, true, "Đang kiểm tra…", "Đăng nhập");

  try {
    const data = await requestLogin(username, password);
    startSession({
      username: data.username,
      email: data.email,
      role: data.role,
      csrf_token: data.csrf_token,
      organization_id: data.organization_id,
      organization_name: data.organization_name,
    });
    form.reset();
    setLoginError("");
    const orgGreeting = data.organization_name ? ` · ${data.organization_name}` : "";
    toast(`Đăng nhập thành công! Xin chào ${data.username}${orgGreeting}.`, "success");
    await reloadAll({ silent: true });
    const returnKey = `ttcs.return:${API_BASE_URL}`;
    const destination = window.sessionStorage.getItem(returnKey) || window.location.hash || "#overview";
    window.sessionStorage.removeItem(returnKey);
    if (document.getElementById(destination.slice(1)) || Object.hasOwn(appScreens, destination.slice(1))) window.location.hash = destination;
  } catch (error) {
    if (error.status === 403) {
      // S-04: tài khoản bị **tạm khoá** sau 5 lần sai -> cảnh báo đỏ nổi bật
      // kèm thông điệp + thời gian chờ còn lại do backend trả về.
      setLoginError(error.message);
      toast(error.message, "error");
    } else if (error.status === 401) {
      const message = "Sai email/tên đăng nhập hoặc mật khẩu. Vui lòng kiểm tra lại!";
      setLoginError(message);
      toast(message, "error");
    } else {
      setLoginError(error.message);
      toast(error.message, "error");
    }
    $("login-password").select();
  } finally {
    setButtonLoading(button, false, "Đang kiểm tra…", "Đăng nhập");
  }
}

/** Hiển thị / xoá trạng thái đang đăng nhập của demo dropdown. */
function setDemoLoginStatus(text) {
  const box = $("demo-quick-status");
  if (!box) return;
  const str = (text || "").trim();
  box.textContent = str;
  box.hidden = str === "";
}

/**
 * Xử lý đăng nhập nhanh khi người dùng chọn tài khoản trong dropdown:
 * - Tự động thực hiện đăng nhập ngay qua POST /auth/demo-login
 * - Không yêu cầu mật khẩu
 * - Khóa dropdown và hiển thị trạng thái "Đang đăng nhập..."
 * - Chuyển đến Dashboard (#overview)
 * - Báo lỗi rõ ràng và mở lại dropdown nếu có lỗi.
 */
async function handleDemoAccountSelect(event) {
  const select = event.target;
  const username = (select.value || "").trim();
  if (!username) {
    return;
  }

  // Khóa dropdown để tránh thao tác liên tiếp và hiển thị trạng thái
  select.disabled = true;
  setLoginError("");
  setDemoLoginStatus("Đang đăng nhập…");

  try {
    const data = await requestDemoLogin(username);
    startSession({
      username: data.username,
      email: data.email,
      role: data.role,
      csrf_token: data.csrf_token,
      organization_id: data.organization_id,
      organization_name: data.organization_name,
    });
    const loginForm = $("login-form");
    if (loginForm) loginForm.reset();
    setLoginError("");
    setDemoLoginStatus("");
    const orgGreeting = data.organization_name ? ` · ${data.organization_name}` : "";
    toast(`Đăng nhập thành công! Xin chào ${data.username}${orgGreeting}.`, "success");
    await reloadAll({ silent: true });
    const returnKey = `ttcs.return:${API_BASE_URL}`;
    const destination = window.sessionStorage.getItem(returnKey) || "#overview";
    window.sessionStorage.removeItem(returnKey);
    if (document.getElementById(destination.slice(1)) || Object.hasOwn(appScreens, destination.slice(1))) {
      window.location.hash = destination;
    } else {
      window.location.hash = "#overview";
    }
    if (typeof renderAppScreen === "function") {
      renderAppScreen();
    }
  } catch (error) {
    console.error("Lỗi đăng nhập nhanh demo:", error);
    const message = error.message || "Đăng nhập nhanh thất bại. Vui lòng kiểm tra lại môi trường Demo.";
    setLoginError(message);
    setDemoLoginStatus("");
    toast(message, "error");
    select.disabled = false;
    select.value = "";
    select.focus();
    return;
  }

  // Sau khi đăng nhập thành công, mở khóa và reset dropdown để sẵn sàng cho lần đăng xuất sau
  select.disabled = false;
  select.value = "";
}

/** Đăng xuất: gọi API thu hồi phiên server-side, xoá phiên local và quay về login. */
async function handleLogout() {
  const username = session ? session.username : "";
  try {
    await apiRequest("/auth/logout", { method: "POST" });
  } catch (err) {
    console.warn("Lỗi khi gọi logout server-side:", err);
  }
  clearSession();

  const demoSelect = $("sprint-demo-account");
  if (demoSelect) {
    demoSelect.disabled = false;
    demoSelect.value = "";
  }
  setDemoLoginStatus("");
  setLoginError("");

  farms = [];
  batches = [];
  users = [];
  auditLogs = [];
  organizations = [];
  pendingHandovers = [];
  products = [];
  resetFarmForm();
  resetBatchForm();
  renderProducts();
  renderProductOptions();
  renderFarms();
  renderFarmOptions();
  renderBatches();
  renderUsers();
  renderAuditLogs();
  renderPendingHandovers();

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

/* ---------------------------------------------------- 6.1. Sản phẩm & Đơn vị tính (T-16, T-17) --- */
/** GET /products -> cập nhật danh mục sản phẩm toàn hệ thống */
async function loadProducts() {
  try {
    const data = await apiRequest("/products");
    products = Array.isArray(data) ? data : [];
    renderProducts();
    renderProductOptions();
  } catch (error) {
    console.warn("Không tải được danh mục sản phẩm:", error);
  }
}

/** Vẽ bảng danh mục sản phẩm */
function renderProducts() {
  const tbody = $("products-table-body");
  if (!tbody) return;
  tbody.innerHTML = products
    .map(
      (p) => `
    <tr>
      <td class="id-cell">#${escapeHtml(p.id)}</td>
      <td><strong>${escapeHtml(p.name)}</strong></td>
      <td><span class="badge badge--ok">${escapeHtml(p.unit)}</span></td>
      <td>${escapeHtml(formatDateTime(p.created_at))}</td>
    </tr>`
    )
    .join("");

  const empty = $("products-empty");
  if (empty) empty.hidden = products.length > 0;
}

/** Đổ danh sách sản phẩm vào dropdown form thu hoạch và dropdown lọc */
function renderProductOptions() {
  const batchProductSelect = $("batch-product-id");
  const filterProductSelect = $("batch-filter-product");

  if (batchProductSelect) {
    const currentVal = batchProductSelect.value;
    batchProductSelect.innerHTML =
      '<option value="">— Chọn sản phẩm từ danh mục —</option>' +
      products
        .map(
          (p) =>
            `<option value="${p.id}">${escapeHtml(p.name)} (${escapeHtml(p.unit)})</option>`
        )
        .join("");
    if (currentVal) batchProductSelect.value = currentVal;
  }

  if (filterProductSelect) {
    const currentFilter = filterProductSelect.value;
    filterProductSelect.innerHTML =
      '<option value="">— Tất cả sản phẩm —</option>' +
      products
        .map((p) => `<option value="${p.id}">${escapeHtml(p.name)}</option>`)
        .join("");
    if (currentFilter) filterProductSelect.value = currentFilter;
  }
}

/** Xử lý submit thêm sản phẩm mới (chỉ Admin - T-17) */
async function handleProductSubmit(event) {
  event.preventDefault();
  const name = $("product-name").value.trim();
  const unit = $("product-unit").value;
  const button = $("btn-submit-product");

  if (!name) {
    toast("Vui lòng nhập tên sản phẩm.", "error");
    return;
  }

  setButtonLoading(button, true, "Đang lưu…", "Lưu sản phẩm");
  try {
    const created = await apiRequest("/products", {
      method: "POST",
      body: { name, unit },
    });
    toast(`Đã thêm sản phẩm "${created.name}" (${created.unit}) vào hệ thống!`, "success");
    $("modal-add-product").hidden = true;
    $("product-form").reset();
    await loadProducts();
  } catch (error) {
    toast(`Thêm sản phẩm thất bại: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Đang lưu…", "Lưu sản phẩm");
  }
}

/* ------------------------------------------------------- 7. Vùng trồng --- */
/** GET /farms -> cập nhật bảng danh sách + select vùng trồng của form lô. */
async function loadFarms() {
  const actor = session;
  dataLoadState.farms = "loading"; renderStats();
  try {
    const data = await apiRequest("/farms");
    if (actor !== session) return;
    dataLoadState.farms = "ready";
    farms = Array.isArray(data) ? data : [];
    renderFarms();
    renderFarmOptions();
  } catch (error) {
    if (actor !== session) return;
    dataLoadState.farms = dataErrorState(error); farms = [];
    renderFarms(); renderFarmOptions();
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
            ${
              canManageFarms()
                ? `<button class="btn btn--primary btn--sm" type="button"
                    data-action="edit" data-entity="farm"
                    data-id="${escapeHtml(farm.id)}">✏️ Sửa</button>`
                : ""
            }
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
              ${
                canManageFarms()
                  ? `<button class="btn btn--primary btn--sm" type="button"
                      data-action="edit" data-entity="farm"
                      data-id="${escapeHtml(farm.id)}">Sửa</button>`
                  : ""
              }
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
  if (!canManageFarms()) {
    toast("Vai trò của bạn không có quyền khai báo hoặc sửa thửa đất.", "error");
    return;
  }

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
  if (!canManageFarms()) {
    toast("Vai trò của bạn không có quyền sửa vùng trồng.", "error");
    return;
  }
  $("farm-entry").open = true;
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
  if (!canDelete()) {
    toast("Chỉ tài khoản Quản trị viên mới có quyền xoá dữ liệu.", "error");
    return;
  }
  const farm = farms.find((item) => item.id === farmId);
  const label = farm ? `#${farm.id} — ${farm.name}` : `#${farmId}`;
  const childCount = batches.filter((batch) => batch.farm_id === farmId).length;

  const question =
    `Bạn có chắc chắn muốn xoá vùng trồng ${label}?` +
    (childCount > 0 ? "\nVùng trồng có lô truy xuất sẽ được bảo vệ khỏi việc xóa." : "") +
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
/** GET /batches -> cập nhật bảng danh sách lô (hỗ trợ phân trang, tìm kiếm mã lô & lọc theo sản phẩm - T-33, T-34) */
async function loadBatches() {
  const version = ++batchRequestVersion;
  const actor = session;
  dataLoadState.batches = "loading"; renderStats();
  $("batch-page-label").textContent = "Đang tải…";
  try {
    const searchVal = $("batch-search-input")?.value?.trim() || "";
    const productVal = $("batch-filter-product")?.value || "";

    const query = new URLSearchParams({page: batchPage, limit: 20});
    if (searchVal) query.append("search", searchVal);
    if (productVal) query.append("product_id", productVal);

    const qs = query.toString() ? `?${query.toString()}` : "";
    const data = await apiRequest(`/batches${qs}`);
    if (version !== batchRequestVersion || actor !== session) return;
    dataLoadState.batches = "ready";
    batches = Array.isArray(data) ? data : [];
    $("batch-page-label").textContent = `Trang ${batchPage}`;
    $("batch-prev").disabled = batchPage === 1;
    $("batch-next").disabled = batches.length < 20;
    renderBatches();
    await refreshScreenData();
    maybeAutoOpenDemoLineage(searchVal);
  } catch (error) {
    if (version !== batchRequestVersion) return;
    dataLoadState.batches = dataErrorState(error); batches = [];
    renderBatches();
    $("recent-activity-list").textContent = dataStateText(dataLoadState.batches);
    $("batch-page-label").textContent = "Tải dữ liệu thất bại";
    toast(`Không tải được danh sách lô nông sản: ${error.message}`, "error");
  }
}

/** Mã lô mẫu phả hệ 3 tầng dùng cho demo nhanh (Quick-access seed data). */
const DEMO_LINEAGE_CODES = ["B-FINAL-01", "B-FINAL-02"];
const DEMO_LINEAGE_DEFAULT = "B-FINAL-01";

/**
 * Quick-access: nếu người dùng gõ đúng mã lô mẫu thì mở ngay cây phả hệ 3 tầng.
 * (Nhờ đó chỉ cần gõ "B-FINAL-01" là bung phả hệ đầy đủ, không bị thiếu trường.)
 */
function maybeAutoOpenDemoLineage(searchVal) {
  const term = String(searchVal || "").trim().toUpperCase();
  if (!DEMO_LINEAGE_CODES.includes(term)) return;

  const match = batches.find((b) => String(b.code || "").toUpperCase() === term);
  if (!match) return;

  const modal = $("modal-batch-details");
  if (currentDetailBatchId === match.id && modal && !modal.hidden) {
    switchDetailTab("lineage"); // modal đang mở sẵn -> chỉ cần chuyển sang Tab 3
    return;
  }

  openBatchDetailsModal(match.id).then(() => switchDetailTab("lineage"));
}

/** Nút quick-access: tự điền mã lô mẫu rồi mở phả hệ 3 tầng (B-FINAL-01). */
async function openLineageDemo() {
  const match = batches.find(b => selectedBatchIds.has(b.id)) || batches[0];
  if (!match) { toast("Chưa có lô trong danh sách để truy xuất.", "info"); return; }
  await openBatchDetailsModal(match.id);
  switchDetailTab("lineage");
}

/** Tìm kiếm mã lô với debounce 300ms (T-34) */
function onBatchSearchInput() {
  if (batchSearchDebounceTimer) {
    clearTimeout(batchSearchDebounceTimer);
  }
  batchSearchDebounceTimer = setTimeout(() => {
    batchPage = 1; selectedBatchIds.clear();
    loadBatches();
  }, 300);
}

/** Nhãn vùng trồng cho bảng lô (dùng lại dữ liệu đã tải từ GET /farms). */
function farmLabel(farmId) {
  const farm = farms.find((item) => item.id === farmId);
  return farm ? `#${farmId} — ${farm.name}` : `#${farmId}`;
}

/** Cập nhật trạng thái nút "Gộp lô đã chọn" dựa trên các checkbox được chọn (T-46). */
function updateMergeButtonState() {
  const btn = $("btn-open-merge-batches");
  if (!btn) return;

  // Giai đoạn 3A.1: Chỉ processor có quyền MERGE mới được kích hoạt nút
  if (!canMerge()) {
    btn.disabled = true;
    btn.hidden = true;
    return;
  }
  btn.hidden = false;

  const count = selectedBatchIds.size;
  const selectAll = $("batch-select-all");
  if (selectAll) {
    selectAll.checked = batches.length > 0 && selectedBatchIds.size === batches.length;
  }

  if (count < 2) {
    btn.disabled = true;
    btn.textContent = `🔀 Gộp lô đã chọn (${count})`;
    btn.title = "Chọn ít nhất 2 lô cùng sản phẩm để gộp";
    return;
  }

  const selectedBatches = batches.filter((b) => selectedBatchIds.has(b.id));
  if (selectedBatches.length < 2) {
    btn.disabled = true;
    btn.textContent = `🔀 Gộp lô đã chọn (${count})`;
    return;
  }
  const firstProdId = selectedBatches[0].product_id;
  const allSameProduct = selectedBatches.every((b) => b.product_id === firstProdId);

  if (!allSameProduct) {
    btn.disabled = true;
    btn.textContent = `⚠️ Khác loại SP (${count})`;
    btn.title = "Tất cả các lô chọn để gộp phải cùng một loại sản phẩm (T-45)";
    return;
  }

  btn.disabled = false;
  btn.textContent = `🔀 Gộp ${count} lô đã chọn`;
  btn.title = `Gộp ${count} lô sản phẩm ${selectedBatches[0].product_name}`;
}

/** Vẽ bảng danh sách lô nông sản (kèm checkbox gộp lô, cột Đơn vị nắm giữ, Trạng thái & Thao tác). */
function renderBatches() {
  $("batch-table-body").innerHTML = batches
    .map((batch) => {
      const holdingOrg = batch.current_org_name || (session?.organization_name || farmLabel(batch.farm_id));
      const pendingItem = pendingHandovers.find((h) => h.batch_id === batch.id);
      const isPending = (batch.pending_handover != null) || (pendingItem != null);

      // Kiểm tra quá hạn 48h bên gửi/bên nhận (T-56, T-57)
      const isOverdue = (batch.pending_handover && (batch.pending_handover.is_overdue || checkIsOverdue(batch.pending_handover.created_at))) ||
                        (pendingItem && (pendingItem.is_overdue || checkIsOverdue(pendingItem.created_at)));

      // Kiểm tra trạng thái sự cố và thu hồi (S-33)
      const isRecalled = window.recallUi?.isBatchRecalled ? (window.recallUi.isBatchRecalled(batch.id) || window.recallUi.isBatchRecalled(batch.code)) : false;
      const recallInfo = window.recallUi?.getBatchRecallInfo ? (window.recallUi.getBatchRecallInfo(batch.id) || window.recallUi.getBatchRecallInfo(batch.code)) : null;

      let statusBadge = '<span class="badge badge--ok">Đang quản lý</span>';
      if (isRecalled) {
        statusBadge = `<span class="badge badge--danger" style="background:#dc2626; color:#fff; font-weight:700;" title="Lô hàng có sự cố và đang trong lệnh thu hồi ${escapeHtml(recallInfo?.recall_code || '')} (S-33)">🚨 Có sự cố</span>`;
      } else if (batch.status === "CONSUMED") {
        statusBadge = '<span class="badge" style="background:#64748b; color:#fff;" title="Lô hàng đã bán hết cho người tiêu dùng (S-29)">🍽️ Đã tiêu thụ</span>';
      } else if (batch.status === "SPLIT") {
        statusBadge = '<span class="badge badge--info" style="background:#0284c7; color:#fff;">✂️ Đã tách</span>';
      } else if (batch.status === "MERGED") {
        statusBadge = '<span class="badge badge--info" style="background:#7c3aed; color:#fff;">🔀 Đã gộp</span>';
      } else if (isPending) {
        statusBadge = isOverdue
          ? '<span class="badge badge--warning">⏳ Chờ duyệt</span> <span class="badge badge--overdue" title="Yêu cầu bàn giao đã quá hạn 48 giờ">⚠️ Quá hạn 48h</span>'
          : '<span class="badge badge--warning">⏳ Chờ duyệt bàn giao</span>';
      }

      // Kiểm tra người dùng có thuộc tổ chức đang nắm giữ lô không (phải có tổ chức hợp lệ)
      const isHolder = session && session.organization_id != null && batch.current_org_id === session.organization_id;

      const initialQty = batch.initial_quantity != null ? batch.initial_quantity : batch.quantity;
      const remainingQty = batch.remaining_quantity != null ? batch.remaining_quantity : initialQty;
      const batchCodeDisplay = batch.code || `#${batch.id}`;

      let handoverBtn = "";
      let splitBtn = "";
      let consumeBtn = "";
      let editBtn = "";
      let recallBtn = "";

      const canOpenRecall = session?.role === "inspector" || (session?.role === "org_admin" && isHolder);
      if (canOpenRecall) {
        if (isRecalled) {
          recallBtn = `<button class="btn btn--outline-danger btn--sm" type="button"
                         data-action="open-recall-section"
                         title="Lô hàng đang trong lệnh thu hồi ${escapeHtml(recallInfo?.recall_code || '')}. Bấm để xem danh sách thu hồi."
                         style="border-color:#dc2626; color:#dc2626;">🚨 Lệnh thu hồi</button>`;
        } else {
          recallBtn = `<button class="btn btn--outline-danger btn--sm" type="button"
                         data-action="create-recall" data-id="${escapeHtml(batch.id)}" data-code="${escapeHtml(batch.code || '')}"
                         title="Đánh dấu lô có sự cố và mở lệnh thu hồi kèm lý do (S-33)"
                         style="border-color:#dc2626; color:#dc2626;">🚨 Báo sự cố</button>`;
        }
      }

      if (isHolder && batch.status !== "CONSUMED") {
        if (isRecalled) {
          // Khi lô có sự cố / trong lệnh thu hồi: Phong tỏa mọi thao tác vật lý
          if (canHandover()) {
            handoverBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang có sự cố / bị thu hồi: chặn bàn giao (S-38)">🚚 Bàn giao</button>`;
          }
          if (canSplit()) {
            splitBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang có sự cố / bị thu hồi: chặn tách lô (S-38)">✂️ Tách</button>`;
          }
          if (canConsume()) {
            consumeBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang có sự cố / bị thu hồi: chặn tiêu thụ (S-38)">🍽️ Tiêu thụ</button>`;
          }
        } else if (isPending) {
          if (canHandover()) {
            handoverBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang có yêu cầu bàn giao chờ xác nhận">⏳ Chờ duyệt</button>`;
          }
          if (canSplit()) {
            splitBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang chờ duyệt bàn giao">✂️ Tách</button>`;
          }
        } else {
          if (canHandover()) {
            handoverBtn = `<button class="btn btn--outline-primary btn--sm" type="button"
                             data-action="open-handover" data-id="${escapeHtml(batch.id)}">🚚 Bàn giao</button>`;
          }
          if (canSplit()) {
            splitBtn = `<button class="btn btn--outline-primary btn--sm" type="button"
                          data-action="split-batch" data-id="${escapeHtml(batch.id)}" ${remainingQty <= 0 ? 'disabled' : ''} title="Tách thành nhiều lô con (T-41)">✂️ Tách</button>`;
          }
          if (canConsume() && remainingQty > 0) {
            consumeBtn = `<button class="btn btn--outline-warning btn--sm" type="button"
                            data-action="consume-batch" data-id="${escapeHtml(batch.id)}" title="Ghi nhận đã bán hết cho người tiêu dùng (S-29)" style="border-color:#d97706; color:#d97706;">🍽️ Tiêu thụ</button>`;
          }
        }
        if (canHarvest() && !isRecalled) {
          editBtn = `<button class="btn btn--light btn--sm" type="button"
                             data-action="edit" data-entity="batch"
                             data-id="${escapeHtml(batch.id)}">Sửa</button>`;
        }
      }

      return `
      <tr class="${batch.id === editingBatchId ? "is-editing" : ""}">
        <td style="text-align: center;" ${canMerge() ? "" : "hidden"}>
          <input type="checkbox" class="batch-select-checkbox" data-id="${escapeHtml(batch.id)}" ${selectedBatchIds.has(batch.id) ? "checked" : ""} />
        </td>
        <td class="id-cell">
          <strong style="font-family:'Cascadia Mono',monospace; letter-spacing:1px; background:#0f172a; color:#facc15; padding:3px 8px; border-radius:4px; font-size:0.95rem;">
            ${escapeHtml(batchCodeDisplay)}
          </strong>
        </td>
        <td>${escapeHtml(farmLabel(batch.farm_id || batch.plot_id))}</td>
        <td><strong>${escapeHtml(batch.product_name)}</strong></td>
        <td class="is-right">${formatNumber(initialQty)} ${escapeHtml(batch.unit || "kg")}</td>
        <td class="is-right"><strong>${formatNumber(remainingQty)} ${escapeHtml(batch.unit || "kg")}</strong></td>
        <td>${escapeHtml(formatDate(batch.harvest_date))}</td>
        <td><span class="badge badge--org">🏢 ${escapeHtml(holdingOrg)}</span></td>
        <td>${statusBadge}</td>
        <td>
          <div class="table__actions">
            <button class="btn btn--primary btn--sm" type="button"
                    data-action="view-details" data-id="${escapeHtml(batch.id)}" title="Xem chi tiết: Tổng quan, Dòng thời gian, Nguồn gốc xuất xứ">🔍 Chi tiết</button>
            ${splitBtn}
            ${handoverBtn}
            ${consumeBtn}
            ${recallBtn}
            ${editBtn}
            ${
              canDelete()
                ? `<button class="btn btn--danger btn--sm" type="button"
                    data-action="delete" data-entity="batch"
                    data-id="${escapeHtml(batch.id)}">Xoá</button>`
                : ""
            }
          </div>
        </td>
      </tr>`;
    })
    .join("");

  $("batch-empty").hidden = batches.length > 0;
  updateMergeButtonState();
  renderStats();
}

/** Nhãn nút submit form lô nông sản theo chế độ hiện tại (tạo mới / sửa). */
function batchSubmitLabel() {
  return editingBatchId === null ? "Tạo lô nông sản" : "Cập nhật lô nông sản";
}

/** Xoá các thông báo lỗi inline của form lô thu hoạch (T-20) */
function clearBatchInlineErrors() {
  const ids = ["err-batch-farm", "err-batch-product", "err-batch-quantity", "err-batch-date"];
  ids.forEach((id) => {
    const el = $(id);
    if (el) {
      el.textContent = "";
      el.hidden = true;
    }
  });
}

/**
 * Xử lý submit form lô nông sản (T-20, T-21, T-22):
 * - Hiển thị lỗi inline ngay cạnh từng ô nhập;
 * - Vô hiệu hóa nút Lưu ngay khi bấm để chặn nhấn đúp;
 * - Khi thành công hiển thị mã lô cỡ lớn >= 28px in đậm ngoài trời nắng kèm nút sao chép.
 */
async function handleBatchSubmit(event) {
  event.preventDefault();
  if (!canHarvest()) {
    toast("Vai trò của bạn không có quyền khai báo thu hoạch.", "error");
    return;
  }
  if ($("batch-submit").disabled) return;
  clearBatchInlineErrors();

  const farmSelect = $("batch-farm-id");
  const productSelect = $("batch-product-id");
  const qtyInput = $("batch-quantity");
  const dateInput = $("batch-harvest-date");
  let hasError = false;

  if (!farmSelect.value) {
    const err = $("err-batch-farm");
    if (err) {
      err.textContent = "Vui lòng chọn thửa đất/vùng trồng xuất xứ.";
      err.hidden = false;
    }
    hasError = true;
  }

  const selectedProductId = productSelect?.value ? Number(productSelect.value) : null;
  const productNameFallback = $("batch-product-name")?.value?.trim() || "";
  if (!selectedProductId && !productNameFallback) {
    const err = $("err-batch-product");
    if (err) {
      err.textContent = "Vui lòng chọn sản phẩm thu hoạch từ danh mục.";
      err.hidden = false;
    }
    hasError = true;
  }

  const rawQty = Number(qtyInput.value);
  if (!rawQty || rawQty <= 0) {
    const err = $("err-batch-quantity");
    if (err) {
      err.textContent = "Khối lượng thu hoạch ban đầu phải lớn hơn 0.";
      err.hidden = false;
    }
    hasError = true;
  }

  const harvestDate = dateInput.value;
  const today = new Date().toISOString().split("T")[0];
  if (!harvestDate) {
    const err = $("err-batch-date");
    if (err) {
      err.textContent = "Vui lòng chọn ngày thu hoạch.";
      err.hidden = false;
    }
    hasError = true;
  } else if (harvestDate > today) {
    const err = $("err-batch-date");
    if (err) {
      err.textContent = "Ngày thu hoạch không thể ở tương lai so với ngày hiện tại.";
      err.hidden = false;
    }
    hasError = true;
  }

  if (hasError) {
    return;
  }

  const isEditing = editingBatchId !== null;
  const button = $("batch-submit");
  // Vô hiệu hóa nút Lưu ngay khi gửi để chặn nhấn đúp (T-20)
  button.disabled = true;
  button.textContent = "Đang lưu…";

  const selectedProduct = products.find((p) => p.id === selectedProductId);
  const payload = {
    plot_id: Number(farmSelect.value),
    farm_id: Number(farmSelect.value),
    product_id: selectedProductId || undefined,
    product_name: selectedProduct ? selectedProduct.name : productNameFallback,
    initial_quantity: rawQty,
    quantity: rawQty,
    harvest_date: harvestDate,
  };

  try {
    if (isEditing) {
      const updated = await apiRequest(`/batches/${editingBatchId}`, { method: "PUT", body: payload });
      toast(`Đã cập nhật lô #${updated.id} "${updated.product_name}"`, "success");
    } else {
      const created = await apiRequest("/batches", { method: "POST", body: payload });
      toast(`Tạo thành công lô #${created.id} - Mã lô: ${created.code}`, "success");

      // Hiển thị mã lô cỡ lớn 28px+ độ tương phản cao để đọc ngoài trời nắng (T-22)
      const banner = $("batch-success-banner");
      const codeDisplay = $("batch-success-code-display");
      if (banner && codeDisplay) {
        codeDisplay.textContent = created.code || `#${created.id}`;
        banner.hidden = false;
        banner.scrollIntoView({ behavior: "smooth", block: "center" });

        // Gắn nút sao chép mã lô
        const copyBtn = $("btn-copy-batch-code");
        if (copyBtn) {
          copyBtn.onclick = () => {
            if (navigator.clipboard) {
              navigator.clipboard.writeText(created.code);
            }
            toast(`Đã sao chép mã lô: ${created.code}`, "success");
          };
        }
      }
    }
    resetBatchForm();
    farmSelect.value = String(payload.farm_id);
    if (selectedProductId) productSelect.value = String(selectedProductId);
    await loadBatches();
    await refreshAuditLogsIfAdmin();
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
  if (!canHarvest()) {
    toast("Vai trò của bạn không có quyền sửa lô nông sản.", "error");
    return;
  }
  $("batch-entry").open = true;
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
  if (!canDelete()) {
    toast("Chỉ tài khoản Quản trị viên mới có quyền xoá dữ liệu.", "error");
    return;
  }
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

/* ----------------------------- 8.1. Kiểm tra toàn vẹn Hash-Chain (T-28, T-29) --- */
/** Xác thực toàn vẹn chuỗi sự kiện của một lô nông sản theo mã hoặc ID */
async function handleInspectChain() {
  const inputEl = $("inspect-batch-code");
  const resultContainer = $("inspect-result-container");
  const val = inputEl?.value?.trim();
  if (!val) {
    toast("Vui lòng nhập mã lô (VD: 4M8KQ2PY) hoặc ID lô cần kiểm tra.", "error");
    return;
  }

  resultContainer.hidden = false;
  resultContainer.innerHTML = '<div class="badge badge--muted">Đang kiểm tra tính toàn vẹn dữ liệu...</div>';

  try {
    let targetBatch = batches.find(
      (b) => (b.code && b.code.toUpperCase() === val.toUpperCase()) || String(b.id) === val
    );
    let targetId = targetBatch ? targetBatch.id : null;

    if (!targetId) {
      const searchRes = await apiRequest(`/batches?search=${encodeURIComponent(val)}`);
      if (Array.isArray(searchRes) && searchRes.length > 0) {
        targetBatch = searchRes[0];
        targetId = targetBatch.id;
      } else if (!isNaN(Number(val))) {
        targetId = Number(val);
      }
    }

    if (!targetId) {
      resultContainer.innerHTML = `<div class="integrity-alert-banner">❌ Không tìm thấy lô nông sản với mã hoặc ID "${escapeHtml(val)}".</div>`;
      return;
    }

    const integrity = await apiRequest(`/batches/${targetId}/integrity`);

    if (integrity.is_valid || integrity.valid) {
      resultContainer.innerHTML = `
        <div class="integrity-valid-badge">
          <span style="font-size:1.4rem;">✓</span>
          <div>
            <div><strong style="color:#15803d; font-size:1.05rem;">DỮ LIỆU TOÀN VẸN - KHÔNG BỊ CAN THIỆP (100%)</strong></div>
            <div>Mã lô: <strong>${escapeHtml(targetBatch?.code || '#' + targetId)}</strong> — Tổng số sự kiện: <strong>${integrity.total_events || 'Tất cả'}</strong></div>
            <div style="font-size:0.88rem; color:#166534; margin-top:4px;">Toàn bộ chuỗi sự kiện được ghi nhận chính xác và đảm bảo tính toàn vẹn tuyệt đối.</div>
          </div>
        </div>`;
    } else {
      const errId = integrity.tampered_event_id || integrity.event_id || "Chưa xác định";
      const errType = integrity.error_type || "HASH_MISMATCH";
      resultContainer.innerHTML = `
        <div class="integrity-alert-banner" style="display:block;">
          <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
            <span style="font-size:1.5rem;">🚨</span>
            <strong style="font-size:1.1rem;">CẢNH BÁO: PHÁT HIỆN CAN THIỆP DỮ LIỆU BẤT HỢP PHÁP!</strong>
          </div>
          <div>Mã lô: <strong>${escapeHtml(targetBatch?.code || '#' + targetId)}</strong></div>
          <div>Vị trí vi phạm: <strong>Sự kiện ID #${escapeHtml(errId)}</strong></div>
          <div>Loại lỗi phát hiện: <code>${escapeHtml(errType)}</code></div>
          <div style="margin-top:6px; font-size:0.9rem; color:#7f1d1d;">${escapeHtml(integrity.message || "Chuỗi mã băm không còn toàn vẹn.")}</div>
        </div>`;
    }
  } catch (error) {
    resultContainer.innerHTML = `<div class="integrity-alert-banner">Lỗi kiểm tra toàn vẹn: ${escapeHtml(error.message)}</div>`;
  }
}

/* ----------------------------- 8.2. Dòng thời gian sự kiện Timeline (T-31, T-32) --- */
/** Mở popup hiển thị dòng thời gian dọc của lô nông sản (tối ưu SQL JOIN 1 lượt + tự động kiểm tra toàn vẹn) */
async function openTimelineModal(batchId) {
  const modal = $("modal-timeline");
  const listEl = $("timeline-list");
  const alertBanner = $("timeline-alert-banner");
  const validBanner = $("timeline-valid-banner");
  const alertText = $("timeline-alert-text");
  const metaEl = $("timeline-batch-meta");

  if (!modal || !listEl) return;
  modal.hidden = false;
  listEl.innerHTML = '<p class="empty">Đang tải dòng thời gian...</p>';
  alertBanner.hidden = true;
  validBanner.hidden = true;

  const batch = batches.find((b) => b.id === batchId);
  if (metaEl && batch) {
    metaEl.innerHTML = `
      <div><strong>Lô hàng:</strong> ${escapeHtml(batch.code || '#' + batch.id)} (${escapeHtml(batch.product_name)})</div>
      <div><strong>Ngày thu hoạch:</strong> ${formatDate(batch.harvest_date)} · <strong>Khối lượng:</strong> ${formatNumber(batch.initial_quantity || batch.quantity)} ${escapeHtml(batch.unit || "kg")}</div>
    `;
  }

  try {
    const events = await apiRequest(`/batches/${batchId}/events`);
    const integrity = await apiRequest(`/batches/${batchId}/integrity`);

    if (integrity.is_valid || integrity.valid) {
      validBanner.hidden = false;
      alertBanner.hidden = true;
    } else {
      alertBanner.hidden = false;
      validBanner.hidden = true;
      const tamperedId = integrity.tampered_event_id || integrity.event_id || "";
      alertText.textContent = `CẢNH BÁO VI PHẠM: Dữ liệu đã bị can thiệp trái phép tại sự kiện #${tamperedId}! (${integrity.error_type || 'HASH_MISMATCH'}). ${integrity.message || ''}`;
    }

    if (!Array.isArray(events) || events.length === 0) {
      listEl.innerHTML = '<p class="empty">Lô hàng chưa có sự kiện nào trong chuỗi.</p>';
      return;
    }

    listEl.innerHTML = events
      .map((e) => {
        let dotClass = "timeline-item__dot";
        if (e.event_type.includes("INIT")) dotClass += " timeline-item__dot--init";
        else if (e.event_type.includes("ACCEPT")) dotClass += " timeline-item__dot--accept";
        else if (e.event_type.includes("REJECT")) dotClass += " timeline-item__dot--reject";

        const orgName = e.organization_name || (session?.organization_name || "Hợp tác xã");
        const userName = e.username || (session?.username || "Người dùng");
        const shortHash = e.current_hash
          ? `${e.current_hash.substring(0, 16)}...${e.current_hash.substring(e.current_hash.length - 8)}`
          : "—";
        const desc =
          e.payload?.description ||
          e.payload?.note ||
          e.payload?.message ||
          e.event_data ||
          `Sự kiện ${e.event_type}`;

        return `
          <div class="timeline-item">
            <div class="${dotClass}"></div>
            <div class="timeline-item__card">
              <div class="timeline-item__header">
                <span class="timeline-item__type">#${e.id} · ${escapeHtml(formatEventType(e.event_type))}</span>
                <span class="timeline-item__time">📅 ${escapeHtml(formatDateTime(e.timestamp || e.created_at))}</span>
              </div>
              <div class="timeline-item__meta">
                <strong>🏢 ${escapeHtml(orgName)}</strong> · 👤 ${escapeHtml(userName)}
              </div>
              <div style="margin-bottom: 8px; color: #1e293b;">
                ${escapeHtml(desc)}
              </div>
              <div class="timeline-item__hash" title="Mã băm SHA-256 toàn vẹn: ${escapeHtml(e.current_hash)}">
                🔒 SHA-256: <code>${escapeHtml(shortHash)}</code>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  } catch (error) {
    listEl.innerHTML = `<p class="empty empty--error">Lỗi khi tải dòng thời gian: ${escapeHtml(error.message)}</p>`;
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
const dataLoadState = { farms: "idle", batches: "idle", audit: "idle", pending: "idle" };
function dataErrorState(error) { return error.status === 403 ? "denied" : "error"; }
function dataStateText(state) {
  return ({idle:"—", loading:"Đang tải…", denied:"Không có quyền xem", error:"Không tải được dữ liệu"})[state] || "";
}
function renderStats() {
  const scope = session?.role === "inspector" ? "Toàn hệ thống" : `Tổ chức: ${session?.organization_name || "chưa được gán"}`;
  $("stat-batches").closest("article").querySelector(".stat-card__hint").textContent = `Trang ${batchPage}, tối đa 20 lô · ${scope} · Theo bộ lọc danh sách lô`;

  $("stat-farms").textContent = dataLoadState.farms === "ready" ? formatNumber(farms.length) : dataStateText(dataLoadState.farms);
  $("stat-batches").textContent = dataLoadState.batches === "ready" ? formatNumber(batches.length) : dataStateText(dataLoadState.batches);
  const totals = new Map();
  for (const batch of batches) {
    const unit = batch.unit || "kg";
    totals.set(unit, (totals.get(unit) || 0) + Number(batch.remaining_quantity ?? batch.quantity ?? 0));
  }
  $("stat-yield").textContent = [...totals].map(([unit, quantity]) => `${formatNumber(Math.round(quantity * 100) / 100)} ${unit}`).join(" · ") || "0";
  $("stat-audit").textContent = dataLoadState.audit === "ready" ? formatNumber(auditLogs.length) : dataStateText(dataLoadState.audit);
  if (dataLoadState.batches !== "ready") $("stat-yield").textContent = dataStateText(dataLoadState.batches);
  const pendingStat = $("stat-pending-handovers");
  if (pendingStat) {
    pendingStat.textContent = dataLoadState.pending === "ready" ? formatNumber(pendingHandovers.length) : dataStateText(dataLoadState.pending);
  }
}

/* ------------------------------------------ 10. Tài khoản (chỉ admin) --- */
let userPage = 1;
let userRequestVersion = 0;
const USER_PAGE_SIZE = 10;

async function loadUsers() {
  const version = ++userRequestVersion;
  const params = new URLSearchParams({ page: userPage, limit: USER_PAGE_SIZE });
  for (const [id, key] of [["user-search", "search"], ["user-role-filter", "role"], ["user-org-filter", "organization_id"], ["user-status-filter", "is_active"]]) {
    if ($(id).value) params.set(key, $(id).value);
  }
  $("user-load-status").textContent = "Đang tải tài khoản…";
  try {
    const data = await apiRequest(`/users?${params}`);
    if (version !== userRequestVersion) return;
    users = Array.isArray(data) ? data : [];
    renderUsers();
    $("user-load-status").textContent = `${users.length} tài khoản trên trang ${userPage}`;
  } catch (error) {
    if (version !== userRequestVersion) return;
    users = []; renderUsers();
    $("user-load-status").textContent = `Không tải được tài khoản: ${error.message}`;
    toast(error.message, "error");
  }
}

function renderUsers() {
  const isSysAdmin = isSystemAdmin();
  const isOrgAdminUser = session?.role === "org_admin";
  const privilegedRoles = ["system_admin", "admin", "org_admin", "inspector"];

  $("user-table-body").innerHTML = users.map(user => {
    const org = organizations.find(o => o.id === user.organization_id);
    const locked = user.is_locked || (user.locked_until && new Date(`${user.locked_until}Z`) > new Date());
    const status = !user.is_active ? "Vô hiệu hóa" : locked ? "Đã khóa" : "Hoạt động";
    const roleLabel = ROLE_NAMES[user.role] || user.role;
    const canManage = isSysAdmin
      ? user.id !== session?.id
      : isOrgAdminUser && user.organization_id === session?.organization_id && !privilegedRoles.includes(user.role);

    return `<tr><td>#${escapeHtml(user.id)}</td><td><strong>${escapeHtml(user.username)}</strong></td><td>${escapeHtml(user.email || "—")}</td>
      <td><span class="role-badge ${user.role === "system_admin" || user.role === "admin" ? "role-badge--admin" : "role-badge--farmer"}">${escapeHtml(roleLabel)}</span></td>
      <td>${escapeHtml(org?.name || "Chưa gán tổ chức")}</td><td><span class="badge ${user.is_active && !locked ? "badge--ok" : "badge--muted"}">${status}</span></td>
      <td class="account-actions">
        ${canManage ? `
          <button class="btn btn--light btn--sm" data-user-action="edit" data-id="${user.id}">Sửa</button>
          <button class="btn btn--light btn--sm" data-user-action="lock" data-id="${user.id}">${locked ? "Mở khóa" : "Khóa"}</button>
          <button class="btn btn--light btn--sm" data-user-action="active" data-id="${user.id}">${user.is_active ? "Vô hiệu hóa" : "Kích hoạt"}</button>
          <button class="btn btn--light btn--sm" data-user-action="password" data-id="${user.id}">Đặt mật khẩu</button>
        ` : `<span class="badge badge--muted">Không thao tác</span>`}
      </td></tr>`;
  }).join("");
  $("user-empty").hidden = users.length > 0;
  $("user-prev").disabled = userPage === 1;
  $("user-next").disabled = users.length < USER_PAGE_SIZE;
  $("user-page-label").textContent = `Trang ${userPage}`;
}

function accountOrgOptions() {
  return organizations.map(o => `<option value="${o.id}">${escapeHtml(o.name)}</option>`).join("");
}

function openAccount(user = null) {
  if (!isAdmin()) {
    toast("Không có quyền quản lý tài khoản.", "error");
    return;
  }
  $("account-form").reset();
  $("account-id").value = user?.id || "";
  $("account-title").textContent = user ? "Chỉnh sửa tài khoản" : "Tạo tài khoản";
  $("account-username").value = user?.username || "";
  $("account-username").disabled = !!user;
  $("account-email").value = user?.email || "";

  if (session?.role === "org_admin") {
    $("account-org").innerHTML = `<option value="${session.organization_id}">${escapeHtml(session.organization_name || "Tổ chức của bạn")}</option>`;
    $("account-org").value = session.organization_id;
    $("account-org").disabled = true;
    $("account-role").innerHTML = `
      <option value="farmer">Nông dân</option>
      <option value="processor">Nhà chế biến</option>
      <option value="transporter">Vận chuyển</option>
      <option value="distributor">Nhà phân phối</option>`;
  } else {
    $("account-org").innerHTML = accountOrgOptions();
    $("account-org").disabled = false;
    if (user) $("account-org").value = user.organization_id;
    $("account-role").innerHTML = `
      <option value="farmer">Nông dân</option>
      <option value="processor">Nhà chế biến</option>
      <option value="transporter">Vận chuyển</option>
      <option value="distributor">Nhà phân phối</option>
      <option value="org_admin">Quản trị tổ chức</option>
      <option value="inspector">Thanh tra viên</option>
      <option value="system_admin">Quản trị hệ thống</option>`;
  }

  $("account-role").value = user?.role || "farmer";
  $("account-password-field").hidden = !!user;
  $("account-password").required = !user;
  $("account-error").hidden = true;
  $("account-dialog").showModal();
}

function bindAccountControls() {
  $("btn-change-password").addEventListener("click", () => {
    $("password-form").reset(); $("password-user-id").value = "self";
    $("password-title").textContent = "Đổi mật khẩu của bạn";
    $("password-current-label").textContent = "Mật khẩu hiện tại *";
    $("password-error").hidden = true; $("password-dialog").showModal();
  });
  $("btn-create-user").addEventListener("click", () => openAccount());
  $("account-close").addEventListener("click", () => $("account-dialog").close());
  $("password-close").addEventListener("click", () => { $("password-dialog").close(); $("password-form").reset(); });

  $("btn-create-org")?.addEventListener("click", () => {
    $("org-form").reset();
    $("org-error").hidden = true;
    $("org-dialog").showModal();
  });
  $("org-close")?.addEventListener("click", () => {
    $("org-dialog").close();
    $("org-form").reset();
  });
  $("org-form")?.addEventListener("submit", async event => {
    event.preventDefault();
    setButtonLoading($("org-save"), true, "Đang lưu…", "Lưu tổ chức");
    try {
      const newOrg = await apiRequest("/organizations", {
        method: "POST",
        body: {
          name: $("org-name").value.trim(),
          code: $("org-code").value.trim(),
          description: $("org-description").value.trim() || undefined,
        },
      });
      organizations.push(newOrg);
      $("org-dialog").close();
      $("org-form").reset();
      toast(`Đã thêm tổ chức ${newOrg.name}.`, "success");
      await loadUsers();
    } catch (err) {
      $("org-error").textContent = err.message;
      $("org-error").hidden = false;
    } finally {
      setButtonLoading($("org-save"), false, "Đang lưu…", "Lưu tổ chức");
    }
  });

  let searchTimer;
  $("user-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { userPage = 1; loadUsers(); }, 300); });
  for (const id of ["user-role-filter", "user-org-filter", "user-status-filter"]) $(id).addEventListener("change", () => { userPage = 1; loadUsers(); });
  $("user-prev").addEventListener("click", () => { userPage--; loadUsers(); });
  $("user-next").addEventListener("click", () => { userPage++; loadUsers(); });
  $("account-form").addEventListener("submit", async event => {
    event.preventDefault();
    const id = $("account-id").value;
    const orgId = session?.role === "org_admin" ? session.organization_id : Number($("account-org").value);
    const body = { email: $("account-email").value, role: $("account-role").value, organization_id: orgId };
    if (!id) Object.assign(body, { username: $("account-username").value, password: $("account-password").value });
    setButtonLoading($("account-save"), true, "Đang lưu…", "Lưu tài khoản");
    try {
      const updated = await apiRequest(id ? `/users/${id}` : "/users", { method: id ? "PATCH" : "POST", body });
      if (updated.username === session.username) {
        startSession({...updated, password: session.password, organization_name: organizations.find(o => o.id === updated.organization_id)?.name});
      }
      $("account-dialog").close(); $("account-form").reset();
      toast("Đã lưu tài khoản.", "success"); if (isAdmin()) { await loadUsers(); await loadAuditLogs({silent: true}); } else { await reloadAll({silent:true}); }
    } catch (error) { $("account-error").textContent = error.message; $("account-error").hidden = false; }
    finally { setButtonLoading($("account-save"), false, "Đang lưu…", "Lưu tài khoản"); }
  });
  $("user-table-body").addEventListener("click", async event => {
    const button = event.target.closest("button[data-user-action]");
    if (!button) return;
    const user = users.find(u => u.id === Number(button.dataset.id));
    if (!user) return;
    const action = button.dataset.userAction;
    if (action === "edit") { openAccount(user); return; }
    if (action === "password") {
      $("password-form").reset(); $("password-user-id").value = user.id;
      $("password-title").textContent = `Đặt mật khẩu: ${user.username}`;
      $("password-current-label").textContent = "Mật khẩu của bạn để xác nhận *";
      $("password-error").hidden = true; $("password-dialog").showModal(); return;
    }
    if (!confirm(`${button.textContent} tài khoản ${user.username}?`)) return;
    button.disabled = true;
    try {
      const locked = user.is_locked || (user.locked_until && new Date(`${user.locked_until}Z`) > new Date());
      await apiRequest(`/users/${user.id}`, {method: "PATCH", body: action === "lock" ? {is_locked: !locked} : {is_active: !user.is_active}});
      toast("Đã cập nhật trạng thái tài khoản.", "success"); await loadUsers(); await loadAuditLogs({silent: true});
    } catch (error) { toast(error.message, "error"); }
    finally { button.disabled = false; }
  });
  $("password-form").addEventListener("submit", async event => {
    event.preventDefault();
    if ($("password-new").value !== $("password-confirm").value) { $("password-error").textContent = "Hai mật khẩu mới chưa khớp."; $("password-error").hidden = false; return; }
    const self = $("password-user-id").value === "self";
    const user = users.find(u => u.id === Number($("password-user-id").value));
    setButtonLoading($("password-save"), true, "Đang lưu…", "Đặt lại mật khẩu");
    try {
      await apiRequest(self ? "/auth/change-password" : `/users/${$("password-user-id").value}/reset-password`, {method: "POST", body: { [self ? "current_password" : "admin_password"]: $("password-admin").value, new_password: $("password-new").value}});
      $("password-dialog").close(); $("password-form").reset();
      if (self || user?.username === session.username) { clearSession(); applySessionToUi(); toast("Mật khẩu đã đổi. Đăng nhập lại bằng mật khẩu mới.", "success"); }
      else { toast("Đã đặt lại mật khẩu.", "success"); await loadAuditLogs({silent: true}); }
    } catch (error) { $("password-error").textContent = error.message; $("password-error").hidden = false; }
    finally { setButtonLoading($("password-save"), false, "Đang lưu…", "Đặt lại mật khẩu"); }
  });
}

/* -------------------------------------- 11. Nhật ký hoạt động (chỉ admin) --- */
/**
 * GET /audit-logs (chỉ admin) -> vẽ bảng "Nhật ký hoạt động" và
 * cập nhật thẻ thống kê "Nhật ký hoạt động" trên dashboard.
 */
async function loadAuditLogs({ silent = false } = {}) {
  const actor = session;
  dataLoadState.audit = "loading"; renderStats();
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
    if (actor !== session) return;
    dataLoadState.audit = "ready";
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
    if (actor !== session) return;
    dataLoadState.audit = dataErrorState(error);
    auditLogs = [];
    renderAuditLogs();
    $("audit-empty").hidden = true;

    const denied = error.status === 401 || error.status === 403;
    errorBox.textContent = denied
      ? `Không có quyền xem nhật ký hoạt động (${error.message})`
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
    reset_password: "Đặt lại mật khẩu",
    change_password: "Đổi mật khẩu",
  };
  const entityLabels = {
    farm: "Vùng trồng",
    batch: "Lô nông sản",
    user: "Tài khoản",
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
  const sprintDemo = window.AGRITRACE_CONFIG?.maxSprint === 3;
  if (sprintDemo) {
    $("login-username").placeholder = "Email hoặc tên tài khoản s123_…";
  }
  const demoAccountSelect = $("sprint-demo-account");
  if (demoAccountSelect) {
    demoAccountSelect.addEventListener("change", handleDemoAccountSelect);
  }
  $("btn-logout").addEventListener("click", handleLogout);
  $("farm-form").addEventListener("submit", handleFarmSubmit);
  $("batch-form").addEventListener("submit", handleBatchSubmit);
  $("farm-cancel").addEventListener("click", () => cancelEdit("farm"));
  $("batch-cancel").addEventListener("click", () => cancelEdit("batch"));
  $("btn-reload").addEventListener("click", () => reloadAll());
  $("btn-load-audit").addEventListener("click", () => loadAuditLogs());

  // Đăng nhập nhanh cho tài khoản demo - S-04: điền **email** để minh hoạ
  // đăng nhập bằng email (người dùng cũng có thể sửa lại thành username).
  const quickAdmin = $("btn-quick-admin");
  if (quickAdmin) {
    quickAdmin.addEventListener("click", () => {
      $("login-username").value = "demo_admin@demo.local";
      $("login-password").value = "";
      setLoginError("");
      $("login-password").focus();
    });
  }
  const quickFarmer = $("btn-quick-farmer");
  if (quickFarmer) {
    quickFarmer.addEventListener("click", () => {
      $("login-username").value = "demo_farm@demo.local";
      $("login-password").value = "";
      setLoginError("");
      $("login-password").focus();
    });
  }
  const quickFarmerTg = $("btn-quick-farmer-tg");
  if (quickFarmerTg) {
    quickFarmerTg.addEventListener("click", () => {
      $("login-username").value = "demo_packing@demo.local";
      $("login-password").value = "";
      setLoginError("");
      $("login-password").focus();
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

  // Bảng và nút của Lô chờ xác nhận bàn giao
  const pendingTbody = $("pending-handovers-table-body");
  if (pendingTbody) {
    pendingTbody.addEventListener("click", handleTableAction);
  }
  const btnRefreshPending = $("btn-refresh-pending");
  if (btnRefreshPending) {
    btnRefreshPending.addEventListener("click", async () => {
      await loadPendingHandovers();
      toast("Đã làm mới danh sách lô chờ xác nhận.", "info");
    });
  }

  // Modal bàn giao sự kiện
  const btnCloseHandover = $("btn-close-handover-modal");
  if (btnCloseHandover) btnCloseHandover.addEventListener("click", closeHandoverModal);
  const btnCancelHandover = $("btn-cancel-handover");
  if (btnCancelHandover) btnCancelHandover.addEventListener("click", closeHandoverModal);
  const handoverForm = $("handover-form");
  if (handoverForm) handoverForm.addEventListener("submit", handleHandoverSubmit);

  // Modal từ chối sự kiện
  const btnCloseReject = $("btn-close-reject-modal");
  if (btnCloseReject) btnCloseReject.addEventListener("click", closeRejectModal);
  const btnCancelReject = $("btn-cancel-reject");
  if (btnCancelReject) btnCancelReject.addEventListener("click", closeRejectModal);
  const rejectForm = $("reject-form");
  if (rejectForm) rejectForm.addEventListener("submit", handleRejectSubmit);
  const rejectReasonInput = $("reject-reason");
  if (rejectReasonInput) rejectReasonInput.addEventListener("input", updateRejectCounter);

  // Đóng modal khi bấm ra ngoài nền backdrop
  const modalHandover = $("modal-handover");
  if (modalHandover) {
    modalHandover.addEventListener("click", (e) => {
      if (e.target === modalHandover) closeHandoverModal();
    });
  }
  const modalReject = $("modal-reject");
  if (modalReject) {
    modalReject.addEventListener("click", (e) => {
      if (e.target === modalReject) closeRejectModal();
    });
  }

  // Quản lý sản phẩm (T-17)
  const btnOpenAddProduct = $("btn-open-add-product");
  if (btnOpenAddProduct) {
    btnOpenAddProduct.addEventListener("click", () => {
      $("modal-add-product").hidden = false;
      $("product-name")?.focus();
    });
  }
  const btnCloseProductModal = $("btn-close-product-modal");
  if (btnCloseProductModal) {
    btnCloseProductModal.addEventListener("click", () => {
      $("modal-add-product").hidden = true;
    });
  }
  const btnCancelProduct = $("btn-cancel-product");
  if (btnCancelProduct) {
    btnCancelProduct.addEventListener("click", () => {
      $("modal-add-product").hidden = true;
    });
  }
  const modalAddProduct = $("modal-add-product");
  if (modalAddProduct) {
    modalAddProduct.addEventListener("click", (e) => {
      if (e.target === modalAddProduct) modalAddProduct.hidden = true;
    });
  }
  const productForm = $("product-form");
  if (productForm) {
    productForm.addEventListener("submit", handleProductSubmit);
  }

  // Tìm kiếm lô (Debounce 300ms) & Bộ lọc sản phẩm (T-34)
  const batchSearchInput = $("batch-search-input");
  if (batchSearchInput) {
    batchSearchInput.addEventListener("input", onBatchSearchInput);
  }
  const batchFilterProduct = $("batch-filter-product");
  if (batchFilterProduct) {
    batchFilterProduct.addEventListener("change", () => { batchPage = 1; selectedBatchIds.clear(); loadBatches(); });
  }
  const btnRefreshBatches = $("btn-refresh-batches");
  if (btnRefreshBatches) {
    btnRefreshBatches.addEventListener("click", () => loadBatches());
  }
  const btnDemoLineage = $("btn-demo-lineage");
  if (btnDemoLineage) {
    btnDemoLineage.addEventListener("click", openLineageDemo);
  }
  const btnDismissBatchBanner = $("btn-dismiss-batch-banner");
  if (btnDismissBatchBanner) {
    btnDismissBatchBanner.addEventListener("click", () => {
      const banner = $("batch-success-banner");
      if (banner) banner.hidden = true;
    });
  }

  // Cán bộ kiểm tra Inspector (T-29)
  const btnInspectChain = $("btn-inspect-chain");
  if (btnInspectChain) {
    btnInspectChain.addEventListener("click", handleInspectChain);
  }
  const inspectBatchCode = $("inspect-batch-code");
  if (inspectBatchCode) {
    inspectBatchCode.addEventListener("keyup", (e) => {
      if (e.key === "Enter") handleInspectChain();
    });
  }

  // Modal Timeline dọc (T-31, T-32)
  const btnCloseTimeline = $("btn-close-timeline-modal");
  if (btnCloseTimeline) {
    btnCloseTimeline.addEventListener("click", () => {
      $("modal-timeline").hidden = true;
    });
  }
  const modalTimeline = $("modal-timeline");
  if (modalTimeline) {
    modalTimeline.addEventListener("click", (e) => {
      if (e.target === modalTimeline) modalTimeline.hidden = true;
    });
  }

  // ==================== SPRINT 3 SỰ KIỆN ====================
  // Checkbox chọn lô & Gộp lô (T-46)
  const batchSelectAll = $("batch-select-all");
  if (batchSelectAll) {
    batchSelectAll.addEventListener("change", (e) => {
      const checked = e.target.checked;
      selectedBatchIds.clear();
      if (checked) {
        batches.forEach((b) => selectedBatchIds.add(b.id));
      }
      document.querySelectorAll(".batch-select-checkbox").forEach((cb) => {
        cb.checked = checked;
      });
      updateMergeButtonState();
    });
  }

  const batchTableBody = $("batch-table-body");
  if (batchTableBody) {
    batchTableBody.addEventListener("change", (e) => {
      if (e.target.classList.contains("batch-select-checkbox")) {
        const id = Number(e.target.dataset.id);
        if (e.target.checked) {
          selectedBatchIds.add(id);
        } else {
          selectedBatchIds.delete(id);
        }
        updateMergeButtonState();
      }
    });
  }

  const btnOpenMerge = $("btn-open-merge-batches");
  if (btnOpenMerge) {
    btnOpenMerge.addEventListener("click", openMergeModal);
  }

  // Chi tiết lô 3 Tab (S-25: T-58, T-59)
  const btnCloseDetails = $("btn-close-batch-details");
  if (btnCloseDetails) {
    btnCloseDetails.addEventListener("click", () => $("modal-batch-details").hidden = true);
  }
  const modalBatchDetails = $("modal-batch-details");
  if (modalBatchDetails) {
    modalBatchDetails.addEventListener("click", (e) => {
      if (e.target === modalBatchDetails) modalBatchDetails.hidden = true;
    });
  }
  const tabBtnOverview = $("tab-btn-overview");
  if (tabBtnOverview) tabBtnOverview.addEventListener("click", () => switchDetailTab("overview"));
  const tabBtnTimeline = $("tab-btn-timeline");
  if (tabBtnTimeline) tabBtnTimeline.addEventListener("click", () => switchDetailTab("timeline"));
  const tabBtnLineage = $("tab-btn-lineage");
  if (tabBtnLineage) tabBtnLineage.addEventListener("click", () => switchDetailTab("lineage"));
  const btnLineageBackward = $("btn-lineage-backward");
  if (btnLineageBackward) btnLineageBackward.addEventListener("click", () => setLineageMode("backward"));
  const btnLineageForward = $("btn-lineage-forward");
  if (btnLineageForward) btnLineageForward.addEventListener("click", () => setLineageMode("forward"));
  const btnDetailVerify = $("btn-detail-verify-chain");
  if (btnDetailVerify) {
    btnDetailVerify.addEventListener("click", () => {
      if (currentDetailBatchId) verifyDetailChain(currentDetailBatchId);
    });
  }

  // Tách lô (S-17, S-18: T-40, T-41)
  const btnCloseSplit = $("btn-close-split-modal");
  if (btnCloseSplit) btnCloseSplit.addEventListener("click", () => $("modal-split-batch").hidden = true);
  const btnCancelSplit = $("btn-cancel-split");
  if (btnCancelSplit) btnCancelSplit.addEventListener("click", () => $("modal-split-batch").hidden = true);
  const btnAddSplitItem = $("btn-add-split-item");
  if (btnAddSplitItem) btnAddSplitItem.addEventListener("click", () => addSplitItemRow(""));
  const splitForm = $("split-form");
  if (splitForm) splitForm.addEventListener("submit", handleSplitSubmit);
  const modalSplit = $("modal-split-batch");
  if (modalSplit) {
    modalSplit.addEventListener("click", (e) => {
      if (e.target === modalSplit) modalSplit.hidden = true;
    });
  }

  // Tách lô thành công
  const btnCloseSplitSuccess = $("btn-close-split-success");
  if (btnCloseSplitSuccess) btnCloseSplitSuccess.addEventListener("click", () => $("modal-split-success").hidden = true);
  const btnDoneSplitSuccess = $("btn-done-split-success");
  if (btnDoneSplitSuccess) btnDoneSplitSuccess.addEventListener("click", () => $("modal-split-success").hidden = true);
  const modalSplitSuccess = $("modal-split-success");
  if (modalSplitSuccess) {
    modalSplitSuccess.addEventListener("click", (e) => {
      if (e.target === modalSplitSuccess) modalSplitSuccess.hidden = true;
    });
  }

  // Gộp lô (S-19, S-20: T-44, T-45, T-46)
  const btnCloseMerge = $("btn-close-merge-modal");
  if (btnCloseMerge) btnCloseMerge.addEventListener("click", () => $("modal-merge-batch").hidden = true);
  const btnCancelMerge = $("btn-cancel-merge");
  if (btnCancelMerge) btnCancelMerge.addEventListener("click", () => $("modal-merge-batch").hidden = true);
  const mergeForm = $("merge-form");
  if (mergeForm) mergeForm.addEventListener("submit", handleMergeSubmit);
  const modalMerge = $("modal-merge-batch");
  if (modalMerge) {
    modalMerge.addEventListener("click", (e) => {
      if (e.target === modalMerge) modalMerge.hidden = true;
    });
  }

  // Gộp lô thành công
  const btnCloseMergeSuccess = $("btn-close-merge-success");
  if (btnCloseMergeSuccess) btnCloseMergeSuccess.addEventListener("click", () => $("modal-merge-success").hidden = true);
  const btnDoneMergeSuccess = $("btn-done-merge-success");
  if (btnDoneMergeSuccess) btnDoneMergeSuccess.addEventListener("click", () => $("modal-merge-success").hidden = true);
  const modalMergeSuccess = $("modal-merge-success");
  if (modalMergeSuccess) {
    modalMergeSuccess.addEventListener("click", (e) => {
      if (e.target === modalMergeSuccess) modalMergeSuccess.hidden = true;
    });
  }
}

/* =====================================================================
   SPRINT 3: NGHIỆP VỤ TÁCH LÔ, GỘP LÔ, PHẢ HỆ BFS VÀ CHI TIẾT 3 TAB
   ===================================================================== */

/** Sao chép văn bản vào clipboard kèm thông báo. */
function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      toast(`Đã sao chép: ${text}`, "success");
    }).catch(() => {
      window.prompt("Sao chép mã này:", text);
    });
  } else {
    window.prompt("Sao chép mã này:", text);
  }
}

/** Rút gọn chuỗi băm SHA-256 dạng "df3c8b…37af0" cho vừa khung hiển thị. */
function shortenHash(hash) {
  const text = String(hash || "");
  if (!text) return "—";
  return text.length > 14 ? `${text.slice(0, 6)}…${text.slice(-5)}` : text;
}

/** Nhãn mã lô dạng badge màu (tự escape chống XSS). */
function batchCodeBadge(code) {
  const text = (code === null || code === undefined || code === "") ? "—" : String(code);
  return `<span class="batch-code-badge">${escapeHtml(text)}</span>`;
}

/** Từ điển nhãn tiếng Việt cho các khóa payload hay gặp. */
const TIMELINE_PAYLOAD_LABELS = {
  batch_code: "🏷️ Mã lô",
  product_name: "📦 Sản phẩm",
  quantity: "⚖️ Khối lượng",
  initial_quantity: "⚖️ Khối lượng ban đầu",
  temperature: "🌡️ Nhiệt độ (°C)",
  note: "📝 Ghi chú",
  description: "📝 Mô tả",
  message: "💬 Thông điệp",
  location: "📍 Vị trí",
  step: "🔢 Bước",
  from_org: "🏢 Từ tổ chức",
  to_org: "🏢 Đến tổ chức",
  total_quantity: "⚖️ Tổng khối lượng",
  quantity_taken: "⚖️ Khối lượng nhận",
  total_split_quantity: "⚖️ Tổng khối lượng tách",
  harvest_date: "📅 Ngày thu hoạch",
  parent_batch_code: "🏷️ Mã lô nguồn",
  merged_batch_code: "🏷️ Mã lô gộp",
};

/**
 * Dựng phần thân thẻ sự kiện theo nghiệp vụ (S-25):
 * - MERGE / EXPORT_MERGE: sản phẩm, tổng khối lượng (số lớn) và danh sách lô nguồn.
 * - SPLIT / GENESIS_SPLIT: khối lượng tách, lô gốc và danh sách lô con mới sinh.
 * - Bàn giao / Thu hoạch: tóm tắt tổ chức, sản phẩm, khối lượng…
 * Tuyệt đối KHÔNG in khối JSON thô.
 */
function renderTimelineBody(evt, p) {
  const type = String(evt.event_type || "").toUpperCase();
  const fallbackDesc = evt.event_data || p.description || p.note || p.message || "";

  if (type === "MERGE") {
    const parents = Array.isArray(p.parent_batches) ? p.parent_batches : [];
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label">📦 Sản phẩm</span>
          <strong>${escapeHtml(p.product_name || "—")}</strong>
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label">⚖️ Tổng khối lượng</span>
          <span class="tl-weight-big">${formatNumber(p.total_quantity)}<span class="tl-unit">${escapeHtml(p.unit || "kg")}</span></span>
        </div>
      </div>
      <div class="tl-source-title">🏷️ Các lô nguồn tham gia gộp (${parents.length})</div>
      <div class="tl-source-list">
        ${parents.length
          ? parents.map((s) => `
            <div class="tl-source-item">
              ${batchCodeBadge(s.code || (s.id != null ? "#" + s.id : "—"))}
              <span class="tl-source-qty">＋ ${formatNumber(s.quantity_taken)} ${escapeHtml(p.unit || "kg")}</span>
            </div>`).join("")
          : `<em class="tl-muted">Không có dữ liệu lô nguồn.</em>`}
      </div>`;
  }

  if (type === "EXPORT_MERGE") {
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label">🏷️ Lô gộp nhận hàng</span>
          ${batchCodeBadge(p.merged_batch_code || (p.merged_batch_id != null ? "#" + p.merged_batch_id : "—"))}
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label">⚖️ Khối lượng đóng góp</span>
          <span class="tl-weight-big">${formatNumber(p.quantity_taken)}<span class="tl-unit">${escapeHtml(p.unit || "kg")}</span></span>
        </div>
      </div>`;
  }

  if (type === "SPLIT") {
    const codes = Array.isArray(p.child_batch_codes) ? p.child_batch_codes : [];
    const qtys = Array.isArray(p.child_quantities) ? p.child_quantities : [];
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label">🏷️ Lô gốc (lô mẹ được tách)</span>
          ${batchCodeBadge(currentDetailBatchCode || (evt.batch_id != null ? "#" + evt.batch_id : "—"))}
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label">✂️ Khối lượng tách</span>
          <span class="tl-weight-big">${formatNumber(p.total_split_quantity)}<span class="tl-unit">${escapeHtml(p.unit || "kg")}</span></span>
        </div>
      </div>
      <div class="tl-source-title">🏷️ Các lô con mới sinh (${codes.length})</div>
      <div class="tl-source-list">
        ${codes.length
          ? codes.map((c, i) => `
            <div class="tl-source-item">
              ${batchCodeBadge(c)}
              <span class="tl-source-qty">${formatNumber(qtys[i])} ${escapeHtml(p.unit || "kg")}</span>
            </div>`).join("")
          : `<em class="tl-muted">Không có dữ liệu lô con.</em>`}
      </div>`;
  }
  if (type === "GENESIS_SPLIT") {
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label">🏷️ Lô gốc</span>
          ${batchCodeBadge(p.parent_batch_code || (p.parent_batch_id != null ? "#" + p.parent_batch_id : "—"))}
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label">✂️ Khối lượng tách</span>
          <span class="tl-weight-big">${formatNumber(p.quantity)}<span class="tl-unit">${escapeHtml(p.unit || "kg")}</span></span>
        </div>
      </div>`;
  }

  if (type === "HANDOVER_INIT" || type === "HANDOVER_ACCEPT" || type === "HANDOVER_REJECT") {
    const from = p.from_org || organizations.find(o => o.id === p.from_org_id)?.name || (p.from_org_id != null ? `Tổ chức #${p.from_org_id}` : "—");
    const to = p.to_org || organizations.find(o => o.id === p.to_org_id)?.name || (p.to_org_id != null ? `Tổ chức #${p.to_org_id}` : "—");
    const note = p.message || p.note || p.reject_reason || "";
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label">🏢 Từ tổ chức</span>
          <strong>${escapeHtml(from)}</strong>
        </div>
        <div class="tl-metric">
          <span class="tl-metric__label">🏢 Đến tổ chức</span>
          <strong>${escapeHtml(to)}</strong>
        </div>
      </div>
      ${note ? `<div class="tl-note">${escapeHtml(note)}</div>` : ""}`;
  }

  if (type === "HARVEST") {
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label">📦 Sản phẩm</span>
          <strong>${escapeHtml(p.product_name || "—")}</strong>
        </div>
        <div class="tl-metric">
          <span class="tl-metric__label">🏷️ Mã lô</span>
          ${batchCodeBadge(p.batch_code || (evt.batch_id != null ? "#" + evt.batch_id : "—"))}
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label">⚖️ Khối lượng thu hoạch</span>
          <span class="tl-weight-big">${formatNumber(p.initial_quantity)}<span class="tl-unit">${escapeHtml(p.unit || "kg")}</span></span>
        </div>
      </div>`;
  }

  // Mặc định: hiển thị mô tả + bảng khóa/giá trị thân thiện (không bao giờ in JSON thô).
  const rows = [];
  Object.keys(p || {}).forEach((key) => {
    if (key === "event_type") return;
    const val = p[key];
    if (val === null || val === undefined || typeof val === "object") return;
    const display = typeof val === "number" ? formatNumber(val) : String(val);
    rows.push(`
      <div class="tl-kv">
        <span class="tl-kv__key">${escapeHtml(TIMELINE_PAYLOAD_LABELS[key] || key)}</span>
        <span class="tl-kv__val">${escapeHtml(display)}</span>
      </div>`);
  });
  const desc = fallbackDesc ? `<div class="tl-note">${escapeHtml(fallbackDesc)}</div>` : "";
  const table = rows.length ? `<div class="tl-kv-list">${rows.join("")}</div>` : "";
  return (desc + table) || `<div class="tl-note">Sự kiện ${escapeHtml(type)}.</div>`;
}

/** Vẽ dòng sự kiện trong Timeline HTML (Tab 2 - S-25). */
function renderTimelineItemHtml(evt) {
  const typeLabels = {
    HARVEST: "🌱 Thu hoạch ban đầu",
    SPLIT: "✂️ Tách lô",
    GENESIS_SPLIT: "✂️ Lô được tạo từ thao tác tách",
    MERGE: "🔀 Gộp lô",
    EXPORT_MERGE: "🔀 Xuất gộp lô",
    HANDOVER_INIT: "🚚 Yêu cầu bàn giao",
    HANDOVER_SENT: "🚚 Yêu cầu bàn giao",
    HANDOVER_ACCEPT: "📥 Đã tiếp nhận",
    HANDOVER_ACCEPTED: "📥 Đã tiếp nhận",
    HANDOVER_REJECT: "❌ Từ chối tiếp nhận",
    HANDOVER_REJECTED: "❌ Từ chối tiếp nhận",
    CONSUMED: "🍽️ Đã tiêu thụ",
  };
  const type = String(evt.event_type || "").toUpperCase();
  const typeClass = type.toLowerCase().replace(/_/g, "-");
  const eventLabel = typeLabels[type] || evt.event_type || "Sự kiện";

  let payload = evt.payload;
  if (typeof payload === "string") {
    try { payload = JSON.parse(payload); } catch (e) { payload = {}; }
  }
  if (!payload || typeof payload !== "object") payload = {};

  const fullHash = evt.current_hash || evt.record_hash || evt.event_hash || "";
  const actor = evt.username || evt.actor_username || evt.actor || "Thông tin nội bộ";
  const orgName = evt.organization_name || "";

  return `
    <div class="timeline-item timeline-item--${escapeHtml(typeClass)}">
      <div class="timeline-item__dot timeline-item__dot--${escapeHtml(typeClass)}"></div>
      <div class="timeline-item__card">
        <div class="timeline-item__header">
          <span class="timeline-item__type">${escapeHtml(eventLabel)}</span>
          <span class="timeline-item__time">${escapeHtml(formatDateTime(evt.timestamp || evt.created_at))}</span>
        </div>
        <div class="timeline-item__meta">
          <strong>Người thực hiện:</strong> ${escapeHtml(actor)}${orgName ? ` · 🏢 ${escapeHtml(orgName)}` : ""}
        </div>
        <div class="timeline-item__body">${renderTimelineBody(evt, payload)}</div>
        <div class="hash-row">
          <span class="hash-row__label">🔒 SHA-256</span>
          <code class="hash-row__code" title="${escapeHtml(fullHash || "Không có mã băm")}">${escapeHtml(shortenHash(fullHash))}</code>
          <button type="button" class="hash-copy-btn" data-hash="${escapeHtml(fullHash)}" title="Sao chép mã băm đầy đủ" aria-label="Sao chép mã băm đầy đủ">📋 Sao chép</button>
        </div>
      </div>
    </div>`;
}

/** Sao chép mã băm đầy đủ vào clipboard và phản hồi nhanh "Đã chép". */
function copyHashToClipboard(button) {
  const full = button.getAttribute("data-hash") || "";
  if (!full) return;

  const showDone = () => {
    const original = button.textContent;
    button.textContent = "✓ Đã chép";
    button.classList.add("is-copied");
    window.setTimeout(() => {
      button.textContent = original;
      button.classList.remove("is-copied");
    }, 1500);
    toast("Đã chép mã băm vào clipboard.", "success");
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(full).then(showDone).catch(() => window.prompt("Sao chép mã băm:", full));
  } else {
    window.prompt("Sao chép mã băm:", full);
  }
}

/** Mở modal dòng thời gian (chuyển sang Tab 2 của Chi tiết Lô) */
function openTimelineModal(batchId) {
  openBatchDetailsModal(batchId);
  switchDetailTab("timeline");
}

/** Mở modal chi tiết lô trung tâm 3 Tab (S-25: T-58, T-59) */
async function openBatchDetailsModal(batchId) {
  currentDetailBatchId = batchId;
  const modal = $("modal-batch-details");
  if (!modal) return;
  modal.hidden = false;
  switchDetailTab("overview");
  await loadDetailOverview(batchId);
}

/** Chuyển đổi giữa 3 Tab trong màn hình chi tiết lô (T-59) */
function switchDetailTab(tabName) {
  currentDetailTab = tabName;
  const tabBtns = {
    overview: $("tab-btn-overview"),
    timeline: $("tab-btn-timeline"),
    lineage: $("tab-btn-lineage"),
  };
  const tabContents = {
    overview: $("tab-content-overview"),
    timeline: $("tab-content-timeline"),
    lineage: $("tab-content-lineage"),
  };

  Object.keys(tabBtns).forEach((k) => {
    if (tabBtns[k]) tabBtns[k].classList.toggle("is-active", k === tabName);
    if (tabContents[k]) tabContents[k].hidden = (k !== tabName);
  });

  if (tabName === "timeline" && currentDetailBatchId) {
    loadDetailTimeline(currentDetailBatchId);
  } else if (tabName === "lineage" && currentDetailBatchId) {
    if (currentLineageMode === "forward") {
      loadDetailLineageForward(currentDetailBatchId);
    } else {
      loadDetailLineage(currentDetailBatchId);
    }
  }
}

/** Tab 1: Tải thông tin tổng quan của lô (T-58, T-59) */
async function loadDetailOverview(batchId) {
  const loading = $("detail-overview-loading");
  const body = $("detail-overview-body");
  const titleCode = $("detail-batch-title-code");
  if (loading) loading.hidden = false;
  if (body) body.hidden = true;

  try {
    const data = await apiRequest(`/batches/${batchId}/summary`);
    const b = data.batch;
    if (titleCode) titleCode.textContent = b.code || `#${b.id}`;
    currentDetailBatchCode = b.code || "";

    // Kiểm tra trạng thái chờ bàn giao (T-56, T-57): ưu tiên cờ tổng hợp từ backend
    const isPending = Boolean(b.is_pending) || Boolean(data.has_pending_handover) || (data.pending_handover != null);
    const pendingBanner = $("detail-pending-banner");
    if (pendingBanner) pendingBanner.hidden = !isPending;

    const actionGroup = $("detail-action-buttons-group");
    if (actionGroup) {
      // Ẩn các nút nghiệp vụ nếu lô đang chờ duyệt bàn giao (T-59)
      actionGroup.hidden = isPending;
    }

    const isHolder = session && (
      b.current_org_id == null ||
      session.organization_id == null ||
      b.current_org_id === session.organization_id
    );

    // Ưu tiên cờ nghiệp vụ tổng hợp từ backend (đã tính cả chờ bàn giao, trạng thái, khối lượng)
    const handoverAllowed = window.canHandover();
    const splitAllowed = window.canSplit();
    const canHandover = handoverAllowed && ((data.can_handover !== undefined)
      ? data.can_handover
      : (!isPending && isHolder && b.remaining_quantity > 0));
    const canSplit = splitAllowed && ((data.can_split !== undefined)
      ? data.can_split
      : (!isPending && isHolder && b.remaining_quantity > 0));

    const btnHandover = $("btn-detail-handover");
    if (btnHandover) {
      btnHandover.hidden = !handoverAllowed;
      btnHandover.disabled = !canHandover;
      btnHandover.onclick = () => {
        $("modal-batch-details").hidden = true;
        openHandoverModal(batchId);
      };
    }

    const btnSplit = $("btn-detail-split");
    if (btnSplit) {
      btnSplit.hidden = !splitAllowed;
      btnSplit.disabled = !canSplit;
      btnSplit.onclick = () => {
        $("modal-batch-details").hidden = true;
        openSplitModal(batchId);
      };
    }

    const canConsumeAction = (data.can_consume !== undefined)
      ? data.can_consume
      : (!isPending && isHolder && b.status !== "CONSUMED" && canConsume() && b.remaining_quantity > 0);

    const btnConsume = $("btn-detail-consume");
    if (btnConsume) {
      btnConsume.hidden = !canConsumeAction;
      btnConsume.onclick = () => {
        handleConsumeBatch(batchId, b.code);
      };
    }

    const meta = $("detail-overview-meta");
    if (meta) {
      meta.innerHTML = `
        <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px;">
          <div><strong>Sản phẩm:</strong> ${escapeHtml(b.product_name)}</div>
          <div><strong>Thửa đất xuất xứ:</strong> ${escapeHtml(b.plot_name || farmLabel(b.plot_id))}</div>
          <div><strong>Vùng trồng:</strong> ${escapeHtml(b.farm_name || "—")}</div>
          <div><strong>Ngày thu hoạch:</strong> ${escapeHtml(formatDate(b.harvest_date))}</div>
          <div><strong>Đơn vị nắm giữ:</strong> <span class="badge badge--org">🏢 ${escapeHtml(b.current_org_name || 'Tổ chức #' + b.current_org_id)}</span></div>
          <div><strong>Khối lượng ban đầu:</strong> ${formatNumber(b.initial_quantity)} ${escapeHtml(b.unit || "kg")}</div>
          <div><strong>Khối lượng còn lại:</strong> <strong style="color:var(--color-primary);">${formatNumber(b.remaining_quantity)} ${escapeHtml(b.unit || "kg")}</strong></div>
          <div><strong>Trạng thái:</strong> <span class="badge ${isPending ? 'badge--warning' : 'badge--ok'}">${escapeHtml(isPending ? 'Chờ duyệt bàn giao' : formatBatchStatus(b.status))}</span></div>
        </div>
      `;
    }

    // Cha trực tiếp
    const parentsList = $("detail-direct-parents-list");
    if (parentsList) {
      if (data.direct_parents && data.direct_parents.length > 0) {
        parentsList.innerHTML = data.direct_parents.map(p => `
          <div style="padding: 6px 0; border-bottom: 1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;">
            <span>Mã: <code style="font-weight:700;">${escapeHtml(p.code || (p.id != null ? "#" + p.id : "—"))}</code></span>
            <span><span class="lineage-badge-relation lineage-badge-relation--${p.relation_type.toLowerCase()}">${formatRelationType(p.relation_type)}</span> ${formatNumber(p.transferred_quantity)} ${escapeHtml(b.unit || "kg")}</span>
          </div>
        `).join("");
      } else {
        parentsList.innerHTML = `<em style="color:var(--color-text-muted);">Đây là lô thu hoạch gốc (Không có lô cha).</em>`;
      }
    }

    // Con trực tiếp
    const childrenList = $("detail-direct-children-list");
    if (childrenList) {
      if (data.direct_children && data.direct_children.length > 0) {
        childrenList.innerHTML = data.direct_children.map(c => `
          <div style="padding: 6px 0; border-bottom: 1px solid #e2e8f0; display:flex; justify-content:space-between; align-items:center;">
            <span>Mã: <code style="font-weight:700;">${escapeHtml(c.code || (c.id != null ? "#" + c.id : "—"))}</code></span>
            <span><span class="lineage-badge-relation lineage-badge-relation--${c.relation_type.toLowerCase()}">${formatRelationType(c.relation_type)}</span> ${formatNumber(c.transferred_quantity)} ${escapeHtml(b.unit || "kg")}</span>
          </div>
        `).join("");
      } else {
        childrenList.innerHTML = `<em style="color:var(--color-text-muted);">Chưa có lô con nào được phân tách/gộp từ lô này.</em>`;
      }
    }

    if (loading) loading.hidden = true;
    if (body) body.hidden = false;
  } catch (err) {
    if (loading) loading.textContent = `Lỗi tải thông tin chi tiết: ${err.message}`;
  }
}

/** Tab 2: Tải dòng thời gian Hash-Chain của lô */
async function loadDetailTimeline(batchId, prefix = "detail") {
  const container = $(`${prefix}-timeline-list`);
  if (!container) return;
  // Ủy quyền sự kiện cho nút "Sao chép" mã băm (nút sinh động theo từng sự kiện).
  container.onclick = (event) => {
    const copyBtn = event.target.closest(".hash-copy-btn");
    if (copyBtn) copyHashToClipboard(copyBtn);
  };
  container.innerHTML = `<div style="text-align:center; padding:16px;">Đang tải dòng thời gian...</div>`;
  setHidden(`${prefix}-timeline-alert-banner`, true);
  setHidden(`${prefix}-timeline-valid-banner`, true);

  const actor = session;
  try {
    const events = await apiRequest(`/batches/${batchId}/events`);
    if (actor !== session || !isSelectedScreenBatch(prefix, batchId)) return;
    if (!Array.isArray(events) || events.length === 0) {
      container.innerHTML = `<p class="empty">Chưa có sự kiện nào được ghi nhận cho lô hàng này.</p>`;
      return;
    }
    container.innerHTML = events.map(renderTimelineItemHtml).join("");
  } catch (err) {
    if (actor !== session || !isSelectedScreenBatch(prefix, batchId)) return;
    container.innerHTML = `<p class="empty empty--error">Không tải được dòng thời gian: ${escapeHtml(err.message)}</p>`;
  }
}

/** Xác thực toàn vẹn toán học chuỗi Hash-Chain trong màn hình chi tiết (T-48, T-59) */
async function verifyDetailChain(batchId, prefix = "detail") {
  const btn = $(`btn-${prefix}-verify-chain`);
  setButtonLoading(btn, true, "Đang kiểm tra…", "🛡️ Kiểm tra tính toàn vẹn");
  const actor = session;
  try {
    // Backend: GET /batches/{batch_id}/integrity — batch_id là SỐ NGUYÊN (không phải batch_code).
    // (Trước đây gọi sai `/events/integrity` nên luôn trả 404 Not Found.)
    const res = await apiRequest(`/batches/${batchId}/integrity`);
    if (actor !== session || !isSelectedScreenBatch(prefix, batchId)) return;
    const isValid = Boolean(res.valid ?? res.is_valid);
    if (isValid) {
      setHidden(`${prefix}-timeline-valid-banner`, false);
      setHidden(`${prefix}-timeline-alert-banner`, true);
      const text = $(`${prefix}-timeline-valid-text`);
      if (text) {
        const total = res.total_events != null ? ` Đã đối chiếu ${res.total_events} sự kiện.` : "";
        text.textContent = `✓ Dữ liệu toàn vẹn - Không phát hiện can thiệp trái phép.${total}`;
      }
      toast("Dữ liệu toàn vẹn - Không phát hiện can thiệp trái phép.", "success");
    } else {
      setHidden(`${prefix}-timeline-valid-banner`, true);
      setHidden(`${prefix}-timeline-alert-banner`, false);
      const text = $(`${prefix}-timeline-alert-text`);
      const tamperedId = res.tampered_event_id ?? res.event_id ?? "?";
      if (text) {
        text.textContent = `CẢNH BÁO: Phát hiện bất thường tại sự kiện #${tamperedId} `
          + `(${res.error_type || "HASH_MISMATCH"}). ${res.message || "Dữ liệu có thể đã bị can thiệp trái phép."}`;
      }
    }
  } catch (err) {
    if (actor !== session || !isSelectedScreenBatch(prefix, batchId)) return;
    toast(`Kiểm tra toàn vẹn thất bại: ${err.message}`, "error");
  } finally {
    setButtonLoading(btn, false, "Đang kiểm tra…", "🛡️ Xác thực toàn vẹn");
  }
}

/** Tab 3: Truy ngược cây phả hệ nguồn gốc BFS (T-49, T-50, T-59) */
async function loadDetailLineage(batchId, prefix = "detail") {
  const loading = $(`${prefix}-lineage-loading`);
  const body = $(`${prefix}-lineage-body`);
  if (loading) loading.hidden = false;
  if (loading) loading.textContent = "Đang tải thông tin nguồn gốc…";
  if (body) body.hidden = true;

  const actor = session;
  try {
    const data = await apiRequest(`/batches/${batchId}/trace-back`);
    if (actor !== session || !isSelectedScreenBatch(prefix, batchId)) return;

    // 1. Lô thu hoạch gốc (Root batches)
    const rootGrid = $(`${prefix}-root-batches-list`);
    if (rootGrid) {
      if (data.root_batches && data.root_batches.length > 0) {
        rootGrid.innerHTML = data.root_batches.map(r => {
          // Đọc linh hoạt tên thuộc tính (API trả `code`/`plot_name`/`owner`...).
          const code = r.batch_code || r.code || (r.batch_id != null ? `#${r.batch_id}` : "—");
          const plotName = r.plot_name || r.location || "Chưa xác định thửa đất";
          const farmName = r.farm_name || r.plot_name || r.location || "—";
          const owner = r.owner || r.farmer_name || "—";
          const area = Number(r.plot_area);
          const areaHtml = r.plot_area != null && Number.isFinite(area)
            ? ` <span style="color:#166534;">(${formatNumber(area)} ha)</span>`
            : "";
          return `
          <div class="root-batch-item">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
              <span class="lineage-node-code">${escapeHtml(code)}</span>
              <span class="badge badge--ok" style="font-size:0.75rem;">GỐC THU HOẠCH</span>
            </div>
            <div style="font-size:0.88rem; color:#334155; line-height:1.4;">
              <div><strong>Thửa đất:</strong> ${escapeHtml(plotName)}${areaHtml}</div>
              <div><strong>Vùng trồng:</strong> ${escapeHtml(farmName)}</div>
              <div><strong>Nông hộ:</strong> ${escapeHtml(owner)}</div>
              <div><strong>Sản phẩm:</strong> ${escapeHtml(r.product_name || "—")}</div>
              <div><strong>Thu hoạch:</strong> ${escapeHtml(formatDate(r.harvest_date))} · ${formatNumber(r.initial_quantity)} ${escapeHtml(r.unit || "kg")}</div>
            </div>
          </div>
        `;
        }).join("");
      } else {
        rootGrid.innerHTML = `<em style="color:var(--color-text-muted);">Không tìm thấy lô thu hoạch gốc.</em>`;
      }
    }

    // 2. Cây phả hệ tổ tiên theo tầng (Ancestors by level)
    const levelsContainer = $(`${prefix}-lineage-levels-container`);
    if (levelsContainer) {
      const levels = data.ancestors_by_level || {};
      const levelKeys = Object.keys(levels).map(Number).sort((a, b) => a - b);

      if (levelKeys.length === 0) {
        levelsContainer.innerHTML = `
          <div class="lineage-level-block" style="text-align:center; color:var(--color-text-muted);">
            Lô này là lô thu hoạch ban đầu trực tiếp từ thửa đất, không có tổ tiên phía trước.
          </div>
        `;
      } else {
        levelsContainer.innerHTML = levelKeys.map(lvl => {
          const nodes = levels[lvl] || [];
          const lvlLabel = lvl === 1 ? "Tầng 1 (Cha mẹ trực tiếp)"
            : lvl === 2 ? "Tầng 2 (Ông bà)"
            : lvl === 3 ? "Tầng 3 (Nguồn gốc / Cụ kỵ)"
            : `Tầng ${lvl}`;
          return `
            <div class="lineage-level-block">
              <div class="lineage-level-title">
                <span>📍</span>
                <span>${lvlLabel} — ${nodes.length} lô tổ tiên</span>
              </div>
              <div class="lineage-nodes-list">
                ${nodes.map(n => {
                  // Đọc linh hoạt tên thuộc tính (API trả `code`/`current_org_name`...).
                  const code = n.batch_code || n.code || (n.batch_id != null ? `#${n.batch_id}` : "—");
                  const relation = (n.relation_type || "split").toLowerCase();
                  const orgId = n.organization_id != null ? n.organization_id : n.current_org_id;
                  const orgName = n.organization_name || n.org_name || n.current_org_name
                    || (orgId != null ? `Tổ chức #${orgId}` : "Hợp tác xã");
                  return `
                  <div class="lineage-node-card lineage-node-card--${relation}">
                    <div class="lineage-node-header">
                      <span class="lineage-node-code">${escapeHtml(code)}</span>
                      <span class="lineage-badge-relation lineage-badge-relation--${relation}">${escapeHtml(formatRelationType(n.relation_type || 'GỐC'))}</span>
                    </div>
                    <div style="font-size:0.85rem; color:#475569; margin-top:4px;">
                      <div><strong>Sản phẩm:</strong> ${escapeHtml(n.product_name || "—")}</div>
                      <div><strong>Khối lượng chuyển:</strong> <strong>${formatNumber(n.transferred_quantity)} ${escapeHtml(n.unit || "kg")}</strong></div>
                      <div><strong>Đơn vị quản lý:</strong> ${escapeHtml(orgName)}</div>
                    </div>
                  </div>
                `;
                }).join("")}
              </div>
            </div>
          `;
        }).join("");
      }
    }

    if (loading) loading.hidden = true;
    if (body) body.hidden = false;
  } catch (err) {
    if (actor !== session || !isSelectedScreenBatch(prefix, batchId)) return;
    if (loading) loading.textContent = `Lỗi truy ngược nguồn gốc: ${err.message}`;
  }
}

let currentLineageMode = "backward";

/** Chuyển đổi giữa chế độ Truy ngược và Truy xuôi trong Tab 3 */
function setLineageMode(mode) {
  currentLineageMode = mode;
  const btnBack = $("btn-lineage-backward");
  const btnFwd = $("btn-lineage-forward");
  const lbl = $("lineage-mode-label");
  const backBody = $("detail-lineage-body");
  const fwdBody = $("detail-lineage-forward-body");

  if (mode === "backward") {
    if (btnBack) { btnBack.classList.add("btn--primary"); btnBack.classList.remove("btn--light"); }
    if (btnFwd) { btnFwd.classList.add("btn--light"); btnFwd.classList.remove("btn--primary"); }
    if (lbl) lbl.textContent = "Chế độ: Xem nguồn gốc từ nông trại";
    if (backBody) backBody.hidden = false;
    if (fwdBody) fwdBody.hidden = true;
    if (currentDetailBatchId) loadDetailLineage(currentDetailBatchId);
  } else {
    if (btnBack) { btnBack.classList.add("btn--light"); btnBack.classList.remove("btn--primary"); }
    if (btnFwd) { btnFwd.classList.add("btn--primary"); btnFwd.classList.remove("btn--light"); }
    if (lbl) lbl.textContent = "Chế độ: Xem các lô liên quan trong chuỗi phân phối";
    if (backBody) backBody.hidden = true;
    if (fwdBody) fwdBody.hidden = false;
    if (currentDetailBatchId) loadDetailLineageForward(currentDetailBatchId);
  }
}

/** Tab 3: Truy xuôi cây phả hệ hậu duệ BFS (S-26, S-27) */
async function loadDetailLineageForward(batchId) {
  const loading = $("detail-lineage-loading");
  const forwardBody = $("detail-lineage-forward-body");
  const backwardBody = $("detail-lineage-body");
  if (loading) {
    loading.textContent = "Đang tải thông tin các lô liên quan...";
    loading.hidden = false;
  }
  if (forwardBody) forwardBody.hidden = true;
  if (backwardBody) backwardBody.hidden = true;

  try {
    const data = await apiRequest(`/batches/${batchId}/trace-forward`);

    // 1. Điểm cuối chuỗi cung ứng & Đã tiêu thụ (Terminal batches)
    const termList = $("detail-terminal-batches-list");
    if (termList) {
      if (data.terminal_batches && data.terminal_batches.length > 0) {
        termList.innerHTML = data.terminal_batches.map(t => {
          const code = t.code || `#${t.batch_id}`;
          const isConsumed = Boolean(t.is_consumed || t.status === "CONSUMED");
          const orgName = t.current_org_name || (t.current_org_id ? `Tổ chức #${t.current_org_id}` : "—");
          const loc = t.location || "Chưa xác định";
          const remQty = isConsumed ? 0 : Number(t.remaining_quantity || 0);
          return `
            <div class="root-batch-item" style="border: 1px solid ${isConsumed ? '#cbd5e1' : '#f59e0b'}; background: ${isConsumed ? '#f8fafc' : '#fffbeb'};">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span class="lineage-node-code">${escapeHtml(code)}</span>
                ${isConsumed
                  ? '<span class="badge" style="background:#64748b; color:#fff; font-size:0.75rem;">🍽️ ĐÃ TIÊU THỤ</span>'
                  : '<span class="badge badge--warning" style="font-size:0.75rem;">🏁 ĐIỂM CUỐI</span>'
                }
              </div>
              <div style="font-size:0.88rem; color:#334155; line-height:1.4;">
                <div><strong>Đơn vị giữ:</strong> ${escapeHtml(orgName)}</div>
                <div><strong>Địa điểm:</strong> ${escapeHtml(loc)}</div>
                <div><strong>Sản phẩm:</strong> ${escapeHtml(t.product_name || "—")}</div>
                <div><strong>Khối lượng còn:</strong> <strong style="color:${isConsumed ? '#64748b' : '#d97706'};">${formatNumber(remQty)} ${escapeHtml(t.unit || "kg")}</strong></div>
              </div>
            </div>
          `;
        }).join("");
      } else {
        termList.innerHTML = `<em style="color:var(--color-text-muted);">Không có điểm cuối phả hệ.</em>`;
      }
    }

    // 2. Cây phả hệ phân tầng hậu duệ (Descendants by level)
    const forwardLevelsContainer = $("detail-forward-levels-container");
    if (forwardLevelsContainer) {
      const levels = data.descendants_by_level || {};
      const levelKeys = Object.keys(levels).map(Number).sort((a, b) => a - b);

      if (levelKeys.length === 0) {
        forwardLevelsContainer.innerHTML = `
          <div class="lineage-level-block" style="text-align:center; color:var(--color-text-muted); padding:20px;">
            Lô này chưa sinh ra bất kỳ lô con hoặc lô cháu nào (chưa từng tách hoặc gộp sang lô khác).
          </div>
        `;
      } else {
        forwardLevelsContainer.innerHTML = levelKeys.map(lvl => {
          const nodes = levels[lvl] || [];
          const lvlLabel = lvl === 1 ? "Thế hệ F1 (Lô con trực tiếp)"
            : lvl === 2 ? "Thế hệ F2 (Lô cháu)"
            : lvl === 3 ? "Thế hệ F3 (Lô chắt)"
            : `Thế hệ F${lvl}`;
          return `
            <div class="lineage-level-block">
              <div class="lineage-level-title" style="color:#0369a1;">
                <span>🌱</span>
                <span>${lvlLabel} — ${nodes.length} lô hậu duệ</span>
              </div>
              <div class="lineage-nodes-list">
                ${nodes.map(n => {
                  const code = n.code || `#${n.batch_id}`;
                  const relation = (n.relation_type || "split").toLowerCase();
                  const orgName = n.current_org_name || (n.current_org_id ? `Tổ chức #${n.current_org_id}` : "—");
                  const loc = n.location || "—";
                  const isConsumed = Boolean(n.is_consumed || n.status === "CONSUMED");
                  const remQty = isConsumed ? 0 : Number(n.remaining_quantity || 0);
                  const maskedTag = n.is_masked ? ` <span class="badge badge--muted" style="font-size:0.7rem;">Nội bộ bên ngoài</span>` : "";
                  return `
                    <div class="lineage-node-card lineage-node-card--${relation}" style="${isConsumed ? 'opacity:0.85; border-color:#94a3b8;' : ''}">
                      <div class="lineage-node-header">
                        <span class="lineage-node-code">${escapeHtml(code)}${maskedTag}</span>
                        <div style="display:flex; gap:4px; align-items:center;">
                          ${isConsumed ? '<span class="badge" style="background:#64748b; color:#fff; font-size:0.75rem;">🍽️ ĐÃ TIÊU THỤ</span>' : ''}
                          <span class="lineage-badge-relation lineage-badge-relation--${relation}">${escapeHtml(formatRelationType(n.relation_type || 'CON'))}</span>
                        </div>
                      </div>
                      <div style="font-size:0.85rem; color:#475569; margin-top:4px; line-height:1.4;">
                        <div><strong>Sản phẩm:</strong> ${escapeHtml(n.product_name || "—")}</div>
                        <div><strong>Lượng nhận từ cha:</strong> <strong>${formatNumber(n.transferred_quantity)} ${escapeHtml(n.unit || "kg")}</strong></div>
                        <div><strong>Khối lượng còn:</strong> <strong style="color:${isConsumed ? '#64748b' : 'var(--color-primary)'};">${formatNumber(remQty)} ${escapeHtml(n.unit || "kg")}</strong></div>
                        <div><strong>Đơn vị nắm giữ:</strong> ${escapeHtml(orgName)}</div>
                        <div><strong>Địa điểm:</strong> ${escapeHtml(loc)}</div>
                      </div>
                    </div>
                  `;
                }).join("")}
              </div>
            </div>
          `;
        }).join("");
      }
    }

    if (loading) loading.hidden = true;
    if (forwardBody) forwardBody.hidden = false;
  } catch (err) {
    if (loading) loading.textContent = `Lỗi truy xuôi nguồn gốc: ${err.message}`;
  }
}

/** Ghi nhận lô nông sản đã bán hết cho người tiêu dùng (CONSUMED - S-29) */
async function handleConsumeBatch(batchId, batchCode) {
  const codeStr = batchCode || `#${batchId}`;
  if (!window.confirm(`Xác nhận lô ${codeStr} đã bán hết cho người tiêu dùng?\n\n- Khối lượng còn lại sẽ chuyển về 0\n- Trạng thái chuyển sang ĐÃ TIÊU THỤ (CONSUMED)\n- Không thể hoàn tác hoặc tiếp tục bàn giao/tách/gộp.`)) {
    return;
  }
  const btn = $("btn-detail-consume");
  setButtonLoading(btn, true, "Đang xử lý…", "🍽️ Đã bán hết (CONSUMED)");
  try {
    const res = await apiRequest(`/batches/${batchId}/consume`, {
      method: "POST",
      body: { notes: "Đã bán hết cho người tiêu dùng tại cửa hàng/siêu thị" },
    });
    toast(res.message || `Đã ghi nhận lô ${codeStr} tiêu thụ thành công!`, "success");
    await loadDetailOverview(batchId);
    await loadBatches();
    await refreshAuditLogsIfAdmin();
  } catch (err) {
    toast(`Ghi nhận tiêu thụ thất bại: ${err.message}`, "error");
  } finally {
    setButtonLoading(btn, false, "Đang xử lý…", "🍽️ Đã bán hết (CONSUMED)");
  }
}

/** Cập nhật lại số thứ tự Lô con #1, #2, #3... liên tục cho danh sách dòng nhập */
function refreshSplitRowNumbers() {
  const container = $("split-items-container");
  if (!container) return;
  const rows = container.querySelectorAll(".dynamic-split-row");
  rows.forEach((row, idx) => {
    const badge = row.querySelector(".split-child-badge");
    if (badge) {
      badge.textContent = `Lô con #${idx + 1}`;
    }
  });
}

/** Mở modal Tách lô (S-17, S-18: T-40, T-41) */
function openSplitModal(batchIdOrCode) {
  if (!canSplit()) { toast("Vai trò của bạn không có quyền tách lô.", "error"); return; }
  let batch = null;
  if (typeof batchIdOrCode === "number" || (!isNaN(Number(batchIdOrCode)) && String(batchIdOrCode).trim() !== "")) {
    const numId = Number(batchIdOrCode);
    batch = batches.find((b) => b.id === numId);
  }
  if (!batch) {
    batch = batches.find((b) => b.code === batchIdOrCode || String(b.id) === String(batchIdOrCode));
  }

  if (!batch) {
    toast(`Không tìm thấy lô nông sản #${batchIdOrCode}`, "error");
    return;
  }

  currentSplitBatch = batch;
  $("split-parent-id").value = String(batch.id);

  const remaining = batch.remaining_quantity != null ? Number(batch.remaining_quantity) : Number(batch.initial_quantity || batch.quantity || 0);
  const unit = batch.unit || "kg";

  // Cập nhật đơn vị tĩnh cho thanh tính toán
  const unitEls = $("split-calc-box") ? $("split-calc-box").querySelectorAll(".split-calc-unit") : [];
  unitEls.forEach((el) => {
    el.textContent = unit;
  });

  $("split-parent-remaining-val").textContent = formatNumber(remaining);
  $("split-parent-meta").innerHTML = `
    <div style="display: flex; flex-direction: column; gap: 4px;">
      <div><strong>Lô mẹ:</strong> <code style="font-weight:700; font-size:1.05rem; color:#1e293b;">${escapeHtml(batch.code || '#' + batch.id)}</code> — <strong>${escapeHtml(batch.product_name)}</strong></div>
      <div style="font-size:0.9rem; color:#475569;"><strong>Khối lượng còn lại:</strong> <strong style="color:var(--color-primary); font-size:1rem;">${formatNumber(remaining)} ${escapeHtml(unit)}</strong> · <strong>Thửa đất:</strong> ${escapeHtml(farmLabel(batch.plot_id || batch.farm_id))}</div>
    </div>
  `;

  // Khởi tạo danh sách lô con (mặc định chia đôi 2 dòng gợi ý)
  const container = $("split-items-container");
  container.innerHTML = "";
  const half = Math.round((remaining / 2) * 100) / 100;
  const remHalf = Math.round((remaining - half) * 100) / 100;
  addSplitItemRow(half > 0 ? half : "");
  addSplitItemRow(remHalf > 0 ? remHalf : "");

  refreshSplitRowNumbers();
  updateSplitCalculation();
  $("modal-split-batch").hidden = false;
}

/** Thêm 1 dòng nhập khối lượng lô con */
function addSplitItemRow(defaultVal = "") {
  const container = $("split-items-container");
  if (!container) return;

  const row = document.createElement("div");
  row.className = "dynamic-split-row";
  const unit = (currentSplitBatch && currentSplitBatch.unit) ? currentSplitBatch.unit : "kg";

  row.innerHTML = `
    <div class="split-row-label">
      <span class="split-child-badge">Lô con</span>
    </div>
    <div class="split-input-wrapper">
      <input type="number" step="any" min="0.01" class="split-child-qty" placeholder="Nhập khối lượng..." value="${defaultVal !== "" ? defaultVal : ""}" required />
      <span class="split-input-unit">${escapeHtml(unit)}</span>
    </div>
    <button type="button" class="btn-remove-split-row" title="Xóa dòng này" aria-label="Xóa dòng">✕</button>
  `;

  const removeBtn = row.querySelector(".btn-remove-split-row");
  removeBtn.addEventListener("click", () => {
    const currentRows = container.querySelectorAll(".dynamic-split-row");
    if (currentRows.length <= 1) {
      toast("Phải có ít nhất 1 dòng khối lượng lô con!", "error");
      return;
    }
    row.remove();
    refreshSplitRowNumbers();
    updateSplitCalculation();
  });

  const input = row.querySelector(".split-child-qty");
  input.addEventListener("input", updateSplitCalculation);

  container.appendChild(row);
  refreshSplitRowNumbers();
  updateSplitCalculation();
}

/** Tính tổng khối lượng các lô con và kiểm tra vượt quá lô mẹ theo thời gian thực (T-41) */
function updateSplitCalculation() {
  const parentId = $("split-parent-id") ? Number($("split-parent-id").value) : 0;
  const parent = currentSplitBatch || batches.find((b) => b.id === parentId);
  const maxRemaining = parent ? Number(parent.remaining_quantity != null ? parent.remaining_quantity : (parent.initial_quantity || parent.quantity || 0)) : 0;
  const unit = (parent && parent.unit) ? parent.unit : "kg";

  const inputs = document.querySelectorAll(".split-child-qty");
  let total = 0;
  let hasEmptyOrInvalid = false;
  let count = 0;

  inputs.forEach((input) => {
    count++;
    const rawVal = input.value.trim();
    const val = parseFloat(rawVal);
    if (rawVal === "" || isNaN(val) || val <= 0) {
      hasEmptyOrInvalid = true;
    } else {
      total += val;
    }
  });

  total = Math.round(total * 100) / 100;
  const diff = Math.round((maxRemaining - total) * 100) / 100;

  const totalEl = $("split-total-calc");
  if (totalEl) totalEl.textContent = formatNumber(total);

  const calcBox = $("split-calc-box");
  const matchBadge = $("split-match-badge");
  const remainingSubtext = $("split-remaining-subtext");
  const errorMsg = $("split-error-msg");
  const submitBtn = $("btn-submit-split");

  // Reset visual states
  if (totalEl) {
    totalEl.classList.remove("is-matched", "is-over");
  }
  if (calcBox) {
    calcBox.classList.remove("has-matched", "has-error", "is-invalid");
  }
  if (matchBadge) matchBadge.hidden = true;
  if (remainingSubtext) remainingSubtext.textContent = "";
  if (errorMsg) {
    errorMsg.hidden = true;
    errorMsg.textContent = "";
  }

  if (count === 0) {
    if (submitBtn) submitBtn.disabled = true;
    return;
  }

  // 1. Kiểm tra ô trống hoặc <= 0
  if (hasEmptyOrInvalid) {
    if (calcBox) calcBox.classList.add("has-error", "is-invalid");
    if (errorMsg) {
      errorMsg.textContent = "⚠️ Vui lòng nhập khối lượng lớn hơn 0 cho tất cả các lô con!";
      errorMsg.hidden = false;
    }
    if (submitBtn) submitBtn.disabled = true;
    return;
  }

  // 2. Kiểm tra vượt quá khối lượng lô mẹ
  if (total > maxRemaining) {
    if (calcBox) calcBox.classList.add("has-error", "is-invalid");
    if (totalEl) totalEl.classList.add("is-over");
    if (errorMsg) {
      errorMsg.textContent = `❌ Vượt quá khối lượng còn lại của lô mẹ! (Tổng con: ${formatNumber(total)} ${unit} > Lô mẹ: ${formatNumber(maxRemaining)} ${unit})`;
      errorMsg.hidden = false;
    }
    if (submitBtn) submitBtn.disabled = true;
    return;
  }

  // 3. Khớp 100%
  if (Math.abs(total - maxRemaining) < 0.001) {
    if (calcBox) calcBox.classList.add("has-matched");
    if (totalEl) totalEl.classList.add("is-matched");
    if (matchBadge) matchBadge.hidden = false;
    if (remainingSubtext) remainingSubtext.textContent = "(Đã khớp 100% lô mẹ)";
    if (submitBtn) submitBtn.disabled = false;
    return;
  }

  // 4. Hợp lệ và còn dư lô mẹ
  if (remainingSubtext) {
    remainingSubtext.textContent = `(Lô mẹ còn lại: ${formatNumber(diff)} ${unit})`;
  }
  if (submitBtn) submitBtn.disabled = false;
}

/** Gửi request tách lô POST /batches/{id}/split (T-40, T-41) */
async function handleSplitSubmit(event) {
  event.preventDefault();
  const rawIdVal = $("split-parent-id") ? $("split-parent-id").value.trim() : "";
  let parentIdentifier = rawIdVal;
  if (!parentIdentifier && currentSplitBatch) {
    parentIdentifier = String(currentSplitBatch.id || currentSplitBatch.code || "");
  }

  if (!parentIdentifier) {
    toast("Không tìm thấy thông tin lô mẹ để thực hiện tách!", "error");
    return;
  }

  const inputs = document.querySelectorAll(".split-child-qty");
  const items = [];
  const child_quantities = [];

  for (const input of inputs) {
    const val = parseFloat(input.value.trim());
    if (isNaN(val) || val <= 0) {
      toast("Vui lòng nhập khối lượng lớn hơn 0 cho tất cả các lô con!", "error");
      input.focus();
      return;
    }
    items.push({ quantity: val });
    child_quantities.push(val);
  }

  if (items.length === 0) {
    toast("Vui lòng nhập ít nhất một lô con hợp lệ!", "error");
    return;
  }

  const btn = $("btn-submit-split");
  setButtonLoading(btn, true, "Đang tách…", "Xác nhận tách lô");

  try {
    let res = null;
    let lastError = null;

    // Danh sách các URL thử gọi để đảm bảo tương thích 100% với router backend
    const endpointsToTry = [
      `/batches/${encodeURIComponent(parentIdentifier)}/split`,
      `/api/v1/batches/${encodeURIComponent(parentIdentifier)}/split`,
    ];

    if (currentSplitBatch && currentSplitBatch.code && currentSplitBatch.code !== parentIdentifier) {
      endpointsToTry.push(`/batches/${encodeURIComponent(currentSplitBatch.code)}/split`);
    }

    for (const url of endpointsToTry) {
      try {
        res = await apiRequest(url, {
          method: "POST",
          body: {
            items: items,
            child_quantities: child_quantities,
          },
        });
        if (res) break;
      } catch (err) {
        lastError = err;
        if (err.status !== 404) {
          // Nếu không phải lỗi 404 (ví dụ lỗi nghiệp vụ 400, 403, 500) thì không thử tiếp
          throw err;
        }
      }
    }

    if (!res) {
      throw lastError || new Error("Không thể kết nối đến máy chủ.");
    }

    $("modal-split-batch").hidden = true;
    toast(res.message || "Tách lô nông sản thành công!", "success");
    openSplitSuccessModal(res);
    await loadBatches();
  } catch (err) {
    toast(`Tách lô thất bại: ${err.message}`, "error");
  } finally {
    setButtonLoading(btn, false, "Đang tách…", "Xác nhận tách lô");
  }
}

/** Hiển thị danh sách mã lô con vừa tạo với cỡ chữ lớn 24px+ kèm nút sao chép (T-41) */
function openSplitSuccessModal(resultData) {
  const modal = $("modal-split-success");
  const list = $("split-success-codes-list");
  if (!modal || !list) return;

  const children = resultData.child_batches || [];
  if (children.length === 0) {
    list.innerHTML = `<p style="color:var(--color-text-muted);">Không có thông tin lô con.</p>`;
  } else {
    list.innerHTML = children.map((c, index) => {
      const code = c.code || (`#${c.id}`);
      const qty = c.initial_quantity != null ? c.initial_quantity : (c.quantity || 0);
      const unit = c.unit || "kg";
      return `
        <div class="split-child-card" style="display:flex; align-items:center; justify-content:space-between; padding:16px 20px; background:#f8fafc; border:1.5px solid #cbd5e1; border-radius:10px; margin-bottom:12px; gap:16px;">
          <div style="text-align:left; flex:1;">
            <div style="font-size:0.85rem; font-weight:700; color:#166534; text-transform:uppercase; margin-bottom:4px;">
              🌱 Lô con #${index + 1} (${escapeHtml(c.product_name || "Nông sản")})
            </div>
            <div class="code-display-huge" style="font-size:1.65rem; font-family:'Cascadia Mono', Consolas, monospace; font-weight:800; padding:10px 18px; margin:4px 0 8px 0; display:inline-block; letter-spacing:2px; background:#0f172a; color:#facc15; border-radius:8px;">
              ${escapeHtml(code)}
            </div>
            <div style="font-size:0.95rem; color:#475569;">
              Khối lượng ban đầu: <strong style="color:#0f172a; font-weight:700;">${formatNumber(qty)} ${escapeHtml(unit)}</strong>
            </div>
          </div>
          <button class="btn btn--sm btn--primary" type="button" style="white-space:nowrap; padding:10px 16px; font-weight:600; display:inline-flex; align-items:center; gap:6px;" onclick="copyText('${escapeHtml(code)}')">
            📋 Sao chép mã
          </button>
        </div>
      `;
    }).join("");
  }

  const copyAllBtn = $("btn-copy-all-split-codes");
  if (copyAllBtn) {
    copyAllBtn.onclick = () => {
      const allCodes = children.map((c) => c.code || `#${c.id}`).join(", ");
      if (allCodes) {
        copyText(allCodes);
      }
    };
  }

  modal.hidden = false;
}

/** Mở modal Gộp lô (S-19, S-20: T-44, T-45, T-46) */
function openMergeModal() {
  if (!canMerge()) {
    toast("Vai trò của bạn không có quyền gộp lô.", "error");
    return;
  }
  const selectedBatches = batches.filter((b) => selectedBatchIds.has(b.id));
  if (selectedBatches.length < 2) {
    toast("Cần chọn ít nhất 2 lô để gộp!", "error");
    return;
  }

  const firstProdId = selectedBatches[0].product_id;
  const sameProd = selectedBatches.every((b) => b.product_id === firstProdId);
  if (!sameProd) {
    toast("Các lô chọn để gộp phải cùng một loại sản phẩm!", "error");
    return;
  }

  $("merge-product-id").value = String(firstProdId);
  $("merge-product-summary").innerHTML = `
    <div><strong>Sản phẩm gộp:</strong> ${escapeHtml(selectedBatches[0].product_name)}</div>
    <div><strong>Số lượng lô mẹ chọn gộp:</strong> ${selectedBatches.length} lô</div>
  `;

  const tbody = $("merge-parents-table-body");
  tbody.innerHTML = selectedBatches.map(b => {
    const rem = b.remaining_quantity != null ? b.remaining_quantity : (b.initial_quantity || b.quantity);
    return `
      <tr>
        <td><strong style="font-family:monospace; background:#0f172a; color:#facc15; padding:2px 6px; border-radius:4px;">${escapeHtml(b.code || '#' + b.id)}</strong></td>
        <td>${escapeHtml(farmLabel(b.plot_id || b.farm_id))}</td>
        <td class="is-right">${formatNumber(rem)}</td>
        <td class="is-right">
          <input type="number" step="any" min="0.01" max="${rem}" value="${rem}" class="merge-parent-qty" data-id="${b.id}" data-max="${rem}" style="width:120px; text-align:right;" required />
        </td>
      </tr>
    `;
  }).join("");

  tbody.querySelectorAll(".merge-parent-qty").forEach(inp => {
    inp.addEventListener("input", updateMergeCalculation);
  });

  updateMergeCalculation();
  $("modal-merge-batch").hidden = false;
}

/** Tính tổng khối lượng gộp và kiểm tra hợp lệ */
function updateMergeCalculation() {
  const inputs = document.querySelectorAll(".merge-parent-qty");
  let total = 0;
  let hasError = false;
  let errMsg = "";
  const unit = batches.find(b => selectedBatchIds.has(b.id))?.unit || "kg";

  inputs.forEach(inp => {
    const val = parseFloat(inp.value);
    const maxVal = parseFloat(inp.dataset.max);
    if (isNaN(val) || val <= 0) {
      hasError = true;
      errMsg = `Khối lượng lấy từ mỗi lô mẹ phải lớn hơn 0 ${unit}!`;
    } else if (val > maxVal) {
      hasError = true;
      errMsg = `Khối lượng lấy (${val} ${unit}) vượt quá số lượng còn lại (${maxVal} ${unit})!`;
    } else {
      total += val;
    }
  });

  total = Math.round(total * 100) / 100;
  $("merge-total-calc").textContent = `${formatNumber(total)} ${unit}`;

  const errorEl = $("merge-error-msg");
  const calcBox = $("merge-calc-box");
  const submitBtn = $("btn-submit-merge");

  if (hasError || total <= 0) {
    calcBox.classList.add("is-invalid");
    errorEl.textContent = `❌ ${errMsg || 'Vui lòng kiểm tra lại khối lượng'}`;
    errorEl.hidden = false;
    submitBtn.disabled = true;
  } else {
    calcBox.classList.remove("is-invalid");
    errorEl.hidden = true;
    submitBtn.disabled = false;
  }
}

/** Gửi request gộp lô POST /batches/merge (T-44, T-45, T-46) */
async function handleMergeSubmit(event) {
  event.preventDefault();
  const productId = Number($("merge-product-id").value);
  const inputs = document.querySelectorAll(".merge-parent-qty");
  const items = [];
  inputs.forEach(inp => {
    const pId = Number(inp.dataset.id);
    const val = parseFloat(inp.value);
    if (!isNaN(val) && val > 0) {
      items.push({ parent_batch_id: pId, quantity: val });
    }
  });

  if (items.length < 2) {
    toast("Cần gộp từ ít nhất 2 lô mẹ!", "error");
    return;
  }

  const btn = $("btn-submit-merge");
  setButtonLoading(btn, true, "Đang gộp…", "Xác nhận gộp lô");

  try {
    const res = await apiRequest("/batches/merge", {
      method: "POST",
      body: { product_id: productId, items },
    });
    $("modal-merge-batch").hidden = true;
    selectedBatchIds.clear();
    openMergeSuccessModal(res);
    await loadBatches();
  } catch (err) {
    toast(`Gộp lô thất bại: ${err.message}`, "error");
  } finally {
    setButtonLoading(btn, false, "Đang gộp…", "Xác nhận gộp lô");
  }
}

/** Hiển thị popup thành công gộp lô với cỡ chữ lớn 24px+ (T-46) */
function openMergeSuccessModal(resultData) {
  const modal = $("modal-merge-success");
  if (!modal) return;
  const b = resultData.merged_batch;
  $("merge-success-code-display").textContent = b.code || `#${b.id}`;
  $("merge-success-meta").innerHTML = `
    <div>Sản phẩm: <strong>${escapeHtml(b.product_name)}</strong></div>
    <div>Tổng khối lượng gộp: <strong>${formatNumber(b.initial_quantity)} ${escapeHtml(b.unit || "kg")}</strong></div>
  `;
  const copyBtn = $("btn-copy-merge-code");
  if (copyBtn) {
    copyBtn.onclick = () => copyText(b.code || String(b.id));
  }
  modal.hidden = false;
}


/* ------------------------------------------- 11. Bàn giao lô hàng (SCRUM-27/28) --- */
/** GET /organizations -> danh sách tổ chức để chọn bên nhận */
async function loadOrganizations() {
  if (session === null) return;
  try {
    const data = await apiRequest("/organizations");
    organizations = Array.isArray(data) ? data : [];
  } catch (error) {
    console.warn("Không tải được danh sách tổ chức:", error.message);
  }
}

/** GET /handovers/pending -> danh sách bàn giao gửi đến tổ chức của user */
async function loadPendingHandovers() {
  const actor = session;
  dataLoadState.pending = "loading"; renderStats();
  if (session === null) {
    pendingHandovers = [];
    renderPendingHandovers();
    return;
  }
  try {
    const data = await apiRequest("/handovers/pending");
    if (actor !== session) return;
    dataLoadState.pending = "ready";
    pendingHandovers = Array.isArray(data) ? data : [];
    renderPendingHandovers();
  } catch (error) {
    if (actor !== session) return;
    dataLoadState.pending = dataErrorState(error);
    console.warn("Không tải được danh sách lô chờ xác nhận:", error.message);
    pendingHandovers = [];
    renderPendingHandovers();
  }
}

/** Vẽ danh sách các lô hàng đang chờ xác nhận bàn giao */
/** Vẽ danh sách các lô hàng đang chờ xác nhận bàn giao (kèm cảnh báo quá hạn 48h - T-56, T-57) */
function renderPendingHandovers() {
  const tbody = $("pending-handovers-table-body");
  if (!tbody) return;

  tbody.innerHTML = pendingHandovers
    .map((h) => {
      const productName = h.batch_product_name || `Lô #${h.batch_id}`;
      const fromOrg = h.from_org_name || `Tổ chức #${h.from_org_id}`;
      const note = h.notes || h.note || "—";
      const isOverdue = h.is_overdue || checkIsOverdue(h.created_at);
      const overdueBadge = isOverdue
        ? '<span class="badge badge--overdue" title="Đã quá hạn xác nhận 48 giờ">⚠️ Quá hạn 48h</span>'
        : '<span class="badge badge--ok" style="font-size:0.8rem;">Trong hạn</span>';

      return `
      <tr class="${isOverdue ? 'is-overdue-row' : ''}">
        <td class="id-cell">${escapeHtml(h.batch_code || `#${h.batch_id}`)}</td>
        <td><strong>${escapeHtml(productName)}</strong></td>
        <td class="is-right">${formatNumber(h.batch_quantity)} ${escapeHtml(h.batch_unit || "kg")}</td>
        <td><span class="badge badge--org">🏢 ${escapeHtml(fromOrg)}</span></td>
        <td>${escapeHtml(formatDateTime(h.created_at))}</td>
        <td>${overdueBadge}</td>
        <td>${escapeHtml(note)}</td>
        <td class="is-center">
          <div class="table__actions" style="justify-content: center;">
            ${canHandover() ? `
              <button class="btn btn--success btn--sm" type="button"
                      data-action="accept-handover" data-id="${escapeHtml(h.id)}">
                ✓ Xác nhận nhận lô
              </button>
              <button class="btn btn--danger btn--sm" type="button"
                      data-action="reject-handover" data-id="${escapeHtml(h.id)}">
                ✕ Từ chối
              </button>
            ` : '—'}
          </div>
        </td>
      </tr>`;
    })
    .join("");

  const countBadge = $("badge-pending-count");
  if (countBadge) {
    countBadge.textContent = `${pendingHandovers.length} lô`;
    countBadge.className = pendingHandovers.length > 0 ? "badge badge--warning" : "badge badge--muted";
  }
  const navPending = $("nav-pending");
  if (navPending && canHandover()) {
    const countBadge = pendingHandovers.length > 0 ? `<span class="sidebar-count-badge">${pendingHandovers.length}</span>` : "";
    updateSidebarNavItem(navPending, "pending", "Tiếp nhận bàn giao", countBadge);
  }
  const statPending = $("stat-pending-handovers");
  if (statPending) {
    statPending.textContent = formatNumber(pendingHandovers.length);
  }
  const emptyEl = $("pending-handovers-empty");
  if (emptyEl) {
    emptyEl.hidden = pendingHandovers.length > 0;
    emptyEl.textContent = dataLoadState.pending === "ready" ? "Không có lô chờ tiếp nhận." : dataStateText(dataLoadState.pending);
  }
  renderStats();
}

/** Mở modal bàn giao lô hàng */
function openHandoverModal(batchId) {
  if (!canHandover()) { toast("Vai trò của bạn không có quyền bàn giao lô.", "error"); return; }
  const batch = batches.find((item) => item.id === batchId);
  if (!batch) {
    toast(`Không tìm thấy lô nông sản #${batchId}.`, "error");
    return;
  }

  $("handover-batch-id").value = String(batch.id);
  $("handover-note").value = "";

  const summary = $("modal-handover-summary");
  if (summary) {
    summary.innerHTML = `
      <div><strong>Lô hàng:</strong> #${escapeHtml(batch.id)} — <strong>${escapeHtml(batch.product_name)}</strong></div>
      <div><strong>Khối lượng:</strong> ${formatNumber(batch.remaining_quantity ?? batch.quantity)} ${escapeHtml(batch.unit || "kg")} · <strong>Vùng xuất xứ:</strong> ${escapeHtml(farmLabel(batch.farm_id))}</div>
      <div><strong>Tổ chức bàn giao:</strong> ${escapeHtml(session?.organization_name || "Tổ chức của bạn")}</div>
    `;
  }

  // Đổ danh sách tổ chức khác vào select
  const select = $("handover-to-org");
  if (select) {
    const targetOrgs = organizations.filter((org) => org.id !== session?.organization_id);
    if (targetOrgs.length === 0) {
      select.innerHTML = '<option value="">— Chưa có tổ chức đối tác khác nào trong hệ thống —</option>';
      select.disabled = true;
    } else {
      select.disabled = false;
      select.innerHTML =
        '<option value="">— Chọn tổ chức tiếp nhận —</option>' +
        targetOrgs
          .map((org) => `<option value="${escapeHtml(org.id)}">${escapeHtml(org.name)} (${escapeHtml(org.code)})</option>`)
          .join("");
    }
  }

  $("modal-handover").hidden = false;
}

/** Đóng modal bàn giao */
function closeHandoverModal() {
  $("modal-handover").hidden = true;
  $("handover-form").reset();
}

/** Xử lý gửi form bàn giao */
async function handleHandoverSubmit(event) {
  event.preventDefault();
  const batchId = Number($("handover-batch-id").value);
  const toOrgId = Number($("handover-to-org").value);
  const note = $("handover-note").value.trim() || null;

  if (!toOrgId) {
    toast("Vui lòng chọn tổ chức tiếp nhận lô hàng!", "error");
    return;
  }

  const button = $("btn-submit-handover");
  setButtonLoading(button, true, "Đang gửi…", "Xác nhận gửi bàn giao");

  try {
    await apiRequest(`/batches/${batchId}/handover`, {
      method: "POST",
      body: { to_org_id: toOrgId, note: note },
    });
    toast(`Đã gửi yêu cầu bàn giao lô nông sản #${batchId} thành công!`, "success");
    closeHandoverModal();
    await loadBatches();
    await loadPendingHandovers();
  } catch (error) {
    toast(`Bàn giao thất bại: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Đang gửi…", "Xác nhận gửi bàn giao");
  }
}

/** Mở modal từ chối tiếp nhận */
function openRejectModal(handoverId) {
  $("reject-handover-id").value = String(handoverId);
  $("reject-reason").value = "";
  updateRejectCounter();
  $("modal-reject").hidden = false;
  $("reject-reason").focus();
}

/** Đóng modal từ chối tiếp nhận */
function closeRejectModal() {
  $("modal-reject").hidden = true;
  $("reject-form").reset();
}

/** Cập nhật bộ đếm ký tự lý do từ chối */
function updateRejectCounter() {
  const reason = $("reject-reason").value.trim();
  const counter = $("reject-reason-counter");
  if (counter) {
    counter.textContent = `Đã nhập: ${reason.length} / tối thiểu 10 ký tự`;
    counter.style.color = reason.length >= 10 ? "var(--color-primary)" : "var(--color-danger)";
  }
}

/** Xử lý gửi form từ chối tiếp nhận */
async function handleRejectSubmit(event) {
  event.preventDefault();
  const handoverId = Number($("reject-handover-id").value);
  const reason = $("reject-reason").value.trim();

  if (reason.length < 10) {
    toast("Lý do từ chối bắt buộc phải có tối thiểu 10 ký tự!", "error");
    $("reject-reason").focus();
    return;
  }

  const button = $("btn-submit-reject");
  setButtonLoading(button, true, "Đang xử lý…", "Xác nhận từ chối");

  try {
    await apiRequest(`/handovers/${handoverId}/reject`, {
      method: "POST",
      body: { reject_reason: reason },
    });
    toast("Đã từ chối tiếp nhận lô hàng.", "info");
    closeRejectModal();
    await loadPendingHandovers();
    await loadBatches();
  } catch (error) {
    toast(`Từ chối thất bại: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Đang xử lý…", "Xác nhận từ chối");
  }
}

/** Tiếp nhận lô hàng (ACCEPT - T-37, T-57) */
async function handleAcceptHandover(handoverId) {
  const h = pendingHandovers.find((item) => item.id === handoverId);
  const batchName = h ? (h.batch_product_name || `lô #${h.batch_id}`) : `lô hàng #${handoverId}`;
  const isOverdue = h && (h.is_overdue || checkIsOverdue(h.created_at));

  let confirmMsg = `Bạn có chắc chắn muốn xác nhận tiếp nhận ${batchName} về tổ chức của mình?`;
  if (isOverdue) {
    confirmMsg += `\n\n⚠️ CẢNH BÁO: Lô hàng này ĐÃ QUÁ HẠN 48 GIỜ. Hệ thống vẫn cho phép xác nhận nhưng sự kiện tiếp nhận sẽ được ghi chú quá hạn để lưu vết minh bạch.`;
  }

  if (!window.confirm(confirmMsg)) {
    return;
  }

  try {
    await apiRequest(`/handovers/${handoverId}/accept`, {
      method: "POST",
    });
    toast(`Đã tiếp nhận ${batchName} thành công!`, "success");
    await loadPendingHandovers();
    await loadBatches();
  } catch (error) {
    toast(`Tiếp nhận lô hàng thất bại: ${error.message}`, "error");
  }
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
 * Xử lý click ở cột "Thao tác" (Chi tiết, Tách, Sửa, Xoá, Bàn giao, Tiếp nhận, Từ chối, Xem timeline).
 */
function handleTableAction(event) {
  const button = event.target.closest("button[data-action]");
  if (button === null) {
    return;
  }

  const id = Number(button.dataset.id);
  const entity = button.dataset.entity;
  const action = button.dataset.action;

  if (action === "view-details") {
    openBatchDetailsModal(id);
    return;
  }

  if (action === "create-recall") {
    const code = button.dataset.code;
    if (window.recallUi?.openCreate) {
      window.recallUi.openCreate(code || id);
    } else {
      toast("Chức năng thu hồi đang khởi tạo...", "info");
    }
    return;
  }

  if (action === "open-recall-section") {
    window.location.hash = "#recall-card";
    const recallCard = $("recall-card");
    if (recallCard) {
      recallCard.scrollIntoView({ behavior: "smooth" });
    }
    return;
  }

  if (action === "split-batch") {
    openSplitModal(id);
    return;
  }

  if (action === "view-timeline") {
    openTimelineModal(id);
    return;
  }

  if (action === "open-handover") {
    if (!canHandover()) {
      toast("Vai trò của bạn không có quyền bàn giao lô.", "error");
      return;
    }
    openHandoverModal(id);
    return;
  }

  if (action === "accept-handover") {
    if (!canHandover()) {
      toast("Vai trò của bạn không có quyền tiếp nhận bàn giao.", "error");
      return;
    }
    handleAcceptHandover(id);
    return;
  }

  if (action === "reject-handover") {
    if (!canHandover()) {
      toast("Vai trò của bạn không có quyền từ chối bàn giao.", "error");
      return;
    }
    openRejectModal(id);
    return;
  }

  if (action === "consume-batch") {
    if (!canConsume()) {
      toast("Vai trò của bạn không có quyền ghi nhận tiêu thụ.", "error");
      return;
    }
    const batch = batches.find((b) => b.id === id);
    handleConsumeBatch(id, batch ? batch.code : null);
    return;
  }

  if (action === "edit") {
    if (entity === "farm") {
      if (!canManageFarms()) {
        toast("Vai trò của bạn không có quyền sửa vùng trồng.", "error");
        return;
      }
      startEditFarm(id);
    } else {
      if (!canHarvest()) {
        toast("Vai trò của bạn không có quyền sửa lô nông sản.", "error");
        return;
      }
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
  await loadOrganizations();
  await loadProducts();
  await loadFarms();
  await loadBatches();
  await loadPendingHandovers();
  if (window.AGRITRACE_CONFIG?.maxSprint !== 3) await window.recallUi?.load();
  if (isAdmin()) {
    $("user-org-filter").innerHTML = '<option value="">Tất cả tổ chức</option>' + accountOrgOptions();
    await loadUsers();
  }
  if (canViewAuditLogs()) await loadAuditLogs({ silent: true });
}

/** Tải lại toàn bộ dữ liệu; `silent = true` để bỏ toast tổng kết. */
async function reloadAll({ silent = false } = {}) {
  const button = $("btn-reload");
  setButtonLoading(button, true, "Đang tải…", "Tải lại dữ liệu");

  await loadAllData();

  setButtonLoading(button, false, "Đang tải…", "Tải lại dữ liệu");
  if (!silent) {
    const parts = [`${farms.length} vùng trồng`, `${batches.length} lô nông sản`];
    if (pendingHandovers.length > 0) {
      parts.push(`${pendingHandovers.length} lô chờ nhận`);
    }
    if (isAdmin()) {
      parts.push(`${auditLogs.length} nhật ký hoạt động`);
    }
    toast(`Đã cập nhật dữ liệu: ${parts.join(", ")}.`, "info");
  }
}

/* Sidebar screens reuse the existing cards, forms and modal handlers. */
const appScreens = {
  overview: ["Tổng quan", "Số liệu và hoạt động trong phạm vi tài khoản của bạn.", ["overview", "recent-activity"]],
  "farm-card": ["Vùng trồng", "Quản lý danh sách, khai báo và chỉnh sửa vùng trồng.", ["farm-card"]],
  "batch-card": ["Lô nông sản", "Thu hoạch, quản lý lô và thực hiện tách/gộp, bàn giao.", ["batch-card", "products-card"]],
  "pending-handovers-card": ["Tiếp nhận bàn giao", "Xác nhận hoặc từ chối các yêu cầu gửi đến tổ chức của bạn.", ["pending-handovers-card"]],
  traceability: ["Truy xuất nguồn gốc", "Xem nguồn gốc và phả hệ của lô nông sản theo quyền truy cập.", ["traceability-card"]],
  events: ["Nhật ký sự kiện", "Dòng thời gian và kiểm tra tính toàn vẹn của lô hàng.", ["events-card", "inspector-card"]],
  "users-card": ["Tài khoản", "Quản lý người dùng theo phạm vi quản trị.", ["users-card"]],
  "audit-card": ["Nhật ký quản trị", "Theo dõi các thao tác quản trị được cấp quyền.", ["audit-card"]],
  "recall-card": ["Thu hồi lô hàng", "Thông tin Recall theo phạm vi được cấp quyền.", ["recall-card"]],
};
let activeAppScreen = "overview";
let screenDataVersion = 0;

function isSelectedScreenBatch(prefix, batchId) {
  if (prefix === "detail") return currentDetailBatchId === batchId;
  const id = prefix === "trace" ? "trace-screen-batch" : "events-screen-batch";
  return Number($(id).value) === batchId;
}

function canOpenScreen(key) {
  if (!session) return false;
  if (key === "farm-card") return ["farmer", "org_admin", "inspector", "system_admin"].includes(session?.role);
  if (key === "users-card") return isAdmin();
  if (key === "audit-card") return canViewAuditLogs();
  if (key === "recall-card") return window.AGRITRACE_CONFIG?.maxSprint !== 3;
  if (key === "pending-handovers-card") return canHandover();
  return Object.hasOwn(appScreens, key);
}

function setupUserMenuDropdown() {
  const btn = $("user-menu-btn");
  const menu = $("user-dropdown-menu");
  if (!btn || !menu) return;

  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const expanded = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!expanded));
    menu.hidden = expanded;
  });

  document.addEventListener("click", (e) => {
    if (!btn.contains(e.target) && !menu.contains(e.target)) {
      btn.setAttribute("aria-expanded", "false");
      menu.hidden = true;
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) {
      btn.setAttribute("aria-expanded", "false");
      menu.hidden = true;
      btn.focus();
    }
  });
}

function setupAppScreens() {
  const view = $("app-view");
  history.scrollRestoration = "manual";
  setupUserMenuDropdown();
  for (const [key, [, , cards]] of Object.entries(appScreens)) {
    const screen = document.createElement("div");
    screen.className = "app-screen";
    screen.dataset.screen = key;
    screen.hidden = true;
    view.append(screen);
    for (const id of cards) screen.append($(id));
  }
  window.addEventListener("hashchange", () => renderAppScreen());
  window.addEventListener("popstate", () => renderAppScreen());
  $("app-sidebar").addEventListener("click", (event) => {
    const link = event.target.closest("a[href^='#']");
    if (!link || !session) return;
    event.preventDefault();
    if (location.hash !== link.hash) history.pushState(null, "", link.hash);
    renderAppScreen();
  });
  $("trace-screen-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const id = Number($("trace-screen-batch").value);
    if (id && session) loadDetailLineage(id, "trace");
  });
  $("events-screen-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const id = Number($("events-screen-batch").value);
    if (id && session) loadDetailTimeline(id, "events");
  });
  $("btn-events-verify-chain").addEventListener("click", () => {
    const id = Number($("events-screen-batch").value);
    if (id && session) verifyDetailChain(id, "events");
  });
  $("events-screen-batch").addEventListener("change", () => {
    setHidden("events-timeline-valid-banner", true);
    setHidden("events-timeline-alert-banner", true);
    $("events-timeline-list").replaceChildren();
  });
  $("trace-screen-batch").addEventListener("change", () => setHidden("trace-lineage-body", true));
}

function renderAppScreen(scroll = true) {
  if (!document.querySelector(".app-screen")) return;
  let key = location.hash.slice(1) || "overview";
  if (key === "products-card") key = "batch-card";
  if (key === "inspector-card") key = "events";
  if (session && !canOpenScreen(key)) {
    key = "overview";
    history.replaceState(null, "", "#overview");
  }
  activeAppScreen = key;
  document.querySelectorAll(".app-screen").forEach((screen) => {
    screen.hidden = !session || screen.dataset.screen !== key;
  });
  document.querySelectorAll("#app-sidebar a[href^='#']:not(.sidebar-brand)").forEach((link) => {
    const target = link.hash.slice(1);
    link.hidden = !canOpenScreen(target);
    const selected = Boolean(session) && target === key;
    link.classList.toggle("is-active", selected);
    if (selected) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  if (!session) {
    screenDataVersion++;
    $("recent-activity-list").replaceChildren();
    $("trace-root-batches-list").replaceChildren();
    $("trace-lineage-levels-container").replaceChildren();
    $("events-timeline-list").replaceChildren();
    setHidden("trace-lineage-body", true);
    setHidden("trace-lineage-loading", true);
    setHidden("events-timeline-valid-banner", true);
    setHidden("events-timeline-alert-banner", true);
    $("events-timeline-valid-text").textContent = "";
    $("events-timeline-alert-text").textContent = "";
    $("trace-screen-batch").replaceChildren();
    $("events-screen-batch").replaceChildren();
    return;
  }
  $("screen-title").textContent = appScreens[key][0];
  let desc = appScreens[key][1];
  if (key === "farm-card") {
    if (session.role === "inspector") {
      desc = "Giám sát thông tin cơ sở và thửa đất canh tác trên toàn hệ thống (Chỉ xem).";
    } else if (!canManageFarms()) {
      desc = "Xem danh mục thửa đất xuất xứ trong phạm vi tổ chức (Chỉ xem — không có quyền khai báo/chỉnh sửa).";
    }
  } else if (key === "batch-card") {
    if (session.role === "farmer") {
      desc = "Khai báo thu hoạch, quản lý lô, thực hiện tách lô và chuyển giao cho khâu tiếp theo.";
    } else if (session.role === "processor") {
      desc = "Quản lý lô tiếp nhận, thực hiện tách lô, gộp lô và bàn giao cho đối tác.";
    } else if (session.role === "transporter") {
      desc = "Theo dõi các lô đang vận chuyển, nhận bàn giao và chuyển tiếp đến điểm phân phối.";
    } else if (session.role === "distributor") {
      desc = "Quản lý lô nông sản phân phối, thực hiện tách lô, bàn giao hoặc ghi nhận tiêu thụ.";
    } else if (session.role === "inspector") {
      desc = "Giám sát thông tin lô hàng toàn hệ thống (Chỉ xem — không tham gia thao tác sản xuất).";
    } else if (isSystemAdmin() || isOrgAdmin()) {
      desc = "Theo dõi dữ liệu lô hàng trong phạm vi được cấp quyền (Chỉ xem — không thao tác nghiệp vụ sản xuất).";
    }
  } else if (key === "users-card") {
    desc = isSystemAdmin()
      ? "Quản trị danh mục tài khoản người dùng và phân quyền toàn hệ thống."
      : "Quản lý tài khoản thành viên trong tổ chức của bạn.";
  } else if (key === "audit-card") {
    desc = session.role === "inspector"
      ? "Nhật ký kiểm toán và thanh tra hoạt động toàn hệ thống."
      : isSystemAdmin()
      ? "Theo dõi toàn bộ nhật ký thao tác và sự kiện quản trị hệ thống."
      : "Theo dõi nhật ký thao tác của người dùng trong tổ chức.";
  }
  $("screen-description").textContent = desc;
  if (scroll) {
    document.querySelectorAll(".modal-backdrop:not([id^='recall'])").forEach((modal) => { modal.hidden = true; });
    window.scrollTo({ top: 0, behavior: "instant" });
    $("screen-title").focus({ preventScroll: true });
  }
}

async function refreshScreenData() {
  const actor = session;
  const version = ++screenDataVersion;
  for (const id of ["trace-screen-batch", "events-screen-batch"]) {
    const select = $(id);
    const selected = select.value;
    select.innerHTML = '<option value="">Chọn lô đang hiển thị…</option>' + batches.map((batch) =>
      `<option value="${escapeHtml(batch.id)}">${escapeHtml(batch.code)} · ${escapeHtml(batch.product_name || "")}</option>`).join("");
    if (batches.some((batch) => String(batch.id) === selected)) select.value = selected;
  }
  $("recent-activity-list").textContent = "Đang tải hoạt động gần đây…";
  const events = await Promise.all(batches.slice(0, 5).map(async (batch) => {
    try {
      const rows = await apiRequest(`/batches/${batch.id}/events`);
      return { rows: rows.map((row) => ({ ...row, dashboardCode: batch.code })), state: "ready" };
    } catch (error) { return { rows: [], state: dataErrorState(error) }; }
  }));
  if (actor !== session || version !== screenDataVersion) return;
  if (events.length && events.every(result => result.state !== "ready")) {
    $("recent-activity-list").textContent = events.every(result => result.state === "denied") ? "Không có quyền xem" : "Không tải được dữ liệu";
    return;
  }
  const recent = events.flatMap(result => result.rows).sort((a, b) => String(b.timestamp || b.created_at).localeCompare(String(a.timestamp || a.created_at))).slice(0, 5);
  $("recent-activity-list").innerHTML = recent.length ? recent.map((event) =>
    `<div class="recent-event"><div><strong>${escapeHtml(event.dashboardCode)}</strong><span>${escapeHtml(event.event_type)}</span></div><time>${escapeHtml(formatDateTime(event.timestamp || event.created_at))}</time></div>`).join("") : '<p class="empty">Chưa có hoạt động trong các lô được lấy mẫu.</p>';
  if (events.some(result => result.state !== "ready")) $("recent-activity-list").insertAdjacentHTML("afterbegin", '<p class="empty">Không tải được đầy đủ dữ liệu sự kiện của các lô được lấy mẫu.</p>');
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
  if (window.AGRITRACE_CONFIG?.maxSprint === 3) {
    try {
      const response = await fetch(`${API_BASE_URL}/demo-scope`, { cache: "no-store" });
      if (!response.ok) throw new Error("Profile unavailable");
      const scope = await response.json();
      if (scope.scope !== "sprint123" || !scope.synthetic) throw new Error("Unexpected profile");
      // Xác minh profile/database demo hợp lệ trong nền, không hiển thị thanh thông báo kỹ thuật ra giao diện người dùng
    } catch (error) {
      console.warn("Không xác minh được profile/database demo:", error);
      $("login-submit").disabled = true;
      return;
    }
  }
  const apiEl = $("stat-api");
  if (apiEl) {
    apiEl.textContent = API_BASE_URL;
  }
  setupAppScreens();
  bindEvents();
  bindAccountControls();
  $("batch-prev").addEventListener("click", () => { batchPage--; selectedBatchIds.clear(); loadBatches(); });
  $("batch-next").addEventListener("click", () => { batchPage++; selectedBatchIds.clear(); loadBatches(); });
  resetFarmForm();
  resetBatchForm();
  await checkHealth();

  // Giai đoạn 2: Khôi phục phiên làm việc bằng xác thực server-side (/auth/me)
  try {
    const me = await apiRequest("/auth/me");
    startSession(me);
    toast(`Đã khôi phục phiên đăng nhập: ${me.username}.`, "info");
    await reloadAll({ silent: true });
    return;
  } catch (error) {
    clearSession();
  }

  applySessionToUi();
  $("login-username").focus();
}

document.addEventListener("DOMContentLoaded", init);
