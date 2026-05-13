/**
 * Pre-demo splash: intro copy, OAuth testing note, and actions before the demo dashboard.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "inboxiq_splash_dismissed";

  function dismissSplash() {
    var splash = document.getElementById("pre-demo-splash");
    if (!splash) return;
    splash.classList.add("is-dismissed");
    splash.setAttribute("aria-hidden", "true");
    document.body.classList.remove("pre-demo-splash-open");
    try {
      sessionStorage.setItem(STORAGE_KEY, "1");
    } catch (e) {}
  }

  function focusDashboardStart() {
    var nav = document.querySelector(".mode-switcher a");
    if (nav && typeof nav.focus === "function") nav.focus();
  }

  function scrollToWalkthrough() {
    var target = document.getElementById("live-gmail-walkthrough");
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(function () {
      if (typeof target.focus === "function") {
        try {
          target.focus({ preventScroll: true });
        } catch (e) {
          target.focus();
        }
      }
    }, 400);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var splash = document.getElementById("pre-demo-splash");
    if (!splash) return;

    var skipped =
      document.documentElement.classList.contains("splash-skipped") ||
      (function () {
        try {
          return sessionStorage.getItem(STORAGE_KEY) === "1";
        } catch (e) {
          return false;
        }
      })();

    var params = new URLSearchParams(window.location.search);
    if (params.get("skip_splash") === "1") {
      try {
        sessionStorage.setItem(STORAGE_KEY, "1");
      } catch (e) {}
      document.documentElement.classList.add("splash-skipped");
      skipped = true;
    }

    if (skipped) {
      splash.classList.add("is-dismissed");
      splash.setAttribute("aria-hidden", "true");
      document.body.classList.remove("pre-demo-splash-open");
      return;
    }

    document.body.classList.add("pre-demo-splash-open");
    splash.setAttribute("aria-hidden", "false");

    var enterBtn = document.getElementById("splash-enter-demo");
    if (enterBtn && typeof enterBtn.focus === "function") {
      window.setTimeout(function () {
        enterBtn.focus();
      }, 0);
    }

    var watchBtn = document.getElementById("splash-watch-walkthrough");

    if (enterBtn) {
      enterBtn.addEventListener("click", function () {
        dismissSplash();
        focusDashboardStart();
      });
    }

    if (watchBtn) {
      watchBtn.addEventListener("click", function () {
        dismissSplash();
        window.requestAnimationFrame(function () {
          scrollToWalkthrough();
        });
      });
    }
  });
})();
