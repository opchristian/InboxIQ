/**
 * InboxIQ — client-side inbox filtering, stats from visible cards, copy-to-clipboard.
 */
(function () {
  "use strict";

  const SEL = {
    card: ".card",
    search: "#inbox-search",
    empty: "#empty-state",
    grid: "#email-grid",
    chipCat: "[data-filter-group='category'] .filter-chip",
    chipPri: "[data-filter-group='priority'] .filter-chip",
    statTotal: "#stat-total",
    statAction: "#stat-action",
    statSchedule: "#stat-schedule",
    statFollow: "#stat-followup",
    statUrgent: "#stat-urgent",
  };

  /** Read filter state from the active chip in a button group. */
  function activeValue(buttons, attrName, fallback) {
    const active = Array.from(buttons).find((b) => b.classList.contains("is-active"));
    return active ? active.getAttribute(attrName) || fallback : fallback;
  }

  /** Toggle active chip styling within one [data-filter-group] container. */
  function activateChip(clicked, siblings) {
    siblings.forEach((b) => b.classList.remove("is-active"));
    clicked.classList.add("is-active");
  }

  /** Recompute visibility, stats (from visible cards only), and empty state from filters + search. */
  function applyFilters() {
    const searchEl = document.querySelector(SEL.search);
    const cards = document.querySelectorAll(SEL.card);
    const emptyEl = document.querySelector(SEL.empty);
    const chipsCat = document.querySelectorAll(SEL.chipCat);
    const chipsPri = document.querySelectorAll(SEL.chipPri);
    const setupCard = document.getElementById("live-setup-card");

    const q = (searchEl && searchEl.value ? searchEl.value : "").trim().toLowerCase();
    const cat = activeValue(chipsCat, "data-category", "all");
    const pri = activeValue(chipsPri, "data-priority", "all");

    const counts = {
      total: 0,
      "Action Needed": 0,
      Schedule: 0,
      "Follow-up": 0,
      Urgent: 0,
    };

    cards.forEach((card) => {
      const c = card.getAttribute("data-category") || "";
      const p = card.getAttribute("data-priority") || "";
      const blob = (card.getAttribute("data-search") || "").toLowerCase();

      const matchCat = cat === "all" || c === cat;
      const matchPri = pri === "all" || p === pri;
      const matchSearch = !q || blob.includes(q);

      const show = matchCat && matchPri && matchSearch;
      card.hidden = !show;

      if (show) {
        counts.total += 1;
        if (Object.prototype.hasOwnProperty.call(counts, c)) {
          counts[c] += 1;
        }
      }
    });

    const setText = (id, val) => {
      const el = document.querySelector(id);
      if (el) el.textContent = String(val);
    };

    setText(SEL.statTotal, counts.total);
    setText(SEL.statAction, counts["Action Needed"]);
    setText(SEL.statSchedule, counts.Schedule);
    setText(SEL.statFollow, counts["Follow-up"]);
    setText(SEL.statUrgent, counts.Urgent);

    if (emptyEl) {
      const setupBlocksFilterEmpty =
        setupCard && !setupCard.classList.contains("is-hidden");
      const hideEmpty = counts.total > 0 || setupBlocksFilterEmpty;
      emptyEl.classList.toggle("is-hidden", hideEmpty);
      emptyEl.setAttribute("aria-hidden", hideEmpty ? "true" : "false");
    }
  }

  /** Copy suggested reply text; briefly swap button label for feedback. */
  async function copySuggestedReply(button) {
    const wrap = button.closest(".field--reply");
    if (!wrap) return;
    const replyEl = wrap.querySelector(".reply");
    const text = replyEl ? replyEl.textContent : "";
    const original = button.textContent;

    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied!";
      button.disabled = true;
      window.setTimeout(() => {
        button.textContent = original;
        button.disabled = false;
      }, 1600);
    } catch {
      button.textContent = "Copy failed";
      window.setTimeout(() => {
        button.textContent = original;
        button.disabled = false;
      }, 1600);
    }
  }

  /** Wire mutually exclusive chips inside each [data-filter-group] container. */
  function bindFilterChips(selector) {
    document.querySelectorAll(selector).forEach((btn) => {
      btn.addEventListener("click", () => {
        const group = btn.closest("[data-filter-group]");
        if (!group) return;
        activateChip(btn, group.querySelectorAll(".filter-chip"));
        applyFilters();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const searchEl = document.querySelector(SEL.search);
    if (searchEl) {
      searchEl.addEventListener("input", applyFilters);
    }

    bindFilterChips(SEL.chipCat);
    bindFilterChips(SEL.chipPri);

    const grid = document.querySelector(SEL.grid);
    if (grid) {
      grid.addEventListener("click", (e) => {
        const btn = e.target.closest(".btn--copy");
        if (btn && grid.contains(btn)) copySuggestedReply(btn);
      });
    }

    applyFilters();
  });
})();
