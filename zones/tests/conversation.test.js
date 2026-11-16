// US36 #98: the conversation page is a chat. It checks for new messages every
// 15 seconds, only while it is visible, stays scrolled to the newest message,
// and sends on Enter.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../../rides/static/rides/js/conversation.js"), "utf8");

function element(extra = {}) {
  return {
    hidden: false,
    dataset: {},
    className: "",
    textContent: "",
    children: [],
    listeners: {},
    append(...items) { this.children.push(...items); },
    addEventListener(name, fn) { this.listeners[name] = fn; },
    ...extra,
  };
}

function setup({ hidden = false, lastId = "4", withList = true } = {}) {
  const list = element({
    dataset: { pollUrl: "/rides/7/messages/3/new/", pollMs: "15000", lastId },
    scrollTop: 0,
    scrollHeight: 500,
  });
  const empty = element();
  let submitted = 0;
  const form = element({ requestSubmit() { submitted += 1; } });
  const box = element({ value: "" });
  const notice = element({ hidden: true });
  const listeners = {};
  const timers = new Map();
  let nextTimer = 1;
  const requests = [];
  let reply = { messages: [], read_only: null };
  let ok = true;

  const document = {
    hidden,
    getElementById(id) {
      if (!withList && id === "conversation-messages") return null;
      return {
        "conversation-messages": list,
        "conversation-empty": empty,
        "conversation-form": form,
        "conversation-read-only": notice,
        id_text: box,
      }[id] ?? null;
    },
    createElement() { return element(); },
    addEventListener(name, fn) { listeners[name] = fn; },
  };
  const window = {
    setInterval(fn, ms) { const id = nextTimer++; timers.set(id, { fn, ms }); return id; },
    clearInterval(id) { timers.delete(id); },
  };
  function fetch(url) {
    requests.push(url);
    return Promise.resolve({ ok, status: ok ? 200 : 500, json: () => Promise.resolve(reply) });
  }
  vm.runInNewContext(source, { document, window, fetch, URLSearchParams, String, Number });

  return {
    list, empty, form, box, notice, requests, timers,
    submitted() { return submitted; },
    press(key, { shiftKey = false, isComposing = false } = {}) {
      let prevented = false;
      box.listeners.keydown({ key, shiftKey, isComposing, preventDefault() { prevented = true; } });
      return prevented;
    },
    respond(data) { reply = data; },
    fail() { ok = false; },
    async tick() {
      const [timer] = timers.values();
      await timer.fn();
    },
    async setHidden(value) {
      document.hidden = value;
      await listeners.visibilitychange();
      await new Promise((resolve) => setImmediate(resolve));
    },
  };
}

test("checks every 15 seconds for messages after the last one shown", async () => {
  const ui = setup();
  assert.equal(ui.timers.size, 1);
  assert.equal([...ui.timers.values()][0].ms, 15000);
  assert.equal(ui.requests.length, 0);
  await ui.tick();
  assert.deepEqual(ui.requests, ["/rides/7/messages/3/new/?after=4"]);
});

test("new messages are added as text and the next check starts after them", async () => {
  const ui = setup({ lastId: "0" });
  ui.respond({
    messages: [
      { id: 5, mine: false, sender: "Early Bird", text: "<b>hi</b>", sent_at: "Wed 11 Nov, 8:00 AM" },
      { id: 6, mine: true, sender: "You", text: "hello", sent_at: "Wed 11 Nov, 8:01 AM" },
    ],
    read_only: null,
  });
  await ui.tick();
  assert.equal(ui.list.children.length, 2);
  const [first, second] = ui.list.children;
  assert.equal(first.className, "chat-row theirs");
  const [bubble] = first.children;
  assert.equal(bubble.className, "chat-bubble");
  const [who, text, time] = bubble.children;
  assert.equal(who.textContent, "Early Bird:");
  assert.equal(text.textContent, "<b>hi</b>");
  assert.equal(time.textContent, "Wed 11 Nov, 8:00 AM");
  assert.equal(second.className, "chat-row mine");
  assert.equal(ui.empty.hidden, true);

  ui.respond({ messages: [], read_only: null });
  await ui.tick();
  assert.equal(ui.requests[1], "/rides/7/messages/3/new/?after=6");
});

test("a message already shown is not added twice", async () => {
  const ui = setup({ lastId: "6" });
  ui.respond({ messages: [{ id: 6, mine: true, sender: "You", text: "x", sent_at: "" }], read_only: null });
  await ui.tick();
  assert.equal(ui.list.children.length, 0);
});

test("no checks while the page is hidden; checks at once when shown again", async () => {
  const ui = setup();
  await ui.setHidden(true);
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.requests.length, 0);

  await ui.setHidden(false);
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.timers.size, 1);
});

test("a page opened in a background tab waits until it is shown", async () => {
  const ui = setup({ hidden: true });
  assert.equal(ui.timers.size, 0);
  assert.equal(ui.requests.length, 0);
  await ui.setHidden(false);
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.timers.size, 1);
});

test("a conversation that becomes read-only hides the form and stops checking", async () => {
  const ui = setup();
  ui.respond({ messages: [], read_only: "This conversation is read-only." });
  await ui.tick();
  assert.equal(ui.form.hidden, true);
  assert.equal(ui.notice.hidden, false);
  assert.equal(ui.notice.textContent, "This conversation is read-only.");
  assert.equal(ui.timers.size, 0);

  await ui.setHidden(true);
  await ui.setHidden(false);
  assert.equal(ui.requests.length, 1);
  assert.equal(ui.timers.size, 0);
});

test("a failed check is ignored and the timer keeps going", async () => {
  const ui = setup();
  ui.fail();
  await ui.tick();
  assert.equal(ui.timers.size, 1);
  assert.equal(ui.list.children.length, 0);
});

test("does nothing on pages without a conversation", () => {
  const ui = setup({ withList: false });
  assert.equal(ui.timers.size, 0);
});

test("the chat opens scrolled to the newest message and follows new ones", async () => {
  const ui = setup();
  assert.equal(ui.list.scrollTop, 500);
  ui.list.scrollTop = 0;
  ui.list.scrollHeight = 800;
  ui.respond({ messages: [{ id: 9, mine: false, sender: "Early Bird", text: "hi", sent_at: "" }], read_only: null });
  await ui.tick();
  assert.equal(ui.list.scrollTop, 800);
});

test("no new messages leaves the scroll position alone", async () => {
  const ui = setup();
  ui.list.scrollTop = 120;
  await ui.tick();
  assert.equal(ui.list.scrollTop, 120);
});

test("Enter sends the message; Shift+Enter is a new line", () => {
  const ui = setup();
  ui.box.value = "See you at the corner";
  assert.equal(ui.press("Enter", { shiftKey: true }), false);
  assert.equal(ui.submitted(), 0);
  assert.equal(ui.press("Enter"), true);
  assert.equal(ui.submitted(), 1);
});

test("Enter on an empty box or while typing an accent sends nothing", () => {
  const ui = setup();
  ui.box.value = "   ";
  assert.equal(ui.press("Enter"), true);
  ui.box.value = "café";
  assert.equal(ui.press("Enter", { isComposing: true }), false);
  assert.equal(ui.press("a"), false);
  assert.equal(ui.submitted(), 0);
});
