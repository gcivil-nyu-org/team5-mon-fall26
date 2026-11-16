// US36 #98: the conversation page as a chat. It checks for new messages every
// 15 seconds while the page is visible; nothing is checked while the tab is
// hidden, and it checks at once when the tab is shown again. The chat stays
// scrolled to the newest message. Enter sends, Shift+Enter adds a new line.
// Sending is a plain form POST, so the page also works without JavaScript
// (new messages then show on reload).
(function () {
  "use strict";

  const list = document.getElementById("conversation-messages");
  if (!list) return;
  const url = list.dataset.pollUrl;
  const every = Number(list.dataset.pollMs) || 15000;
  const empty = document.getElementById("conversation-empty");
  const form = document.getElementById("conversation-form");
  const box = document.getElementById("id_text");
  const notice = document.getElementById("conversation-read-only");
  let lastId = Number(list.dataset.lastId) || 0;
  let timer = null;
  let finished = false;

  function scrollToNewest() {
    list.scrollTop = list.scrollHeight;
  }

  function show(message) {
    const row = document.createElement("li");
    row.className = `chat-row ${message.mine ? "mine" : "theirs"}`;
    row.dataset.id = String(message.id);
    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    const who = document.createElement("span");
    who.className = "visually-hidden";
    who.textContent = `${message.sender}:`;
    const text = document.createElement("p");
    text.className = "chat-text";
    text.textContent = message.text; // never innerHTML: messages are user text
    const time = document.createElement("p");
    time.className = "chat-time";
    time.textContent = message.sent_at;
    bubble.append(who, text, time);
    row.append(bubble);
    list.append(row);
    if (empty) empty.hidden = true;
  }

  function stop() {
    if (timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
  }

  function start() {
    if (timer === null && !finished) timer = window.setInterval(check, every);
  }

  function becomeReadOnly(reason) {
    finished = true;
    stop();
    if (form) form.hidden = true;
    if (notice) {
      notice.textContent = reason;
      notice.hidden = false;
    }
  }

  function check() {
    if (finished || document.hidden) return Promise.resolve();
    return fetch(`${url}?${new URLSearchParams({ after: lastId })}`, {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => {
        let added = false;
        for (const message of data.messages) {
          if (message.id > lastId) {
            show(message);
            lastId = message.id;
            added = true;
          }
        }
        if (added) scrollToNewest();
        if (data.read_only) becomeReadOnly(data.read_only);
      })
      .catch(() => {
        // A dropped connection: try again at the next check.
      });
  }

  if (form && box) {
    box.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      if (box.value.trim()) form.requestSubmit();
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stop();
    } else {
      check();
      start();
    }
  });

  scrollToNewest();
  if (!document.hidden) start();
})();
