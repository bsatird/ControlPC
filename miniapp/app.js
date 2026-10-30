/* ControlPC Mini App — логіка (Етап 2: преміальний дашборд) */
(function () {
  'use strict';

  var tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;
  var TOKEN_KEY = 'controlpc.miniapp.token';
  var REFRESH_MS = 10000;

  var state = {
    token: '',
    user: null,
    timer: null,
    ticker: null,
    busy: false,
    online: false,
    offlineNotified: false,
    toastTimer: null,
    nextAt: 0,
    capabilities: null,
    pane: '',
    confirm: null,
    actionBusy: false,
    procList: [],
    procQuery: '',
    procLoadedAt: 0,
    camUrl: ''
  };

  // Розділи панелі керування (Етап 3)
  var PANE_TITLES = {
    power: 'Живлення',
    media: 'Медіа',
    apps: 'Додатки та процеси',
    camera: 'Камера'
  };

  var POWER_TITLES = {
    shutdown: 'Вимкнути ПК?',
    reboot: 'Перезавантажити ПК?',
    sleep: 'Перевести ПК в сон?'
  };

  var POWER_BUTTONS = {
    shutdown: 'Вимкнути',
    reboot: 'Перезавантажити',
    sleep: 'У сон'
  };

  var PROC_STATUS = {
    running: 'працює',
    sleeping: 'очікує',
    stopped: 'зупинено',
    zombie: 'зомбі',
    idle: 'простій'
  };

  try { state.token = sessionStorage.getItem(TOKEN_KEY) || ''; } catch (e) { state.token = ''; }

  // --- дрібні утиліти ---
  function $(id) { return document.getElementById(id); }

  function each(selector, callback) {
    var nodes = document.querySelectorAll(selector);
    for (var i = 0; i < nodes.length; i++) { callback(nodes[i], i); }
  }

  function isNum(value) {
    return value !== null && value !== undefined && value !== '' && isFinite(Number(value));
  }

  function clamp(value, min, max) {
    var n = Number(value);
    if (!isFinite(n)) { return min; }
    return Math.max(min, Math.min(max, n));
  }

  function pad2(n) { return n < 10 ? '0' + n : '' + n; }

  function fmtClock(date) {
    var d = date instanceof Date ? date : new Date(date || Date.now());
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes()) + ':' + pad2(d.getSeconds());
  }

  function fmtMb(mb) {
    var value = Number(mb) || 0;
    return value >= 1024 ? (value / 1024).toFixed(1) + ' ГБ' : Math.round(value) + ' МБ';
  }

  function fmtGb(gb) {
    var value = Number(gb) || 0;
    return (value >= 100 ? String(Math.round(value)) : value.toFixed(1)) + ' ГБ';
  }

  function loadWord(percent) {
    if (!isNum(percent)) { return 'немає даних'; }
    var p = Number(percent);
    if (p >= 90) { return 'критичне навантаження'; }
    if (p >= 70) { return 'високе навантаження'; }
    if (p >= 40) { return 'помірне навантаження'; }
    return 'нормальне навантаження';
  }

  function shortVersion(value) {
    var text = String(value || '').trim();
    if (!text) { return 'v—'; }
    var first = text.split(' ')[0];
    if (first.charAt(0) === 'v' || first.charAt(0) === 'V') { first = first.slice(1); }
    return 'v' + first;
  }

  function setText(id, value) {
    var el = $(id);
    if (!el) { return; }
    var text = (value === undefined || value === null || value === '') ? '—' : String(value);
    if (el.textContent !== text) { el.textContent = text; }
  }

  // --- Telegram: тактильний відгук ---
  var HAPTIC_KINDS = { light: 1, medium: 1, heavy: 1, rigid: 1, soft: 1 };

  function haptic(kind) {
    var style = HAPTIC_KINDS[kind] ? kind : 'light';
    try {
      if (tg && tg.HapticFeedback && tg.HapticFeedback.impactOccurred) {
        tg.HapticFeedback.impactOccurred(style);
      }
    } catch (e) { /* старі версії Telegram */ }
  }

  function notifyHaptic(type) {
    try {
      if (tg && tg.HapticFeedback && tg.HapticFeedback.notificationOccurred) {
        tg.HapticFeedback.notificationOccurred(type || 'success');
      }
    } catch (e) { /* ignore */ }
  }

  function selectionHaptic() {
    try {
      if (tg && tg.HapticFeedback && tg.HapticFeedback.selectionChanged) {
        tg.HapticFeedback.selectionChanged();
      }
    } catch (e) { /* ignore */ }
  }

  // --- Telegram: тема та системні кольори ---
  function isLightScheme() {
    if (tg && tg.colorScheme) { return tg.colorScheme === 'light'; }
    try {
      return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches);
    } catch (e) {
      return false;
    }
  }

  function applyTheme() {
    var root = document.documentElement;
    var light = isLightScheme();
    root.setAttribute('data-theme', light ? 'light' : 'dark');

    var params = (tg && tg.themeParams) || {};
    var map = { bg_color: '--page-bg', text_color: '--page-ink', hint_color: '--muted' };
    Object.keys(map).forEach(function (key) {
      var value = params[key];
      var property = map[key];
      if (typeof value === 'string' && value) {
        root.style.setProperty(property, value);
      } else {
        root.style.removeProperty(property);
      }
    });
  }

  function syncChrome() {
    if (!tg) { return; }
    var params = tg.themeParams || {};
    var bg = params.bg_color || (isLightScheme() ? '#eef1f7' : '#0a0c11');
    try {
      if (typeof tg.setHeaderColor === 'function') { tg.setHeaderColor(bg); }
    } catch (e) { /* Bot API < 6.1 */ }
    try {
      if (typeof tg.setBackgroundColor === 'function') { tg.setBackgroundColor(bg); }
    } catch (e) { /* Bot API < 6.1 */ }
    try {
      if (typeof tg.setBottomBarColor === 'function') { tg.setBottomBarColor(bg); }
    } catch (e) { /* Bot API < 7.10 */ }
  }

  // --- екрани, лоадери, тости ---
  function showScreen(name) {
    ['loading', 'error', 'main'].forEach(function (key) {
      var el = $('screen-' + key);
      if (el) { el.classList.toggle('hidden', key !== name); }
    });
  }

  function setBusy(on) {
    var bar = $('load-bar');
    if (bar) { bar.classList.toggle('is-active', !!on); }
    var btn = $('refresh-btn');
    if (btn) {
      btn.classList.toggle('is-spinning', !!on);
      btn.disabled = !!on;
    }
  }

  function setOnline(on) {
    state.online = !!on;
    var dot = $('conn-dot');
    if (dot) {
      dot.classList.toggle('dot--on', !!on);
      dot.classList.toggle('dot--off', !on);
    }
    setText('conn-text', on ? 'на зв\'язку' : 'немає зв\'язку');
  }

  function toast(message) {
    var el = $('toast');
    if (!el) { return; }
    el.textContent = message;
    el.classList.add('is-visible');
    if (state.toastTimer) { clearTimeout(state.toastTimer); }
    state.toastTimer = setTimeout(function () { el.classList.remove('is-visible'); }, 2600);
  }

  function showError(title, text) {
    setText('error-title', title || 'Помилка');
    setText('error-text', text || '');
    setOnline(false);
    showScreen('error');
  }

  function errorTitle(err) {
    if (err && typeof err === 'object' && err.title) { return err.title; }
    return 'Помилка оновлення';
  }

  function errorText(err) {
    if (err && typeof err === 'object' && err.text) { return err.text; }
    return 'Сервер Mini App не відповідає. Перевір, чи запущений бот на ПК.';
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
    var status = res.data.status || {};
    render(status);
    return status;
  }

  // --- відображення показників ---
  function setBar(id, percent) {
    var el = $(id);
    if (!el) { return; }
    el.style.width = clamp(percent, 0, 100) + '%';
  }

  function markLevel(key, percent, lowIsBad) {
    var card = $('card-' + key);
    var bar = $(key + '-bar');
    var level = 0;
    if (isNum(percent)) {
      var p = Number(percent);
      if (lowIsBad) {
        level = p <= 15 ? 2 : (p <= 30 ? 1 : 0);
      } else {
        level = p >= 90 ? 2 : (p >= 70 ? 1 : 0);
      }
    }
    if (card) {
      card.classList.toggle('is-empty', !isNum(percent));
      card.classList.toggle('is-warn', level === 1);
      card.classList.toggle('is-danger', level === 2);
    }
    if (bar) {
      bar.classList.toggle('is-warn', level === 1);
      bar.classList.toggle('is-danger', level === 2);
    }
    return level;
  }

  function applyMetric(key, percent, foot, detail, lowIsBad) {
    var has = isNum(percent);
    var value = has ? Math.round(Number(percent)) : null;
    setText(key + '-val', has ? value : '—');
    setBar(key + '-bar', has ? value : 0);
    setText(key + '-foot', foot);
    setText(key + '-detail', detail);
    markLevel(key, has ? value : null, lowIsBad);
  }

  function subtitleOf(status) {
    var parts = [];
    if (status.platform) { parts.push(status.platform); }
    if (status.python) { parts.push('Python ' + status.python); }
    return parts.length ? parts.join(' · ') : 'підключено';
  }

  function cpuFoot(cpu) {
    var physical = Number(cpu.cores_physical) || 0;
    var logical = Number(cpu.cores_logical) || 0;
    if (!physical && !logical) { return 'ядра недоступні'; }
    return physical + ' ядер / ' + logical + ' потоків';
  }

  function cpuDetail(cpu) {
    var parts = [];
    if (Number(cpu.freq_mhz)) { parts.push(Math.round(Number(cpu.freq_mhz)) + ' МГц'); }
    parts.push(loadWord(cpu.percent));
    return parts.join(' · ');
  }

  function ramFoot(mem) {
    if (!mem.total_mb) { return 'дані недоступні'; }
    return fmtMb(mem.used_mb) + ' з ' + fmtMb(mem.total_mb);
  }

  function ramDetail(mem, swap) {
    var parts = [];
    if (swap && swap.total_mb) {
      parts.push('підкачка ' + Math.round(Number(swap.percent) || 0) + '% від ' + fmtMb(swap.total_mb));
    } else {
      parts.push('файл підкачки недоступний');
    }
    parts.push(loadWord(mem.percent));
    return parts.join(' · ');
  }

  function diskFoot(disk) {
    if (!disk.total_gb) { return 'дані недоступні'; }
    return fmtGb(disk.free_gb) + ' вільно з ' + fmtGb(disk.total_gb);
  }

  function diskDetail(disk) {
    if (!disk.total_gb) { return 'дані недоступні'; }
    var used = Number(disk.total_gb) - Number(disk.free_gb || 0);
    return 'зайнято ' + fmtGb(used) + ' · ' + loadWord(disk.percent);
  }

  function batteryFoot(battery) {
    if (!battery) { return 'батарею не знайдено'; }
    return battery.plugged ? 'заряджається' : 'від батареї';
  }

  function batteryDetail(battery) {
    if (!battery) { return 'схоже, це стаціонарний ПК'; }
    return battery.plugged ? 'живлення від мережі' : 'автономна робота';
  }

  function userLabel() {
    var user = state.user;
    if (!user) { return '—'; }
    var name = user.first_name || user.username || ('ID ' + user.id);
    if (user.username && user.first_name) { return name + ' @' + user.username; }
    return name;
  }

  function renderProcesses(list) {
    var holder = $('proc-list');
    if (!holder) { return; }
    var procs = Array.isArray(list) ? list : [];

    holder.textContent = '';
    if (!procs.length) {
      var empty = document.createElement('li');
      empty.className = 'procs__empty muted';
      empty.textContent = 'дані недоступні';
      holder.appendChild(empty);
      return;
    }

    var max = 1;
    procs.forEach(function (proc) {
      var share = Number(proc && proc.memory_percent) || 0;
      if (share > max) { max = share; }
    });
    var scale = Math.max(max, 10);

    procs.forEach(function (proc) {
      var share = Number(proc && proc.memory_percent) || 0;
      var row = document.createElement('li');

      var name = document.createElement('span');
      name.className = 'procs__name';
      name.textContent = (proc && proc.name) ? proc.name : '?';

      var value = document.createElement('span');
      value.className = 'procs__val';
      value.textContent = share.toFixed(1) + '% RAM';

      var track = document.createElement('span');
      track.className = 'procs__track';
      var fill = document.createElement('i');
      fill.style.width = clamp((share / scale) * 100, 3, 100) + '%';
      track.appendChild(fill);

      row.appendChild(name);
      row.appendChild(value);
      row.appendChild(track);
      holder.appendChild(row);
    });
  }

  function render(status) {
    var cpu = status.cpu || {};
    var mem = status.memory || {};
    var disk = status.disk || {};
    var swap = status.swap || {};
    var battery = status.battery || null;

    setText('bot-version', shortVersion(status.bot_version));
    setText('pc-name', status.pc_name || 'ControlPC');
    setText('pc-subtitle', subtitleOf(status));
    setText('info-uptime', status.uptime || '—');

    applyMetric('cpu', cpu.percent, cpuFoot(cpu), cpuDetail(cpu), false);
    applyMetric('ram', mem.percent, ramFoot(mem), ramDetail(mem, swap), false);
    applyMetric('disk', disk.percent, diskFoot(disk), diskDetail(disk), false);
    applyMetric('bat', battery ? battery.percent : null,
      batteryFoot(battery), batteryDetail(battery), true);

    setText('info-pc', status.pc_name || '—');
    setText('info-platform', status.platform || '—');
    setText('info-bot', status.bot_version || '—');
    setText('info-api', status.api_version || '—');
    setText('info-timestamp', status.timestamp || '—');
    setText('foot-user', userLabel());

    renderProcesses(status.top_processes);

    var syncedAt = status.time ? Number(status.time) * 1000 : Date.now();
    setText('updated-at', fmtClock(new Date(syncedAt)));
    state.nextAt = Date.now() + REFRESH_MS;
    setOnline(true);
    tick();
  }

  // ==========================================
  // ЕТАП 3: РОЗДІЛИ КЕРУВАННЯ
  // ==========================================
  function errText(res, fallback) {
    if (res && res.data && res.data.error) { return res.data.error; }
    if (res && res.status) { return fallback + ' (код ' + res.status + ')'; }
    return fallback;
  }

  function failAction(res, fallback) {
    notifyHaptic('error');
    toast(errText(res, fallback));
  }

  function showBackButton(show) {
    try {
      if (!tg || !tg.BackButton) { return; }
      if (show) { tg.BackButton.show(); } else { tg.BackButton.hide(); }
    } catch (e) { /* старі версії Telegram */ }
  }

  function openSheet(pane) {
    var sheet = $('sheet');
    if (!sheet || !PANE_TITLES[pane]) { return; }
    state.pane = pane;
    setText('sheet-title', PANE_TITLES[pane]);
    each('#sheet [data-pane]', function (node) {
      node.classList.toggle('hidden', node.getAttribute('data-pane') !== pane);
    });
    sheet.classList.remove('hidden');
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () { sheet.classList.add('is-open'); });
    });
    showBackButton(true);
    selectionHaptic();
    if (pane === 'apps') { loadProcesses(state.procList.length > 0); }
    if (pane === 'camera') { checkCameraHint(); }
  }

  function closeSheet() {
    var sheet = $('sheet');
    state.pane = '';
    showBackButton(false);
    if (!sheet || sheet.classList.contains('hidden')) { return; }
    sheet.classList.remove('is-open');
    window.setTimeout(function () {
      if (!state.pane) { sheet.classList.add('hidden'); }
    }, 320);
  }

  // --- вікно підтвердження ---
  function openConfirm(options) {
    var box = $('confirm');
    if (!box) { options.onResolve(false); return; }
    state.confirm = options;
    var title = $('confirm-title');
    var text = $('confirm-text');
    var yes = $('confirm-yes');
    var check = $('confirm-check');
    if (title) { title.textContent = options.title || 'Підтверди дію'; }
    if (text) { text.textContent = options.text || ''; }
    if (yes) { yes.textContent = options.label || 'Виконати'; yes.disabled = true; }
    if (check) { check.checked = false; }
    box.classList.remove('hidden');
    haptic('medium');
    notifyHaptic('warning');
  }

  function closeConfirm() {
    var box = $('confirm');
    if (box) { box.classList.add('hidden'); }
    state.confirm = null;
  }

  function resolveConfirm(ok) {
    var ctx = state.confirm;
    if (!ctx) { return; }
    closeConfirm();
    if (typeof ctx.onResolve === 'function') { ctx.onResolve(ok); }
  }

  // --- можливості ПК ---
  async function loadCapabilities() {
    try {
      var res = await api('/api/actions');
      if (!res.ok || !res.data.ok) { return; }
      state.capabilities = res.data.actions || {};
      applyCapabilities();
    } catch (e) { /* дашборд працює й без цього */ }
  }

  function applyCapabilities() {
    var caps = state.capabilities || {};
    var pairs = [['power', 'power'], ['media', 'media'], ['apps', 'processes'], ['camera', 'camera']];
    pairs.forEach(function (pair) {
      var key = pair[0];
      var enabled = caps[pair[1]] !== false;
      each('[data-nav="' + key + '"]', function (node) {
        node.classList.toggle('is-disabled', !enabled);
        node.setAttribute('aria-disabled', enabled ? 'false' : 'true');
      });
      var hint = $('hint-' + key);
      if (hint && !enabled) { hint.textContent = 'недоступно'; }
    });
    if (caps.camera === false) {
      var camBtn = $('cam-btn');
      if (camBtn) { camBtn.disabled = true; camBtn.textContent = 'Камера недоступна'; }
      setText('cam-meta', 'на ПК немає модуля opencv');
    }
    setText('control-badge', caps.windows === false ? 'обмежено' : 'Етап 3');
  }

  function checkCameraHint() {
    var caps = state.capabilities || {};
    if (caps.camera === false || state.camUrl) { return; }
    setText('cam-meta', 'камера готова до знімка');
  }

  // --- живлення ---
  async function requestPower(action) {
    if (state.actionBusy) { return; }
    var delayNode = $('power-delay');
    var delay = delayNode ? parseInt(delayNode.value, 10) : 15;
    if (!isNum(delay)) { delay = 15; }
    haptic('light');
    state.actionBusy = true;
    try {
      var res = await api('/api/power', { method: 'POST', body: { action: action, delay: delay } });
      if (!res.ok || !res.data.ok) { failAction(res, 'Дія живлення не виконалася'); return; }
      var data = res.data;
      if (!data.needs_confirm) {
        notifyHaptic('success');
        toast(data.text || 'Готово');
        return;
      }
      openConfirm({
        title: POWER_TITLES[action] || 'Підтверди дію',
        text: data.text || '',
        label: POWER_BUTTONS[action] || 'Виконати',
        onResolve: function (ok) {
          if (!ok) { haptic('soft'); return; }
          executePower(action, delay, data.token);
        }
      });
    } catch (e) {
      notifyHaptic('error');
      toast('Немає зв\'язку з ПК');
    } finally {
      state.actionBusy = false;
    }
  }

  async function executePower(action, delay, token) {
    haptic('heavy');
    try {
      var res = await api('/api/power', {
        method: 'POST',
        body: { action: action, delay: delay, confirm: token }
      });
      if (!res.ok || !res.data.ok) { failAction(res, 'Дія не виконалася'); return; }
      notifyHaptic('success');
      toast(res.data.text || 'Готово');
      if (action === 'shutdown' || action === 'reboot') { closeSheet(); }
    } catch (e) {
      notifyHaptic('error');
      toast('Немає зв\'язку з ПК');
    }
  }

  async function cancelPower() {
    haptic('medium');
    try {
      var res = await api('/api/power', { method: 'POST', body: { action: 'cancel' } });
      if (!res.ok || !res.data.ok) { failAction(res, 'Не вдалося скасувати'); return; }
      notifyHaptic('success');
      toast(res.data.text || 'Скасовано');
    } catch (e) {
      notifyHaptic('error');
      toast('Немає зв\'язку з ПК');
    }
  }

  // --- медіа ---
  async function sendMedia(action, node) {
    if (!action) { return; }
    haptic('light');
    if (node) { node.disabled = true; }
    try {
      var res = await api('/api/media', { method: 'POST', body: { action: action, steps: 2 } });
      if (!res.ok || !res.data.ok) { failAction(res, 'Медіа-дія не виконалася'); return; }
      notifyHaptic('success');
      toast(res.data.text || 'Виконано');
    } catch (e) {
      notifyHaptic('error');
      toast('Немає зв\'язку з ПК');
    } finally {
      if (node) { node.disabled = false; }
    }
  }

  // --- процеси (панель «Додатки») ---
  async function loadProcesses(silent) {
    var btn = $('proc-refresh');
    if (btn) { btn.classList.add('is-spinning'); btn.disabled = true; }
    if (!silent) { setText('proc-note', 'завантажую список…'); }
    try {
      var res = await api('/api/processes?limit=40');
      if (!res.ok || !res.data.ok) {
        state.procList = [];
        renderProcManager();
        setText('proc-note', errText(res, 'Список недоступний'));
        return;
      }
      state.procList = Array.isArray(res.data.processes) ? res.data.processes : [];
      state.procLoadedAt = Date.now();
      renderProcManager();
    } catch (e) {
      state.procList = [];
      renderProcManager();
      setText('proc-note', 'немає зв\'язку з ПК');
    } finally {
      if (btn) { btn.classList.remove('is-spinning'); btn.disabled = false; }
    }
  }

  function renderProcManager() {
    var holder = $('proc-manager');
    if (!holder) { return; }
    var needle = (state.procQuery || '').toLowerCase();
    var source = state.procList || [];
    var items = needle ? source.filter(function (proc) {
      return String(proc.name || '').toLowerCase().indexOf(needle) >= 0;
    }) : source.slice();

    holder.textContent = '';
    if (!items.length) {
      var empty = document.createElement('li');
      empty.className = 'proc-list__empty muted';
      empty.textContent = source.length ? 'Нічого не знайдено' : 'Список порожній';
      holder.appendChild(empty);
    } else {
      items.forEach(function (proc) { holder.appendChild(buildProcRow(proc)); });
    }
    var note = source.length
      ? ('показано ' + items.length + ' з ' + source.length + ' · за RAM')
      : 'список недоступний';
    setText('proc-note', note);
  }

  function buildProcRow(proc) {
    var row = document.createElement('li');
    row.className = 'proc-row';

    var main = document.createElement('span');
    main.className = 'proc-row__main';

    var name = document.createElement('span');
    name.className = 'proc-row__name';
    name.textContent = proc.name || '?';

    var meta = document.createElement('span');
    meta.className = 'proc-row__meta';
    var parts = ['PID ' + proc.pid, (Number(proc.memory_percent) || 0).toFixed(1) + '% RAM'];
    if (proc.status) { parts.push(PROC_STATUS[proc.status] || proc.status); }
    if (proc.user) { parts.push(proc.user); }
    meta.textContent = parts.join(' · ');

    main.appendChild(name);
    main.appendChild(meta);

    var kill = document.createElement('button');
    kill.type = 'button';
    kill.className = 'proc-row__kill';
    if (proc.protected) {
      kill.textContent = 'захист';
      kill.disabled = true;
      kill.title = proc.protected_reason || 'Системний процес';
    } else {
      kill.textContent = 'Завершити';
      kill.addEventListener('click', function () { requestKill(proc, row); });
    }

    row.appendChild(main);
    row.appendChild(kill);
    return row;
  }

  async function requestKill(proc, row) {
    haptic('medium');
    if (row) { row.classList.add('is-busy'); }
    try {
      var res = await api('/api/process/kill', { method: 'POST', body: { pid: proc.pid } });
      if (!res.ok || !res.data.ok) { failAction(res, 'Не вдалося завершити процес'); return; }
      var data = res.data;
      openConfirm({
        title: 'Завершити процес',
        text: data.text || ('Завершити «' + (data.name || proc.name) + '»?'),
        label: 'Завершити',
        onResolve: function (ok) {
          if (!ok) { haptic('soft'); return; }
          executeKill(data.pid, data.token);
        }
      });
    } catch (e) {
      notifyHaptic('error');
      toast('Немає зв\'язку з ПК');
    } finally {
      if (row) { row.classList.remove('is-busy'); }
    }
  }

  async function executeKill(pid, token) {
    haptic('heavy');
    try {
      var res = await api('/api/process/kill', {
        method: 'POST',
        body: { pid: pid, confirm: token }
      });
      if (!res.ok || !res.data.ok) {
        notifyHaptic('error');
        toast(errText(res, 'Процес не завершено'));
        loadProcesses(true);
        return;
      }
      notifyHaptic('success');
      toast(res.data.text || 'Процес завершено');
      state.procList = (state.procList || []).filter(function (item) { return item.pid !== pid; });
      renderProcManager();
      loadProcesses(true);
    } catch (e) {
      notifyHaptic('error');
      toast('Немає зв\'язку з ПК');
    }
  }

  // --- камера ---
  function setCameraBusy(busy) {
    var btn = $('cam-btn');
    if (!btn) { return; }
    var caps = state.capabilities || {};
    if (caps.camera === false) { return; }
    btn.disabled = busy;
    btn.textContent = busy ? 'Знімаю…' : 'Зробити знімок';
  }

  async function takeSnapshot() {
    haptic('medium');
    setCameraBusy(true);
    setText('cam-meta', 'знімаю кадр…');
    try {
      var headers = { 'Accept': 'image/jpeg' };
      if (state.token) { headers['X-MiniApp-Token'] = state.token; }
      var res = await fetch('/api/camera/snapshot', {
        headers: headers,
        cache: 'no-store',
        credentials: 'same-origin'
      });
      if (!res.ok) {
        var data = {};
        try { data = await res.json(); } catch (e) { data = {}; }
        throw { text: data.error || ('Камера недоступна (код ' + res.status + ')') };
      }
      var blob = await res.blob();
      var url = URL.createObjectURL(blob);
      if (state.camUrl) { URL.revokeObjectURL(state.camUrl); }
      state.camUrl = url;

      var img = $('cam-img');
      if (img) {
        img.src = url;
        img.classList.remove('hidden');
        img.onload = function () {
          setText('cam-size', img.naturalWidth + '×' + img.naturalHeight);
          var size = $('cam-size');
          if (size) { size.classList.remove('hidden'); }
        };
      }
      var empty = $('cam-empty');
      if (empty) { empty.classList.add('hidden'); }

      var flash = $('cam-flash');
      if (flash) {
        flash.classList.remove('is-active');
        void flash.offsetWidth;
        flash.classList.add('is-active');
      }
      setText('cam-meta', 'знімок о ' + fmtClock(new Date()));
      notifyHaptic('success');
    } catch (e) {
      notifyHaptic('error');
      toast((e && e.text) || 'Не вдалося зробити знімок');
      setText('cam-meta', 'камера недоступна');
    } finally {
      setCameraBusy(false);
    }
  }

  // --- таймери ---
  function tick() {
    var el = $('next-refresh');
    if (!el) { return; }
    if (state.busy) {
      el.textContent = 'оновлюю дані…';
      return;
    }
    if (!state.online) {
      el.textContent = 'немає зв\'язку · повторюю автоматично';
      return;
    }
    var left = state.nextAt ? Math.max(0, Math.round((state.nextAt - Date.now()) / 1000)) : 0;
    el.textContent = 'автооновлення через ' + left + ' с';
  }

  function startTicker() {
    if (state.ticker) { clearInterval(state.ticker); }
    state.ticker = setInterval(tick, 1000);
  }

  function startAutoRefresh() {
    if (state.timer) { clearInterval(state.timer); }
    state.timer = setInterval(function () {
      if (document.hidden) { return; }
      refresh(false);
    }, REFRESH_MS);
    state.nextAt = Date.now() + REFRESH_MS;
  }

  // --- оновлення даних ---
  async function refresh(manual) {
    if (state.busy) { return; }
    state.busy = true;
    setBusy(true);
    if (manual) { haptic('light'); }
    var wasOffline = !state.online;
    try {
      if (!state.token) { await authenticate(); }
      await loadStatus(true);
      showScreen('main');
      state.offlineNotified = false;
      if (manual) {
        notifyHaptic('success');
        toast('Дані оновлено');
      } else if (wasOffline) {
        toast('Зв\'язок з ПК відновлено');
      }
    } catch (err) {
      setOnline(false);
      if (manual) {
        showError(errorTitle(err), errorText(err));
      } else if (!state.offlineNotified) {
        state.offlineNotified = true;
        toast('Немає зв\'язку з ПК — повторюю спробу');
      }
    } finally {
      state.busy = false;
      setBusy(false);
      state.nextAt = Date.now() + REFRESH_MS;
      tick();
    }
  }

  async function boot() {
    showScreen('loading');
    setOnline(false);
    try {
      if (tg) {
        tg.ready();
        tg.expand();
      }
      applyTheme();
      syncChrome();
      if (!state.token) { await authenticate(); }
      await loadCapabilities();
      await loadStatus(true);
      showScreen('main');
      startAutoRefresh();
      startTicker();
    } catch (err) {
      if (err && typeof err === 'object' && err.title) {
        showError(err.title, err.text || '');
      } else {
        showError('Немає зв\'язку', 'Сервер Mini App не відповідає. Перевір, чи запущений бот на ПК.');
      }
    }
  }

  function bindControlUi() {
    var closeBtn = $('sheet-close');
    if (closeBtn) {
      closeBtn.addEventListener('click', function () { haptic('soft'); closeSheet(); });
    }
    var scrim = $('sheet-scrim');
    if (scrim) {
      scrim.addEventListener('click', function () { haptic('soft'); closeSheet(); });
    }

    each('[data-power]', function (button) {
      button.addEventListener('click', function () {
        requestPower(button.getAttribute('data-power'));
      });
    });

    each('[data-media]', function (button) {
      button.addEventListener('click', function () {
        sendMedia(button.getAttribute('data-media'), button);
      });
    });

    var cancelBtn = $('power-cancel');
    if (cancelBtn) { cancelBtn.addEventListener('click', cancelPower); }

    var procRefresh = $('proc-refresh');
    if (procRefresh) {
      procRefresh.addEventListener('click', function () {
        haptic('light');
        loadProcesses(false);
      });
    }

    var search = $('proc-search');
    if (search) {
      var searchTimer = null;
      search.addEventListener('input', function () {
        state.procQuery = search.value || '';
        if (searchTimer) { window.clearTimeout(searchTimer); }
        searchTimer = window.setTimeout(function () {
          renderProcManager();
          selectionHaptic();
        }, 160);
      });
    }

    var camBtn = $('cam-btn');
    if (camBtn) { camBtn.addEventListener('click', takeSnapshot); }

    var check = $('confirm-check');
    if (check) {
      check.addEventListener('change', function () {
        var yes = $('confirm-yes');
        if (yes) { yes.disabled = !check.checked; }
        selectionHaptic();
      });
    }

    var noBtn = $('confirm-no');
    if (noBtn) {
      noBtn.addEventListener('click', function () { haptic('soft'); resolveConfirm(false); });
    }

    var yesBtn = $('confirm-yes');
    if (yesBtn) {
      yesBtn.addEventListener('click', function () {
        if (yesBtn.disabled) { return; }
        resolveConfirm(true);
      });
    }

    document.addEventListener('keydown', function (event) {
      if (event.key !== 'Escape') { return; }
      if (state.confirm) { resolveConfirm(false); return; }
      if (state.pane) { closeSheet(); }
    });

    if (tg && tg.BackButton && typeof tg.BackButton.onClick === 'function') {
      try {
        tg.BackButton.onClick(function () { closeSheet(); });
      } catch (e) { /* старі версії Telegram */ }
    }
  }

  // --- події ---
  function bindUi() {
    var refreshBtn = $('refresh-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', function () { refresh(true); });
    }

    var retryBtn = $('retry-btn');
    if (retryBtn) {
      retryBtn.addEventListener('click', function () {
        haptic('medium');
        boot();
      });
    }

    each('[data-metric]', function (card) {
      card.addEventListener('click', function () {
        var opened = card.classList.toggle('is-open');
        haptic(opened ? 'light' : 'soft');
        selectionHaptic();
      });
    });

    each('[data-nav]', function (button) {
      button.addEventListener('click', function () {
        var pane = button.getAttribute('data-pane');
        var label = button.getAttribute('data-nav-label') || 'Розділ';
        if (!pane) {
          haptic('medium');
          notifyHaptic('warning');
          toast('«' + label + '» буде в наступному оновленні');
          return;
        }
        if (button.classList.contains('is-disabled')) {
          notifyHaptic('warning');
          toast('«' + label + '» недоступно на цьому ПК');
          return;
        }
        openSheet(pane);
      });
    });

    bindControlUi();

    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { return; }
      state.nextAt = Date.now() + REFRESH_MS;
      tick();
      refresh(false);
    });

    if (tg && typeof tg.onEvent === 'function') {
      try {
        tg.onEvent('themeChanged', function () {
          applyTheme();
          syncChrome();
        });
      } catch (e) { /* старі версії Telegram */ }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindUi();
    boot();
  });
})();
