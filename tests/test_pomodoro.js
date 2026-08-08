const test = require("node:test");
const assert = require("node:assert/strict");

const { PomodoroTimer, formatDuration } = require("../web/pomodoro.js");

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) { return values.has(key) ? values.get(key) : null; },
    setItem(key, value) { values.set(key, String(value)); },
  };
}

test("formatDuration renders a timer clock", () => {
  assert.equal(formatDuration(1500), "25:00");
  assert.equal(formatDuration(9), "00:09");
  assert.equal(formatDuration(0), "00:00");
});

test("PomodoroTimer transitions from focus to break and records completion", () => {
  let now = 0;
  const timer = new PomodoroTimer({
    now: () => now,
    storage: memoryStorage(),
    workSeconds: 10,
    shortBreakSeconds: 5,
    longBreakSeconds: 8,
    cyclesBeforeLongBreak: 2,
  });

  timer.start();
  now = 10_000;
  timer.tick();

  assert.equal(timer.snapshot().phase, "short_break");
  assert.equal(timer.snapshot().remainingSeconds, 5);
  assert.equal(timer.snapshot().completedFocuses, 1);
  assert.equal(timer.snapshot().running, true);

  now = 15_000;
  timer.tick();
  assert.equal(timer.snapshot().phase, "work");
  assert.equal(timer.snapshot().remainingSeconds, 10);
});

test("PomodoroTimer persists the daily completed-focus count locally", () => {
  const storage = memoryStorage();
  let now = 0;
  const first = new PomodoroTimer({ now: () => now, storage, workSeconds: 1, shortBreakSeconds: 1 });
  first.start();
  now = 1_000;
  first.tick();

  const reloaded = new PomodoroTimer({ now: () => now, storage, workSeconds: 1, shortBreakSeconds: 1 });
  assert.equal(reloaded.snapshot().completedFocuses, 1);
});
