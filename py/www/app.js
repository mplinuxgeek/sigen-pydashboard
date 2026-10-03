var TAB_NAMES = ["metrics", "monthly", "import", "info", "settings", "firmware", "panel"];
var metricsTimer = null,
  logTimer = null,
  blTimer = null,
  logSince = 0,
  logAutoScroll = true,
  logPaused = false;
function showTab(name, skipHash) {
  if (TAB_NAMES.indexOf(name) < 0) name = "metrics";
  TAB_NAMES.forEach(function (n) {
    document.getElementById("tab" + n[0].toUpperCase() + n.slice(1)).className = "tab" + (n === name ? " active" : "");
    document.getElementById("tabBtn" + n[0].toUpperCase() + n.slice(1)).className = "tabbtn" + (n === name ? " active" : "");
  });
  if (name === "metrics") {
    initChartsOnce();
    renderMetrics();
    if (!metricsTimer) metricsTimer = setInterval(renderMetrics, 5000);
  } else if (metricsTimer) {
    clearInterval(metricsTimer);
    metricsTimer = null;
  }
  if (name === "monthly") {
    renderMonthlyHistory();
  }
  if (name === "info") {
    fetchLogs();
    if (!logTimer) logTimer = setInterval(fetchLogs, 2500);
  } else if (logTimer) {
    clearInterval(logTimer);
    logTimer = null;
  }
  if (name === "settings") {
    pollBacklightStatus();
    if (!blTimer) blTimer = setInterval(pollBacklightStatus, 10000);
  } else if (blTimer) {
    clearInterval(blTimer);
    blTimer = null;
  }
  if (!skipHash) history.replaceState(null, "", "#" + name);
}
document.getElementById("tabBtnMetrics").onclick = function () {
  showTab("metrics");
};
document.getElementById("tabBtnMonthly").onclick = function () {
  showTab("monthly");
};
document.getElementById("tabBtnImport").onclick = function () {
  showTab("import");
};
document.getElementById("tabBtnInfo").onclick = function () {
  showTab("info");
};
document.getElementById("tabBtnSettings").onclick = function () {
  showTab("settings");
};
document.getElementById("tabBtnFirmware").onclick = function () {
  showTab("firmware");
};
window.addEventListener("hashchange", function () {
  showTab(location.hash.slice(1), true);
});
(function () {
  var TOKEN_IDS = ["histToken", "setToken", "fwToken", "sigenToken"];
  var globalEl = document.getElementById("globalAuthToken");
  var saved = localStorage.getItem("adminToken") || "";
  if (globalEl) {
    globalEl.value = saved;
    globalEl.addEventListener("input", function () {
      var val = globalEl.value;
      localStorage.setItem("adminToken", val);
      TOKEN_IDS.forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.value = val;
      });
    });
  }
  TOKEN_IDS.forEach(function (id) {
    var el = document.getElementById(id);
    if (el) el.value = saved;
  });
})();
document.getElementById("uploadBtn").onclick = function () {
  var fileInput = document.getElementById("csvFile");
  var status = document.getElementById("histStatus");
  if (!fileInput.files.length) {
    status.style.color = "#f87171";
    status.textContent = "Please select a CSV file first.";
    return;
  }
  var token = document.getElementById("histToken").value;
  if (!token) {
    needToken(status);
    return;
  }
  if (!confirm("This replaces ALL stored history on the device. Continue?")) {
    return;
  }
  var file = fileInput.files[0];
  status.style.color = "#38bdf8";
  status.textContent = "Uploading and parsing CSV...";
  var reader = new FileReader();
  reader.onload = function (e) {
    fetch("/api/history/import", {
      method: "POST",
      headers: { "Content-Type": "text/csv", "X-OTA-Token": token },
      body: e.target.result,
    })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        if (d.status === "ok") {
          status.style.color = "#4ade80";
          status.textContent = "Success! Imported " + d.imported + " records into device history.";
        } else {
          status.style.color = "#f87171";
          status.textContent = "Error: " + (d.error || "Import failed");
        }
      })
      .catch(function (err) {
        status.style.color = "#f87171";
        status.textContent = "Upload failed: " + err.message;
      });
  };
  reader.readAsText(file);
};
function row(label, value, warn) {
  return (
    '<div class="row' +
    (warn ? " warn" : "") +
    '"><span class="label">' +
    label +
    '</span><span class="value">' +
    value +
    "</span></div>"
  );
}
function card(title, rows, badge, icon) {
  var b = badge ? '<span class="badge ' + badge.cls + '">' + badge.text + "</span>" : "";
  var i = icon ? '<span class="card-icon">' + icon + "</span>" : "";
  return '<div class="card"><div class="card-header"><h2>' + i + title + "</h2>" + b + "</div>" + rows.join("") + "</div>";
}
function metricsCard(title, rows, pct, color, badge, icon) {
  var b = badge ? '<span class="badge ' + badge.cls + '">' + badge.text + "</span>" : "";
  var i = icon ? '<span class="card-icon">' + icon + "</span>" : "";
  var bar =
    pct == null
      ? ""
      : '<div class="bar-track"><div class="bar-fill" style="width:' +
        Math.max(0, Math.min(100, pct)) +
        "%;background:" +
        color +
        '"></div></div>';
  return '<div class="card"><div class="card-header"><h2>' + i + title + "</h2>" + b + "</div>" + bar + rows.join("") + "</div>";
}
function renderMetrics() {
  Promise.all([
    fetch("/api/metrics").then(function (r) {
      return r.json();
    }),
    fetch("/api/monthly")
      .then(function (r) {
        return r.json();
      })
      .catch(function () {
        return null;
      }),
  ])
    .then(function (results) {
      var m = results[0],
        mo = results[1];
      var cb = mo && mo.current_billing;
      var status = document.getElementById("metricsStatus");
      if (m.alive) {
        status.style.color = "#94a3b8";
        status.textContent = "";
      } else {
        status.style.color = "#fbbf24";
        status.textContent = "Modbus link not responding -- values may be stale.";
      }
      var invKw = m.sizing.inverter_kw || 1,
        solKw = m.sizing.solar_kw || 1;
      var cards = [];
      var battState = m.battery.power_kw > 0.05 ? "Charging" : m.battery.power_kw < -0.05 ? "Discharging" : "Standby";
      var battBadgeClr = battState === "Charging" ? "badge-success" : battState === "Discharging" ? "badge-info" : "badge-warning";
      var battEta = "--";
      if (m.battery.soc_valid && m.battery.capacity_valid && Math.abs(m.battery.power_kw) > 0.05) {
        var battHours =
          m.battery.power_kw > 0
            ? (m.battery.capacity_kwh * (100 - m.battery.soc_pct)) / 100 / m.battery.power_kw
            : (m.battery.capacity_kwh * m.battery.soc_pct) / 100 / -m.battery.power_kw;
        if (battHours <= 99) {
          var battH = Math.floor(battHours),
            battM = Math.floor((battHours - battH) * 60);
          battEta = battH + "h " + (battM < 10 ? "0" : "") + battM + "m to " + (m.battery.power_kw > 0 ? "full" : "empty");
        }
      }
      cards.push(
        metricsCard(
          "Battery",
          [
            row("SOC", m.battery.soc_pct.toFixed(1) + "%", !m.battery.soc_valid),
            row("Power", (m.battery.power_kw >= 0 ? "+" : "") + m.battery.power_kw.toFixed(2) + " kW", !m.battery.power_valid),
            row("ETA", battEta),
            row("Capacity", m.battery.capacity_kwh.toFixed(1) + " kWh", !m.battery.capacity_valid),
            row("Temp", m.battery.temp_c.toFixed(1) + " \u00b0C", !m.battery.temp_valid),
          ],
          m.battery.soc_pct,
          "#10b981",
          { text: battState, cls: battBadgeClr },
          "&#128267;",
        ),
      );
      var pvPct = Math.max(0, Math.min(100, (m.pv.power_kw / solKw) * 100));
      var loadPct = m.load.power_kw <= 0.05 ? null : (m.pv.power_kw / m.load.power_kw) * 100;
      var coveringTxt = loadPct == null ? "--% of load" : loadPct.toFixed(0) + "% of load" + (loadPct > 100 ? " (excess)" : "");
      cards.push(
        metricsCard(
          "Solar",
          [
            row("Power", m.pv.power_kw.toFixed(2) + " kW", !m.pv.power_valid),
            row("Covering", coveringTxt),
            row("Today", m.pv.daily_kwh.toFixed(1) + " kWh", !m.pv.daily_valid),
            row("Month to date", cb ? cb.solar_kwh.toFixed(1) + " kWh" : "--", !cb),
          ],
          pvPct,
          "#f59e0b",
          { text: m.pv.power_kw > 0.05 ? "Generating" : "Idle", cls: m.pv.power_kw > 0.05 ? "badge-warning" : "badge-info" },
          "&#9728;&#65039;",
        ),
      );
      cards.push(
        metricsCard(
          "Load",
          [
            row("Power", m.load.power_kw.toFixed(2) + " kW", !m.load.power_valid),
            row("Today", m.load.daily_kwh.toFixed(1) + " kWh", !m.load.daily_valid),
            row("Month to date", cb ? cb.load_kwh.toFixed(1) + " kWh" : "--", !cb),
          ],
          (m.load.power_kw / invKw) * 100,
          "#3b82f6",
          null,
          "&#9889;",
        ),
      );
      var gridDir = m.grid.power_kw > 0.05 ? "Importing" : m.grid.power_kw < -0.05 ? "Exporting" : "Idle";
      var gridBadgeClr = gridDir === "Importing" ? "badge-warning" : gridDir === "Exporting" ? "badge-success" : "badge-info";
      cards.push(
        metricsCard(
          "Grid",
          [
            row("Power", (m.grid.power_kw >= 0 ? "+" : "") + m.grid.power_kw.toFixed(2) + " kW", !m.grid.power_valid),
            row("Status", m.grid.status.replace(/_/g, " "), !m.grid.status_valid || m.grid.status !== "on_grid"),
            row("Import today", m.grid.daily_import_kwh.toFixed(1) + " kWh", !m.grid.daily_import_valid),
            row("Export today", m.grid.daily_export_kwh.toFixed(1) + " kWh", !m.grid.daily_export_valid),
            row("Import MTD", cb ? cb.grid_import_kwh.toFixed(1) + " kWh" : "--", !cb),
            row("Export MTD", cb ? cb.grid_export_kwh.toFixed(1) + " kWh" : "--", !cb),
          ],
          (Math.abs(m.grid.power_kw) / invKw) * 100,
          "#ef4444",
          { text: gridDir, cls: gridBadgeClr },
          '<svg style="width:18px;height:18px;fill:currentColor;vertical-align:-2px" viewBox="0 0 24 24"><path d="M12 2L8 8H11V13H8L6 16H9.5L5 22H7.5L9.5 19H14.5L16.5 22H19L14.5 16H18L16 13H13V8H16L12 2ZM11.5 9.5H12.5V11.5H11.5V9.5ZM10.5 14.5H13.5L14.5 16H9.5L10.5 14.5Z"/></svg>',
        ),
      );
      document.getElementById("metricsGrid").innerHTML = cards.join("");
    })
    .catch(function (err) {
      var status = document.getElementById("metricsStatus");
      status.style.color = "#f87171";
      status.textContent = "Failed to load metrics: " + err.message;
    });
}
function renderMonthlyHistory() {
  var status = document.getElementById("monthlyStatus");
  status.textContent = "Loading monthly history...";
  fetch("/api/monthly")
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (res) {
      status.textContent = "";
      var rows = [];
      var mNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
      if (res.current) {
        var c = res.current;
        var name = (mNames[c.month - 1] || c.month) + " " + c.year + " (Current)";
        rows.push(
          '<tr style="font-weight:600;background:rgba(56,189,248,0.08)"><td>' +
            name +
            "</td><td>" +
            c.solar_kwh.toFixed(1) +
            "</td><td>" +
            c.grid_import_kwh.toFixed(1) +
            "</td><td>" +
            c.grid_export_kwh.toFixed(1) +
            "</td><td>" +
            c.load_kwh.toFixed(1) +
            "</td></tr>",
        );
      }
      if (res.history && res.history.length) {
        res.history
          .slice()
          .reverse()
          .forEach(function (h) {
            var name = (mNames[h.month - 1] || h.month) + " " + h.year;
            rows.push(
              "<tr><td>" +
                name +
                "</td><td>" +
                h.solar_kwh.toFixed(1) +
                "</td><td>" +
                h.grid_import_kwh.toFixed(1) +
                "</td><td>" +
                h.grid_export_kwh.toFixed(1) +
                "</td><td>" +
                h.load_kwh.toFixed(1) +
                "</td></tr>",
            );
          });
      }
      if (!rows.length) {
        document.getElementById("monthlyBody").innerHTML =
          '<tr><td colspan="5" style="text-align:center;color:#64748b;padding:16px">No monthly history recorded yet.</td></tr>';
      } else {
        document.getElementById("monthlyBody").innerHTML = rows.join("");
      }
      var chartLabels = [],
        chartSolar = [],
        chartImport = [],
        chartExport = [],
        chartLoad = [];
      if (res.history && res.history.length) {
        res.history.forEach(function (h) {
          chartLabels.push((mNames[h.month - 1] || h.month) + " '" + String(h.year).slice(-2));
          chartSolar.push(h.solar_kwh);
          chartImport.push(h.grid_import_kwh);
          chartExport.push(h.grid_export_kwh);
          chartLoad.push(h.load_kwh);
        });
      }
      if (res.current) {
        var c = res.current;
        chartLabels.push((mNames[c.month - 1] || c.month) + " '" + String(c.year).slice(-2) + "*");
        chartSolar.push(c.solar_kwh);
        chartImport.push(c.grid_import_kwh);
        chartExport.push(c.grid_export_kwh);
        chartLoad.push(c.load_kwh);
      }
      renderMonthlyChart(chartLabels, chartSolar, chartImport, chartExport, chartLoad);
    })
    .catch(function (err) {
      status.style.color = "#f87171";
      status.textContent = "Failed to load: " + err.message;
    });
}
function renderMonthlyChart(labels, solar, imp, exp, load) {
  if (!monthlyChart) {
    monthlyChart = new Chart(document.getElementById("monthlyChart"), {
      type: "bar",
      data: {
        labels: labels,
        datasets: [
          { label: "Load", data: load, backgroundColor: "rgba(77,182,173,.85)", barPercentage: 0.72 },
          { label: "Solar", data: solar, backgroundColor: "rgba(255,152,0,.85)", barPercentage: 0.72 },
          { label: "Grid Import", data: imp, backgroundColor: "rgba(220,70,70,.85)", barPercentage: 0.72 },
          { label: "Grid Export", data: exp, backgroundColor: "rgba(162,128,219,.85)", barPercentage: 0.72 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          title: { display: true, text: "Monthly Energy (kWh)", color: "#f8fafc" },
          legend: { labels: { color: "#cbd5e1" } },
        },
        scales: chartScales,
      },
    });
  } else {
    monthlyChart.data.labels = labels;
    monthlyChart.data.datasets[0].data = load;
    monthlyChart.data.datasets[1].data = solar;
    monthlyChart.data.datasets[2].data = imp;
    monthlyChart.data.datasets[3].data = exp;
    monthlyChart.update();
  }
}
function fmtDuration(totalSeconds) {
  if (totalSeconds < 0) return "never";
  var h = Math.floor(totalSeconds / 3600),
    m = Math.floor((totalSeconds % 3600) / 60),
    s = Math.floor(totalSeconds % 60);
  if (h > 0) return h + "h " + m + "m";
  if (m > 0) return m + "m " + s + "s";
  return s + "s";
}
function fmtBytes(b) {
  if (b < 1024) return b + " B";
  if (b < 1024 * 1024) return (b / 1024).toFixed(1) + " KB";
  return (b / 1024 / 1024).toFixed(2) + " MB";
}
var chartsStarted = false,
  chartIntervalS = 300,
  chartRecords = [],
  powerChart,
  socChart,
  monthlyChart = null;
var dayOffset = 0,
  MAX_DAY_OFFSET = 30;
var chartScales = {
  x: { grid: { color: "#334155" }, ticks: { color: "#94a3b8", maxTicksLimit: 12 } },
  y: { grid: { color: "#334155" }, ticks: { color: "#94a3b8" } },
};
function dayBounds(offsetDays) {
  var start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - offsetDays);
  var end = new Date(start.getTime() + 86400000);
  return [start.getTime(), end.getTime()];
}
function fmtKwh(v) {
  return v.toFixed(v < 10 ? 2 : 1);
}
var dayCache = {},
  dayReq = 0;
