/*! Customer chat widget. Embed with one script tag; styles live in a shadow root so they never clash with the host site. */
(function () {
  var s = document.currentScript;
  if (!s) return;
  var cfg = {
    api: (s.dataset.api || "").replace(/\/$/, ""),
    business: s.dataset.business || "",
    name: s.dataset.name || "Assistant",
    color: s.dataset.color || "#1f5eff",
    greeting: s.dataset.greeting || "Hi! How can I help you today?",
    side: s.dataset.position === "left" ? "left" : "right",
    chips: (s.dataset.suggestions || "").split("|").filter(Boolean),
    phone: s.dataset.phone || ""
  };

  function ink(hex) {
    var h = hex.replace("#", "");
    if (h.length === 3) h = h.split("").map(function (c) { return c + c; }).join("");
    var r = parseInt(h.substr(0, 2), 16), g = parseInt(h.substr(2, 2), 16), b = parseInt(h.substr(4, 2), 16);
    return 0.299 * r + 0.587 * g + 0.114 * b > 165 ? "#111111" : "#ffffff";
  }

  if (!cfg.business) console.error("chat widget: add data-business=\"your-business-id\" to the script tag");

  var sid;
  try {
    sid = localStorage.getItem("ca_sid");
    if (!sid) { sid = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()); localStorage.setItem("ca_sid", sid); }
  } catch (e) { sid = String(Date.now()) + Math.random(); }

  var host = document.createElement("div");
  host.style.cssText = "all:initial;position:fixed;z-index:2147483000;bottom:0;" + cfg.side + ":0;";
  document.body.appendChild(host);
  var root = host.attachShadow({ mode: "open" });

  root.innerHTML =
    "<style>" +
    ":host{font-family:system-ui,-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}" +
    "*{box-sizing:border-box}" +
    ".wrap{--a:" + cfg.color + ";--on:" + ink(cfg.color) + ";position:fixed;bottom:20px;" + cfg.side + ":20px;display:flex;flex-direction:column;align-items:" + (cfg.side === "left" ? "flex-start" : "flex-end") + ";gap:12px}" +
    "button{font:inherit;cursor:pointer}" +
    ":focus-visible{outline:3px solid var(--a);outline-offset:2px}" +
    ".launcher{width:60px;height:60px;border-radius:50%;border:0;background:var(--a);color:var(--on);display:grid;place-items:center;box-shadow:0 6px 20px rgba(0,0,0,.25)}" +
    ".launcher svg{width:28px;height:28px}" +
    ".panel{width:380px;height:min(580px,calc(100vh - 110px));background:#fff;color:#16181d;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.28);display:flex;flex-direction:column;overflow:hidden;transition:opacity .18s,transform .18s}" +
    ".panel[hidden]{display:none}" +
    "header{display:flex;align-items:center;justify-content:space-between;padding:14px 16px;border-bottom:1px solid #e6e8ec}" +
    ".t{font-weight:650;font-size:16px;line-height:1.2}" +
    ".t small{display:flex;align-items:center;gap:6px;font-weight:400;font-size:12.5px;color:#5b6270;margin-top:3px}" +
    ".t small i{width:8px;height:8px;border-radius:50%;background:#1aa05a;display:inline-block}" +
    ".x{border:0;background:none;width:36px;height:36px;border-radius:8px;color:#5b6270;font-size:22px;line-height:1}" +
    ".x:hover{background:#f1f2f4}" +
    ".log{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;scroll-behavior:smooth}" +
    ".m{max-width:84%;padding:10px 13px;border-radius:14px;font-size:15px;line-height:1.45;white-space:pre-wrap;overflow-wrap:anywhere}" +
    ".m.bot{background:#f1f2f4;align-self:flex-start;border-bottom-left-radius:4px}" +
    ".m.me{background:var(--a);color:var(--on);align-self:flex-end;border-bottom-right-radius:4px}" +
    ".m.err{background:#fdecec;color:#8a1c1c;align-self:flex-start}" +
    ".m.sys{background:none;color:#5b6270;font-size:13px;align-self:center;text-align:center;padding:2px}" +
    ".m.sys a{color:inherit;font-weight:600}" +
    ".dots{display:inline-flex;gap:4px;padding:4px 0}" +
    ".dots i{width:7px;height:7px;border-radius:50%;background:#8a91a0;animation:b 1s infinite}" +
    ".dots i:nth-child(2){animation-delay:.15s}.dots i:nth-child(3){animation-delay:.3s}" +
    "@keyframes b{0%,60%,100%{opacity:.35}30%{opacity:1}}" +
    ".chips{display:flex;flex-wrap:wrap;gap:8px;padding:0 16px 10px}" +
    ".chips button{border:1px solid #d5d9e0;background:#fff;color:#16181d;border-radius:999px;padding:7px 12px;font-size:13.5px}" +
    ".chips button:hover{border-color:var(--a)}" +
    "form{display:flex;gap:8px;padding:10px 12px;border-top:1px solid #e6e8ec}" +
    "input{flex:1;min-width:0;font:inherit;font-size:16px;border:1px solid #d5d9e0;border-radius:10px;padding:10px 12px;color:#16181d;background:#fff}" +
    "input:focus{outline:2px solid var(--a);border-color:transparent}" +
    ".send{border:0;background:var(--a);color:var(--on);border-radius:10px;padding:0 16px;font-weight:600}" +
    ".send:disabled{opacity:.5;cursor:default}" +
    ".note{margin:0;padding:0 14px 10px;font-size:11.5px;color:#6b7280;text-align:center}" +
    "@media(max-width:480px){.wrap{bottom:0;" + cfg.side + ":0;left:0;right:0;padding:0;align-items:" + (cfg.side === "left" ? "flex-start" : "flex-end") + "}.launcher{margin:0 16px calc(16px + env(safe-area-inset-bottom,0px))}.panel{position:fixed;inset:0;width:100%;height:100%;border-radius:0;padding-bottom:env(safe-area-inset-bottom,0px)}}" +
    "@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important;scroll-behavior:auto!important}}" +
    "</style>" +
    "<div class='wrap'>" +
    "<section class='panel' role='dialog' aria-label='Chat with " + cfg.name.replace(/'/g, "&#39;") + "' hidden>" +
    "<header><div class='t'><span class='nm'></span><small><i></i>AI assistant</small></div><button class='x' type='button' aria-label='Close chat'>&times;</button></header>" +
    "<div class='log' role='log' aria-live='polite'></div>" +
    "<div class='chips'></div>" +
    "<form autocomplete='off'><input type='text' maxlength='1000' placeholder='Type your message' aria-label='Message'><button class='send' type='submit'>Send</button></form>" +
    "<p class='note'>AI assistant. Answers may contain mistakes. Please don't share card numbers or other sensitive details.</p>" +
    "</section>" +
    "<button class='launcher' type='button' aria-expanded='false' aria-label='Open chat'>" +
    "<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M21 12a8 8 0 0 1-11.6 7.1L3 20.5l1.5-4.9A8 8 0 1 1 21 12z'/></svg>" +
    "</button></div>";

  var q = function (sel) { return root.querySelector(sel); };
  var panel = q(".panel"), launcher = q(".launcher"), log = q(".log"), chips = q(".chips");
  var form = q("form"), input = q("input"), send = q(".send");
  q(".nm").textContent = cfg.name;

  var started = false, busy = false;

  function add(cls, text) {
    var d = document.createElement("div");
    d.className = "m " + cls;
    d.textContent = text;
    log.appendChild(d);
    log.scrollTop = log.scrollHeight;
    return d;
  }

  function setOpen(open) {
    panel.hidden = !open;
    launcher.setAttribute("aria-expanded", String(open));
    launcher.setAttribute("aria-label", open ? "Close chat" : "Open chat");
    if (open) {
      if (!started) {
        started = true;
        add("bot", cfg.greeting);
        cfg.chips.forEach(function (c) {
          var b = document.createElement("button");
          b.type = "button"; b.textContent = c;
          b.onclick = function () { submit(c); };
          chips.appendChild(b);
        });
      }
      setTimeout(function () { input.focus(); }, 30);
    } else { launcher.focus(); }
  }

  function submit(text) {
    text = (text || "").trim();
    if (!text || busy) return;
    busy = true; send.disabled = true; chips.innerHTML = "";
    add("me", text);
    input.value = "";
    var wait = add("bot", "");
    wait.innerHTML = "<span class='dots'><i></i><i></i><i></i></span>";
    fetch(cfg.api + "/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ business_id: cfg.business, session_id: sid, message: text })
    })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        wait.textContent = d.reply;
        if (d.handoff) {
          var n = add("sys", "A team member will follow up. ");
          if (cfg.phone) {
            var a = document.createElement("a");
            a.href = "tel:" + cfg.phone; a.textContent = "Call " + cfg.phone;
            n.appendChild(a);
          }
        }
      })
      .catch(function () {
        wait.className = "m err";
        wait.textContent = "We couldn't reach the assistant. Please try again" + (cfg.phone ? " or call " + cfg.phone : "") + ".";
      })
      .then(function () { busy = false; send.disabled = false; log.scrollTop = log.scrollHeight; input.focus(); });
  }

  launcher.onclick = function () { setOpen(panel.hidden); };
  q(".x").onclick = function () { setOpen(false); };
  form.onsubmit = function (e) { e.preventDefault(); submit(input.value); };
  root.addEventListener("keydown", function (e) { if (e.key === "Escape" && !panel.hidden) setOpen(false); });
})();
