/* Aurum — общий скрипт сайта. Без сборки и зависимостей. */
(function () {
  "use strict";

  var TOKEN_KEY = "aurum_token";
  var cfg = window.AURUM || {};

  // ------------------------------------------------------------------ утилиты

  function token() {
    try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
  }
  function setToken(value) {
    try {
      if (value) localStorage.setItem(TOKEN_KEY, value);
      else localStorage.removeItem(TOKEN_KEY);
    } catch (e) { /* приватный режим — просто живём без сохранения */ }
  }

  function api(path, options) {
    options = options || {};
    var headers = { Accept: "application/json" };
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (options.auth !== false && token()) headers.Authorization = "Bearer " + token();

    return fetch(path, {
      method: options.method || "GET",
      headers: headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body)
    }).then(function (response) {
      return response.text().then(function (raw) {
        var data = null;
        try { data = raw ? JSON.parse(raw) : null; } catch (e) { data = null; }
        if (!response.ok) {
          var detail = data && data.detail;
          if (Array.isArray(detail)) detail = detail[0] && (detail[0].msg || detail[0]);
          var error = new Error(detail || "Ошибка " + response.status);
          error.status = response.status;
          throw error;
        }
        return data;
      });
    });
  }

  function $(selector, root) { return (root || document).querySelector(selector); }
  function $all(selector, root) { return Array.prototype.slice.call((root || document).querySelectorAll(selector)); }

  function showError(node, message) {
    if (!node) return;
    node.textContent = message;
    node.hidden = !message;
  }

  function money(amount) {
    return String(Math.round(amount / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, " ") + " ₽";
  }

  function formatDate(value) {
    if (!value) return "—";
    var date = new Date(value);
    if (isNaN(date.getTime())) return "—";
    return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "long", year: "numeric" });
  }

  function planById(id) {
    var plans = cfg.plans || [];
    for (var i = 0; i < plans.length; i++) if (plans[i].id === id) return plans[i];
    return null;
  }

  function nextUrl(fallback) {
    var params = new URLSearchParams(location.search);
    var next = params.get("next");
    if (next && next.charAt(0) === "/") return next;
    return fallback || "/account";
  }

  function goLogin() {
    var here = location.pathname + location.search;
    location.replace("/login?next=" + encodeURIComponent(here));
  }

  // -------------------------------------------------------------- шапка сайта

  function updateNav() {
    var signedIn = Boolean(token());
    $all('[data-auth="in"]').forEach(function (node) { node.hidden = !signedIn; });
    $all('[data-auth="out"]').forEach(function (node) { node.hidden = signedIn; });
  }

  // ------------------------------------------------------------------- формы

  function bindLogin() {
    var form = $('[data-form="login"]');
    if (!form) return;
    var error = $('[data-error]', form);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = $('button[type="submit"]', form);
      var username = (form.username.value || "").trim().toLowerCase();
      var password = form.password.value || "";
      showError(error, "");
      if (!username || !password) { showError(error, "Заполните логин и пароль"); return; }

      button.disabled = true;
      api("/api/login", { method: "POST", auth: false, body: { username: username, password: password } })
        .then(function (data) {
          setToken(data.access_token);
          location.replace(nextUrl("/account"));
        })
        .catch(function (err) { showError(error, err.message); })
        .finally(function () { button.disabled = false; });
    });
  }

  function bindRegister() {
    var form = $('[data-form="register"]');
    if (!form) return;
    var error = $('[data-error]', form);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      var button = $('button[type="submit"]', form);
      var username = (form.username.value || "").trim().toLowerCase();
      var password = form.password.value || "";
      var repeat = form.password2.value || "";
      showError(error, "");

      if (password.length < 8) { showError(error, "Пароль должен быть не короче 8 символов"); return; }
      if (password !== repeat) { showError(error, "Пароли не совпадают"); return; }

      button.disabled = true;
      api("/api/register", { method: "POST", auth: false, body: { username: username, password: password } })
        .then(function (data) {
          setToken(data.access_token);
          location.replace("/account");
        })
        .catch(function (err) { showError(error, err.message); })
        .finally(function () { button.disabled = false; });
    });
  }

  // ---------------------------------------------------------------- кабинет

  function bindAccount() {
    var page = $(".page-account");
    if (!page) return;
    if (!token()) { goLogin(); return; }

    var logout = $("[data-logout]");
    if (logout) {
      logout.addEventListener("click", function () {
        setToken("");
        location.replace("/");
      });
    }

    api("/api/me")
      .then(function (data) {
        var user = data.user || {};
        var sub = data.subscription || {};

        $all("[data-username]").forEach(function (node) { node.textContent = user.username || "—"; });
        $all("[data-hwid]").forEach(function (node) {
          node.textContent = user.hwid_bound ? "привязано" : "не привязано (привяжется при входе в лаунчере)";
        });

        var status = $("[data-sub-status]");
        if (status) {
          status.textContent = sub.active ? "активна" : "не активна";
          status.classList.toggle("active", Boolean(sub.active));
          status.classList.toggle("inactive", !sub.active);
        }
        var plan = $("[data-sub-plan]");
        if (plan) plan.textContent = sub.active ? "тариф " + (sub.plan || "premium") : "";
        var note = $("[data-sub-note]");
        if (note) {
          var text = (user.note || "").trim();
          note.textContent = text;
          note.hidden = !text;
        }
        var days = $("[data-sub-days]");
        if (days) days.textContent = sub.active ? sub.days_left + " дн." : "0 дн.";
        var expires = $("[data-sub-expires]");
        if (expires) expires.textContent = sub.active ? formatDate(sub.expires_at) : "—";
      })
      .catch(function (err) {
        if (err.status === 401) { setToken(""); goLogin(); return; }
        showError($("[data-error]"), err.message);
      });

    api("/api/billing/history")
      .then(function (data) {
        var body = $("[data-history]");
        if (!body) return;
        var rows = data.payments || [];
        if (!rows.length) {
          body.innerHTML = '<tr><td colspan="4" class="muted">Платежей пока не было</td></tr>';
          return;
        }
        var labels = { succeeded: "оплачен", pending: "ожидает", canceled: "отменён", failed: "ошибка" };
        body.innerHTML = rows.map(function (row) {
          var plan = planById(row.plan_id);
          return "<tr><td>" + formatDate(row.created_at) + "</td><td>" +
            (plan ? plan.title : row.days + " дн.") + "</td><td>" + money(row.amount) +
            "</td><td>" + (labels[row.status] || row.status) + "</td></tr>";
        }).join("");
      })
      .catch(function () { /* история не критична */ });
  }

  // ----------------------------------------------------------------- покупка

  function bindBuy() {
    var page = $(".page-buy");
    if (!page) return;

    var params = new URLSearchParams(location.search);
    var plan = planById(params.get("plan") || "quarter");
    if (!plan) { location.replace("/#pricing"); return; }

    var title = $("[data-plan-title]");
    var days = $("[data-plan-days]");
    var price = $("[data-plan-price]");
    if (title) title.textContent = plan.title;
    if (days) days.textContent = plan.days + " дней";
    if (price) price.textContent = plan.price_label;

    var pay = $("[data-pay]");
    if (!pay) return;
    var error = $("[data-error]");

    pay.addEventListener("click", function () {
      if (!token()) {
        location.href = "/login?next=" + encodeURIComponent("/buy?plan=" + plan.id);
        return;
      }
      showError(error, "");
      pay.disabled = true;
      pay.textContent = "Создаём счёт…";

      api("/api/billing/checkout", { method: "POST", body: { plan_id: plan.id } })
        .then(function (data) {
          if (!data.confirmation_url) throw new Error("Платёжный сервис не вернул ссылку");
          location.href = data.confirmation_url;
        })
        .catch(function (err) {
          if (err.status === 401) {
            setToken("");
            location.href = "/login?next=" + encodeURIComponent("/buy?plan=" + plan.id);
            return;
          }
          showError(error, err.message);
          pay.disabled = false;
          pay.textContent = "Перейти к оплате";
        });
    });
  }

  // --------------------------------------------------------- экран после оплаты

  function bindSuccess() {
    var page = $(".page-buy");
    var title = $("[data-title]");
    var icon = $("[data-icon]");
    var text = $("[data-text]");
    var account = $("[data-account]");
    var retry = $("[data-retry]");
    if (!title || !$("[data-icon]") || !/success/.test(location.pathname)) return;

    var params = new URLSearchParams(location.search);
    var id = params.get("payment");
    if (!id || !token()) { location.replace("/account"); return; }

    var tries = 0;

    function finish(ok, message) {
      icon.textContent = ok ? "✓" : "!";
      icon.classList.add(ok ? "ok" : "bad");
      title.textContent = ok ? "Подписка активна" : "Оплата не подтверждена";
      text.textContent = message;
      if (account) account.hidden = false;
      if (retry) retry.hidden = false;
    }

    function poll() {
      tries += 1;
      api("/api/billing/payments/" + encodeURIComponent(id))
        .then(function (data) {
          var payment = data.payment || {};
          if (payment.status === "succeeded") {
            var sub = data.subscription || {};
            finish(true, "Доступ открыт до " + formatDate(sub.expires_at) + ". Можно запускать лаунчер.");
            return;
          }
          if (payment.status === "canceled" || payment.status === "failed") {
            finish(false, "Платёж отменён. Деньги не списаны — можно попробовать снова.");
            return;
          }
          if (tries > 40) {
            finish(false, "Оплата ещё обрабатывается. Проверьте статус в личном кабинете через минуту.");
            return;
          }
          text.textContent = "Проверяем оплату… (" + tries + ")";
          setTimeout(poll, 3000);
        })
        .catch(function (err) {
          if (err.status === 401) { setToken(""); goLogin(); return; }
          finish(false, err.message);
        });
    }

    poll();
  }

  // -------------------------------------------------------------------- старт

  function init() {
    updateNav();
    bindLogin();
    bindRegister();
    bindAccount();
    bindBuy();
    bindSuccess();

    $all("[data-year]").forEach(function (node) { node.textContent = new Date().getFullYear(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
