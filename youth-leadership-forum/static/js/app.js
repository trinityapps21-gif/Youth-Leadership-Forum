(function () {
  "use strict";
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  function api(url, method, body) {
    var opts = { method: method || "GET", headers: { "X-CSRF-Token": csrf }, credentials: "same-origin" };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) { var e = new Error(data.error || "Something went wrong. Try again."); e.data = data; throw e; }
        return data;
      });
    });
  }
  window.YLF = { api: api, csrf: csrf };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  // confirm before destructive forms
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute && e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) e.preventDefault();
  });

  // disable buttons after submit to stop double posts
  document.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    var b = e.target.querySelector && e.target.querySelector('button[type=submit].btn:not([data-keep])');
    if (b) setTimeout(function () { b.disabled = true; }, 0);
  });

  // close open dropdowns when clicking elsewhere
  document.addEventListener("click", function (e) {
    document.querySelectorAll("details.menu[open], details.pop[open]").forEach(function (d) {
      if (!d.contains(e.target)) d.removeAttribute("open");
    });
  });

  // ---- likes ----
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".js-like");
    if (!btn) return;
    api("/api/posts/" + btn.dataset.id + "/like", "POST").then(function (d) {
      btn.classList.toggle("liked", d.liked);
      btn.setAttribute("aria-pressed", d.liked ? "true" : "false");
      btn.querySelector(".n").textContent = d.count;
    }).catch(function (err) { alert(err.message); });
  });

  // ---- comments ----
  function renderComments(box, list) {
    var wrap = box.querySelector(".comments");
    wrap.textContent = "";
    list.forEach(function (c) {
      var row = el("div", "comment");
      var av;
      if (c.avatar) { av = el("img", "av av-sm"); av.src = c.avatar; av.alt = ""; }
      else { av = el("span", "av av-sm av-ph", c.initials); }
      var col = el("div");
      var bub = el("div", "bubble");
      bub.appendChild(el("b", null, c.name));
      bub.appendChild(document.createTextNode(c.content));
      var meta = el("div", "meta", c.when);
      if (c.mine) {
        var del = el("button", "icon-btn", "Delete");
        del.type = "button";
        del.style.padding = "0 .3rem"; del.style.fontSize = ".75rem";
        del.addEventListener("click", function () {
          api("/api/comments/" + c.id + "/delete", "POST").then(function () { load(box); bump(box, -1); });
        });
        meta.appendChild(document.createTextNode(" · "));
        meta.appendChild(del);
      }
      col.appendChild(bub); col.appendChild(meta);
      row.appendChild(av); row.appendChild(col);
      wrap.appendChild(row);
    });
  }
  function bump(box, d) {
    var n = box.closest(".post").querySelector(".js-toggle-comments .n");
    n.textContent = Math.max(0, parseInt(n.textContent, 10) + d);
  }
  function load(box) {
    return api("/api/posts/" + box.dataset.id + "/comments").then(function (d) { renderComments(box, d.comments); });
  }
  document.addEventListener("click", function (e) {
    var t = e.target.closest(".js-toggle-comments");
    if (!t) return;
    var box = t.closest(".post").querySelector(".comment-box");
    box.classList.toggle("hidden");
    if (!box.classList.contains("hidden")) {
      load(box);
      var inp = box.querySelector("input"); if (inp) inp.focus();
    }
  });
  document.addEventListener("submit", function (e) {
    var f = e.target.closest(".comment-form");
    if (!f) return;
    e.preventDefault();
    var box = f.closest(".comment-box"), inp = f.querySelector("input");
    var text = inp.value.trim();
    if (!text) return;
    api("/api/posts/" + box.dataset.id + "/comments", "POST", { content: text }).then(function (d) {
      inp.value = "";
      renderComments(box, d.comments);
      bump(box, 1);
    }).catch(function (err) { alert(err.message); });
  });

  // ---- report dialog ----
  var dlg = document.getElementById("report-dialog");
  if (dlg) {
    var current = null;
    document.addEventListener("click", function (e) {
      var b = e.target.closest(".js-report");
      if (!b) return;
      current = { type: b.dataset.type, id: b.dataset.id };
      dlg.querySelector(".r-title").textContent = b.dataset.type === "user" ? "Report this person" : "Report this post";
      dlg.querySelector(".r-msg").textContent = "";
      dlg.querySelector("form").reset();
      dlg.querySelector(".r-send").disabled = false;
      if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
    });
    dlg.querySelector(".r-cancel").addEventListener("click", function () { dlg.close(); });
    dlg.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var reason = (dlg.querySelector("input[name=reason]:checked") || {}).value;
      var msg = dlg.querySelector(".r-msg");
      if (!reason) { msg.textContent = "Choose a reason first."; return; }
      var btn = dlg.querySelector(".r-send"); btn.disabled = true;
      api("/api/report", "POST", { target_type: current.type, target_id: current.id, reason: reason, detail: dlg.querySelector("textarea").value })
        .then(function (d) { msg.textContent = d.message; setTimeout(function () { dlg.close(); }, 1400); })
        .catch(function (err) { msg.textContent = err.message; btn.disabled = false; });
    });
  }

  // ---- composer image preview ----
  var fileInput = document.getElementById("post-image");
  if (fileInput) {
    var prev = document.getElementById("post-preview");
    fileInput.addEventListener("change", function () {
      var f = fileInput.files[0];
      prev.textContent = "";
      if (!f) return;
      var box = el("div", "preview"), img = el("img");
      img.src = URL.createObjectURL(f); img.alt = "Photo preview";
      var rm = el("button", "btn btn-sm btn-ghost", "Remove photo"); rm.type = "button"; rm.style.marginTop = ".4rem";
      rm.addEventListener("click", function () { fileInput.value = ""; prev.textContent = ""; });
      box.appendChild(img); box.appendChild(rm); prev.appendChild(box);
    });
  }

  // ---- auto-grow textareas ----
  document.querySelectorAll("textarea[data-autogrow]").forEach(function (t) {
    t.addEventListener("input", function () { t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 140) + "px"; });
  });

  // ---- unread badge polling (skipped on the chat thread, which handles its own) ----
  if (document.body.dataset.signedIn === "1") {
    setInterval(function () {
      if (document.hidden) return;
      api("/api/unread").then(function (d) {
        document.querySelectorAll(".js-unread").forEach(function (b) {
          b.textContent = d.unread; b.classList.toggle("hidden", !d.unread);
        });
      }).catch(function () {});
    }, 20000);
  }
})();
