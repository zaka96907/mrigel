// Small progressive enhancements. Every page works without this file.
(function () {
  "use strict";

  function on(root, selector, event, handler) {
    root.addEventListener(event, function (e) {
      var target = e.target.closest(selector);
      if (target && root.contains(target)) handler(e, target);
    });
  }

  function init(root) {
    // flashes: dismiss and fade out after a while
    root.querySelectorAll(".flash").forEach(function (el) {
      setTimeout(function () { el.remove(); }, 6000);
    });
    // stamp press, once, when the server marks it
    root.querySelectorAll(".stamp[data-press]").forEach(function (el) {
      el.classList.add("press");
    });
  }

  on(document, "[data-menu]", "click", function () {
    document.body.classList.toggle("nav-open");
  });
  on(document, ".scrim", "click", function () {
    document.body.classList.remove("nav-open");
  });
  on(document, ".flash button", "click", function (e, btn) {
    btn.closest(".flash").remove();
  });
  on(document, "[data-select-all]", "change", function (e, box) {
    var form = box.closest("form");
    form.querySelectorAll('input[name="ids"]').forEach(function (cb) { cb.checked = box.checked; });
  });
  on(document, "[data-copy]", "click", function (e, btn) {
    var input = document.getElementById(btn.getAttribute("data-copy"));
    if (!input) return;
    var text = input.value || input.textContent;
    var done = function () {
      var label = btn.querySelector("span");
      if (!label) return;
      var old = label.textContent;
      label.textContent = btn.getAttribute("data-copied") || "✓";
      setTimeout(function () { label.textContent = old; }, 1500);
    };
    if (navigator.clipboard) { navigator.clipboard.writeText(text).then(done); }
    else { input.select(); document.execCommand("copy"); done(); }
  });
  on(document, "[data-reveal]", "click", function (e, btn) {
    var input = document.getElementById(btn.getAttribute("data-reveal"));
    if (input) input.type = input.type === "password" ? "text" : "password";
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") document.body.classList.remove("nav-open");
  });

  // Order form: live total, and save the cart once the phone is filled (abandoned cart recovery).
  document.querySelectorAll("form[data-draft]").forEach(function (form) {
    var price = +form.getAttribute("data-price") || 0;
    var fee = +form.getAttribute("data-fee") || 0;
    var upsell = +form.getAttribute("data-upsell") || 0;
    var out = form.querySelector("[data-total]");
    var lastSent = "";
    function total() {
      var qty = +(form.querySelector('[name="qty"]') || {}).value || 1;
      var extra = form.querySelector('[name="upsell"]');
      var sum = price * qty + fee + (extra && extra.checked ? upsell : 0);
      if (out) out.textContent = sum.toLocaleString("fr-FR").replace(/\u202f|\u00a0/g, " ");
    }
    function draft() {
      var phone = (form.querySelector('[name="phone"]') || {}).value || "";
      if (phone.replace(/\D/g, "").length < 9 || !window.fetch) return;
      var data = new FormData(form);
      var key = Array.from(data.entries()).map(function (p) { return p.join("="); }).join("&");
      if (key === lastSent) return;
      lastSent = key;
      fetch(form.getAttribute("data-draft"), { method: "POST", body: data, credentials: "omit" }).catch(function () {});
    }
    form.addEventListener("change", function () { total(); draft(); });
    form.addEventListener("focusout", draft);
    total();
  });

  // Installable app: cache the shell so the queue opens on a weak connection.
  if ("serviceWorker" in navigator && document.querySelector('link[rel="manifest"]')) {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js").catch(function () {}); });
  }

  init(document);
})();
