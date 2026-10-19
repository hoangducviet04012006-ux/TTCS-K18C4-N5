/* =====================================================================
   Frontend demo - Truy xuất nguồn gốc và giám sát chuỗi lạnh nông sản
   JavaScript thuần (không framework, không thư viện ngoài).
   Cấu trúc: cấu hình -> tiện ích -> gọi API -> trạng thái -> render -> sự kiện.
   ===================================================================== */

"use strict";


// In-page confirmation avoids browser-native dialogs blocking QA and mobile input.
function confirmAction(message) {
  if (document.getElementById("action-confirm-dialog")) return Promise.resolve(false);
  return new Promise(resolve => {
    const previousFocus = document.activeElement;
    const dialog = document.createElement("dialog");
    dialog.id = "action-confirm-dialog";
    dialog.setAttribute("aria-labelledby", "action-confirm-title");
    dialog.style.cssText = "max-width:460px;width:calc(100% - 32px);border:0;border-radius:12px;padding:24px;box-shadow:0 16px 60px #0004";
    const title = document.createElement("h3");
    title.id = "action-confirm-title";
    title.textContent = "Xác nhận thao tác";
    const text = document.createElement("p");
    text.textContent = message;
    text.style.whiteSpace = "pre-line";
    const actions = document.createElement("div");
    actions.style.cssText = "display:flex;justify-content:flex-end;gap:12px;margin-top:20px";
    const cancel = document.createElement("button");
    cancel.type = "button"; cancel.className = "btn"; cancel.textContent = "Hủy";
    const accept = document.createElement("button");
    accept.type = "button"; accept.className = "btn btn--primary"; accept.textContent = "Xác nhận";
    const finish = value => {
      dialog.close(); dialog.remove();
      if (previousFocus?.isConnected) previousFocus.focus();
      resolve(value);
    };
    cancel.addEventListener("click", () => finish(false), {once:true});
    accept.addEventListener("click", () => finish(true), {once:true});
    dialog.addEventListener("cancel", event => { event.preventDefault(); finish(false); }, {once:true});
    actions.append(cancel, accept); dialog.append(title, text, actions);
    document.body.append(dialog); dialog.showModal(); cancel.focus();
  });
}

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
window.formatRelationType = formatRelationType;

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
window.formatBatchStatus = formatBatchStatus;

/** Chuẩn hóa loại sự kiện sang tiếng Việt dễ hiểu */
function formatEventType(type) {
  const map = {
    HARVEST: "Thu hoạch ban đầu",
    BATCH_UPDATED: "Cập nhật thông tin lô",
    SPLIT: "Tách lô",
    GENESIS_SPLIT: "Lô được tạo từ thao tác tách",
    MERGE: "Gộp lô",
    EXPORT_MERGE: "Xuất gộp lô",
    HANDOVER_INIT: "Yêu cầu bàn giao",
    HANDOVER_SENT: "Yêu cầu bàn giao",
    HANDOVER_ACCEPT: "Đã tiếp nhận",
    HANDOVER_ACCEPTED: "Đã tiếp nhận",
    HANDOVER_REJECT: "Từ chối tiếp nhận",
    HANDOVER_REJECTED: "Từ chối tiếp nhận",
    CONSUMED: "Đã tiêu thụ",
    INTERNAL_TRANSFER: "Chuyển vị trí nội bộ",
    RECALL_INIT: "Mở lệnh thu hồi",
    RECALL_AFFECTED: "Cách ly lô liên quan",
    RECALL_ACKNOWLEDGED: "Xác nhận xử lý",
    RECALL_COMPLETED: "Hoàn tất xác nhận",
    TRIP_DISPATCH: "Khởi hành chuyến lạnh (lên xe)",
    TRIP_DELIVER: "Hoàn thành chuyến lạnh (xuống xe)",
  };
  return map[String(type || "").toUpperCase()] || "Sự kiện nghiệp vụ";
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
  const requestActor = session;
  const headers = { "X-Requested-With": "XMLHttpRequest", ...extraHeaders };
  if (body && !(body instanceof FormData)) {
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
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      credentials: "include", // Luôn gửi và nhận HttpOnly session cookie
      signal: controller.signal,
    });
  } catch (error) {
    // `status = 0`: không có phản hồi HTTP (backend chưa chạy hoặc sai cổng).
    const offline = new Error(
      `Không kết nối được máy chủ. Vui lòng kiểm tra kết nối và mở lại phần mềm.`
    );
    offline.status = 0;
    throw offline;
  } finally {
    window.clearTimeout(timeout);
  }

  const data = await readJson(response);
  if (auth && requestActor !== session && !["/auth/login", "/auth/demo-login", "/auth/logout"].includes(path)) {
    const error = new Error("Tài khoản đã thay đổi; phản hồi của phiên trước được bỏ qua.");
    error.stale = true;
    throw error;
  }
  if (!response.ok) {
    // Giai đoạn 3A.1: Tự động xử lý khi phiên đăng nhập hết hạn hoặc bị thu hồi (HTTP 401)
    if (response.status === 401 && path !== "/auth/login") {
      handleSessionExpired();
    }
    const error = new Error(describeError(data, response.status));
    error.status = response.status;
    error.detail = data?.detail;
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
let auditOffset = 0;
// SCRUM-27/28: Danh sách tổ chức và các bàn giao đang chờ duyệt
let organizations = [];
let pendingHandovers = [];
let products = [];
let batchSearchDebounceTimer = null;
let batchPage = 1;
let batchRequestVersion = 0;
// Giai đoạn 1B: Theo dõi bàn giao nông sản cho vai trò Farmer
let activeFarmerHandoverTab = "outgoing";
let farmerRejectedBatchesCache = [];
let farmerRejectedCheckVersion = 0;

// SPRINT 3: Tách / Gộp lô & Phả hệ BFS & Quá hạn 48h
let selectedBatchIds = new Set();
let currentDetailBatchId = null;
let currentDetailBatchCode = "";
let currentDetailTab = "overview";
let forwardLineageRequest = 0;
let currentSplitBatch = null;

// SCRUM-77 S-40: Quản lý chuyến xe lạnh
let coldTrips = [];
let currentDetailTripId = null;

/** Kiểm tra một thời điểm có quá 48 giờ so với hiện tại hay không. */
function checkIsOverdue(createdAtStr) {
  if (!createdAtStr) return false;
  try {
    const text = String(createdAtStr);
    const created = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(text) ? text : `${text.replace(" ", "T")}Z`);
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
  clearSession();
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
  for (const id of ["org-badge", "user-badge", "user-dropdown-meta"]) if ($(id)) $(id).textContent = "";
  setHidden("user-dropdown-menu", true);
  $("user-menu-btn")?.setAttribute("aria-expanded", "false");
  batchRequestVersion++; userRequestVersion++; farmerRejectedCheckVersion++;
  batchEvidence.clear(); selectedBatchIds.clear();
  $("toast-container")?.replaceChildren();
  currentSplitBatch = null; editingBatchId = null; editingFarmId = null;
  userPage = 1; batchPage = 1;
  products = []; organizations = [];
  for (const id of ["batch-search-input", "batch-filter-product", "user-search", "user-role-filter", "user-status-filter", "inspect-batch-code"]) if ($(id)) $(id).value = "";
  for (const id of ["batch-form", "farm-form", "account-form", "password-form", "handover-form", "reject-form", "product-form"]) $(id)?.reset();
  for (const id of ["batch-form-mode", "farm-form-mode", "batch-cancel", "farm-cancel", "batch-success-banner", "inspect-result-container"]) setHidden(id, true);
  for (const id of ["detail-overview-meta", "detail-timeline-list", "detail-root-batches-list", "detail-lineage-levels-container", "user-load-status", "audit-error"]) $(id)?.replaceChildren();
  farms = []; batches = []; users = []; auditLogs = []; pendingHandovers = [];
  auditOffset = 0; $("audit-filter-form")?.reset(); $("audit-table-body")?.replaceChildren();
  activeFarmerHandoverTab = "outgoing";
  farmerRejectedBatchesCache = [];
  for (const key of Object.keys(dataLoadState)) dataLoadState[key] = "idle";
  screenDataVersion++;
  currentDetailBatchId = null;
  window.phaseCUi?.reset();
  $("detail-forward-graph")?.replaceChildren();
  if ($("detail-forward-graph")) $("detail-forward-graph").onclick = null;
  $("detail-terminal-batches-list")?.replaceChildren();
  for (const id of ["trace-root-batches-list", "trace-lineage-levels-container", "events-timeline-list", "recent-activity-list"]) $(id).textContent = "";
  for (const id of ["trace-screen-batch", "events-screen-batch"]) $(id).innerHTML = '<option value="">Chọn lô đang hiển thị…</option>';
  for (const id of ["events-timeline-valid-banner", "events-timeline-alert-banner", "trace-lineage-body"]) setHidden(id, true);
  renderProducts(); renderProductOptions(); renderFarmOptions();
  renderFarms(); renderBatches(); renderUsers(); renderAuditLogs(); renderPendingHandovers();
  batchPage = 1;
  const pageSizeSelect = $("batch-page-size");
  if (pageSizeSelect) pageSizeSelect.value = "5";
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

// Verified against backend/app/services/rbac.py and router dependencies.
const UI_ACTION_ROLES = Object.freeze({
  HARVEST: ["farmer"], FARM_MANAGE: ["farmer", "org_admin"],
  BATCH_UPDATE: ["farmer", "processor", "transporter", "distributor", "org_admin"],
  SPLIT: ["farmer", "processor", "distributor"], MERGE: ["processor"],
  HANDOVER_INIT: ["farmer", "processor", "transporter", "distributor"],
  HANDOVER_RESPOND: ["farmer", "processor", "transporter", "distributor"],
  LOCATION_MANAGE: ["distributor", "org_admin"],
  BATCH_CONSUME: ["distributor", "org_admin"], PRODUCT_CREATE: ["system_admin", "admin"],
  USER_MANAGE: ["system_admin", "admin", "org_admin"],
  AUDIT_VIEW: ["system_admin", "admin", "org_admin", "inspector"],
  INTEGRITY_VERIFY: ["farmer", "processor", "transporter", "distributor", "org_admin", "system_admin", "admin", "inspector"],
  TRIP_CREATE: ["transporter", "org_admin"],
  TRIP_COMPLETE: ["transporter", "org_admin"],
});
function hasUiAction(action) { return !!session && !!UI_ACTION_ROLES[action]?.includes(session.role); }
function requireUiAction(action) {
  if (hasUiAction(action)) return true;
  toast("Tài khoản hiện tại không có quyền thực hiện thao tác này.", "error");
  return false;
}
function batchUiLabel() {
  if (isPackingUser()) return "Lô sơ chế & đóng gói";
  return { processor: "Lô tiếp nhận & xử lý", transporter: "Lô vận chuyển", distributor: "Lô phân phối" }[session?.role] || "Lô nông sản";
}
function accountUiLabel() {
  if (isPackingUser()) return "Nhân viên sơ chế & đóng gói";
  return {farmer: "Nông dân", processor: "Nhân viên tiếp nhận & xử lý", transporter: "Nhân viên vận chuyển", distributor: "Nhân viên phân phối", inspector: "Cán bộ kiểm tra", org_admin: "Quản trị tổ chức", system_admin: "Quản trị hệ thống", admin: "Quản trị hệ thống"}[session?.role] || "Thành viên";
}
const batchEvidence = new Map();
function batchIsHeld(batch) {
  return !!session && session.organization_id != null && batch?.current_org_id === session.organization_id;
}
function batchIsRecalled(batch) {
  return batch?.is_recalled === true || !!(window.recallUi?.isBatchRecalled(batch?.id) || window.recallUi?.isBatchRecalled(batch?.code));
}
function batchHasPending(batch) { return !!(batch?.is_pending || batch?.pending_handover); }
function batchActionAllowed(batch, action) {
  if (!hasUiAction(action) || !batchIsHeld(batch)) return false;
  if (batchHasPending(batch) || batchIsRecalled(batch)) return false;
  const evidence = batchEvidence.get(batch.id);
  if (action === "BATCH_UPDATE") {
    // The existing form edits origin and quantity, frozen after any relation/handover.
    return !!evidence && !evidence.error && !evidence.hasHistory && batch.status !== "CONSUMED";
  }
  if (action !== "MERGE" && !["ACTIVE", "SPLIT"].includes(batch.status)) return false;
  if (action === "MERGE" && batch.status === "CONSUMED") return false;
  if (batch.remaining_quantity == null || !Number.isFinite(Number(batch.remaining_quantity)) || Number(batch.remaining_quantity) <= 0) return false;
  const flag = {SPLIT: "can_split", MERGE: "can_merge", HANDOVER_INIT: "can_handover", BATCH_CONSUME: "can_consume"}[action];
  return !flag || evidence?.summary?.[flag] !== false;
}
function requireBatchAction(batch, action) {
  if (batchActionAllowed(batch, action)) return true;
  toast("Lô không đủ điều kiện cho thao tác này hoặc dữ liệu quyền chưa được tải. Vui lòng làm mới danh sách.", "error");
  return false;
}
function handoverResponseAllowed(h, accept = false) {
  return hasUiAction("HANDOVER_RESPOND") && !!h && h.status === "PENDING" && session.organization_id != null && h.to_org_id === session.organization_id && (!accept || !batchIsRecalled({id: h.batch_id, code: h.batch_code}));
}
function canManageAccount(user) {
  return isSystemAdmin() || (isOrgAdmin() && session.organization_id != null && (!user || (user.organization_id === session.organization_id && !["system_admin", "admin", "inspector"].includes(user.role))));
}

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
  setHidden("nav-recall", !isLoggedIn || !isRecallEnabled());
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
  const isFarmerRole = session?.role === "farmer";
  const hasBatchPageSize = isLoggedIn;
  setHidden("farmer-quick-actions", !isFarmerRole);
  setHidden("farmer-page-size-wrap", !hasBatchPageSize);
  setHidden("batch-count-label", !hasBatchPageSize);
  if (!isFarmerRole) setHidden("farmer-overdue-banner", true);

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
    const batchNavLabel = batchUiLabel();
    updateSidebarNavItem(navBatches, "batches", batchNavLabel);
  }
  const navPending = $("nav-pending");
  if (navPending) {
    navPending.hidden = !canHandover();
    const isFarmer = session?.role === "farmer";
    const outgoingCount = batches.filter(b => b.is_pending || b.pending_handover).length;
    const countBadge = isFarmer
      ? (outgoingCount > 0 ? `<span class="sidebar-count-badge">${outgoingCount}</span>` : "")
      : ((canHandover() && pendingHandovers.length > 0) ? `<span class="sidebar-count-badge">${pendingHandovers.length}</span>` : "");
    updateSidebarNavItem(navPending, "pending", isFarmer ? "Theo dõi bàn giao" : "Tiếp nhận bàn giao", countBadge);
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
    orgBadge.textContent = ` ${session.organization_name}`;
    orgBadge.title = session.organization_name;
  }

  const badge = $("user-badge");
  if (badge !== null && isLoggedIn) {
    const roleText = ROLE_NAMES[session.role] || (adminUser ? "Quản trị viên" : "Thành viên");
    badge.textContent = accountUiLabel();
    badge.title = `${session.username} · ${roleText}`;
    badge.className = "user-menu-text";
    const dropdownMeta = $("user-dropdown-meta");
    if (dropdownMeta) {
      dropdownMeta.textContent = `${session.username} · ${roleText} · ${session.organization_name || "Giám sát toàn hệ thống"}`;
    }
  }

  const orgContext = $("farm-org-context");
  if (orgContext !== null && isLoggedIn) {
    orgContext.textContent = `Các thửa đất thuộc: ${session.organization_name || "Tổ chức của bạn"}`;
  }

  const batchCardTitle = $("batch-card-title");
  if (batchCardTitle) {
    if (isPackingUser()) {
      batchCardTitle.innerHTML = 'Quản lý lô sơ chế &amp; đóng gói <span class="tag">Sơ chế &amp; Đóng gói</span>';
    } else if (session?.role === "processor") {
      batchCardTitle.innerHTML = 'Quản lý lô nông sản <span class="tag">Tiếp nhận &amp; Chế biến</span>';
    } else if (session?.role === "farmer") {
      batchCardTitle.textContent = "Quản lý lô nông sản (Thu hoạch & Truy xuất)";
    } else {
      batchCardTitle.textContent = batchUiLabel();
    }
  }
  const batchCardDesc = $("batch-card-desc");
  if (batchCardDesc) {
    if (isPackingUser()) {
      batchCardDesc.textContent = "Theo dõi các lô tiếp nhận, thực hiện sơ chế, phân loại, tách lô, gộp lô và chuyển giao cho đối tác chuỗi cung ứng.";
    } else if (session?.role === "processor") {
      batchCardDesc.textContent = "Theo dõi các lô nông sản tiếp nhận, thực hiện chế biến, tách lô, gộp lô và chuyển giao trong chuỗi cung ứng.";
    } else {
      batchCardDesc.textContent = session?.role === "farmer" ? "Theo dõi thu hoạch, khối lượng và nguồn gốc của lô đang giữ." : "Theo dõi lượng còn lại, vị trí và tình trạng các lô của tổ chức.";
    }
  }

  setHidden("users-card", !adminUser);
  if (adminUser) {
    $("users-card").querySelector(".card__title").textContent = isOrgAdmin() ? "Tài khoản nội bộ tổ chức" : "Tài khoản toàn hệ thống";
    $("users-card").querySelector(".card__desc").textContent = isOrgAdmin() ? `Chỉ quản lý thành viên thuộc ${session.organization_name || "tổ chức của bạn"}.` : "Quản lý tài khoản theo quyền quản trị hệ thống.";
  }
  setHidden("audit-card", !canViewAuditLogs());
  setHidden("stat-audit-card", !canViewAuditLogs());
  setHidden("btn-open-add-product", !isSystemAdmin());
  setHidden("nav-products", !isSystemAdmin());
  updateSidebarNavItem($("nav-products"), "batches", "Danh mục sản phẩm");
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
  const currentBatchLimit = hasBatchPageSize ? (Number($("batch-page-size")?.value) || 5) : 20;
  $("stat-batches").closest("article").querySelector(".stat-card__hint").textContent = `Trang ${batchPage}, tối đa ${currentBatchLimit} lô · ${scopeText}`;
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

  const pendingTitle = $("pending-handovers-title");
  const pendingDesc = $("pending-handovers-desc");
  if (pendingTitle && pendingDesc) {
    if (session?.role === "farmer") {
      pendingTitle.innerHTML = ` Theo dõi bàn giao nông sản <span id="badge-pending-count" class="badge badge--warning">0 lô</span>`;
      pendingDesc.textContent = "Theo dõi trạng thái các lô hàng nông trại đã bàn giao cho các khâu tiếp theo và xử lý phản hồi từ đối tác.";
    } else if (isPackingUser()) {
      pendingTitle.innerHTML = ` Tiếp nhận bàn giao nông sản <span id="badge-pending-count" class="badge badge--warning">0 lô</span>`;
      pendingDesc.textContent = "Danh sách các lô nông sản do tổ chức khác gửi đến HTX Tân Cương cần xác nhận tiếp nhận để đưa vào quy trình sơ chế, phân loại & đóng gói.";
    } else if (session?.role === "processor") {
      pendingTitle.innerHTML = ` Tiếp nhận bàn giao nông sản <span id="badge-pending-count" class="badge badge--warning">0 lô</span>`;
      pendingDesc.textContent = "Danh sách các lô nông sản chuyển giao đến cơ sở cần xác nhận tiếp nhận để đưa vào quy trình chế biến & lưu chuyển.";
    } else {
      pendingTitle.innerHTML = ` Lô hàng chờ xác nhận bàn giao <span id="badge-pending-count" class="badge badge--warning">0 lô</span>`;
      pendingDesc.textContent = "Danh sách các lô nông sản được tổ chức khác bàn giao đến tổ chức của bạn. Vui lòng xác nhận tiếp nhận hoặc từ chối.";
    }
  }
  renderFarmerHandoverPanels();
  setHidden("inspector-card", !session || !(isSystemAdmin() || session.role === "inspector"));
  setHidden("products-card", !isSystemAdmin());
  const phaseSection = document.querySelector(".sidebar-section--phase-c");
  if (phaseSection) phaseSection.hidden = !canOpenScreen("locations-card") && !canOpenScreen("imports-card");

  renderStats();
  renderAppScreen(false);
}