function loadDay(offsetDays) {
  var b = dayBounds(offsetDays),
    hit = dayCache[b[0]];
  // finished days never change; today is refetched when older than a minute
  if (hit && (offsetDays > 0 || Date.now() - hit.at < 60000)) return Promise.resolve(hit.records);
  return fetch("/api/history?from=" + Math.floor(b[0] / 1000) + "&to=" + Math.floor(b[1] / 1000))
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (payload) {
      chartIntervalS = payload.interval_s || 300;
      var records = payload.records || [];
      dayCache[b[0]] = { at: Date.now(), records: records };
      return records;
    });
}
function renderDay(offsetDays) {
  offsetDays = Math.max(0, Math.min(MAX_DAY_OFFSET, offsetDays));
  dayOffset = offsetDays;
  var req = ++dayReq,
    status = document.getElementById("chartStatus");
  status.textContent = "Loading...";
  loadDay(offsetDays)
    .then(function (records) {
      if (req === dayReq) drawDay(offsetDays, records);
    })
    .catch(function (err) {
      if (req === dayReq) status.textContent = "Failed to load history: " + err.message;
    });
}
function drawDay(offsetDays, records) {
  var bounds = dayBounds(offsetDays),
    start = bounds[0];
  var dayName =
    offsetDays === 0
      ? "Today"
      : offsetDays === 1
        ? "Yesterday"
        : new Date(start).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  document.getElementById("dayLabel").textContent = dayName;
  document.getElementById("btnOlderDay").disabled = offsetDays >= MAX_DAY_OFFSET;
  document.getElementById("btnNewerDay").disabled = offsetDays <= 0;
  var status = document.getElementById("chartStatus");
  if (!records.length) {
    status.textContent = dayName + ": no history recorded yet for this day.";
  } else {
    status.textContent = "";
  }
  var labels = records.map(function (d) {
    return new Date(d.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  });
  var pv = records.map(function (d) {
    return d.pv_kw;
  });
  var load = records.map(function (d) {
    return d.load_kw;
  });
  var batt = records.map(function (d) {
    return d.battery_kw;
  });
  var grid = records.map(function (d) {
    return d.grid_kw;
  });
  var soc = records.map(function (d) {
    return d.soc_pct;
  });
  var dtH = chartIntervalS / 3600,
    solarKwh = 0,
    importKwh = 0,
    exportKwh = 0,
    battKwh = 0;
  records.forEach(function (d) {
    solarKwh += d.pv_kw * dtH;
    if (d.grid_kw > 0) importKwh += d.grid_kw * dtH;
    else exportKwh += -d.grid_kw * dtH;
    if (d.battery_kw < 0) battKwh += -d.battery_kw * dtH;
  });
  document.getElementById("statSolar").textContent = fmtKwh(solarKwh);
  document.getElementById("statImport").textContent = fmtKwh(importKwh);
  document.getElementById("statExport").textContent = fmtKwh(exportKwh);
  document.getElementById("statBattery").textContent = fmtKwh(battKwh);
  powerChart.data.labels = labels;
  powerChart.data.datasets[0].data = pv;
  powerChart.data.datasets[1].data = load;
  powerChart.data.datasets[2].data = batt;
  powerChart.data.datasets[3].data = grid;
  powerChart.update();
  socChart.data.labels = labels;
  socChart.data.datasets[0].data = soc;
  socChart.update();
}
function initChartsOnce() {
  if (chartsStarted) return;
  chartsStarted = true;
  powerChart = new Chart(document.getElementById("powerChart"), {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Solar PV (kW)",
          data: [],
          borderColor: "rgba(245,158,11,.85)",
          backgroundColor: "rgba(245,158,11,.15)",
          fill: true,
          tension: 0.3,
          pointRadius: 1.5,
        },
        { label: "House Load (kW)", data: [], borderColor: "rgba(59,130,246,.85)", tension: 0.3, pointRadius: 1.5 },
        { label: "Battery Power (kW)", data: [], borderColor: "rgba(16,185,129,.85)", tension: 0.3, pointRadius: 1.5 },
        { label: "Grid Power (kW)", data: [], borderColor: "rgba(239,68,68,.85)", tension: 0.3, pointRadius: 1.5 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { title: { display: true, text: "Power Flow (kW)", color: "#f8fafc" }, legend: { labels: { color: "#cbd5e1" } } },
      scales: chartScales,
    },
  });
  socChart = new Chart(document.getElementById("socChart"), {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Battery SOC (%)",
          data: [],
          borderColor: "rgba(139,92,246,.85)",
          backgroundColor: "rgba(139,92,246,.2)",
          fill: true,
          tension: 0.3,
          pointRadius: 1.5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        title: { display: true, text: "Battery State of Charge (%)", color: "#f8fafc" },
        legend: { labels: { color: "#cbd5e1" } },
      },
      scales: { x: chartScales.x, y: { min: 0, max: 100, grid: { color: "#334155" }, ticks: { color: "#94a3b8" } } },
    },
  });
  document.getElementById("btnOlderDay").onclick = function () {
    renderDay(dayOffset + 1);
  };
  document.getElementById("btnNewerDay").onclick = function () {
    renderDay(dayOffset - 1);
  };
  renderDay(0);
}
Promise.all([
  fetch("/api/system").then(function (r) {
    return r.json();
  }),
  fetch("/api/health")
    .then(function (r) {
      return r.json();
    })
    .catch(function () {
      return null;
    }),
])
  .then(function (results) {
    var sys = results[0],
      health = results[1];
    document.getElementById("status").textContent = "";
    var cards = [];
    cards.push(
      card("Firmware", [
        row("Version", sys.firmware.version),
        row("Project", sys.firmware.project),
        row("IDF", sys.firmware.idf),
        row("Built", sys.firmware.built),
        row("Running slot", sys.firmware.running_slot + " (" + sys.firmware.image_state + ")"),
        row("Inactive slot", sys.firmware.inactive_slot + " (" + sys.firmware.inactive_version + ")"),
      ]),
    );
    cards.push(
      card("Boot & Health", [
        row("Uptime", fmtDuration(sys.boot.uptime_s)),
        row("Reset reason", sys.boot.reset_reason),
        row("Last reboot trigger", sys.boot.last_reboot_trigger || "unknown (power-on, or a crash)"),
        health
          ? row("UI loop", health.ui ? Math.round(health.ui.fps * 10) / 10 + " fps, load " + health.ui.load + "%" : "--", health.ui && health.ui.errors > 0)
          : row("UI loop", "/api/health unreachable", true),
        health ? row("Log ring", fmtBytes(health.log_bytes)) : row("Log ring", "--"),
      ]),
    );
    cards.push(
      card("Network", [
        row("Connected", sys.network.connected ? "yes" : "no", !sys.network.connected),
        row("SSID", sys.network.ssid || "--"),
        row("IP", sys.network.ip || "--"),
        row("Signal", sys.network.rssi_dbm + " dBm"),
        row("MAC", sys.network.mac),
      ]),
    );
    cards.push(
      card("Inverter", [
        row("Host", sys.inverter.host + ":" + sys.inverter.port),
        row("Responding", sys.inverter.responding ? "yes" : "no", !sys.inverter.responding),
        row("Model", sys.inverter.model || "--"),
        row("Serial", sys.inverter.serial || "--"),
      ]),
    );
    cards.push(
      card("NTP", [
        row("Synced", (sys.ntp.synced ? "yes" : "no") + " (" + sys.ntp.status + ")", !sys.ntp.synced),
        row("Server", sys.ntp.server || "--"),
        row("Last sync", fmtDuration(sys.ntp.seconds_since_sync) + (sys.ntp.seconds_since_sync >= 0 ? " ago" : "")),
        row("Sync count", sys.ntp.sync_count),
        row("Timezone", sys.ntp.timezone),
      ]),
    );
    cards.push(
      card("Memory", [
        row("Internal free", fmtBytes(sys.memory.internal_free)),
        row("Internal largest block", fmtBytes(sys.memory.internal_largest_block), sys.memory.internal_largest_block < 4096),
        row("Internal min free", fmtBytes(sys.memory.internal_min_free), sys.memory.internal_min_free < 4096),
        row("PSRAM free", fmtBytes(sys.memory.psram_free)),
        row("Flash / PSRAM", sys.memory.flash_mb + " MB / " + sys.memory.psram_mb + " MB"),
      ]),
    );
    cards.push(
      card("Display", [
        row("Orientation", sys.display.orientation),
        row("Backlight", sys.display.backlight_percent + "%"),
        row("Chip", sys.hardware.chip),
      ]),
    );
    document.getElementById("cards").innerHTML = cards.join("");
  })
  .catch(function (err) {
    document.getElementById("status").textContent = "Failed to load: " + err.message;
  });
