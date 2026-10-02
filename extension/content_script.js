// Injected on https://www.youtube.com/results* (see manifest.json).
// Detects the search query, injects a sidebar panel, and renders ranked
// results from the backend for both Best Pick and Learning Path modes.
(function () {
  const SIDEBAR_ID = "ytf-sidebar";
  const LEVELS = ["all", "beginner", "intermediate", "advanced"];

  const MIN_FETCH_INTERVAL_MS = 5000; // hard cap: never fetch more than once per 5s,
                                       // regardless of how many change events fire
  const SEARCH_TIMEOUT_MS = 120000; // Learning Path can legitimately take over a
                                     // minute (decompose + up to 10 subtopic searches
                                     // + scoring); never leave the skeleton spinning
                                     // forever with no feedback

  const state = {
    query: null,
    mode: "best_pick",
    level: "all",
    cache: {}, // `${mode}::${level}::${query}` -> response data
    loading: false,
    lastFetchAt: 0,
  };

  function getSearchQuery() {
    return new URLSearchParams(window.location.search).get("search_query") || "";
  }

  function cacheKey() {
    return `${state.mode}::${state.level}::${state.query}`;
  }

  function sendSearch(query, mode, level) {
    return new Promise((resolve, reject) => {
      // Keeps the MV3 service worker alive for the duration of a potentially
      // long-running search — background.js can otherwise be terminated by
      // Chrome mid-request (idle timeout), silently breaking the response
      // path and leaving the sidebar stuck on the loading skeleton forever.
      const keepAlivePort = chrome.runtime.connect({ name: "keepalive" });
      let settled = false;

      const timeoutId = setTimeout(() => {
        if (settled) return;
        settled = true;
        keepAlivePort.disconnect();
        reject(new Error(`Search timed out after ${SEARCH_TIMEOUT_MS / 1000}s`));
      }, SEARCH_TIMEOUT_MS);

      chrome.runtime.sendMessage({ type: "SEARCH", query, mode, level }, (response) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeoutId);
        keepAlivePort.disconnect();
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        if (!response || !response.ok) {
          reject(new Error(response?.error || "Unknown error"));
          return;
        }
        resolve(response.data);
      });
    });
  }

  function el(tag, opts = {}, children = []) {
    const node = document.createElement(tag);
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = opts.text;
    if (opts.href) node.href = opts.href;
    if (opts.attrs) {
      for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
    }
    for (const child of children) node.appendChild(child);
    return node;
  }

  function buildSidebar() {
    const existing = document.getElementById(SIDEBAR_ID);
    if (existing) return existing;

    const container = el("div", { attrs: { id: SIDEBAR_ID } });

    const tabs = el("div", { className: "ytf-tabs" }, [
      el("button", { className: "ytf-tab ytf-tab-active", text: "★ Best Pick", attrs: { "data-mode": "best_pick" } }),
      el("button", { className: "ytf-tab", text: "🗺 Path", attrs: { "data-mode": "learning_path" } }),
      el("button", { className: "ytf-tab", text: "🎯 Skill Mix", attrs: { "data-mode": "skill_mix" } }),
    ]);

    const filterRow = el("div", { className: "ytf-filter-row" }, [
      el("label", { className: "ytf-filter-label", text: "Level:" }),
      (() => {
        const select = el("select", { className: "ytf-level-select" });
        for (const lvl of LEVELS) {
          const opt = el("option", { text: lvl[0].toUpperCase() + lvl.slice(1) });
          opt.value = lvl;
          select.appendChild(opt);
        }
        return select;
      })(),
    ]);

    const content = el("div", { className: "ytf-content" });

    container.appendChild(el("div", { className: "ytf-header", text: "Freeskool" }));
    container.appendChild(tabs);
    container.appendChild(filterRow);
    container.appendChild(content);

    tabs.querySelectorAll(".ytf-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        tabs.querySelectorAll(".ytf-tab").forEach((b) => b.classList.remove("ytf-tab-active"));
        btn.classList.add("ytf-tab-active");
        state.mode = btn.dataset.mode;
        loadAndRender();
      });
    });

    const levelSelect = filterRow.querySelector(".ytf-level-select");
    chrome.storage.local.get("level", ({ level }) => {
      if (level && LEVELS.includes(level)) {
        state.level = level;
        levelSelect.value = level;
      }
    });
    levelSelect.addEventListener("change", () => {
      state.level = levelSelect.value;
      chrome.storage.local.set({ level: state.level });
      loadAndRender();
    });

    (document.body || document.documentElement).appendChild(container);
    return container;
  }

  function renderLoading(content) {
    content.replaceChildren(
      el("div", { className: "ytf-skeleton" }, [
        el("div", { className: "ytf-skeleton-line" }),
        el("div", { className: "ytf-skeleton-line" }),
        el("div", { className: "ytf-skeleton-line ytf-skeleton-short" }),
      ])
    );
  }

  function renderError(content, message) {
    content.replaceChildren(el("div", { className: "ytf-error", text: `Couldn't load results: ${message}` }));
  }

  function levelPill(level) {
    return el("span", { className: `ytf-pill ytf-pill-${level || "unknown"}`, text: level || "unknown" });
  }

  function typeBadge(type) {
    return el("span", { className: "ytf-badge", text: type === "playlist" ? "PLAYLIST" : "VIDEO" });
  }

  function buildResultCard(item, { hero } = { hero: false }) {
    const card = el("div", { className: hero ? "ytf-card ytf-hero" : "ytf-card ytf-runner-up" });
    const top = el("div", { className: "ytf-card-top" }, [typeBadge(item.type), levelPill(item.level)]);
    const title = el("div", { className: "ytf-card-title", text: item.title });
    const meta = el("div", { className: "ytf-card-meta", text: `${item.channel} · score ${item.score}/10` });
    const summary = el("div", { className: "ytf-card-summary", text: item.summary || "" });

    card.appendChild(top);
    card.appendChild(title);
    card.appendChild(meta);
    card.appendChild(summary);

    if (hero) {
      card.appendChild(el("div", { className: "ytf-why", text: item.why_best || "" }));
      card.appendChild(el("a", { className: "ytf-watch-btn", text: "Watch Now", href: item.url, attrs: { target: "_blank", rel: "noopener" } }));
    } else {
      card.appendChild(el("a", { className: "ytf-watch-link", text: "Watch →", href: item.url, attrs: { target: "_blank", rel: "noopener" } }));
    }
    return card;
  }

  function renderBestPick(content, data) {
    content.replaceChildren();
    if (!data.recommendation) {
      content.appendChild(el("div", { className: "ytf-empty", text: "No good results found for this query and level." }));
      return;
    }
    content.appendChild(buildResultCard(data.recommendation, { hero: true }));

    if (data.runners_up && data.runners_up.length) {
      const runnersHeader = el("div", { className: "ytf-runners-header", text: `Also worth watching (${data.runners_up.length})` });
      runnersHeader.addEventListener("click", () => runnersBody.classList.toggle("ytf-collapsed"));
      const runnersBody = el("div", { className: "ytf-runners-body ytf-collapsed" });
      for (const r of data.runners_up) runnersBody.appendChild(buildResultCard(r, { hero: false }));
      content.appendChild(runnersHeader);
      content.appendChild(runnersBody);
    }
  }

  function formatDuration(mins) {
    if (mins == null) return "";
    if (mins < 60) return `${Math.round(mins)} min`;
    return `${(mins / 60).toFixed(1)} hrs`;
  }

  function renderPathBased(content, data) {
    content.replaceChildren();

    const header = el("div", { className: "ytf-path-header" }, [
      el("div", { className: "ytf-path-title", text: data.topic || "" }),
      el("div", { className: "ytf-path-total", text: `Estimated total: ${data.estimated_total_hrs} hrs · ${data.level}` }),
    ]);
    if (data.domains && data.domains.length) {
      header.appendChild(el("div", { className: "ytf-path-domains", text: `Skills: ${data.domains.join(" + ")}` }));
    }
    content.appendChild(header);

    if (data.gaps && data.gaps.length) {
      const gapsBox = el("div", { className: "ytf-gaps" }, [
        el("div", { className: "ytf-gaps-title", text: "⚠ Gaps — no strong tutorial found for:" }),
      ]);
      for (const g of data.gaps) gapsBox.appendChild(el("div", { className: "ytf-gap-item", text: g }));
      content.appendChild(gapsBox);
    }

    if (!data.path || !data.path.length) {
      content.appendChild(el("div", { className: "ytf-empty", text: "No path could be assembled for this topic." }));
      return;
    }

    const openAllBtn = el("button", { className: "ytf-open-all-btn", text: "Open All in Queue" });
    openAllBtn.addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "OPEN_TABS", urls: data.path.map((s) => s.url) });
    });
    content.appendChild(openAllBtn);

    const list = el("div", { className: "ytf-path-list" });
    for (const step of data.path) {
      const stepCard = el("div", { className: "ytf-path-step" });
      stepCard.appendChild(el("div", { className: "ytf-step-num", text: String(step.step) }));
      const body = el("div", { className: "ytf-step-body" });
      body.appendChild(el("div", { className: "ytf-step-subtopic", text: step.subtopic }));
      body.appendChild(el("a", { className: "ytf-step-title", text: step.title, href: step.url, attrs: { target: "_blank", rel: "noopener" } }));
      body.appendChild(el("div", { className: "ytf-step-meta", text: `${step.channel} · ${typeBadgeText(step.type)} · ${formatDuration(step.duration_mins)}` }));
      body.appendChild(el("div", { className: "ytf-step-why", text: step.why || "" }));
      stepCard.appendChild(body);
      list.appendChild(stepCard);
    }
    content.appendChild(list);
  }

  function typeBadgeText(type) {
    return type === "playlist" ? "Playlist" : "Video";
  }

  function renderResults(content, mode, data) {
    if (mode === "best_pick") {
      renderBestPick(content, data);
    } else {
      // learning_path and skill_mix share the exact same output shape
      // (skill_mix just adds a "domains" field) — same renderer for both.
      renderPathBased(content, data);
    }
  }

  async function loadAndRender() {
    const container = buildSidebar();
    const content = container.querySelector(".ytf-content");
    if (!state.query) return;

    // Captured now, not read from `state` again later — state.mode can
    // change (user switches tabs) while this specific request is still in
    // flight below. Rendering against a since-changed state.mode made a
    // stale response from an abandoned tab get displayed as if it were the
    // now-active tab's data (confirmed live: Learning Path and Skill Mix
    // showing "the same videos" after a tab switch mid-request). Render
    // decisions in this call must stay pinned to the mode it was actually
    // fetched for.
    const mode = state.mode;
    const key = cacheKey();
    if (state.cache[key]) {
      renderResults(content, mode, state.cache[key]);
      return;
    }

    // Each backend call costs real SerpApi/LLM credits — these two guards are
    // a hard stop against ever firing overlapping or rapid-fire requests, no
    // matter how many "the query changed" signals arrive in quick succession.
    // Blocked requests still need visible feedback — a silent no-op here
    // previously left the sidebar showing stale data from a different tab/
    // mode with no explanation why a tab switch seemingly "did nothing."
    if (state.loading) {
      renderError(content, "Still loading the previous request — try again in a moment.");
      return;
    }
    const now = Date.now();
    const waitRemainingMs = MIN_FETCH_INTERVAL_MS - (now - state.lastFetchAt);
    if (waitRemainingMs > 0) {
      renderError(content, `Please wait ${Math.ceil(waitRemainingMs / 1000)}s before searching again.`);
      return;
    }

    state.loading = true;
    state.lastFetchAt = now;
    renderLoading(content);
    try {
      const data = await sendSearch(state.query, mode, state.level);
      state.cache[key] = data;
      // Only render if this request's tab/mode is still the one showing —
      // otherwise this is exactly the stale-response case above, now caught
      // at render time too: the data is still cached under its own key for
      // when the user switches back, just not painted over whatever's
      // currently on screen.
      if (state.mode === mode) {
        renderResults(content, mode, data);
      }
    } catch (err) {
      if (state.mode === mode) {
        renderError(content, err.message || String(err));
      }
    } finally {
      state.loading = false;
      // The user switched tabs while this request was in flight — it just
      // finished for the tab they left, not the one they're on now,  so
      // pick up the one they actually want. Still subject to the
      // MIN_FETCH_INTERVAL_MS guard above, so this can't bypass the rate
      // limit — worst case it shows "please wait Xs" instead of leaving the
      // sidebar stuck on "still loading" with nothing to act on.
      if (state.mode !== mode) {
        loadAndRender();
      }
    }
  }

  function onQueryChange() {
    const q = getSearchQuery();
    if (q === state.query) return;
    state.query = q;
    state.cache = {};
    loadAndRender();
  }

  // Searching from YouTube's own search bar (as opposed to typing a new URL)
  // navigates via history.pushState, not a full page load. yt-navigate-finish
  // is supposed to cover this, but doesn't reliably fire for every in-page
  // search-bar submission (confirmed: URL-bar reload always updated results,
  // the on-page search box sometimes didn't) — patching pushState/replaceState
  // directly catches every URL change regardless of how YouTube's own event
  // dispatch behaves. Still no interval/polling: this only reacts to actual
  // navigation calls, so it can't fire on its own without a real URL change.
  function patchHistoryForSpaNav() {
    for (const method of ["pushState", "replaceState"]) {
      const original = history[method];
      history[method] = function (...args) {
        const result = original.apply(this, args);
        onQueryChange();
        return result;
      };
    }
  }

  function init() {
    buildSidebar();
    onQueryChange();

    patchHistoryForSpaNav();
    document.addEventListener("yt-navigate-finish", onQueryChange);
    window.addEventListener("popstate", onQueryChange);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
