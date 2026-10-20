"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const form = $("trace-form");
  const codeInput = $("batch-code");
  const searchButton = $("search-button");
  const notice = $("notice");
  const result = $("trace-result");
  const milestoneList = $("milestone-list");
  const rootList = $("root-list");

  // Có thể cấu hình window.AGRITRACE_CONFIG.apiBase trước khi tải trang.
  // Khi chạy frontend trên máy tính trong mạng LAN, dùng cùng hostname với cổng API 8000.
  const API_BASE_URL = window.AGRITRACE_CONFIG?.apiBase
    || (window.location.protocol === "file:"
      ? "http://127.0.0.1:8000"
      : window.location.origin.replace(/:\d+$/, "") + ":8000");

  function showNotice(message, isError = false) {
    notice.textContent = message;
    notice.classList.toggle("is-error", isError);
    notice.hidden = false;
  }

  function hideNotice() {
    notice.hidden = true;
    notice.textContent = "";
    notice.classList.remove("is-error");
  }

  function displayDate(value) {
    if (!value) return "Chưa có dữ liệu";
    const raw = String(value);
    const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (match) return match[3] + "/" + match[2] + "/" + match[1];
    const date = new Date(raw);
    return Number.isNaN(date.getTime()) ? raw : new Intl.DateTimeFormat("vi-VN", {
      dateStyle: "medium",
      timeStyle: raw.includes("T") ? "short" : undefined
    }).format(date);
  }

  function setText(id, value, fallback = "Chưa có dữ liệu") {
    $(id).textContent = value == null || String(value).trim() === "" ? fallback : String(value);
  }

  function makeElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = String(text);
    return element;
  }

  function renderMilestones(items) {
    milestoneList.replaceChildren();
    const milestones = Array.isArray(items) ? items : [];
    $("empty-milestones").hidden = milestones.length > 0;
    milestones.forEach((item, index) => {
      const li = makeElement("li", "timeline-item");
      const heading = makeElement("h3", "", item.stage || "Mốc hành trình");
      const parts = [];
      if (item.organization_type) parts.push(item.organization_type);
      if (item.timestamp) parts.push(displayDate(item.timestamp));
      li.append(heading);
      if (parts.length) li.append(makeElement("p", "timeline-meta", parts.join(" · ")));
      if (item.status) li.append(makeElement("span", "timeline-status", item.status));
      if (!item.step) li.setAttribute("aria-label", "Mốc " + (index + 1));
      milestoneList.append(li);
    });
  }

  function renderRoots(items) {
    rootList.replaceChildren();
    const roots = Array.isArray(items) ? items : [];
    $("roots-section").hidden = roots.length === 0;
    roots.forEach((root) => {
      const li = makeElement("li");
      li.append(makeElement("strong", "", (root.product_name || "Nông sản") + " · " + (root.batch_code || "Không rõ mã lô")));
      const details = [root.farm_name, root.plot_name, root.location, root.harvest_date ? "Thu hoạch " + displayDate(root.harvest_date) : ""]
        .filter(Boolean);
      if (details.length) li.append(makeElement("span", "", details.join(" · ")));
      rootList.append(li);
    });
  }

  function renderTrace(data) {
    setText("product-name", data.product_name);
    setText("result-code", data.batch_code);
    setText("batch-status", data.status, "Chưa cập nhật");
    setText("origin-name", data.origin?.farm_name || data.origin?.plot_name, "Chưa có dữ liệu vùng trồng");
    setText("origin-location", data.origin?.location, "Chưa có địa phương");
    setText("plot-name", data.origin?.plot_name ? "Thửa/vùng: " + data.origin.plot_name : "", "");
    setText("harvest-date", displayDate(data.harvest_date));
    renderMilestones(data.milestones);
    renderRoots(data.root_batches);
    result.hidden = false;
  }

  async function lookupBatch(rawCode, updateAddress = true) {
    const code = String(rawCode || "").trim();
    if (!code) {
      showNotice("Vui lòng nhập mã lô nông sản để tra cứu.", true);
      codeInput.focus();
      return;
    }

    codeInput.value = code;
    searchButton.disabled = true;
    searchButton.textContent = "Đang tra cứu…";
    result.hidden = true;
    hideNotice();

    if (updateAddress) {
      const url = new URL(window.location.href);
      url.searchParams.set("code", code);
      window.history.replaceState({}, "", url);
    }

    try {
      const response = await fetch(API_BASE_URL + "/public/trace/" + encodeURIComponent(code), {
        method: "GET",
        headers: { Accept: "application/json" }
      });
      const data = await response.json().catch(() => ({}));

      if (response.status === 404) {
        showNotice("Không tìm thấy lô hàng có mã “" + code + "”. Hãy kiểm tra lại mã trên tem QR.", true);
        return;
      }
      if (!response.ok) {
        showNotice("Hệ thống chưa thể tra cứu lúc này (mã lỗi " + response.status + "). Vui lòng thử lại sau.", true);
        return;
      }
      if (!data || !data.batch_code || !data.origin) {
        showNotice("Dữ liệu truy xuất nhận được chưa đúng định dạng. Vui lòng liên hệ đơn vị quản lý hệ thống.", true);
        return;
      }
      renderTrace(data);
    } catch (error) {
      showNotice("Không kết nối được máy chủ truy xuất. Hãy kiểm tra kết nối mạng hoặc thử lại khi hệ thống hoạt động.", true);
    } finally {
      searchButton.disabled = false;
      searchButton.textContent = "Tra cứu";
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    lookupBatch(codeInput.value);
  });

  const params = new URLSearchParams(window.location.search);
  const initialCode = params.get("code") || params.get("batch_code") || "";
  if (initialCode.trim()) {
    codeInput.value = initialCode.trim();
    lookupBatch(initialCode, false);
  }
})();
