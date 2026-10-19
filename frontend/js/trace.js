/* S-46 public QR trace page. No login/session is required. */
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
    if (!last || /\\.html?$/i.test(last)) return "";
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

  function renderRoots(items) {
    const list = document.getElementById("roots");
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
        root.batch_code, root.product_name, root.harvest_date,
        root.location, root.farm_name, root.plot_name
      ].filter(Boolean).join(" · ");
      list.appendChild(item);
    });
  }

  async function loadPublicTrace() {
    // Never leave the initial loading message indefinitely.
    const timeout = window.setTimeout(() => {
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
        headers: { Accept: "application/json" }
      });
      let data = {};
      try { data = await response.json(); } catch (_error) { /* handled below */ }
      if (!response.ok) {
        if (response.status === 404) throw new Error("Không tìm thấy lô hàng có mã " + code + ".");
        throw new Error(data.detail || "Không thể tải thông tin truy xuất (HTTP " + response.status + ").");
      }

      putText("code", data.batch_code);
      putText("product", data.product_name);
      putText("date", data.harvest_date);
      putText("batch-status", data.status);
      putText("location", data.origin && data.origin.location);
      putText("farm", [
        data.origin && data.origin.farm_name,
        data.origin && data.origin.plot_name
      ].filter(Boolean).join(" · "));
      renderRoots(data.root_batches);
      contentEl.hidden = false;
      statusEl.hidden = true;
    } catch (error) {
      showError(error && error.message ? error.message : "Không thể tải thông tin truy xuất.");
    } finally {
      window.clearTimeout(timeout);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadPublicTrace, { once: true });
  } else {
    loadPublicTrace();
  }

  // Expose pure parsing helper for lightweight Node regression tests.
  if (typeof module !== "undefined" && module.exports) {
    module.exports = { getBatchCode };
  }
})();
