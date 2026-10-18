(function () {
  var STORAGE_KEY = "vremya-theme";
  var root = document.documentElement;

  function getTheme() {
    return root.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function setTheme(theme) {
    root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (_e) {
      /* ignore */
    }
    var btn = document.querySelector("[data-theme-toggle]");
    if (btn) {
      btn.setAttribute(
        "aria-label",
        theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему"
      );
    }
  }

  function setCircleVars(x, y) {
    var maxX = Math.max(x, window.innerWidth - x);
    var maxY = Math.max(y, window.innerHeight - y);
    var radius = Math.hypot(maxX, maxY);
    root.style.setProperty("--theme-x", x + "px");
    root.style.setProperty("--theme-y", y + "px");
    root.style.setProperty("--theme-r", radius + "px");
  }

  function toggleTheme(event) {
    var next = getTheme() === "dark" ? "light" : "dark";
    var x = event && typeof event.clientX === "number" ? event.clientX : window.innerWidth - 40;
    var y = event && typeof event.clientY === "number" ? event.clientY : 40;
    setCircleVars(x, y);

    var reduceMotion =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (reduceMotion || !document.startViewTransition) {
      setTheme(next);
      return;
    }

    // Как в Telegram: при переходе на тёмную тема «сжимается» круг,
    // на светлую — раскрывается из кнопки.
    var goingDark = next === "dark";
    root.classList.remove("theme-circle-in", "theme-circle-out");
    root.classList.add(goingDark ? "theme-circle-out" : "theme-circle-in");

    var transition = document.startViewTransition(function () {
      setTheme(next);
    });

    transition.finished.finally(function () {
      root.classList.remove("theme-circle-in", "theme-circle-out");
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var btn = document.querySelector("[data-theme-toggle]");
    if (btn) {
      btn.addEventListener("click", toggleTheme);
      btn.setAttribute(
        "aria-label",
        getTheme() === "dark" ? "Включить светлую тему" : "Включить тёмную тему"
      );
    }

    var navToggle = document.querySelector("[data-nav-toggle]");
    var nav = document.querySelector("[data-nav]");
    if (navToggle && nav) {
      navToggle.addEventListener("click", function () {
        var open = nav.classList.toggle("is-open");
        navToggle.setAttribute("aria-expanded", open ? "true" : "false");
      });
    }
  });
})();
