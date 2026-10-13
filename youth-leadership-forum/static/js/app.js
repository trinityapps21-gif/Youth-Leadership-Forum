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
      syncLikers(btn.closest(".post"), d.count);
    }).catch(function (err) { alert(err.message); });
  });

  // ---- who liked ----
  function syncLikers(post, count) {
    var b = post && post.querySelector(".js-likers");
    if (!b) return;
    b.classList.toggle("hidden", !count);
    b.querySelector(".likers-n").textContent = count;
    b.querySelector(".likers-w").textContent = count === 1 ? "like" : "likes";
  }
  var likesDlg = document.getElementById("likes-dialog");
  if (likesDlg) {
    var likesList = document.getElementById("likes-list"), likesEmpty = likesDlg.querySelector(".likers-empty");
    document.getElementById("likes-close").addEventListener("click", function () { likesDlg.close(); });
    likesDlg.addEventListener("click", function (e) { if (e.target === likesDlg) likesDlg.close(); });
    document.addEventListener("click", function (e) {
      var b = e.target.closest(".js-likers");
      if (!b) return;
      likesList.textContent = ""; likesEmpty.classList.add("hidden");
      var loading = el("li", "muted small", "Loading…"); likesList.appendChild(loading);
      if (likesDlg.showModal) likesDlg.showModal(); else likesDlg.setAttribute("open", "");
      api("/api/posts/" + b.dataset.id + "/likes").then(function (d) {
        likesList.textContent = "";
        likesEmpty.classList.toggle("hidden", d.likes.length > 0);
        d.likes.forEach(function (u) {
          var li = el("li"), a = el("a", "liker"); a.href = u.url;
          var av;
          if (u.avatar) { av = el("img", "av av-md"); av.src = u.avatar; av.alt = ""; } else { av = el("span", "av av-md av-ph", u.initials); }
          var col = el("span", "grow"), nm = el("span", "nm", u.name);
          col.appendChild(nm);
          var sub = [u.role !== "member" ? u.role.charAt(0).toUpperCase() + u.role.slice(1) : "", u.organization].filter(Boolean).join(" · ");
          if (sub) col.appendChild(el("span", "small muted sub", sub));
          a.appendChild(av); a.appendChild(col); li.appendChild(a); likesList.appendChild(li);
        });
      }).catch(function (err) { likesList.textContent = ""; likesList.appendChild(el("li", "small", err.message)); });
    });
  }

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

  // ---- composer: photo / video / music / document ----
  var composer = document.getElementById("post-btn") && document.getElementById("post-btn").form;
  if (composer) {
    var picks = Array.prototype.slice.call(composer.querySelectorAll("input.pick"));
    var prev = document.getElementById("post-preview");
    var errBox = document.getElementById("post-error");
    var prog = document.getElementById("post-progress");
    var LIMIT = { image: 25, video: 40, audio: 15, document: 10 };
    var chosen = null; // the file that will be sent

    function showError(msg) { errBox.textContent = msg || ""; errBox.classList.toggle("hidden", !msg); }
    function clearAll() { picks.forEach(function (p) { p.value = ""; }); chosen = null; prev.textContent = ""; showError(""); }
    function size(n) { return n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB"; }

    // Big phone photos: shrink to 1600px in the browser so they upload fast.
    function shrinkImage(file) {
      return new Promise(function (resolve) {
        if (!/^image\/(jpeg|png|webp)$/.test(file.type) || file.size < 1500000) return resolve(file);
        var url = URL.createObjectURL(file), img = new Image();
        img.onload = function () {
          var k = Math.min(1, 1600 / Math.max(img.width, img.height)), c = document.createElement("canvas");
          c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
          c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
          c.toBlob(function (blob) {
            URL.revokeObjectURL(url);
            if (!blob || blob.size >= file.size) return resolve(file);
            resolve(new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }));
          }, "image/jpeg", 0.85);
        };
        img.onerror = function () { URL.revokeObjectURL(url); resolve(file); };
        img.src = url;
      });
    }

    function preview(file, kind) {
      prev.textContent = "";
      var box = el("div", "preview"), url = URL.createObjectURL(file), node;
      if (kind === "image") { node = el("img"); node.src = url; node.alt = "Photo preview"; }
      else if (kind === "video") { node = el("video"); node.src = url; node.controls = true; node.preload = "metadata"; node.setAttribute("playsinline", ""); }
      else if (kind === "audio") { node = el("audio"); node.src = url; node.controls = true; }
      else { node = el("div", "post-file"); node.appendChild(el("span", "fname", file.name)); }
      box.appendChild(node);
      box.appendChild(el("div", "small muted", file.name + " · " + size(file.size)));
      var rm = el("button", "btn btn-sm btn-ghost", "Remove"); rm.type = "button"; rm.style.marginTop = ".4rem";
      rm.addEventListener("click", clearAll);
      box.appendChild(rm); prev.appendChild(box);
    }

    picks.forEach(function (input) {
      input.addEventListener("change", function () {
        var f = input.files[0], kind = input.dataset.kind;
        picks.forEach(function (p) { if (p !== input) p.value = ""; });
        showError("");
        if (!f) { clearAll(); return; }
        if (f.size > LIMIT[kind] * 1048576) {
          clearAll(); showError("That " + kind + " is too large. The limit is " + LIMIT[kind] + " MB.");
          return;
        }
        (kind === "image" ? shrinkImage(f) : Promise.resolve(f)).then(function (file) {
          chosen = { file: file, kind: kind }; preview(file, kind);
        });
      });
    });

    // Send with a progress bar. Without JavaScript the form still posts normally.
    composer.addEventListener("submit", function (e) {
      if (!chosen) return;
      e.preventDefault();
      var fd = new FormData(composer);
      fd.delete("media");
      fd.append("media", chosen.file, chosen.file.name);
      var xhr = new XMLHttpRequest(), btn = document.getElementById("post-btn"), fill = prog.querySelector(".fill");
      btn.disabled = true; showError(""); prog.classList.remove("hidden"); fill.style.width = "0%";
      xhr.upload.onprogress = function (ev) { if (ev.lengthComputable) fill.style.width = Math.round(ev.loaded / ev.total * 100) + "%"; };
      xhr.onload = function () {
        var data = {};
        try { data = JSON.parse(xhr.responseText); } catch (x) {}
        if (xhr.status === 413) { fail("That file is too large to upload."); return; }
        if (xhr.status === 403 || xhr.status === 401) { fail("Your session expired. Reload the page and sign in again."); return; }
        if (xhr.status !== 200 || !data.ok) { fail(data.error || "The upload didn't finish. Try again."); return; }
        window.location.href = composer.getAttribute("action").replace(/\/post$/, "");  // reload the feed
      };
      xhr.onerror = function () { fail("The upload didn't finish. Check your connection and try again."); };
      xhr.ontimeout = xhr.onerror; xhr.timeout = 180000;
      function fail(msg) { btn.disabled = false; prog.classList.add("hidden"); showError(msg); }
      xhr.open("POST", composer.getAttribute("action"));
      xhr.setRequestHeader("X-CSRF-Token", csrf);
      xhr.setRequestHeader("X-Upload", "1");
      xhr.send(fd);
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
