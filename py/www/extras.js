// Web UI additions that sit on top of app.js: token handling, software updates, WiFi, Modbus test, backlight curve,
// panel view and accessibility. Loaded after app.js (it wraps showTab and uses its helpers).
(function () {
  "use strict";
  var $ = function (id) {
    return document.getElementById(id);
  };
  var cap = function (n) {
    return n[0].toUpperCase() + n.slice(1);
  };
  var tokenEl = $("globalAuthToken");
  var token = function () {
    return tokenEl.value || "";
  };
  var sleep = function (ms) {
    return new Promise(function (r) {
      setTimeout(r, ms);
    });
  };

  // ---- helpers -------------------------------------------------------------------------------------------------
  // JSON request with the admin token; throws Error(message) with the server's {"error": ...} text when it fails.
  async function api(path, opts) {
    opts = opts || {};
    var headers = { "X-OTA-Token": token() };
    var init = { method: opts.method || "GET", headers: headers };
    if (opts.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.body);
    }
    var r = await fetch(path, init);
    var text = await r.text();
    var data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch (e) {
      data = null;
    }
    if (!r.ok) {
      var err = new Error((data && data.error) || "HTTP " + r.status);
      err.status = r.status;
      throw err;
    }
    return data;
  }
  function say(el, kind, text) {
    el.textContent = text;
    el.style.color = kind === "ok" ? "#4ade80" : kind === "bad" ? "#f87171" : kind === "warn" ? "#fbbf24" : "#94a3b8";
  }
  function busy(btn, on) {
    btn.disabled = on;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function ago(s) {
    if (s == null) return "never";
    if (s < 90) return s + " s ago";
    if (s < 5400) return Math.round(s / 60) + " min ago";
    return Math.round(s / 3600) + " h ago";
  }
  // Wait until the panel answers again (after a restart); resolves with /api/version's JSON.
  async function waitForDevice(statusEl, label, timeoutMs) {
    var start = Date.now();
    await sleep(6000);
    while (Date.now() - start < timeoutMs) {
      try {
        var r = await fetch("/api/version", { cache: "no-store" });
        if (r.ok) return await r.json();
      } catch (e) {
        /* still restarting */
      }
      say(statusEl, "info", label + " (" + Math.round((Date.now() - start) / 1000) + " s)");
      await sleep(3000);
    }
    throw new Error("the panel did not come back within " + Math.round(timeoutMs / 1000) + " s");
  }

  // ---- token ---------------------------------------------------------------------------------------------------
  var tokenState = $("tokenState");
  function setTokenState(kind, text) {
    tokenState.className = "token-state " + kind;
    tokenState.textContent = text;
  }
  // Checked when you finish typing (change event), never per keystroke: a wrong prefix would count towards the lockout.
  async function checkToken() {
    if (!token()) return setTokenState("locked", "Locked: enter the token to make changes");
    try {
      await api("/api/auth");
      setTokenState("ok", "Unlocked");
    } catch (e) {
      setTokenState("bad", (e.status === 401 || e.status === 403) ? "Token not accepted" : e.status === 429 ? "Too many tries, wait a few minutes" : "Panel not reachable");
    }
  }
  tokenEl.addEventListener("change", checkToken);
  window.needToken = function (statusEl) {
    if (statusEl) say(statusEl, "warn", "Enter the admin token (top right) to do this.");
    else setTokenState("locked", "Enter the admin token to do this");
    tokenEl.focus();
    tokenEl.classList.remove("shake");
    void tokenEl.offsetWidth;
    tokenEl.classList.add("shake");
  };
  $("forgetTokenBtn").onclick = function () {
    try {
      localStorage.removeItem("adminToken");
    } catch (e) {
      /* storage blocked */
    }
    tokenEl.value = "";
    tokenEl.dispatchEvent(new Event("input"));
    setTokenState("locked", "Token forgotten in this browser");
  };
  checkToken();

  // ---- software updates ------------------------------------------------------------------------------------------
  var updBusy = false;
  function renderUpdate(d) {
    var s = d.state;
    var badge = $("updBadge");
    if (s.status === "installing") {
      badge.className = "badge badge-info";
      badge.textContent = "Installing";
    } else if (s.available) {
      badge.className = "badge badge-warning";
      badge.textContent = "Update available";
    } else if (s.error) {
      badge.className = "badge badge-warning";
      badge.textContent = "Check failed";
    } else if (s.checked_ago_s != null) {
      badge.className = "badge badge-success";
      badge.textContent = "Up to date";
    } else {
      badge.className = "badge";
      badge.textContent = "";
    }
    $("updInfo").innerHTML =
      row("Running", esc(d.current)) +
      row("Latest release", s.latest ? esc(s.latest) : "not checked yet") +
      row("Last checked", s.checked_ago_s == null ? "never" : ago(s.checked_ago_s)) +
      row("Source", esc(d.repo));
    $("updNotes").textContent = s.available && s.notes ? s.notes : "";
    var inst = $("updInstallBtn");
    inst.hidden = !s.available;
    inst.textContent = s.available ? "Install " + s.latest : "Install";
    $("updProgressWrap").style.display = s.status === "installing" ? "block" : "none";
    $("updProgressBar").style.width = s.progress + "%";
    if (s.status === "installing") say($("updStatus"), "info", "Downloading and verifying... " + s.progress + "%");
    else if (s.error) say($("updStatus"), "bad", s.error);
    $("updAuto").checked = d.auto;
    if (document.activeElement !== $("updRepo")) $("updRepo").value = d.repo;
    $("updCheckBtn").disabled = s.status !== "idle";
    return s;
  }
  async function refreshUpdate() {
    try {
      renderUpdate(await fetch("/api/update").then(function (r) {
        return r.json();
      }));
    } catch (e) {
      say($("updStatus"), "bad", "Panel not reachable.");
    }
  }
  $("updCheckBtn").onclick = async function () {
    if (!token()) return needToken($("updStatus"));
    busy(this, true);
    say($("updStatus"), "info", "Asking GitHub...");
    try {
      renderUpdate(await api("/api/update/check", { method: "POST" }));
      var st = await fetch("/api/update").then(function (r) {
        return r.json();
      });
      if (!st.state.error) say($("updStatus"), "ok", st.state.available ? "Version " + st.state.latest + " is available." : "You are running the latest version.");
    } catch (e) {
      say($("updStatus"), "bad", "Check failed: " + e.message);
    }
    busy(this, false);
  };
  $("updInstallBtn").onclick = async function () {
    if (!token()) return needToken($("updStatus"));
    if (!confirm("Install the new version from GitHub now? The panel restarts; settings and history are kept, and the old version returns automatically if the new one fails to start.")) return;
    busy(this, true);
    try {
      await api("/api/update/install", { method: "POST" });
      updBusy = true;
      var failed = false;
      while (updBusy) {
        await sleep(1500);
        try {
          var d = await fetch("/api/update").then(function (r) {
            return r.json();
          });
          var s = renderUpdate(d);
          if (s.error) {
            failed = true;
            break;
          }
          if (s.status === "idle" && s.progress >= 100) break;
        } catch (e) {
          break; // the panel is restarting
        }
      }
      updBusy = false;
      if (!failed) {
        var v = await waitForDevice($("updStatus"), "Restarting", 120000);
        say($("updStatus"), "ok", "Updated: now running " + v.version + ". Reloading...");
        await sleep(1500);
        location.reload();
      }
    } catch (e) {
      updBusy = false;
      say($("updStatus"), "bad", "Install failed: " + e.message);
    }
    busy(this, false);
  };
  $("updSaveBtn").onclick = async function () {
    if (!token()) return needToken($("updStatus"));
    try {
      renderUpdate(await api("/api/update/config", { method: "POST", body: { repo: $("updRepo").value.trim(), auto: $("updAuto").checked } }));
      say($("updStatus"), "ok", "Update settings saved.");
    } catch (e) {
      say($("updStatus"), "bad", "Not saved: " + e.message);
    }
  };

  // upload a release's app tar by hand
  $("appFile").onchange = function () {
    $("appUploadBtn").disabled = !$("appFile").files.length;
  };
  $("appUploadBtn").onclick = function () {
    var file = $("appFile").files[0];
    if (!file) return;
    if (!token()) return needToken($("appStatus"));
    if (!confirm("Install " + file.name + " and restart the panel now?")) return;
    var btn = this,
      bar = $("appProgressBar"),
      st = $("appStatus");
    busy(btn, true);
    $("appProgressWrap").style.display = "block";
    bar.style.width = "0%";
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/ota/py", true);
    xhr.setRequestHeader("Content-Type", "application/x-tar");
    xhr.setRequestHeader("X-OTA-Token", token());
    xhr.upload.onprogress = function (e) {
      if (e.lengthComputable) {
        bar.style.width = Math.round((e.loaded / e.total) * 100) + "%";
        say(st, "info", "Uploading... " + Math.round((e.loaded / e.total) * 100) + "%");
      }
    };
    xhr.onload = async function () {
      if (xhr.status < 200 || xhr.status >= 300) {
        var msg = xhr.responseText;
        try {
          msg = JSON.parse(msg).error || msg;
        } catch (e) {
          /* plain text */
        }
        say(st, "bad", "Rejected (" + xhr.status + "): " + msg);
        return busy(btn, false);
      }
      try {
        var v = await waitForDevice(st, "Installed, waiting for the panel to restart", 120000);
        say(st, "ok", "Done: now running " + v.version + ". Reloading...");
        await sleep(1500);
        location.reload();
      } catch (e) {
        say(st, "bad", e.message);
        busy(btn, false);
      }
    };
    xhr.onerror = function () {
      say(st, "bad", "Network error during upload.");
      busy(btn, false);
    };
    xhr.send(file);
  };

  // ---- Modbus connection test ----------------------------------------------------------------------------------
  $("setModbusTestBtn").onclick = async function () {
    var st = $("setModbusTestStatus");
    if (!token()) return needToken(st);
    var port = parseInt($("setPort").value, 10) || 502;
    busy(this, true);
    say(st, "info", "Connecting to " + $("setIp").value + ":" + port + "... (up to 10 s)");
    try {
      var d = await api("/api/modbus/test", { method: "POST", body: { ip: $("setIp").value.trim(), port: port } });
      if (d.ok) say(st, "ok", "Connected in " + d.connect_ms + " ms: " + (d.model || "unknown model") + (d.serial ? ", serial " + d.serial : ""));
      else say(st, "bad", "Could not reach the inverter: " + (/timeout/i.test(d.error) ? "no answer (timed out): check the address, port and that Modbus TCP is enabled" : d.error));
    } catch (e) {
      say(st, "bad", "Test failed: " + e.message);
    }
    busy(this, false);
  };

  // ---- WiFi --------------------------------------------------------------------------------------------------------
  var wifiChoice = null;
  async function loadWifi() {
    try {
      var w = await fetch("/api/wifi").then(function (r) {
        return r.json();
      });
      $("wifiInfo").innerHTML =
        row("Mode", w.mode === "ap" ? "Setup hotspot" : w.connected ? "Connected" : "Not connected", !w.connected && w.mode !== "ap") +
        row("Network", esc(w.ssid || "--")) +
        row("Address", esc(w.ip || "--")) +
        row("Signal", w.connected ? w.rssi + " dBm" : "--");
    } catch (e) {
      $("wifiInfo").innerHTML = row("WiFi", "unavailable", true);
    }
  }
  $("wifiScanBtn").onclick = async function () {
    var st = $("wifiStatus");
    if (!token()) return needToken(st);
    busy(this, true);
    say(st, "info", "Scanning... the panel pauses for a few seconds.");
    try {
      var nets = await api("/api/wifi/scan");
      var list = $("wifiList");
      list.innerHTML = "";
      nets.forEach(function (n) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "wifi-item";
        b.setAttribute("role", "option");
        b.innerHTML = "<span>" + esc(n.ssid) + (n.secure ? " &#128274;" : "") + "</span><span>" + n.rssi + " dBm</span>";
        b.onclick = function () {
          wifiChoice = n;
          Array.prototype.forEach.call(list.children, function (c) {
            c.setAttribute("aria-selected", c === b ? "true" : "false");
          });
          $("wifiPassField").hidden = !n.secure;
          $("wifiPassLabel").textContent = "Password for " + n.ssid;
          $("wifiConnectBtn").hidden = false;
          $("wifiConnectBtn").textContent = "Connect to " + n.ssid;
          if (n.secure) $("wifiPass").focus();
        };
        list.appendChild(b);
      });
      say(st, nets.length ? "ok" : "warn", nets.length ? nets.length + " networks found. Pick one." : "No networks found. Try again.");
    } catch (e) {
      say(st, "bad", "Scan failed: " + e.message);
    }
    busy(this, false);
  };
  $("wifiConnectBtn").onclick = async function () {
    var st = $("wifiStatus");
    if (!wifiChoice) return;
    if (!token()) return needToken(st);
    if (!confirm("Join " + wifiChoice.ssid + "? The panel leaves its current network, and its address on the new network will probably be different (see the Info screen on the panel).")) return;
    busy(this, true);
    try {
      var d = await api("/api/wifi/connect", { method: "POST", body: { ssid: wifiChoice.ssid, password: $("wifiPass").value } });
      say(st, "ok", d.note + " This page will stop responding if the address changes.");
      $("wifiPass").value = "";
    } catch (e) {
      say(st, "bad", "Could not start joining: " + e.message);
    }
    busy(this, false);
  };

  // ---- backlight custom curve ----------------------------------------------------------------------------------
  function curveRow(time, pct) {
    var r = document.createElement("div");
    r.className = "curve-row";
    r.innerHTML =
      '<input type="time" aria-label="Time of day" value="' + esc(time) + '"><input type="number" min="0" max="100" aria-label="Brightness percent" value="' + esc(pct) +
      '"><span>%</span><button type="button" class="btn btn-sec" aria-label="Remove this point">&times;</button>';
    r.querySelector("button").onclick = function () {
      r.remove();
    };
    return r;
  }
  function showCurveBox() {
    $("blCurveBox").hidden = $("setBlPreset").value !== "custom";
  }
  async function loadCurve() {
    showCurveBox();
    try {
      var bl = await fetch("/api/backlight").then(function (r) {
        return r.json();
      });
      var rows = $("blCurveRows");
      rows.innerHTML = "";
      (bl.points && bl.points.length ? bl.points : [["07:00", 80], ["22:00", 10]]).forEach(function (p) {
        rows.appendChild(curveRow(p[0], p[1]));
      });
    } catch (e) {
      /* leave empty */
    }
  }
  $("setBlPreset").addEventListener("change", showCurveBox);
  $("blAddPoint").onclick = function () {
    var rows = $("blCurveRows");
    if (rows.children.length >= 8) return say($("blCurveStatus"), "warn", "At most 8 points.");
    rows.appendChild(curveRow("12:00", 50));
  };
  $("blSaveCurve").onclick = async function () {
    var st = $("blCurveStatus");
    if (!token()) return needToken(st);
    var pts = Array.prototype.map.call($("blCurveRows").children, function (r) {
      var i = r.querySelectorAll("input");
      return [i[0].value, parseInt(i[1].value, 10)];
    });
    for (var k = 0; k < pts.length; k++) {
      if (!pts[k][0] || isNaN(pts[k][1]) || pts[k][1] < 0 || pts[k][1] > 100) return say(st, "bad", "Every point needs a time and a brightness of 0-100.");
      if (k && pts[k][0] <= pts[k - 1][0]) return say(st, "bad", "Times must be in ascending order, with no duplicates.");
    }
    try {
      await api("/api/backlight/curve", { method: "POST", body: { points: pts } });
      say(st, "ok", "Custom curve saved and applied.");
    } catch (e) {
      say(st, "bad", "Not saved: " + e.message);
    }
  };

  // ---- panel performance knobs ---------------------------------------------------------------------------------
  async function loadTuning() {
    try {
      var t = await fetch("/api/tuning").then(function (r) {
        return r.json();
      });
      $("advSingle").checked = !!t["ui.single"];
      $("advAnimate").checked = !!t["ui.animate"];
    } catch (e) {
      /* leave as is */
    }
  }
  $("advSaveBtn").onclick = async function () {
    var st = $("advStatus");
    if (!token()) return needToken(st);
    if (!confirm("Save and restart the panel now?")) return;
    try {
      await api("/api/tuning", { method: "POST", body: { "ui.single": $("advSingle").checked, "ui.animate": $("advAnimate").checked } });
      await api("/api/reset", { method: "POST" });
      var v = await waitForDevice(st, "Restarting", 90000);
      say(st, "ok", "Panel is back (" + v.version + ").");
    } catch (e) {
      say(st, "bad", e.message);
    }
  };

  // ---- panel view ------------------------------------------------------------------------------------------------------
  var panelTimer = null,
    panelBusy = false,
    panelUrl = null;
  async function panelRefresh() {
    if (panelBusy) return;
    panelBusy = true;
    var st = $("panelStatus");
    say(st, "info", "Capturing the screen (takes a couple of seconds)...");
    try {
      var r = await fetch("/api/screenshot?_=" + Date.now());
      if (!r.ok) throw new Error(r.status === 503 ? "another capture is running" : "HTTP " + r.status);
      var blob = await r.blob();
      if (panelUrl) URL.revokeObjectURL(panelUrl);
      panelUrl = URL.createObjectURL(blob);
      $("panelImg").src = panelUrl;
      say(st, "info", "Updated " + new Date().toLocaleTimeString());
    } catch (e) {
      say(st, "bad", "Capture failed: " + e.message);
    }
    panelBusy = false;
  }
  function panelAutoSet() {
    clearInterval(panelTimer);
    panelTimer = null;
    if ($("panelAuto").checked && $("tabPanel").classList.contains("active")) panelTimer = setInterval(panelRefresh, 5000);
  }
  $("panelAuto").onchange = panelAutoSet;
  $("panelRefresh").onclick = panelRefresh;
  function swipe(dir) {
    fetch("/api/swipe?dir=" + dir, { method: "POST" })
      .then(function () {
        return sleep(900);
      })
      .then(panelRefresh);
  }
  $("panelPrev").onclick = function () {
    swipe("right");
  };
  $("panelNext").onclick = function () {
    swipe("left");
  };

  // ---- tabs: keyboard, aria, per-tab loading -------------------------------------------------------------------
  $("tabBtnPanel").onclick = function () {
    showTab("panel");
  };
  var baseShowTab = showTab,
    firstMetrics = true;
  window.showTab = function (name, skipHash) {
    baseShowTab(name, skipHash);
    if (TAB_NAMES.indexOf(name) < 0) name = "metrics";
    TAB_NAMES.forEach(function (n) {
      $("tabBtn" + cap(n)).setAttribute("aria-selected", n === name ? "true" : "false");
    });
    if (name === "metrics") {
      if (!firstMetrics && dayOffset === 0) renderDay(0); // served from cache when under a minute old
      firstMetrics = false;
    }
    if (name === "firmware") refreshUpdate();
    if (name === "settings") {
      loadWifi();
      loadCurve();
      loadTuning();
    }
    if (name === "panel") panelRefresh();
    panelAutoSet();
  };
  $("tabBtnPanel").parentNode.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    var i = TAB_NAMES.map(function (n) {
      return $("tabBtn" + cap(n));
    }).indexOf(document.activeElement);
    if (i < 0) return;
    // follow the visual order of the buttons
    var btns = Array.prototype.slice.call(e.currentTarget.querySelectorAll("[role=tab]"));
    var at = btns.indexOf(document.activeElement);
    var next = btns[(at + (e.key === "ArrowRight" ? 1 : btns.length - 1)) % btns.length];
    next.focus();
    next.click();
    e.preventDefault();
  });

  // link every settings label to its control, for screen readers and click-to-focus
  Array.prototype.forEach.call(document.querySelectorAll(".field"), function (f) {
    var l = f.querySelector("label"),
      c = f.querySelector("input,select");
    if (l && c && c.id && !l.htmlFor) l.htmlFor = c.id;
  });

  // app.js already showed the tab named in the URL; run this file's per-tab loading for it too
  var startTab = location.hash.slice(1);
  TAB_NAMES.forEach(function (n) {
    $("tabBtn" + cap(n)).setAttribute("aria-selected", $("tabBtn" + cap(n)).classList.contains("active") ? "true" : "false");
  });
  if (startTab && startTab !== "metrics" && TAB_NAMES.indexOf(startTab) >= 0) window.showTab(startTab, true);
})();
