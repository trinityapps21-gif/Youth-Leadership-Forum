(function () {
  "use strict";
  var cfg = JSON.parse(document.getElementById("chat-data").textContent);
  var box = document.getElementById("msgs");
  var form = document.getElementById("send-form");
  var input = document.getElementById("msg-input");
  var lastId = 0, lastDay = "", sending = false;

  function nearBottom() { return box.scrollHeight - box.scrollTop - box.clientHeight < 140; }
  function append(list) {
    var stick = nearBottom() || lastId === 0;
    list.forEach(function (m) {
      if (m.id <= lastId) return;
      if (m.day !== lastDay) {
        var d = document.createElement("div"); d.className = "day"; d.textContent = m.day; box.appendChild(d); lastDay = m.day;
      }
      var b = document.createElement("div"); b.className = "msg" + (m.mine ? " mine" : "");
      if (cfg.group && !m.mine) { var w = document.createElement("span"); w.className = "who"; w.textContent = m.sender; b.appendChild(w); }
      b.appendChild(document.createTextNode(m.content));
      var t = document.createElement("time"); t.textContent = m.time; b.appendChild(t);
      box.appendChild(b); lastId = m.id;
    });
    if (stick) box.scrollTop = box.scrollHeight;
  }
  function poll() {
    if (document.hidden) return;
    YLF.api("/api/chats/" + cfg.id + "/messages?after=" + lastId).then(function (d) { append(d.messages); }).catch(function () {});
  }
  append(cfg.messages);
  box.scrollTop = box.scrollHeight;
  setInterval(poll, 3000);
  document.addEventListener("visibilitychange", poll);

  function send() {
    var text = input.value.trim();
    if (!text || sending) return;
    sending = true;
    YLF.api("/api/chats/" + cfg.id + "/messages?after=" + lastId, "POST", { content: text }).then(function (d) {
      input.value = ""; input.style.height = "44px"; append(d.messages);
    }).catch(function (err) {
      var n = document.getElementById("send-error"); n.textContent = err.message; n.classList.remove("hidden");
      setTimeout(function () { n.classList.add("hidden"); }, 4000);
    }).then(function () { sending = false; input.focus(); });
  }
  if (form) {
    form.addEventListener("submit", function (e) { e.preventDefault(); send(); });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
    });
  }
})();
