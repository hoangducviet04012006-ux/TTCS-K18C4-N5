/* =====================================================================
   Frontend demo - Truy xuáº¥t nguá»“n gá»‘c vÃ  giÃ¡m sÃ¡t chuá»—i láº¡nh nÃ´ng sáº£n
   JavaScript thuáº§n (khÃ´ng framework, khÃ´ng thÆ° viá»‡n ngoÃ i).
   Cáº¥u trÃºc: cáº¥u hÃ¬nh -> tiá»‡n Ã­ch -> gá»i API -> tráº¡ng thÃ¡i -> render -> sá»± kiá»‡n.
   ===================================================================== */

"use strict";

/* ---------------------------------------------------------- 1. Cáº¥u hÃ¬nh --- */
// Äá»‹a chá»‰ backend FastAPI (Ä‘á»•i á»Ÿ Ä‘Ã¢y náº¿u cháº¡y cá»•ng khÃ¡c).
const API_BASE_URL = "http://127.0.0.1:8000";

// KhoÃ¡ lÆ°u phiÃªn Ä‘Äƒng nháº­p trong sessionStorage (tá»± máº¥t khi Ä‘Ã³ng tab).
const SESSION_STORAGE_KEY = "ttcs.session";

// TÃªn vai trÃ² admin do backend quy Ä‘á»‹nh (dÃ¹ng Ä‘á»ƒ phÃ¢n quyá»n á»Ÿ giao diá»‡n).
const ROLE_ADMIN = "admin";

/* ---------------------------------------------------------- 2. Tiá»‡n Ã­ch --- */
/** Láº¥y element theo id cho ngáº¯n gá»n. */
const $ = (id) => document.getElementById(id);

/**
 * Báº­t/táº¯t hiá»ƒn thá»‹ cá»§a pháº§n tá»­ theo id (dÃ¹ng trong `applySessionToUi`).
 *
 * VÃ¬ sao khÃ´ng viáº¿t tháº³ng `$(id).hidden = ...`: náº¿u index.html thiáº¿u id Ä‘Ã³ -
 * thÆ°á»ng do trÃ¬nh duyá»‡t cÃ²n cache báº£n `app.js` cÅ© hoáº·c báº£n HTML cÅ©, tá»©c HTML
 * vÃ  app.js lá»‡ch phiÃªn báº£n - thÃ¬ `$(id)` lÃ  null vÃ  cÃ¢u lá»‡nh sáº½ nÃ©m lá»—i lÃ m
 * `applySessionToUi` dá»«ng giá»¯a Ä‘Æ°á»ng: cÃ¡c má»¥c phÃ­a sau (trong Ä‘Ã³ cÃ³
 * "3. Lá»‹ch sá»­ thao tÃ¡c") khÃ´ng bao giá» Ä‘Æ°á»£c báº­t mÃ  cÅ©ng khÃ´ng tháº¥y bÃ¡o lá»—i.
 * HÃ m nÃ y chá»‰ cáº£nh bÃ¡o trong Console rá»“i bá» qua Ä‘á»ƒ giao diá»‡n cÃ²n láº¡i váº«n cháº¡y.
 */
function setHidden(id, hidden) {
  const element = $(id);
  if (element === null) {
    console.warn(
      `[frontend] KhÃ´ng tÃ¬m tháº¥y #${id} trong index.html â€” HTML vÃ  app.js cÃ³ thá»ƒ ` +
      "lá»‡ch phiÃªn báº£n (nháº¥n Ctrl+F5 Ä‘á»ƒ táº£i láº¡i báº£n má»›i)."
    );
    return;
  }
  element.hidden = hidden;
}

/** Chá»‘ng XSS: escape dá»¯ liá»‡u do ngÆ°á»i dÃ¹ng nháº­p trÆ°á»›c khi chÃ¨n vÃ o HTML. */
function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/** 120.5 -> "120,5" (Ä‘á»‹nh dáº¡ng sá»‘ kiá»ƒu Viá»‡t Nam). */
function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("vi-VN").format(number) : "â€”";
}

/** "2026-01-15" (tá»« input type=date / API) -> "15/01/2026". */
function formatDate(value) {
  if (!value) return "â€”";
  const parts = String(value).split("-");
  return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : String(value);
}

/**
 * "2026-09-30T14:20:05.123456" (backend lÆ°u UTC, **khÃ´ng** kÃ¨m mÃºi giá») ->
 * "30/09/2026 21:20:05" (giá» cá»§a mÃ¡y ngÆ°á»i dÃ¹ng, Sprint 7).
 *
 * CÃ¡ch lÃ m: Ä‘á»c cÃ¡c thÃ nh pháº§n ngÃ y/giá» cá»§a chuá»—i báº±ng regex (trÃ¡nh viá»‡c má»—i
 * trÃ¬nh duyá»‡t parse pháº§n giÃ¢y láº» `.123456` má»™t kiá»ƒu), dá»±ng `Date` theo **UTC**
 * rá»“i láº¥y cÃ¡c thÃ nh pháº§n theo giá» Ä‘á»‹a phÆ°Æ¡ng. Chuá»—i láº¡ -> tráº£ vá» nguyÃªn báº£n.
 */
function formatDateTime(value) {
  if (!value) return "â€”";

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

/** Hiá»ƒn thá»‹ thÃ´ng bÃ¡o á»Ÿ gÃ³c pháº£i trÃªn: type = "success" | "error" | "info". */
function toast(message, type = "info") {
  const container = $("toast-container");
  const element = document.createElement("div");
  element.className = `toast toast--${type}`;
  element.setAttribute("role", type === "error" ? "alert" : "status");
  element.textContent = message;
  container.appendChild(element);
  window.setTimeout(() => element.remove(), TOAST_DURATION_MS);
}

/** Báº­t/táº¯t tráº¡ng thÃ¡i "Ä‘ang gá»­i" cá»§a nÃºt submit (trÃ¡nh báº¥m 2 láº§n). */
function setButtonLoading(button, isLoading, loadingText, idleText) {
  button.disabled = isLoading;
  button.textContent = isLoading ? loadingText : idleText;
}

/* -------------------------------------------------------- 3. Gá»i API --- */
/**
 * Gá»i API backend vÃ  tráº£ vá» dá»¯ liá»‡u JSON.
 * Máº·c Ä‘á»‹nh gá»­i kÃ¨m tÃ i khoáº£n Ä‘ang Ä‘Äƒng nháº­p (xÃ¡c thá»±c HTTP Basic);
 * truyá»n `auth: false` cho request khÃ´ng cáº§n xÃ¡c thá»±c (VD: Ä‘Äƒng nháº­p).
 * NÃ©m Error vá»›i thÃ´ng Ä‘iá»‡p tiáº¿ng Viá»‡t dá»… Ä‘á»c náº¿u request tháº¥t báº¡i.
 */
async function apiRequest(path, { method = "GET", body, auth = true, headers: extraHeaders = {} } = {}) {
  const headers = {};
  if (body) {
    headers["Content-Type"] = "application/json";
  }
  if (auth) {
    Object.assign(headers, authHeader());
  }
  Object.assign(headers, extraHeaders);

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    // `status = 0`: khÃ´ng cÃ³ pháº£n há»“i HTTP (backend chÆ°a cháº¡y hoáº·c sai cá»•ng).
    const offline = new Error(
      `KhÃ´ng káº¿t ná»‘i Ä‘Æ°á»£c backend (${API_BASE_URL}). HÃ£y cháº¯c cháº¯n uvicorn Ä‘ang cháº¡y.`
    );
    offline.status = 0;
    throw offline;
  }

  const data = await readJson(response);
  if (!response.ok) {
    // Sprint 7: gáº¯n mÃ£ HTTP vÃ o Error Ä‘á»ƒ nÆ¡i gá»i xá»­ lÃ½ riÃªng 401/403 (xem
    // `loadAuditLogs`). CÃ¡c Ä‘oáº¡n `catch` cÅ© chá»‰ Ä‘á»c `error.message` nÃªn khÃ´ng
    // bá»‹ áº£nh hÆ°á»Ÿng.
    const error = new Error(describeError(data, response.status));
    error.status = response.status;
    throw error;
  }
  return data;
}

/** Äá»c JSON an toÃ n (response lá»—i cÃ³ thá»ƒ khÃ´ng pháº£i JSON). */
async function readJson(response) {
  try {
    return await response.json();
  } catch (error) {
    return null;
  }
}

/** Chuyá»ƒn lá»—i cá»§a FastAPI (`detail`) thÃ nh cÃ¢u thÃ´ng bÃ¡o dá»… hiá»ƒu. */
function describeError(data, status) {
  const detail = data ? data.detail : null;

  // Lá»—i nghiá»‡p vá»¥: 404 farm khÃ´ng tá»“n táº¡i, 500 lá»—i database...
  if (typeof detail === "string") {
    return detail;
  }

  // Lá»—i validate cá»§a Pydantic (422): detail lÃ  máº£ng cÃ¡c lá»—i.
  if (Array.isArray(detail)) {
    return detail
      .map((item) => `${(item.loc || []).join(".")}: ${item.msg}`)
      .join(" | ");
  }

  return `YÃªu cáº§u tháº¥t báº¡i (HTTP ${status}).`;
}

/* ------------------------------------------------------- 4. Tráº¡ng thÃ¡i --- */
// Dá»¯ liá»‡u Ä‘ang hiá»ƒn thá»‹ trÃªn giao diá»‡n.
let farms = [];
let batches = [];
let users = [];
// Sprint 7: lá»‹ch sá»­ thao tÃ¡c (chá»‰ admin táº£i Ä‘Æ°á»£c - xem `loadAuditLogs`).
let auditLogs = [];
// SCRUM-27/28: Danh sÃ¡ch tá»• chá»©c vÃ  cÃ¡c bÃ n giao Ä‘ang chá» duyá»‡t
let organizations = [];
let pendingHandovers = [];

// [S-07] Danh mục sản phẩm và đơn vị tính
let products = [];
let units = [];
let editingProductId = null;
let editingUnitId = null;