function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function formatLogLine(line) {
  var lvl = "D";
  if (line.includes(" E (") || line.includes(" [E] ")) lvl = "E";
  else if (line.includes(" W (") || line.includes(" [W] ")) lvl = "W";
  else if (line.includes(" I (") || line.includes(" [I] ")) lvl = "I";
  return '<div class="log-line log-' + lvl + '">' + escapeHtml(line) + "</div>";
}
function fetchLogs() {
  if (logPaused) return;
  var token = document.getElementById("globalAuthToken").value || localStorage.getItem("adminToken") || "";
  if (!token) {
    document.getElementById("logStatus").style.color = "#fbbf24";
    document.getElementById("logStatus").textContent = "Admin token required for logs";
    return;
  }
  fetch("/api/logs?since=" + logSince, { headers: { "X-OTA-Token": token } })
    .then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      var nextSeq = r.headers.get("X-Log-Next");
      var totalBytes = r.headers.get("X-Log-Total");
      if (nextSeq) logSince = parseInt(nextSeq, 10);
      document.getElementById("logMeta").textContent = "Log sequence: " + logSince + " | Total bytes: " + (totalBytes || "--");
      document.getElementById("logStatus").style.color = "#34d399";
      document.getElementById("logStatus").textContent = "Live (polling 2.5s)";
      return r.text();
    })
    .then(function (text) {
      if (!text) return;
      var consoleEl = document.getElementById("logConsole");
      var lines = text.split("\n");
      var html = lines
        .filter(function (l) {
          return l.trim().length > 0;
        })
        .map(formatLogLine)
        .join("");
      consoleEl.insertAdjacentHTML("beforeend", html);
      if (logAutoScroll) {
        consoleEl.scrollTop = consoleEl.scrollHeight;
      }
    })
    .catch(function (err) {
      document.getElementById("logStatus").style.color = "#f87171";
      document.getElementById("logStatus").textContent = "Error: " + err.message;
    });
}
document.getElementById("logAutoScrollBtn").onclick = function () {
  logAutoScroll = !logAutoScroll;
  this.className = "log-btn" + (logAutoScroll ? " active" : "");
  if (logAutoScroll) {
    var el = document.getElementById("logConsole");
    el.scrollTop = el.scrollHeight;
  }
};
document.getElementById("logPauseBtn").onclick = function () {
  logPaused = !logPaused;
  this.className = "log-btn" + (logPaused ? " active" : "");
  this.textContent = logPaused ? "Resume" : "Pause";
  document.getElementById("logStatus").textContent = logPaused ? "Paused" : "Live (polling 2.5s)";
};
document.getElementById("logClearBtn").onclick = function () {
  document.getElementById("logConsole").innerHTML = "";
};
var tzData = null;
function fillZoneSelect(wantZone) {
  var code = document.getElementById("setCountry").value;
  var zsel = document.getElementById("setZone");
  var zones = (tzData[code] && tzData[code].zones) || [];
  zsel.innerHTML = zones
    .map(function (z) {
      return '<option value="' + z.z + '">' + z.l + "</option>";
    })
    .join("");
  if (
    wantZone &&
    zones.some(function (z) {
      return z.z === wantZone;
    })
  ) {
    zsel.value = wantZone;
  }
}
function fillCountrySelect(wantCountry, wantZone) {
  var sel = document.getElementById("setCountry");
  var codes = Object.keys(tzData);
  sel.innerHTML = codes
    .map(function (c) {
      return '<option value="' + c + '">' + tzData[c].name + "</option>";
    })
    .join("");
  sel.value = wantCountry && codes.indexOf(wantCountry) >= 0 ? wantCountry : codes[0];
  fillZoneSelect(wantZone);
}
document.getElementById("setCountry").onchange = function () {
  fillZoneSelect();
};
function updateBillingModeFields() {
  var fixed = document.getElementById("setBillingMode").value === "1";
  document.getElementById("setBillingDate").disabled = fixed;
  document.getElementById("setBillingCycleLen").disabled = !fixed;
  document.getElementById("setBillingAnchor").disabled = !fixed;
}
document.getElementById("setBillingMode").onchange = updateBillingModeFields;
function minuteToHhmm(m) {
  var h = Math.floor(m / 60),
    mm = m % 60;
  return (h < 10 ? "0" : "") + h + ":" + (mm < 10 ? "0" : "") + mm;
}
function hhmmToMinute(s) {
  var p = s.split(":");
  return parseInt(p[0], 10) * 60 + parseInt(p[1], 10);
}
function loadSettings() {
  fetch("/api/settings")
    .then(function (r) {
      return r.json();
    })
    .then(function (s) {
      document.getElementById("setIp").value = s.modbus.ip;
      document.getElementById("setPort").value = s.modbus.port;
      document.getElementById("setInverter").value = s.sizing.inverter_kw;
      document.getElementById("setSolar").value = s.sizing.solar_kw;
      document.getElementById("setBillingDate").value = s.billing.date;
      document.getElementById("setBillingMode").value = String(s.billing.mode);
      document.getElementById("setBillingCycleLen").value = s.billing.cycle_length_days;
      document.getElementById("setBillingAnchor").value = s.billing.anchor;
      updateBillingModeFields();
      document.getElementById("setBlankEnabled").checked = s.blanking.enabled;
      document.getElementById("setBlankTimeout").value = String(s.blanking.timeout_s);
      document.getElementById("setNightEnabled").checked = s.night.enabled;
      document.getElementById("setNightStart").value = minuteToHhmm(s.night.start_minute);
      document.getElementById("setNightEnd").value = minuteToHhmm(s.night.end_minute);
      document.getElementById("setOrientation").value = s.orientation.portrait ? "portrait" : "landscape";
      var wantCountry = s.timezone.country_code,
        wantZone = s.timezone.zone;
      if (tzData) {
        fillCountrySelect(wantCountry, wantZone);
      } else {
        fetch("/tzdata.json")
          .then(function (r) {
            return r.json();
          })
          .then(function (d) {
            tzData = d;
            fillCountrySelect(wantCountry, wantZone);
          })
          .catch(function () {});
      }
    })
    .catch(function (err) {
      document.getElementById("setStatus").style.color = "#f87171";
      document.getElementById("setStatus").textContent = "Failed to load settings: " + err.message;
    });
  fetch("/api/backlight")
    .then(function (r) {
      return r.json();
    })
    .then(function (bl) {
      document.getElementById("setBlEnabled").checked = bl.enabled;
      document.getElementById("setBlPreset").value = bl.preset;
      document.getElementById("setBlPreset").dispatchEvent(new Event("change"));
      applyBlPercent(bl.percent);
      updateBlSliderEnabled();
    })
    .catch(function () {});
}
loadSettings();
function updateBlSliderEnabled() {
  document.getElementById("setBlSlider").disabled = document.getElementById("setBlPreset").value !== "off";
}
document.getElementById("setBlPreset").onchange = updateBlSliderEnabled;
var blDragging = false;
document.getElementById("setBlSlider").addEventListener("pointerdown", function () {
  blDragging = true;
});
window.addEventListener("pointerup", function () {
  blDragging = false;
});
function applyBlPercent(pct) {
  document.getElementById("setBlPercent").textContent = "(" + pct + "%)";
  if (!blDragging) {
    document.getElementById("setBlSlider").value = pct;
  }
}
function pollBacklightStatus() {
  fetch("/api/backlight")
    .then(function (r) {
      return r.json();
    })
    .then(function (bl) {
      applyBlPercent(bl.percent);
    })
    .catch(function () {});
}
var blSliderTimer = null;
document.getElementById("setBlSlider").oninput = function () {
  if (document.getElementById("setBlPreset").value !== "off") return;
  var pct = this.value;
  document.getElementById("setBlPercent").textContent = "(" + pct + "%)";
  var token = document.getElementById("setToken").value;
  if (!token) return;
  clearTimeout(blSliderTimer);
  blSliderTimer = setTimeout(function () {
    fetch("/api/backlight/set?percent=" + pct, { method: "POST", headers: { "X-OTA-Token": token } }).catch(function () {});
  }, 120);
};
document.getElementById("setSaveBtn").onclick = function () {
  var status = document.getElementById("setStatus");
  var token = document.getElementById("setToken").value;
  if (!token) {
    needToken(status);
    return;
  }
  var body = {
    ip: document.getElementById("setIp").value,
    port: parseInt(document.getElementById("setPort").value, 10),
    inverter_kw: parseFloat(document.getElementById("setInverter").value),
    solar_kw: parseFloat(document.getElementById("setSolar").value),
    billing_date: parseInt(document.getElementById("setBillingDate").value, 10),
    billing_mode: parseInt(document.getElementById("setBillingMode").value, 10),
    billing_cycle_length_days: parseInt(document.getElementById("setBillingCycleLen").value, 10),
    blank_enabled: document.getElementById("setBlankEnabled").checked,
    blank_timeout_s: parseInt(document.getElementById("setBlankTimeout").value, 10),
    night_enabled: document.getElementById("setNightEnabled").checked,
    night_start_minute: hhmmToMinute(document.getElementById("setNightStart").value),
    night_end_minute: hhmmToMinute(document.getElementById("setNightEnd").value),
    country_code: document.getElementById("setCountry").value,
    zone: document.getElementById("setZone").value,
  };
  var pin = document.getElementById("setOtaPin").value;
  if (pin) body.ota_pin = pin;
  var anchor = document.getElementById("setBillingAnchor").value;
  if (anchor) body.billing_anchor = anchor;
  status.style.color = "#94a3b8";
  status.textContent = "Saving...";
  fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-OTA-Token": token },
    body: JSON.stringify(body),
  })
    .then(function (r) {
      if (!r.ok)
        return r.json().then(function (e) {
          throw new Error(e.error || "HTTP " + r.status);
        });
      return r.json();
    })
    .then(function () {
      status.style.color = "#4ade80";
      status.textContent = "Saved. The device restarts automatically if the Modbus IP/port changed.";
      document.getElementById("setOtaPin").value = "";
    })
    .catch(function (err) {
      status.style.color = "#f87171";
      status.textContent = "Save failed: " + err.message;
    });
  fetch("/api/backlight/config", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-OTA-Token": token },
    body: JSON.stringify({
      enabled: document.getElementById("setBlEnabled").checked,
      preset: document.getElementById("setBlPreset").value,
    }),
  }).catch(function () {});
  if (document.getElementById("setBlPreset").value === "off") {
    var pct = document.getElementById("setBlSlider").value;
    fetch("/api/backlight/set?percent=" + pct, { method: "POST", headers: { "X-OTA-Token": token } }).catch(function () {});
  }
};
document.getElementById("setOrientBtn").onclick = function () {
  var token = document.getElementById("setToken").value;
  if (!token) {
    needToken();
    return;
  }
  var portrait = document.getElementById("setOrientation").value === "portrait";
  if (!confirm("Switch to " + (portrait ? "Portrait" : "Landscape") + " and restart the device now?")) return;
  fetch("/api/orientation", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-OTA-Token": token },
    body: JSON.stringify({ portrait: portrait }),
  })
    .then(function () {
      alert("Switching orientation -- the device is restarting.");
    })
    .catch(function (err) {
      alert("Failed: " + err.message);
    });
};
document.getElementById("setRebootBtn").onclick = function () {
  var token = document.getElementById("setToken").value;
  if (!token) {
    needToken();
    return;
  }
  if (!confirm("Reboot the device now?")) return;
  fetch("/api/reset", { method: "POST", headers: { "X-OTA-Token": token } })
    .then(function () {
      alert("Rebooting device...");
    })
    .catch(function (err) {
      alert("Failed: " + err.message);
    });
};
document.getElementById("setClearHistBtn").onclick = function () {
  var token = document.getElementById("setToken").value;
  if (!token) {
    needToken();
    return;
  }
  if (!confirm("Clear ALL stored history data (graphs and exports)? This cannot be undone.")) return;
  fetch("/api/history/clear", { method: "POST", headers: { "X-OTA-Token": token } })
    .then(function () {
      alert("History data cleared.");
      location.reload();
    })
    .catch(function (err) {
      alert("Failed: " + err.message);
    });
};
document.getElementById("setResetBtn").onclick = function () {
  var token = document.getElementById("setToken").value;
  if (!token) {
    needToken();
    return;
  }
  if (!confirm("This forgets the saved WiFi network and Modbus IP/port, then restarts. History is kept. Continue?")) return;
  fetch("/api/reset-wifi-modbus", { method: "POST", headers: { "X-OTA-Token": token } })
    .then(function () {
      alert("Resetting WiFi & Modbus -- the device is restarting.");
    })
    .catch(function (err) {
      alert("Failed: " + err.message);
    });
};
document.getElementById("setFactoryResetBtn").onclick = function () {
  var token = document.getElementById("setToken").value;
  if (!token) {
    needToken();
    return;
  }
  if (!confirm("FACTORY RESET: This wipes saved settings, network credentials, and clears ALL stored history data. Continue?"))
    return;
  fetch("/api/factory-reset", { method: "POST", headers: { "X-OTA-Token": token } })
    .then(function () {
      alert("Factory reset initiated -- the device is restarting.");
    })
    .catch(function (err) {
      alert("Failed: " + err.message);
    });
};
var fwToken = document.getElementById("fwToken");
var fwFlashBtn = document.getElementById("fwFlashBtn");
var fwFileInput = document.getElementById("fwFile");
var fwStatus = document.getElementById("fwStatus");
var fwInfoGrid = document.getElementById("fwInfoGrid");
var fwProgressWrap = document.getElementById("fwProgressWrap");
var fwProgressBar = document.getElementById("fwProgressBar");
Promise.all([
  fetch("/api/ota").then(function (r) {
    return r.json();
  }),
  fetch("/api/version")
    .then(function (r) {
      return r.ok ? r.json() : null;
    })
    .catch(function () {
      return null;
    }),
])
  .then(function (results) {
    var ota = results[0],
      ver = results[1];
    fwInfoGrid.innerHTML =
      row("Project", ota.project_name || "?") +
      row("IDF", ota.idf_version || "?") +
      row(
        "Running",
        (ota.running_partition || (ver && ver.running_slot) || "?") + " (" + (ota.version || (ver && ver.version) || "?") + ")",
      ) +
      row("Inactive", ver ? (ver.inactive_slot || "?") + " (" + (ver.inactive_version || "?") + ")" : "N/A");
  })
  .catch(function (err) {
    fwInfoGrid.innerHTML = row("Firmware info", "unavailable (" + err.message + ")", true);
  });
