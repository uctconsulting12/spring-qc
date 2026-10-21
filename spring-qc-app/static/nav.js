/* Spring QC — shared navbar + theme toggle + info tooltips.
   Include on admin / monitor / reports (the control pages).
   Pages add their own status chips into #app-nav-right if needed. */
(function () {
    'use strict';
    var THEME_KEY = 'spring_qc_theme';

    var ROUTES = [
        { href: '/admin', label: 'Admin' },
        { href: '/monitor', label: 'Monitor' },
        { href: '/reports', label: 'Reports' }
    ];

    function currentPath() {
        var p = location.pathname.replace(/\/+$/, '');
        return p === '' ? '/' : p;
    }

    function buildNav() {
        var mount = document.getElementById('app-nav');
        if (!mount) return;
        var path = currentPath();
        var links = ROUTES.map(function (r) {
            var active = path === r.href;
            return '<a class="app-nav__link' + (active ? ' is-active' : '') + '" href="' + r.href + '"' +
                (active ? ' aria-current="page"' : '') + '>' + r.label + '</a>';
        }).join('');
        mount.className = 'app-nav';
        mount.innerHTML =
            '<a class="app-nav__brand" href="/">' +
                '<span class="app-nav__mark">◆</span><span class="app-nav__name">Spring QC</span>' +
            '</a>' +
            '<nav class="app-nav__links">' + links + '</nav>' +
            '<div class="app-nav__right" id="app-nav-right">' +
                '<button class="btn btn--ghost btn--icon" id="app-nav-theme" title="Toggle light / dark" aria-label="Toggle theme">🌙</button>' +
            '</div>';
    }

    function applyTheme(t) {
        var root = document.documentElement;
        if (t === 'dark' || t === 'light') root.setAttribute('data-theme', t);
        else root.removeAttribute('data-theme');
        var dark = t === 'dark' || (!t && window.matchMedia('(prefers-color-scheme: dark)').matches);
        var btn = document.getElementById('app-nav-theme');
        if (btn) btn.textContent = dark ? '☀️' : '🌙';
        document.querySelectorAll('[data-theme-label]').forEach(function (el) {
            el.textContent = dark ? 'Light mode' : 'Dark mode';
        });
    }

    function wireTheme() {
        var stored = null;
        try { stored = localStorage.getItem(THEME_KEY); } catch (e) {}
        applyTheme(stored);
        document.addEventListener('click', function (e) {
            var t = e.target.closest('#app-nav-theme, [data-theme-toggle]');
            if (!t) return;
            var cur = document.documentElement.getAttribute('data-theme');
            var dark = cur === 'dark' || (!cur && window.matchMedia('(prefers-color-scheme: dark)').matches);
            var next = dark ? 'light' : 'dark';
            try { localStorage.setItem(THEME_KEY, next); } catch (err) {}
            applyTheme(next);
        });
    }

    function wireTooltips() {
        var tip = document.getElementById('tip');
        if (!tip) {
            tip = document.createElement('div');
            tip.id = 'tip';
            document.body.appendChild(tip);
        }
        document.addEventListener('mouseover', function (e) {
            var d = e.target.closest('.info-dot');
            if (!d) return;
            tip.textContent = d.getAttribute('data-tip') || '';
            tip.style.display = 'block';
            var r = d.getBoundingClientRect();
            tip.style.left = Math.max(8, Math.min(r.left - 8, window.innerWidth - 280)) + 'px';
            tip.style.top = (r.bottom + 8) + 'px';
        });
        document.addEventListener('mouseout', function (e) {
            if (e.target.closest('.info-dot')) tip.style.display = 'none';
        });
    }

    function init() {
        buildNav();
        wireTheme();
        wireTooltips();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.SpringQC = { applyTheme: applyTheme };
})();
