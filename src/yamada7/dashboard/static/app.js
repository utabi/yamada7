const REFRESH_MS = 2000;
const refreshIndicator = document.getElementById("refresh-interval");
const latestTick = document.getElementById("latest-tick");
const latestLife = document.getElementById("latest-life");
const latestResources = document.getElementById("latest-resources");
const latestDanger = document.getElementById("latest-danger");
const latestUnknown = document.getElementById("latest-unknown");
const latestReward = document.getElementById("latest-reward");
const latestFear = document.getElementById("latest-fear");
const latestCuriosity = document.getElementById("latest-curiosity");
const latestPlan = document.getElementById("latest-plan");
const latestRaw = document.getElementById("latest-raw");
const eventsList = document.getElementById("events-list");
const playbookUpdates = document.getElementById("playbook-updates");
const refreshBtn = document.getElementById("refresh-btn");
const playbookStatsFiles = document.getElementById("playbook-stats-files");
const playbookStatsSections = document.getElementById("playbook-stats-sections");
const playbookStatsChars = document.getElementById("playbook-stats-chars");

let timer = null;
let chart = null;

refreshIndicator.textContent = REFRESH_MS;

async function fetchJSON(endpoint) {
  const res = await fetch(endpoint);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function ensureChart(ctx) {
  if (chart) {
    return chart;
  }
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Life",
          data: [],
          fill: false,
          borderColor: "#22c55e",
          tension: 0.2,
        },
        {
          label: "Resources",
          data: [],
          fill: false,
          borderColor: "#14b8a6",
          tension: 0.2,
        },
        {
          label: "Danger",
          data: [],
          fill: false,
          borderColor: "#ef4444",
          tension: 0.2,
        },
        {
          label: "Unknown",
          data: [],
          fill: false,
          borderColor: "#6366f1",
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        x: {
          title: {
            display: true,
            text: "Tick",
          },
        },
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: "Value",
          },
        },
      },
    },
  });
  return chart;
}

function updateLatestCard(data) {
  if (!data) return;
  latestTick.textContent = data.tick ?? "-";
  latestLife.textContent = data.life ?? "-";
  latestResources.textContent = data.resources ?? "-";
  latestDanger.textContent = data.danger ?? "-";
  latestUnknown.textContent = data.unknown ?? "-";
  latestReward.textContent = data.reward?.toFixed?.(3) ?? "-";
  latestFear.textContent = data.fear_note || "-";
  latestCuriosity.textContent = data.curiosity_note || "-";
}

function formatPlan(plan) {
  if (!plan) return "-";
  const lines = [];
  lines.push(`Intent: ${plan.intent}`);
  if (plan.sub_goals && plan.sub_goals.length) {
    lines.push("Sub Goals:");
    plan.sub_goals.forEach((g) => lines.push(`  - ${g}`));
  }
  if (plan.actions && plan.actions.length) {
    lines.push("Actions:");
    plan.actions.forEach((a, idx) => {
      lines.push(
        `  ${idx + 1}. ${a.action_id} conf=${a.confidence?.toFixed?.(2) ?? "-"} risk=${a.risk_estimate?.toFixed?.(
          2
        ) ?? "-"}`
      );
    });
  }
  if (plan.notes) {
    lines.push(`Notes: ${plan.notes}`);
  }
  return lines.join("\n");
}

function updateChart(metrics) {
  const ctx = document.getElementById("metrics-chart").getContext("2d");
  const chartInstance = ensureChart(ctx);
  const labels = metrics.map((m) => m.tick);
  chartInstance.data.labels = labels;
  chartInstance.data.datasets[0].data = metrics.map((m) => m.life ?? null);
  chartInstance.data.datasets[1].data = metrics.map((m) => m.resources ?? null);
  chartInstance.data.datasets[2].data = metrics.map((m) => m.danger ?? null);
  chartInstance.data.datasets[3].data = metrics.map((m) => m.unknown ?? null);
  chartInstance.update();
}

function updateRawSnapshot(snapshot) {
  if (!snapshot) {
    latestRaw.textContent = "データがありません";
    return;
  }
  latestPlan.textContent = formatPlan(snapshot.action_plan);
  latestRaw.textContent = JSON.stringify(snapshot, null, 2);
}

function renderEvents(events) {
  eventsList.innerHTML = "";
  if (!events || !events.length) {
    const empty = document.createElement("li");
    empty.textContent = "イベントがありません";
    eventsList.appendChild(empty);
    return;
  }
  events
    .slice()
    .reverse()
    .forEach((event) => {
      const li = document.createElement("li");
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.innerHTML = `<span>${new Date(event.timestamp).toLocaleTimeString()}</span><span>${event.channel}</span>`;

      const message = document.createElement("div");
      message.className = "message";
      message.textContent = event.payload?.message ?? "(no message)";

      const detail = document.createElement("div");
      detail.className = "detail";
      const tick = event.payload?.tick ?? "-";
      const life = event.payload?.life ?? "-";
      const danger = event.payload?.danger ?? "-";
      detail.textContent = `tick=${tick}, life=${life}, danger=${danger}`;

      li.appendChild(meta);
      li.appendChild(message);
      li.appendChild(detail);
      eventsList.appendChild(li);
    });
}

function renderPlaybookUpdates(updates) {
  playbookUpdates.innerHTML = "";
  if (!updates || !updates.length) {
    const empty = document.createElement("li");
    empty.textContent = "プレイブックの更新はありません";
    playbookUpdates.appendChild(empty);
    return;
  }
  updates
    .slice()
    .reverse()
    .forEach((update) => {
      const li = document.createElement("li");
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.innerHTML = `<span>${update.target}</span><span>${update.status ?? update.change_type}</span>`;
      const content = document.createElement("div");
      content.className = "content";
      const preview = update.content ? String(update.content).slice(0, 160) : "";
      const body = update.reason ? `${update.change_type}: ${update.reason}` : update.change_type;
      content.textContent = preview ? `${body}\n${preview}` : body;
      li.appendChild(meta);
      li.appendChild(content);
      playbookUpdates.appendChild(li);
    });
}

function renderPlaybookStats(stats) {
  if (!stats || typeof stats !== "object") {
    playbookStatsFiles.textContent = "-";
    playbookStatsSections.textContent = "-";
    playbookStatsChars.textContent = "-";
    return;
  }
  playbookStatsFiles.textContent = stats.files ?? "-";
  playbookStatsSections.textContent = stats.sections ?? "-";
  playbookStatsChars.textContent = stats.characters ?? "-";
}

async function refresh() {
  try {
    const [metricsRes, latestRes, eventsRes] = await Promise.all([
      fetchJSON("/metrics"),
      fetchJSON("/latest"),
      fetchJSON("/events"),
    ]);
    const metrics = metricsRes.items ?? [];
    const latest = latestRes.item ?? null;
    const events = eventsRes.items ?? [];
    if (metrics.length) {
      updateLatestCard(metrics[metrics.length - 1]);
      updateChart(metrics);
    }
    updateRawSnapshot(latest);
    renderEvents(events);
    renderPlaybookUpdates(latest?.playbook_updates ?? []);
    renderPlaybookStats(latest?.playbook_stats ?? null);
  } catch (err) {
    console.error("更新に失敗しました", err);
  }
}

function start() {
  refresh();
  timer = setInterval(refresh, REFRESH_MS);
}

refreshBtn.addEventListener("click", refresh);

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearInterval(timer);
  } else {
    start();
  }
});

start();