fwFileInput.onchange = function () {
  fwFlashBtn.disabled = !fwFileInput.files.length;
};
fwFlashBtn.onclick = function () {
  var file = fwFileInput.files[0];
  if (!file) return;
  if (!fwToken.value) {
    needToken(fwStatus);
    return;
  }
  if (!confirm("Upload " + file.name + " (" + file.size + " bytes) and reboot the device into it now?")) return;
  fwFlashBtn.disabled = true;
  fwProgressWrap.style.display = "block";
  fwProgressBar.style.width = "0%";
  fwStatus.style.color = "#94a3b8";
  fwStatus.textContent = "Uploading " + file.name + " (" + file.size + " bytes)...";
  var xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/ota", true);
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  xhr.setRequestHeader("X-OTA-Token", fwToken.value);
  xhr.upload.onprogress = function (e) {
    if (e.lengthComputable) {
      var pct = Math.round((e.loaded / e.total) * 100);
      fwProgressBar.style.width = pct + "%";
      fwStatus.textContent = "Uploading... " + pct + "% (" + e.loaded + "/" + e.total + " bytes)";
    }
  };
  xhr.onload = function () {
    if (xhr.status >= 200 && xhr.status < 300) {
      fwStatus.style.color = "#4ade80";
      fwStatus.textContent = "Upload complete! Device is verifying and rebooting...";
      waitForFwReboot();
    } else {
      fwStatus.style.color = "#f87171";
      fwStatus.textContent = "Upload failed (" + xhr.status + "): " + xhr.responseText;
      fwFlashBtn.disabled = false;
    }
  };
  xhr.onerror = function () {
    fwStatus.style.color = "#f87171";
    fwStatus.textContent = "Network error during upload.";
    fwFlashBtn.disabled = false;
  };
  xhr.send(file);
};
function waitForFwReboot() {
  var start = Date.now(),
    timeoutMs = 60000;
  setTimeout(function poll() {
    if (Date.now() - start > timeoutMs) {
      fwStatus.style.color = "#f87171";
      fwStatus.textContent = "Reboot verification timed out (60s).";
      fwFlashBtn.disabled = false;
      return;
    }
    fetch("/api/ota")
      .then(function (r) {
        if (!r.ok) throw new Error("not ready");
        return r.json();
      })
      .then(function (d) {
        fwStatus.style.color = "#4ade80";
        fwStatus.textContent = "Device back online, running " + d.version + " on " + d.running_partition + ".";
        fwFlashBtn.disabled = false;
      })
      .catch(function () {
        fwStatus.textContent = "Waiting for device to come back online... (" + Math.round((Date.now() - start) / 1000) + "s)";
        setTimeout(poll, 3000);
      });
  }, 5000);
}
(function () {
  var NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main";
  function findEOCD(dv) {
    for (var i = dv.byteLength - 22; i >= 0; i--) {
      if (dv.getUint32(i, true) === 0x06054b50) return i;
    }
    throw new Error("Not a valid zip file.");
  }
  function readZipEntries(buf) {
    var dv = new DataView(buf);
    var eocd = findEOCD(dv);
    var entryCount = dv.getUint16(eocd + 10, true);
    var cdOffset = dv.getUint32(eocd + 16, true);
    var entries = [];
    var p = cdOffset;
    for (var i = 0; i < entryCount; i++) {
      if (dv.getUint32(p, true) !== 0x02014b50) throw new Error("Corrupt zip central directory.");
      var method = dv.getUint16(p + 10, true);
      var compSize = dv.getUint32(p + 20, true);
      var nameLen = dv.getUint16(p + 28, true);
      var extraLen = dv.getUint16(p + 30, true);
      var commentLen = dv.getUint16(p + 32, true);
      var localOffset = dv.getUint32(p + 42, true);
      var name = new TextDecoder().decode(new Uint8Array(buf, p + 46, nameLen));
      entries.push({ name: name, method: method, compSize: compSize, localOffset: localOffset });
      p += 46 + nameLen + extraLen + commentLen;
    }
    return entries;
  }
  async function extractEntry(buf, entry) {
    var dv = new DataView(buf);
    var p = entry.localOffset;
    if (dv.getUint32(p, true) !== 0x04034b50) throw new Error("Corrupt local file header for " + entry.name + ".");
    var nameLen = dv.getUint16(p + 26, true);
    var extraLen = dv.getUint16(p + 28, true);
    var dataStart = p + 30 + nameLen + extraLen;
    var compressed = new Uint8Array(buf, dataStart, entry.compSize);
    if (entry.method === 0) return compressed.slice();
    if (entry.method === 8) {
      if (typeof DecompressionStream === "undefined")
        throw new Error("This browser has no built-in zip decompression -- try a recent Chrome, Edge, Firefox, or Safari.");
      var stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    }
    throw new Error("Unsupported zip compression method " + entry.method + " for " + entry.name + ".");
  }
  async function extractByPredicate(buf, predicate) {
    var entries = readZipEntries(buf);
    var entry = entries.find(predicate);
    if (!entry) return null;
    return extractEntry(buf, entry);
  }
  function parseSheetRows(xmlText) {
    var doc = new DOMParser().parseFromString(xmlText, "application/xml");
    if (doc.getElementsByTagName("parsererror").length) throw new Error("Could not parse the worksheet XML.");
    var rows = Array.from(doc.getElementsByTagNameNS(NS, "row"));
    return rows.map(function (row) {
      var cells = Array.from(row.getElementsByTagNameNS(NS, "c"));
      return cells.map(function (c) {
        var isEl = c.getElementsByTagNameNS(NS, "is")[0];
        var t = isEl && isEl.getElementsByTagNameNS(NS, "t")[0];
        return t ? t.textContent : "";
      });
    });
  }
  var COLUMN_PATTERNS = {
    date: ["date"],
    solar: ["solar"],
    load: ["load"],
    grid_import: ["grid imported", "grid import"],
    grid_export: ["grid exported", "grid export"],
  };
  function resolveColumns(headerRow) {
    var lower = headerRow.map(function (h) {
      return h.toLowerCase();
    });
    var col = {};
    Object.keys(COLUMN_PATTERNS).forEach(function (key) {
      var patterns = COLUMN_PATTERNS[key];
      var idx = lower.findIndex(function (h) {
        return patterns.some(function (p) {
          return h.includes(p);
        });
      });
      if (idx < 0) throw new Error('Missing "' + key + '" column in the header row: ' + headerRow.join(", "));
      col[key] = idx;
    });
    return col;
  }
  function parseFloatCell(s) {
    s = (s || "").trim();
    if (!s || s === "--") return 0.0;
    var v = parseFloat(s);
    return Number.isFinite(v) ? v : 0.0;
  }
  function buildMonthlyRows(sheetRows) {
    if (!sheetRows.length) throw new Error("Empty worksheet.");
    var col = resolveColumns(sheetRows[0]);
    var dataRows = sheetRows.slice(1);
    if (dataRows.length && (dataRows[dataRows.length - 1][col.date] || "").trim().toLowerCase() === "total") {
      dataRows = dataRows.slice(0, -1);
    }
    var totals = new Map();
    var skipped = 0;
    dataRows.forEach(function (r) {
      var dateStr = (r[col.date] || "").trim();
      var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
      if (!m) {
        skipped++;
        return;
      }
      var year = parseInt(m[1], 10),
        month = parseInt(m[2], 10);
      var key = year + "-" + month;
      if (!totals.has(key)) totals.set(key, { year: year, month: month, solar: 0, grid_import: 0, grid_export: 0, load: 0 });
      var t = totals.get(key);
      t.solar += parseFloatCell(r[col.solar]);
      t.grid_import += parseFloatCell(r[col.grid_import]);
      t.grid_export += parseFloatCell(r[col.grid_export]);
      t.load += parseFloatCell(r[col.load]);
    });
    var now = new Date();
    var curKey = now.getFullYear() + "-" + (now.getMonth() + 1);
    var emptyMonths = 0;
    var rows = Array.from(totals.values())
      .filter(function (t) {
        return t.year + "-" + t.month !== curKey;
      })
      .filter(function (t) {
        var empty = t.solar === 0 && t.grid_import === 0 && t.grid_export === 0 && t.load === 0;
        if (empty) emptyMonths++;
        return !empty;
      })
      .sort(function (a, b) {
        return a.year - b.year || a.month - b.month;
      })
      .map(function (t) {
        return {
          year: t.year,
          month: t.month,
          solar_kwh: t.solar,
          grid_import_kwh: t.grid_import,
          grid_export_kwh: t.grid_export,
          load_kwh: t.load,
        };
      });
    return { rows: rows, skipped: skipped, emptyMonths: emptyMonths };
  }
  async function sigenConvert(arrayBuf) {
    var xlsxBuf = arrayBuf;
    var outerXlsx = await extractByPredicate(arrayBuf, function (e) {
      return e.name.toLowerCase().endsWith(".xlsx");
    });
    if (outerXlsx) {
      xlsxBuf = outerXlsx.buffer.slice(outerXlsx.byteOffset, outerXlsx.byteOffset + outerXlsx.byteLength);
    }
    var sheetBytes = await extractByPredicate(xlsxBuf, function (e) {
      return /^xl\/worksheets\/sheet\d+\.xml$/.test(e.name);
    });
    if (!sheetBytes) throw new Error("No worksheet found inside the .xlsx.");
    var xmlText = new TextDecoder("utf-8").decode(sheetBytes);
    return buildMonthlyRows(parseSheetRows(xmlText));
  }
  function toCsv(rows) {
    var lines = ["year,month,solar_kwh,grid_import_kwh,grid_export_kwh,load_kwh"];
    rows.forEach(function (r) {
      lines.push(
        [
          r.year,
          r.month,
          r.solar_kwh.toFixed(2),
          r.grid_import_kwh.toFixed(2),
          r.grid_export_kwh.toFixed(2),
          r.load_kwh.toFixed(2),
        ].join(","),
      );
    });
    return lines.join("\n") + "\n";
  }
  var sigenCsv = null;
  function sigenRenderResults(rows, skipped, emptyMonths) {
    document.getElementById("sigenResultsCard").style.display = "";
    document.getElementById("sigenPushCard").style.display = "";
    var summaryHtml = "<b>" + rows.length + "</b> month(s) converted.";
    if (skipped) summaryHtml += " (" + skipped + " row(s) with an unparsable date skipped.)";
    if (emptyMonths) summaryHtml += " (" + emptyMonths + " month(s) with no data at all skipped.)";
    document.getElementById("sigenSummary").innerHTML = summaryHtml;
    var head = "<tr><th>Month</th><th>Solar</th><th>Grid In</th><th>Grid Out</th><th>Load</th></tr>";
    var body = rows
      .map(function (r) {
        return (
          "<tr><td>" +
          r.year +
          "-" +
          String(r.month).padStart(2, "0") +
          "</td><td>" +
          r.solar_kwh.toFixed(1) +
          "</td><td>" +
          r.grid_import_kwh.toFixed(1) +
          "</td><td>" +
          r.grid_export_kwh.toFixed(1) +
          "</td><td>" +
          r.load_kwh.toFixed(1) +
          "</td></tr>"
        );
      })
      .join("");
    document.getElementById("sigenPreview").innerHTML = head + body;
    sigenCsv = toCsv(rows);
  }
  document.getElementById("sigenDownloadBtn").onclick = function () {
    if (!sigenCsv) return;
    var blob = new Blob([sigenCsv], { type: "text/csv" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "monthly_import.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  document.getElementById("sigenPushBtn").onclick = async function () {
    var token = document.getElementById("sigenToken").value;
    var statusEl = document.getElementById("sigenPushStatus");
    if (!sigenCsv) return;
    if (!token) {
      needToken(statusEl);
      return;
    }
    if (!confirm("This replaces every completed month currently stored on this device. Continue?")) return;
    statusEl.style.color = "#94a3b8";
    statusEl.textContent = "Pushing...";
    try {
      var resp = await fetch("/api/monthly/import", {
        method: "POST",
        headers: { "X-OTA-Token": token, "Content-Type": "text/csv" },
        body: sigenCsv,
      });
      var text = await resp.text();
      if (!resp.ok) {
        statusEl.style.color = "#f87171";
        statusEl.textContent = "Device rejected the import (" + resp.status + "): " + text;
        return;
      }
      statusEl.style.color = "#4ade80";
      statusEl.textContent = "Device accepted the import: " + text;
    } catch (e) {
      statusEl.style.color = "#f87171";
      statusEl.textContent = "Request failed: " + e.message;
    }
  };
  async function sigenHandleFile(file) {
    var parseStatus = document.getElementById("sigenParseStatus");
    document.getElementById("sigenResultsCard").style.display = "none";
    document.getElementById("sigenPushCard").style.display = "none";
    parseStatus.style.color = "#94a3b8";
    parseStatus.textContent = "Reading " + file.name + " ...";
    try {
      var buf = await file.arrayBuffer();
      var result = await sigenConvert(buf);
      if (!result.rows.length) {
        parseStatus.style.color = "#f87171";
        parseStatus.textContent = 'No complete months found -- check this is a SigenStor "Log" export.';
        return;
      }
      parseStatus.textContent = "";
      sigenRenderResults(result.rows, result.skipped, result.emptyMonths);
    } catch (e) {
      parseStatus.style.color = "#f87171";
      parseStatus.textContent = "Error: " + e.message;
    }
  }
  var sigenDrop = document.getElementById("sigenDrop");
  var sigenFileInput = document.getElementById("sigenFile");
  sigenFileInput.addEventListener("change", function () {
    if (sigenFileInput.files[0]) sigenHandleFile(sigenFileInput.files[0]);
  });
  ["dragenter", "dragover"].forEach(function (evt) {
    sigenDrop.addEventListener(evt, function (e) {
      e.preventDefault();
      sigenDrop.classList.add("drag");
    });
  });
  ["dragleave", "drop"].forEach(function (evt) {
    sigenDrop.addEventListener(evt, function (e) {
      e.preventDefault();
      sigenDrop.classList.remove("drag");
    });
  });
  sigenDrop.addEventListener("drop", function (e) {
    var file = e.dataTransfer.files[0];
    if (file) sigenHandleFile(file);
  });
})();
showTab(location.hash.slice(1));
