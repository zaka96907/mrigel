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

  init(document);
})();
