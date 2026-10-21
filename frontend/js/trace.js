/* S-46 & S-48 public QR trace page. Only public fields returned, no login required. */
"use strict";

(function () {
  const statusEl = document.getElementById("status");
  const contentEl = document.getElementById("content");

  function showError(message) {
    statusEl.hidden = false;
    statusEl.className = "error";
    statusEl.textContent = message;
    contentEl.hidden = true;
  }

  function getBatchCode(url) {
    const parsed = new URL(url, window.location.href);
    const queryCode = parsed.searchParams.get("batch_code");
    if (queryCode && queryCode.trim()) return queryCode.trim();
    const path = parsed.pathname.replace(/\/+$/, "");
    const last = path.split("/").pop() || "";
    if (!last || /\.html?$/i.test(last)) return "";
    try {
      return decodeURIComponent(last).trim();
    } catch (_error) {
      return "";
    }
  }

  async function getApiBase() {
    const configured = window.AGRITRACE_CONFIG && window.AGRITRACE_CONFIG.apiBase;
    if (typeof configured === "string" && configured.trim()) return configured.trim();

    // A deploy may provide frontend/config.json with a different API origin.
    // An empty apiBase intentionally means the API is served from this origin.
    try {
      const response = await fetch(new URL("config.json", window.location.href), {
        cache: "no-store",
        headers: { Accept: "application/json" }
      });
      if (response.ok) {
        const config = await response.json();
        if (config && typeof config.apiBase === "string" && config.apiBase.trim()) {
          return config.apiBase.trim();
        }
        if (config && config.apiBase === "") return window.location.origin;
      }
    } catch (_error) {
      // Continue to the same-origin default below.
    }
    return window.location.origin;
  }

  function putText(id, value) {
    document.getElementById(id).textContent =
      value === null || value === undefined || value === ""
        ? "Chưa có thông tin công khai"
        : String(value);
  }

  function formatVnDateTime(value) {
    if (!value) return "";
    const str = String(value).trim();
    const match = str.match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/);
    if (!match) return str;
    const [, y, m, d, h, min, s] = match;
    // Backend SQLite stores naive UTC datetime (event_now). Convert UTC to Vietnam local time (ICT, UTC+7).
    const utcMs = Date.UTC(Number(y), Number(m) - 1, Number(d), Number(h), Number(min), Number(s || 0));
    const vnDate = new Date(utcMs + 7 * 60 * 60 * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(vnDate.getUTCDate())}/${pad(vnDate.getUTCMonth() + 1)}/${vnDate.getUTCFullYear()} ` +
      `${pad(vnDate.getUTCHours())}:${pad(vnDate.getUTCMinutes())}:${pad(vnDate.getUTCSeconds())}`;
  }

  function formatVnDate(value) {
    if (!value) return "";
    const str = String(value).trim();
    const match = str.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return str;
    const [, y, m, d] = match;
    return `${d}/${m}/${y}`;
  }

  function renderRoots(items) {
    const list = document.getElementById("roots");
    if (!list) return;
    list.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
      const item = document.createElement("li");
      item.textContent = "Chưa có dữ liệu lô nguồn bổ sung.";
      list.appendChild(item);
      return;
    }
    items.forEach((root) => {
      const item = document.createElement("li");
      item.textContent = [
        root.batch_code, root.product_name, formatVnDate(root.harvest_date) || root.harvest_date,
        root.location, root.farm_name, root.plot_name
      ].filter(Boolean).join(" · ");
      list.appendChild(item);
    });
  }

  function renderMilestones(items) {
    const list = document.getElementById("milestones");
    if (!list) return;
    list.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
      const item = document.createElement("li");
      item.textContent = "Chưa có dữ liệu công đoạn bổ sung.";
      list.appendChild(item);
      return;
    }
    items.forEach((m) => {
      const item = document.createElement("li");
      item.className = "milestone-item";
      const header = document.createElement("b");
      header.textContent = "Bước " + m.step + ": " + m.stage;
      const meta = document.createElement("div");
      meta.className = "muted";
      const formattedTime = m.timestamp ? formatVnDateTime(m.timestamp) : null;
      meta.textContent = [
        "Đơn vị: " + m.organization_type,
        formattedTime ? "Thời gian: " + formattedTime : null,
        m.status ? "Trạng thái: " + m.status : null
      ].filter(Boolean).join(" · ");
      item.appendChild(header);
      item.appendChild(meta);
      list.appendChild(item);
    });
  }

  async function loadPublicTrace() {
    // Never leave the initial loading message indefinitely.
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      controller.abort();
      showError("Hết thời gian chờ khi tải dữ liệu. Vui lòng thử lại sau.");
    }, 15000);
    try {
      const code = getBatchCode(window.location.href);
      if (!code) {
        showError("Đường dẫn không có mã lô (batch_code).");
        return;
      }
      const base = await getApiBase();
      const apiUrl = new URL(
        "/public/trace/" + encodeURIComponent(code),
        base.endsWith("/") ? base : base + "/"
      );
      const response = await fetch(apiUrl.href, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: controller.signal
      });
      let data = {};
      try { data = await response.json(); } catch (_error) { /* handled below */ }
      if (!response.ok) {
        if (response.status === 404) throw new Error("Không tìm thấy lô hàng có mã " + code + ".");
        throw new Error(data.detail || "Không thể tải thông tin truy xuất (HTTP " + response.status + ").");
      }

      function formatPublicBatchStatus(s) {
        if (!s) return "Chưa có thông tin";
        const map = {
          ACTIVE: "Đang lưu hành",
          RECALLED: "Đã thu hồi",
          QUARANTINED: "Đang cách ly kiểm định",
          SPLIT: "Đã phân tách",
          MERGED: "Đã gộp lô",
          CONSUMED: "Đã tiêu thụ",
          IN_TRANSIT: "Đang vận chuyển",
        };
        return map[String(s).toUpperCase()] || s;
      }

      putText("code", data.batch_code);
      putText("product", data.product_name);
      putText("date", formatVnDate(data.harvest_date) || data.harvest_date);
      putText("batch-status", formatPublicBatchStatus(data.status));
      putText("location", data.origin && data.origin.location);
      putText("farm", [
        data.origin && data.origin.farm_name,
        data.origin && data.origin.plot_name
      ].filter(Boolean).join(" · "));
      renderRoots(data.root_batches);
      renderMilestones(data.milestones);
      const recall = document.getElementById("recall-warning");
      if (recall) {
        recall.hidden = !data.recall_warning;
        recall.innerHTML = data.recall_warning
          ? `<strong>⚠️ CẢNH BÁO THU HỒI / CÁCH LY:</strong> ${escapePublicHtml(data.recall_message || "Lô hàng nằm trong danh mục thu hồi hoặc đang bị cách ly kiểm tra chất lượng.")}`
          : "";
      }
      contentEl.hidden = false;
      statusEl.hidden = true;
      await verifyPublicIntegrity(base, code);
    } catch (error) {
      if (error && error.name === "AbortError") {
        showError("Hết thời gian chờ khi tải dữ liệu. Vui lòng thử lại sau.");
      } else {
        showError(error && error.message ? error.message : "Không thể tải thông tin truy xuất.");
      }
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function escapePublicHtml(text) {
    const div = document.createElement("div");
    div.textContent = String(text || "");
    return div.innerHTML;
  }

  async function verifyPublicIntegrity(base, code) {
    const badge = document.getElementById("integrity-status");
    if (!badge) return;
    badge.textContent = "Đang kiểm tra tính toàn vẹn dữ liệu...";
    badge.className = "muted";
    const abort = new AbortController();
    const timer = window.setTimeout(() => abort.abort(), 10000);
    try {
      const response = await fetch(new URL("/public/trace/" + encodeURIComponent(code) + "/integrity", base), {
        cache: "no-store", signal: abort.signal, headers: {Accept: "application/json"}
      });
      if (!response.ok) throw new Error("Không thể xác minh");
      const data = await response.json();
      const verdict = classifyIntegrity(data, code);
      if (verdict === "VERIFIED") {
        badge.textContent = "Dữ liệu đã được xác thực";
        badge.className = "privacy-badge";
      } else if (verdict === "INVALID") {
        badge.textContent = "Dữ liệu không toàn vẹn";
        badge.className = "error";
      } else {
        badge.textContent = "Chưa thể xác minh dữ liệu";
        badge.className = "error";
      }
    } catch (_error) {
      badge.textContent = "Chưa thể xác minh dữ liệu";
      badge.className = "error";
    } finally {
      window.clearTimeout(timer);
    }
  }

  function classifyIntegrity(data, code) {
    if (!data || data.batch_code !== code) return "UNAVAILABLE";
    if (data.is_valid === false) return "INVALID";
    if (data.is_valid === true && data.status === "VERIFIED" && data.total_events_checked > 0 &&
        data.total_batches_checked > 0 && typeof data.verification_seal === "string" && data.verification_seal.length === 64) {
      return "VERIFIED";
    }
    return "UNAVAILABLE";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadPublicTrace, { once: true });
  } else {
    loadPublicTrace();
  }

  // Expose pure parsing helper for lightweight Node regression tests.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { getBatchCode, classifyIntegrity, formatVnDateTime, formatVnDate };
  }
})();