/** Nhân viên sơ chế & đóng gói (s123_packing - HTX Tân Cương, Org 1). */
function isPackingUser() {
  return session !== null && (session.role === "processor" && session.organization_id === 1);
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

function isRecallEnabled() {
  return !!window.AGRITRACE_CONFIG?.recallEnabled || window.AGRITRACE_CONFIG?.maxSprint !== 3;
}

function canViewAuditLogs() {
  return hasUiAction("AUDIT_VIEW");
}

/** Nông dân canh tác có quyền thu hoạch (HARVEST). */
function canHarvest() {
  return hasUiAction("HARVEST");
}

/** BATCH_UPDATE: các vai trò nghiệp vụ và org_admin, theo backend. */
function canUpdateBatch() {
  return hasUiAction("BATCH_UPDATE");
}

/** Quản lý thửa đất / vùng trồng (FARM_MANAGE): nông dân và quản trị tổ chức. */
function canManageFarms() {
  return hasUiAction("FARM_MANAGE");
}

/** Gộp lô (MERGE): chỉ nhà chế biến (processor). */
function canMerge() {
  return hasUiAction("MERGE");
}

/** Tách lô (SPLIT): nông dân, nhà chế biến, nhà phân phối. */
function canSplit() {
  return hasUiAction("SPLIT");
}

/** Bàn giao (HANDOVER_INIT): nông dân, nhà chế biến, vận chuyển, nhà phân phối. */
function canHandover() {
  return hasUiAction("HANDOVER_INIT");
}

/** Ghi nhận đã tiêu thụ (CONSUMED - S-29): nhà phân phối (distributor) hoặc quản trị tổ chức (org_admin). */
function canConsume() {
  return hasUiAction("BATCH_CONSUME");
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
 * Kiểm tra quyền xoá lô nông sản:
 * - Theo backend delete_batch: chỉ admin của tổ chức đang giữ lô (isHolder).
 * - Backend cấm tuyệt đối xoá lô đã có lịch sử bất biến (trả 409 Conflict).
 * - Chỉ hiện khi endpoint sự kiện đã xác nhận lô không có lịch sử bất biến.
 */
function canDeleteFarm(farm) {
  // Hidden by UX: FarmResponse exposes neither linked batch count nor a delete flag.
  // A current batch page cannot prove that no historical batch references this farm.
  return false;
}

function canDeleteBatch(batch) {
  if (!batch || !canDelete()) return false;
  const isHolder = session && session.organization_id != null && batch.current_org_id === session.organization_id;
  if (!isHolder) return false;
  return batchEvidence.get(batch.id)?.eventCount === 0;
}

/**
 * Hiển thị / xoá cảnh báo đỏ ngay trong form đăng nhập.
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
  coldTrips = [];
  currentDetailTripId = null;
  renderColdTripsTable();

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

/* ---------------------------------------------------- 6.1. Sản phẩm & Đơn vị tính --- */
/** GET /products -> cập nhật danh mục sản phẩm toàn hệ thống */
async function loadProducts() {
  const actor = session;
  dataLoadState.products = "loading";
  try {
    const data = await apiRequest("/products");
    if (actor !== session) return;
    dataLoadState.products = "ready";
    products = Array.isArray(data) ? data : [];
    renderProducts();
    renderProductOptions(); renderStats();
  } catch (error) {
    if (actor !== session) return;
    dataLoadState.products = dataErrorState(error); products = []; renderProducts(); renderProductOptions();
    toast(`Không tải được danh mục sản phẩm: ${error.message}`, "error");
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
  if (!requireUiAction("PRODUCT_CREATE")) return;
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

let farmViewMode = "table"; // "cards" | "table"

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
  setHidden("farm-table-body-controls", isCards);
  setHidden("farm-table-body-pager", isCards);
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
              <h4 class="farm-card__name">${escapeHtml(farm.name)}</h4>
            </div>
            <span class="farm-card__area-badge">${formatNumber(farm.area)} ha</span>
          </div>
          <div class="farm-card__body">
            <div class="farm-card__meta">
              <span class="meta-label">Vị trí:</span>
              <span class="meta-value">${escapeHtml(farm.location)}</span>
            </div>
            <div class="farm-card__meta">
              <span class="meta-label">Tọa độ GPS:</span>
              <span class="meta-value">${farm.coordinates ? escapeHtml(farm.coordinates) : '<em style="color:#9ca3af">Chưa cập nhật</em>'}</span>
            </div>
            <div class="farm-card__meta">
              <span class="meta-label">Nông hộ phụ trách:</span>
              <span class="meta-value">${escapeHtml(farm.owner)}</span>
            </div>
          </div>
          <div class="farm-card__footer">
            ${
              canManageFarms()
                ? `<button class="btn btn--primary btn--sm" type="button"
                    data-action="edit" data-entity="farm"
                    data-id="${escapeHtml(farm.id)}">Sửa</button>`
                : ""
            }
            ${
              canDeleteFarm(farm)
                ? `<button class="btn btn--danger btn--sm" type="button"
                    data-action="delete" data-entity="farm"
                    data-id="${escapeHtml(farm.id)}">Xoá</button>`
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
                canDeleteFarm(farm)
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
  $("farm-cancel").hidden = false;
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
  if (!canDeleteFarm(farms.find(f => f.id === farmId))) {
    toast("Chưa xác minh được điều kiện xóa vùng trồng: API không cung cấp số lô liên quan.", "error");
    return;
  }
  const farm = farms.find((item) => item.id === farmId);
  const label = farm ? `#${farm.id} — ${farm.name}` : `#${farmId}`;
  const childCount = batches.filter((batch) => batch.farm_id === farmId).length;

  const question =
    `Bạn có chắc chắn muốn xoá vùng trồng ${label}?` +
    (childCount > 0 ? "\nVùng trồng có lô truy xuất sẽ được bảo vệ khỏi việc xóa." : "") +
    "\nHành động này không thể hoàn tác.";
  if (!await confirmAction(question)) {
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

    const isFarmer = session?.role === "farmer";
    const hasCustomPageSize = true;
    const pageSizeEl = $("batch-page-size");
    const limitVal = hasCustomPageSize ? (Number(pageSizeEl?.value) || 5) : 20;

    const query = new URLSearchParams({page: batchPage, limit: limitVal});
    if (searchVal) query.append("search", searchVal);
    if (productVal) query.append("product_id", productVal);

    const qs = query.toString() ? `?${query.toString()}` : "";
    const data = await apiRequest(`/batches${qs}`);
    if (version !== batchRequestVersion || actor !== session) return;
    dataLoadState.batches = "ready";
    batches = Array.isArray(data) ? data : [];
    const evidenceRows = await Promise.all(batches.map(async batch => {
      try {
        const [summary, events] = await Promise.all([
          apiRequest(`/batches/${batch.id}/summary`), apiRequest(`/batches/${batch.id}/events`),
        ]);
        return [batch.id, { summary, eventCount: events.length,
          hasHistory: summary.direct_parents.length > 0 || summary.direct_children.length > 0 || events.some(e => ["HANDOVER_INIT", "HANDOVER_ACCEPT", "HANDOVER_REJECT"].includes(e.event_type)) }];
      } catch (error) { return [batch.id, {error: error.message}]; }
    }));
    if (version !== batchRequestVersion || actor !== session) return;
    batchEvidence.clear();
    for (const [id, evidence] of evidenceRows) batchEvidence.set(id, evidence);
    const evidenceFailures = evidenceRows.filter(([, evidence]) => evidence.error);
    if (evidenceFailures.length) toast(`Không xác minh được quyền chi tiết của ${evidenceFailures.length} lô; thao tác sửa/xóa tạm ẩn. ${evidenceFailures[0][1].error}`, "warning");
    $("batch-page-label").textContent = `Trang ${batchPage}`;
    $("batch-prev").disabled = batchPage <= 1;
    $("batch-next").disabled = batches.length < limitVal;

    const countLabel = $("batch-count-label");
    if (countLabel) {
      if (hasCustomPageSize) {
        countLabel.hidden = false;
        if (batches.length === 0) {
          countLabel.textContent = "Không có lô nào";
        } else if (batches.length < limitVal) {
          countLabel.textContent = `Hiển thị ${batches.length} lô · Hết danh sách`;
        } else {
          countLabel.textContent = `Hiển thị ${batches.length} lô`;
        }
      } else {
        countLabel.hidden = true;
      }
    }

    renderBatches();
    if (session?.role === "farmer") {
      renderFarmerHandoverPanels();
      checkFarmerRejectedBatches();
    }
    await refreshScreenData();
    maybeAutoOpenDemoLineage(searchVal);
  } catch (error) {
    if (version !== batchRequestVersion || actor !== session) return;
    dataLoadState.batches = dataErrorState(error); batches = [];
    renderBatches();
    $("recent-activity-list").textContent = dataStateText(dataLoadState.batches);
    $("batch-page-label").textContent = "Tải dữ liệu thất bại";
    const countLabel = $("batch-count-label");
    if (countLabel) countLabel.textContent = "Lỗi tải dữ liệu";
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

/** Tìm kiếm mã lô với debounce 300ms */
function clearMergeSelectionWithNotice() {
  if (selectedBatchIds.size) toast("Đã bỏ lựa chọn gộp khi đổi bộ lọc. Gộp chỉ áp dụng cho lô trên cùng một trang.", "info");
  selectedBatchIds.clear();
}
function onBatchSearchInput() {
  if (batchSearchDebounceTimer) {
    clearTimeout(batchSearchDebounceTimer);
  }
  batchSearchDebounceTimer = setTimeout(() => {
    batchPage = 1; clearMergeSelectionWithNotice();
    loadBatches();
  }, 300);
}

/** Nhãn vùng trồng cho bảng lô (dùng lại dữ liệu đã tải từ GET /farms). */
function farmLabel(farmId) {
  const farm = farms.find((item) => item.id === farmId);
  return farm ? `#${farmId} — ${farm.name}` : `#${farmId}`;
}

/** Kiểm tra lô nông sản có đủ điều kiện hợp lệ để gộp lô theo quy tắc backend hay không */
function isBatchEligibleForMerge(batch) {
  return batchActionAllowed(batch, "MERGE");
}

/** Lấy lý do chi tiết vì sao lô không đủ điều kiện gộp để hiển thị tooltip/giải thích */
function getBatchMergeIneligibleReason(batch) {
  if (!session || !canMerge()) return "Tài khoản không có quyền gộp lô.";
  const isHolder = session && session.organization_id != null && batch.current_org_id === session.organization_id;
  if (!isHolder) return "Lô thuộc quyền sở hữu của tổ chức khác.";
  const isRecalled = batchIsRecalled(batch);
  if (isRecalled) return "Lô hàng đang trong lệnh thu hồi / sự cố.";
  const pendingItem = pendingHandovers.find((h) => h.batch_id === batch.id);
  const isPending = batchHasPending(batch) || (pendingItem != null);
  if (isPending) return "Lô đang có yêu cầu bàn giao chờ xác nhận (chờ xác nhận).";
  if (batch.status === "CONSUMED") return "Lô hàng đã tiêu thụ (CONSUMED).";
  const initialQty = batch.initial_quantity != null ? batch.initial_quantity : batch.quantity;
  const remainingQty = batch.remaining_quantity != null ? batch.remaining_quantity : initialQty;
  if (batch.remaining_quantity == null || !Number.isFinite(Number(batch.remaining_quantity))) return "Chưa có dữ liệu khối lượng còn lại để xác minh điều kiện gộp.";
  if (Number(remainingQty) <= 0) return "Lô đã hết khối lượng còn lại (0 kg).";
  return "";
}

/** Cập nhật trạng thái nút "Gộp lô đã chọn" dựa trên các checkbox được chọn. */
function updateMergeButtonState() {
  const btn = $("btn-open-merge-batches");
  if (!btn) return;

  // Giai đoạn 3A.1: Chỉ processor có quyền MERGE mới được kích hoạt nút
  if (!canMerge()) {
    btn.disabled = true;
    btn.hidden = true;
    const hint = $("merge-condition-hint");
    if (hint) hint.hidden = true;
    return;
  }
  btn.hidden = false;

  const hint = $("merge-condition-hint");

  // Loại bỏ các ID không còn hợp lệ khỏi tập đã chọn
  let removedSelections = 0;
  for (const id of selectedBatchIds) {
    const b = batches.find((item) => item.id === id);
    if (!b || !isBatchEligibleForMerge(b)) {
      selectedBatchIds.delete(id);
      removedSelections++;
    }
  }
  if (removedSelections) toast(`Đã bỏ ${removedSelections} lựa chọn gộp vì lô không còn đủ điều kiện trên trang hiện tại.`, "warning");

  const eligibleBatches = batches.filter(isBatchEligibleForMerge);
  const count = selectedBatchIds.size;
  const selectAll = $("batch-select-all");
  if (selectAll) {
    selectAll.checked = eligibleBatches.length > 0 && selectedBatchIds.size === eligibleBatches.length;
    selectAll.disabled = eligibleBatches.length < 2;
    selectAll.title = eligibleBatches.length < 2
      ? "Cần ít nhất 2 lô đủ điều kiện để chọn tất cả"
      : "Chọn tất cả các lô đủ điều kiện gộp trên trang này";
  }

  if (count === 0) {
    btn.disabled = true;
    btn.textContent = `Gộp lô đã chọn (0)`;
    btn.title = eligibleBatches.length < 2
      ? "Trang hiện tại chưa có đủ 2 lô hợp lệ (còn khối lượng > 0, không chờ bàn giao hoặc bị thu hồi) để gộp"
      : "Chọn ít nhất 2 lô cùng sản phẩm trên cùng một trang để gộp";
    if (hint) {
      hint.hidden = false;
      hint.className = "merge-condition-hint";
      hint.textContent = eligibleBatches.length < 2
        ? "Chưa đủ 2 lô hợp lệ trên trang này để gộp (lô phải còn khối lượng > 0 kg, không chờ bàn giao hoặc bị thu hồi). Nếu các lô ở trang khác, vui lòng tăng số lô/trang hoặc lọc theo sản phẩm."
        : `Tích chọn ít nhất 2 lô cùng loại sản phẩm trên trang này để gộp (hiện có ${eligibleBatches.length} lô đủ điều kiện). Lưu ý: Thao tác gộp chỉ áp dụng cho các lô trên cùng một trang.`;
    }
    return;
  }

  if (count === 1) {
    btn.disabled = true;
    btn.textContent = `Gộp lô đã chọn (1)`;
    btn.title = "Cần chọn ít nhất 2 lô cùng sản phẩm trên cùng một trang để gộp";
    if (hint) {
      hint.hidden = false;
      hint.className = "merge-condition-hint merge-condition-hint--warn";
      hint.textContent = "Đã chọn 1 lô trên trang này. Vui lòng chọn thêm ít nhất 1 lô nữa cùng loại sản phẩm trên cùng trang để gộp.";
    }
    return;
  }

  const selectedBatches = batches.filter((b) => selectedBatchIds.has(b.id));
  const firstProdId = selectedBatches[0].product_id;
  const allSameProduct = selectedBatches.every((b) => b.product_id === firstProdId);

  if (!allSameProduct) {
    btn.disabled = true;
    btn.textContent = `Khác loại SP (${count})`;
    btn.title = "Tất cả các lô chọn để gộp phải cùng một loại sản phẩm";
    if (hint) {
      hint.hidden = false;
      hint.className = "merge-condition-hint merge-condition-hint--warn";
      hint.textContent = `Không thể gộp: ${count} lô được chọn có sản phẩm khác nhau. Tất cả phải cùng loại sản phẩm.`;
    }
    return;
  }

  btn.disabled = false;
  btn.textContent = `Gộp ${count} lô đã chọn`;
  btn.title = `Gộp ${count} lô sản phẩm ${selectedBatches[0].product_name} trên trang này`;
  if (hint) {
    hint.hidden = false;
    hint.className = "merge-condition-hint merge-condition-hint--ok";
    hint.textContent = `Đủ điều kiện: Sẵn sàng gộp ${count} lô sản phẩm "${selectedBatches[0].product_name}" trên trang này.`;
  }
}

/** Vẽ bảng danh sách lô nông sản (kèm checkbox gộp lô, cột Đơn vị nắm giữ, Trạng thái & Thao tác). */
function renderBatches() {
  $("batch-table-body").innerHTML = batches
    .map((batch) => {
      const holdingOrg = batch.current_org_name || (session?.organization_name || farmLabel(batch.farm_id));
      const pendingItem = pendingHandovers.find((h) => h.batch_id === batch.id);
      const isPending = batchHasPending(batch) || (pendingItem != null);

      // Kiểm tra quá hạn 48h bên gửi/bên nhận
      const isOverdue = (batch.pending_handover && (batch.pending_handover.is_overdue || checkIsOverdue(batch.pending_handover.created_at))) ||
                        (pendingItem && (pendingItem.is_overdue || checkIsOverdue(pendingItem.created_at)));

      // Kiểm tra trạng thái sự cố và thu hồi
      const isRecalled = batchIsRecalled(batch);
      const recallInfo = window.recallUi?.getBatchRecallInfo ? (window.recallUi.getBatchRecallInfo(batch.id) || window.recallUi.getBatchRecallInfo(batch.code)) : null;

      let statusBadge = '<span class="badge badge--ok">Đang quản lý</span>';
      if (isRecalled) {
        statusBadge = `<span class="badge badge--danger" style="background:#dc2626; color:#fff; font-weight:700;" title="Lô hàng có sự cố và đang trong lệnh thu hồi ${escapeHtml(recallInfo?.recall_code || '')}">Có sự cố</span>`;
      } else if (batch.status === "CONSUMED") {
        statusBadge = '<span class="badge" style="background:#64748b; color:#fff;" title="Lô hàng đã bán hết cho người tiêu dùng">Đã tiêu thụ</span>';
      } else if (batch.status === "SPLIT") {
        statusBadge = '<span class="badge badge--info" style="background:#0284c7; color:#fff;">Đã tách</span>';
      } else if (batch.status === "MERGED") {
        statusBadge = '<span class="badge badge--info" style="background:#7c3aed; color:#fff;">Đã gộp</span>';
      } else if (isPending) {
        statusBadge = isOverdue
          ? '<span class="badge badge--warning">Chờ duyệt</span> <span class="badge badge--overdue" title="Yêu cầu bàn giao đã quá hạn 48 giờ">Quá hạn 48h</span>'
          : '<span class="badge badge--warning">Chờ duyệt bàn giao</span>';
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

      const canOpenRecall = isRecallEnabled() && (session?.role === "inspector" || (session?.role === "org_admin" && isHolder));
      if (canOpenRecall) {
        if (isRecalled) {
          recallBtn = `<button class="btn btn--outline-danger btn--sm" type="button"
                         data-action="open-recall-section"
                         title="Lô hàng đang trong lệnh thu hồi ${escapeHtml(recallInfo?.recall_code || '')}. Bấm để xem danh sách thu hồi."
                         style="border-color:#dc2626; color:#dc2626;">Lệnh thu hồi</button>`;
        } else {
          recallBtn = `<button class="btn btn--outline-danger btn--sm" type="button"
                         data-action="create-recall" data-id="${escapeHtml(batch.id)}" data-code="${escapeHtml(batch.code || '')}"
                         title="Đánh dấu lô có sự cố và mở lệnh thu hồi kèm lý do"
                         style="border-color:#dc2626; color:#dc2626;">Báo sự cố</button>`;
        }
      }

      if (isHolder && batch.status !== "CONSUMED") {
        if (isRecalled) {
          // Khi lô có sự cố / trong lệnh thu hồi: Phong tỏa mọi thao tác vật lý
          if (canHandover()) {
            handoverBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang có sự cố / bị thu hồi: chặn bàn giao">Bàn giao</button>`;
          }
          if (canSplit()) {
            splitBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang có sự cố / bị thu hồi: chặn tách lô">Tách</button>`;
          }
          if (canConsume()) {
            consumeBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang có sự cố / bị thu hồi: chặn tiêu thụ">Tiêu thụ</button>`;
          }
        } else if (isPending) {
          if (canHandover()) {
            handoverBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang có yêu cầu bàn giao chờ xác nhận">Chờ duyệt</button>`;
          }
          if (canSplit()) {
            splitBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="Lô hàng đang chờ duyệt bàn giao">Tách</button>`;
          }
        } else {
          if (batchActionAllowed(batch, "HANDOVER_INIT")) {
            handoverBtn = `<button class="btn btn--outline-primary btn--sm" type="button"
                             data-action="open-handover" data-id="${escapeHtml(batch.id)}">Bàn giao</button>`;
          }
          if (batchActionAllowed(batch, "SPLIT")) {
            splitBtn = `<button class="btn btn--outline-primary btn--sm" type="button"
                          data-action="split-batch" data-id="${escapeHtml(batch.id)}" title="Tách thành nhiều lô con">Tách</button>`;
          }
          if (batchActionAllowed(batch, "BATCH_CONSUME")) {
            consumeBtn = `<button class="btn btn--outline-warning btn--sm" type="button"
                            data-action="consume-batch" data-id="${escapeHtml(batch.id)}" title="Ghi nhận đã bán hết cho người tiêu dùng" style="border-color:#d97706; color:#d97706;">Tiêu thụ</button>`;
          }
        }
        if (
          batchActionAllowed(batch, "BATCH_UPDATE")
        ) {
          editBtn = `<button class="btn btn--light btn--sm" type="button"
                             data-action="edit" data-entity="batch"
                             data-id="${escapeHtml(batch.id)}">Sửa</button>`;
        }
      }

      const mergeEligible = isBatchEligibleForMerge(batch);
      const mergeIneligibleReason = getBatchMergeIneligibleReason(batch);
      if (!mergeEligible && selectedBatchIds.has(batch.id)) {
        selectedBatchIds.delete(batch.id);
      }
      const mergeCheckbox = mergeEligible
        ? `<input type="checkbox" class="batch-select-checkbox" data-id="${escapeHtml(batch.id)}" ${selectedBatchIds.has(batch.id) ? "checked" : ""} title="Chọn lô ${escapeHtml(batchCodeDisplay)} để gộp" />`
        : `<input type="checkbox" class="batch-select-checkbox" data-id="${escapeHtml(batch.id)}" disabled title="${escapeHtml(mergeIneligibleReason)}" />`;

      return `
      <tr class="${batch.id === editingBatchId ? "is-editing" : ""}">
        <td style="text-align: center;" ${canMerge() ? "" : "hidden"}>
          ${mergeCheckbox}
        </td>
        <td class="id-cell">
          <strong style="font-family:'Cascadia Mono',monospace; letter-spacing:1px; background:#0f172a; color:#facc15; padding:3px 8px; border-radius:4px; font-size:0.95rem;">
            ${escapeHtml(batchCodeDisplay)}
          </strong>
          ${batch.is_simulation ? `<span class="badge" style="background:#e0f2fe; color:#0369a1; border:1px solid #bae6fd; font-size:0.68rem; margin-left:4px; font-weight:600;" title="Dữ liệu nguồn gốc mô phỏng: ${escapeHtml(batch.dataset_source || 'Thực hành')}">Mô phỏng</span>` : ''}
        </td>
        <td><strong>${escapeHtml(batch.product_name)}</strong></td>
        <td class="is-right"><strong>${formatNumber(remainingQty)} ${escapeHtml(batch.unit || "kg")}</strong><span class="quantity-original">Ban đầu: ${formatNumber(initialQty)}</span></td>
        <td>${escapeHtml(holdingOrg)}</td>
        <td>${escapeHtml([batch.current_location_name,batch.current_location].filter(Boolean).join(" · ") || "Chưa ghi nhận")}</td>
        <td>${statusBadge}</td>
        <td>
          <div class="batch-actions-cell">
            <button class="btn btn--light btn--sm" type="button" data-action="view-details" data-id="${escapeHtml(batch.id)}">Chi tiết</button>
            <details class="action-dropdown" data-batch-id="${escapeHtml(batch.id)}">
              <summary class="action-dropdown__toggle" aria-label="Thao tác cho lô ${escapeHtml(batchCodeDisplay)}">Thao tác ▾</summary>
              <div class="action-dropdown__menu">
                <button class="btn btn--light btn--sm mobile-detail-action" type="button" data-action="view-details" data-id="${escapeHtml(batch.id)}">Xem chi tiết</button>
                <button class="btn btn--light btn--sm" type="button" data-action="view-details" data-open-lineage="true" data-id="${escapeHtml(batch.id)}">Truy xuất nguồn gốc</button>
                ${splitBtn}${handoverBtn}${consumeBtn}${recallBtn}${editBtn}
                ${canDeleteBatch(batch) ? `<button class="btn btn--danger btn--sm" type="button" data-action="delete" data-entity="batch" data-id="${escapeHtml(batch.id)}">Xóa lô</button>` : ""}
              </div>
            </details>
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
  return editingBatchId === null ? "Lưu thu hoạch" : "Lưu thay đổi";
}

/** Xoá các thông báo lỗi inline của form lô thu hoạch */
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
 * Xử lý submit form lô nông sản:
 * - Hiển thị lỗi inline ngay cạnh từng ô nhập;
 * - Vô hiệu hóa nút Lưu ngay khi bấm để chặn nhấn đúp;
 * - Khi thành công hiển thị mã lô cỡ lớn >= 28px in đậm ngoài trời nắng kèm nút sao chép.
 */
async function handleBatchSubmit(event) {
  event.preventDefault();
  const isEditing = editingBatchId !== null;
  if (!isEditing && !canHarvest()) {
    toast("Vai trò của bạn không có quyền khai báo thu hoạch.", "error");
    return;
  }
  if (isEditing && !canUpdateBatch()) {
    toast("Vai trò của bạn không có quyền cập nhật lô nông sản.", "error");
    return;
  }
  if (isEditing && !requireBatchAction(batches.find(b => b.id === editingBatchId), "BATCH_UPDATE")) return;
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
  const today = new Intl.DateTimeFormat("en-CA", {timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date());
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

  const button = $("batch-submit");
  // Vô hiệu hóa nút Lưu ngay khi gửi để chặn nhấn đúp
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
      const original = batches.find(b => b.id === editingBatchId);
      if (!farms.some(f => f.id === payload.plot_id && f.organization_id === session.organization_id)) {
        if (payload.plot_id !== original.plot_id) throw new Error("Vùng trồng mới phải thuộc tổ chức của bạn.");
        delete payload.plot_id; delete payload.farm_id;
      }
      const updated = await apiRequest(`/batches/${editingBatchId}`, { method: "PUT", body: payload });
      toast(`Đã cập nhật lô #${updated.id} "${updated.product_name}"`, "success");
    } else {
      const created = await apiRequest("/batches", { method: "POST", body: payload });
      toast(`Tạo thành công lô #${created.id} - Mã lô: ${created.code}`, "success");

      // Hiển thị mã lô cỡ lớn 28px+ độ tương phản cao để đọc ngoài trời nắng
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
  $("batch-entry").querySelector("summary").textContent = "Ghi nhận lô thu hoạch";
  $("batch-form").reset();
  $("batch-form-mode").hidden = true;
  $("batch-cancel").hidden = false;
  $("batch-submit").textContent = batchSubmitLabel();
  if (!canHarvest()) {
    setHidden("batch-entry", true);
  }
}

/**
 * Bấm nút "Sửa" ở bảng lô -> đổ dữ liệu lên form và chuyển sang chế độ sửa
 * (nút submit sẽ gọi ``PUT /batches/{id}``).
 */
function startEditBatch(batchId) {
  if (!canUpdateBatch()) {
    toast("Vai trò của bạn không có quyền sửa lô nông sản.", "error");
    return;
  }
  const candidate = batches.find(item => item.id === batchId);
  if (!requireBatchAction(candidate, "BATCH_UPDATE")) return;
  const batchEntry = $("batch-entry");
  if (batchEntry) {
    batchEntry.querySelector("summary").textContent = "Cập nhật thông tin lô";
    batchEntry.hidden = false;
    batchEntry.open = true;
  }
  const batch = batches.find((item) => item.id === batchId);
  if (!batch) {
    toast(`Không tìm thấy lô nông sản #${batchId} trong dữ liệu đang hiển thị.`, "error");
    return;
  }

  editingBatchId = batch.id;
  const targetFarmId = batch.farm_id || batch.plot_id;
  if (targetFarmId) {
    const select = $("batch-farm-id");
    if (![...select.options].some(option => option.value === String(targetFarmId))) {
      select.add(new Option(batch.plot_name || batch.farm_name || `Vùng xuất xứ #${targetFarmId}`, String(targetFarmId)));
    }
    select.value = String(targetFarmId);
  }

  const productSelect = $("batch-product-id");
  if (productSelect) {
    if (batch.product_id) {
      productSelect.value = String(batch.product_id);
    } else {
      const found = products.find((p) => p.name === batch.product_name);
      if (found) productSelect.value = String(found.id);
    }
  }
  $("batch-product-name").value = batch.product_name || "";
  const initialQty = batch.initial_quantity != null ? batch.initial_quantity : batch.quantity;
  $("batch-quantity").value = initialQty;
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
  if (!canDeleteBatch(batch)) {
    toast("Lô nông sản đã có lịch sử bất biến hoặc thuộc tổ chức khác, không thể xoá.", "error");
    return;
  }
  const label = batch ? `#${batch.id} — ${batch.product_name}` : `#${batchId}`;

  if (!await confirmAction(`Bạn có chắc chắn muốn xoá lô nông sản ${label}?\nHành động này không thể hoàn tác.`)) {
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

/* ----------------------------- 8.1. Kiểm tra toàn vẹn Hash-Chain --- */
/** Xác thực toàn vẹn chuỗi sự kiện của một lô nông sản theo mã hoặc ID */
async function handleInspectChain() {
  if (!session || !(isSystemAdmin() || session.role === "inspector")) { toast("Biểu mẫu này dành cho thanh tra và quản trị hệ thống.", "error"); return; }
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
      resultContainer.innerHTML = `<div class="integrity-alert-banner"> Không tìm thấy lô nông sản với mã hoặc ID "${escapeHtml(val)}".</div>`;
      return;
    }

    const integrity = await apiRequest(`/batches/${targetId}/integrity`);

    if (integrity.is_valid || integrity.valid) {
      resultContainer.innerHTML = `
        <div class="integrity-valid-badge">
          <span style="font-size:1.4rem;">✓</span>
          <div>
            <div><strong style="color:#15803d; font-size:1.05rem;">Chuỗi sự kiện hợp lệ</strong></div>
            <div>Mã lô: <strong>${escapeHtml(targetBatch?.code || '#' + targetId)}</strong> — Tổng số sự kiện: <strong>${integrity.total_events || 'Tất cả'}</strong></div>
            <div style="font-size:0.88rem; color:#166534; margin-top:4px;">Không phát hiện sai lệch trong chuỗi sự kiện tại thời điểm kiểm tra.</div>
          </div>
        </div>`;
    } else {
      const errId = integrity.tampered_event_id || integrity.event_id || "Chưa xác định";
      const errType = integrity.error_type || "HASH_MISMATCH";
      resultContainer.innerHTML = `
        <div class="integrity-alert-banner" style="display:block;">
          <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
            <span style="font-size:1.5rem;"></span>
            <strong style="font-size:1.1rem;">Phát hiện sai lệch trong chuỗi sự kiện</strong>
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

/* ----------------------------- 8.2. Dòng thời gian sự kiện Timeline --- */
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
                <span class="timeline-item__time"> ${escapeHtml(formatDateTime(e.timestamp || e.created_at))}</span>
              </div>
              <div class="timeline-item__meta">
                <strong> ${escapeHtml(orgName)}</strong> ·  ${escapeHtml(userName)}
              </div>
              <div style="margin-bottom: 8px; color: #1e293b;">
                ${escapeHtml(desc)}
              </div>
              <div class="timeline-item__hash" title="Mã băm SHA-256 toàn vẹn: ${escapeHtml(e.current_hash)}">
                 Mã xác thực: <code>${escapeHtml(shortHash)}</code>
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
 * - **Vùng trồng đã tải**: số phần tử của `farms` (nguồn: `GET /farms`);
 * - **Tổng lô nông sản**: số phần tử của `batches` (nguồn: `GET /batches`);
 * - **Tổng sản lượng (kg)**: cộng `quantity` của mọi lô (làm tròn 2 chữ số);
 * - **Lịch sử thao tác** (Sprint 7, chỉ admin thấy): số phần tử của `auditLogs`
 *   (nguồn: `GET /audit-logs`) - farmer không tải được nên thẻ này bị ẩn.
 *
 * Hàm được gọi lại mỗi khi vẽ xong bảng (`renderFarms` / `renderBatches` /
 * `renderAuditLogs`) nên số liệu luôn khớp với dữ liệu vừa tải.
 */
const dataLoadState = { farms: "idle", batches: "idle", audit: "idle", pending: "idle", users: "idle", products: "idle", organizations: "idle" };
function dataErrorState(error) { return error.status === 403 ? "denied" : "error"; }
function dataStateText(state) {
  return ({idle:"—", loading:"Đang tải…", denied:"Không có quyền xem", error:"Không tải được dữ liệu"})[state] || "";
}
/** Đổi tên các sự kiện kỹ thuật trên Dashboard sang tiếng Việt chuẩn theo nghiệp vụ nông dân */
function formatDashboardEventType(type) {
  const t = String(type || "").toUpperCase().trim();
  const map = {
    HARVEST: "Thu hoạch",
    HANDOVER_INIT: "Gửi yêu cầu bàn giao",
    HANDOVER_PENDING: "Gửi yêu cầu bàn giao",
    HANDOVER_SENT: "Gửi yêu cầu bàn giao",
    HANDOVER_ACCEPT: "Đối tác đã tiếp nhận",
    HANDOVER_ACCEPTED: "Đối tác đã tiếp nhận",
    HANDOVER_REJECT: "Đối tác từ chối",
    HANDOVER_REJECTED: "Đối tác từ chối",
    SPLIT: "Tách lô",
    GENESIS_SPLIT: "Lô mới từ tách",
    MERGE: "Gộp lô",
    EXPORT_MERGE: "Xuất gộp lô",
    CONSUMED: "Tiêu thụ",
    INTERNAL_TRANSFER: "Chuyển vị trí nội bộ",
    ALLOCATE_STORES: "Phân bổ cửa hàng",
    RECALL_ACKNOWLEDGED: "Xác nhận xử lý thu hồi",
    RECALL_COMPLETED: "Hoàn tất xác nhận thu hồi",
    RECALL_INIT: "Khởi tạo thu hồi",
    RECALL_AFFECTED: "Ảnh hưởng thu hồi",
    RECALL_COMPLETE: "Hoàn tất thu hồi",
    TEMP_CHECK: "Kiểm tra nhiệt độ",
    INSPECTION: "Kiểm định chất lượng",
    STATUS_UPDATE: "Cập nhật trạng thái",
    TRIP_DISPATCH: "Khởi hành chuyến lạnh (lên xe)",
    TRIP_DELIVER: "Hoàn thành chuyến lạnh (xuống xe)",
  };
  return map[t] || "Sự kiện nghiệp vụ";
}

/** Trích xuất mô tả sự kiện bằng tiếng Việt dễ hiểu cho Nông dân */
function getEventDescription(event) {
  if (event.event_data && event.event_data.trim() && !event.event_data.startsWith("Sự kiện ")) {
    return event.event_data.trim();
  }
  let payload = event.payload;
  if (typeof payload === "string") {
    try { payload = JSON.parse(payload); } catch (e) { payload = {}; }
  }
  if (payload && typeof payload === "object") {
    if (payload.description) return String(payload.description).trim();
    if (payload.message) return String(payload.message).trim();
    if (payload.note) return String(payload.note).trim();
  }
  if (event.notes && event.notes.trim()) return event.notes.trim();
  const type = String(event.event_type || "").toUpperCase().trim();
  if (type === "HARVEST") return "Ghi nhận thu hoạch nông sản ban đầu";
  if (type === "HANDOVER_INIT") return "Gửi yêu cầu bàn giao lô nông sản cho đối tác";
  if (type === "HANDOVER_ACCEPT") return "Đối tác đã xác nhận tiếp nhận lô thành công";
  if (type === "HANDOVER_REJECT") return "Yêu cầu bàn giao bị đối tác từ chối";
  if (type === "SPLIT") return "Tách lô thành các lô nhỏ hơn";
  if (type === "MERGE") return "Gộp các lô thành lô mới";
  if (type === "CONSUMED") return "Lô hàng đã được ghi nhận tiêu thụ hết";
  if (type === "TRIP_DISPATCH") return "Lô hàng được xếp lên thùng lạnh và khởi hành vận chuyển";
  if (type === "TRIP_DELIVER") return "Lô hàng đã kết thúc hành trình vận chuyển lạnh và dỡ khỏi xe";
  return "";
}

function renderStats() {
  const isFarmer = session?.role === "farmer";
  const scope = session?.role === "inspector" ? "Toàn hệ thống" : `Tổ chức: ${session?.organization_name || "chưa được gán"}`;

  setHidden("stat-farms-card", !canOpenScreen("farm-card") || isSystemAdmin());
  setHidden("stat-batches-card", isSystemAdmin());
  setHidden("stat-yield-card", isSystemAdmin());
  setHidden("recent-activity", isSystemAdmin());
  setHidden("stat-users-card", !isAdmin());
  setHidden("stat-products-card", !isSystemAdmin());
  setHidden("stat-orgs-card", !isSystemAdmin());
  setHidden("stat-eligible-card", !(canSplit() || canMerge() || canConsume()));
  setHidden("stat-outgoing-card", !canHandover() || session?.role === "farmer");
  if ($("stat-outgoing")) $("stat-outgoing").textContent = dataLoadState.batches === "ready" ? formatNumber(batches.filter(batchHasPending).length) : dataStateText(dataLoadState.batches);
  if ($("stat-users")) $("stat-users").textContent = dataLoadState.users === "ready" ? formatNumber(users.length) : dataStateText(dataLoadState.users);
  if ($("stat-products")) $("stat-products").textContent = dataLoadState.products === "ready" ? formatNumber(products.length) : dataStateText(dataLoadState.products);
  if ($("stat-orgs")) $("stat-orgs").textContent = dataLoadState.organizations === "ready" ? formatNumber(organizations.length) : dataStateText(dataLoadState.organizations);
  if ($("stat-eligible")) {
    const action = canConsume() ? "BATCH_CONSUME" : "SPLIT";
    $("stat-eligible").textContent = dataLoadState.batches === "ready" ? formatNumber(batches.filter(b => batchActionAllowed(b, action)).length) : dataStateText(dataLoadState.batches);
    $("stat-eligible-label").textContent = canConsume() ? "Lô đủ điều kiện tiêu thụ" : canMerge() ? "Lô đủ điều kiện tách / gộp" : "Lô đủ điều kiện tách";
    if (canMerge() && dataLoadState.batches === "ready") $("stat-eligible").textContent = `${batches.filter(b => batchActionAllowed(b, "SPLIT")).length} / ${batches.filter(isBatchEligibleForMerge).length}`;
  }
  // Thẻ 1: Vùng trồng
  $("stat-farms").textContent = dataLoadState.farms === "ready" ? formatNumber(farms.length) : dataStateText(dataLoadState.farms);
  const statFarmsCard = $("stat-farms-card");
  if (statFarmsCard) {
    const hintEl = statFarmsCard.querySelector(".stat-card__hint");
    if (hintEl) {
      hintEl.textContent = isFarmer
        ? `Vùng trồng canh tác thuộc ${session?.organization_name || "Hợp tác xã"}`
        : "Số vùng đã tải trong phạm vi tài khoản";
    }
  }

  // Thẻ 2: Lô nông sản
  $("stat-batches").textContent = dataLoadState.batches === "ready" ? formatNumber(batches.length) : dataStateText(dataLoadState.batches);
  const statBatchesCard = $("stat-batches-card");
  if (statBatchesCard) {
    const labelEl = statBatchesCard.querySelector(".stat-card__label");
    const hintEl = statBatchesCard.querySelector(".stat-card__hint");
    if (session) {
      const currentLimit = Number($("batch-page-size")?.value) || 5;
      if (labelEl) labelEl.textContent = `${batchUiLabel()} (Trang hiện tại)`;
      if (hintEl) hintEl.textContent = `Trang ${batchPage} (tối đa ${currentLimit} lô) · ${scope} · Theo bộ lọc danh sách lô`;
    } else {
      if (labelEl) labelEl.textContent = "Lô trên trang hiện tại";
      if (hintEl) hintEl.textContent = `Trang ${batchPage}, tối đa 20 lô · ${scope} · Theo bộ lọc danh sách lô`;
    }
  }

  // Thẻ 3: Khối lượng
  const totals = new Map();
  for (const batch of batches) {
    const unit = batch.unit || "kg";
    totals.set(unit, (totals.get(unit) || 0) + Number(batch.remaining_quantity ?? batch.quantity ?? 0));
  }
  $("stat-yield").textContent = [...totals].map(([unit, quantity]) => `${formatNumber(Math.round(quantity * 100) / 100)} ${unit}`).join(" · ") || "0";
  if (dataLoadState.batches !== "ready") $("stat-yield").textContent = dataStateText(dataLoadState.batches);
  const statYieldCard = $("stat-yield-card");
  if (statYieldCard) {
    const labelEl = statYieldCard.querySelector(".stat-card__label");
    const hintEl = statYieldCard.querySelector(".stat-card__hint");
    if (isFarmer) {
      if (labelEl) labelEl.textContent = "Sản lượng còn lại (Trang hiện tại)";
      if (hintEl) hintEl.textContent = `Khối lượng các lô đang hiển thị trên trang ${batchPage}`;
    } else {
      if (labelEl) labelEl.textContent = "Khối lượng còn lại trên trang";
      if (hintEl) hintEl.textContent = "Khối lượng các lô đang hiển thị";
    }
  }

  // Thẻ 4: Nhật ký kiểm toán (Sprint 7, chỉ admin thấy)
  $("stat-audit").textContent = dataLoadState.audit === "ready" ? formatNumber(auditLogs.length) : dataStateText(dataLoadState.audit);

  // Thẻ 5: Lô chờ xác nhận (Farmer: tính số lô ĐÃ GỬI chờ đối tác nhận; các vai trò khác: số lô chờ nhận)
  const pendingStat = $("stat-pending-handovers");
  const outgoingPending = isFarmer ? batches.filter(b => b.is_pending || b.pending_handover) : [];
  if (pendingStat) {
    pendingStat.textContent = isFarmer
      ? (dataLoadState.batches === "ready" ? formatNumber(outgoingPending.length) : dataStateText(dataLoadState.batches))
      : (dataLoadState.pending === "ready" ? formatNumber(pendingHandovers.length) : dataStateText(dataLoadState.pending));
  }
  const statPendingCard = $("stat-pending-card");
  if (statPendingCard) {
    const labelEl = statPendingCard.querySelector(".stat-card__label");
    const hintEl = statPendingCard.querySelector(".stat-card__hint");
    if (isFarmer) {
      if (labelEl) labelEl.textContent = "Lô đã gửi chờ xác nhận (Trang hiện tại)";
      if (hintEl) hintEl.innerHTML = `Chờ đối tác tiếp nhận · Trang hiện tại · <a href="#pending-handovers-card">Theo dõi bàn giao →</a>`;
    } else {
      if (labelEl) labelEl.textContent = "Lô chờ xác nhận";
      if (hintEl) hintEl.innerHTML = `Chờ tiếp nhận · <a href="#pending-handovers-card">Xem chi tiết ↓</a>`;
    }
  }

  // Cảnh báo bàn giao quá hạn 48h dành riêng cho Farmer
  if (isFarmer) {
    const overdueList = outgoingPending.filter(b => {
      const createdAt = b.pending_handover?.created_at;
      return b.pending_handover?.is_overdue || checkIsOverdue(createdAt);
    });
    const overdueBanner = $("farmer-overdue-banner");
    if (overdueBanner) {
      if (overdueList.length > 0) {
        overdueBanner.hidden = false;
        const codes = overdueList.map(b => b.code).join(", ");
        const titleEl = $("farmer-overdue-title");
        const textEl = $("farmer-overdue-text");
        if (titleEl) titleEl.textContent = ` Cảnh báo: Có ${overdueList.length} lô bàn giao đã quá hạn 48 giờ chưa được tiếp nhận`;
        if (textEl) textEl.textContent = `Các lô: ${codes}. Bên nhận chưa xử lý, vui lòng liên hệ đối tác để kiểm tra.`;
      } else {
        overdueBanner.hidden = true;
      }
    }
    const quickHandoverDesc = $("farmer-quick-handover-desc");
    if (quickHandoverDesc) {
      quickHandoverDesc.textContent = outgoingPending.length > 0
        ? `${outgoingPending.length} lô đang chờ xác nhận${overdueList.length > 0 ? ` (${overdueList.length} quá hạn)` : ""}`
        : "Kiểm tra tiến độ các lô đã gửi đối tác";
    }
  } else {
    setHidden("farmer-overdue-banner", true);
  }
  window.workspaceUi?.limitStats();
}

/* ------------------------------------------ 10. Tài khoản (chỉ admin) --- */
let userPage = 1;
let userRequestVersion = 0;
const USER_PAGE_SIZE = 10;

async function loadUsers() {
  if (!hasUiAction("USER_MANAGE")) return;
  const actor = session;
  dataLoadState.users = "loading";
  const version = ++userRequestVersion;
  const params = new URLSearchParams({ page: userPage, limit: USER_PAGE_SIZE });
  for (const [id, key] of [["user-search", "search"], ["user-role-filter", "role"], ["user-org-filter", "organization_id"], ["user-status-filter", "is_active"]]) {
    if ($(id).value) params.set(key, $(id).value);
  }
  if (session?.role === "org_admin" && session.organization_id) {
    params.set("organization_id", session.organization_id);
  }
  $("user-load-status").textContent = "Đang tải tài khoản…";
  renderStats();
  try {
    const data = await apiRequest(`/users?${params}`);
    if (version !== userRequestVersion || actor !== session) return;
    dataLoadState.users = "ready";
    users = Array.isArray(data) ? data : [];
    renderUsers(); renderStats();
    $("user-load-status").textContent = `${users.length} tài khoản trên trang ${userPage}`;
  } catch (error) {
    if (version !== userRequestVersion || actor !== session) return;
    dataLoadState.users = dataErrorState(error);
    users = []; renderUsers(); renderStats();
    $("user-load-status").textContent = `Không tải được tài khoản: ${error.message}`;
    toast(error.message, "error");
  }
}

function renderUsers() {
  $("user-table-body").innerHTML = users.map(user => {
    const org = organizations.find(o => o.id === user.organization_id);
    const locked = user.is_locked || (user.locked_until && new Date(`${user.locked_until}Z`) > new Date());
    const status = !user.is_active ? "Vô hiệu hóa" : locked ? "Đã khóa" : "Hoạt động";
    const roleLabel = ROLE_NAMES[user.role] || user.role;
    const canManage = canManageAccount(user);
    const isSelf = user.username === session?.username;

    return `<tr><td>#${escapeHtml(user.id)}</td><td><strong>${escapeHtml(user.username)}</strong></td><td>${escapeHtml(user.email || "—")}</td>
      <td><span class="role-badge ${user.role === "system_admin" || user.role === "admin" ? "role-badge--admin" : "role-badge--farmer"}">${escapeHtml(roleLabel)}</span></td>
      <td>${escapeHtml(org?.name || "Chưa gán tổ chức")}</td><td><span class="badge ${user.is_active && !locked ? "badge--ok" : "badge--muted"}">${status}</span></td>
      <td class="account-actions">
        ${canManage ? `
          <button class="btn btn--light btn--sm" data-user-action="edit" data-id="${user.id}">Sửa</button>
          ${!isSelf ? `<button class="btn btn--light btn--sm" data-user-action="lock" data-id="${user.id}">${locked ? "Mở khóa" : "Khóa"}</button>
          <button class="btn btn--light btn--sm" data-user-action="active" data-id="${user.id}">${user.is_active ? "Vô hiệu hóa" : "Kích hoạt"}</button>
          <button class="btn btn--light btn--sm" data-user-action="password" data-id="${user.id}">Đặt mật khẩu</button>` : '<span class="badge badge--muted">Tài khoản của bạn · Đổi mật khẩu ở menu tài khoản</span>'}
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
  if (!canManageAccount(user)) { toast("Không có quyền quản lý tài khoản này.", "error"); return; }
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

  if (isOrgAdmin() && user?.role === "org_admin") {
    $("account-role").add(new Option("Quản trị tổ chức (vai trò hiện tại)", "org_admin"));
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
    if (!isSystemAdmin()) return;
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
    if (!isSystemAdmin()) { toast("Chỉ quản trị hệ thống được tạo tổ chức.", "error"); return; }
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
    if (!canManageAccount(id ? users.find(u => String(u.id) === id) || {organization_id: null} : null)) { toast("Không có quyền quản lý tài khoản này.", "error"); return; }
    const orgId = session?.role === "org_admin" ? session.organization_id : Number($("account-org").value);
    const body = { email: $("account-email").value, role: $("account-role").value, organization_id: orgId };
    const original = users.find(user => String(user.id) === id);
    if (isOrgAdmin()) {
      if (original && body.role === original.role) delete body.role;
      if (body.role && !["farmer", "processor", "transporter", "distributor"].includes(body.role)) { toast("Quản trị tổ chức chỉ được gán vai trò nhân viên nghiệp vụ.", "error"); return; }
    }
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
    if (!user || !canManageAccount(user)) return;
    const action = button.dataset.userAction;
    if (action === "edit") { openAccount(user); return; }
    if (action === "password") {
      $("password-form").reset(); $("password-user-id").value = user.id;
      $("password-title").textContent = `Đặt mật khẩu: ${user.username}`;
      $("password-current-label").textContent = "Mật khẩu của bạn để xác nhận *";
      $("password-error").hidden = true; $("password-dialog").showModal(); return;
    }
    if (!await confirmAction(`${button.textContent} tài khoản ${user.username}?`)) return;
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
    if (!session || (!self && (!user || !canManageAccount(user)))) { toast("Không có quyền đặt mật khẩu tài khoản này.", "error"); return; }
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
  if (!hasUiAction("AUDIT_VIEW")) return;
  const actor = session;
  dataLoadState.audit = "loading"; renderStats();
  const button = $("btn-load-audit");
  const errorBox = $("audit-error");

  // --- trạng thái đang tải ---
  setButtonLoading(button, true, "Đang tải…", "Làm mới nhật ký");
  errorBox.hidden = true;
  $("audit-empty").hidden = true;
  $("audit-table-body").innerHTML =
    '<tr class="is-loading"><td class="is-center" colspan="9">Đang tải nhật ký hoạt động…</td></tr>';

  try {
    const params = new URLSearchParams({limit: "100", offset: String(auditOffset)});
    for (const [key, id] of [["batch_id", "audit-filter-batch"], ["user_id", "audit-filter-user"], ["entity", "audit-filter-entity"]]) {
      if ($(id)?.value) params.set(key, $(id).value);
    }
    const data = await apiRequest(`/audit-logs?${params}`);
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
    sell_out: "Tiêu thụ hết", split: "Tách lô", merge: "Gộp lô", allocate_store: "Phân bổ cửa hàng",
    handover_init: "Khởi tạo bàn giao", handover_accept: "Tiếp nhận bàn giao", handover_reject: "Từ chối bàn giao",
    transfer_location: "Chuyển vị trí", recall: "Tạo yêu cầu thu hồi", confirm: "Xác nhận xử lý thu hồi", recall_complete: "Hoàn tất xác nhận thu hồi", csv_import: "Nhập CSV",
  };
  const entityLabels = {
    farm: "Vùng trồng",
    batch: "Lô nông sản",
    user: "Tài khoản", handover: "Bàn giao", recall: "Thu hồi", location: "Địa điểm", product: "Sản phẩm",
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
          actionLabels[log.operation || log.action.toLowerCase()] || log.operation || log.action
        )}</span></td>
        <td><span class="entity-badge">${escapeHtml(entityLabels[log.entity] || log.entity)}</span></td>
        <td class="is-right">#${escapeHtml(log.entity_id)}</td>
        <td>${escapeHtml((log.batch_ids || []).map(id => "#" + id).join(", ") || (log.entity === "batch" ? "#" + log.entity_id : "—"))}</td>
        <td>${escapeHtml(log.source_ip || "Chưa có dữ liệu")}</td>
        <td>${escapeHtml([log.location_name, log.location_address].filter(Boolean).join(" · ") || "Chưa có dữ liệu")}</td>
      </tr>`
    )
    .join("");

  $("audit-prev").disabled = auditOffset === 0;
  $("audit-next").disabled = auditLogs.length < 100;
  $("audit-page").textContent = `Trang ${auditOffset / 100 + 1} · ${auditLogs.length} bản ghi`;
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
  $("audit-filter-form").addEventListener("submit", event => { event.preventDefault(); auditOffset = 0; loadAuditLogs(); });
  $("audit-filter-reset").addEventListener("click", () => { $("audit-filter-form").reset(); auditOffset = 0; loadAuditLogs(); });
  $("audit-prev").addEventListener("click", () => { auditOffset = Math.max(0, auditOffset - 100); loadAuditLogs(); });
  $("audit-next").addEventListener("click", () => { auditOffset += 100; loadAuditLogs(); });

  // Thao tác nhanh trên Dashboard dành riêng cho Farmer
  const btnQuickAddFarm = $("btn-quick-add-farm");
  if (btnQuickAddFarm) {
    btnQuickAddFarm.addEventListener("click", () => {
      if (editingFarmId) cancelEdit("farm");
      if (location.hash !== "#farm-card") history.pushState(null, "", "#farm-card");
      renderAppScreen();
      const entry = $("farm-entry");
      if (entry) {
        entry.open = true;
        entry.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      $("farm-name")?.focus();
    });
  }
  const btnQuickHarvest = $("btn-quick-harvest");
  if (btnQuickHarvest) {
    btnQuickHarvest.addEventListener("click", () => {
      if (editingBatchId) cancelEdit("batch");
      if (location.hash !== "#batch-card") history.pushState(null, "", "#batch-card");
      renderAppScreen();
      const entry = $("batch-entry");
      if (entry) {
        entry.open = true;
        entry.scrollIntoView({ behavior: "smooth", block: "start" });
      }
      $("batch-farm-id")?.focus();
    });
  }
  const btnQuickTrackHandover = $("btn-quick-track-handover");
  if (btnQuickTrackHandover) {
    btnQuickTrackHandover.addEventListener("click", () => {
      if (location.hash !== "#pending-handovers-card") history.pushState(null, "", "#pending-handovers-card");
      renderAppScreen();
    });
  }

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
      if (session?.role === "farmer") {
        await loadBatches();
        await checkFarmerRejectedBatches(true);
      }
      await loadPendingHandovers();
      toast(session?.role === "farmer" ? "Đã làm mới thông tin theo dõi bàn giao." : "Đã làm mới danh sách lô chờ xác nhận.", "info");
    });
  }

  // Sự kiện Tab và Thao tác màn hình theo dõi bàn giao của Farmer
  const tabFarmerOutgoing = $("tab-farmer-outgoing");
  if (tabFarmerOutgoing) {
    tabFarmerOutgoing.addEventListener("click", () => {
      activeFarmerHandoverTab = "outgoing";
      renderFarmerHandoverPanels();
    });
  }
  const tabFarmerIncoming = $("tab-farmer-incoming");
  if (tabFarmerIncoming) {
    tabFarmerIncoming.addEventListener("click", () => {
      activeFarmerHandoverTab = "incoming";
      renderFarmerHandoverPanels();
    });
  }
  const btnCheckRejected = $("btn-check-rejected");
  if (btnCheckRejected) {
    btnCheckRejected.addEventListener("click", async () => {
      await checkFarmerRejectedBatches(true);
      toast("Đã kiểm tra phản hồi từ chối cho các lô trên trang.", "info");
    });
  }
  const farmerOutgoingTbody = $("farmer-outgoing-table-body");
  if (farmerOutgoingTbody) {
    farmerOutgoingTbody.addEventListener("click", handleTableAction);
  }
  const farmerRejectedTbody = $("farmer-rejected-table-body");
  if (farmerRejectedTbody) {
    farmerRejectedTbody.addEventListener("click", handleTableAction);
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

  // Quản lý sản phẩm
  const btnOpenAddProduct = $("btn-open-add-product");
  if (btnOpenAddProduct) {
    btnOpenAddProduct.addEventListener("click", () => {
      if (!requireUiAction("PRODUCT_CREATE")) return;
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

  // Tìm kiếm lô (Debounce 300ms) & Bộ lọc sản phẩm
  const batchSearchInput = $("batch-search-input");
  if (batchSearchInput) {
    batchSearchInput.addEventListener("input", onBatchSearchInput);
  }
  const batchFilterProduct = $("batch-filter-product");
  if (batchFilterProduct) {
    batchFilterProduct.addEventListener("change", () => { batchPage = 1; clearMergeSelectionWithNotice(); loadBatches(); });
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

  // Cán bộ kiểm tra Inspector
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

  // Modal Timeline dọc
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
  // Checkbox chọn lô & Gộp lô
  const batchSelectAll = $("batch-select-all");
  if (batchSelectAll) {
    batchSelectAll.addEventListener("change", (e) => {
      const checked = e.target.checked;
      selectedBatchIds.clear();
      if (checked) {
        batches.forEach((b) => {
          if (isBatchEligibleForMerge(b)) selectedBatchIds.add(b.id);
        });
      }
      document.querySelectorAll(".batch-select-checkbox:not(:disabled)").forEach((cb) => {
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

  // SCRUM-77 S-40: Sự kiện Chuyến xe lạnh
  const btnRefreshTrips = $("btn-refresh-trips");
  if (btnRefreshTrips) {
    btnRefreshTrips.addEventListener("click", () => loadColdTrips());
  }

  const btnOpenCreateTrip = $("btn-open-create-trip-modal");
  if (btnOpenCreateTrip) {
    btnOpenCreateTrip.addEventListener("click", openCreateTripModal);
  }

  const btnCloseCreateTrip = $("btn-close-create-trip");
  if (btnCloseCreateTrip) {
    btnCloseCreateTrip.addEventListener("click", () => {
      $("modal-create-trip").hidden = true;
    });
  }

  const btnCancelCreateTrip = $("btn-cancel-create-trip");
  if (btnCancelCreateTrip) {
    btnCancelCreateTrip.addEventListener("click", () => {
      $("modal-create-trip").hidden = true;
    });
  }

  const modalCreateTrip = $("modal-create-trip");
  if (modalCreateTrip) {
    modalCreateTrip.addEventListener("click", (e) => {
      if (e.target === modalCreateTrip) modalCreateTrip.hidden = true;
    });
  }

  const createTripForm = $("create-trip-form");
  if (createTripForm) {
    createTripForm.addEventListener("submit", handleCreateTripSubmit);
  }

  const btnCloseTripDetail = $("btn-close-trip-detail");
  if (btnCloseTripDetail) {
    btnCloseTripDetail.addEventListener("click", () => {
      $("modal-trip-detail").hidden = true;
    });
  }

  const btnDismissTripDetail = $("btn-dismiss-trip-detail");
  if (btnDismissTripDetail) {
    btnDismissTripDetail.addEventListener("click", () => {
      $("modal-trip-detail").hidden = true;
    });
  }

  const modalTripDetail = $("modal-trip-detail");
  if (modalTripDetail) {
    modalTripDetail.addEventListener("click", (e) => {
      if (e.target === modalTripDetail) modalTripDetail.hidden = true;
    });
  }

  const btnCompleteTripAction = $("btn-complete-trip-action");
  if (btnCompleteTripAction) {
    btnCompleteTripAction.addEventListener("click", () => {
      const tripId = btnCompleteTripAction.dataset.tripId;
      if (tripId) handleCompleteTrip(Number(tripId));
    });
  }

  const tripsTableBody = $("trips-table-body");
  if (tripsTableBody) {
    tripsTableBody.addEventListener("click", (e) => {
      const viewBtn = e.target.closest(".btn-view-trip");
      if (viewBtn && viewBtn.dataset.tripId) {
        openTripDetailModal(Number(viewBtn.dataset.tripId));
        return;
      }
      const completeBtn = e.target.closest(".btn-complete-trip");
      if (completeBtn && completeBtn.dataset.tripId) {
        handleCompleteTrip(Number(completeBtn.dataset.tripId));
        return;
      }
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
  batch_code: " Mã lô",
  product_name: " Sản phẩm",
  quantity: "⚖ Khối lượng",
  initial_quantity: "⚖ Khối lượng ban đầu",
  temperature: " Nhiệt độ (°C)",
  note: " Ghi chú",
  description: " Mô tả",
  message: " Thông điệp",
  location: " Vị trí",
  step: " Bước",
  from_org: " Từ tổ chức",
  to_org: " Đến tổ chức",
  total_quantity: "⚖ Tổng khối lượng",
  quantity_taken: "⚖ Khối lượng nhận",
  total_split_quantity: "⚖ Tổng khối lượng tách",
  harvest_date: " Ngày thu hoạch",
  parent_batch_code: " Mã lô nguồn",
  merged_batch_code: " Mã lô gộp",
  trip_code: " Mã chuyến xe",
  container_code: " Thùng lạnh",
  vehicle_plate: " Biển số xe",
  driver_name: " Tài xế",
};

/**
 * Dựng phần thân thẻ sự kiện theo nghiệp vụ:
 * - MERGE / EXPORT_MERGE: sản phẩm, tổng khối lượng (số lớn) và danh sách lô nguồn.
 * - SPLIT / GENESIS_SPLIT: khối lượng tách, lô gốc và danh sách lô con mới sinh.
 * - Bàn giao / Thu hoạch: tóm tắt tổ chức, sản phẩm, khối lượng…
 * Tuyệt đối KHÔNG in khối JSON thô.
 */
function renderTimelineBody(evt, p) {
  const type = String(evt.event_type || "").toUpperCase();
  const fallbackDesc = evt.event_data || p.description || p.note || p.message || "";

  if (type === "TRIP_DISPATCH" || type === "TRIP_DELIVER") {
    const isDispatch = type === "TRIP_DISPATCH";
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label"> Mã chuyến xe</span>
          <strong>${escapeHtml(p.trip_code || "—")}</strong>
        </div>
        <div class="tl-metric">
          <span class="tl-metric__label"> Thùng lạnh</span>
          <code>${escapeHtml(p.container_code || "—")}</code>
        </div>
        ${p.vehicle_plate ? `
        <div class="tl-metric">
          <span class="tl-metric__label"> Biển số xe</span>
          <strong>${escapeHtml(p.vehicle_plate)}</strong>
        </div>` : ""}
        ${p.driver_name ? `
        <div class="tl-metric">
          <span class="tl-metric__label"> Tài xế</span>
          <strong>${escapeHtml(p.driver_name)}</strong>
        </div>` : ""}
      </div>
      <div class="tl-note" style="margin-top: 6px;">
        ${isDispatch ? "Lô hàng được xếp lên thùng lạnh và bắt đầu vận chuyển giám sát nhiệt độ." : "Lô hàng đã kết thúc vận chuyển và dỡ khỏi thùng lạnh an toàn."}
      </div>`;
  }

  if (type === "MERGE") {
    const parents = Array.isArray(p.parent_batches) ? p.parent_batches : [];
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label"> Sản phẩm</span>
          <strong>${escapeHtml(p.product_name || "—")}</strong>
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label">⚖ Tổng khối lượng</span>
          <span class="tl-weight-big">${formatNumber(p.total_quantity)}<span class="tl-unit">${escapeHtml(p.unit || "kg")}</span></span>
        </div>
      </div>
      <div class="tl-source-title"> Các lô nguồn tham gia gộp (${parents.length})</div>
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
          <span class="tl-metric__label"> Lô gộp nhận hàng</span>
          ${batchCodeBadge(p.merged_batch_code || (p.merged_batch_id != null ? "#" + p.merged_batch_id : "—"))}
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label">⚖ Khối lượng đóng góp</span>
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
          <span class="tl-metric__label"> Lô gốc (lô mẹ được tách)</span>
          ${batchCodeBadge(currentDetailBatchCode || (evt.batch_id != null ? "#" + evt.batch_id : "—"))}
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label"> Khối lượng tách</span>
          <span class="tl-weight-big">${formatNumber(p.total_split_quantity)}<span class="tl-unit">${escapeHtml(p.unit || "kg")}</span></span>
        </div>
      </div>
      <div class="tl-source-title"> Các lô con mới sinh (${codes.length})</div>
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
          <span class="tl-metric__label"> Lô gốc</span>
          ${batchCodeBadge(p.parent_batch_code || (p.parent_batch_id != null ? "#" + p.parent_batch_id : "—"))}
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label"> Khối lượng tách</span>
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
          <span class="tl-metric__label"> Từ tổ chức</span>
          <strong>${escapeHtml(from)}</strong>
        </div>
        <div class="tl-metric">
          <span class="tl-metric__label"> Đến tổ chức</span>
          <strong>${escapeHtml(to)}</strong>
        </div>
      </div>
      ${note ? `<div class="tl-note">${escapeHtml(note)}</div>` : ""}`;
  }

  if (type === "HARVEST") {
    return `
      <div class="tl-summary">
        <div class="tl-metric">
          <span class="tl-metric__label"> Sản phẩm</span>
          <strong>${escapeHtml(p.product_name || "—")}</strong>
        </div>
        <div class="tl-metric">
          <span class="tl-metric__label"> Mã lô</span>
          ${batchCodeBadge(p.batch_code || (evt.batch_id != null ? "#" + evt.batch_id : "—"))}
        </div>
        <div class="tl-metric tl-metric--weight">
          <span class="tl-metric__label">⚖ Khối lượng thu hoạch</span>
          <span class="tl-weight-big">${formatNumber(p.initial_quantity)}<span class="tl-unit">${escapeHtml(p.unit || "kg")}</span></span>
        </div>
      </div>`;
  }

  // Mặc định: hiển thị mô tả + bảng khóa/giá trị thân thiện (không bao giờ in JSON thô).
  const rows = [];
  Object.keys(p || {}).forEach((key) => {
    if (key === "event_type" || !Object.hasOwn(TL_PAYLOAD_LABELS,key)) return;
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
  return (desc + table) || `<div class="tl-note">${escapeHtml(formatEventType(type))}.</div>`;
}

/** Vẽ dòng sự kiện trong Timeline HTML (Tab 2 - S-25). */
function renderTimelineItemHtml(evt) {
  const type = String(evt.event_type || "").toUpperCase();
  const typeClass = type.toLowerCase().replace(/_/g, "-");
  const eventLabel = formatEventType(type);

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
          <strong>Người thực hiện:</strong> ${escapeHtml(actor)}${orgName ? ` ·  ${escapeHtml(orgName)}` : ""}
        </div>
        <div class="timeline-item__body">${renderTimelineBody(evt, payload)}</div>
        <div class="hash-row">
          <span class="hash-row__label">Mã xác thực</span>
          <code class="hash-row__code" title="${escapeHtml(fullHash || "Không có mã băm")}">${escapeHtml(shortenHash(fullHash))}</code>
          <button type="button" class="hash-copy-btn" data-hash="${escapeHtml(fullHash)}" title="Sao chép mã băm đầy đủ" aria-label="Sao chép mã băm đầy đủ"> Sao chép</button>
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

/** Hiển thị modal QR truy xuất; không tự tải ảnh xuống. */
let currentBatchQrObjectUrl = null;
async function showBatchQrModal() {
  const batchId = currentDetailBatchId;
  if (!batchId || !session) { toast("Vui lòng đăng nhập và mở chi tiết một lô trước.", "error"); return; }
  const modal = $("modal-batch-qr");
  const image = $("batch-qr-image");
  const statusEl = $("batch-qr-status");
  const urlEl = $("batch-qr-url");
  const download = $("btn-download-batch-qr");
  modal.hidden = false;
  image.hidden = true; statusEl.hidden = false; statusEl.textContent = "Đang tải mã QR...";
  urlEl.textContent = ""; urlEl.removeAttribute("href"); download.disabled = true;
  $("batch-qr-product").textContent = ""; $("batch-qr-code").textContent = "";
  try {
    const infoResponse = await fetch(`${API_BASE_URL}/batches/${encodeURIComponent(batchId)}/qr-info`, {credentials:"include", headers:{"X-Requested-With":"XMLHttpRequest"}});
    if (!infoResponse.ok) {
      let message = "Không thể tải thông tin QR.";
      try { const data = await infoResponse.json(); if (typeof data.detail === "string") message = data.detail; } catch (_) {}
      throw new Error(message);
    }
    const info = await infoResponse.json();
    const qrResponse = await fetch(`${API_BASE_URL}/batches/${encodeURIComponent(batchId)}/qr`, {credentials:"include", headers:{"X-Requested-With":"XMLHttpRequest"}});
    if (!qrResponse.ok) {
      let message = "Không thể tạo mã QR.";
      try { const data = await qrResponse.json(); if (typeof data.detail === "string") message = data.detail; } catch (_) {}
      throw new Error(message);
    }
    const blob = await qrResponse.blob();
    if (!blob.type.includes("image/png")) throw new Error("API không trả về ảnh PNG hợp lệ.");
    if (currentBatchQrObjectUrl) URL.revokeObjectURL(currentBatchQrObjectUrl);
    currentBatchQrObjectUrl = URL.createObjectURL(blob);
    image.src = currentBatchQrObjectUrl; image.hidden = false;
    $("batch-qr-product").textContent = info.product_name || "Nông sản";
    $("batch-qr-code").textContent = `Mã lô: ${info.batch_code}`;
    urlEl.href = info.trace_url; urlEl.textContent = info.trace_url;
    statusEl.hidden = true; download.disabled = false;
    download.onclick = () => {
      const a = document.createElement("a"); a.href = currentBatchQrObjectUrl;
      a.download = `QR-${String(info.batch_code).replace(/[^a-zA-Z0-9_-]/g, "_")}.png`;
      document.body.appendChild(a); a.click(); a.remove();
    };
  } catch (error) {
    statusEl.textContent = error.message || "Đã xảy ra lỗi khi tải mã QR.";
    statusEl.hidden = false; toast(`Không thể hiển thị QR: ${statusEl.textContent}`, "error");
  }
}
function closeBatchQrModal() {
  const modal = $("modal-batch-qr"); if (modal) modal.hidden = true;
  if (currentBatchQrObjectUrl) { URL.revokeObjectURL(currentBatchQrObjectUrl); currentBatchQrObjectUrl = null; }
}

/** Mở modal chi tiết lô trung tâm 3 Tab (S-25: T-58, T-59) */
async function openBatchDetailsModal(batchId) {
  currentDetailBatchId = batchId;
  const qrButton = $("btn-detail-qr-download");
  if (qrButton && !qrButton.dataset.qrBound) {
    qrButton.dataset.qrBound = "true";
    qrButton.addEventListener("click", showBatchQrModal);
  }
  const modal = $("modal-batch-details");
  if (!modal) return;
  modal.hidden = false;
  switchDetailTab("overview");
  await loadDetailOverview(batchId);
}

/** Chuyển đổi giữa 3 Tab trong màn hình chi tiết lô */
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

/** Tab 1: Tải thông tin tổng quan của lô */
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

    // Kiểm tra trạng thái chờ bàn giao: ưu tiên cờ tổng hợp từ backend
    const isPending = Boolean(b.is_pending) || Boolean(data.has_pending_handover) || (data.pending_handover != null);
    const pendingBanner = $("detail-pending-banner");
    if (pendingBanner) pendingBanner.hidden = !isPending;

    const actionGroup = $("detail-action-buttons-group");
    if (actionGroup) {
      // Ẩn các nút nghiệp vụ nếu lô đang chờ duyệt bàn giao
      actionGroup.hidden = isPending;
    }

    if (!session || currentDetailBatchId !== batchId) return;
    const isHolder = batchIsHeld(b);

    // Ưu tiên cờ nghiệp vụ tổng hợp từ backend (đã tính cả chờ bàn giao, trạng thái, khối lượng)
    const handoverAllowed = window.canHandover();
    const splitAllowed = window.canSplit();
    const canHandover = handoverAllowed && isHolder && !batchIsRecalled(b) && ["ACTIVE", "SPLIT"].includes(b.status) && ((data.can_handover !== undefined)
      ? data.can_handover
      : (!isPending && isHolder && b.remaining_quantity > 0));
    const canSplit = splitAllowed && isHolder && !batchIsRecalled(b) && ["ACTIVE", "SPLIT"].includes(b.status) && ((data.can_split !== undefined)
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

    const canConsumeAction = canConsume() && isHolder && !batchIsRecalled(b) && !isPending && ["ACTIVE", "SPLIT"].includes(b.status) && Number(b.remaining_quantity) > 0 && data.can_consume !== false;

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
          <div><strong>Vị trí nguồn gốc:</strong> ${escapeHtml(data.plot?.location || "Chưa có dữ liệu")}</div>
          <div><strong>Vị trí hiện tại:</strong> ${escapeHtml(b.current_location ? [b.current_location_name, b.current_location].filter(Boolean).join(" · ") : "Chưa có dữ liệu")}</div>
          <div><strong>Đơn vị nắm giữ:</strong> <span class="badge badge--org"> ${escapeHtml(b.current_org_name || 'Tổ chức #' + b.current_org_id)}</span></div>
          <div><strong>Khối lượng ban đầu:</strong> ${formatNumber(b.initial_quantity)} ${escapeHtml(b.unit || "kg")}</div>
          <div><strong>Khối lượng còn lại:</strong> <strong style="color:var(--color-primary);">${formatNumber(b.remaining_quantity)} ${escapeHtml(b.unit || "kg")}</strong></div>
          <div><strong>Trạng thái:</strong> <span class="badge ${isPending ? 'badge--warning' : 'badge--ok'}">${escapeHtml(isPending ? 'Chờ duyệt bàn giao' : formatBatchStatus(b.status))}</span></div>
        </div>
      `;
    }

    window.recallUi?.renderBatchIncident?.();

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

/** Xác thực toàn vẹn toán học chuỗi Hash-Chain trong màn hình chi tiết */
async function verifyDetailChain(batchId, prefix = "detail") {
  const btn = $(`btn-${prefix}-verify-chain`);
  const idleText = prefix === "events" ? "Kiểm tra tính toàn vẹn" : " Xác thực toàn vẹn";
  setButtonLoading(btn, true, "Đang kiểm tra…", idleText);
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
    setHidden(`${prefix}-timeline-valid-banner`, true);
    setHidden(`${prefix}-timeline-alert-banner`, false);
    const text = $(`${prefix}-timeline-alert-text`);
    if (text) {
      text.textContent = `Lỗi kiểm tra toàn vẹn: ${err.message}`;
    }
    toast(`Kiểm tra toàn vẹn thất bại: ${err.message}`, "error");
  } finally {
    setButtonLoading(btn, false, "Đang kiểm tra…", idleText);
  }
}

/** Xác thực toàn diện tính toàn vẹn phả hệ dữ liệu truy xuất nguồn gốc (Story S-50) */
async function verifyTraceabilityIntegrity(batchId) {
  const btn = $("btn-traceability-verify-integrity");
  const idleText = "Kiểm tra tính toàn vẹn";
  if (btn) setButtonLoading(btn, true, "Đang kiểm tra…", idleText);
  try {
    const res = await apiRequest(`/batches/${batchId}/trace-integrity`);
    const isValid = Boolean(res.valid ?? res.is_valid);
    if (isValid) {
      setHidden("traceability-valid-banner", false);
      setHidden("traceability-alert-banner", true);
      const text = $("traceability-valid-text");
      if (text) {
        text.textContent = `✓ ${res.message || "Toàn bộ chuỗi truy xuất nguồn gốc toàn vẹn 100%."}`;
      }
      toast(res.message || "Toàn bộ chuỗi truy xuất nguồn gốc toàn vẹn 100%.", "success");
    } else {
      setHidden("traceability-valid-banner", true);
      setHidden("traceability-alert-banner", false);
      const text = $("traceability-alert-text");
      if (text) {
        text.textContent = `⚠ ${res.message || "Cảnh báo vi phạm toàn vẹn dữ liệu!"}`;
      }
      toast(`CẢNH BÁO: ${res.message}`, "error");
    }
    return res;
  } catch (err) {
    toast(`Lỗi xác thực toàn vẹn chuỗi truy xuất: ${err.message}`, "error");
    throw err;
  } finally {
    if (btn) setButtonLoading(btn, false, "Đang kiểm tra…", idleText);
  }
}
window.verifyTraceabilityIntegrity = verifyTraceabilityIntegrity;

/** Tab 3: Truy ngược cây phả hệ nguồn gốc BFS */
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
                <span></span>
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

/** Tab 3: Truy xuôi cây phả hệ hậu duệ BFS */
async function loadDetailLineageForward(batchId) {
  const requestId = ++forwardLineageRequest;
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
    if (!session || currentDetailBatchId !== batchId || currentLineageMode !== "forward" || requestId !== forwardLineageRequest) return;

    // 1. Điểm cuối chuỗi cung ứng & Đã tiêu thụ (Terminal batches)
    const termList = $("detail-terminal-batches-list");
    if (termList) {
      if (data.terminal_batches && data.terminal_batches.length > 0) {
        termList.innerHTML = data.terminal_batches.map(t => {
          const code = t.code || `#${t.batch_id}`;
          const isConsumed = Boolean(t.is_consumed || t.status === "CONSUMED");
          const orgName = t.current_org_name || (t.current_org_id ? `Tổ chức #${t.current_org_id}` : "—");
          const loc = t.location || "Chưa xác định";
          const remQty = t.remaining_quantity == null ? null : Number(t.remaining_quantity);
          return `
            <div class="root-batch-item" style="border: 1px solid ${isConsumed ? '#cbd5e1' : '#f59e0b'}; background: ${isConsumed ? '#f8fafc' : '#fffbeb'};">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span class="lineage-node-code">${escapeHtml(code)}</span>
                ${isConsumed
                  ? '<span class="badge" style="background:#64748b; color:#fff; font-size:0.75rem;"> ĐÃ TIÊU THỤ</span>'
                  : '<span class="badge badge--warning" style="font-size:0.75rem;"> ĐIỂM CUỐI</span>'
                }
              </div>
              <div style="font-size:0.88rem; color:#334155; line-height:1.4;">
                <div><strong>Đơn vị giữ:</strong> ${escapeHtml(orgName)}</div>
                <div><strong>Vị trí nguồn gốc:</strong> ${escapeHtml(loc)}</div>
                <div><strong>Vị trí hiện tại:</strong> ${escapeHtml(t.current_location ? [t.current_location_name, t.current_location].filter(Boolean).join(" · ") : "Chưa có dữ liệu")}</div>
                <div><strong>Sản phẩm:</strong> ${escapeHtml(t.product_name || "—")}</div>
                <div><strong>Khối lượng còn:</strong> <strong style="color:${isConsumed ? '#64748b' : '#d97706'};">${remQty == null ? "Chưa có dữ liệu" : formatNumber(remQty) + " " + escapeHtml(t.unit || "kg")}</strong></div>
              </div>
            </div>
          `;
        }).join("");
      } else {
        termList.innerHTML = `<em style="color:var(--color-text-muted);">Không có điểm cuối phả hệ.</em>`;
      }
    }

    // S-28: render the DAG from authorized API edges, never inferred parents.
    const graph = $("detail-forward-graph");
    if (graph && window.AgriLineage) window.AgriLineage.mount(graph, data);
    const legacyLevels = $("detail-forward-levels-container");
    if (legacyLevels) legacyLevels.replaceChildren();

    if (loading) loading.hidden = true;
    if (forwardBody) forwardBody.hidden = false;
  } catch (err) {
    if (session && currentDetailBatchId === batchId && currentLineageMode === "forward" && requestId === forwardLineageRequest && loading) {
      loading.textContent = `Lỗi truy xuôi nguồn gốc: ${err.message}`;
    }
  }
}

/** Ghi nhận lô nông sản đã bán hết cho người tiêu dùng (CONSUMED - S-29) */
async function handleConsumeBatch(batchId, batchCode) {
  if (!requireBatchAction(batches.find(b => b.id === batchId), "BATCH_CONSUME")) return;
  const codeStr = batchCode || `#${batchId}`;
  if (!await confirmAction(`Xác nhận lô ${codeStr} đã bán hết cho người tiêu dùng?\n\n- Khối lượng còn lại sẽ chuyển về 0\n- Trạng thái chuyển sang ĐÃ TIÊU THỤ\n- Không thể hoàn tác hoặc tiếp tục bàn giao/tách/gộp.`)) {
    return;
  }
  const btn = $("btn-detail-consume");
  setButtonLoading(btn, true, "Đang xử lý…", "Đã bán hết");
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
    setButtonLoading(btn, false, "Đang xử lý…", "Đã bán hết");
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

  if (!requireBatchAction(batch, "SPLIT")) return;
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

/** Tính tổng khối lượng các lô con và kiểm tra vượt quá lô mẹ theo thời gian thực */
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
      errorMsg.textContent = " Vui lòng nhập khối lượng lớn hơn 0 cho tất cả các lô con!";
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
      errorMsg.textContent = ` Vượt quá khối lượng còn lại của lô mẹ! (Tổng con: ${formatNumber(total)} ${unit} > Lô mẹ: ${formatNumber(maxRemaining)} ${unit})`;
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

/** Gửi request tách lô POST /batches/{id}/split */
async function handleSplitSubmit(event) {
  event.preventDefault();
  if (!requireBatchAction(currentSplitBatch, "SPLIT")) return;
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

/** Hiển thị danh sách mã lô con vừa tạo với cỡ chữ lớn 24px+ kèm nút sao chép */
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
               Lô con #${index + 1} (${escapeHtml(c.product_name || "Nông sản")})
            </div>
            <div class="code-display-huge" style="font-size:1.65rem; font-family:'Cascadia Mono', Consolas, monospace; font-weight:800; padding:10px 18px; margin:4px 0 8px 0; display:inline-block; letter-spacing:2px; background:#0f172a; color:#facc15; border-radius:8px;">
              ${escapeHtml(code)}
            </div>
            <div style="font-size:0.95rem; color:#475569;">
              Khối lượng ban đầu: <strong style="color:#0f172a; font-weight:700;">${formatNumber(qty)} ${escapeHtml(unit)}</strong>
            </div>
          </div>
          <button class="btn btn--sm btn--primary" type="button" style="white-space:nowrap; padding:10px 16px; font-weight:600; display:inline-flex; align-items:center; gap:6px;" onclick="copyText('${escapeHtml(code)}')">
             Sao chép mã
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
  if (selectedBatches.some(b => !requireBatchAction(b, "MERGE"))) return;
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
    errorEl.textContent = ` ${errMsg || 'Vui lòng kiểm tra lại khối lượng'}`;
    errorEl.hidden = false;
    submitBtn.disabled = true;
  } else {
    calcBox.classList.remove("is-invalid");
    errorEl.hidden = true;
    submitBtn.disabled = false;
  }
}

/** Gửi request gộp lô POST /batches/merge */
async function handleMergeSubmit(event) {
  event.preventDefault();
  if (!requireUiAction("MERGE")) return;
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

  if (items.some(item => !requireBatchAction(batches.find(b => b.id === item.parent_batch_id), "MERGE"))) return;
  if (items.some(item => batches.find(b => b.id === item.parent_batch_id)?.product_id !== productId)) { toast("Các lô phải cùng sản phẩm.", "error"); return; }
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

/** Hiển thị popup thành công gộp lô với cỡ chữ lớn 24px+ */
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
  const actor = session;
  dataLoadState.organizations = "loading";
  try {
    const data = await apiRequest("/organizations");
    if (actor !== session) return;
    dataLoadState.organizations = "ready";
    organizations = Array.isArray(data) ? data : [];
  } catch (error) {
    if (actor !== session) return;
    dataLoadState.organizations = dataErrorState(error); organizations = [];
    toast(`Không tải được tổ chức: ${error.message}`, "error");
  }
}

/** GET /handovers/pending -> danh sách bàn giao gửi đến tổ chức của user */
async function loadPendingHandovers() {
  const actor = session;
  dataLoadState.pending = "loading"; renderStats();
  if (!hasUiAction("HANDOVER_RESPOND")) {
    dataLoadState.pending = "idle";
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
    toast(`Không tải được yêu cầu tiếp nhận: ${error.message}`, "error");
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
        ? '<span class="badge badge--overdue" title="Đã quá hạn xác nhận 48 giờ"> Quá hạn 48h</span>'
        : '<span class="badge badge--ok" style="font-size:0.8rem;">Trong hạn</span>';

      return `
      <tr class="${isOverdue ? 'is-overdue-row' : ''}">
        <td class="id-cell">${escapeHtml(h.batch_code || `#${h.batch_id}`)}</td>
        <td><strong>${escapeHtml(productName)}</strong></td>
        <td class="is-right">${formatNumber(h.batch_quantity)} ${escapeHtml(h.batch_unit || "kg")}</td>
        <td><span class="badge badge--org"> ${escapeHtml(fromOrg)}</span></td>
        <td>${escapeHtml(formatDateTime(h.created_at))}</td>
        <td>${overdueBadge}</td>
        <td>${escapeHtml(note)}</td>
        <td class="is-center">
          <div class="table__actions" style="justify-content: center;">
            ${handoverResponseAllowed(h) ? `
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

  const isFarmer = session?.role === "farmer";
  const outgoingPending = batches.filter(b => b.is_pending || b.pending_handover);

  const countBadge = $("badge-pending-count");
  if (countBadge) {
    if (isFarmer) {
      countBadge.textContent = `${outgoingPending.length} lô đang chờ`;
      countBadge.className = outgoingPending.length > 0 ? "badge badge--warning" : "badge badge--muted";
    } else {
      countBadge.textContent = `${pendingHandovers.length} lô`;
      countBadge.className = pendingHandovers.length > 0 ? "badge badge--warning" : "badge badge--muted";
    }
  }
  const navPending = $("nav-pending");
  if (navPending && canHandover()) {
    const badgeText = isFarmer
      ? (outgoingPending.length > 0 ? `<span class="sidebar-count-badge">${outgoingPending.length}</span>` : "")
      : (pendingHandovers.length > 0 ? `<span class="sidebar-count-badge">${pendingHandovers.length}</span>` : "");
    updateSidebarNavItem(navPending, "pending", isFarmer ? "Theo dõi bàn giao" : "Tiếp nhận bàn giao", badgeText);
  }
  const statPending = $("stat-pending-handovers");
  if (statPending) {
    statPending.textContent = formatNumber(isFarmer ? outgoingPending.length : pendingHandovers.length);
  }
  const emptyEl = $("pending-handovers-empty");
  if (emptyEl) {
    emptyEl.hidden = pendingHandovers.length > 0;
    if (dataLoadState.pending === "ready") {
      if (isPackingUser()) {
        emptyEl.innerHTML = `
          <strong>Hiện chưa có yêu cầu bàn giao nào gửi đến HTX Tân Cương.</strong><br>
          <span style="font-size:0.875rem; color:#64748b; display:inline-block; margin-top:4px;">
            ℹ Trong luồng chuỗi cung ứng miền Bắc, HTX Tân Cương (Org 1) là đơn vị khởi tạo nguồn nông sản. Khi có lô hàng từ tổ chức đối tác khác chuyển giao đến HTX, yêu cầu sẽ hiển thị tại đây để bạn xác nhận tiếp nhận hoặc từ chối.
          </span>`;
      } else if (session?.role === "processor") {
        emptyEl.innerHTML = `
          <strong>Hiện chưa có yêu cầu bàn giao nào gửi đến đơn vị của bạn.</strong><br>
          <span style="font-size:0.875rem; color:#64748b; display:inline-block; margin-top:4px;">
            ℹ Danh sách các lô nông sản do đối tác chuyển giao đến cơ sở tiếp nhận & chế biến để bạn xác nhận tiếp nhận hoặc từ chối.
          </span>`;
      } else {
        emptyEl.textContent = "Hiện không có lô hàng nào đang chờ tổ chức của bạn xác nhận tiếp nhận.";
      }
    } else {
      emptyEl.textContent = dataStateText(dataLoadState.pending);
    }
  }
  renderFarmerHandoverPanels();
  renderStats();
}

/** Vẽ các panel và bảng theo dõi bàn giao dành riêng cho Farmer */
function renderFarmerHandoverPanels() {
  const isFarmer = session?.role === "farmer";

  // Bỏ thanh chuyển tab vì:
  // - Farmer chỉ có một nội dung duy nhất là "Theo dõi bàn giao" (không sử dụng nhận bàn giao).
  // - Các vai trò khác (processor, transporter, distributor,...) sử dụng trực tiếp màn hình Tiếp nhận bàn giao gốc.
  setHidden("farmer-handover-tabs", true);

  if (!isFarmer) {
    setHidden("panel-farmer-outgoing", true);
    setHidden("panel-incoming-handovers", false);
    return;
  }

  // Đối với Farmer: Ẩn hoàn toàn giao diện tiếp nhận bàn giao, chỉ hiển thị màn hình Theo dõi bàn giao
  setHidden("panel-farmer-outgoing", false);
  setHidden("panel-incoming-handovers", true);

  // Vẽ bảng lô đã gửi đang chờ xác nhận
  const outgoingPending = batches.filter(b => b.is_pending || b.pending_handover);
  const outgoingTbody = $("farmer-outgoing-table-body");
  const outgoingEmpty = $("farmer-outgoing-empty");
  const outgoingWrap = $("farmer-outgoing-table-wrap");

  if (outgoingTbody) {
    outgoingTbody.innerHTML = outgoingPending.map(b => {
      const toOrgId = b.pending_handover?.to_org_id;
      const targetOrg = organizations.find(o => o.id === toOrgId);
      const toOrgName = targetOrg ? targetOrg.name : (toOrgId ? `Tổ chức #${toOrgId}` : "Chưa xác định");
      const createdAt = b.pending_handover?.created_at;
      const isOverdue = b.pending_handover?.is_overdue || checkIsOverdue(createdAt);
      const overdueBadge = isOverdue
        ? '<span class="badge badge--overdue" title="Đã quá 48 giờ chưa được xác nhận"> Quá hạn 48h</span>'
        : '<span class="badge badge--warning"> Đang chờ xác nhận</span>';
      const qtyStr = `${formatNumber(b.remaining_quantity ?? b.quantity)} ${escapeHtml(b.unit || "kg")}`;

      return `
        <tr class="${isOverdue ? 'is-overdue-row' : ''}">
          <td class="id-cell"><strong>${escapeHtml(b.code || `#${b.id}`)}</strong></td>
          <td><strong>${escapeHtml(b.product_name || "Nông sản")}</strong></td>
          <td class="is-right">${qtyStr}</td>
          <td><span class="badge badge--org"> ${escapeHtml(toOrgName)}</span></td>
          <td>${escapeHtml(formatDateTime(createdAt))}</td>
          <td>${overdueBadge}</td>
          <td class="is-center">
            <div class="table__actions" style="justify-content: center; gap: 4px;">
              <button class="btn btn--light btn--sm" type="button" data-action="farmer-view-detail" data-id="${escapeHtml(b.id)}" title="Xem chi tiết lô">
                 Chi tiết
              </button>
              <button class="btn btn--light btn--sm" type="button" data-action="farmer-view-history" data-id="${escapeHtml(b.id)}" title="Xem lịch sử sự kiện">
                 Lịch sử
              </button>
            </div>
          </td>
        </tr>`;
    }).join("");
  }

  if (outgoingEmpty && outgoingWrap) {
    outgoingEmpty.hidden = outgoingPending.length > 0;
    outgoingWrap.hidden = outgoingPending.length === 0;
  }

  renderFarmerRejectedTable();
}

/** Vẽ bảng danh sách lô bị từ chối tiếp nhận */
function renderFarmerRejectedTable() {
  const rejectedTbody = $("farmer-rejected-table-body");
  const rejectedEmpty = $("farmer-rejected-empty");
  const rejectedWrap = $("farmer-rejected-table-wrap");
  if (!rejectedTbody) return;

  if (farmerRejectedBatchesCache.length === 0) {
    rejectedTbody.innerHTML = "";
    if (rejectedWrap) rejectedWrap.hidden = true;
    if (rejectedEmpty) rejectedEmpty.hidden = false;
    return;
  }

  rejectedTbody.innerHTML = farmerRejectedBatchesCache.map(item => {
    const b = item.batch;
    const targetOrg = organizations.find(o => o.id === item.toOrgId);
    const orgName = targetOrg ? targetOrg.name : (item.toOrgId ? `Tổ chức #${item.toOrgId}` : "Bên nhận");
    const qtyStr = `${formatNumber(b.remaining_quantity ?? b.quantity)} ${escapeHtml(b.unit || "kg")}`;

    return `
      <tr>
        <td class="id-cell"><strong>${escapeHtml(b.code || `#${b.id}`)}</strong></td>
        <td><strong>${escapeHtml(b.product_name || "Nông sản")}</strong></td>
        <td class="is-right">${qtyStr}</td>
        <td><span class="badge badge--org"> ${escapeHtml(orgName)}</span></td>
        <td>${escapeHtml(formatDateTime(item.rejectedAt))}</td>
        <td><div style="color:#b91c1c; font-weight:600; max-width:240px; word-break:break-word;"> ${escapeHtml(item.rejectReason)}</div></td>
        <td class="is-center">
          <div class="table__actions" style="justify-content: center; gap: 4px;">
            <button class="btn btn--light btn--sm" type="button" data-action="farmer-view-detail" data-id="${escapeHtml(b.id)}" title="Xem chi tiết lô">
               Chi tiết
            </button>
            <button class="btn btn--light btn--sm" type="button" data-action="farmer-view-history" data-id="${escapeHtml(b.id)}" title="Xem lịch sử sự kiện">
               Lịch sử
            </button>
            <button class="btn btn--primary btn--sm" type="button" data-action="farmer-re-handover" data-id="${escapeHtml(b.id)}" title="Bàn giao lại hoặc chuyển đối tác khác">
               Bàn giao lại
            </button>
            <button class="btn btn--light btn--sm" type="button" data-action="farmer-split" data-id="${escapeHtml(b.id)}" title="Tách lô để phân loại">
               Tách lô
            </button>
          </div>
        </td>
      </tr>`;
  }).join("");

  if (rejectedWrap) rejectedWrap.hidden = false;
  if (rejectedEmpty) rejectedEmpty.hidden = true;
}

/** Kiểm tra phản hồi từ chối từ các lô đang giữ (giới hạn tối đa 5 lô trên trang hiện tại để chống quét không giới hạn) */
async function checkFarmerRejectedBatches(force = false) {
  if (session?.role !== "farmer") return;
  const currentVersion = ++farmerRejectedCheckVersion;
  // Bounded sample: tối đa 5 lô đang giữ không ở trạng thái pending
  const candidateBatches = batches.filter(b => !b.is_pending && b.status !== "CONSUMED").slice(0, 5);
  if (candidateBatches.length === 0) {
    farmerRejectedBatchesCache = [];
    renderFarmerRejectedTable();
    return;
  }

  try {
    const results = await Promise.allSettled(
      candidateBatches.map(async (b) => {
        const events = await apiRequest(`/batches/${b.id}/events`);
        if (!Array.isArray(events)) return null;
        const handoverEvents = events.filter(e =>
          ["HANDOVER_INIT", "HANDOVER_ACCEPT", "HANDOVER_REJECT"].includes(e.event_type)
        );
        if (handoverEvents.length === 0) return null;
        const lastEvent = handoverEvents[handoverEvents.length - 1];
        if (lastEvent.event_type === "HANDOVER_REJECT") {
          return {
            batch: b,
            event: lastEvent,
            rejectReason: lastEvent.payload?.reject_reason || lastEvent.event_data || "Không nêu rõ lý do",
            toOrgId: lastEvent.payload?.to_org_id,
            rejectedAt: lastEvent.timestamp || lastEvent.created_at,
          };
        }
        return null;
      })
    );
    if (currentVersion !== farmerRejectedCheckVersion || session?.role !== "farmer") return;
    farmerRejectedBatchesCache = results
      .filter(r => r.status === "fulfilled" && r.value !== null)
      .map(r => r.value);
    renderFarmerRejectedTable();
  } catch (err) {
    console.warn("Lỗi khi kiểm tra phản hồi từ chối:", err.message);
  }
}

/** Mở modal bàn giao lô hàng */
function openHandoverModal(batchId) {
  if (!canHandover()) { toast("Vai trò của bạn không có quyền bàn giao lô.", "error"); return; }
  const batch = batches.find((item) => item.id === batchId);
  if (!batch) {
    toast(`Không tìm thấy lô nông sản #${batchId}.`, "error");
    return;
  }

  if (!requireBatchAction(batch, "HANDOVER_INIT")) return;
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
  if (!requireBatchAction(batches.find(b => b.id === batchId), "HANDOVER_INIT")) return;
  if (toOrgId === session.organization_id) { toast("Không thể bàn giao cho chính tổ chức của bạn.", "error"); return; }

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
  if (!handoverResponseAllowed(pendingHandovers.find(h => h.id === handoverId))) { toast("Không có quyền phản hồi yêu cầu này.", "error"); return; }
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
  if (!handoverResponseAllowed(pendingHandovers.find(h => h.id === handoverId))) { toast("Yêu cầu không thuộc tổ chức tiếp nhận hoặc không còn chờ xử lý.", "error"); return; }
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
  if (!handoverResponseAllowed(pendingHandovers.find(h => h.id === handoverId))) { toast("Yêu cầu không thuộc tổ chức tiếp nhận hoặc không còn chờ xử lý.", "error"); return; }

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
  if (!handoverResponseAllowed(h, true)) { toast("Yêu cầu không đủ điều kiện tiếp nhận.", "error"); return; }
  const batchName = h ? (h.batch_product_name || `lô #${h.batch_id}`) : `lô hàng #${handoverId}`;
  const isOverdue = h && (h.is_overdue || checkIsOverdue(h.created_at));

  let confirmMsg = `Bạn có chắc chắn muốn xác nhận tiếp nhận ${batchName} về tổ chức của mình?`;
  if (isOverdue) {
    confirmMsg += `\n\n CẢNH BÁO: Lô hàng này ĐÃ QUÁ HẠN 48 GIỜ. Hệ thống vẫn cho phép xác nhận nhưng sự kiện tiếp nhận sẽ được ghi chú quá hạn để lưu vết minh bạch.`;
  }

  if (!await confirmAction(confirmMsg)) {
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
    $("farm-entry").open=false;
    renderFarms();
    toast("Đã huỷ chế độ sửa vùng trồng.", "info");
    return;
  }

  resetBatchForm();
  $("batch-entry").open=false;
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

  const details = button.closest("details.action-dropdown");
  if (details) details.removeAttribute("open");

  const id = Number(button.dataset.id);
  const entity = button.dataset.entity;
  const action = button.dataset.action;

  if (action === "view-details") {
    openBatchDetailsModal(id).then(() => {
      if (button.dataset.openLineage && currentDetailBatchId === id) switchDetailTab("lineage");
    });
    return;
  }

  if (action === "create-recall") {
    if (!canOpenScreen("recall-card")) { toast("Thu hồi chưa được mở trong bản demo này.", "info"); return; }
    const code = button.dataset.code;
    if (window.recallUi?.openCreate) {
      window.recallUi.openCreate(code || id);
    } else {
      toast("Chức năng thu hồi đang khởi tạo...", "info");
    }
    return;
  }

  if (action === "open-recall-section") {
    if (!canOpenScreen("recall-card")) return;
    window.location.hash = "#recall-card";
    const recallCard = $("recall-card");
    if (recallCard) {
      recallCard.scrollIntoView({ behavior: "smooth" });
    }
    return;
  }

  if (action === "split-batch") {
    if (!canSplit()) {
      toast("Vai trò của bạn không có quyền tách lô.", "error");
      return;
    }
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

  if (action === "farmer-view-detail") {
    openBatchDetailsModal(id);
    return;
  }

  if (action === "farmer-view-history") {
    openBatchDetailsModal(id).then(() => switchDetailTab("timeline"));
    return;
  }

  if (action === "farmer-re-handover") {
    openHandoverModal(id);
    return;
  }

  if (action === "farmer-split") {
    openSplitModal(id);
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
      if (!canUpdateBatch()) {
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

/* ------------------------------------------- SCRUM-77 S-40: Chuyến xe lạnh --- */
function canCreateTrip() {
  return session && ["transporter", "org_admin", "system_admin"].includes(session.role);
}

async function loadColdTrips() {
  const actor = session;
  if (!actor) return;
  try {
    const data = await apiRequest("/trips");
    if (actor !== session) return;
    coldTrips = Array.isArray(data) ? data : [];
    renderColdTripsTable();
  } catch (error) {
    if (actor !== session) return;
    console.error("Lỗi tải danh sách chuyến xe lạnh:", error);
    coldTrips = [];
    renderColdTripsTable();
  }
}

function renderColdTripsTable() {
  const tbody = $("trips-table-body");
  const emptyEl = $("trips-empty");
  const btnCreate = $("btn-open-create-trip-modal");
  if (!tbody) return;

  if (btnCreate) {
    btnCreate.hidden = !canCreateTrip();
  }

  if (!coldTrips.length) {
    tbody.innerHTML = "";
    if (emptyEl) emptyEl.hidden = false;
    return;
  }

  if (emptyEl) emptyEl.hidden = true;

  tbody.innerHTML = coldTrips.map(trip => {
    const isTransiting = trip.status === "IN_TRANSIT";
    const statusBadge = isTransiting
      ? '<span class="badge badge--warning" style="background:#e0f2fe; color:#0369a1; border-color:#bae6fd;">Đang vận chuyển</span>'
      : trip.status === "COMPLETED"
      ? '<span class="badge badge--ok">Hoàn thành</span>'
      : `<span class="badge">${escapeHtml(trip.status)}</span>`;

    const canComplete = isTransiting && canCreateTrip() && (isSystemAdmin() || trip.transporter_org_id === session?.organization_id);

    return `
      <tr>
        <td class="id-cell"><strong>${escapeHtml(trip.trip_code)}</strong></td>
        <td><code>${escapeHtml(trip.container_code)}</code></td>
        <td>
          <div>${escapeHtml(trip.vehicle_plate || "—")}</div>
          <small class="text-muted">${escapeHtml(trip.driver_name || "")}</small>
        </td>
        <td>
          <div style="font-size:0.9em;">Từ: ${escapeHtml(trip.start_location || "—")}</div>
          <div style="font-size:0.9em;">Đến: ${escapeHtml(trip.destination_location || "—")}</div>
        </td>
        <td class="is-center"><span class="badge">${trip.batch_count || 0}</span></td>
        <td>${escapeHtml(formatDateTime(trip.start_time))}</td>
        <td>${statusBadge}</td>
        <td class="is-right">
          <div class="table__actions" style="justify-content: flex-end; gap: 4px;">
            <button class="btn btn--light btn--sm btn-view-trip" type="button" data-trip-id="${trip.id}">Xem</button>
            ${canComplete ? `<button class="btn btn--success btn--sm btn-complete-trip" type="button" data-trip-id="${trip.id}">Xuống xe</button>` : ""}
          </div>
        </td>
      </tr>
    `;
  }).join("");
}

function openCreateTripModal() {
  if (!canCreateTrip()) {
    toast("Bạn không có quyền mở chuyến xe lạnh.", "error");
    return;
  }
  const form = $("create-trip-form");
  if (form) form.reset();

  const containerEl = $("create-trip-batches-list");
  if (!containerEl) return;

  const eligibleBatches = batches.filter(b => {
    const isOwner = isSystemAdmin() || b.current_org_id === session?.organization_id;
    const isActive = b.status === "ACTIVE" || b.status === "SPLIT";
    const hasQty = (b.remaining_quantity || b.quantity || 0) > 0;
    const notPending = !b.pending_handover;
    const notRecalled = !b.is_recalled;
    return isOwner && isActive && hasQty && notPending && notRecalled;
  });

  if (!eligibleBatches.length) {
    containerEl.innerHTML = `<p class="empty" style="padding: 12px;">Không có lô nông sản nào khả dụng để vận chuyển (cần thuộc tổ chức của bạn, trạng thái Hoạt động, chưa bàn giao).</p>`;
  } else {
    containerEl.innerHTML = eligibleBatches.map(b => `
      <label class="trip-batch-item" style="display: flex; align-items: center; gap: 8px; padding: 6px 4px; border-bottom: 1px solid var(--color-border-light, #eee); cursor: pointer;">
        <input type="checkbox" name="trip_batch_id" value="${b.id}" style="width: auto; margin: 0;" />
        <div>
          <strong>${escapeHtml(b.code)}</strong> · ${escapeHtml(b.product_name || "Sản phẩm")}
          <span class="text-muted" style="margin-left: 6px; font-size: 0.85em;">(${formatNumber(b.remaining_quantity || b.quantity)} ${escapeHtml(b.unit || "kg")})</span>
        </div>
      </label>
    `).join("");
  }

  $("modal-create-trip").hidden = false;
}

async function handleCreateTripSubmit(e) {
  e.preventDefault();
  if (!canCreateTrip()) {
    toast("Bạn không có quyền mở chuyến xe lạnh.", "error");
    return;
  }

  const containerCode = $("create-trip-container").value.trim();
  const tripCode = $("create-trip-code").value.trim() || undefined;
  const vehiclePlate = $("create-trip-plate").value.trim() || undefined;
  const driverName = $("create-trip-driver").value.trim() || undefined;
  const startLocation = $("create-trip-start").value.trim() || undefined;
  const destinationLocation = $("create-trip-dest").value.trim() || undefined;
  const notes = $("create-trip-notes").value.trim() || undefined;

  const checkedBoxes = document.querySelectorAll("#create-trip-batches-list input[name='trip_batch_id']:checked");
  const batchIds = Array.from(checkedBoxes).map(cb => Number(cb.value));

  if (!containerCode) {
    toast("Vui lòng nhập mã thùng lạnh.", "error");
    $("create-trip-container").focus();
    return;
  }

  if (batchIds.length === 0) {
    toast("Vui lòng chọn ít nhất 1 lô nông sản để gắn vào chuyến xe.", "error");
    return;
  }

  const payload = {
    container_code: containerCode,
    batch_ids: batchIds,
  };
  if (tripCode) payload.trip_code = tripCode;
  if (vehiclePlate) payload.vehicle_plate = vehiclePlate;
  if (driverName) payload.driver_name = driverName;
  if (startLocation) payload.start_location = startLocation;
  if (destinationLocation) payload.destination_location = destinationLocation;
  if (notes) payload.notes = notes;

  const submitBtn = $("btn-submit-create-trip");
  setButtonLoading(submitBtn, true, "Đang xử lý…", "Bắt đầu chuyến xe (Ghi nhận Lên xe)");

  try {
    const res = await apiRequest("/trips", {
      method: "POST",
      body: payload,
    });
    toast(`Mở chuyến ${res.trip_code} thành công! Đã ghi nhận Lên xe cho ${res.batches ? res.batches.length : batchIds.length} lô.`, "success");
    $("modal-create-trip").hidden = true;
    await loadColdTrips();
    await loadBatches();
  } catch (error) {
    toast(`Mở chuyến xe thất bại: ${error.message}`, "error");
  } finally {
    setButtonLoading(submitBtn, false, "Đang xử lý…", "Bắt đầu chuyến xe (Ghi nhận Lên xe)");
  }
}

async function openTripDetailModal(tripId) {
  try {
    const trip = await apiRequest(`/trips/${tripId}`);
    currentDetailTripId = trip.id;

    const summaryEl = $("trip-detail-header");
    if (summaryEl) {
      summaryEl.innerHTML = `
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px;">
          <div><strong>Mã chuyến:</strong> ${escapeHtml(trip.trip_code)}</div>
          <div><strong>Thùng lạnh:</strong> <code>${escapeHtml(trip.container_code)}</code></div>
          <div><strong>Biển số:</strong> ${escapeHtml(trip.vehicle_plate || "—")}</div>
          <div><strong>Tài xế:</strong> ${escapeHtml(trip.driver_name || "—")}</div>
          <div><strong>Lộ trình:</strong> ${escapeHtml(trip.start_location || "—")} ➔ ${escapeHtml(trip.destination_location || "—")}</div>
          <div><strong>Trạng thái:</strong> ${trip.status === "IN_TRANSIT" ? '<span class="badge badge--warning">Đang vận chuyển</span>' : trip.status === "COMPLETED" ? '<span class="badge badge--ok">Hoàn thành</span>' : escapeHtml(trip.status)}</div>
          <div><strong>Khởi hành:</strong> ${escapeHtml(formatDateTime(trip.start_time))}</div>
          <div><strong>Kết thúc:</strong> ${trip.end_time ? escapeHtml(formatDateTime(trip.end_time)) : "—"}</div>
        </div>
        ${trip.notes ? `<div style="margin-top: 8px; font-size: 0.9em;"><em>Ghi chú:</em> ${escapeHtml(trip.notes)}</div>` : ""}
      `;
    }

    const tbody = $("trip-detail-batches-body");
    if (tbody) {
      tbody.innerHTML = (trip.batches || []).map(b => `
        <tr>
          <td class="id-cell"><strong>${escapeHtml(b.batch_code)}</strong></td>
          <td>${escapeHtml(b.product_name || "—")}</td>
          <td class="is-right">${formatNumber(b.remaining_quantity)} ${escapeHtml(b.unit || "kg")}</td>
          <td>${escapeHtml(formatDateTime(b.attached_at))}</td>
          <td>${b.detached_at ? escapeHtml(formatDateTime(b.detached_at)) : '<span class="badge badge--warning">Đang trên xe</span>'}</td>
        </tr>
      `).join("");
    }

    const btnComplete = $("btn-complete-trip-action");
    if (btnComplete) {
      const isOwner = isSystemAdmin() || trip.transporter_org_id === session?.organization_id;
      btnComplete.hidden = !(trip.status === "IN_TRANSIT" && canCreateTrip() && isOwner);
      btnComplete.dataset.tripId = String(trip.id);
    }

    $("modal-trip-detail").hidden = false;
  } catch (error) {
    toast(`Không tải được chi tiết chuyến xe: ${error.message}`, "error");
  }
}

async function handleCompleteTrip(tripId) {
  if (!await confirmAction("Bạn có chắc chắn muốn hoàn thành chuyến xe và ghi nhận Xuống xe (TRIP_DELIVER) cho toàn bộ các lô nông sản trên chuyến này?")) {
    return;
  }

  try {
    const res = await apiRequest(`/trips/${tripId}/complete`, {
      method: "POST",
      body: {},
    });
    toast(`Chuyến ${res.trip_code} đã hoàn thành! Đã ghi nhận Xuống xe cho ${res.batches ? res.batches.length : 0} lô.`, "success");
    $("modal-trip-detail").hidden = true;
    await loadColdTrips();
    await loadBatches();
  } catch (error) {
    toast(`Không thể hoàn thành chuyến: ${error.message}`, "error");
  }
}

/** Tải dữ liệu dùng chung cho giao diện sau khi đăng nhập (theo phân quyền). */
async function loadAllData() {
  const actor = session;
  if (!actor) return;
  await checkHealth();
  if (actor !== session) return;
  await loadOrganizations();
  if (actor !== session) return;
  await loadProducts();
  if (actor !== session) return;
  await loadFarms();
  if (actor !== session) return;
  await loadBatches();
  if (actor !== session) return;
  await loadPendingHandovers();
  if (actor !== session) return;
  if (canOpenScreen("cold-trips-card")) await loadColdTrips();
  if (actor !== session) return;
  await window.phaseCUi?.load();
  if (actor !== session) return;
  if (isRecallEnabled()) await window.recallUi?.load();
  if (isAdmin()) {
    const orgFilter = $("user-org-filter");
    if (session?.role === "org_admin") {
      const myOrg = organizations.find(o => o.id === session.organization_id);
      const orgName = session.organization_name || myOrg?.name || "Tổ chức của bạn";
      orgFilter.innerHTML = `<option value="${session.organization_id}">${escapeHtml(orgName)}</option>`;
      orgFilter.value = String(session.organization_id);
      orgFilter.disabled = true;
    } else {
      orgFilter.disabled = false;
      orgFilter.innerHTML = '<option value="">Tất cả tổ chức</option>' + accountOrgOptions();
    }
    await loadUsers();
  }
  if (canViewAuditLogs()) await loadAuditLogs({ silent: true });
  renderStats();
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
  overview: ["Tổng quan", "Số liệu và hoạt động trong phạm vi tài khoản của bạn.", ["farmer-overdue-banner", "farmer-quick-actions", "overview", "recent-activity"]],
  "farm-card": ["Vùng trồng", "Quản lý danh sách, khai báo và chỉnh sửa vùng trồng.", ["farm-card"]],
  "batch-card": ["Lô nông sản", "Quản lý lô theo quyền và điều kiện dữ liệu.", ["batch-card"]],
  "products-card": ["Danh mục sản phẩm", "Danh mục dùng chung và tạo sản phẩm theo quyền quản trị hệ thống.", ["products-card"]],
  "pending-handovers-card": ["Tiếp nhận bàn giao", "Xác nhận hoặc từ chối các yêu cầu gửi đến tổ chức của bạn.", ["pending-handovers-card"]],
  traceability: ["Truy xuất nguồn gốc", "Xem nguồn gốc và phả hệ của lô nông sản theo quyền truy cập.", ["traceability-card"]],
  events: ["Nhật ký sự kiện", "Dòng thời gian và kiểm tra tính toàn vẹn của lô hàng.", ["events-card", "inspector-card"]],
  "users-card": ["Tài khoản", "Quản lý người dùng theo phạm vi quản trị.", ["users-card"]],
  "audit-card": ["Nhật ký kiểm toán", "Tra cứu lịch sử thao tác theo người dùng và lô.", ["audit-card"]],
  "locations-card": ["Địa điểm phân phối", "Cửa hàng và phân bổ theo tổ chức đang giữ.", ["locations-card"]],
  "imports-card": ["Nhập CSV", "Nhập danh sách sản phẩm hoặc thửa đất từ tệp CSV.", ["imports-card"]],
  "recall-card": ["Thu hồi lô hàng", "Theo dõi sự cố và xác nhận xử lý của các tổ chức liên quan.", ["recall-card"]],
  "cold-trips-card": ["Chuyến xe lạnh", "Khai báo và giám sát các chuyến vận chuyển chuỗi lạnh (S-40).", ["cold-trips-card"]],
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
  if (["locations-card", "imports-card"].includes(key)) return !!window.phaseCUi?.canOpen(key);
  if (key === "farm-card") return ["farmer", "org_admin", "inspector", "system_admin"].includes(session?.role);
  if (key === "products-card") return hasUiAction("PRODUCT_CREATE");
  if (key === "users-card") return hasUiAction("USER_MANAGE");
  if (key === "audit-card") return canViewAuditLogs();
  if (key === "recall-card") return isRecallEnabled();
  if (key === "pending-handovers-card") return canHandover();
  if (key === "cold-trips-card") return ["transporter", "org_admin", "inspector", "system_admin"].includes(session?.role);
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
    if (id && session) {
      verifyDetailChain(id, "events");
    } else if (!id) {
      toast("Vui lòng chọn lô cần kiểm tra tính toàn vẹn.", "error");
    }
  });
  $("events-screen-batch").addEventListener("change", () => {
    setHidden("events-timeline-valid-banner", true);
    setHidden("events-timeline-alert-banner", true);
    $("events-timeline-list").replaceChildren();
  });
  const btnTraceIntegrity = $("btn-traceability-verify-integrity");
  if (btnTraceIntegrity) {
    btnTraceIntegrity.addEventListener("click", () => {
      const id = Number($("trace-screen-batch").value);
      if (id && session) {
        verifyTraceabilityIntegrity(id);
      } else if (!id) {
        toast("Vui lòng chọn lô cần kiểm tra tính toàn vẹn chuỗi truy xuất.", "error");
      }
    });
  }
  $("trace-screen-batch").addEventListener("change", () => {
    setHidden("traceability-valid-banner", true);
    setHidden("traceability-alert-banner", true);
    setHidden("trace-lineage-body", true);
  });
}

function renderAppScreen(scroll = true) {
  if (!document.querySelector(".app-screen")) return;
  let key = location.hash.slice(1) || "overview";

  if (key === "inspector-card") key = "events";
  if (session && !canOpenScreen(key)) {
    key = "overview";
    history.replaceState(null, "", "#overview");
  }
  activeAppScreen = key;
  document.querySelectorAll(".app-screen").forEach((screen) => {
    screen.hidden = !session || screen.dataset.screen !== key;
  });
  setHidden("inspector-card", !session || !(isSystemAdmin() || session.role === "inspector"));
  setHidden("farmer-quick-actions", session?.role !== "farmer");
  const phaseSection = document.querySelector(".sidebar-section--phase-c");
  if (phaseSection) phaseSection.hidden = !canOpenScreen("locations-card") && !canOpenScreen("imports-card");
  setHidden("products-card", !isSystemAdmin());
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
  $("screen-title").textContent = key === "batch-card" ? batchUiLabel() : key === "overview" ? ({inspector: "Tổng quan giám sát", system_admin: "Tổng quan quản trị", admin: "Tổng quan quản trị", org_admin: "Tổng quan tổ chức"}[session.role] || "Tổng quan") : appScreens[key][0];
  let desc = appScreens[key][1];
  if (key === "overview" && session.role === "farmer") {
    desc = "Theo dõi thu hoạch và các việc cần xử lý của tổ chức.";
  } else if (key === "farm-card") {
    if (session.role === "inspector") {
      desc = "Giám sát thông tin cơ sở và thửa đất canh tác trên toàn hệ thống (Chỉ xem).";
    } else if (!canManageFarms()) {
      desc = "Xem danh mục thửa đất xuất xứ trong phạm vi tổ chức (Chỉ xem — không có quyền khai báo/chỉnh sửa).";
    }
  } else if (key === "batch-card") {
    if (session.role === "farmer") {
      desc = "Khai báo thu hoạch, quản lý lô, thực hiện tách lô và chuyển giao cho khâu tiếp theo.";
    } else if (isPackingUser()) {
      $("screen-title").textContent = "Quản lý lô sơ chế & đóng gói";
      desc = "Theo dõi các lô tiếp nhận, thực hiện sơ chế, phân loại, tách lô, gộp lô và chuyển giao cho đối tác chuỗi cung ứng.";
    } else if (session.role === "processor") {
      $("screen-title").textContent = batchUiLabel();
      desc = "Theo dõi các lô nông sản tiếp nhận, thực hiện chế biến, tách lô, gộp lô và chuyển giao trong chuỗi cung ứng.";
    } else if (session.role === "transporter") {
      desc = "Theo dõi các lô đang vận chuyển, nhận bàn giao và chuyển tiếp đến điểm phân phối.";
    } else if (session.role === "distributor") {
      desc = "Quản lý lô nông sản phân phối, thực hiện tách lô, bàn giao hoặc ghi nhận tiêu thụ.";
    } else if (session.role === "inspector") {
      desc = "Giám sát thông tin lô hàng toàn hệ thống (Chỉ xem — không tham gia thao tác sản xuất).";
    } else if (isOrgAdmin()) {
      desc = "Quản lý lô của tổ chức: cập nhật dữ liệu chưa có lịch sử bàn giao/tách/gộp; các thao tác còn lại theo quyền backend và cấu hình demo.";
    } else if (isSystemAdmin()) {
      desc = "Tra cứu lô trong phạm vi tổ chức được backend cấp; quản trị hệ thống không có quyền sản xuất.";
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
  } else if (key === "pending-handovers-card") {
    if (session.role === "farmer") {
      $("screen-title").textContent = "Theo dõi bàn giao";
      desc = "Theo dõi tiến độ các lô đã bàn giao cho đối tác và kiểm tra phản hồi tiếp nhận.";
    } else if (isPackingUser()) {
      $("screen-title").textContent = "Tiếp nhận bàn giao";
      desc = "Kiểm tra và xác nhận tiếp nhận (hoặc từ chối) các lô nông sản do tổ chức khác chuyển giao đến HTX để đưa vào sơ chế & đóng gói.";
    } else if (session.role === "processor") {
      $("screen-title").textContent = "Tiếp nhận bàn giao";
      desc = "Kiểm tra và xác nhận tiếp nhận (hoặc từ chối) các lô nông sản do đối tác chuyển giao đến cơ sở tiếp nhận & chế biến.";
    }
  } else if (key === "events") {
    if (session.role === "farmer") {
      desc = "Xem dòng thời gian sự kiện và xác thực tính toàn vẹn chuỗi mã băm của lô nông sản.";
    } else if (isPackingUser()) {
      desc = "Xem dòng thời gian sự kiện và xác thực tính toàn vẹn chuỗi mã băm của lô hàng sơ chế & đóng gói.";
    }
  }
  const conciseDescriptions={overview:"Các số liệu trong phạm vi tài khoản; số liệu lô tính theo trang đang xem.","batch-card":"Theo dõi lượng còn lại, tổ chức đang giữ và tình trạng lô.","farm-card":"Tra cứu vùng trồng trong phạm vi tài khoản.","pending-handovers-card":"Kiểm tra lô và xác nhận hoặc từ chối bàn giao.",traceability:"Chọn lô để xem nguồn gốc và các lô liên quan.",events:"Chọn lô để xem lịch sử và kiểm tra tính toàn vẹn.","cold-trips-card":"Khai báo và giám sát các chuyến vận chuyển chuỗi lạnh (S-40)."};
  $("screen-description").textContent = conciseDescriptions[key] || appScreens[key][1];
  if (key === "cold-trips-card") {
    loadColdTrips();
  }
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
  const isReceiverView = session.role === "processor" && !isPackingUser();
  const recentSource = events.flatMap(result => result.rows).filter(event => !isReceiverView || (event.event_type === "HANDOVER_ACCEPT" && (event.to_org_id === session.organization_id || event.payload?.to_org_id === session.organization_id)));
  $("recent-activity").querySelector("h3").textContent = isReceiverView ? "Hoạt động tiếp nhận gần đây" : "Hoạt động gần đây";
  const recent = recentSource.sort((a, b) => String(b.timestamp || b.created_at).localeCompare(String(a.timestamp || a.created_at))).slice(0, 5);
  const isFarmer = session?.role === "farmer";
  if (isFarmer) {
    $("recent-activity-list").innerHTML = recent.length ? recent.map((event) => {
      const type = String(event.event_type || "").toUpperCase().trim();
      const typeClass = type.toLowerCase().replace(/_/g, "-");
      const desc = getEventDescription(event);
      return `
        <div class="recent-event recent-event--farmer">
          <div class="recent-event__main">
            <div class="recent-event__header">
              <strong class="recent-event__code">${escapeHtml(event.dashboardCode)}</strong>
              <span class="recent-event__badge recent-event__badge--${escapeHtml(typeClass)}">${escapeHtml(formatDashboardEventType(event.event_type))}</span>
            </div>
            ${desc ? `<p class="recent-event__desc">${escapeHtml(desc)}</p>` : ""}
          </div>
          <time class="recent-event__time">${escapeHtml(formatDateTime(event.timestamp || event.created_at))}</time>
        </div>`;
    }).join("") : '<p class="empty">Chưa có hoạt động trong các lô được lấy mẫu.</p>';
  } else {
    $("recent-activity-list").innerHTML = recent.length ? recent.map((event) =>
      `<div class="recent-event"><div><strong>${escapeHtml(event.dashboardCode)}</strong><span>${escapeHtml(formatEventType(event.event_type))}</span></div><time>${escapeHtml(formatDateTime(event.timestamp || event.created_at))}</time></div>`).join("") : '<p class="empty">Chưa có hoạt động trong các lô được lấy mẫu.</p>';
  }
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
  $("btn-close-batch-qr")?.addEventListener("click", closeBatchQrModal);
  $("btn-close-batch-qr-footer")?.addEventListener("click", closeBatchQrModal);
  $("modal-batch-qr")?.addEventListener("click", event => { if (event.target.id === "modal-batch-qr") closeBatchQrModal(); });
  bindEvents();
  bindAccountControls();
  const handleBatchPageNav = (delta) => {
    if (selectedBatchIds.size > 0) {
      toast("Đã bỏ chọn các lô khi chuyển trang. Chức năng gộp áp dụng cho các lô trên cùng một trang.", "info");
    }
    batchPage += delta;
    selectedBatchIds.clear();
    loadBatches();
  };
  $("batch-prev").addEventListener("click", () => handleBatchPageNav(-1));
  $("batch-next").addEventListener("click", () => handleBatchPageNav(1));
  const batchPageSize = $("batch-page-size");
  if (batchPageSize) {
    batchPageSize.addEventListener("change", () => {
      if (selectedBatchIds.size > 0) {
        toast("Đã bỏ chọn các lô khi thay đổi số lượng hiển thị trên trang.", "info");
      }
      batchPage = 1;
      selectedBatchIds.clear();
      loadBatches();
    });
  }
  document.addEventListener("click", (e) => {
    if (!e.target.closest("details.action-dropdown")) {
      document.querySelectorAll("details.action-dropdown[open]").forEach((d) => d.removeAttribute("open"));
    }
  });
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