// ID báº£n ghi Ä‘ang Ä‘Æ°á»£c Sá»¬A trÃªn form (null = form Ä‘ang á»Ÿ cháº¿ Ä‘á»™ "thÃªm má»›i").
// Sprint 5: báº¥m nÃºt "Sá»­a" á»Ÿ báº£ng -> form phÃ­a trÃªn Ä‘á»• sáºµn dá»¯ liá»‡u vÃ  nÃºt submit
// gá»i PUT thay vÃ¬ POST.
let editingFarmId = null;
let editingBatchId = null;

// PhiÃªn Ä‘Äƒng nháº­p hiá»‡n táº¡i: { username, role, password } hoáº·c null (chÆ°a Ä‘Äƒng nháº­p).
// Sprint 4 khÃ´ng dÃ¹ng JWT: client giá»¯ láº¡i thÃ´ng tin Ä‘Äƒng nháº­p Ä‘á»ƒ gá»­i kÃ¨m header
// `Authorization: Basic ...` trong má»—i request.
let session = null;

// [T-59] ID cá»§a lÃ´ Ä‘ang Ä‘Æ°á»£c hiá»ƒn thá»‹ trong chi tiáº¿t (dÃ¹ng cho nÃºt Timeline / Ancestors).
let currentBatchId = null;

/* --------------------------------------------------------- 5. ÄÄƒng nháº­p --- */
/**
 * MÃ£ hoÃ¡ chuá»—i "username:password" sang Base64 theo chuáº©n HTTP Basic.
 * DÃ¹ng TextEncoder Ä‘á»ƒ há»— trá»£ tiáº¿ng Viá»‡t (btoa chá»‰ nháº­n kÃ½ tá»± Latin-1).
 */
function encodeBase64(text) {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

/** Header xÃ¡c thá»±c cá»§a tÃ i khoáº£n Ä‘ang Ä‘Äƒng nháº­p (rá»—ng náº¿u chÆ°a Ä‘Äƒng nháº­p). */
function authHeader() {
  if (session === null) {
    return {};
  }
  const token = encodeBase64(`${session.username}:${session.password}`);
  return { Authorization: `Basic ${token}` };
}

/** POST /auth/login - kiá»ƒm tra tÃ i khoáº£n; nÃ©m Error náº¿u sai (backend tráº£ 401). */
function requestLogin(username, password) {
  return apiRequest("/auth/login", {
    method: "POST",
    body: { username, password },
    auth: false, // request Ä‘Äƒng nháº­p khÃ´ng gá»­i kÃ¨m header cá»§a phiÃªn cÅ©
  });
}

/** LÆ°u phiÃªn Ä‘Äƒng nháº­p vÃ o bá»™ nhá»› + sessionStorage (giá»¯ Ä‘Æ°á»£c khi F5 trong tab). */
function startSession({ username, role, password, organization_id, organization_name }) {
  session = { username, role, password, organization_id, organization_name };
  window.sessionStorage.setItem(
    SESSION_STORAGE_KEY,
    JSON.stringify({ username, password, organization_id, organization_name })
  );
  applySessionToUi();
}

/** Äá»c phiÃªn Ä‘Äƒng nháº­p Ä‘Ã£ lÆ°u trong tab; tráº£ null náº¿u chÆ°a cÃ³ hoáº·c dá»¯ liá»‡u há»ng. */
function restoreSession() {
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    const saved = raw ? JSON.parse(raw) : null;
    if (saved && saved.username && saved.password) {
      return saved;
    }
  } catch (error) {
    // Dá»¯ liá»‡u lÆ°u khÃ´ng há»£p lá»‡ -> coi nhÆ° chÆ°a Ä‘Äƒng nháº­p.
  }
  return null;
}

/** XoÃ¡ phiÃªn Ä‘Äƒng nháº­p khá»i bá»™ nhá»› vÃ  sessionStorage. */
function clearSession() {
  session = null;
  window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
}

/**
 * Cáº­p nháº­t giao diá»‡n theo tráº¡ng thÃ¡i Ä‘Äƒng nháº­p, vai trÃ² (role) vÃ  tá»• chá»©c:
 * - chÆ°a Ä‘Äƒng nháº­p: chá»‰ hiá»‡n mÃ n hÃ¬nh login;
 * - farmer: hiá»‡n chá»©c nÄƒng quáº£n lÃ½ nÃ´ng sáº£n (thá»­a Ä‘áº¥t, lÃ´ nÃ´ng sáº£n) cá»§a tá»• chá»©c mÃ¬nh;
 * - admin: hiá»‡n toÃ n bá»™, thÃªm má»¥c quáº£n trá»‹ tÃ i khoáº£n;
 * - hiá»ƒn thá»‹ logo/tÃªn tá»• chá»©c cá»§a user Ä‘ang hoáº¡t Ä‘á»™ng.
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
    orgBadge.textContent = `ðŸ¢ ${session.organization_name}`;
  }

  const badge = $("user-badge");
  if (badge !== null && isLoggedIn) {
    const roleText = adminUser ? "Quáº£n trá»‹ viÃªn" : "Chá»§ nÃ´ng há»™ / NÃ´ng dÃ¢n";
    badge.textContent = `ðŸ‘¤ ${session.username} (${roleText})`;
    badge.className = adminUser ? "badge badge--ok" : "badge badge--muted";
  }

  const orgContext = $("farm-org-context");
  if (orgContext !== null && isLoggedIn) {
    orgContext.textContent = `CÃ¡c thá»­a Ä‘áº¥t thuá»™c: ${session.organization_name || "Tá»• chá»©c cá»§a báº¡n"}`;
  }

  setHidden("users-card", !adminUser);
  setHidden("audit-card", !adminUser);
  setHidden("stat-audit-card", !adminUser);
}

/** PhiÃªn hiá»‡n táº¡i cÃ³ pháº£i tÃ i khoáº£n **admin** khÃ´ng (dÃ¹ng cho chá»©c nÄƒng chá»‰ admin). */
function isAdmin() {
  return session !== null && session.role === ROLE_ADMIN;
}

/**
 * Quyá»n xoÃ¡ dá»¯ liá»‡u á»Ÿ giao diá»‡n: **chá»‰ admin** (Sprint 5).
 * Farmer dÃ¹ng giao diá»‡n sáº½ khÃ´ng tháº¥y nÃºt XoÃ¡; náº¿u cá»‘ gá»i API xoÃ¡ thÃ¬ backend
 * tráº£ `403 Forbidden` (`require_admin`) - Ä‘Ã¢y chá»‰ lÃ  lá»›p báº£o vá»‡ á»Ÿ UI.
 */
function canDelete() {
  return isAdmin();
}

/** Xá»­ lÃ½ submit form Ä‘Äƒng nháº­p -> POST /auth/login. */
async function handleLoginSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  const username = $("login-username").value.trim();
  const password = $("login-password").value; // khÃ´ng trim máº­t kháº©u

  const button = $("login-submit");
  setButtonLoading(button, true, "Äang kiá»ƒm traâ€¦", "ÄÄƒng nháº­p");

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
    const orgGreeting = data.organization_name ? ` Â· ${data.organization_name}` : "";
    toast(`ÄÄƒng nháº­p thÃ nh cÃ´ng! Xin chÃ o ${data.username}${orgGreeting}.`, "success");
    await reloadAll({ silent: true });
  } catch (error) {
    if (error.status === 401) {
      toast("Sai tÃªn Ä‘Äƒng nháº­p hoáº·c máº­t kháº©u. Vui lÃ²ng kiá»ƒm tra láº¡i!", "error");
    } else {
      toast(error.message, "error");
    }
    $("login-password").select();
  } finally {
    setButtonLoading(button, false, "Äang kiá»ƒm traâ€¦", "ÄÄƒng nháº­p");
  }
}

/** ÄÄƒng xuáº¥t: xoÃ¡ phiÃªn, xoÃ¡ dá»¯ liá»‡u Ä‘ang hiá»ƒn thá»‹ vÃ  quay vá» mÃ n hÃ¬nh login. */
function handleLogout() {
  const username = session ? session.username : "";
  clearSession();

  farms = [];
  batches = [];
  users = [];
  auditLogs = [];
  organizations = [];
  pendingHandovers = [];
  resetFarmForm();
  resetBatchForm();
  renderFarms();
  renderFarmOptions();
  renderBatches();
  renderUsers();
  renderAuditLogs();
  renderPendingHandovers();

  applySessionToUi();
  toast(username ? `ÄÃ£ Ä‘Äƒng xuáº¥t tÃ i khoáº£n ${username}.` : "ÄÃ£ Ä‘Äƒng xuáº¥t.", "info");
  $("login-username").focus();
}

/* ------------------------------------------- 6. Kiá»ƒm tra backend sá»‘ng --- */
async function checkHealth() {
  const badge = $("health-badge");
  try {
    const data = await apiRequest("/health");
    badge.textContent = "Há»‡ thá»‘ng trá»±c tuyáº¿n";
    badge.className = "badge badge--ok";
  } catch (error) {
    badge.textContent = "Máº¥t káº¿t ná»‘i mÃ¡y chá»§";
    badge.className = "badge badge--error";
    toast("KhÃ´ng káº¿t ná»‘i Ä‘Æ°á»£c tá»›i mÃ¡y chá»§ API: " + error.message, "error");
  }
}

/* ------------------------------------------------------- 7. VÃ¹ng trá»“ng --- */
/** GET /farms -> cáº­p nháº­t báº£ng danh sÃ¡ch + select vÃ¹ng trá»“ng cá»§a form lÃ´. */
async function loadFarms() {
  try {
    const data = await apiRequest("/farms");
    farms = Array.isArray(data) ? data : [];
    renderFarms();
    renderFarmOptions();
  } catch (error) {
    toast(`KhÃ´ng táº£i Ä‘Æ°á»£c danh sÃ¡ch vÃ¹ng trá»“ng: ${error.message}`, "error");
  }
}

let farmViewMode = "cards"; // "cards" | "table"

/** Chuyá»ƒn Ä‘á»•i giá»¯a cháº¿ Ä‘á»™ xem Dáº¡ng Tháº» vÃ  Dáº¡ng Báº£ng */
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

