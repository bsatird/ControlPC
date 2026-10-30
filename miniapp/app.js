/* ControlPC Mini App — логіка (Етап 1: дашборд + авторизація Telegram) */
(function () {
  'use strict';

  var tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
  var TOKEN_KEY = 'controlpc.miniapp.token';
  var REFRESH_MS = 10000;

  var state = {
    token: sessionStorage.getItem(TOKEN_KEY) || '',
    user: null,
    timer: null,
    busy: false
  };

  function $(id) { return document.getElementById(id); }

  function haptic(style) {
    try {
      if (tg && tg.HapticFeedback) { tg.HapticFeedback.impactOccurred(style || 'light'); }
    } catch (e) { /* haptics можуть бути недоступні */ }
  }

  function showScreen(name) {
    ['loading', 'error', 'main'].forEach(function (key) {
      var el = $('screen-' + key);
      if (el) { el.classList.toggle('hidden', key !== name); }
    });
  }

  function setDot(online) {
    var dot = $('conn-dot');
    if (!dot) { return; }
    dot.classList.toggle('dot--on', !!online);
    dot.classList.toggle('dot--off', !online);
  }

  function showError(title, text) {
    $('error-title').textContent = title;
    $('error-text').textContent = text;
    setDot(false);
    showScreen('error');
  }

  function setText(id, value) {
    var el = $(id);
    if (el) { el.textContent = (value === undefined || value === null || value === '') ? '—' : String(value); }
  }

  function setBar(id, percent) {
    var el = $(id);
    if (!el) { return; }
    var p = Math.max(0, Math.min(100, Number(percent) || 0));
    el.style.width = p + '%';
    el.classList.toggle('is-warn', p >= 70 && p < 90);
    el.classList.toggle('is-danger', p >= 90);
  }

  function fmtMb(mb) {
    var value = Number(mb) || 0;
    return value >= 1024 ? (value / 1024).toFixed(1) + ' ГБ' : Math.round(value) + ' МБ';
  }

  function fmtTime(unix) {
    var d = unix ? new Date(unix * 1000) : new Date();
    function pad(n) { return n < 10 ? '0' + n : '' + n; }
    return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  // --- запити до API ---
  async function api(path, options) {
    var opts = options || {};
    var headers = { 'Accept': 'application/json' };
    if (opts.body) { headers['Content-Type'] = 'application/json'; }
    if (state.token) { headers['X-MiniApp-Token'] = state.token; }
    var res = await fetch(path, {
      method: opts.method || 'GET',
      headers: headers,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      cache: 'no-store',
      credentials: 'same-origin'
    });
    var data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    return { ok: res.ok, status: res.status, data: data };
  }

  async function authenticate() {
    var initData = tg ? (tg.initData || '') : '';
    if (!initData) {
      throw {
        title: 'Відкрий через Telegram',
        text: 'Ця сторінка працює лише всередині Telegram. Натисни в боті кнопку «🖥 Відкрити ControlPC».'
      };
    }
    var res = await fetch('/api/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData: initData }),
      cache: 'no-store'
    });
    var data = {};
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok || !data.ok) {
      throw {
        title: 'Доступ закрито',
        text: data.error || ('Сервер відхилив авторизацію (код ' + res.status + ').')
      };
    }
    state.token = data.token;
    state.user = data.user || null;
    try { sessionStorage.setItem(TOKEN_KEY, data.token); } catch (e) { /* приватний режим */ }
    return data;
  }

  async function loadStatus(retryAuth) {
    var res = await api('/api/status');
    if (res.status === 401 && retryAuth) {
      state.token = '';
      try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) { /* ignore */ }
      await authenticate();
      res = await api('/api/status');
    }
    if (!res.ok) {
      throw { title: 'Дані недоступні', text: res.data.error || ('Помилка ' + res.status) };
    }
    render(res.data.status || {});
    return res.data.status || {};
  }

  // --- відображення ---
  function render(status) {
    var cpu = status.cpu || {};
    var mem = status.memory || {};
    var disk = status.disk || {};
    var battery = status.battery;

    setText('pc-name', status.pc_name || 'ControlPC');
    setText('pc-subtitle', status.platform || 'підключено');

    setText('cpu-val', cpu.percent !== undefined ? Math.round(cpu.percent) : '—');
    setBar('cpu-bar', cpu.percent);
    setText('cpu-foot', cpu.cores_physical
      ? cpu.cores_physical + ' ядер / ' + (cpu.cores_logical || '?') + ' потоків'
      : 'дані недоступні');

    setText('ram-val', mem.percent !== undefined ? Math.round(mem.percent) : '—');
    setBar('ram-bar', mem.percent);
    setText('ram-foot', mem.total_mb
      ? fmtMb(mem.used_mb) + ' з ' + fmtMb(mem.total_mb)
      : 'дані недоступні');

    setText('disk-val', disk.percent !== undefined ? Math.round(disk.percent) : '—');
    setBar('disk-bar', disk.percent);
    setText('disk-foot', disk.total_gb
      ? disk.free_gb + ' ГБ вільно з ' + disk.total_gb + ' ГБ'
      : 'дані недоступні');

    if (battery && battery.percent !== undefined) {
      setText('bat-val', Math.round(battery.percent));
      setBar('bat-bar', battery.percent);
      setText('bat-foot', battery.plugged ? 'заряджається' : 'від батареї');
    } else {
      setText('bat-val', '—');
      setBar('bat-bar', 0);
      setText('bat-foot', 'батарею не знайдено');
    }

    setText('info-pc', status.pc_name);
    setText('info-platform', status.platform);
    setText('info-uptime', status.uptime);
    setText('info-bot', status.bot_version);
    setText('updated-at', fmtTime(status.time));

    var list = $('proc-list');
    if (list) {
      list.innerHTML = '';
      var procs = Array.isArray(status.top_processes) ? status.top_processes : [];
      if (!procs.length) {
        var empty = document.createElement('li');
        empty.className = 'muted';
        empty.textContent = 'дані недоступні';
        list.appendChild(empty);
      } else {
        procs.forEach(function (proc) {
          var li = document.createElement('li');
          var name = document.createElement('span');
          name.className = 'name';
          name.textContent = proc.name || '?';
          var memEl = document.createElement('span');
          memEl.className = 'mem';
          memEl.textContent = (proc.memory_percent !== undefined ? proc.memory_percent : 0) + '% RAM';
          li.appendChild(name);
          li.appendChild(memEl);
          list.appendChild(li);
        });
      }
    }

    setText('foot-user', state.user
      ? ((state.user.first_name || '') + (state.user.username ? ' @' + state.user.username : ''))
      : ('ID ' + (state.user && state.user.id ? state.user.id : '—')));
    setText('foot-api', status.api_version);
    setText('foot-time', status.timestamp);
    setDot(true);
  }

  // --- оновлення ---
  async function refresh(manual) {
    if (state.busy) { return; }
    state.busy = true;
    var btn = $('refresh-btn');
    if (btn) { btn.classList.add('spin'); }
    if (manual) { haptic('light'); }
    try {
      if (!state.token) { await authenticate(); }
      await loadStatus(true);
    } catch (err) {
      setDot(false);
      if (manual) {
        showError(err && err.title ? err.title : 'Помилка оновлення',
          err && err.text ? err.text : 'Сервер Mini App не відповідає.');
      }
    } finally {
      state.busy = false;
      if (btn) { btn.classList.remove('spin'); }
    }
  }

  function startAutoRefresh() {
    if (state.timer) { clearInterval(state.timer); }
    state.timer = setInterval(function () {
      if (document.hidden) { return; }
      refresh(false);
    }, REFRESH_MS);
  }

  async function boot() {
    showScreen('loading');
    try {
      if (tg) {
        tg.ready();
        tg.expand();
        try {
          if (tg.setHeaderColor) { tg.setHeaderColor('#17212b'); }
          if (tg.setBackgroundColor) { tg.setBackgroundColor('#17212b'); }
        } catch (e) { /* старим версіям Telegram це недоступно */ }
      }
      if (!state.token) { await authenticate(); }
      await loadStatus(true);
      showScreen('main');
      startAutoRefresh();
    } catch (err) {
      if (err && err.title) {
        showError(err.title, err.text || '');
      } else {
        showError('Немає зв\'язку', 'Сервер Mini App не відповідає. Перевір, чи запущений бот на ПК.');
      }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    var refreshBtn = $('refresh-btn');
    if (refreshBtn) { refreshBtn.addEventListener('click', function () { refresh(true); }); }
    var retryBtn = $('retry-btn');
    if (retryBtn) { retryBtn.addEventListener('click', function () { boot(); }); }
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) { refresh(false); }
    });
    if (tg && tg.onEvent) {
      tg.onEvent('themeChanged', function () { document.body.style.background = ''; });
    }
    boot();
  });
})();

