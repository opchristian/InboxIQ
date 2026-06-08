/**
 * InboxIQ — client-side inbox filtering, stats from visible cards, copy-to-clipboard.
 */
(function () {
  "use strict";

  const SEL = {
    card: "#email-grid .card",
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
    actionPlanContent: "#action-plan-content",
    actionPlanCopy: "#copy-action-plan",
  };

  const ACTION_PLAN_GROUPS = [
    { key: "urgent", title: "Urgent" },
    { key: "scheduling", title: "Scheduling" },
    { key: "follow_ups", title: "Follow-ups" },
    { key: "fyi", title: "FYI" },
  ];

  let actionPlanCopyText = "";

  /** Seed clipboard text from server-rendered action plan (before filters run). */
  function seedActionPlanCopyText() {
    const section = document.getElementById("action-plan-section");
    if (section && section.dataset.initialCopy) {
      actionPlanCopyText = section.dataset.initialCopy;
    }
  }

  /** Escape text before injecting into the action plan DOM. */
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /** Map dashboard category badge to an action plan group key. */
  function categoryToActionGroup(category) {
    const map = {
      Urgent: "urgent",
      Schedule: "scheduling",
      "Follow-up": "follow_ups",
      "Action Needed": "follow_ups",
      FYI: "fyi",
    };
    return map[category] || "";
  }

  /** First sentence or clause, trimmed for action-plan bullets. */
  function firstSentence(text, maxLen) {
    const limit = maxLen || 120;
    if (!text) return "";
    const cleaned = String(text).replace(/\s+/g, " ").trim();
    const parts = cleaned.split(/(?<=[.!?])\s+/);
    let sentence = parts[0] || cleaned;
    if (sentence.length > limit) {
      sentence = `${sentence.slice(0, limit - 3).trim()}...`;
    }
    return sentence;
  }

  /** Human-readable name from a From header. */
  function senderName(raw) {
    if (!raw) return "";
    const lt = raw.indexOf("<");
    if (lt > 0) {
      return raw.slice(0, lt).trim().replace(/^["']|["']$/g, "");
    }
    return raw.trim();
  }

  /** Detect calendar-style invites for scheduling bullets. */
  function isCalendarStyle(sender, subject) {
    const combo = `${sender} ${subject}`.toLowerCase();
    return ["calendar", "noreply@", "invitation", "invite", "rsvp", "google meet"].some(
      (kw) => combo.includes(kw)
    );
  }

  /** Read a structured output field from a card by its label. */
  function extractField(card, label) {
    const fields = card.querySelectorAll(".field");
    for (const field of fields) {
      const dt = field.querySelector("dt");
      if (dt && dt.textContent.trim().toLowerCase() === label.toLowerCase()) {
        if (label.toLowerCase() === "suggested reply") {
          const replyEl = field.querySelector(".reply");
          return replyEl ? replyEl.textContent.trim() : "";
        }
        const dd = field.querySelector("dd");
        return dd ? dd.textContent.trim() : "";
      }
    }
    return "";
  }

  /** Build one action-plan line from visible card content when data attributes are missing. */
  function buildLineFromCard(card, group, category) {
    const senderEl = card.querySelector(".card__sender");
    const subjectEl = card.querySelector(".card__subject");
    const sender = senderEl ? senderEl.textContent.trim() : "";
    const subject = subjectEl ? subjectEl.textContent.trim() : "";
    const name = senderName(sender);
    const task = extractField(card, "Task summary");
    const scheduling = extractField(card, "Scheduling need");
    const deadline = extractField(card, "Deadline");
    const suggested = extractField(card, "Suggested reply");

    if (category === "FYI" || group === "fyi") {
      const label = subject.split("—")[0].split(" - ")[0].trim() || name;
      return `${label}: No response needed.`;
    }

    if (category === "Schedule" || group === "scheduling") {
      const action = firstSentence(task || scheduling || subject);
      if (isCalendarStyle(sender, subject)) {
        return `Calendar invite: ${action}`;
      }
      return name ? `${name}: ${action}` : action;
    }

    if (category === "Urgent" || group === "urgent") {
      const action = firstSentence(task || deadline || subject);
      return name ? `${name}: ${action}` : action;
    }

    const action = firstSentence(task || suggested || subject);
    return name ? `${name}: ${action}` : action;
  }

  /** Build grouped action plan items from all analyzed email cards (ignores filters). */
  function buildActionPlanFromCards(cards) {
    const buckets = Object.fromEntries(
      ACTION_PLAN_GROUPS.map((group) => [group.key, []])
    );

    cards.forEach((card) => {
      const category = card.getAttribute("data-category") || "";
      let group = card.getAttribute("data-action-group") || "";
      let line = card.getAttribute("data-action-line") || "";

      if (!group) {
        group = categoryToActionGroup(category);
      }
      if (!line && group) {
        line = buildLineFromCard(card, group, category);
      }

      if (group && line && Object.prototype.hasOwnProperty.call(buckets, group)) {
        buckets[group].push(line);
      }
    });

    return ACTION_PLAN_GROUPS.map((group) => ({
      key: group.key,
      title: group.title,
      items: buckets[group.key],
    })).filter((group) => group.items.length > 0);
  }

  /** Plain-text clipboard payload for the action plan. */
  function formatActionPlanCopy(groups) {
    if (!groups.length) return "";
    const lines = ["Today's InboxIQ Action Plan", ""];
    groups.forEach((group) => {
      lines.push(group.title);
      group.items.forEach((item) => lines.push(`• ${item}`));
      lines.push("");
    });
    return `${lines.join("\n").trim()}\n`;
  }

  /** Render action plan groups into #action-plan-content from all analyzed cards. */
  function updateActionPlan() {
    const content = document.querySelector(SEL.actionPlanContent);
    const copyBtn = document.querySelector(SEL.actionPlanCopy);
    if (!content) return;

    const cards = document.querySelectorAll(SEL.card);
    const groups = buildActionPlanFromCards(cards);

    if (!groups.length) {
      content.innerHTML =
        '<p class="action-plan__empty">No action plan yet. Analyze inbox emails to generate one.</p>';
      actionPlanCopyText = "";
      if (copyBtn) copyBtn.disabled = true;
      return;
    }

    if (copyBtn) copyBtn.disabled = false;
    content.innerHTML = groups
      .map(
        (group) => `<div class="action-plan__group" data-action-plan-group="${escapeHtml(group.key)}">
          <h3 class="action-plan__group-title">${escapeHtml(group.title)}</h3>
          <ul class="action-plan__list">
            ${group.items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
          </ul>
        </div>`
      )
      .join("");

    actionPlanCopyText = formatActionPlanCopy(groups);
  }

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

  /** Searchable text for a card: data-search plus visible card fields. */
  function cardSearchText(card) {
    const parts = [card.getAttribute("data-search") || ""];

    const sender = card.querySelector(".card__sender");
    const subject = card.querySelector(".card__subject");
    const preview = card.querySelector(".card__preview");
    if (sender) parts.push(sender.textContent);
    if (subject) parts.push(subject.textContent);
    if (preview) parts.push(preview.textContent);

    card.querySelectorAll(".field").forEach((field) => {
      const reply = field.querySelector(".reply");
      if (reply) {
        parts.push(reply.textContent);
        return;
      }
      const dd = field.querySelector("dd");
      if (dd) parts.push(dd.textContent);
    });

    return parts.join(" ").toLowerCase().replace(/\s+/g, " ").trim();
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
      const blob = cardSearchText(card);

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

  /** Write text to clipboard (Clipboard API with textarea fallback). */
  async function writeToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.left = "-9999px";
    document.body.appendChild(textarea);
    textarea.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(textarea);
    if (!ok) throw new Error("copy failed");
  }

  /** Briefly swap a button label for copy feedback. */
  function flashCopyFeedback(button, success) {
    const original = button.textContent;
    button.textContent = success ? "Copied!" : "Copy failed";
    button.disabled = true;
    window.setTimeout(() => {
      button.textContent = original;
      button.disabled = false;
    }, 1600);
  }

  /** Copy the full action plan text; briefly swap button label for feedback. */
  async function copyActionPlan() {
    const copyBtn = document.querySelector(SEL.actionPlanCopy);
    if (!copyBtn || !actionPlanCopyText.trim()) return;

    try {
      await writeToClipboard(actionPlanCopyText);
      flashCopyFeedback(copyBtn, true);
    } catch {
      flashCopyFeedback(copyBtn, false);
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
    seedActionPlanCopyText();

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

    const actionPlanCopyBtn = document.querySelector(SEL.actionPlanCopy);
    if (actionPlanCopyBtn) {
      actionPlanCopyBtn.addEventListener("click", copyActionPlan);
    }

    updateActionPlan();
    applyFilters();
  });
})();
