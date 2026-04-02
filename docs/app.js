let chartInstance = null;

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
  }
}

function formatPrice(value) {
  return Number(value).toFixed(3) + " 元/升";
}

function formatPercent(value) {
  return Number(value).toFixed(2) + "%";
}

function formatPercentMaybe(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return "--";
  }
  return formatPercent(numeric);
}

function clampPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return null;
  }
  return Math.min(100, Math.max(0, numeric));
}

function setPercentileBar(maskId, value) {
  const mask = document.getElementById(maskId);
  if (!mask) {
    return;
  }

  const pct = clampPercent(value);
  if (pct === null) {
    mask.style.width = "100%";
    return;
  }

  const remainder = 100 - pct;
  mask.style.width = `${remainder.toFixed(2)}%`;
}

function setHistoryHint(text) {
  setText("historyHint", text);
}

function setChartHint(text) {
  setText("chartHint", text);
}

function parseDateOnly(isoDate) {
  return new Date(isoDate + "T00:00:00");
}

function computePercentile(values, target) {
  if (!Array.isArray(values) || values.length === 0) {
    return null;
  }
  const numericTarget = Number(target);
  if (!Number.isFinite(numericTarget)) {
    return null;
  }
  const lowerOrEqual = values.filter((v) => Number(v) <= numericTarget).length;
  return (lowerOrEqual / values.length) * 100;
}

function valuesInRange(prices, startDate, endDate) {
  return prices
    .filter((item) => {
      const d = parseDateOnly(item.date);
      return d >= startDate && d <= endDate;
    })
    .map((item) => Number(item.price))
    .filter((v) => Number.isFinite(v));
}

function normalizeDecision(decision) {
  if (decision === "FILL" || decision === "HOLD" || decision === "WALK") {
    return decision;
  }
  return "HOLD";
}

function decisionLabel(decision) {
  if (decision === "FILL") {
    return "建议加油";
  }
  if (decision === "WALK") {
    return "建议观望";
  }
  return "按需加油";
}

function decisionText(metric, decision) {
  const zhText = metric && typeof metric.decision_text_zh === "string" ? metric.decision_text_zh : "";
  if (zhText) {
    return zhText;
  }

  const rawText = metric && typeof metric.decision_text === "string" ? metric.decision_text : "";
  if (/[\u4e00-\u9fff]/.test(rawText)) {
    return rawText;
  }

  if (decision === "FILL") {
    return "当前价格处于近一年相对低位，建议加油。";
  }
  if (decision === "WALK") {
    return "当前价格处于近一年相对高位，建议观望。";
  }
  return "当前价格处于中位区间，可按需补能。";
}

function resolveBargainIndex(metric) {
  const direct = Number(metric && metric.bargain_index);
  if (Number.isFinite(direct)) {
    return Math.min(100, Math.max(0, direct));
  }

  const percentile = Number(metric && metric.price_percentile);
  if (Number.isFinite(percentile)) {
    return Math.min(100, Math.max(0, 100 - percentile));
  }

  return null;
}

function resolvePeriodPercentiles(metric, prices) {
  const periods = (metric && metric.period_percentiles) || {};
  const reference =
    Array.isArray(prices) && prices.length > 0
      ? parseDateOnly(prices[prices.length - 1].date)
      : new Date();
  const todayPrice = Number(metric && metric.today_price);

  const start30 = new Date(reference);
  start30.setDate(start30.getDate() - 29);

  const start120 = new Date(reference);
  start120.setDate(start120.getDate() - 119);

  const monthStart = new Date(reference.getFullYear(), reference.getMonth(), 1);
  const quarterStartMonth = Math.floor(reference.getMonth() / 3) * 3;
  const quarterStart = new Date(reference.getFullYear(), quarterStartMonth, 1);

  const fallback30 = computePercentile(valuesInRange(prices, start30, reference), todayPrice);
  const fallbackMonth = computePercentile(valuesInRange(prices, monthStart, reference), todayPrice);
  const fallbackQuarter = computePercentile(valuesInRange(prices, quarterStart, reference), todayPrice);
  const fallback120 = computePercentile(valuesInRange(prices, start120, reference), todayPrice);

  const pick = (primary, fallback) => {
    const p = Number(primary);
    if (Number.isFinite(p)) {
      return p;
    }
    return fallback;
  };

  return {
    past30: pick(periods.past_30_days && periods.past_30_days.value, fallback30),
    thisMonth: pick(periods.this_month && periods.this_month.value, fallbackMonth),
    thisQuarter: pick(periods.this_quarter && periods.this_quarter.value, fallbackQuarter),
    past120: pick(periods.past_120_days && periods.past_120_days.value, fallback120),
  };
}

