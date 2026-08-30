const refreshButton = document.getElementById("refresh-button");
const newsRoot = document.getElementById("news-root");
const updatedLine = document.getElementById("updated-line");
const feedStatus = document.getElementById("feed-status");
const feedStatusGrid = document.getElementById("feed-status-grid");

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function setMetric(id, value) {
  document.getElementById(id).textContent = value ?? 0;
}

function formatDate(value) {
  if (!value) return "Date unavailable";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Date unavailable";
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Denver",
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date) + " MT";
}

function showLoading(message = "RSS.app feeds are loading in the background.") {
  newsRoot.replaceChildren();
  const card = el("section", "loading-card");
  card.appendChild(el("div", "loading-dot"));
  const copy = el("div");
  copy.appendChild(el("h2", "", "Loading Wyoming policy coverage"));
  copy.appendChild(el("p", "", message));
  card.appendChild(copy);
  newsRoot.appendChild(card);
}

function showError(message) {
  newsRoot.replaceChildren();
  const card = el("section", "error-card");
  const copy = el("div");
  copy.appendChild(el("h2", "", "The site is online, but RSS.app could not be loaded."));
  copy.appendChild(el("p", "", message || "Try Refresh feeds again in a moment."));
  card.appendChild(copy);
  newsRoot.appendChild(card);
}

function renderCard(item) {
  const card = el("article", "story-card");

  if (item.image) {
    const imageLink = el("a", "story-image-link");
    imageLink.href = item.link;
    imageLink.target = "_blank";
    imageLink.rel = "noopener noreferrer";

    const image = el("img", "story-image");
    image.src = item.image;
    image.alt = "";
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    imageLink.appendChild(image);
    card.appendChild(imageLink);
  }

  const body = el("div", "story-body");
  const meta = el("div", "story-meta");
  meta.appendChild(el("span", "story-source", item.source || "Source"));
  meta.appendChild(el("span", "", formatDate(item.published_at)));
  body.appendChild(meta);

  const title = el("h3");
  const titleLink = el("a", "", item.title || "Untitled story");
  titleLink.href = item.link || "#";
  titleLink.target = "_blank";
  titleLink.rel = "noopener noreferrer";
  title.appendChild(titleLink);
  body.appendChild(title);

  body.appendChild(
    el(
      "p",
      "story-summary",
      item.summary || "Open the original article for full details.",
    ),
  );

  const readRow = el("div", "read-row");
  const readLink = el("a", "read-link", "Read original article");
  readLink.href = item.link || "#";
  readLink.target = "_blank";
  readLink.rel = "noopener noreferrer";
  readRow.appendChild(readLink);
  body.appendChild(readRow);

  card.appendChild(body);
  return card;
}

function renderFeedStatus(sections) {
  feedStatusGrid.replaceChildren();

  for (const section of sections) {
    const row = el("div", "feed-row");
    row.appendChild(el("span", "", section.category));

    if (section.status === "ok") {
      row.appendChild(
        el(
          "span",
          "feed-ok",
          `${section.items.length} ${section.items.length === 1 ? "item" : "items"}`,
        ),
      );
    } else {
      row.appendChild(el("span", "feed-failed", "feed unavailable"));
    }

    feedStatusGrid.appendChild(row);
  }

  feedStatus.hidden = false;
}

function renderDigest(payload) {
  const metrics = payload.metrics || {};
  const sections = payload.sections || [];

  setMetric("item-count", metrics.items || 0);
  setMetric("source-count", metrics.sources || 0);
  setMetric("feed-count", metrics.feeds || 9);
  setMetric("failed-count", metrics.failed_feeds || 0);

  updatedLine.textContent = `Current RSS.app feed contents · Updated ${formatDate(payload.generated_at)}` +
    (payload.refreshing ? " · refreshing" : "");

  newsRoot.replaceChildren();

  for (const section of sections) {
    const wrap = el("section", "category-section");
    const heading = el("div", "category-heading");
    heading.appendChild(el("h2", "", section.category));
    heading.appendChild(
      el(
        "span",
        "",
        `${section.items.length} ${section.items.length === 1 ? "item" : "items"}`,
      ),
    );
    wrap.appendChild(heading);

    if (section.items.length) {
      const grid = el("div", "story-grid");
      for (const item of section.items) {
        grid.appendChild(renderCard(item));
      }
      wrap.appendChild(grid);
    } else {
      const message = section.status === "ok"
        ? "RSS.app returned no items for this feed."
        : "This RSS.app feed is temporarily unavailable.";
      wrap.appendChild(el("div", "section-empty", message));
    }

    newsRoot.appendChild(wrap);
  }

  renderFeedStatus(sections);
}

async function loadNews({ force = false, attempt = 0 } = {}) {
  refreshButton.disabled = true;

  try {
    const url = force ? "/api/news?refresh=1" : "/api/news";
    const response = await fetch(url, { cache: "no-store" });
    const payload = await response.json();

    if (payload.status === "loading") {
      showLoading();
      if (attempt < 40) {
        window.setTimeout(
          () => loadNews({ force: false, attempt: attempt + 1 }),
          1200,
        );
      } else {
        showError("The RSS.app feeds are taking longer than expected.");
        refreshButton.disabled = false;
      }
      return;
    }

    if (payload.status === "error") {
      showError(`RSS refresh failed: ${payload.error || "unknown error"}.`);
      refreshButton.disabled = false;
      return;
    }

    renderDigest(payload);
    refreshButton.disabled = false;

    if (payload.refreshing && attempt < 40) {
      window.setTimeout(
        () => loadNews({ force: false, attempt: attempt + 1 }),
        1800,
      );
    }
  } catch (error) {
    if (attempt < 6) {
      window.setTimeout(
        () => loadNews({ force: false, attempt: attempt + 1 }),
        1200,
      );
      return;
    }

    showError("The news API could not be reached.");
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", () => {
  updatedLine.textContent = "Refreshing all nine RSS.app feeds…";
  feedStatus.hidden = true;
  showLoading("A fresh copy of all nine RSS.app feeds is being collected.");
  loadNews({ force: true });
});

loadNews();
