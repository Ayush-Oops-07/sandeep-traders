/* ═══════════════════════════════════════════════════════════════════════════
   SANDEEP TRADERS — BUSINESS SUITE — app.js
   Full SPA: auth, routing, ledger, invoices, charts, modals
════════════════════════════════════════════════════════════════════════════ */
"use strict";

// ── GLOBAL ERROR GUARD — prevents white screen on JS crash ───────────────────
window.addEventListener("unhandledrejection", (e) => {
  console.error("Unhandled promise rejection:", e.reason);
  if (typeof toast === "function") {
    toast("Kuch error aaya. Page reload karo agar problem rahe.", "error");
  }
  e.preventDefault();
});
window.onerror = (msg, src, line, col, err) => {
  console.error("JS Error:", msg, src, line, err);
  return false; // don't suppress console
};

// ── STATE ─────────────────────────────────────────────────────────────────────
const S = {
  user:           null,
  module:         "customer",   // "customer" | "shoper"
  currentPage:    "home",
  currentPartyId: null,
  currentParty:   null,
  allParties:     [],
  ledgerEntries:  [],
  invoices:       [],
  products:       [],
  statusFilter:   "",
  invViewId:      null,
  charts:         {},
  chartInstance:  {},
  submitLock:     false,
};

// ── INIT ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  initTheme();
  startClock();
  populateChartYears();
  initHistory();
  await checkAuth();
});

// ═══════════════════════════════════════════════════════════════════════════════
//  AUTH
// ═══════════════════════════════════════════════════════════════════════════════

async function checkAuth() {
  try {
    const res  = await fetch("/api/auth/me");
    const data = await res.json();
    if (data.authenticated) {
      S.user = data.user;
      showApp();
    } else {
      showLogin();
    }
  } catch {
    showLogin();
  }
}

function showLogin() {
  document.getElementById("login-screen").style.display = "flex";
  document.getElementById("app").classList.remove("visible");
}

function showApp() {
  document.getElementById("login-screen").style.display = "none";
  const app = document.getElementById("app");
  app.classList.add("visible");
  document.body.classList.add("on-home"); // hide chrome immediately before navigate runs
  updateUserUI();
  loadHomeStats();
  navigate("home");
  // Destroy any stale charts
  Object.keys(S.chartInstance).forEach(k => {
    try { if (S.chartInstance[k]) S.chartInstance[k].destroy(); } catch {}
    delete S.chartInstance[k];
  });
}

async function doLogin() {
  if (S.submitLock) return;
  const username = document.getElementById("login-user").value;
  const password = document.getElementById("login-pass").value;
  const errEl    = document.getElementById("login-err");
  const btn      = document.getElementById("login-btn");

  errEl.style.display = "none";
  if (!username) { showLoginErr("Please select a user."); return; }
  if (!password) { showLoginErr("Please enter your password."); return; }

  S.submitLock = true;
  btn.disabled = true;
  document.getElementById("login-btn-text").textContent = "Signing in…";

  try {
    const res  = await api("POST", "/api/auth/login", { username, password });
    if (res.ok) {
      S.user = res.user;
      showApp();
    } else {
      showLoginErr(res.error || "Invalid credentials.");
    }
  } catch {
    showLoginErr("Server error. Please try again.");
  } finally {
    S.submitLock = false;
    btn.disabled = false;
    document.getElementById("login-btn-text").textContent = "Sign In";
  }
}

function showLoginErr(msg) {
  const el = document.getElementById("login-err");
  el.textContent = msg;
  el.style.display = "block";
}

async function doLogout() {
  closeAllDropdowns();
  await fetch("/api/auth/logout", { method: "POST" });
  S.user = null;
  S.currentPartyId = null;
  showLogin();
  document.getElementById("login-pass").value = "";
  document.getElementById("login-err").style.display = "none";
}

function togglePw() {
  const inp  = document.getElementById("login-pass");
  const icon = document.getElementById("pw-icon");
  if (inp.type === "password") {
    inp.type = "text";
    icon.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
  } else {
    inp.type = "password";
    icon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
  }
}

function updateUserUI() {
  if (!S.user) return;
  const initials = (S.user.full_name || S.user.username).charAt(0).toUpperCase();
  document.getElementById("user-av").textContent   = initials;
  document.getElementById("user-nm").textContent   = S.user.full_name || S.user.username;
  document.getElementById("user-dd-name").textContent = S.user.full_name || S.user.username;
  document.getElementById("user-dd-role").textContent = S.user.role;
}

function toggleUserMenu() {
  document.getElementById("user-dropdown").classList.toggle("open");
}

function closeAllDropdowns() {
  document.getElementById("user-dropdown").classList.remove("open");
}

document.addEventListener("click", (e) => {
  if (!e.target.closest("#user-pill") && !e.target.closest("#user-dropdown")) {
    document.getElementById("user-dropdown").classList.remove("open");
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
//  THEME
// ═══════════════════════════════════════════════════════════════════════════════

function initTheme() {
  const saved = localStorage.getItem("st-theme") || "dark";
  applyTheme(saved);
  injectThemeToggle();
}

function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("st-theme", theme);
}

function toggleTheme() {
  const cur  = document.documentElement.getAttribute("data-theme") || "dark";
  const next = cur === "dark" ? "light" : "dark";
  applyTheme(next);
  const btn = document.getElementById("theme-toggle-btn");
  if (btn) btn.innerHTML = next === "dark" ? moonIcon() : sunIcon();
  // Redraw charts for new bg
  if (S.currentPage === "dashboard") loadDashboard();
}

function injectThemeToggle() {
  const btn = document.createElement("button");
  btn.id        = "theme-toggle-btn";
  btn.className = "theme-toggle";
  btn.onclick   = toggleTheme;
  btn.title     = "Toggle theme";
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  btn.innerHTML = cur === "dark" ? moonIcon() : sunIcon();
  document.querySelector(".topbar-right")?.prepend(btn);
}

function moonIcon() {
  return `<svg width="17" height="17" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3a7 7 0 009.79 9.79z"/></svg>`;
}
function sunIcon() {
  return `<svg width="17" height="17" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MODULE SWITCHING
// ═══════════════════════════════════════════════════════════════════════════════

function switchModule(mod) {
  S.module = mod;
  // Module buttons
  document.querySelectorAll(".module-btn").forEach(b => b.classList.remove("active", "shoper-active"));
  const modBtn = document.getElementById(`mod-${mod}`);
  if (modBtn) modBtn.classList.add("active");
  if (mod === "shoper" && modBtn) modBtn.classList.add("shoper-active");

  // Update labels
  const label = mod === "customer" ? "Customer Module" : "Shoper / Wholesale Module";
  const tbLabel = document.getElementById("tb-module-label");
  if (tbLabel) tbLabel.textContent = label;

  const navCustLabel = document.getElementById("nav-customers-label");
  if (navCustLabel) navCustLabel.textContent = mod === "customer" ? "Customers" : "Shopers";

  const custPageTitle = document.getElementById("cust-page-title");
  if (custPageTitle) custPageTitle.textContent = mod === "customer" ? "Customers" : "Shopers / Wholesalers";

  const dashTitle = document.getElementById("dash-title");
  if (dashTitle) dashTitle.textContent = mod === "customer" ? "👤 Customer Dashboard" : "🏪 Shoper / Wholesale Dashboard";

  const badge = document.getElementById("dash-module-badge");
  if (badge) {
    badge.textContent = mod === "customer" ? "Customer Module" : "Shoper Module";
    badge.className = mod === "customer" ? "module-indicator" : "module-indicator module-indicator-shoper";
  }

  const dashSub = document.getElementById("dash-sub");
  if (dashSub) dashSub.textContent = mod === "customer"
    ? "Retail sales · Pakhopali Road, Thawe"
    : "Wholesale accounts · Pakhopali Road, Thawe";

  // Destroy all existing chart instances so they render fresh
  Object.keys(S.chartInstance).forEach(k => {
    try { if (S.chartInstance[k]) S.chartInstance[k].destroy(); } catch {}
    delete S.chartInstance[k];
  });

  closeSidebar();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  ROUTING / NAVIGATION
// ═══════════════════════════════════════════════════════════════════════════════

const PAGE_IDS = ["home","dashboard","customers","ledger","invoices","products"];

function navigate(page, pushState = true) {
  // Hide all pages
  PAGE_IDS.forEach(p => {
    const el = document.getElementById(`page-${p}`);
    if (el) el.classList.remove("active");
  });
  // Show target
  const target = document.getElementById(`page-${page}`);
  if (target) target.classList.add("active");

  S.currentPage = page;

  // ── Show/hide topbar, sidebar, bottom-nav on home page ──────────────────
  // Use CSS class toggle (no style.display) to prevent layout-reflow white flash
  if (page === "home") {
    document.body.classList.add("on-home");
  } else {
    document.body.classList.remove("on-home");
    // Update sidebar nav items for current module
    updateSidebarForModule(S.module);
  }

  // Update nav active states
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
  const navEl = document.getElementById(`nav-${page}`);
  if (navEl) navEl.classList.add("active");

  // Breadcrumbs
  updateBreadcrumb(page);

  // Load data
  if (page === "dashboard") loadDashboard();
  if (page === "customers") loadParties();
  if (page === "invoices")  loadInvoices();
  if (page === "products")  loadProducts();

  // Push browser history
  if (pushState) {
    const state = { page, partyId: S.currentPartyId };
    history.pushState(state, "", `#${page}`);
  }

  if (page !== "home") closeSidebar();
  setBottomNavFromPage(page);
}

// ── Update sidebar nav items based on current module ─────────────────────────
function updateSidebarForModule(mod) {
  // Customer module: show Dashboard, Customers, Invoices, Products
  // Shoper module: show Dashboard, Shopers, Invoices, Products
  const navCustomers = document.getElementById("nav-customers");
  const navInvoices  = document.getElementById("nav-invoices");
  const navProducts  = document.getElementById("nav-products");
  const navDashboard = document.getElementById("nav-dashboard");

  // All nav items always visible but labels update
  if (navCustomers) navCustomers.style.display = "";
  if (navInvoices)  navInvoices.style.display  = "";
  if (navProducts)  navProducts.style.display  = "";
  if (navDashboard) navDashboard.style.display = "";

  // Update customer/shoper label
  const lbl = document.getElementById("nav-customers-label");
  if (lbl) lbl.textContent = mod === "customer" ? "Customers" : "Shopers";

  // Update module buttons active state
  document.querySelectorAll(".module-btn").forEach(b => b.classList.remove("active", "shoper-active"));
  const modBtn = document.getElementById(`mod-${mod}`);
  if (modBtn) {
    modBtn.classList.add("active");
    if (mod === "shoper") modBtn.classList.add("shoper-active");
  }
}

function updateBreadcrumb(page) {
  const mod  = S.module === "customer" ? "Customer" : "Shoper";
  const map  = {
    home: ["Home"],
    dashboard: [mod, "Dashboard"],
    customers: [mod, S.module === "customer" ? "Customers" : "Shopers"],
    ledger:    [mod, S.module === "customer" ? "Customers" : "Shopers", S.currentParty?.name || "Ledger"],
    invoices:  [mod, "Invoices"],
    products:  ["Products"],
  };
  const parts = map[page] || [page];
  document.getElementById("breadcrumb").innerHTML = parts
    .map(p => `<span>${p}</span>`).join("");
}

// Back navigation
function initHistory() {
  window.addEventListener("popstate", (e) => {
    const state = e.state;
    if (state && state.page) {
      if (state.page === "ledger" && state.partyId) {
        S.currentPartyId = state.partyId;
        openLedger(state.partyId, false);
      } else {
        navigate(state.page, false);
      }
    } else {
      navigate("home", false);
    }
  });
}

function goBack() {
  history.back();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SIDEBAR
// ═══════════════════════════════════════════════════════════════════════════════

function toggleSidebar() {
  document.getElementById("sidebar").classList.toggle("open");
  document.getElementById("sidebar-overlay").classList.toggle("open");
}
function closeSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebar-overlay").classList.remove("open");
}
function openSidebar() {
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("sidebar-overlay").classList.add("open");
}

// ═══════════════════════════════════════════════════════════════════════════════
//  BOTTOM NAV
// ═══════════════════════════════════════════════════════════════════════════════

function setBottomNav(id) {
  document.querySelectorAll(".bnav-btn").forEach(b => b.classList.remove("active"));
  const el = document.getElementById(`bnav-${id}`);
  if (el) el.classList.add("active");
}

function setBottomNavFromPage(page) {
  const map = { home:"home", dashboard:"dashboard", customers:"customers", ledger:"customers", invoices:"invoices" };
  setBottomNav(map[page] || "home");
}

// ═══════════════════════════════════════════════════════════════════════════════
//  CLOCK & GREETING
// ═══════════════════════════════════════════════════════════════════════════════

function startClock() {
  function tick() {
    const now  = new Date();
    const str  = now.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    const el   = document.getElementById("live-clock");
    if (el) el.textContent = str;

    // Home page clock
    const hclock = document.getElementById("home-clock");
    if (hclock) hclock.textContent = str;

    // Home page date
    const hdate = document.getElementById("home-date");
    if (hdate) hdate.textContent = now.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

    const h = now.getHours();
    const greet = h < 12 ? "Good Morning 🌅" : h < 17 ? "Good Afternoon ☀️" : h < 20 ? "Good Evening 🌆" : "Good Night 🌙";
    const hel = document.getElementById("home-greeting");
    if (hel) hel.textContent = greet;
  }
  tick();
  setInterval(tick, 1000);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  HOME STATS
// ═══════════════════════════════════════════════════════════════════════════════

async function loadHomeStats() {
  for (const mod of ["customer", "shoper"]) {
    try {
      const data = await api("GET", `/api/parties/stats?type=${mod}`);
      const el   = document.getElementById(`mc-stats-${mod}`);
      if (el) {
        const label = mod === "customer" ? "Customers" : "Shopers";
        const pendingColor = mod === "customer" ? "var(--amber)" : "var(--purple, #a855f7)";
        el.innerHTML = `
          <div class="mc-stat-row">
            <span class="mc-stat-num">${data.total}</span>
            <span class="mc-stat-lbl">${label}</span>
          </div>
          <div class="mc-stat-row">
            <span class="mc-stat-num" style="color:${pendingColor}">₹${fmtK(data.net_outstanding)}</span>
            <span class="mc-stat-lbl">Outstanding</span>
          </div>`;
      }
    } catch {
      const el = document.getElementById(`mc-stats-${mod}`);
      if (el) el.innerHTML = `<span style="color:var(--text3);font-size:12px">Could not load stats</span>`;
    }
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  DASHBOARD
// ═══════════════════════════════════════════════════════════════════════════════

async function loadDashboard() {
  const year = document.getElementById("chart-year")?.value || new Date().getFullYear();

  // Update badge on dashboard load too
  const badge = document.getElementById("dash-module-badge");
  if (badge) {
    badge.textContent = S.module === "customer" ? "Customer Module" : "Shoper Module";
    badge.className = S.module === "customer" ? "module-indicator" : "module-indicator module-indicator-shoper";
  }
  const dashTitle = document.getElementById("dash-title");
  if (dashTitle) dashTitle.textContent = S.module === "customer" ? "👤 Customer Dashboard" : "🏪 Shoper / Wholesale Dashboard";
  const dashSub = document.getElementById("dash-sub");
  if (dashSub) dashSub.textContent = S.module === "customer"
    ? "Retail sales · Pakhopali Road, Thawe"
    : "Wholesale accounts · Pakhopali Road, Thawe";

  try {
    const data = await api("GET", `/api/dashboard/?type=${S.module}&year=${year}`);

    // KPI
    const k = data.kpi;
    setText("kpi-total",       k.total_parties);
    setText("kpi-pending",     k.pending_count);
    setText("kpi-advance",     k.advance_count);
    setText("kpi-outstanding", "₹" + fmtK(k.net_outstanding));
    setText("kpi-today-sales", "₹" + fmtK(k.today_sales));
    setText("kpi-today-coll",  "₹" + fmtK(k.today_collections));

    // Charts
    renderSalesChart(data.charts);
    renderCollChart(data.charts);
    renderDonutChart(data.portfolio);
    renderTop10Chart(data.top_pending);

    // Top pending table
    const tbody = document.getElementById("top-pending-body");
    document.getElementById("pending-badge").textContent = k.pending_count;
    if (data.top_pending.length === 0) {
      tbody.innerHTML = `<tr><td colspan="5" class="empty-state" style="text-align:center;padding:24px;color:var(--text2)">No pending accounts</td></tr>`;
    } else {
      tbody.innerHTML = data.top_pending.map((p, i) => `
        <tr>
          <td>${i+1}</td>
          <td><b>${esc(p.name)}</b></td>
          <td>${esc(p.mobile || "—")}</td>
          <td class="td-r" style="color:var(--amber)">${fmt(p.balance)}</td>
          <td>
            <button class="btn btn-sm btn-ghost" onclick="openLedger(${p.id})">Ledger</button>
          </td>
        </tr>`).join("");
    }

    // Recent transactions
    renderRecentTxn(data.recent_transactions);

  } catch (e) {
    console.error("Dashboard load error:", e);
    toast("Failed to load dashboard", "error");
  }
}

function renderRecentTxn(txns) {
  const tbody = document.getElementById("recent-txn-body");
  if (!txns || txns.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--text2)">No transactions yet</td></tr>`;
    return;
  }
  tbody.innerHTML = txns.map(e => {
    const drCls = e.debit > 0  ? 'style="color:var(--amber)"' : '';
    const crCls = e.credit > 0 ? 'style="color:var(--green2)"' : '';
    const balCls = e.running_balance > 0 ? 'style="color:var(--amber)"' :
                   e.running_balance < 0 ? 'style="color:var(--green2)"' : '';
    return `<tr>
      <td>${formatDate(e.entry_date)}</td>
      <td><b>${esc(e.party_name || "")}</b></td>
      <td>${esc(e.particulars)}</td>
      <td class="td-r" ${drCls}>${e.debit  > 0 ? fmt(e.debit)  : "—"}</td>
      <td class="td-r" ${crCls}>${e.credit > 0 ? fmt(e.credit) : "—"}</td>
      <td class="td-r" ${balCls}>${fmt(Math.abs(e.running_balance))}${e.running_balance < 0 ? " Adv" : ""}</td>
    </tr>`;
  }).join("");
}

function populateChartYears() {
  const sel = document.getElementById("chart-year");
  if (!sel) return;
  const cur = new Date().getFullYear();
  for (let y = cur; y >= cur - 4; y--) {
    const opt = document.createElement("option");
    opt.value = y; opt.textContent = y;
    sel.appendChild(opt);
  }
}

// ── CHARTS ────────────────────────────────────────────────────────────────────

function getChartTheme() {
  const theme = document.documentElement.getAttribute("data-theme") || "dark";
  return {
    grid:   theme === "dark" ? "rgba(255,255,255,.06)" : "rgba(0,0,0,.06)",
    text:   theme === "dark" ? "#8896b0"               : "#64748b",
    bg:     theme === "dark" ? "#0f1624"               : "#f8fafc",
  };
}

function baseChartOptions(t) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { grid: { color: t.grid }, ticks: { color: t.text, font: { size: 11 } } },
      y: { grid: { color: t.grid }, ticks: { color: t.text, font: { size: 11 }, callback: v => "₹" + fmtK(v) } },
    },
  };
}