function paintDecision(decision) {
  const tag = document.getElementById("decisionTag");
  if (!tag) {
    return;
  }

  const normalized = normalizeDecision(decision);
  tag.classList.remove("fill", "hold", "walk");
  if (normalized === "FILL") {
    tag.classList.add("fill");
  } else if (normalized === "HOLD") {
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
          label: "基准 92#",
          data: values,
          borderColor: "#0f8a6b",
          backgroundColor: "rgba(15,138,107,0.12)",
          borderWidth: 2,
          fill: values.length > 1,
          tension: values.length > 2 ? 0.3 : 0,
          pointRadius: values.length === 1 ? 5 : 0,
          pointHoverRadius: values.length === 1 ? 6 : 3,
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
  setText("updatedAt", "暂无数据，请先执行更新脚本。");
  setHistoryHint("历史窗口当前为空。请稍后重试。");
  setText("decisionTag", "--");
  setText("decisionText", "暂无决策建议。");
  setText("bargainIndex", "--");
  setText("todayPrice", "--");
  setText("pricePercentile", "--");
  setText("sampleSize", "0");
  setText("pricePercentile30d", "--");
  setText("pricePercentileMonth", "--");
  setText("pricePercentileQuarter", "--");
  setText("pricePercentile120d", "--");
  setPercentileBar("barPricePercentile", null);
  setPercentileBar("barPricePercentile30d", null);
  setPercentileBar("barPricePercentileMonth", null);
  setPercentileBar("barPricePercentileQuarter", null);
  setPercentileBar("barPricePercentile120d", null);
  setChartHint("暂无图表数据。");
}

function render(latest, history) {
  const metric = latest.metric;
  const prices = Array.isArray(history.prices) ? history.prices : [];

  if (!metric || prices.length === 0) {
    renderEmpty();
    return;
  }

  const decision = normalizeDecision(metric.decision);
  const bargainIndex = resolveBargainIndex(metric);
  const periodPercentiles = resolvePeriodPercentiles(metric, prices);

  setText("updatedAt", "更新时间：" + latest.updated_at);
  setText("decisionTag", decisionLabel(decision));
  setText("decisionText", decisionText(metric, decision));
  setText("bargainIndex", bargainIndex === null ? "--" : formatPercent(bargainIndex));
  setText("todayPrice", formatPrice(metric.today_price));
  setText("pricePercentile", formatPercent(metric.price_percentile));
  setText("sampleSize", String(metric.sample_size || prices.length));
  setText("pricePercentile30d", formatPercentMaybe(periodPercentiles.past30));
  setText("pricePercentileMonth", formatPercentMaybe(periodPercentiles.thisMonth));
  setText("pricePercentileQuarter", formatPercentMaybe(periodPercentiles.thisQuarter));
  setText("pricePercentile120d", formatPercentMaybe(periodPercentiles.past120));
  setPercentileBar("barPricePercentile", metric.price_percentile);
  setPercentileBar("barPricePercentile30d", periodPercentiles.past30);
  setPercentileBar("barPricePercentileMonth", periodPercentiles.thisMonth);
  setPercentileBar("barPricePercentileQuarter", periodPercentiles.thisQuarter);
  setPercentileBar("barPricePercentile120d", periodPercentiles.past120);
  paintDecision(decision);

  const sampleSize = Number(metric.sample_size || prices.length || 0);
  if (sampleSize < 30) {
    setHistoryHint("历史样本较少，系统正在自动回填近一年基准曲线。");
  } else {
    setHistoryHint("已加载过去一年样本。指数会按天自动刷新。");
  }
  if (sampleSize === 1) {
    setChartHint("当前仅 1 个样本点，图中显示为单点。请等待自动积累或执行回填更新。");
  } else if (sampleSize < 30) {
    setChartHint("样本较少，曲线波动仅供参考。");
  } else {
    setChartHint("基于 365 天窗口的代表性基准油价走势。");
  }

  renderChart(prices);
  renderTail(prices);
}

async function bootstrap() {
  try {
    const cacheBust = Date.now();
    const [latestRes, historyRes] = await Promise.all([
      fetch(`./data/latest.json?v=${cacheBust}`, { cache: "no-store" }),
      fetch(`./data/history.json?v=${cacheBust}`, { cache: "no-store" }),
    ]);

    if (!latestRes.ok || !historyRes.ok) {
      throw new Error("数据文件加载失败。");
    }

    const latest = await latestRes.json();
    const history = await historyRes.json();
    render(latest, history);
  } catch (error) {
    console.error(error);
    renderEmpty();
    setText("decisionText", "数据加载失败，请检查 docs/data 下的 JSON 文件。");
  }
}

bootstrap();
