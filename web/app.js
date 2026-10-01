/* dropscope dashboard: WebSocket live feed + REST drill-down. Degrades
   gracefully to tables if Chart.js (CDN) is unavailable. */
(function () {
  "use strict";

  var hasChart = typeof window.Chart !== "undefined";
  var jobChart = null, tsChart = null;
  var selectedJob = null;
  var jobNames = {};

  function el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
  function fmt(ts) { return new Date(ts * 1000).toLocaleTimeString(); }
  function reasonClass(r) {
    r = (r || "").toLowerCase();
    var known = { buffer_full: 1, wred: 1, packet_integrity: 1, port_discard: 1 };
    return known[r] ? "tag " + r : "tag";
  }

  function initCharts() {
    if (!hasChart) return;
    jobChart = new Chart(el("jobChart"), {
      type: "bar",
      data: { labels: [], datasets: [{ label: "drops", data: [],
        backgroundColor: "#58a6ff" }] },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false, animation: false,
        onClick: function (evt, items, chart) {
          var els = (items && items.length)
            ? items
            : chart.getElementsAtEventForMode(evt, "nearest", { intersect: false }, true);
          if (els && els.length) {
            var idx = els[0].index;
            var jid = jobChart.data._ids[idx];
            if (jid) selectJob(jid);
          }
        },
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#8b949e" }, grid: { color: "#21262d" } },
          y: { ticks: { color: "#e6edf3" }, grid: { display: false } }
        }
      }
    });
    // Robust native click -> select job (nearest bar by y, forgiving on x).
    // Uses the real DOM event so hit-testing coordinates always map correctly.
    el("jobChart").addEventListener("click", function (evt) {
      if (!jobChart) return;
      var pts = jobChart.getElementsAtEventForMode(
        evt, "nearest", { intersect: false }, true);
      if (pts && pts.length) {
        var jid = (jobChart.data._ids || [])[pts[0].index];
        if (jid) selectJob(jid);
      }
    });
    el("jobChart").style.cursor = "pointer";
    tsChart = new Chart(el("tsChart"), {
      type: "line",
      data: { labels: [], datasets: [{ label: "drops/s", data: [],
        borderColor: "#f85149", backgroundColor: "rgba(248,81,73,.15)",
        fill: true, tension: .25, pointRadius: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { ticks: { color: "#8b949e", maxTicksLimit: 8 }, grid: { color: "#21262d" } },
          y: { beginAtZero: true, ticks: { color: "#8b949e" }, grid: { color: "#21262d" } }
        }
      }
    });
  }

  function renderSummary(s) {
    jobNames = s.job_names || {};
    el("kpiTotal").textContent = (s.total_drops || 0).toLocaleString();
    el("kpiFlows").textContent = (s.flows_tracked || 0).toLocaleString();
    var jobsHit = (s.top_jobs || []).filter(function (j) {
      return j.job_id !== "unattributed";
    }).length;
    el("kpiJobs").textContent = jobsHit;

    var labels = (s.top_jobs || []).map(function (j) {
      return j.name || j.job_id;
    });
    var ids = (s.top_jobs || []).map(function (j) { return j.job_id; });
    var data = (s.top_jobs || []).map(function (j) { return j.drops; });
    if (jobChart) {
      jobChart.data.labels = labels;
      jobChart.data._ids = ids;
      jobChart.data.datasets[0].data = data;
      jobChart.data.datasets[0].backgroundColor = ids.map(function (id) {
        return id === "unattributed" ? "#6e7681" : "#58a6ff";
      });
      jobChart.update();
    }
    if (tsChart) {
      var series = s.series || [];
      tsChart.data.labels = series.map(function (p) { return fmt(p.ts); });
      tsChart.data.datasets[0].data = series.map(function (p) { return p.drops; });
      tsChart.update();
    }
    if (selectedJob) loadFlows(selectedJob);
  }

  function pushFeed(d) {
    var body = el("feedBody");
    var tr = document.createElement("tr");
    var job = d.job_id
      ? esc(jobNames[d.job_id] || d.job_id)
      : '<span class="tag unattr">unattributed</span>';
    tr.innerHTML =
      '<td class="mono">' + esc(d.flow_key) + "</td>" +
      "<td>" + job + "</td>" +
      '<td><span class="' + reasonClass(d.drop_reason) + '">' + esc(d.drop_reason) + "</span></td>" +
      "<td>" + esc(d.queue) + "</td>";
    body.insertBefore(tr, body.firstChild);
    while (body.children.length > 14) body.removeChild(body.lastChild);
  }

  function selectJob(jid) {
    selectedJob = jid;
    loadFlows(jid);
  }

  function loadFlows(jid) {
    fetch("/api/jobs/" + encodeURIComponent(jid) + "/flows")
      .then(function (r) { return r.json(); })
      .then(function (res) {
        el("flowsTitle").textContent =
          "Flows affected in " + (res.name || jid);
        var body = el("flowsBody");
        body.innerHTML = "";
        if (!res.flows || !res.flows.length) {
          body.innerHTML = '<tr><td class="empty" colspan="5">No flows yet.</td></tr>';
          return;
        }
        res.flows.forEach(function (f) {
          var tr = document.createElement("tr");
          tr.innerHTML =
            '<td class="mono">' + esc(f.flow_key || f.flow_id) + "</td>" +
            "<td>" + esc(f.role || "") + "</td>" +
            "<td>" + (f.queue != null ? esc(f.queue) : "") + "</td>" +
            '<td><span class="' + reasonClass(f.drop_reason) + '">' +
              esc(f.drop_reason || "") + "</span></td>" +
            "<td>" + esc(f.drops) + "</td>";
          body.appendChild(tr);
        });
      })
      .catch(function () {});
  }

  function connect() {
    var proto = location.protocol === "https:" ? "wss" : "ws";
    var ws = new WebSocket(proto + "://" + location.host + "/ws");
    ws.onopen = function () {
      var s = el("status");
      s.textContent = "live"; s.className = "on";
    };
    ws.onclose = function () {
      var s = el("status");
      s.textContent = "reconnecting\u2026"; s.className = "";
      setTimeout(connect, 1500);
    };
    ws.onmessage = function (evt) {
      var msg = JSON.parse(evt.data);
      if (msg.type === "snapshot" || msg.type === "summary") {
        renderSummary(msg.data);
      } else if (msg.type === "drop") {
        pushFeed(msg.data);
      }
    };
  }

  initCharts();
  connect();
})();