function safeDestroyChart(key) {
  try {
    if (S.chartInstance[key]) {
      S.chartInstance[key].destroy();
      S.chartInstance[key] = null;
    }
  } catch (e) {}
}

function resetCanvas(id) {
  const oldCanvas = document.getElementById(id);
  if (!oldCanvas) return null;
  const parent = oldCanvas.parentNode; // this is .chart-wrap
  const newCanvas = document.createElement("canvas");
  newCanvas.id = id;
  // No height attribute — CSS controls size via .chart-wrap
  parent.replaceChild(newCanvas, oldCanvas);
  return newCanvas;
}

function renderSalesChart(data) {
  const t   = getChartTheme();
  safeDestroyChart("sales");
  const ctx = resetCanvas("chart-sales");
  if (!ctx) return;
  S.chartInstance.sales = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.months,
      datasets: [{
        label: "Sales ₹",
        data: data.sales,
        backgroundColor: S.module === "customer" ? "rgba(59,130,246,.75)" : "rgba(168,85,247,.75)",
        borderRadius: 6,
        borderSkipped: false,
      }]
    },
    options: baseChartOptions(t),
  });
}

function renderCollChart(data) {
  const t   = getChartTheme();
  safeDestroyChart("coll");
  const ctx = resetCanvas("chart-coll");
  if (!ctx) return;
  S.chartInstance.coll = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.months,
      datasets: [{
        label: "Collections ₹",
        data: data.collections,
        borderColor: "#10b981",
        backgroundColor: "rgba(16,185,129,.12)",
        tension: .4, fill: true,
        pointBackgroundColor: "#10b981",
        pointRadius: 4,
        pointHoverRadius: 6,
      }]
    },
    options: baseChartOptions(t),
  });
}

function renderDonutChart(portfolio) {
  const t = getChartTheme();
  safeDestroyChart("donut");
  const ctx = resetCanvas("chart-donut");
  if (!ctx) return;
  const total = (portfolio.pending || 0) + (portfolio.advance || 0) + (portfolio.clear || 0);
  S.chartInstance.donut = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: ["Pending", "Advance", "Clear"],
      datasets: [{
        data: total === 0 ? [1, 0, 0] : [portfolio.pending, portfolio.advance, portfolio.clear],
        backgroundColor: total === 0 ? ["#334155","#334155","#334155"] : ["#f59e0b","#10b981","#3b82f6"],
        borderColor: "transparent",
        hoverOffset: 8,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: "68%",
      plugins: {
        legend: {
          display: true, position: "bottom",
          labels: { color: t.text, font: { size: 11 }, boxWidth: 12, padding: 14 }
        },
        tooltip: {
          callbacks: {
            label: (ctx) => total === 0 ? " No data" : ` ${ctx.label}: ${ctx.parsed}`
          }
        }
      }
    }
  });
}

