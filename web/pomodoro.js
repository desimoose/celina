(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
    return;
  }
  root.CelinaPomodoro = factory();
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const STORAGE_KEY = "celina-pomodoro-v1";

  function formatDuration(seconds) {
    const safe = Math.max(0, Math.floor(Number(seconds) || 0));
    const minutes = Math.floor(safe / 60);
    const remainder = safe % 60;
    return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
  }

  function defaultStorage() {
    try {
      return typeof localStorage === "undefined" ? null : localStorage;
    } catch {
      return null;
    }
  }

  function dayKey(now) {
    return new Date(now()).toISOString().slice(0, 10);
  }

  class PomodoroTimer {
    constructor(options = {}) {
      this.now = options.now || Date.now;
      this.storage = options.storage === undefined ? defaultStorage() : options.storage;
      this.onChange = options.onChange || (() => {});
      this.workSeconds = Math.max(1, Number(options.workSeconds || 1500));
      this.shortBreakSeconds = Math.max(1, Number(options.shortBreakSeconds || 300));
      this.longBreakSeconds = Math.max(1, Number(options.longBreakSeconds || 900));
      this.cyclesBeforeLongBreak = Math.max(1, Number(options.cyclesBeforeLongBreak || 4));
      this.preset = options.preset || "classic";
      this.phase = "work";
      this.remainingSeconds = this.workSeconds;
      this.completedFocuses = this._readCompletedFocuses();
      this.cycle = 0;
      this.running = false;
      this.started = false;
      this.lastTickAt = null;
    }

    start() {
      if (!this.running) {
        this.running = true;
        this.started = true;
        this.lastTickAt = this.now();
        this._emit();
      }
      return this.snapshot();
    }

    pause() {
      if (this.running) {
        this.tick();
        this.running = false;
        this.lastTickAt = null;
        this._emit();
      }
      return this.snapshot();
    }

    reset() {
      this.running = false;
      this.started = false;
      this.lastTickAt = null;
      this.phase = "work";
      this.remainingSeconds = this.workSeconds;
      this.cycle = 0;
      this._emit();
      return this.snapshot();
    }

    setPreset(preset, durations) {
      if (this.running) return this.snapshot();
      this.preset = preset;
      if (durations) {
        this.workSeconds = Math.max(1, Number(durations.workSeconds));
        this.shortBreakSeconds = Math.max(1, Number(durations.shortBreakSeconds));
        this.longBreakSeconds = Math.max(1, Number(durations.longBreakSeconds));
      }
      return this.reset();
    }

    tick() {
      if (!this.running || this.lastTickAt === null) return this.snapshot();
      const current = this.now();
      let elapsed = Math.max(0, Math.floor((current - this.lastTickAt) / 1000));
      if (!elapsed) return this.snapshot();
      this.lastTickAt += elapsed * 1000;

      while (elapsed >= this.remainingSeconds) {
        elapsed -= this.remainingSeconds;
        this._advancePhase();
      }
      this.remainingSeconds -= elapsed;
      this._emit();
      return this.snapshot();
    }

    snapshot() {
      return {
        phase: this.phase,
        remainingSeconds: this.remainingSeconds,
        completedFocuses: this.completedFocuses,
        cycle: this.cycle,
        running: this.running,
        started: this.started,
        preset: this.preset,
        workSeconds: this.workSeconds,
        shortBreakSeconds: this.shortBreakSeconds,
        longBreakSeconds: this.longBreakSeconds,
      };
    }

    _advancePhase() {
      if (this.phase === "work") {
        this.completedFocuses += 1;
        this.cycle += 1;
        this._writeCompletedFocuses();
        this.phase = this.cycle % this.cyclesBeforeLongBreak === 0
          ? "long_break" : "short_break";
      } else {
        this.phase = "work";
      }
      this.remainingSeconds = this._durationFor(this.phase);
    }

    _durationFor(phase) {
      if (phase === "long_break") return this.longBreakSeconds;
      if (phase === "short_break") return this.shortBreakSeconds;
      return this.workSeconds;
    }

    _readCompletedFocuses() {
      if (!this.storage) return 0;
      try {
        const raw = this.storage.getItem(STORAGE_KEY);
        const saved = raw ? JSON.parse(raw) : null;
        return saved && saved.day === dayKey(this.now)
          ? Math.max(0, Number(saved.completedFocuses) || 0) : 0;
      } catch {
        return 0;
      }
    }

    _writeCompletedFocuses() {
      if (!this.storage) return;
      try {
        this.storage.setItem(STORAGE_KEY, JSON.stringify({
          day: dayKey(this.now),
          completedFocuses: this.completedFocuses,
        }));
      } catch { /* browser storage may be disabled */ }
    }

    _emit() {
      this.onChange(this.snapshot());
    }
  }

  return { PomodoroTimer, formatDuration };
});