/** Váº½ danh sÃ¡ch thá»­a Ä‘áº¥t (cáº£ dáº¡ng tháº» trá»±c quan vÃ  dáº¡ng báº£ng chi tiáº¿t). */
function renderFarms() {
  const cardsContainer = $("farm-cards-container");
  const tableBody = $("farm-table-body");

  // 1. Dáº¡ng Tháº» (Cards) - trá»±c quan, tá»‘i Æ°u cho nÃ´ng dÃ¢n
  if (cardsContainer) {
    cardsContainer.innerHTML = farms
      .map(
        (farm) => `
        <article class="farm-card ${farm.id === editingFarmId ? "is-editing" : ""}">
          <div class="farm-card__header">
            <div class="farm-card__title-group">
              <span class="farm-card__icon">ðŸŒ¾</span>
              <h4 class="farm-card__name">${escapeHtml(farm.name)}</h4>
            </div>
            <span class="farm-card__area-badge">${formatNumber(farm.area)} ha</span>
          </div>
          <div class="farm-card__body">
            <div class="farm-card__meta">
              <span class="meta-label">ðŸ“ Vá»‹ trÃ­:</span>
              <span class="meta-value">${escapeHtml(farm.location)}</span>
            </div>
            <div class="farm-card__meta">
              <span class="meta-label">ðŸŒ Tá»a Ä‘á»™ GPS:</span>
              <span class="meta-value">${farm.coordinates ? escapeHtml(farm.coordinates) : '<em style="color:#9ca3af">ChÆ°a cáº­p nháº­t</em>'}</span>
            </div>
            <div class="farm-card__meta">
              <span class="meta-label">ðŸ‘¤ NÃ´ng há»™ phá»¥ trÃ¡ch:</span>
              <span class="meta-value">${escapeHtml(farm.owner)}</span>
            </div>
          </div>
          <div class="farm-card__footer">
            <button class="btn btn--primary btn--sm" type="button"
                    data-action="edit" data-entity="farm"
                    data-id="${escapeHtml(farm.id)}">âœï¸ Sá»­a</button>
            ${
              canDelete()
                ? `<button class="btn btn--danger btn--sm" type="button"
                    data-action="delete" data-entity="farm"
                    data-id="${escapeHtml(farm.id)}">ðŸ—‘ï¸ XoÃ¡</button>`
                : ""
            }
          </div>
        </article>`
      )
      .join("");
  }

  // 2. Dáº¡ng Báº£ng (Table)
  if (tableBody) {
    tableBody.innerHTML = farms
      .map(
        (farm) => `
        <tr class="${farm.id === editingFarmId ? "is-editing" : ""}">
          <td><strong>${escapeHtml(farm.name)}</strong></td>
          <td>${escapeHtml(farm.location)}</td>
          <td>${farm.coordinates ? escapeHtml(farm.coordinates) : '<em style="color:#9ca3af">â€”</em>'}</td>
          <td class="is-right">${formatNumber(farm.area)}</td>
          <td>${escapeHtml(farm.owner)}</td>
          <td>
            <div class="table__actions">
              <button class="btn btn--primary btn--sm" type="button"
                      data-action="edit" data-entity="farm"
                      data-id="${escapeHtml(farm.id)}">Sá»­a</button>
              ${
                canDelete()
                  ? `<button class="btn btn--danger btn--sm" type="button"
                      data-action="delete" data-entity="farm"
                      data-id="${escapeHtml(farm.id)}">XoÃ¡</button>`
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

/** Äá»• danh sÃ¡ch vÃ¹ng trá»“ng vÃ o select `farm_id` cá»§a form táº¡o lÃ´. */
function renderFarmOptions() {
  const select = $("batch-farm-id");
  const selected = select.value;

  if (farms.length === 0) {
    select.innerHTML = '<option value="">â€” ChÆ°a cÃ³ thá»­a Ä‘áº¥t nÃ o, hÃ£y thÃªm thá»­a Ä‘áº¥t trÆ°á»›c â€”</option>';
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

  // Giá»¯ láº¡i lá»±a chá»n cÅ© náº¿u vÃ¹ng trá»“ng Ä‘Ã³ váº«n cÃ²n.
  if (selected && farms.some((farm) => String(farm.id) === selected)) {
    select.value = selected;
  }
}

/** NhÃ£n nÃºt submit form vÃ¹ng trá»“ng theo cháº¿ Ä‘á»™ hiá»‡n táº¡i (thÃªm má»›i / sá»­a). */
function farmSubmitLabel() {
  return editingFarmId === null ? "ThÃªm thá»­a Ä‘áº¥t" : "Cáº­p nháº­t thá»­a Ä‘áº¥t";
}

/**
 * Xá»­ lÃ½ submit form vÃ¹ng trá»“ng:
 * - cháº¿ Ä‘á»™ thÃªm má»›i (`editingFarmId === null`) -> POST /farms;
 * - cháº¿ Ä‘á»™ sá»­a (Ä‘Ã£ báº¥m nÃºt "Sá»­a" á»Ÿ báº£ng)       -> PUT /farms/{id}.
 */
async function handleFarmSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  const area = Number($("farm-area").value);
  if (isNaN(area) || area <= 0) {
    toast("Diá»‡n tÃ­ch thá»­a Ä‘áº¥t báº¯t buá»™c pháº£i lá»›n hÆ¡n 0 ha!", "error");
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
  setButtonLoading(button, true, "Äang lÆ°uâ€¦", farmSubmitLabel());

  try {
    if (isEditing) {
      const updated = await apiRequest(`/farms/${editingFarmId}`, { method: "PUT", body: payload });
      toast(`ÄÃ£ cáº­p nháº­t thá»­a Ä‘áº¥t: ${updated.name}`, "success");
    } else {
      const created = await apiRequest("/farms", { method: "POST", body: payload });
      toast(`ThÃªm thÃ nh cÃ´ng thá»­a Ä‘áº¥t: ${created.name}`, "success");
    }
    resetFarmForm(); // vá» láº¡i cháº¿ Ä‘á»™ "thÃªm má»›i"
    await loadFarms(); // cáº­p nháº­t danh sÃ¡ch thá»­a Ä‘áº¥t vÃ  select lÃ´ nÃ´ng sáº£n
    await loadBatches();
    await refreshAuditLogsIfAdmin();
    $("farm-name").focus();
  } catch (error) {
    toast(`${isEditing ? "Cáº­p nháº­t" : "ThÃªm"} thá»­a Ä‘áº¥t tháº¥t báº¡i: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Äang lÆ°uâ€¦", farmSubmitLabel());
  }
}

/** ÄÆ°a form vÃ¹ng trá»“ng vá» cháº¿ Ä‘á»™ "thÃªm má»›i" (bá» dá»¯ liá»‡u Ä‘ang sá»­a). */
function resetFarmForm() {
  editingFarmId = null;
  $("farm-form").reset();
  $("farm-form-mode").hidden = true;
  $("farm-cancel").hidden = true;
  $("farm-submit").textContent = farmSubmitLabel();
}

/**
 * Báº¥m nÃºt "Sá»­a" á»Ÿ báº£ng/tháº» -> Ä‘á»• dá»¯ liá»‡u vÃ¹ng trá»“ng lÃªn form vÃ  chuyá»ƒn sang cháº¿ Ä‘á»™ sá»­a.
 */
function startEditFarm(farmId) {
  const farm = farms.find((item) => item.id === farmId);
  if (!farm) {
    toast(`KhÃ´ng tÃ¬m tháº¥y thá»­a Ä‘áº¥t #${farmId} trong dá»¯ liá»‡u Ä‘ang hiá»ƒn thá»‹.`, "error");
    return;
  }

  editingFarmId = farm.id;
  $("farm-name").value = farm.name;
  $("farm-location").value = farm.location;
  $("farm-area").value = farm.area;
  $("farm-coordinates").value = farm.coordinates || "";
  $("farm-owner").value = farm.owner;

  const mode = $("farm-form-mode");
  mode.textContent = `Äang sá»­a thá»­a Ä‘áº¥t: ${farm.name}. Báº¥m "Cáº­p nháº­t thá»­a Ä‘áº¥t" Ä‘á»ƒ lÆ°u.`;
  mode.hidden = false;
  $("farm-cancel").hidden = false;
  $("farm-submit").textContent = farmSubmitLabel();

  renderFarms(); // tÃ´ viá»n card/dÃ²ng Ä‘ang sá»­a
  $("farm-form").scrollIntoView({ behavior: "smooth", block: "start" });
  $("farm-name").focus();
}

/**
 * XoÃ¡ vÃ¹ng trá»“ng (chá»‰ admin) -> ``DELETE /farms/{id}``.
 * Backend xoÃ¡ kÃ¨m má»i lÃ´ nÃ´ng sáº£n cá»§a vÃ¹ng Ä‘Ã³ nÃªn giao diá»‡n pháº£i táº£i láº¡i cáº£
 * hai báº£ng; sá»‘ lÃ´ bá»‹ xoÃ¡ kÃ¨m Ä‘Æ°á»£c backend tráº£ vá» trong ``deleted_batches``.
 */
async function deleteFarm(farmId) {
  const farm = farms.find((item) => item.id === farmId);
  const label = farm ? `#${farm.id} â€” ${farm.name}` : `#${farmId}`;
  const childCount = batches.filter((batch) => batch.farm_id === farmId).length;

  const question =
    `Báº¡n cÃ³ cháº¯c cháº¯n muá»‘n xoÃ¡ vÃ¹ng trá»“ng ${label}?` +
    (childCount > 0 ? `\nLÆ°u Ã½: ToÃ n bá»™ ${childCount} lÃ´ nÃ´ng sáº£n trá»±c thuá»™c vÃ¹ng nÃ y cÅ©ng sáº½ bá»‹ xoÃ¡ theo.` : "") +
    "\nHÃ nh Ä‘á»™ng nÃ y khÃ´ng thá»ƒ hoÃ n tÃ¡c.";
  if (!window.confirm(question)) {
    return;
  }

  try {
    const result = await apiRequest(`/farms/${farmId}`, { method: "DELETE" });
    toast(result && result.message ? result.message : `ÄÃ£ xoÃ¡ vÃ¹ng trá»“ng #${farmId}.`, "success");

    if (editingFarmId === farmId) {
      resetFarmForm(); // vÃ¹ng trá»“ng Ä‘ang sá»­a Ä‘Ã£ bá»‹ xoÃ¡ -> form vá» cháº¿ Ä‘á»™ thÃªm má»›i
    }
    await loadFarms();
    await loadBatches(); // cÃ¡c lÃ´ cá»§a vÃ¹ng trá»“ng vá»«a xoÃ¡ cÅ©ng biáº¿n máº¥t
    await refreshAuditLogsIfAdmin(); // Sprint 7: vá»«a xoÃ¡ -> cáº­p nháº­t lá»‹ch sá»­
  } catch (error) {
    toast(`XoÃ¡ vÃ¹ng trá»“ng tháº¥t báº¡i: ${error.message}`, "error");
  }
}

/* ------------------------------------------------------ 8. LÃ´ nÃ´ng sáº£n --- */
/** GET /batches -> cáº­p nháº­t báº£ng danh sÃ¡ch lÃ´. */
async function loadBatches() {
  try {
    const data = await apiRequest("/batches");
    batches = Array.isArray(data) ? data : [];
    renderBatches();
  } catch (error) {
    toast(`KhÃ´ng táº£i Ä‘Æ°á»£c danh sÃ¡ch lÃ´ nÃ´ng sáº£n: ${error.message}`, "error");
  }
}

/** NhÃ£n vÃ¹ng trá»“ng cho báº£ng lÃ´ (dÃ¹ng láº¡i dá»¯ liá»‡u Ä‘Ã£ táº£i tá»« GET /farms). */
function farmLabel(farmId) {
  const farm = farms.find((item) => item.id === farmId);
  return farm ? `#${farmId} â€” ${farm.name}` : `#${farmId}`;
}

/** Váº½ báº£ng danh sÃ¡ch lÃ´ nÃ´ng sáº£n (kÃ¨m cá»™t ÄÆ¡n vá»‹ náº¯m giá»¯, Tráº¡ng thÃ¡i & Thao tÃ¡c). */
function renderBatches() {
  $("batch-table-body").innerHTML = batches
    .map((batch) => {
      const holdingOrg = batch.current_org_name || (session?.organization_name || farmLabel(batch.farm_id));
      const isPending = (batch.pending_handover != null) || pendingHandovers.some((h) => h.batch_id === batch.id);
      const statusBadge = isPending
        ? '<span class="badge badge--warning">â³ Chá» bÃ n giao</span>'
        : '<span class="badge badge--ok">Äang quáº£n lÃ½</span>';

      // Kiá»ƒm tra ngÆ°á»i dÃ¹ng cÃ³ thuá»™c tá»• chá»©c Ä‘ang náº¯m giá»¯ lÃ´ khÃ´ng
      const isHolder = session && (
        batch.current_org_id == null ||
        session.organization_id == null ||
        batch.current_org_id === session.organization_id
      );

      let handoverBtn = "";
      if (isHolder) {
        if (isPending) {
          handoverBtn = `<button class="btn btn--light btn--sm" type="button" disabled title="LÃ´ hÃ ng Ä‘ang cÃ³ yÃªu cáº§u bÃ n giao chá» xÃ¡c nháº­n">â³ Chá» duyá»‡t</button>`;
        } else {
          handoverBtn = `<button class="btn btn--outline-primary btn--sm" type="button"
                           data-action="open-handover" data-id="${escapeHtml(batch.id)}">ðŸšš BÃ n giao</button>`;
        }
      }

      return `
      <tr class="${batch.id === editingBatchId ? "is-editing" : ""}">
        <td class="id-cell"><a href="javascript:void(0)" onclick="openBatchDetail(${batch.id})" style="font-weight: bold; text-decoration: underline;" title="Xem chi tiáº¿t lÃ´ #${batch.id}">#${escapeHtml(batch.id)}</a></td>
        <td>${escapeHtml(farmLabel(batch.farm_id))}</td>
        <td><strong>${escapeHtml(batch.product_name)}</strong></td>
        <td class="is-right">${formatNumber(batch.quantity)}</td>
        <td>${escapeHtml(formatDate(batch.harvest_date))}</td>
        <td><span class="badge badge--org">ðŸ¢ ${escapeHtml(holdingOrg)}</span></td>
        <td>${statusBadge}</td>
        <td>
          <div class="table__actions">
            <button class="btn btn--light btn--sm" type="button"
                    data-action="view-detail" data-entity="batch"
                    data-id="${escapeHtml(batch.id)}">ðŸ‘ï¸ Chi tiáº¿t</button>
            <button class="btn btn--primary btn--sm" type="button"
                    data-action="edit" data-entity="batch"
                    data-id="${escapeHtml(batch.id)}">Sá»­a</button>
            ${handoverBtn}
            ${
              canDelete()
                ? `<button class="btn btn--danger btn--sm" type="button"
                    data-action="delete" data-entity="batch"
                    data-id="${escapeHtml(batch.id)}">XoÃ¡</button>`
                : ""
            }
          </div>
        </td>
      </tr>`;
    })
    .join("");

  $("batch-empty").hidden = batches.length > 0;
  renderStats();
}

/** NhÃ£n nÃºt submit form lÃ´ nÃ´ng sáº£n theo cháº¿ Ä‘á»™ hiá»‡n táº¡i (táº¡o má»›i / sá»­a). */
function batchSubmitLabel() {
  return editingBatchId === null ? "Táº¡o lÃ´ nÃ´ng sáº£n" : "Cáº­p nháº­t lÃ´ nÃ´ng sáº£n";
}

/**
 * Xá»­ lÃ½ submit form lÃ´ nÃ´ng sáº£n:
 * - cháº¿ Ä‘á»™ táº¡o má»›i (`editingBatchId === null`) -> POST /batches;
 * - cháº¿ Ä‘á»™ sá»­a (Ä‘Ã£ báº¥m nÃºt "Sá»­a" á»Ÿ báº£ng)       -> PUT /batches/{id}.
 */
async function handleBatchSubmit(event) {
  event.preventDefault();

  const form = event.currentTarget;
  if (!form.reportValidity()) {
    return;
  }

  const farmSelect = $("batch-farm-id");
  if (!farmSelect.value) {
    toast("ChÆ°a cÃ³ vÃ¹ng trá»“ng nÃ o. Vui lÃ²ng thÃªm vÃ¹ng trá»“ng trÆ°á»›c khi táº¡o lÃ´ nÃ´ng sáº£n.", "error");
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
  setButtonLoading(button, true, "Äang lÆ°uâ€¦", batchSubmitLabel());

  try {
    if (isEditing) {
      const updated = await apiRequest(`/batches/${editingBatchId}`, { method: "PUT", body: payload });
      toast(`ÄÃ£ cáº­p nháº­t lÃ´ #${updated.id} "${updated.product_name}"`, "success");
    } else {
      const idempotencyKey = (
        window.crypto?.randomUUID?.() ||
        `${Date.now()}-${Math.random().toString(36).slice(2)}`
      );

      const created = await apiRequest("/batches", {
        method: "POST",
        body: payload,
        headers: {
          "Idempotency-Key": idempotencyKey,
        },
      });
      toast(
        `Táº¡o thÃ nh cÃ´ng lÃ´ #${created.id} "${created.product_name}" cho vÃ¹ng trá»“ng #${created.farm_id}`,
        "success"
      );
    }
    resetBatchForm(); // vá» láº¡i cháº¿ Ä‘á»™ "táº¡o má»›i"
    farmSelect.value = String(payload.farm_id); // giá»¯ láº¡i vÃ¹ng trá»“ng vá»«a chá»n
    await loadBatches();
    await refreshAuditLogsIfAdmin(); // Sprint 7: vá»«a ghi dá»¯ liá»‡u -> cáº­p nháº­t lá»‹ch sá»­
  } catch (error) {
    toast(`${isEditing ? "Cáº­p nháº­t" : "Táº¡o"} lÃ´ nÃ´ng sáº£n tháº¥t báº¡i: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Äang lÆ°uâ€¦", batchSubmitLabel());
  }
}

/** ÄÆ°a form lÃ´ nÃ´ng sáº£n vá» cháº¿ Ä‘á»™ "táº¡o má»›i" (bá» dá»¯ liá»‡u Ä‘ang sá»­a). */
function resetBatchForm() {
  editingBatchId = null;
  $("batch-form").reset();
  $("batch-form-mode").hidden = true;
  $("batch-cancel").hidden = true;
  $("batch-submit").textContent = batchSubmitLabel();
}

/**
 * Báº¥m nÃºt "Sá»­a" á»Ÿ báº£ng lÃ´ -> Ä‘á»• dá»¯ liá»‡u lÃªn form vÃ  chuyá»ƒn sang cháº¿ Ä‘á»™ sá»­a
 * (nÃºt submit sáº½ gá»i ``PUT /batches/{id}``).
 */
function startEditBatch(batchId) {
  const batch = batches.find((item) => item.id === batchId);
  if (!batch) {
    toast(`KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n #${batchId} trong dá»¯ liá»‡u Ä‘ang hiá»ƒn thá»‹.`, "error");
    return;
  }

  editingBatchId = batch.id;
  $("batch-farm-id").value = String(batch.farm_id); // select Ä‘Ã£ Ä‘Æ°á»£c Ä‘á»• á»Ÿ loadFarms()
  $("batch-product-name").value = batch.product_name;
  $("batch-quantity").value = batch.quantity;
  $("batch-harvest-date").value = batch.harvest_date; // API tráº£ sáºµn dáº¡ng yyyy-MM-dd

  const mode = $("batch-form-mode");
  mode.textContent = `Äang sá»­a lÃ´ #${batch.id} â€” ${batch.product_name}. Báº¥m "Cáº­p nháº­t lÃ´ nÃ´ng sáº£n" Ä‘á»ƒ lÆ°u.`;
  mode.hidden = false;
  $("batch-cancel").hidden = false;
  $("batch-submit").textContent = batchSubmitLabel();

  renderBatches(); // tÃ´ ná»n dÃ²ng Ä‘ang sá»­a trong báº£ng
  $("batch-form").scrollIntoView({ behavior: "smooth", block: "start" });
  $("batch-product-name").focus();
}

/** XoÃ¡ lÃ´ nÃ´ng sáº£n (chá»‰ admin) -> ``DELETE /batches/{id}``. */
async function deleteBatch(batchId) {
  const batch = batches.find((item) => item.id === batchId);
  const label = batch ? `#${batch.id} â€” ${batch.product_name}` : `#${batchId}`;

  if (!window.confirm(`Báº¡n cÃ³ cháº¯c cháº¯n muá»‘n xoÃ¡ lÃ´ nÃ´ng sáº£n ${label}?\nHÃ nh Ä‘á»™ng nÃ y khÃ´ng thá»ƒ hoÃ n tÃ¡c.`)) {
    return;
  }

  try {
    const result = await apiRequest(`/batches/${batchId}`, { method: "DELETE" });
    toast(result && result.message ? result.message : `ÄÃ£ xoÃ¡ lÃ´ nÃ´ng sáº£n #${batchId}.`, "success");

    if (editingBatchId === batchId) {
      resetBatchForm(); // lÃ´ Ä‘ang sá»­a Ä‘Ã£ bá»‹ xoÃ¡ -> form vá» cháº¿ Ä‘á»™ táº¡o má»›i
    }
    await loadBatches();
    await refreshAuditLogsIfAdmin(); // Sprint 7: vá»«a xoÃ¡ -> cáº­p nháº­t lá»‹ch sá»­
  } catch (error) {
    toast(`XoÃ¡ lÃ´ nÃ´ng sáº£n tháº¥t báº¡i: ${error.message}`, "error");
  }
}

/* ------------------------------------------------------- 9. Thá»‘ng kÃª --- */
/**
 * Cáº­p nháº­t cÃ¡c tháº» thá»‘ng kÃª trÃªn dashboard tá»« dá»¯ liá»‡u Ä‘ang hiá»ƒn thá»‹:
 * - **Tá»•ng vÃ¹ng trá»“ng**: sá»‘ pháº§n tá»­ cá»§a `farms` (nguá»“n: `GET /farms`);
 * - **Tá»•ng lÃ´ nÃ´ng sáº£n**: sá»‘ pháº§n tá»­ cá»§a `batches` (nguá»“n: `GET /batches`);
 * - **Tá»•ng sáº£n lÆ°á»£ng (kg)**: cá»™ng `quantity` cá»§a má»i lÃ´ (lÃ m trÃ²n 2 chá»¯ sá»‘);
 * - **Lá»‹ch sá»­ thao tÃ¡c** (Sprint 7, chá»‰ admin tháº¥y): sá»‘ pháº§n tá»­ cá»§a `auditLogs`
 *   (nguá»“n: `GET /audit-logs`) - farmer khÃ´ng táº£i Ä‘Æ°á»£c nÃªn tháº» nÃ y bá»‹ áº©n.
 *
 * HÃ m Ä‘Æ°á»£c gá»i láº¡i má»—i khi váº½ xong báº£ng (`renderFarms` / `renderBatches` /
 * `renderAuditLogs`) nÃªn sá»‘ liá»‡u luÃ´n khá»›p vá»›i dá»¯ liá»‡u vá»«a táº£i.
 */
function renderStats() {
  const totalYield = batches.reduce((sum, batch) => sum + Number(batch.quantity || 0), 0);

  $("stat-farms").textContent = formatNumber(farms.length);
  $("stat-batches").textContent = formatNumber(batches.length);
  $("stat-yield").textContent = formatNumber(Math.round(totalYield * 100) / 100);
  $("stat-audit").textContent = formatNumber(auditLogs.length);
  const pendingStat = $("stat-pending-handovers");
  if (pendingStat) {
    pendingStat.textContent = formatNumber(pendingHandovers.length);
  }
}

/* ------------------------------------------ 10. TÃ i khoáº£n (chá»‰ admin) --- */
/** GET /users (chá»‰ admin) -> cáº­p nháº­t báº£ng tÃ i khoáº£n; farmer gá»i sáº½ nháº­n 403. */
async function loadUsers() {
  try {
    const data = await apiRequest("/users");
    users = Array.isArray(data) ? data : [];
    renderUsers();
  } catch (error) {
    users = [];
    renderUsers();
    toast(`KhÃ´ng táº£i Ä‘Æ°á»£c danh sÃ¡ch tÃ i khoáº£n: ${error.message}`, "error");
  }
}

/** Váº½ báº£ng tÃ i khoáº£n (hiá»ƒn thá»‹ username + vai trÃ² tiáº¿ng Viá»‡t dáº¡ng badge). */
function renderUsers() {
  $("user-table-body").innerHTML = users
    .map((user) => {
      const isAdminRole = user.role === ROLE_ADMIN;
      const roleLabel = isAdminRole ? "Quáº£n trá»‹ viÃªn" : "Chá»§ nÃ´ng há»™ / HTX";
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

/* -------------------------------------- 11. Nháº­t kÃ½ hoáº¡t Ä‘á»™ng (chá»‰ admin) --- */
/**
 * GET /audit-logs (chá»‰ admin) -> váº½ báº£ng "Nháº­t kÃ½ hoáº¡t Ä‘á»™ng" vÃ 
 * cáº­p nháº­t tháº» thá»‘ng kÃª "Nháº­t kÃ½ hoáº¡t Ä‘á»™ng" trÃªn dashboard.
 */
async function loadAuditLogs({ silent = false } = {}) {
  const button = $("btn-load-audit");
  const errorBox = $("audit-error");

  // --- tráº¡ng thÃ¡i Ä‘ang táº£i ---
  setButtonLoading(button, true, "Äang táº£iâ€¦", "LÃ m má»›i nháº­t kÃ½");
  errorBox.hidden = true;
  $("audit-empty").hidden = true;
  $("audit-table-body").innerHTML =
    '<tr class="is-loading"><td class="is-center" colspan="6">Äang táº£i nháº­t kÃ½ hoáº¡t Ä‘á»™ngâ€¦</td></tr>';

  try {
    const data = await apiRequest("/audit-logs");
    auditLogs = Array.isArray(data) ? data : [];
    renderAuditLogs();

    if (!silent) {
      toast(
        auditLogs.length > 0
          ? `ÄÃ£ táº£i ${formatNumber(auditLogs.length)} báº£n ghi nháº­t kÃ½ hoáº¡t Ä‘á»™ng.`
          : "ChÆ°a cÃ³ hoáº¡t Ä‘á»™ng nÃ o Ä‘Æ°á»£c ghi nháº­n.",
        auditLogs.length > 0 ? "success" : "info"
      );
    }
  } catch (error) {
    auditLogs = [];
    renderAuditLogs();
    $("audit-empty").hidden = true;

    const denied = error.status === 401 || error.status === 403;
    errorBox.textContent = denied
      ? `KhÃ´ng cÃ³ quyá»n xem nháº­t kÃ½ hoáº¡t Ä‘á»™ng - má»¥c nÃ y chá»‰ dÃ nh cho Quáº£n trá»‹ viÃªn (${error.message})`
      : `KhÃ´ng táº£i Ä‘Æ°á»£c nháº­t kÃ½ hoáº¡t Ä‘á»™ng: ${error.message}`;
    errorBox.hidden = false;

    if (!silent || denied) {
      toast(errorBox.textContent, "error");
    }
  } finally {
    setButtonLoading(button, false, "Äang táº£iâ€¦", "LÃ m má»›i nháº­t kÃ½");
  }
}

/** Váº½ báº£ng nháº­t kÃ½ hoáº¡t Ä‘á»™ng (má»›i nháº¥t trÆ°á»›c) + cáº­p nháº­t tháº» thá»‘ng kÃª. */
function renderAuditLogs() {
  const actionLabels = {
    create: "ThÃªm má»›i",
    update: "Cáº­p nháº­t",
    delete: "XÃ³a",
  };
  const entityLabels = {
    farm: "VÃ¹ng trá»“ng",
    batch: "LÃ´ nÃ´ng sáº£n",
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

/** NhÃ£n ngÆ°á»i thá»±c hiá»‡n: Æ°u tiÃªn `username`, thiáº¿u thÃ¬ hiá»ƒn thá»‹ `#user_id`. */
function auditUserLabel(log) {
  return log.username ? log.username : `#${log.user_id}`;
}

/**
 * Sau má»—i thao tÃ¡c ghi thÃ nh cÃ´ng (táº¡o/sá»­a/xoÃ¡ vÃ¹ng trá»“ng hoáº·c lÃ´ nÃ´ng sáº£n),
 * admin tháº¥y lá»‹ch sá»­ má»›i ngay mÃ  khÃ´ng cáº§n báº¥m nÃºt: gá»i im láº·ng Ä‘á»ƒ báº£ng log vÃ 
 * tháº» thá»‘ng kÃª khÃ´ng bá»‹ cÅ©. Farmer khÃ´ng gá»i Ä‘Æ°á»£c `GET /audit-logs` nÃªn bá» qua.
 */
async function refreshAuditLogsIfAdmin() {
  if (!isAdmin()) {
    return;
  }
  await loadAuditLogs({ silent: true });
}

/* --------------------------------------------------------- 12. Sá»± kiá»‡n --- */
function bindEvents() {
  $("login-form").addEventListener("submit", handleLoginSubmit);
  $("btn-logout").addEventListener("click", handleLogout);
  $("farm-form").addEventListener("submit", handleFarmSubmit);
  $("batch-form").addEventListener("submit", handleBatchSubmit);
  $("farm-cancel").addEventListener("click", () => cancelEdit("farm"));
  $("batch-cancel").addEventListener("click", () => cancelEdit("batch"));
  $("btn-reload").addEventListener("click", () => reloadAll());
  $("btn-load-audit").addEventListener("click", () => loadAuditLogs());

  // ÄÄƒng nháº­p nhanh cho tÃ i khoáº£n demo (Quáº£n trá»‹ viÃªn & Chá»§ nÃ´ng há»™)
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

  // Chuyá»ƒn Ä‘á»•i hiá»ƒn thá»‹ Tháº» / Báº£ng cho Thá»­a Ä‘áº¥t
  const btnViewCards = $("btn-view-cards");
  if (btnViewCards) {
    btnViewCards.addEventListener("click", () => setFarmViewMode("cards"));
  }
  const btnViewTable = $("btn-view-table");
  if (btnViewTable) {
    btnViewTable.addEventListener("click", () => setFarmViewMode("table"));
  }

  // Cá»™t "Thao tÃ¡c" (Sá»­a / XoÃ¡) trÃªn tháº» vÃ  báº£ng dÃ¹ng event delegation
  const cardsContainer = $("farm-cards-container");
  if (cardsContainer) {
    cardsContainer.addEventListener("click", handleTableAction);
  }
  $("farm-table-body").addEventListener("click", handleTableAction);
  $("batch-table-body").addEventListener("click", handleTableAction);

  // Báº£ng vÃ  nÃºt cá»§a LÃ´ chá» xÃ¡c nháº­n bÃ n giao
  const pendingTbody = $("pending-handovers-table-body");
  if (pendingTbody) {
    pendingTbody.addEventListener("click", handleTableAction);
  }
  const btnRefreshPending = $("btn-refresh-pending");
  if (btnRefreshPending) {
    btnRefreshPending.addEventListener("click", async () => {
      await loadPendingHandovers();
      toast("ÄÃ£ lÃ m má»›i danh sÃ¡ch lÃ´ chá» xÃ¡c nháº­n.", "info");
    });
  }

  // Modal bÃ n giao sá»± kiá»‡n
  const btnCloseHandover = $("btn-close-handover-modal");
  if (btnCloseHandover) btnCloseHandover.addEventListener("click", closeHandoverModal);
  const btnCancelHandover = $("btn-cancel-handover");
  if (btnCancelHandover) btnCancelHandover.addEventListener("click", closeHandoverModal);
  const handoverForm = $("handover-form");
  if (handoverForm) handoverForm.addEventListener("submit", handleHandoverSubmit);

  // Modal tá»« chá»‘i sá»± kiá»‡n
  const btnCloseReject = $("btn-close-reject-modal");
  if (btnCloseReject) btnCloseReject.addEventListener("click", closeRejectModal);
  const btnCancelReject = $("btn-cancel-reject");
  if (btnCancelReject) btnCancelReject.addEventListener("click", closeRejectModal);
  const rejectForm = $("reject-form");
  if (rejectForm) rejectForm.addEventListener("submit", handleRejectSubmit);
  const rejectReasonInput = $("reject-reason");
  if (rejectReasonInput) rejectReasonInput.addEventListener("input", updateRejectCounter);

  // ÄÃ³ng modal khi báº¥m ra ngoÃ i ná»n backdrop
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

  // NÃºt Ä‘Ã³ng trang chi tiáº¿t lÃ´ S-25
  const btnCloseDetail = $("btn-close-batch-detail");
  if (btnCloseDetail) btnCloseDetail.addEventListener("click", closeBatchDetail);

  // [T-59] Header buttons: xem timeline / ancestors
  const btnHeaderTimeline = $("btn-view-batch-timeline");
  if (btnHeaderTimeline) {
    btnHeaderTimeline.addEventListener("click", () => {
      if (currentBatchId !== null) openBatchTimelineModal(currentBatchId);
    });
  }
  const btnHeaderAncestors = $("btn-view-batch-ancestors");
  if (btnHeaderAncestors) {
    btnHeaderAncestors.addEventListener("click", () => {
      if (currentBatchId !== null) openBatchAncestorsModal(currentBatchId);
    });
  }

  // [T-59] Nav bar buttons (inside batch-detail-body)
  const btnNavTimeline = $("btn-detail-nav-timeline");
  if (btnNavTimeline) {
    btnNavTimeline.addEventListener("click", () => {
      if (currentBatchId !== null) openBatchTimelineModal(currentBatchId);
    });
  }
  const btnNavAncestors = $("btn-detail-nav-ancestors");
  if (btnNavAncestors) {
    btnNavAncestors.addEventListener("click", () => {
      if (currentBatchId !== null) openBatchAncestorsModal(currentBatchId);
    });
  }

  // [T-59] Modal timeline: Ä‘Ã³ng báº±ng nÃºt Ã— vÃ  click backdrop
  const btnCloseTimeline = $("btn-close-timeline-modal");
  if (btnCloseTimeline) btnCloseTimeline.addEventListener("click", closeBatchTimelineModal);
  const modalTimeline = $("modal-batch-timeline");
  if (modalTimeline) {
    modalTimeline.addEventListener("click", (e) => {
      if (e.target === modalTimeline) closeBatchTimelineModal();
    });
  }

  // [T-59] Modal ancestors: Ä‘Ã³ng báº±ng nÃºt Ã— vÃ  click backdrop
  const btnCloseAncestors = $("btn-close-ancestors-modal");
  if (btnCloseAncestors) btnCloseAncestors.addEventListener("click", closeBatchAncestorsModal);
  const modalAncestors = $("modal-batch-ancestors");
  if (modalAncestors) {
    modalAncestors.addEventListener("click", (e) => {
      if (e.target === modalAncestors) closeBatchAncestorsModal();
    });
  }
}

/* ------------------------------------------- 11. BÃ n giao lÃ´ hÃ ng (SCRUM-27/28) --- */
/** GET /organizations -> danh sÃ¡ch tá»• chá»©c Ä‘á»ƒ chá»n bÃªn nháº­n */
async function loadOrganizations() {
  if (session === null) return;
  try {
    const data = await apiRequest("/organizations");
    organizations = Array.isArray(data) ? data : [];
  } catch (error) {
    console.warn("KhÃ´ng táº£i Ä‘Æ°á»£c danh sÃ¡ch tá»• chá»©c:", error.message);
  }
}

/** GET /handovers/pending -> danh sÃ¡ch bÃ n giao gá»­i Ä‘áº¿n tá»• chá»©c cá»§a user */
async function loadPendingHandovers() {
  if (session === null) {
    pendingHandovers = [];
    renderPendingHandovers();
    return;
  }
  try {
    const data = await apiRequest("/handovers/pending");
    pendingHandovers = Array.isArray(data) ? data : [];
    renderPendingHandovers();
  } catch (error) {
    console.warn("KhÃ´ng táº£i Ä‘Æ°á»£c danh sÃ¡ch lÃ´ chá» xÃ¡c nháº­n:", error.message);
    pendingHandovers = [];
    renderPendingHandovers();
  }
}

/** Váº½ danh sÃ¡ch cÃ¡c lÃ´ hÃ ng Ä‘ang chá» xÃ¡c nháº­n bÃ n giao */
function renderPendingHandovers() {
  const tbody = $("pending-handovers-table-body");
  if (!tbody) return;

  tbody.innerHTML = pendingHandovers
    .map((h) => {
      const productName = h.batch_product_name || `LÃ´ #${h.batch_id}`;
      const fromOrg = h.from_org_name || `Tá»• chá»©c #${h.from_org_id}`;
      const note = h.notes || h.note || "â€”";
      return `
      <tr>
        <td class="id-cell">#${escapeHtml(h.batch_id)}</td>
        <td><strong>${escapeHtml(productName)}</strong></td>
        <td class="is-right">${formatNumber(h.batch_quantity)}</td>
        <td><span class="badge badge--org">ðŸ¢ ${escapeHtml(fromOrg)}</span></td>
        <td>${escapeHtml(formatDateTime(h.created_at))}</td>
        <td>${escapeHtml(note)}</td>
        <td class="is-center">
          <div class="table__actions" style="justify-content: center;">
            <button class="btn btn--success btn--sm" type="button"
                    data-action="accept-handover" data-id="${escapeHtml(h.id)}">
              âœ“ XÃ¡c nháº­n nháº­n lÃ´
            </button>
            <button class="btn btn--danger btn--sm" type="button"
                    data-action="reject-handover" data-id="${escapeHtml(h.id)}">
              âœ• Tá»« chá»‘i
            </button>
          </div>
        </td>
      </tr>`;
    })
    .join("");

  const countBadge = $("badge-pending-count");
  if (countBadge) {
    countBadge.textContent = `${pendingHandovers.length} lÃ´`;
    countBadge.className = pendingHandovers.length > 0 ? "badge badge--warning" : "badge badge--muted";
  }
  const statPending = $("stat-pending-handovers");
  if (statPending) {
    statPending.textContent = formatNumber(pendingHandovers.length);
  }
  const emptyEl = $("pending-handovers-empty");
  if (emptyEl) {
    emptyEl.hidden = pendingHandovers.length > 0;
  }
  renderStats();
}

/** Má»Ÿ modal bÃ n giao lÃ´ hÃ ng */
function openHandoverModal(batchId) {
  const batch = batches.find((item) => item.id === batchId);
  if (!batch) {
    toast(`KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n #${batchId}.`, "error");
    return;
  }

  $("handover-batch-id").value = String(batch.id);
  $("handover-note").value = "";

  const summary = $("modal-handover-summary");
  if (summary) {
    summary.innerHTML = `
      <div><strong>LÃ´ hÃ ng:</strong> #${escapeHtml(batch.id)} â€” <strong>${escapeHtml(batch.product_name)}</strong></div>
      <div><strong>Khá»‘i lÆ°á»£ng:</strong> ${formatNumber(batch.quantity)} kg Â· <strong>VÃ¹ng xuáº¥t xá»©:</strong> ${escapeHtml(farmLabel(batch.farm_id))}</div>
      <div><strong>Tá»• chá»©c bÃ n giao:</strong> ${escapeHtml(session?.organization_name || "Tá»• chá»©c cá»§a báº¡n")}</div>
    `;
  }

  // Äá»• danh sÃ¡ch tá»• chá»©c khÃ¡c vÃ o select
  const select = $("handover-to-org");
  if (select) {
    const targetOrgs = organizations.filter((org) => org.id !== session?.organization_id);
    if (targetOrgs.length === 0) {
      select.innerHTML = '<option value="">â€” ChÆ°a cÃ³ tá»• chá»©c Ä‘á»‘i tÃ¡c khÃ¡c nÃ o trong há»‡ thá»‘ng â€”</option>';
      select.disabled = true;
    } else {
      select.disabled = false;
      select.innerHTML =
        '<option value="">â€” Chá»n tá»• chá»©c tiáº¿p nháº­n â€”</option>' +
        targetOrgs
          .map((org) => `<option value="${escapeHtml(org.id)}">${escapeHtml(org.name)} (${escapeHtml(org.code)})</option>`)
          .join("");
    }
  }

  $("modal-handover").hidden = false;
}

/** ÄÃ³ng modal bÃ n giao */
function closeHandoverModal() {
  $("modal-handover").hidden = true;
  $("handover-form").reset();
}

/** Xá»­ lÃ½ gá»­i form bÃ n giao */
async function handleHandoverSubmit(event) {
  event.preventDefault();
  const batchId = Number($("handover-batch-id").value);
  const toOrgId = Number($("handover-to-org").value);
  const note = $("handover-note").value.trim() || null;

  if (!toOrgId) {
    toast("Vui lÃ²ng chá»n tá»• chá»©c tiáº¿p nháº­n lÃ´ hÃ ng!", "error");
    return;
  }

  const button = $("btn-submit-handover");
  setButtonLoading(button, true, "Äang gá»­iâ€¦", "XÃ¡c nháº­n gá»­i bÃ n giao");

  try {
    await apiRequest(`/batches/${batchId}/handover`, {
      method: "POST",
      body: { to_org_id: toOrgId, note: note },
    });
    toast(`ÄÃ£ gá»­i yÃªu cáº§u bÃ n giao lÃ´ nÃ´ng sáº£n #${batchId} thÃ nh cÃ´ng!`, "success");
    closeHandoverModal();
    await loadBatches();
    await loadPendingHandovers();
  } catch (error) {
    toast(`BÃ n giao tháº¥t báº¡i: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Äang gá»­iâ€¦", "XÃ¡c nháº­n gá»­i bÃ n giao");
  }
}

/** Má»Ÿ modal tá»« chá»‘i tiáº¿p nháº­n */
function openRejectModal(handoverId) {
  $("reject-handover-id").value = String(handoverId);
  $("reject-reason").value = "";
  updateRejectCounter();
  $("modal-reject").hidden = false;
  $("reject-reason").focus();
}

/** ÄÃ³ng modal tá»« chá»‘i tiáº¿p nháº­n */
function closeRejectModal() {
  $("modal-reject").hidden = true;
  $("reject-form").reset();
}

/** Cáº­p nháº­t bá»™ Ä‘áº¿m kÃ½ tá»± lÃ½ do tá»« chá»‘i */
function updateRejectCounter() {
  const reason = $("reject-reason").value.trim();
  const counter = $("reject-reason-counter");
  if (counter) {
    counter.textContent = `ÄÃ£ nháº­p: ${reason.length} / tá»‘i thiá»ƒu 10 kÃ½ tá»±`;
    counter.style.color = reason.length >= 10 ? "var(--color-primary)" : "var(--color-danger)";
  }
}

/** Xá»­ lÃ½ gá»­i form tá»« chá»‘i tiáº¿p nháº­n */
async function handleRejectSubmit(event) {
  event.preventDefault();
  const handoverId = Number($("reject-handover-id").value);
  const reason = $("reject-reason").value.trim();

  if (reason.length < 10) {
    toast("LÃ½ do tá»« chá»‘i báº¯t buá»™c pháº£i cÃ³ tá»‘i thiá»ƒu 10 kÃ½ tá»±!", "error");
    $("reject-reason").focus();
    return;
  }

  const button = $("btn-submit-reject");
  setButtonLoading(button, true, "Äang xá»­ lÃ½â€¦", "XÃ¡c nháº­n tá»« chá»‘i");

  try {
    await apiRequest(`/handovers/${handoverId}/respond`, {
      method: "POST",
      body: { action: "REJECT", reject_reason: reason },
    });
    toast("ÄÃ£ tá»« chá»‘i tiáº¿p nháº­n lÃ´ hÃ ng.", "info");
    closeRejectModal();
    await loadPendingHandovers();
    await loadBatches();
  } catch (error) {
    toast(`Tá»« chá»‘i tháº¥t báº¡i: ${error.message}`, "error");
  } finally {
    setButtonLoading(button, false, "Äang xá»­ lÃ½â€¦", "XÃ¡c nháº­n tá»« chá»‘i");
  }
}

/** Tiáº¿p nháº­n lÃ´ hÃ ng (ACCEPT) */
async function handleAcceptHandover(handoverId) {
  const h = pendingHandovers.find((item) => item.id === handoverId);
  const batchName = h ? (h.batch_product_name || `lÃ´ #${h.batch_id}`) : `lÃ´ hÃ ng #${handoverId}`;

  if (!window.confirm(`Báº¡n cÃ³ cháº¯c cháº¯n muá»‘n xÃ¡c nháº­n tiáº¿p nháº­n ${batchName} vá» tá»• chá»©c cá»§a mÃ¬nh?`)) {
    return;
  }

  try {
    await apiRequest(`/handovers/${handoverId}/respond`, {
      method: "POST",
      body: { action: "ACCEPT" },
    });
    toast(`ÄÃ£ tiáº¿p nháº­n ${batchName} thÃ nh cÃ´ng!`, "success");
    await loadPendingHandovers();
    await loadBatches();
  } catch (error) {
    toast(`Tiáº¿p nháº­n lÃ´ hÃ ng tháº¥t báº¡i: ${error.message}`, "error");
  }
}

/** Huá»· cháº¿ Ä‘á»™ sá»­a cá»§a form vÃ¹ng trá»“ng / lÃ´ nÃ´ng sáº£n (nÃºt "Huá»· sá»­a"). */
function cancelEdit(entity) {
  if (entity === "farm") {
    resetFarmForm();
    renderFarms();
    toast("ÄÃ£ huá»· cháº¿ Ä‘á»™ sá»­a vÃ¹ng trá»“ng.", "info");
    return;
  }

  resetBatchForm();
  renderBatches();
  toast("ÄÃ£ huá»· cháº¿ Ä‘á»™ sá»­a lÃ´ nÃ´ng sáº£n.", "info");
}

/** [S-25] Xem trang chi tiáº¿t má»™t lÃ´ nÃ´ng sáº£n theo batchId. */
async function openBatchDetail(batchId) {
  const card = $("batch-detail-card");
  const loading = $("batch-detail-loading");
  const notFound = $("batch-detail-not-found");
  const errorEl = $("batch-detail-error");
  const body = $("batch-detail-body");

  if (!card) return;

  // [T-59] LÆ°u láº¡i batch ID Ä‘ang xem Ä‘á»ƒ header buttons dÃ¹ng Ä‘Ãºng batch.
  currentBatchId = batchId;

  card.hidden = false;
  loading.hidden = false;
  notFound.hidden = true;
  errorEl.hidden = true;
  body.hidden = true;

  card.scrollIntoView({ behavior: "smooth", block: "start" });

  try {
    const data = await apiRequest(`/batches/${batchId}`);
    loading.hidden = true;

    if (!data || !data.id) {
      notFound.hidden = false;
      return;
    }

    $("batch-detail-header-title").textContent = `ðŸ“¦ Trang chi tiáº¿t lÃ´ nÃ´ng sáº£n #${data.id} - ${data.product_name}`;
    $("bd-id").textContent = `#${data.id}`;
    $("bd-product-name").textContent = data.product_name || "N/A";
    $("bd-initial-qty").textContent = formatNumber(data.initial_quantity || data.quantity);
    $("bd-remaining-qty").textContent = formatNumber(data.remaining_quantity != null ? data.remaining_quantity : (data.quantity || 0));
    $("bd-unit-1").textContent = data.unit || "kg";
    $("bd-unit-2").textContent = data.unit || "kg";
    $("bd-status").textContent = data.status || "Äang lÆ°u kho";
    $("bd-harvest-date").textContent = formatDate(data.harvest_date);

    $("bd-current-org").textContent = data.current_org_name ? `ðŸ¢ ${data.current_org_name}` : "Tá»• chá»©c chÆ°a xÃ¡c Ä‘á»‹nh";
    $("bd-farm-name").textContent = data.farm_name || farmLabel(data.farm_id) || "N/A";
    $("bd-farm-location").textContent = data.farm_location || "N/A";

    // LÃ´ máº¹ trá»±c tiáº¿p
    const parentContainer = $("bd-parent-container");
    if (data.parent && data.parent.id) {
      const p = data.parent;
      parentContainer.innerHTML = `
        <div class="tree-card">
          <div class="tree-card__info">
            <span class="tree-card__code">ðŸŒ± LÃ´ máº¹ trá»±c tiáº¿p: #${escapeHtml(p.id)}</span>
            <span class="tree-card__name">${escapeHtml(p.product_name)}</span>
            <span class="tree-card__meta">Khá»‘i lÆ°á»£ng: ${formatNumber(p.remaining_quantity != null ? p.remaining_quantity : p.quantity)} / ${formatNumber(p.quantity)} ${escapeHtml(p.unit || "kg")} Â· Tráº¡ng thÃ¡i: ${escapeHtml(p.status || "Äang lÆ°u kho")} Â· NÆ¡i giá»¯: ${escapeHtml(p.current_org_name || "N/A")}</span>
          </div>
          <button class="btn btn--outline-primary btn--sm tree-card__action" type="button" onclick="openBatchDetail(${p.id})">
            ðŸ‘ï¸ Xem lÃ´ máº¹ #${p.id} â†—
          </button>
        </div>
      `;
    } else {
      parentContainer.innerHTML = `<div class="no-tree-msg">KhÃ´ng cÃ³ lÃ´ máº¹</div>`;
    }

    // LÃ´ con trá»±c tiáº¿p
    const childrenContainer = $("bd-children-container");
    if (data.children && data.children.length > 0) {
      childrenContainer.innerHTML = data.children.map((c) => `
        <div class="tree-card">
          <div class="tree-card__info">
            <span class="tree-card__code">ðŸŒ¿ LÃ´ con trá»±c tiáº¿p: #${escapeHtml(c.id)}</span>
            <span class="tree-card__name">${escapeHtml(c.product_name)}</span>
            <span class="tree-card__meta">Khá»‘i lÆ°á»£ng: ${formatNumber(c.remaining_quantity != null ? c.remaining_quantity : c.quantity)} / ${formatNumber(c.quantity)} ${escapeHtml(c.unit || "kg")} Â· Tráº¡ng thÃ¡i: ${escapeHtml(c.status || "Äang lÆ°u kho")} Â· NÆ¡i giá»¯: ${escapeHtml(c.current_org_name || "N/A")}</span>
          </div>
          <button class="btn btn--outline-primary btn--sm tree-card__action" type="button" onclick="openBatchDetail(${c.id})">
            ðŸ‘ï¸ Xem lÃ´ con #${c.id} â†—
          </button>
        </div>
      `).join("");
    } else {
      childrenContainer.innerHTML = `<div class="no-tree-msg">KhÃ´ng cÃ³ lÃ´ con</div>`;
    }

    body.hidden = false;
  } catch (error) {
    loading.hidden = true;
    if (error.message && error.message.includes("404")) {
      notFound.hidden = false;
    } else {
      errorEl.hidden = false;
      errorEl.textContent = `âš ï¸ ÄÃ£ xáº£y ra lá»—i khi láº¥y chi tiáº¿t lÃ´ nÃ´ng sáº£n: ${error.message}`;
    }
  }
}

/** ÄÃ³ng trang chi tiáº¿t lÃ´ */
function closeBatchDetail() {
  const card = $("batch-detail-card");
  if (card) card.hidden = true;
}

/* ------------------------------------------- [T-59] DÃ²ng thá»i gian & Tá»• tiÃªn --- */

/** Má»Ÿ modal xem dÃ²ng thá»i gian (timeline events) cá»§a má»™t lÃ´. */
async function openBatchTimelineModal(batchId) {
  const modal = $("modal-batch-timeline");
  const loadingEl = $("modal-timeline-loading");
  const errorEl = $("modal-timeline-error");
  const emptyEl = $("modal-timeline-empty");
  const listEl = $("modal-timeline-list");
  const labelEl = $("modal-timeline-batch-label");

  if (!modal) return;
  modal.hidden = false;

  loadingEl.hidden = false;
  errorEl.hidden = true;
  emptyEl.hidden = true;
  listEl.hidden = true;
  listEl.innerHTML = "";
  if (labelEl) labelEl.textContent = `LÃ´ nÃ´ng sáº£n #${batchId}`;

  try {
    const events = await apiRequest(`/batches/${batchId}/events`);
    loadingEl.hidden = true;

    if (!Array.isArray(events) || events.length === 0) {
      emptyEl.hidden = false;
      return;
    }

    listEl.innerHTML = events.map((ev, idx) => `
      <div class="timeline-item">
        <div class="timeline-item__dot">${idx + 1}</div>
        <div class="timeline-item__body">
          <div class="timeline-item__type">${escapeHtml(ev.event_type || "EVENT")}</div>
          <div class="timeline-item__data">${escapeHtml(ev.event_data || "")}</div>
          <div class="timeline-item__time">
            ${ev.timestamp ? formatDate(ev.timestamp) : ""}
            ${ev.user_id ? ` Â· NgÆ°á»i ghi: #${ev.user_id}` : ""}
          </div>
        </div>
      </div>
    `).join("");
    listEl.hidden = false;
  } catch (err) {
    loadingEl.hidden = true;
    errorEl.hidden = false;
    errorEl.textContent = `âš ï¸ KhÃ´ng thá»ƒ táº£i dÃ²ng thá»i gian: ${err.message}`;
  }
}

/** ÄÃ³ng modal dÃ²ng thá»i gian. */
function closeBatchTimelineModal() {
  const modal = $("modal-batch-timeline");
  if (modal) modal.hidden = true;
}

/** Má»Ÿ modal xem danh sÃ¡ch tá»• tiÃªn (ancestors) cá»§a má»™t lÃ´. */
async function openBatchAncestorsModal(batchId) {
  const modal = $("modal-batch-ancestors");
  const loadingEl = $("modal-ancestors-loading");
  const errorEl = $("modal-ancestors-error");
  const emptyEl = $("modal-ancestors-empty");
  const listEl = $("modal-ancestors-list");
  const labelEl = $("modal-ancestors-batch-label");

  if (!modal) return;
  modal.hidden = false;

  loadingEl.hidden = false;
  errorEl.hidden = true;
  emptyEl.hidden = true;
  listEl.hidden = true;
  listEl.innerHTML = "";
  if (labelEl) labelEl.textContent = `LÃ´ nÃ´ng sáº£n #${batchId}`;

  try {
    const data = await apiRequest(`/batches/${batchId}/ancestors`);
    loadingEl.hidden = true;

    const ancestors = Array.isArray(data.ancestors) ? data.ancestors : [];

    if (ancestors.length === 0) {
      emptyEl.hidden = false;
      return;
    }

    const genLabel = (gen) => {
      if (gen === 1) return "LÃ´ máº¹ trá»±c tiáº¿p";
      if (gen === 2) return "LÃ´ bÃ ";
      if (gen === 3) return "LÃ´ cá»‘";
      return `Tháº¿ há»‡ ${gen}`;
    };

    listEl.innerHTML = ancestors.map((anc) => `
      <div class="ancestor-item">
        <span class="ancestor-item__gen">${genLabel(anc.generation || 1)}</span>
        <div class="ancestor-item__info">
          <div class="ancestor-item__name">
            #${escapeHtml(String(anc.id))} Â· ${escapeHtml(anc.product_name || anc.product || "")}
          </div>
          <div class="ancestor-item__meta">
            KL cÃ²n láº¡i: ${formatNumber(anc.remaining_quantity)} / ${formatNumber(anc.quantity)} ${escapeHtml(anc.unit || "kg")}
            Â· ${escapeHtml(anc.current_org_name || "N/A")}
          </div>
        </div>
        <div class="ancestor-item__action">
          <button class="btn btn--outline-primary btn--sm" type="button" onclick="openBatchDetail(${anc.id})">
            ðŸ‘ï¸ Xem #${anc.id}
          </button>
        </div>
      </div>
    `).join("");
    listEl.hidden = false;
  } catch (err) {
    loadingEl.hidden = true;
    if (err.message && err.message.includes("404")) {
      errorEl.hidden = false;
      errorEl.textContent = "âŒ KhÃ´ng tÃ¬m tháº¥y lÃ´ nÃ´ng sáº£n nÃ y.";
    } else {
      errorEl.hidden = false;
      errorEl.textContent = `âš ï¸ KhÃ´ng thá»ƒ táº£i danh sÃ¡ch tá»• tiÃªn: ${err.message}`;
    }
  }
}

/** ÄÃ³ng modal danh sÃ¡ch tá»• tiÃªn. */
function closeBatchAncestorsModal() {
  const modal = $("modal-batch-ancestors");
  if (modal) modal.hidden = true;
}

/**
 * Xá»­ lÃ½ click á»Ÿ cá»™t "Thao tÃ¡c" (Chi tiáº¿t, Sá»­a, XoÃ¡, BÃ n giao, Tiáº¿p nháº­n, Tá»« chá»‘i).
 */
function handleTableAction(event) {
  const button = event.target.closest("button[data-action]");
  if (button === null) {
    return;
  }

  const id = Number(button.dataset.id);
  const entity = button.dataset.entity;
  const action = button.dataset.action;

  if (action === "view-detail") {
    openBatchDetail(id);
    return;
  }

  if (action === "open-handover") {
    openHandoverModal(id);
    return;
  }

  if (action === "accept-handover") {
    handleAcceptHandover(id);
    return;
  }

  if (action === "reject-handover") {
    openRejectModal(id);
    return;
  }

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
      toast("Chá»‰ tÃ i khoáº£n Quáº£n trá»‹ viÃªn má»›i cÃ³ quyá»n xoÃ¡ dá»¯ liá»‡u.", "error");
      return;
    }
    if (entity === "farm") {
      deleteFarm(id);
    } else {
      deleteBatch(id);
    }
  }
}

/** Táº£i dá»¯ liá»‡u dÃ¹ng chung cho giao diá»‡n sau khi Ä‘Äƒng nháº­p (theo phÃ¢n quyá»n). */
async function loadAllData() {
  await checkHealth();
  await loadOrganizations();
  await loadFarms();
  await loadBatches();
  await loadPendingHandovers();
  if (isAdmin()) {
    await loadUsers();
    await loadAuditLogs({ silent: true });
  }
}

/** Táº£i láº¡i toÃ n bá»™ dá»¯ liá»‡u; `silent = true` Ä‘á»ƒ bá» toast tá»•ng káº¿t. */
async function reloadAll({ silent = false } = {}) {
  const button = $("btn-reload");
  setButtonLoading(button, true, "Äang táº£iâ€¦", "Táº£i láº¡i dá»¯ liá»‡u");

  await loadAllData();

  setButtonLoading(button, false, "Äang táº£iâ€¦", "Táº£i láº¡i dá»¯ liá»‡u");
  if (!silent) {
    const parts = [`${farms.length} vÃ¹ng trá»“ng`, `${batches.length} lÃ´ nÃ´ng sáº£n`];
    if (pendingHandovers.length > 0) {
      parts.push(`${pendingHandovers.length} lÃ´ chá» nháº­n`);
    }
    if (isAdmin()) {
      parts.push(`${auditLogs.length} nháº­t kÃ½ hoáº¡t Ä‘á»™ng`);
    }
    toast(`ÄÃ£ cáº­p nháº­t dá»¯ liá»‡u: ${parts.join(", ")}.`, "info");
  }
}

/* ------------------------------------------------------- 13. Khá»Ÿi Ä‘á»™ng --- */
/**
 * Khá»Ÿi Ä‘á»™ng á»©ng dá»¥ng:
 * 1. gáº¯n sá»± kiá»‡n + kiá»ƒm tra backend Ä‘ang cháº¡y;
 * 2. náº¿u tab cÃ²n phiÃªn Ä‘Äƒng nháº­p cÅ© (sessionStorage) thÃ¬ xÃ¡c thá»±c láº¡i vá»›i
 *    backend rá»“i vÃ o tháº³ng giao diá»‡n;
 * 3. ngÆ°á»£c láº¡i, hiá»‡n mÃ n hÃ¬nh Ä‘Äƒng nháº­p.
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
      toast(`ÄÃ£ khÃ´i phá»¥c phiÃªn Ä‘Äƒng nháº­p: ${data.username}.`, "info");
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