function renderTop10Chart(parties) {
  const t = getChartTheme();
  safeDestroyChart("top10");
  const ctx = resetCanvas("chart-top10");
  if (!ctx) return;
  const top = parties.slice(0, 8);
  if (top.length === 0) return;
  const accentColor = S.module === "customer" ? "rgba(245,158,11,.75)" : "rgba(168,85,247,.75)";
  S.chartInstance.top10 = new Chart(ctx, {
    type: "bar",
    data: {
      labels: top.map(p => p.name.split(" ").slice(0,2).join(" ")),
      datasets: [{
        label: "Balance ₹",
        data: top.map(p => p.balance),
        backgroundColor: accentColor,
        borderRadius: 4,
      }]
    },
    options: {
      ...baseChartOptions(t),
      indexAxis: "y",
    }
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  PARTIES (CUSTOMERS / SHOPERS)
// ═══════════════════════════════════════════════════════════════════════════════

async function loadParties() {
  const q = (document.getElementById("cust-search")?.value || "").trim();
  const params = new URLSearchParams({
    type: S.module, q,
    ...(S.statusFilter ? { status: S.statusFilter } : {}),
  });
  try {
    const data = await api("GET", `/api/parties/?${params}`);
    S.allParties = data;
    renderPartyTable(data);
    renderPartyCards(data);
  } catch (e) {
    toast("Failed to load parties", "error");
  }
}

function renderPartyTable(parties) {
  const tbody = document.getElementById("party-table-body");
  if (parties.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:32px;color:var(--text2)">
      No records found. <button class="btn btn-sm btn-primary" onclick="openAddParty()" style="margin-left:8px">Add First</button>
    </td></tr>`;
    return;
  }
  tbody.innerHTML = parties.map((p, i) => {
    const [cls, lbl] = p.balance > 0 ? ["badge-amber","Pending"] :
                        p.balance < 0 ? ["badge-green","Advance"] :
                                        ["badge-gray","Clear"];
    return `<tr>
      <td>${i+1}</td>
      <td><b>${esc(p.name)}</b></td>
      <td>${esc(p.mobile || "—")}</td>
      <td>${esc((p.address || "").substring(0,30) || "—")}</td>
      <td class="td-r" style="color:${p.balance>0?'var(--amber)':p.balance<0?'var(--green2)':'inherit'}">${fmt(Math.abs(p.balance))}</td>
      <td><span class="badge ${cls}">${lbl}</span></td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm btn-ghost" onclick="openLedger(${p.id})">Ledger</button>
          <button class="btn btn-sm btn-ghost" onclick="openEditParty(${p.id})">Edit</button>
          <button class="btn btn-sm btn-ghost" style="color:var(--red2)" onclick="confirmDeleteParty(${p.id},'${esc(p.name).replace(/'/g,"\\'")}')">Del</button>
        </div>
      </td>
    </tr>`;
  }).join("");
}

function renderPartyCards(parties) {
  const cont = document.getElementById("party-card-list");
  if (parties.length === 0) {
    cont.innerHTML = `<div class="empty-state"><div class="es-icon">👥</div><p>No records found</p>
      <button class="btn btn-sm btn-primary" onclick="openAddParty()" style="margin-top:12px">Add First</button></div>`;
    return;
  }
  cont.innerHTML = parties.map(p => {
    const [col, lbl] = p.balance > 0 ? ["var(--amber)","Pending"] :
                        p.balance < 0 ? ["var(--green2)","Advance"] :
                                        ["var(--text2)","Clear"];
    return `<div class="party-card" onclick="openLedger(${p.id})">
      <div class="pc-avatar">${(p.name||"?").charAt(0).toUpperCase()}</div>
      <div class="pc-info">
        <div class="pc-name">${esc(p.name)}</div>
        <div class="pc-meta">${esc(p.mobile || "—")} ${p.city ? "· "+esc(p.city) : ""}</div>
      </div>
      <div class="pc-right">
        <div class="pc-balance" style="color:${col}">₹${fmt(Math.abs(p.balance))}</div>
        <div class="pc-status" style="color:${col}">${lbl}</div>
      </div>
    </div>`;
  }).join("");
}

function setStatusFilter(el, val) {
  document.querySelectorAll(".ftab").forEach(b => b.classList.remove("active"));
  el.classList.add("active");
  S.statusFilter = val;
  loadParties();
}

// ── ADD / EDIT PARTY ──────────────────────────────────────────────────────────

function openAddParty(prefillName = "") {
  document.getElementById("party-modal-title").textContent = `Add ${S.module === "customer" ? "Customer" : "Shoper"}`;
  document.getElementById("party-edit-id").value = "";
  document.getElementById("party-name").value    = prefillName;
  document.getElementById("party-mobile").value  = "";
  document.getElementById("party-mobile2").value = "";
  document.getElementById("party-address").value = "";
  document.getElementById("party-city").value    = "";
  document.getElementById("party-gstin").value   = "";
  document.getElementById("party-opening").value = "0";
  document.getElementById("party-notes").value   = "";
  openModal("modal-party");
  setTimeout(() => document.getElementById("party-name").focus(), 150);
}

async function openEditParty(partyId) {
  try {
    const p = await api("GET", `/api/parties/${partyId}`);
    document.getElementById("party-modal-title").textContent = "Edit Party";
    document.getElementById("party-edit-id").value  = p.id;
    document.getElementById("party-name").value     = p.name;
    document.getElementById("party-mobile").value   = p.mobile  || "";
    document.getElementById("party-mobile2").value  = p.mobile2 || "";
    document.getElementById("party-address").value  = p.address || "";
    document.getElementById("party-city").value     = p.city    || "";
    document.getElementById("party-gstin").value    = p.gstin   || "";
    document.getElementById("party-opening").value  = p.opening_balance;
    document.getElementById("party-notes").value    = p.notes   || "";
    openModal("modal-party");
  } catch {
    toast("Failed to load party", "error");
  }
}

async function saveParty() {
  if (S.submitLock) return;
  const editId = document.getElementById("party-edit-id").value;
  const name   = document.getElementById("party-name").value.trim();
  if (!name) { toast("Name is required", "error"); return; }

  const body = {
    party_type:      S.module,
    name,
    mobile:          document.getElementById("party-mobile").value.trim(),
    mobile2:         document.getElementById("party-mobile2").value.trim(),
    address:         document.getElementById("party-address").value.trim(),
    city:            document.getElementById("party-city").value.trim(),
    gstin:           document.getElementById("party-gstin").value.trim(),
    opening_balance: parseFloat(document.getElementById("party-opening").value) || 0,
    notes:           document.getElementById("party-notes").value.trim(),
  };

  S.submitLock = true;
  try {
    if (editId) {
      await api("PUT",  `/api/parties/${editId}`, body);
      toast("Party updated", "success");
    } else {
      await api("POST", `/api/parties/`, body);
      toast("Party added", "success");
    }
    closeModal("modal-party");
    loadParties();
    if (S.currentPage === "dashboard") loadDashboard();
  } catch (e) {
    toast(e.message || "Error saving party", "error");
  } finally {
    S.submitLock = false;
  }
}

function confirmDeleteParty(id, name) {
  openConfirm(
    "Delete Party",
    `Are you sure you want to delete <b>${name}</b>? This will hide the party but keep all history.`,
    async () => {
      try {
        await api("DELETE", `/api/parties/${id}`);
        toast("Party deleted", "success");
        loadParties();
      } catch {
        toast("Error deleting", "error");
      }
    }
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
//  LEDGER
// ═══════════════════════════════════════════════════════════════════════════════

async function openLedger(partyId, pushState = true) {
  S.currentPartyId = partyId;
  navigate("ledger", pushState);
  if (pushState) history.pushState({ page: "ledger", partyId }, "", `#ledger`);

  try {
    const party = await api("GET", `/api/parties/${partyId}`);
    S.currentParty = party;
    document.getElementById("ledger-party-name").textContent = party.name;
    document.getElementById("ledger-party-meta").textContent =
      [party.mobile, party.address, party.city].filter(Boolean).join(" · ") || "No contact info";
    updateBreadcrumb("ledger");
    await loadLedgerData();
  } catch {
    toast("Failed to load ledger", "error");
  }
}

async function loadLedgerData() {
  const from = document.getElementById("ledger-from")?.value || "";
  const to   = document.getElementById("ledger-to")?.value || "";
  const q    = document.getElementById("ledger-search")?.value || "";
  const params = new URLSearchParams({ ...(from && {from}), ...(to && {to}), ...(q && {q}) });

  try {
    const data = await api("GET", `/api/ledger/${S.currentPartyId}?${params}`);
    S.ledgerEntries = data.entries;
    renderLedgerTable(data);
    updateLedgerBalance(data.balance, data.opening_balance);

    // Summary cards (Total Sales / Total Payments / Current Balance) come
    // from the ONE centralized ledger calculation source on the backend —
    // never recomputed client-side from raw entries — so they can never
    // drift from what the ledger table itself shows.
    const summary = await api("GET", `/api/parties/${S.currentPartyId}/summary`);
    const totalPayments = summary.total_payments_received + summary.total_payments_given;
    setText("lsb-sales",    "₹" + fmt(summary.total_sales));
    setText("lsb-payments", "₹" + fmt(totalPayments));
    setText("lsb-opening",  "₹" + fmt(Math.abs(summary.opening_balance)));
    setText("lsb-balance",  (summary.current_balance >= 0 ? "₹" : "-₹") + fmt(Math.abs(summary.current_balance)));
  } catch {
    toast("Failed to load ledger entries", "error");
  }
}

function renderLedgerTable(data) {
  const tbody = document.getElementById("ledger-body");
  const empty = document.getElementById("ledger-empty");
  const entries = data.entries;

  if (entries.length === 0) {
    tbody.innerHTML = "";
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";

  // Opening balance row
  let rows = "";
  if (data.opening_balance !== 0) {
    rows += `<tr style="background:rgba(255,255,255,.02)">
      <td><span class="badge badge-gray">OB</span></td>
      <td>—</td>
      <td><em>Opening Balance</em></td>
      <td class="td-r">${data.opening_balance > 0 ? fmt(data.opening_balance) : "—"}</td>
      <td class="td-r">${data.opening_balance < 0 ? fmt(Math.abs(data.opening_balance)) : "—"}</td>
      <td class="td-r">${fmt(Math.abs(data.opening_balance))}</td>
      <td></td>
    </tr>`;
  }

  rows += entries.map((e, i) => {
    const drCls = e.debit > 0  ? 'style="color:var(--amber)"' : '';
    const crCls = e.credit > 0 ? 'style="color:var(--green2)"' : '';
    const balCls = e.running_balance > 0 ? 'style="color:var(--amber)"' :
                   e.running_balance < 0 ? 'style="color:var(--green2)"' : '';
    const typeBadge = e.entry_type === "sale" ? "badge-amber" :
                      e.entry_type === "payment" ? "badge-green" :
                      e.entry_type === "advance_received" ? "badge-green" :
                      e.entry_type === "advance_paid" ? "badge-amber" :
                      e.entry_type === "adjustment" ? "badge-blue" : "badge-gray";

    // "Adjust" button is only offered on credit (payment received) entries
    const isCredit = e.credit > 0 && (
      e.entry_type === "payment" ||
      e.entry_type === "credit" ||
      e.entry_type === "advance_received"
    );
    const adjustBtn = isCredit
      ? `<button class="btn btn-sm btn-ghost" title="Adjust this payment against an invoice"
           style="color:var(--blue2)" onclick="openAdjustModal(${JSON.stringify(e).replace(/"/g,'&quot;')})">Adjust</button>`
      : "";

    return `<tr>
      <td><span class="badge ${typeBadge}">${i+1}</span></td>
      <td>${formatDate(e.entry_date)}</td>
      <td>
        ${esc(e.particulars)}
        ${(e.entry_type === "advance_received" || e.entry_type === "advance_paid")
          ? `<span class="badge badge-blue" style="margin-left:6px;font-size:9px">ADVANCE</span>` : ""}
        ${e.invoice_number ? `<br><small style="color:var(--text2)">Invoice: ${esc(e.invoice_number)}</small>` : ""}
        ${e.payment_mode   ? `<small style="color:var(--text2)"> · ${esc(e.payment_mode)}</small>` : ""}
      </td>
      <td class="td-r" ${drCls}>${e.debit  > 0 ? fmt(e.debit)  : "—"}</td>
      <td class="td-r" ${crCls}>${e.credit > 0 ? fmt(e.credit) : "—"}</td>
      <td class="td-r" ${balCls}>${fmt(Math.abs(e.running_balance))}${e.running_balance < 0 ? "<br><small>Adv</small>" : ""}</td>
      <td>
        <div style="display:flex;gap:4px;flex-wrap:wrap">
          ${e.invoice_id ? `<button class="btn btn-sm btn-ghost" onclick="viewInvoice(${e.invoice_id})">View</button>` : ""}
          ${adjustBtn}
          ${e.entry_type !== "adjustment" ? `<button class="btn btn-sm btn-ghost" onclick="openEditEntry(${JSON.stringify(e).replace(/"/g,'&quot;')})">Edit</button>` : ""}
          <button class="btn btn-sm btn-ghost" style="color:var(--red2)" onclick="confirmDeleteEntry(${e.id})">${e.entry_type === "adjustment" ? "Remove" : "Del"}</button>
        </div>
      </td>
    </tr>`;
  }).join("");

  tbody.innerHTML = rows;
}

function updateLedgerBalance(balance, opening) {
  const chip = document.getElementById("ledger-balance-chip");
  const val  = document.getElementById("ledger-balance-val");
  if (balance > 0) {
    val.textContent = "₹" + fmt(balance);
    val.style.color = "var(--amber)";
    chip.style.borderColor = "rgba(245,158,11,.3)";
  } else if (balance < 0) {
    val.textContent = "ADV ₹" + fmt(Math.abs(balance));
    val.style.color = "var(--green2)";
    chip.style.borderColor = "rgba(16,185,129,.3)";
  } else {
    val.textContent = "₹0 (Clear)";
    val.style.color = "var(--text2)";
    chip.style.borderColor = "var(--border)";
  }
}

function filterLedger() { loadLedgerData(); }
function clearLedgerFilters() {
  document.getElementById("ledger-search").value = "";
  document.getElementById("ledger-from").value   = "";
  document.getElementById("ledger-to").value     = "";
  loadLedgerData();
}

function printLedger() {
  const party = S.currentParty;
  if (!party) return;
  const html = buildLedgerPrintHtml(party, S.ledgerEntries);
  const win  = window.open("", "_blank", "width=800,height=600");
  win.document.write(html);
  win.document.close();
  setTimeout(() => { win.print(); }, 400);
}

function buildLedgerPrintHtml(party, entries) {
  const rows = entries.map((e, i) => `
    <tr>
      <td>${i+1}</td>
      <td>${formatDate(e.entry_date)}</td>
      <td>${e.particulars}${e.invoice_number ? " ("+e.invoice_number+")" : ""}</td>
      <td style="text-align:right">${e.debit  > 0 ? fmt(e.debit)  : ""}</td>
      <td style="text-align:right">${e.credit > 0 ? fmt(e.credit) : ""}</td>
      <td style="text-align:right">${fmt(Math.abs(e.running_balance))}${e.running_balance < 0 ? " Adv" : ""}</td>
    </tr>`).join("");

  return `<!DOCTYPE html><html><head><title>Ledger - ${party.name}</title>
  <style>
    body { font-family: Arial, sans-serif; font-size: 12px; color: #1a1a2e; }
    h1 { font-size: 18px; } p { color: #555; }
    table { width: 100%; border-collapse: collapse; margin-top: 16px; }
    th { background: #1e3a5f; color: #fff; padding: 7px 8px; text-align: left; font-size: 11px; }
    td { padding: 7px 8px; border-bottom: 1px solid #e2e8f0; }
    tr:nth-child(even) td { background: #f8fafc; }
    .brand { color: #1e3a5f; font-size: 22px; font-weight: 900; }
    @media print { body { -webkit-print-color-adjust: exact; } }
  </style></head><body>
  <div class="brand">SANDEEP TRADERS</div>
  <p>Pakhopali Road, Thawe, Gopalganj · Printed: ${new Date().toLocaleString("en-IN")}</p>
  <hr>
  <h1>Ledger: ${party.name}</h1>
  <p>${[party.mobile, party.address].filter(Boolean).join(" · ")}</p>
  <table>
    <thead><tr><th>#</th><th>Date</th><th>Particulars</th><th>Debit ₹</th><th>Credit ₹</th><th>Balance ₹</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
  <script>window.onload=()=>window.print();</script></body></html>`;
}

// ─── PAYMENT RECEIVE / PAYMENT GIVE MODAL (Issue 1) ──────────────────────────

function openQuickPaymentModal(paymentType = "RECEIVED", prePartyId = null) {
  document.getElementById("qpmnt-payment-type").value = paymentType;

  const isReceived = paymentType === "RECEIVED";
  document.getElementById("qpmnt-title").textContent = isReceived ? "💰 Payment Receive" : "📤 Payment Give";
  const saveBtn = document.getElementById("qpmnt-save-btn");
  saveBtn.textContent = isReceived ? "Save Payment" : "Save Payment";
  saveBtn.className = isReceived ? "btn btn-success" : "btn btn-danger";

  setTodayDate("qpmnt-date");
  document.getElementById("qpmnt-amount").value    = "";
  document.getElementById("qpmnt-note").value      = "";
  document.getElementById("qpmnt-reference").value = "";
  document.getElementById("qpmnt-mode").value      = "cash";
  clearPartySelection("qpmnt");

  const pid = prePartyId || S.currentPartyId;
  if (pid) {
    const p = S.currentParty || S.allParties.find(x => x.id === pid);
    if (p) setPartySelection("qpmnt", p);
  }
  openModal("modal-quick-payment");
}

// Backward-compatible alias (older buttons / inline handlers)
function openPaymentModal(prePartyId = null) {
  openQuickPaymentModal("RECEIVED", prePartyId);
}

async function saveQuickPayment() {
  if (S.submitLock) return;
  const partyId      = parseInt(document.getElementById("qpmnt-party-id").value);
  const amount       = parseFloat(document.getElementById("qpmnt-amount").value);
  const paymentType  = document.getElementById("qpmnt-payment-type").value;

  if (!partyId)            { toast("Select a customer", "error"); return; }
  if (!amount || amount <= 0) { toast("Enter a valid amount", "error"); return; }

  S.submitLock = true;
  const btn = document.getElementById("qpmnt-save-btn");
  btn.disabled = true; btn.textContent = "Saving…";

  try {
    await api("POST", "/api/payments/", {
      customer_id:       partyId,
      payment_type:      paymentType,
      amount,
      payment_mode:       document.getElementById("qpmnt-mode").value,
      reference_no:       document.getElementById("qpmnt-reference").value,
      note:               document.getElementById("qpmnt-note").value,
      transaction_date:   document.getElementById("qpmnt-date").value,
    });
    toast(paymentType === "RECEIVED" ? "Payment received ✓" : "Payment given ✓", "success");
    closeModal("modal-quick-payment");
    if (S.currentPage === "ledger")    loadLedgerData();
    if (S.currentPage === "dashboard") loadDashboard();
    if (S.currentPage === "customers") loadParties();
  } catch (e) {
    toast(e.message || "Error saving payment", "error");
  } finally {
    S.submitLock = false;
    btn.disabled = false;
    btn.textContent = "Save Payment";
  }
}

// ─── ADJUST PAYMENT AGAINST INVOICE MODAL (Issue 5) ──────────────────────────

let _adjustPaymentEntry = null;

async function openAdjustModal(entry) {
  _adjustPaymentEntry = entry;

  document.getElementById("adj-payment-summary").innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center">
      <div>
        <div style="font-weight:600">${esc(entry.particulars)}</div>
        <div style="font-size:12px;color:var(--text2)">${formatDate(entry.entry_date)}${entry.payment_mode ? " · " + esc(entry.payment_mode) : ""}</div>
      </div>
      <div style="font-size:18px;font-weight:700;color:var(--green2)">₹${fmt(entry.credit)}</div>
    </div>`;

  document.getElementById("adj-amount").value = entry.credit;
  document.getElementById("adj-amount").max   = entry.credit;
  document.getElementById("adj-date").value   = new Date().toISOString().slice(0,10);
  document.getElementById("adj-notes").value  = "";
  document.getElementById("adj-mode-existing").checked = true;
  toggleAdjMode();

  // Load this customer's open invoices for the dropdown
  const sel = document.getElementById("adj-invoice-select");
  sel.innerHTML = `<option value="">Loading invoices…</option>`;
  try {
    const invoices = await api("GET", `/api/invoices/?party_id=${entry.party_id}&type=${S.module}&per_page=50`);
    const open = (invoices.invoices || []).filter(i => !i.is_cancelled);
    if (open.length === 0) {
      sel.innerHTML = `<option value="">No invoices found — create a new one instead</option>`;
    } else {
      sel.innerHTML = `<option value="">— Select invoice —</option>` + open.map(inv =>
        `<option value="${inv.id}">#${esc(inv.invoice_number)} · ${formatDate(inv.invoice_date)} · ₹${fmt(inv.total_amount)}</option>`
      ).join("");
    }
  } catch {
    sel.innerHTML = `<option value="">Failed to load invoices</option>`;
  }

  openModal("modal-adjust");
}

function toggleAdjMode() {
  const isExisting = document.getElementById("adj-mode-existing").checked;
  document.getElementById("adj-existing-block").style.display = isExisting ? "" : "none";
  document.getElementById("adj-new-block").style.display      = isExisting ? "none" : "";
}

async function saveAdjustment() {
  if (S.submitLock) return;
  if (!_adjustPaymentEntry) return;

  const amount = parseFloat(document.getElementById("adj-amount").value) || 0;
  if (amount <= 0) { toast("Enter a valid amount", "error"); return; }
  if (amount > _adjustPaymentEntry.credit) {
    toast("Amount cannot exceed the payment received", "error");
    return;
  }

  const isExisting = document.getElementById("adj-mode-existing").checked;
  let invoiceId = null;

  S.submitLock = true;
  const btn = document.getElementById("adj-save-btn");
  btn.disabled = true; btn.textContent = "Saving…";

  try {
    if (isExisting) {
      invoiceId = parseInt(document.getElementById("adj-invoice-select").value) || null;
      if (!invoiceId) {
        toast("Select an invoice", "error");
        S.submitLock = false; btn.disabled = false; btn.textContent = "Adjust Payment";
        return;
      }
    } else {
      // Create a new invoice inline first, for the adjustment amount
      const desc = document.getElementById("adj-new-desc").value.trim() || "Service Charge";
      const newInvAmount = parseFloat(document.getElementById("adj-new-amount").value) || amount;
      const res = await api("POST", "/api/invoices/", {
        party_id: _adjustPaymentEntry.party_id,
        party_type: S.module,
        invoice_date: document.getElementById("adj-date").value,
        items: [{ product_name: desc, item_type: "service", amount: newInvAmount, is_manual_total: true }],
      });
      invoiceId = res.invoice.id;
    }

    const res2 = await api("POST", "/api/adjustments/", {
      payment_ledger_entry_id: _adjustPaymentEntry.id,
      invoice_id: invoiceId,
      amount,
      adjustment_date: document.getElementById("adj-date").value,
      notes: document.getElementById("adj-notes").value.trim(),
    });

    const s = res2.summary;
    let msg = `Adjusted ₹${fmt(amount)} ✓`;
    if (s.invoice_total != null) {
      const remaining = s.invoice_total - amount;
      msg += remaining > 0 ? ` · Outstanding ₹${fmt(remaining)}` : ` · Fully settled`;
    }
    toast(msg, "success");
    closeModal("modal-adjust");
    loadLedgerData();
    if (S.currentPage === "dashboard") loadDashboard();
  } catch (e) {
    toast(e.message || "Error saving adjustment", "error");
  } finally {
    S.submitLock = false;
    btn.disabled = false; btn.textContent = "Adjust Payment";
  }
}

// ─── DEBIT MODAL ───────────────────────────────────────────────────────────────

function openDebitModal() {
  setTodayDate("debit-date");
  document.getElementById("debit-amount").value      = "";
  document.getElementById("debit-particulars").value = "";
  document.getElementById("debit-notes").value       = "";
  openModal("modal-debit");
}

async function saveDebit() {
  if (S.submitLock) return;
  const amount = parseFloat(document.getElementById("debit-amount").value);
  const partic = document.getElementById("debit-particulars").value.trim();
  if (!amount || amount <= 0) { toast("Enter a valid amount", "error"); return; }
  if (!partic) { toast("Particulars required", "error"); return; }

  S.submitLock = true;
  try {
    await api("POST", "/api/ledger/debit", {
      party_id:    S.currentPartyId,
      amount,
      date:        document.getElementById("debit-date").value,
      particulars: partic,
      notes:       document.getElementById("debit-notes").value,
    });
    toast("Debit entry added ✓", "success");
    closeModal("modal-debit");
    loadLedgerData();
  } catch (e) {
    toast(e.message || "Error adding debit", "error");
  } finally {
    S.submitLock = false;
  }
}

// ─── EDIT ENTRY MODAL ──────────────────────────────────────────────────────────

function openEditEntry(entry) {
  document.getElementById("edit-entry-id").value          = entry.id;
  document.getElementById("edit-entry-date").value        = entry.entry_date || "";
  document.getElementById("edit-entry-particulars").value = entry.particulars || "";
  document.getElementById("edit-entry-notes").value       = entry.notes || "";
  document.getElementById("edit-entry-mode").value        = entry.payment_mode || "";

  const amtField = document.getElementById("edit-entry-amount");
  const note     = document.getElementById("edit-invoice-note");

  if (entry.invoice_id && entry.entry_type === "sale") {
    amtField.value   = entry.debit;
    amtField.disabled = true;
    note.style.display = "block";
  } else {
    amtField.value    = entry.debit > 0 ? entry.debit : entry.credit;
    amtField.disabled = false;
    note.style.display = "none";
  }
  openModal("modal-edit-entry");
}

async function saveEditEntry() {
  if (S.submitLock) return;
  const id = document.getElementById("edit-entry-id").value;
  S.submitLock = true;
  try {
    await api("PUT", `/api/ledger/${id}`, {
      date:         document.getElementById("edit-entry-date").value,
      particulars:  document.getElementById("edit-entry-particulars").value,
      notes:        document.getElementById("edit-entry-notes").value,
      payment_mode: document.getElementById("edit-entry-mode").value,
      amount:       parseFloat(document.getElementById("edit-entry-amount").value) || undefined,
    });
    toast("Entry updated ✓", "success");
    closeModal("modal-edit-entry");
    loadLedgerData();
  } catch (e) {
    toast(e.message || "Error updating entry", "error");
  } finally {
    S.submitLock = false;
  }
}

function confirmDeleteEntry(id) {
  openConfirm("Delete Entry", "Delete this ledger entry? Balance will be recalculated.", async () => {
    try {
      await api("DELETE", `/api/ledger/${id}`);
      toast("Entry deleted ✓", "success");
      loadLedgerData();
      if (S.currentPage === "dashboard") loadDashboard();
    } catch {
      toast("Error deleting entry", "error");
    }
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  INVOICES
// ═══════════════════════════════════════════════════════════════════════════════

async function loadInvoices() {
  const q      = (document.getElementById("inv-search")?.value || "").trim();
  const params = new URLSearchParams({ type: S.module, ...(q && { q }) });
  try {
    const data = await api("GET", `/api/invoices/?${params}`);
    S.invoices = data.invoices;
    renderInvoiceTable(data.invoices);
  } catch {
    toast("Failed to load invoices", "error");
  }
}

function renderInvoiceTable(invoices) {
  const tbody = document.getElementById("inv-table-body");
  const empty = document.getElementById("inv-empty");
  if (invoices.length === 0) {
    tbody.innerHTML = "";
    if (empty) empty.style.display = "block";
    return;
  }
  if (empty) empty.style.display = "none";
  tbody.innerHTML = invoices.map(inv => `
    <tr>
      <td><b style="color:var(--blue2)">${esc(inv.invoice_number)}</b></td>
      <td class="inv-tbl-hide-mobile">${formatDate(inv.invoice_date)}</td>
      <td>${esc(inv.party_name)}</td>
      <td class="td-r" style="color:var(--amber)"><b>${fmt(inv.total_amount)}</b></td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm btn-ghost" onclick="viewInvoice(${inv.id})">View</button>
          <button class="btn btn-sm btn-ghost" onclick="openEditInvoice(${inv.id})">Edit</button>
          <button class="btn btn-sm btn-ghost" style="color:var(--red2)" onclick="confirmCancelInvoice(${inv.id},'${esc(inv.invoice_number)}')">Cancel</button>
        </div>
      </td>
    </tr>`).join("");
}

// ── INVOICE BUILDER ───────────────────────────────────────────────────────────

let invRows = [];

function openInvoiceModal(prePartyId = null) {
  // ISSUE 3 FIX: fully reset every piece of form state so a previous
  // invoice's products/customer/notes/totals never bleed into a new one.
  resetInvoiceFormState();

  setTodayDate("inv-date");
  document.getElementById("inv-modal-sub").textContent = S.module === "customer" ? "Customer Invoice" : "Shoper Invoice";
  clearPartySelection("inv");

  if (prePartyId || S.currentPartyId) {
    const pid = prePartyId || S.currentPartyId;
    const p   = S.currentParty || S.allParties.find(x => x.id === pid);
    if (p) setPartySelection("inv", p);
  }

  addInvRow();
  updateInvTotals();
  openModal("modal-invoice");
}

function resetInvoiceFormState() {
  // Clear the row-tracking array AND the actual DOM — both must be wiped,
  // otherwise leftover row elements from the previous invoice stay visible
  // even though they're no longer tracked, or get duplicated on next save.
  invRows = [];
  const container = document.getElementById("inv-items-body");
  if (container) container.innerHTML = "";

  document.getElementById("inv-number").value   = "";
  document.getElementById("inv-due-date").value = "";
  document.getElementById("inv-notes").value    = "";
  document.getElementById("inv-date").value     = "";

  // Reset totals display back to ₹0 immediately (don't wait for next
  // recalc — a half-open modal should never show stale totals either).
  setText("inv-subtotal", "₹0.00");
  setText("inv-discount", "-₹0.00");
  setText("inv-gst",      "+₹0.00");
  setText("inv-grand",    "₹0.00");
}

function addInvRow(prefill = {}) {
  const rowId = Date.now() + Math.floor(Math.random() * 10000);
  const itemType = prefill.item_type || "inventory";
  invRows.push({ id: rowId, itemType });

  const container = document.getElementById("inv-items-body");
  const card = document.createElement("div");
  card.id = `inv-row-${rowId}`;
  card.className = "inv-item-card";
  card.dataset.itemType = itemType;

  const units = ["BAG","KG","TON","CFT","MTR","FEET","INCH","NOS","PCS","BOX","BUNDLE","ROLL","LTR","SQF","RFT","QTL"];
  const unitOpts = `<option value="">—</option>` + units.map(u =>
    `<option value="${u}" ${(prefill.unit||"")===u?"selected":""}>${u}</option>`
  ).join("");

  card.innerHTML = `
    <div class="inv-card-header">
      <!-- Item type toggle pill -->
      <div class="inv-type-toggle">
        <button type="button" class="inv-type-btn ${itemType==="inventory"?"active":""}"
          id="inv-type-inv-${rowId}" onclick="setInvRowType(${rowId},'inventory')">
          📦 Inventory
        </button>
        <button type="button" class="inv-type-btn svc ${itemType==="service"?"active":""}"
          id="inv-type-svc-${rowId}" onclick="setInvRowType(${rowId},'service')">
          🔧 Service / Charge
        </button>
      </div>
      <button class="inv-row-del" type="button" onclick="removeInvRow(${rowId})" title="Remove">✕</button>
    </div>

    <!-- Description / product name (always visible) -->
    <div class="inv-card-desc">
      <div class="prod-cell" style="position:relative;flex:1">
        <input class="inv-row-input" type="text"
          placeholder="${itemType==="service"?"e.g. Labour Charge, Transport Charge…":"🔍 Product name..."}"
          id="prod-name-${rowId}" value="${esc(prefill.product_name||prefill.description||"")}"
          oninput="onInvRowDescInput(${rowId},this.value)"
          onfocus="${itemType==="inventory"?`filterProdDrop(${rowId},this.value)`:""}"
          autocomplete="off" style="font-size:14px;font-weight:500;padding:10px 12px">
        <div class="prod-dropdown" id="prod-drop-${rowId}" style="display:none"></div>
      </div>
    </div>

    <!-- Inventory fields (hidden for service rows) -->
    <div class="inv-card-fields" id="inv-inv-fields-${rowId}"
      style="${itemType==="service"?"display:none":""}">
      <div class="inv-field-group">
        <label class="inv-field-lbl">Unit</label>
        <select class="inv-row-input inv-unit-sel" id="inv-unit-${rowId}">${unitOpts}</select>
      </div>
      <div class="inv-field-group">
        <label class="inv-field-lbl">Qty</label>
        <input class="inv-row-input" type="number" placeholder="0" id="inv-qty-${rowId}"
          min="0" step="0.001" value="${prefill.quantity||""}"
          oninput="recalcRow(${rowId})" inputmode="decimal">
      </div>
      <div class="inv-field-group">
        <label class="inv-field-lbl">Rate ₹</label>
        <input class="inv-row-input" type="number" placeholder="0.00" id="inv-rate-${rowId}"
          min="0" step="0.01" value="${prefill.rate||""}"
          oninput="recalcRow(${rowId})" inputmode="decimal">
      </div>
      <div class="inv-field-group">
        <label class="inv-field-lbl">Disc %</label>
        <input class="inv-row-input" type="number" placeholder="0" id="inv-disc-${rowId}"
          min="0" max="100" step="0.01"
          value="${prefill.discount_pct!=null?prefill.discount_pct:0}"
          oninput="recalcRow(${rowId})" inputmode="decimal">
      </div>
      <div class="inv-field-group">
        <label class="inv-field-lbl">GST %</label>
        <input class="inv-row-input" type="number" placeholder="0" id="inv-gst-${rowId}"
          min="0" max="28" step="0.01"
          value="${prefill.gst_pct!=null?prefill.gst_pct:0}"
          oninput="recalcRow(${rowId})" inputmode="decimal">
      </div>
      <div class="inv-field-group" style="min-width:110px">
        <label class="inv-field-lbl">
          Total
          <span class="manual-badge" id="inv-manual-badge-${rowId}"
            style="display:none;font-size:9px;color:var(--amber);margin-left:4px">✎ manual</span>
        </label>
        <input class="inv-row-input inv-total-override" type="number" placeholder="0.00"
          id="inv-row-total-${rowId}" min="0" step="0.01"
          value="${prefill.is_manual_total&&prefill.total?prefill.total:""}"
          oninput="onManualTotal(${rowId})" inputmode="decimal"
          title="Auto-calculated. Edit to override manually.">
      </div>
    </div>

    <!-- Service amount field (only visible for service rows) -->
    <div class="inv-card-fields" id="inv-svc-fields-${rowId}"
      style="${itemType==="inventory"?"display:none":""}">
      <div class="inv-field-group" style="flex:1;max-width:200px">
        <label class="inv-field-lbl">Amount ₹ <span class="req">*</span></label>
        <input class="inv-row-input" type="number" placeholder="0.00" id="inv-svc-amount-${rowId}"
          min="0" step="0.01"
          value="${itemType==="service"&&prefill.total?prefill.total:(prefill.amount||"")}"
          oninput="updateInvTotals()" inputmode="decimal">
      </div>
    </div>
  `;
  container.appendChild(card);

  if (itemType === "inventory" && prefill.is_manual_total && prefill.total) {
    document.getElementById(`inv-manual-badge-${rowId}`).style.display = "inline";
  }

  if (itemType === "inventory" && !prefill.is_manual_total) {
    recalcRow(rowId);
  }
}

function setInvRowType(rowId, newType) {
  const card = document.getElementById(`inv-row-${rowId}`);
  if (!card) return;
  card.dataset.itemType = newType;

  const row = invRows.find(r => r.id === rowId);
  if (row) row.itemType = newType;

  document.getElementById(`inv-type-inv-${rowId}`)?.classList.toggle("active", newType === "inventory");
  document.getElementById(`inv-type-svc-${rowId}`)?.classList.toggle("active", newType === "service");

  const invFields = document.getElementById(`inv-inv-fields-${rowId}`);
  const svcFields = document.getElementById(`inv-svc-fields-${rowId}`);
  const nameInput = document.getElementById(`prod-name-${rowId}`);

  if (newType === "service") {
    if (invFields) invFields.style.display = "none";
    if (svcFields) svcFields.style.display = "";
    if (nameInput) {
      nameInput.placeholder = "e.g. Labour Charge, Transport Charge…";
      nameInput.removeAttribute("onfocus");
      document.getElementById(`prod-drop-${rowId}`)?.style && (document.getElementById(`prod-drop-${rowId}`).style.display = "none");
    }
  } else {
    if (invFields) invFields.style.display = "";
    if (svcFields) svcFields.style.display = "none";
    if (nameInput) {
      nameInput.placeholder = "🔍 Product name...";
      nameInput.setAttribute("onfocus", `filterProdDrop(${rowId},this.value)`);
    }
    recalcRow(rowId);
  }
  updateInvTotals();
}

function onInvRowDescInput(rowId, value) {
  const card = document.getElementById(`inv-row-${rowId}`);
  if (card?.dataset?.itemType === "inventory") {
    filterProdDrop(rowId, value);
  }
}

function onManualTotal(rowId) {
  // User has manually typed a Total — mark this row as manually adjusted
  // so save logic sends is_manual_total=true and respects the override.
  const badge = document.getElementById(`inv-manual-badge-${rowId}`);
  const input = document.getElementById(`inv-row-total-${rowId}`);
  if (!input) return;
  const val = parseFloat(input.value);
  if (!isNaN(val) && input.value.trim() !== "") {
    if (badge) badge.style.display = "inline";
    const row = invRows.find(r => r.id === rowId);
    if (row) row.manualTotal = true;
  } else {
    if (badge) badge.style.display = "none";
    const row = invRows.find(r => r.id === rowId);
    if (row) row.manualTotal = false;
  }
  updateInvTotals();
}

function removeInvRow(rowId) {
  invRows = invRows.filter(r => r.id !== rowId);
  document.getElementById(`inv-row-${rowId}`)?.remove();
  updateInvTotals();
}

function recalcRow(rowId) {
  const card = document.getElementById(`inv-row-${rowId}`);
  if (!card || card.dataset.itemType === "service") {
    updateInvTotals();
    return;
  }
  const qty  = parseFloat(document.getElementById(`inv-qty-${rowId}`)?.value)  || 0;
  const rate = parseFloat(document.getElementById(`inv-rate-${rowId}`)?.value) || 0;
  const disc = parseFloat(document.getElementById(`inv-disc-${rowId}`)?.value) || 0;
  const gst  = parseFloat(document.getElementById(`inv-gst-${rowId}`)?.value)  || 0;
  const auto  = qty * rate * (1 - disc / 100) * (1 + gst / 100);

  // Only overwrite the total input if the user hasn't manually set it.
  const row = invRows.find(r => r.id === rowId);
  const totalInput = document.getElementById(`inv-row-total-${rowId}`);
  if (totalInput && !(row?.manualTotal)) {
    totalInput.value = auto > 0 ? auto.toFixed(2) : "";
    const badge = document.getElementById(`inv-manual-badge-${rowId}`);
    if (badge) badge.style.display = "none";
  }
  updateInvTotals();
}

function getRowTotal(rowId) {
  const card = document.getElementById(`inv-row-${rowId}`);
  if (!card) return 0;
  if (card.dataset.itemType === "service") {
    return parseFloat(document.getElementById(`inv-svc-amount-${rowId}`)?.value) || 0;
  }
  return parseFloat(document.getElementById(`inv-row-total-${rowId}`)?.value) || 0;
}

function updateInvTotals() {
  // The grand total is always the straight sum of each row's displayed
  // total — it never re-derives from qty*rate so manual overrides are
  // always respected.
  let grandTotal = 0;
  invRows.forEach(({ id }) => { grandTotal += getRowTotal(id); });
  setText("inv-grand", "₹" + fmt(grandTotal));
  // Keep the subtotal/discount/gst rows accurate for display only
  let subtotal = 0, discTotal = 0, gstTotal = 0;
  invRows.forEach(({ id }) => {
    const card = document.getElementById(`inv-row-${id}`);
    if (!card || card.dataset.itemType === "service") {
      subtotal += getRowTotal(id);
      return;
    }
    const qty  = parseFloat(document.getElementById(`inv-qty-${id}`)?.value)  || 0;
    const rate = parseFloat(document.getElementById(`inv-rate-${id}`)?.value) || 0;
    const disc = parseFloat(document.getElementById(`inv-disc-${id}`)?.value) || 0;
    const gst  = parseFloat(document.getElementById(`inv-gst-${id}`)?.value)  || 0;
    const base = qty * rate;
    const dAmt = base * disc / 100;
    const gAmt = (base - dAmt) * gst / 100;
    subtotal  += base;
    discTotal += dAmt;
    gstTotal  += gAmt;
  });
  setText("inv-subtotal", "₹" + fmt(subtotal));
  setText("inv-discount", "-₹" + fmt(discTotal));
  setText("inv-gst",      "+₹" + fmt(gstTotal));
}

async function saveInvoice() {
  if (S.submitLock) return;
  const partyId = parseInt(document.getElementById("inv-party-id").value);
  if (!partyId) { toast("Select a party", "error"); return; }

  const items = [];
  for (const { id, itemType, manualTotal } of invRows) {
    if (itemType === "service") {
      const desc   = (document.getElementById(`prod-name-${id}`)?.value || "").trim();
      const amount = parseFloat(document.getElementById(`inv-svc-amount-${id}`)?.value) || 0;
      if (!desc) continue;
      if (amount <= 0) { toast(`Enter amount for: ${desc}`, "error"); return; }
      items.push({ product_name: desc, item_type: "service", amount, is_manual_total: true });
    } else {
      const name  = (document.getElementById(`prod-name-${id}`)?.value || "").trim();
      const qty   = parseFloat(document.getElementById(`inv-qty-${id}`)?.value)  || 0;
      const rate  = parseFloat(document.getElementById(`inv-rate-${id}`)?.value) || 0;
      const total = parseFloat(document.getElementById(`inv-row-total-${id}`)?.value) || 0;
      const isManual = !!manualTotal;
      if (!name) continue;
      if (qty <= 0 && !isManual) { toast(`Enter quantity for: ${name}`, "error"); return; }
      if (total <= 0) continue;
      items.push({
        product_name: name,
        unit:         (document.getElementById(`inv-unit-${id}`)?.value  || "").trim(),
        quantity:     qty,
        rate,
        discount_pct: parseFloat(document.getElementById(`inv-disc-${id}`)?.value) || 0,
        gst_pct:      parseFloat(document.getElementById(`inv-gst-${id}`)?.value)  || 0,
        total:        isManual ? total : undefined,
        is_manual_total: isManual,
        item_type: "inventory",
      });
    }
  }

  if (items.length === 0) { toast("Add at least one item", "error"); return; }

  S.submitLock = true;
  const btn = document.getElementById("inv-save-btn");
  btn.disabled = true; btn.textContent = "Saving…";

  try {
    const res = await api("POST", "/api/invoices/", {
      party_id:       partyId,
      party_type:     S.module,
      invoice_date:   document.getElementById("inv-date").value,
      invoice_number: document.getElementById("inv-number").value.trim() || undefined,
      due_date:       document.getElementById("inv-due-date").value || undefined,
      notes:          document.getElementById("inv-notes").value.trim(),
      items,
    });
    toast(`Invoice ${res.invoice.invoice_number} saved ✓`, "success");
    closeModal("modal-invoice");
    if (S.currentPage === "ledger")    loadLedgerData();
    if (S.currentPage === "invoices")  loadInvoices();
    if (S.currentPage === "dashboard") loadDashboard();
    if (S.currentPage === "customers") loadParties();
    if (res.invoice && res.invoice.id) {
      setTimeout(() => viewInvoice(res.invoice.id), 300);
    }
  } catch (e) {
    toast(e.message || "Error saving invoice", "error");
  } finally {
    S.submitLock = false;
    btn.disabled = false; btn.textContent = "Save & Create Entry";
  }
}

// ── PRODUCT AUTOCOMPLETE ──────────────────────────────────────────────────────

async function filterProdDrop(rowId, q) {
  const drop = document.getElementById(`prod-drop-${rowId}`);
  if (!drop) return;
  try {
    const partyType = S.module || "customer";
    const products = await api("GET", `/api/invoices/products?q=${encodeURIComponent(q || "")}&party_type=${partyType}`);
    const filtered = q
      ? products.filter(p => p.name.toUpperCase().includes(q.toUpperCase()))
      : products;

    if (filtered.length === 0) {
      if (q && q.length > 1) {
        drop.innerHTML = `<div class="prod-dd-item">
          <span class="pd-item-create">➕ Add "${esc(q)}" as new product</span>
        </div>`;
        drop.querySelector(".prod-dd-item").onclick = () => {
          document.getElementById(`prod-name-${rowId}`).value = q;
          drop.style.display = "none";
        };
        drop.style.display = "block";
        // Mobile positioning
        if (window.innerWidth <= 768) {
          const vvh = window.visualViewport ? window.visualViewport.height : window.innerHeight;
          const kbHeight = window.innerHeight - vvh;
          drop.style.bottom = (kbHeight > 50 ? kbHeight : 0) + "px";
          drop.style.top = "auto";
        }
      } else {
        drop.style.display = "none";
      }
      return;
    }

    drop.innerHTML = filtered.map(p => `
      <div class="prod-dd-item" data-rowid="${rowId}" data-name="${esc(p.name)}" data-unit="${esc(p.default_unit||"")}" data-rate="${p.default_rate||0}">
        <div style="font-size:13px;font-weight:600">${esc(p.name)}</div>
        ${p.default_unit ? `<div style="font-size:11px;color:var(--text2);margin-top:2px">${esc(p.default_unit)} · ₹${fmt(p.default_rate)}</div>` : ""}
      </div>`).join("");

    // Use event delegation — works on mobile touch too
    drop.querySelectorAll(".prod-dd-item").forEach(el => {
      el.addEventListener("mousedown", (e) => {
        e.preventDefault();
        selectProdRow(
          parseInt(el.dataset.rowid),
          el.dataset.name,
          el.dataset.unit,
          parseFloat(el.dataset.rate) || 0
        );
      });
      el.addEventListener("touchend", (e) => {
        e.preventDefault();
        selectProdRow(
          parseInt(el.dataset.rowid),
          el.dataset.name,
          el.dataset.unit,
          parseFloat(el.dataset.rate) || 0
        );
      });
    });

    drop.style.display = "block";

    // Position dropdown — on mobile use fixed coords to escape overflow clipping
    const inputEl = document.getElementById(`prod-name-${rowId}`);
    if (inputEl) {
      const rect = inputEl.getBoundingClientRect();
      const isMobile = window.innerWidth <= 768;
      if (isMobile) {
        // Fixed positioning: show as bottom sheet above keyboard
        // Estimate keyboard height: if visual viewport is smaller, keyboard is up
        const vvh = window.visualViewport ? window.visualViewport.height : window.innerHeight;
        const kbHeight = window.innerHeight - vvh;
        const bottomOffset = kbHeight > 50 ? kbHeight : 0; // above keyboard
        drop.style.bottom = bottomOffset + "px";
        drop.style.top = "auto";
        drop.style.borderRadius = "16px 16px 0 0";
        drop.style.borderTop = "1.5px solid var(--blue)";
        drop.style.borderBottom = "none";
      } else {
        // Desktop: position relative to input
        const spaceBelow = window.innerHeight - rect.bottom;
        if (spaceBelow < 220) {
          drop.style.bottom = "100%";
          drop.style.top = "auto";
          drop.style.borderRadius = "8px 8px 0 0";
          drop.style.borderTop = "1.5px solid var(--blue)";
          drop.style.borderBottom = "none";
        } else {
          drop.style.bottom = "";
          drop.style.top = "100%";
          drop.style.borderRadius = "0 0 8px 8px";
          drop.style.borderTop = "none";
          drop.style.borderBottom = "";
        }
      }
    }
  } catch {
    drop.style.display = "none";
  }
}

function selectProdRow(rowId, name, unit, rate) {
  const ni = document.getElementById(`prod-name-${rowId}`);
  const ui = document.getElementById(`inv-unit-${rowId}`);
  const ri = document.getElementById(`inv-rate-${rowId}`);
  if (ni) ni.value = name;
  if (ui && unit) {
    // Try to set the select value; if unit not in options, add it dynamically
    ui.value = unit;
    if (ui.value !== unit) {
      const opt = document.createElement("option");
      opt.value = unit;
      opt.textContent = unit;
      ui.appendChild(opt);
      ui.value = unit;
    }
  }
  if (ri && rate) ri.value = rate;
  document.getElementById(`prod-drop-${rowId}`).style.display = "none";
  document.getElementById(`inv-qty-${rowId}`)?.focus();
  recalcRow(rowId);
}

// Close dropdowns when clicking outside
document.addEventListener("click", (e) => {
  if (!e.target.closest(".prod-cell")) {
    document.querySelectorAll(".prod-dropdown").forEach(d => d.style.display = "none");
  }
});

// ── VIEW INVOICE ──────────────────────────────────────────────────────────────

async function viewInvoice(invId) {
  S.invViewId = invId;
  try {
    const inv = await api("GET", `/api/invoices/${invId}`);
    document.getElementById("invv-title").textContent = `Invoice #${inv.invoice_number}`;
    document.getElementById("invoice-print-content").innerHTML = buildInvoiceHtml(inv);
    openModal("modal-inv-view");
  } catch {
    toast("Failed to load invoice", "error");
  }
}

function buildInvoiceHtml(inv) {
  const isShoper = inv.party_type === "shoper";
  const accentColor = isShoper ? "#7c3aed" : "#1e3a5f";
  const accentLight = isShoper ? "#ede9fe" : "#dbeafe";
  const accentText  = isShoper ? "#5b21b6" : "#1e40af";

  const rows = (inv.items || []).map((it, i) => {
    const isService = it.item_type === "service";
    const pName = it.product_name || "—";
    const pUnit = it.unit || "";
    if (isService) {
      return `
      <tr>
        <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-size:13px">${i+1}</td>
        <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-weight:600;font-size:13px">
          ${esc(pName)}
          <span style="font-size:10px;font-weight:700;color:#6366f1;margin-left:6px;padding:1px 6px;background:#ede9fe;border-radius:8px">SERVICE</span>
        </td>
        <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;color:#94a3b8;font-size:12px" colspan="5">—</td>
        <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:700;font-size:13px">₹${fmt(it.total)}</td>
      </tr>`;
    }
    return `
    <tr>
      <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-size:13px">${i+1}</td>
      <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-weight:600;font-size:13px">${esc(pName)}</td>
      <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;font-size:13px;color:#475569">${esc(pUnit)}</td>
      <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px">${parseFloat(it.quantity).toFixed(3)}</td>
      <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:13px">₹${fmt(it.rate)}</td>
      <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:13px">${parseFloat(it.discount_pct).toFixed(2)}%</td>
      <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;font-size:13px">${parseFloat(it.gst_pct).toFixed(2)}%</td>
      <td style="padding:8px 10px;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:700;font-size:13px">₹${fmt(it.total)}</td>
    </tr>`;
  }).join("");

  const invoiceTypeLbl = isShoper ? "WHOLESALE INVOICE" : "CUSTOMER INVOICE";

  return `<div style="font-family:'DM Sans',Arial,sans-serif;background:#fff;border-radius:10px;overflow:hidden">
    <!-- Header -->
    <div style="background:${accentColor};color:#fff;padding:24px 28px;display:flex;justify-content:space-between;align-items:flex-start">
      <div>
        <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:900;letter-spacing:.5px">SANDEEP TRADERS</div>
        <div style="font-size:12px;opacity:.8;margin-top:4px">Pakhopali Road, Thawe, Gopalganj, Bihar</div>
        <div style="font-size:12px;opacity:.8">Contact: Sandeep &amp; Mandeep</div>
      </div>
      <div style="text-align:right">
        <div style="background:rgba(255,255,255,.18);padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;letter-spacing:.8px;margin-bottom:8px">${invoiceTypeLbl}</div>
        <div style="font-family:'JetBrains Mono','Courier New',monospace;font-size:24px;font-weight:900">#${esc(inv.invoice_number)}</div>
      </div>
    </div>

    <!-- Party & Date Info -->
    <div style="padding:20px 28px;display:grid;grid-template-columns:1fr 1fr;gap:16px;border-bottom:1px solid #e2e8f0">
      <div>
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;color:#64748b;margin-bottom:6px">Bill To</div>
        <div style="font-size:17px;font-weight:700;color:#0f172a">${esc(inv.party_name)}</div>
        <div style="font-size:12px;color:#64748b;margin-top:3px">${isShoper ? "Wholesale / Shoper" : "Retail Customer"}</div>
      </div>
      <div style="text-align:right">
        <div style="font-size:12px;color:#64748b">Invoice Date: <b style="color:#0f172a">${formatDate(inv.invoice_date)}</b></div>
        ${inv.due_date ? `<div style="font-size:12px;color:#64748b;margin-top:5px">Due Date: <b style="color:#0f172a">${formatDate(inv.due_date)}</b></div>` : ""}
      </div>
    </div>

    <!-- Items Table -->
    <div style="padding:0 28px 20px">
      <table style="width:100%;border-collapse:collapse;margin-top:16px">
        <thead>
          <tr style="background:${accentLight}">
            <th style="padding:10px;text-align:left;font-size:11px;font-weight:700;letter-spacing:.5px;color:${accentText};text-transform:uppercase">#</th>
            <th style="padding:10px;text-align:left;font-size:11px;font-weight:700;letter-spacing:.5px;color:${accentText};text-transform:uppercase">Product Name</th>
            <th style="padding:10px;text-align:left;font-size:11px;font-weight:700;letter-spacing:.5px;color:${accentText};text-transform:uppercase">Unit</th>
            <th style="padding:10px;text-align:right;font-size:11px;font-weight:700;letter-spacing:.5px;color:${accentText};text-transform:uppercase">Qty</th>
            <th style="padding:10px;text-align:right;font-size:11px;font-weight:700;letter-spacing:.5px;color:${accentText};text-transform:uppercase">Rate ₹</th>
            <th style="padding:10px;text-align:right;font-size:11px;font-weight:700;letter-spacing:.5px;color:${accentText};text-transform:uppercase">Disc%</th>
            <th style="padding:10px;text-align:right;font-size:11px;font-weight:700;letter-spacing:.5px;color:${accentText};text-transform:uppercase">GST%</th>
            <th style="padding:10px;text-align:right;font-size:11px;font-weight:700;letter-spacing:.5px;color:${accentText};text-transform:uppercase">Total ₹</th>
          </tr>
        </thead>
        <tbody>${rows || `<tr><td colspan="8" style="text-align:center;padding:20px;color:#94a3b8">No items</td></tr>`}</tbody>
      </table>
    </div>

    <!-- Totals -->
    <div style="padding:16px 28px;border-top:2px solid ${accentLight};display:flex;justify-content:flex-end">
      <div style="min-width:220px">
        ${inv.subtotal > 0 ? `<div style="display:flex;justify-content:space-between;font-size:13px;color:#64748b;margin-bottom:6px"><span>Subtotal</span><span>₹${fmt(inv.subtotal)}</span></div>` : ""}
        ${inv.discount_amount > 0 ? `<div style="display:flex;justify-content:space-between;font-size:13px;color:#ef4444;margin-bottom:6px"><span>Discount</span><span>-₹${fmt(inv.discount_amount)}</span></div>` : ""}
        ${inv.gst_amount > 0 ? `<div style="display:flex;justify-content:space-between;font-size:13px;color:#64748b;margin-bottom:6px"><span>GST</span><span>+₹${fmt(inv.gst_amount)}</span></div>` : ""}
        <div style="display:flex;justify-content:space-between;font-size:18px;font-weight:900;color:${accentColor};border-top:2px solid ${accentLight};padding-top:10px;margin-top:4px">
          <span>Grand Total</span><span>₹${fmt(inv.total_amount)}</span>
        </div>
      </div>
    </div>

    ${inv.notes ? `<div style="margin:0 28px 16px;padding:10px 14px;background:#f8fafc;border-radius:8px;font-size:12px;color:#475569;border-left:3px solid ${accentColor}">Notes: ${esc(inv.notes)}</div>` : ""}

    <div style="text-align:center;padding:16px;background:${accentLight};font-size:12px;color:${accentText};font-weight:500">
      Thank you for your business! · SANDEEP TRADERS · Pakhopali Road, Thawe
    </div>
  </div>`;
}

function printInvoice() {
  const html  = document.getElementById("invoice-print-content").innerHTML;
  const win   = window.open("", "_blank", "width=750,height=620");
  win.document.write(`<!DOCTYPE html><html><head>
    <title>Invoice</title>
    <link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;900&family=DM+Sans:wght@400;500;600&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
    <style>
      *{margin:0;padding:0;box-sizing:border-box}
      body{font-family:'DM Sans',Arial,sans-serif;background:#fff}
      @media print{body{-webkit-print-color-adjust:exact}}
    </style>
  </head><body>${html}<script>window.onload=()=>window.print();</script></body></html>`);
  win.document.close();
}

// ── EDIT INVOICE ──────────────────────────────────────────────────────────────

let editInvId = null;
let editInvRows = [];

async function openEditInvoice(invId) {
  editInvId = invId;
  editInvRows = [];
  try {
    const inv = await api("GET", `/api/invoices/${invId}`);
    document.getElementById("edit-inv-id").value      = inv.id;
    document.getElementById("edit-inv-date").value    = inv.invoice_date || "";
    document.getElementById("edit-inv-number").value  = inv.invoice_number || "";
    document.getElementById("edit-inv-due").value     = inv.due_date || "";
    document.getElementById("edit-inv-notes").value   = inv.notes || "";

    // Populate items
    const tbody = document.getElementById("edit-inv-items-body");
    tbody.innerHTML = "";
    editInvRows = [];
    (inv.items || []).forEach(it => {
      addEditInvRow({
        product_name: it.product_name,
        unit: it.unit || "",
        quantity: it.quantity,
        rate: it.rate,
        discount_pct: it.discount_pct || 0,
        gst_pct: it.gst_pct || 0,
      });
    });
    if (editInvRows.length === 0) addEditInvRow();
    updateEditInvTotals();
    closeModal("modal-inv-view");
    openModal("modal-edit-invoice");
  } catch (e) {
    toast("Failed to load invoice for editing", "error");
  }
}

function addEditInvRow(prefill = {}) {
  const rowId = Date.now() + Math.floor(Math.random() * 10000);
  const itemType = prefill.item_type || "inventory";
  editInvRows.push({ id: rowId, itemType, manualTotal: !!prefill.is_manual_total });
  const tbody = document.getElementById("edit-inv-items-body");
  const tr = document.createElement("tr");
  tr.id = `edit-inv-row-${rowId}`;
  tr.dataset.itemType = itemType;

  const units = ["BAG","KG","TON","CFT","MTR","FEET","INCH","NOS","PCS","BOX","BUNDLE","ROLL","LTR","SQF","RFT","QTL"];
  const unitOpts = `<option value="">—</option>` + units.map(u =>
    `<option value="${u}" ${(prefill.unit||"")===u?"selected":""}>${u}</option>`
  ).join("");

  if (itemType === "service") {
    tr.innerHTML = `
      <td colspan="6" style="padding:4px 8px">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:10px;font-weight:700;color:var(--blue);padding:2px 8px;background:rgba(59,130,246,.12);border-radius:12px">🔧 SERVICE</span>
          <input class="inv-row-input" type="text" style="flex:1" placeholder="Service description…"
            id="edit-prod-name-${rowId}" value="${esc(prefill.product_name||"")}">
        </div>
      </td>
      <td>
        <input class="inv-row-input" type="number" placeholder="0.00" id="edit-inv-svc-amount-${rowId}"
          min="0" step="0.01" style="width:90px;text-align:right"
          value="${prefill.total||""}" oninput="updateEditInvTotals()">
      </td>
      <td><button class="inv-row-del" type="button" onclick="removeEditInvRow(${rowId})">✕</button></td>`;
  } else {
    const autoTotal = prefill.is_manual_total && prefill.total ? prefill.total : "";
    tr.innerHTML = `
      <td class="prod-cell">
        <input class="inv-row-input" type="text" placeholder="Product name" id="edit-prod-name-${rowId}"
          oninput="filterEditProdDrop(${rowId},this.value)" onfocus="filterEditProdDrop(${rowId},this.value)" autocomplete="off"
          value="${esc(prefill.product_name||"")}">
        <div class="prod-dropdown" id="edit-prod-drop-${rowId}" style="display:none"></div>
      </td>
      <td><select class="inv-row-input inv-unit-sel" id="edit-inv-unit-${rowId}" style="width:80px;padding:4px 2px;cursor:pointer">${unitOpts}</select></td>
      <td><input class="inv-row-input" type="number" placeholder="0" id="edit-inv-qty-${rowId}" min="0" step="0.001"
        oninput="recalcEditRow(${rowId})" style="width:70px;text-align:right" value="${prefill.quantity||""}"></td>
      <td><input class="inv-row-input" type="number" placeholder="0.00" id="edit-inv-rate-${rowId}" min="0" step="0.01"
        oninput="recalcEditRow(${rowId})" style="width:80px;text-align:right" value="${prefill.rate||""}"></td>
      <td><input class="inv-row-input" type="number" placeholder="0" id="edit-inv-disc-${rowId}" min="0" max="100" step="0.01"
        oninput="recalcEditRow(${rowId})" value="${prefill.discount_pct||0}" style="width:58px;text-align:right"></td>
      <td><input class="inv-row-input" type="number" placeholder="0" id="edit-inv-gst-${rowId}" min="0" max="28" step="0.01"
        oninput="recalcEditRow(${rowId})" value="${prefill.gst_pct||0}" style="width:52px;text-align:right"></td>
      <td>
        <input class="inv-row-input" type="number" placeholder="auto" id="edit-inv-row-total-${rowId}"
          min="0" step="0.01" style="width:90px;text-align:right;font-weight:600"
          value="${autoTotal}" oninput="onEditManualTotal(${rowId})"
          title="Auto-calculated. Edit to override manually.">
      </td>
      <td><button class="inv-row-del" type="button" onclick="removeEditInvRow(${rowId})">✕</button></td>`;
  }

  tbody.appendChild(tr);
  if (itemType === "inventory") recalcEditRow(rowId);
}

function onEditManualTotal(rowId) {
  const row = editInvRows.find(r => r.id === rowId);
  const input = document.getElementById(`edit-inv-row-total-${rowId}`);
  if (row && input) {
    row.manualTotal = input.value.trim() !== "" && !isNaN(parseFloat(input.value));
  }
  updateEditInvTotals();
}

function removeEditInvRow(rowId) {
  editInvRows = editInvRows.filter(r => r.id !== rowId);
  document.getElementById(`edit-inv-row-${rowId}`)?.remove();
  updateEditInvTotals();
}

function recalcEditRow(rowId) {
  const tr = document.getElementById(`edit-inv-row-${rowId}`);
  if (!tr || tr.dataset.itemType === "service") { updateEditInvTotals(); return; }
  const qty  = parseFloat(document.getElementById(`edit-inv-qty-${rowId}`)?.value)  || 0;
  const rate = parseFloat(document.getElementById(`edit-inv-rate-${rowId}`)?.value) || 0;
  const disc = parseFloat(document.getElementById(`edit-inv-disc-${rowId}`)?.value) || 0;
  const gst  = parseFloat(document.getElementById(`edit-inv-gst-${rowId}`)?.value)  || 0;
  const auto = qty * rate * (1 - disc/100) * (1 + gst/100);
  const row = editInvRows.find(r => r.id === rowId);
  const totalInput = document.getElementById(`edit-inv-row-total-${rowId}`);
  if (totalInput && !row?.manualTotal) {
    totalInput.value = auto > 0 ? auto.toFixed(2) : "";
  }
  updateEditInvTotals();
}

function getEditRowTotal(rowId) {
  const tr = document.getElementById(`edit-inv-row-${rowId}`);
  if (!tr) return 0;
  if (tr.dataset.itemType === "service") {
    return parseFloat(document.getElementById(`edit-inv-svc-amount-${rowId}`)?.value) || 0;
  }
  return parseFloat(document.getElementById(`edit-inv-row-total-${rowId}`)?.value) || 0;
}

function updateEditInvTotals() {
  let grandTotal = 0, subtotal = 0, discTotal = 0, gstTotal = 0;
  editInvRows.forEach(({ id }) => {
    grandTotal += getEditRowTotal(id);
    const tr = document.getElementById(`edit-inv-row-${id}`);
    if (!tr || tr.dataset.itemType === "service") { subtotal += getEditRowTotal(id); return; }
    const qty  = parseFloat(document.getElementById(`edit-inv-qty-${id}`)?.value)  || 0;
    const rate = parseFloat(document.getElementById(`edit-inv-rate-${id}`)?.value) || 0;
    const disc = parseFloat(document.getElementById(`edit-inv-disc-${id}`)?.value) || 0;
    const gst  = parseFloat(document.getElementById(`edit-inv-gst-${id}`)?.value)  || 0;
    const base = qty * rate;
    subtotal  += base;
    discTotal += base * disc / 100;
    gstTotal  += (base - base * disc / 100) * gst / 100;
  });
  setText("edit-inv-subtotal", "₹" + fmt(subtotal));
  setText("edit-inv-discount", "-₹" + fmt(discTotal));
  setText("edit-inv-gst",      "+₹" + fmt(gstTotal));
  setText("edit-inv-grand",    "₹" + fmt(grandTotal));
}

async function filterEditProdDrop(rowId, q) {
  const drop = document.getElementById(`edit-prod-drop-${rowId}`);
  if (!drop) return;
  try {
    const partyType = S.module || "customer";
    const products = await api("GET", `/api/invoices/products?q=${encodeURIComponent(q || "")}&party_type=${partyType}`);
    const filtered = q ? products.filter(p => p.name.toUpperCase().includes(q.toUpperCase())) : products;
    if (filtered.length === 0) { drop.style.display = "none"; return; }
    drop.innerHTML = filtered.map(p => `
      <div class="prod-dd-item" data-rowid="${rowId}" data-name="${esc(p.name)}" data-unit="${esc(p.default_unit||"")}" data-rate="${p.default_rate||0}">
        <div style="font-size:13px;font-weight:600">${esc(p.name)}</div>
        ${p.default_unit ? `<div style="font-size:11px;color:var(--text2);margin-top:2px">${esc(p.default_unit)} · ₹${fmt(p.default_rate)}</div>` : ""}
      </div>`).join("");
    drop.querySelectorAll(".prod-dd-item").forEach(el => {
      el.addEventListener("mousedown", (e) => { e.preventDefault(); selectEditProdRow(parseInt(el.dataset.rowid), el.dataset.name, el.dataset.unit, parseFloat(el.dataset.rate)||0); });
      el.addEventListener("touchend", (e) => { e.preventDefault(); selectEditProdRow(parseInt(el.dataset.rowid), el.dataset.name, el.dataset.unit, parseFloat(el.dataset.rate)||0); });
    });
    drop.style.display = "block";
    // Mobile: position as fixed bottom sheet above keyboard
    if (window.innerWidth <= 768) {
      const vvh = window.visualViewport ? window.visualViewport.height : window.innerHeight;
      const kbHeight = window.innerHeight - vvh;
      drop.style.bottom = (kbHeight > 50 ? kbHeight : 0) + "px";
      drop.style.top = "auto";
    }
  } catch { drop.style.display = "none"; }
}

function selectEditProdRow(rowId, name, unit, rate) {
  const ni = document.getElementById(`edit-prod-name-${rowId}`);
  const ui = document.getElementById(`edit-inv-unit-${rowId}`);
  const ri = document.getElementById(`edit-inv-rate-${rowId}`);
  if (ni) ni.value = name;
  if (ui && unit) { ui.value = unit; }
  if (ri && rate) ri.value = rate;
  document.getElementById(`edit-prod-drop-${rowId}`).style.display = "none";
  document.getElementById(`edit-inv-qty-${rowId}`)?.focus();
  recalcEditRow(rowId);
}

async function saveEditInvoice() {
  if (S.submitLock) return;
  const invId = editInvId;
  const items = [];
  for (const { id, itemType, manualTotal } of editInvRows) {
    if (itemType === "service") {
      const desc   = (document.getElementById(`edit-prod-name-${id}`)?.value || "").trim();
      const amount = parseFloat(document.getElementById(`edit-inv-svc-amount-${id}`)?.value) || 0;
      if (!desc || amount <= 0) continue;
      items.push({ product_name: desc, item_type: "service", amount, is_manual_total: true });
    } else {
      const name  = (document.getElementById(`edit-prod-name-${id}`)?.value || "").trim();
      const qty   = parseFloat(document.getElementById(`edit-inv-qty-${id}`)?.value)  || 0;
      const rate  = parseFloat(document.getElementById(`edit-inv-rate-${id}`)?.value) || 0;
      const total = parseFloat(document.getElementById(`edit-inv-row-total-${id}`)?.value) || 0;
      const isManual = !!manualTotal;
      if (!name || total <= 0) continue;
      items.push({
        product_name: name,
        unit:         (document.getElementById(`edit-inv-unit-${id}`)?.value || "").trim(),
        quantity:     qty,
        rate,
        discount_pct: parseFloat(document.getElementById(`edit-inv-disc-${id}`)?.value) || 0,
        gst_pct:      parseFloat(document.getElementById(`edit-inv-gst-${id}`)?.value)  || 0,
        total:        isManual ? total : undefined,
        is_manual_total: isManual,
        item_type: "inventory",
      });
    }
  }

  if (items.length === 0) { toast("Add at least one item", "error"); return; }

  S.submitLock = true;
  const btn = document.getElementById("edit-inv-save-btn");
  btn.disabled = true; btn.textContent = "Saving…";

  try {
    const res = await api("PUT", `/api/invoices/${invId}`, {
      invoice_date:   document.getElementById("edit-inv-date").value,
      invoice_number: document.getElementById("edit-inv-number").value.trim() || undefined,
      due_date:       document.getElementById("edit-inv-due").value || null,
      notes:          document.getElementById("edit-inv-notes").value.trim(),
      items,
    });
    toast(`Invoice updated ✓`, "success");
    closeModal("modal-edit-invoice");
    if (S.currentPage === "invoices")  loadInvoices();
    if (S.currentPage === "ledger")    loadLedgerData();
    if (S.currentPage === "dashboard") loadDashboard();
    setTimeout(() => viewInvoice(invId), 250);
  } catch (e) {
    toast(e.message || "Error updating invoice", "error");
  } finally {
    S.submitLock = false;
    btn.disabled = false; btn.textContent = "Save Changes";
  }
}

function confirmCancelInvoice(invId, invNum) {
  openConfirm("Cancel Invoice", `Cancel invoice <b>#${invNum}</b>? This will reverse the ledger entry.`, async () => {
    try {
      await api("POST", `/api/invoices/${invId}/cancel`);
      toast("Invoice cancelled ✓", "success");
      closeModal("modal-inv-view");
      loadInvoices();
      if (S.currentPage === "ledger") loadLedgerData();
    } catch {
      toast("Error cancelling invoice", "error");
    }
  });
}

async function cancelInvoice() {
  if (S.invViewId) confirmCancelInvoice(S.invViewId, "");
}

// ═══════════════════════════════════════════════════════════════════════════════
//  PRODUCTS PAGE
// ═══════════════════════════════════════════════════════════════════════════════

async function loadProducts() {
  const q = (document.getElementById("prod-search")?.value || "").trim();
  const partyType = S.module || "customer";
  try {
    const products = await api("GET", `/api/invoices/products?q=${encodeURIComponent(q)}&party_type=${partyType}`);
    S.products = products;
    renderProductsGrid(products);
  } catch {
    toast("Failed to load products", "error");
  }
}

function renderProductsGrid(products) {
  const grid = document.getElementById("products-grid");
  if (!grid) return;
  if (products.length === 0) {
    grid.innerHTML = `<div style="color:var(--text2);grid-column:1/-1;text-align:center;padding:24px">No products found</div>`;
    return;
  }
  grid.innerHTML = products.map(p => `
    <div class="prod-chip">
      <div class="prod-chip-name">${esc(p.name)}</div>
      <button class="prod-chip-del" title="Delete" onclick="confirmDeleteProduct(${p.id},'${esc(p.name).replace(/'/g,"\\'")}')">✕</button>
    </div>`).join("");
}

function openAddProductModal() {
  document.getElementById("new-prod-name").value = "";
  document.getElementById("new-prod-unit").value = "";
  document.getElementById("new-prod-rate").value = "";
  openModal("modal-add-product");
  setTimeout(() => document.getElementById("new-prod-name").focus(), 150);
}

async function saveNewProduct() {
  const name = document.getElementById("new-prod-name").value.trim();
  if (!name) { toast("Product name required", "error"); return; }
  try {
    await api("POST", "/api/invoices/products", {
      name,
      default_unit: document.getElementById("new-prod-unit").value,
      default_rate: parseFloat(document.getElementById("new-prod-rate").value) || 0,
    });
    toast("Product added ✓", "success");
    closeModal("modal-add-product");
    loadProducts();
  } catch (e) {
    toast(e.message || "Error adding product", "error");
  }
}

function confirmDeleteProduct(id, name) {
  openConfirm("Delete Product", `Remove <b>${name}</b> from product list?`, async () => {
    try {
      await api("DELETE", `/api/invoices/products/${id}`);
      toast("Product removed ✓", "success");
      loadProducts();
    } catch {
      toast("Error deleting product", "error");
    }
  });
}

// ═══════════════════════════════════════════════════════════════════════════════
//  NEW ENTRY FLOW
// ═══════════════════════════════════════════════════════════════════════════════

function openNewEntry() {
  openModal("modal-new-entry");
}

// ═══════════════════════════════════════════════════════════════════════════════
//  CHANGE PASSWORD
// ═══════════════════════════════════════════════════════════════════════════════

function openChangePassword() {
  closeAllDropdowns();
  document.getElementById("cpw-old").value = "";
  document.getElementById("cpw-new").value = "";
  document.getElementById("cpw-confirm").value = "";
  openModal("modal-change-pw");
}

async function saveChangePw() {
  const old = document.getElementById("cpw-old").value;
  const nw  = document.getElementById("cpw-new").value;
  const cf  = document.getElementById("cpw-confirm").value;
  if (nw !== cf) { toast("Passwords do not match", "error"); return; }
  if (nw.length < 6) { toast("Password must be at least 6 characters", "error"); return; }
  try {
    await api("POST", "/api/auth/change-password", { old_password: old, new_password: nw });
    toast("Password updated ✓", "success");
    closeModal("modal-change-pw");
  } catch (e) {
    toast(e.message || "Error updating password", "error");
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  PARTY SEARCH DROPDOWNS (shared component)
// ═══════════════════════════════════════════════════════════════════════════════

let _partySearchTimeout = {};

function searchPartyDropdown(prefix) {
  clearTimeout(_partySearchTimeout[prefix]);
  _partySearchTimeout[prefix] = setTimeout(() => _doPartySearch(prefix), 200);
}

async function _doPartySearch(prefix) {
  const input = document.getElementById(`${prefix}-party-search`);
  const drop  = document.getElementById(`${prefix}-party-dropdown`);
  if (!input || !drop) return;
  const q = input.value.trim();
  if (q.length < 1) { drop.style.display = "none"; return; }

  try {
    const params   = new URLSearchParams({ type: S.module, q });
    const parties  = await api("GET", `/api/parties/?${params}`);
    const results  = parties.slice(0, 8);

    let html = results.map(p => `
      <div class="pd-item" onclick="selectPartyInModal('${prefix}',${JSON.stringify(p).replace(/"/g,'&quot;')})">
        <div class="pd-item-name">${esc(p.name)}</div>
        <div class="pd-item-meta">${esc(p.mobile || "")} ${p.balance > 0 ? "· Bal: ₹"+fmt(p.balance) : ""}</div>
      </div>`).join("");

    // Option to create new
    html += `<div class="pd-item" onclick="createPartyFromModal('${prefix}','${esc(q).replace(/'/g,"\\'")}')">
      <span class="pd-item-create">➕ Add "${esc(q)}" as new ${S.module === "customer" ? "customer" : "shoper"}</span>
    </div>`;

    drop.innerHTML  = html;
    drop.style.display = "block";
  } catch {}
}

function selectPartyInModal(prefix, party) {
  setPartySelection(prefix, party);
}

function setPartySelection(prefix, party) {
  document.getElementById(`${prefix}-party-id`).value = party.id;
  document.getElementById(`${prefix}-party-name-chip`).textContent = party.name + (party.balance ? ` · ₹${fmt(Math.abs(party.balance))}` : "");
  document.getElementById(`${prefix}-selected-party`).style.display = "flex";
  document.getElementById(`${prefix}-party-search`).style.display   = "none";
  document.getElementById(`${prefix}-party-dropdown`).style.display = "none";
}

function clearPartySelection(prefix) {
  document.getElementById(`${prefix}-party-id`).value = "";
  document.getElementById(`${prefix}-selected-party`).style.display = "none";
  document.getElementById(`${prefix}-party-search`).style.display   = "";
  document.getElementById(`${prefix}-party-search`).value           = "";
}

async function createPartyFromModal(prefix, name) {
  document.getElementById(`${prefix}-party-dropdown`).style.display = "none";
  try {
    const newParty = await api("POST", "/api/parties/", {
      party_type: S.module,
      name:       name.trim(),
    });
    setPartySelection(prefix, newParty);
    toast(`${S.module === "customer" ? "Customer" : "Shoper"} "${name}" created ✓`, "success");
  } catch (e) {
    toast(e.message || "Error creating party", "error");
  }
}

// Close party dropdowns on outside click
document.addEventListener("click", (e) => {
  if (!e.target.closest(".party-search-wrap")) {
    document.querySelectorAll(".party-dropdown").forEach(d => d.style.display = "none");
  }
});

// ═══════════════════════════════════════════════════════════════════════════════
//  MODAL HELPERS
// ═══════════════════════════════════════════════════════════════════════════════

function openModal(id) {
  const el = document.getElementById(id);
  if (el) {
    el.classList.add("open");
    // Close on overlay click
    el.onclick = (e) => { if (e.target === el) closeModal(id); };
  }
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("open");
}

// ESC to close modals
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    document.querySelectorAll(".modal-overlay.open").forEach(m => m.classList.remove("open"));
  }
});

// ── CONFIRM MODAL ──────────────────────────────────────────────────────────────

let _confirmCallback = null;

function openConfirm(title, msg, onOk) {
  _confirmCallback = onOk;
  document.getElementById("confirm-title").textContent = title;
  document.getElementById("confirm-msg").innerHTML     = msg;
  document.getElementById("confirm-ok-btn").onclick    = () => { closeModal("modal-confirm"); onOk(); };
  openModal("modal-confirm");
}

// ═══════════════════════════════════════════════════════════════════════════════
//  API FETCH WRAPPER
// ═══════════════════════════════════════════════════════════════════════════════

async function api(method, url, body) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
  };
  if (body && method !== "GET") opts.body = JSON.stringify(body);
  const res  = await fetch(url, opts);

  // Handle non-JSON responses gracefully
  let data;
  try {
    data = await res.json();
  } catch {
    data = { error: `Server error (HTTP ${res.status})` };
  }

  if (res.status === 401) {
    S.user = null;
    // Close any open modals before redirecting to login
    document.querySelectorAll(".modal.open, .modal-overlay.open").forEach(m => m.classList.remove("open"));
    showLogin();
    throw new Error("Session expire ho gayi. Dobara login karo.");
  }
  if (!res.ok) {
    const errMsg = data.error || data.detail || `Server error (HTTP ${res.status})`;
    throw new Error(errMsg);
  }
  return data;
}

// ═══════════════════════════════════════════════════════════════════════════════
//  TOAST NOTIFICATIONS
// ═══════════════════════════════════════════════════════════════════════════════

let _toastTimeout;

function toast(msg, type = "info") {
  const el = document.getElementById("toast");
  clearTimeout(_toastTimeout);
  el.textContent = msg;
  el.className   = `toast show ${type}`;
  _toastTimeout  = setTimeout(() => { el.className = "toast"; }, 2800);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  FORMATTERS & UTILITIES
// ═══════════════════════════════════════════════════════════════════════════════

function fmt(n) {
  const num = parseFloat(n) || 0;
  return num.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtK(n) {
  const num = parseFloat(n) || 0;
  if (Math.abs(num) >= 1_00_000) return (num / 1_00_000).toFixed(1) + "L";
  if (Math.abs(num) >= 1_000)    return (num / 1_000).toFixed(1) + "K";
  return num.toFixed(0);
}

function formatDate(d) {
  if (!d) return "—";
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" });
}

function esc(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function setTodayDate(inputId) {
  const el = document.getElementById(inputId);
  if (el) el.value = new Date().toISOString().split("T")[0];
}

// ── MOBILE KEYBOARD HANDLER ──────────────────────────────────────────────────
// When keyboard appears/disappears on mobile, re-position open product dropdowns
if (window.visualViewport) {
  window.visualViewport.addEventListener("resize", () => {
    const kbHeight = window.innerHeight - window.visualViewport.height;
    const bottomOffset = kbHeight > 50 ? kbHeight : 0;
    document.querySelectorAll(".prod-dropdown[style*='block']").forEach(drop => {
      if (window.innerWidth <= 768) {
        drop.style.bottom = bottomOffset + "px";
        drop.style.top = "auto";
      }
    });
  });
}
