/** Initialise la navigation repliable, le drawer mobile et les formulaires automatiques. */
function initializeInterface() {
  const body = document.body;
  const sidebar = document.querySelector(".sidebar");
  const toggle = document.querySelector("[data-sidebar-toggle]");
  const opener = document.querySelector("[data-sidebar-open]");
  const overlay = document.querySelector("[data-sidebar-overlay]");

  function setCollapsed(collapsed) {
    body.classList.toggle("sidebar-collapsed", collapsed);
    toggle?.setAttribute("aria-expanded", String(!collapsed));
    const label = toggle?.querySelector(".sr-only");
    if (label) label.textContent = collapsed ? "Déployer le menu" : "Réduire le menu";
    try { localStorage.setItem("sidebar-collapsed", String(collapsed)); } catch (_) { /* Storage may be unavailable. */ }
  }

  function setMobileOpen(open) {
    const mobile = window.matchMedia('(max-width:760px)').matches;
    open = open && mobile;
    body.classList.toggle("sidebar-mobile-open", open);
    opener?.setAttribute("aria-expanded", String(open));
    if (sidebar) sidebar.inert = mobile && !open;
    const main = document.getElementById('main-content');
    if (main) main.inert = open;
    if (open) sidebar?.querySelector("a, button")?.focus();
    else if (mobile && sidebar?.contains(document.activeElement)) opener?.focus();
  }

  try { if (sidebar && localStorage.getItem("sidebar-collapsed") === "true") setCollapsed(true); } catch (_) { /* Keep the default layout. */ }
  setMobileOpen(false);
  window.matchMedia('(max-width:760px)').addEventListener('change', () => setMobileOpen(false));
  toggle?.addEventListener("click", () => setCollapsed(!body.classList.contains("sidebar-collapsed")));
  opener?.addEventListener("click", () => setMobileOpen(true));
  overlay?.addEventListener("click", () => setMobileOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setMobileOpen(false);
    if (event.key === 'Tab' && body.classList.contains('sidebar-mobile-open')) {
      const controls = Array.from(sidebar.querySelectorAll('a, button')).filter(element => element.getClientRects().length);
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  });
  document.querySelectorAll("[data-auto-submit]").forEach((form) => {
    form.querySelectorAll("select").forEach((select) => select.addEventListener("change", () => { form.classList.add("is-loading"); form.requestSubmit(); }));
  });
  document.querySelectorAll("[data-prevent-double-submit]").forEach((form) => {
    form.addEventListener("submit", () => {
      form.querySelectorAll("button[type='submit'], button:not([type])").forEach((button) => {
        window.setTimeout(() => { button.disabled = true; }, 0);
      });
    });
  });
  document.querySelectorAll("[data-file-upload]").forEach((form) => {
    const input = form.querySelector("input[type='file']");
    const filename = form.querySelector("[data-file-name]");
    input?.addEventListener("change", () => {
      if (filename) filename.textContent = input.files?.[0]?.name || "Aucun fichier sélectionné";
    });
    form.addEventListener("submit", () => {
      const label = form.querySelector("[data-submit-label]");
      if (label) label.textContent = "Import en cours…";
    });
  });
}
document.addEventListener("DOMContentLoaded", initializeInterface);
