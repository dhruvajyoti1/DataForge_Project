// EchoAssist — dashboard interactions.
// Auth guard, theme toggle, sidebar retract (desktop), mobile nav toggle, logout.

(function () {
  "use strict";

  /* ---------- Auth guard ----------
     No backend yet — this just makes sure the login page is what
     visitors land on first, by bouncing back to it if the session
     flag set by login.html isn't present. */
  if (sessionStorage.getItem("echoassist_loggedIn") !== "true") {
    window.location.href = "login.html";
    return;
  }

  const savedUsername = sessionStorage.getItem("echoassist_username");
  if (savedUsername) {
    const nameEl = document.getElementById("sidebar-user-name");
    const avatarEl = document.getElementById("sidebar-user-avatar");
    if (nameEl) nameEl.textContent = savedUsername;
    if (avatarEl) avatarEl.textContent = savedUsername.slice(0, 2).toUpperCase();
  }

  /* ---------- Theme toggle ---------- */
  const themeToggle = document.getElementById("theme-toggle");
  const themeLabel = themeToggle ? themeToggle.querySelector(".theme-toggle-label") : null;
  const root = document.documentElement;

  function applyTheme(isDark) {
    root.classList.toggle("dark", isDark);
    try { localStorage.setItem("echoassist_theme", isDark ? "dark" : "light"); } catch (e) {}
    if (themeLabel) themeLabel.textContent = isDark ? "Dark mode" : "Light mode";
    if (themeToggle) {
      themeToggle.setAttribute(
        "aria-label",
        isDark ? "Switch to light mode" : "Switch to dark mode"
      );
    }
  }

  // Read the same persisted preference the anti-flash head script used,
  // so every page (including login) agrees on the theme. Falls back to
  // the OS preference only the first time, before anything's been saved.
  let storedTheme = null;
  try { storedTheme = localStorage.getItem("echoassist_theme"); } catch (e) {}
  const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(storedTheme ? storedTheme === "dark" : prefersDark);

  if (themeToggle) {
    themeToggle.addEventListener("click", () => {
      applyTheme(!root.classList.contains("dark"));
    });
  }

  /* ---------- Desktop sidebar retract/expand ---------- */
  const retractBtn = document.getElementById("sidebar-retract");
  const sidebar = document.getElementById("sidebar");

  if (retractBtn && sidebar) {
    retractBtn.addEventListener("click", () => {
      const collapsed = sidebar.classList.toggle("is-collapsed");
      retractBtn.setAttribute("aria-expanded", String(!collapsed));
      retractBtn.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
    });
  }

  /* ---------- Mobile sidebar toggle ---------- */
  const navToggle = document.getElementById("mobile-nav-toggle");
  const overlay = document.getElementById("nav-overlay");

  function setNavOpen(open) {
    if (!sidebar || !overlay || !navToggle) return;
    sidebar.classList.toggle("is-open", open);
    overlay.classList.toggle("is-open", open);
    navToggle.setAttribute("aria-expanded", String(open));
  }

  if (navToggle) {
    navToggle.addEventListener("click", () => {
      setNavOpen(!sidebar.classList.contains("is-open"));
    });
  }

  if (overlay) {
    overlay.addEventListener("click", () => setNavOpen(false));
  }

  if (sidebar) {
    sidebar.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => setNavOpen(false));
    });
  }

  /* ---------- Logout ---------- */
  const logoutBtn = document.getElementById("logout-btn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      sessionStorage.removeItem("echoassist_loggedIn");
      sessionStorage.removeItem("echoassist_username");
      window.location.href = "login.html";
    });
  }
})();
