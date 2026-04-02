let chartInstance = null;

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
  }
}

function formatPrice(value) {
  return Number(value).toFixed(3) + " CNY/L";
}

function formatPercent(value) {
  return Number(value).toFixed(2) + "%";
}

function paintDecision(decision) {
  const tag = document.getElementById("decisionTag");
  if (!tag) {
    return;
  }

  tag.classList.remove("fill", "hold", "walk");
  if (decision === "FILL") {
    tag.classList.add("fill");
  } else if (decision === "HOLD") {
    tag.classList.add("hold");
  } else {
    tag.classList.add("walk");
  }
}

function renderTail(items) {
  const list = document.getElementById("tailList");
  if (!list) {
    return;
  }

  list.innerHTML = "";
  const tail = items.slice(-7).reverse();
  for (const entry of tail) {
    const li = document.createElement("li");
    const left = document.createElement("span");
    const right = document.createElement("strong");
    left.textContent = entry.date;
    right.textContent = formatPrice(entry.price);
    li.appendChild(left);
    li.appendChild(right);
    list.appendChild(li);
  }
}

function renderChart(points) {
  const canvas = document.getElementById("priceChart");
  if (!canvas || !window.Chart) {
    return;
  }

  const labels = points.map((item) => item.date);
  const values = points.map((item) => item.price);

  if (chartInstance) {
    chartInstance.destroy();
  }

  chartInstance = new window.Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Benchmark 92#",
          data: values,
          borderColor: "#0f8a6b",
          backgroundColor: "rgba(15,138,107,0.12)",
          borderWidth: 2,
          fill: true,
          tension: 0.3,
          pointRadius: 0,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: "index",
        intersect: false,
      },
      plugins: {
        legend: {
          display: false,
        },
      },
      scales: {
        x: {
          ticks: {
            maxTicksLimit: 6,
          },
          grid: {
            color: "rgba(0,0,0,0.08)",
          },
        },
        y: {
          grid: {
            color: "rgba(0,0,0,0.08)",
          },
        },
      },
    },
  });
}

function renderEmpty() {
  setText("updatedAt", "No data yet. Run updater script first.");
  setText("decisionTag", "--");
  setText("decisionText", "No decision available.");
  setText("bargainIndex", "--");
  setText("todayPrice", "--");
  setText("pricePercentile", "--");
  setText("sampleSize", "0");
}

function render(latest, history) {
  const metric = latest.metric;
  const prices = Array.isArray(history.prices) ? history.prices : [];

  if (!metric || prices.length === 0) {
    renderEmpty();
    return;
  }

  setText("updatedAt", "Updated: " + latest.updated_at);
  setText("decisionTag", metric.decision);
  setText("decisionText", metric.decision_text);
  setText("bargainIndex", formatPercent(metric.bargain_index));
  setText("todayPrice", formatPrice(metric.today_price));
  setText("pricePercentile", formatPercent(metric.price_percentile));
  setText("sampleSize", String(metric.sample_size));
  paintDecision(metric.decision);

  renderChart(prices);
  renderTail(prices);
}

async function bootstrap() {
  try {
    const [latestRes, historyRes] = await Promise.all([
      fetch("./data/latest.json", { cache: "no-store" }),
      fetch("./data/history.json", { cache: "no-store" }),
    ]);

    if (!latestRes.ok || !historyRes.ok) {
      throw new Error("Failed to fetch data files.");
    }

    const latest = await latestRes.json();
    const history = await historyRes.json();
    render(latest, history);
  } catch (error) {
    console.error(error);
    renderEmpty();
    setText("decisionText", "Data load failed. Check docs/data JSON files.");
  }
}

bootstrap();
