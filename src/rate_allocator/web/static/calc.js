/* Tasas MX — calculator UI logic. Vanilla JS, no build step. */
(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);

  const els = {
    slider: $('#amount-slider'),
    input: $('#amount-input'),
    list: $('#inst-list'),
    toggleAll: $('#toggle-all'),
    selectedCount: $('#selected-count'),
    cta: $('#calc-btn'),
    placeholder: $('#results-placeholder'),
    results: $('#results'),
    rTotal: $('#r-total'),
    rRate: $('#r-rate'),
    rReturn: $('#r-return'),
    planCards: $('#plan-cards'),
    warning: $('#result-warning'),
    chartCanvas: $('#alloc-chart'),
    deltaBanner: $('#delta-banner'),
    rDelta: $('#r-delta'),
    rTradRate: $('#r-trad-rate'),
    rTradReturn: $('#r-trad-return'),
    staleBanner: $('#stale-banner'),
    staleRecalc: $('#stale-recalc'),
    noticiasList: $('#noticias-list'),
  };

  const state = {
    institutions: [],
    selected: new Set(),
    chart: null,
    hasResults: false,
  };

  // ── number formatting helpers ─────────────────────────────────────────────

  const fmtMXN = (n) => '$' + Math.round(n).toLocaleString('es-MX') + ' MXN';
  const fmtNumber = (n) => Math.round(n).toLocaleString('es-MX');
  const parseAmount = (s) => {
    const cleaned = String(s).replace(/[^\d]/g, '');
    if (!cleaned) return 0;
    return Math.min(Math.max(parseInt(cleaned, 10), Number(els.slider.min)), Number(els.slider.max));
  };

  // ── amount sync ───────────────────────────────────────────────────────────

  function setAmount(n, source) {
    const clamped = Math.min(Math.max(n, Number(els.slider.min)), Number(els.slider.max));
    if (source !== 'slider') els.slider.value = clamped;
    if (source !== 'input') els.input.value = fmtNumber(clamped);
  }

  els.slider.addEventListener('input', (e) => {
    setAmount(Number(e.target.value), 'slider');
    markStale();
  });
  els.input.addEventListener('input', (e) => {
    const n = parseAmount(e.target.value);
    setAmount(n, 'input');
    markStale();
  });
  els.input.addEventListener('blur', (e) => {
    els.input.value = fmtNumber(parseAmount(e.target.value));
  });
  els.input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      els.input.blur();
      calculate();
    }
  });

  // ── stale-results handling ────────────────────────────────────────────────

  function markStale() {
    if (state.hasResults) els.staleBanner.hidden = false;
  }

  els.staleRecalc.addEventListener('click', calculate);

  // ── institutions load + render ────────────────────────────────────────────

  async function loadInstitutions() {
    try {
      const res = await fetch('/instituciones');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      state.institutions = data.instituciones;
      data.instituciones.forEach((i) => state.selected.add(i.nombre));
      renderInstitutions();
    } catch (err) {
      els.list.innerHTML = '<div class="loading" style="color:var(--warning)">No se pudo cargar la lista de instituciones. Recarga la página.</div>';
      console.error(err);
    }
  }

  function tagFor(tipo) {
    if (tipo === 'sofipo') return '<span class="tag tag-sofipo">SOFIPO</span>';
    if (tipo === 'banco') return '<span class="tag tag-banco">Banco</span>';
    return '<span class="tag">Fintech</span>';
  }

  function renderInstitutions() {
    const html = state.institutions.map((i) => {
      const active = state.selected.has(i.nombre);
      const condClass = i.tiene_condicion ? 'cond-warn' : 'cond-ok';
      const condIcon = i.tiene_condicion ? '⚠️' : '✓';
      return `
        <label class="inst ${active ? 'is-active' : ''}" data-name="${escapeAttr(i.nombre)}">
          <input type="checkbox" class="inst-check" ${active ? 'checked' : ''} aria-label="${escapeAttr(i.nombre)}">
          <div class="inst-main">
            <p class="inst-name">${escapeHtml(i.nombre)} ${tagFor(i.tipo)}</p>
            <p class="inst-meta">
              <span>${escapeHtml(i.cobertura_label)}</span>
              <span class="${condClass}">${condIcon} ${escapeHtml(i.condicion)}</span>
            </p>
          </div>
          <div class="inst-rate">
            ${escapeHtml(i.tasa_max_label)}
            <small>tasa máx.</small>
          </div>
        </label>
      `;
    }).join('');
    els.list.innerHTML = html;

    els.list.querySelectorAll('.inst').forEach((row) => {
      const checkbox = row.querySelector('.inst-check');
      checkbox.addEventListener('change', () => {
        const name = row.dataset.name;
        if (checkbox.checked) state.selected.add(name);
        else state.selected.delete(name);
        row.classList.toggle('is-active', checkbox.checked);
        updateSelectedCount();
        markStale();
      });
    });

    updateSelectedCount();
  }

  function updateSelectedCount() {
    els.selectedCount.textContent = state.selected.size;
    const total = state.institutions.length;
    els.toggleAll.textContent = state.selected.size === total
      ? 'Deseleccionar todo'
      : 'Seleccionar todo';
    els.cta.disabled = state.selected.size === 0;
  }

  els.toggleAll.addEventListener('click', () => {
    const total = state.institutions.length;
    if (state.selected.size === total) {
      state.selected.clear();
    } else {
      state.institutions.forEach((i) => state.selected.add(i.nombre));
    }
    renderInstitutions();
    markStale();
  });

  // ── calc / results ────────────────────────────────────────────────────────

  els.cta.addEventListener('click', calculate);

  async function calculate() {
    const total = parseAmount(els.input.value);
    if (!total || state.selected.size === 0) return;

    els.cta.classList.add('is-loading');
    els.cta.disabled = true;

    try {
      const res = await fetch('/api/allocate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          total,
          instituciones_habilitadas: Array.from(state.selected),
          horizonte_anos: 1.0,
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({ detail: 'Error' }));
        throw new Error(body.detail || ('HTTP ' + res.status));
      }
      const data = await res.json();
      renderResults(total, data);
    } catch (err) {
      console.error(err);
      showWarning('No se pudo calcular el plan: ' + err.message);
    } finally {
      els.cta.classList.remove('is-loading');
      els.cta.disabled = false;
    }
  }

  function showWarning(msg) {
    els.placeholder.hidden = true;
    els.results.hidden = false;
    els.warning.textContent = msg;
    els.warning.hidden = false;
    els.planCards.innerHTML = '';
    els.rTotal.textContent = fmtMXN(parseAmount(els.input.value));
    els.rRate.textContent = '—';
    els.rReturn.textContent = '—';
    if (state.chart) { state.chart.destroy(); state.chart = null; }
  }

  function renderResults(total, data) {
    els.placeholder.hidden = true;
    els.results.hidden = false;
    els.warning.hidden = true;
    els.staleBanner.hidden = true;
    state.hasResults = true;
    document.body.classList.add('results-visible');

    els.rTotal.textContent = fmtMXN(total);

    if (data.total_asignado < 1) {
      els.rRate.textContent = '—';
      els.rReturn.textContent = '—';
      els.planCards.innerHTML = '';
      els.deltaBanner.hidden = true;
      if (state.chart) { state.chart.destroy(); state.chart = null; }
      els.warning.textContent = 'No se pudo generar una asignación con las instituciones seleccionadas.';
      els.warning.hidden = false;
      return;
    }

    animateNumber(els.rRate, 0, data.tasa_efectiva, (v) => (v * 100).toFixed(2) + '% anual');
    animateNumber(els.rReturn, 0, data.rendimiento_esperado, (v) => fmtMXN(v));

    if (data.comparativa && data.comparativa.delta > 0) {
      els.rTradRate.textContent = data.comparativa.tasa_tradicional_label;
      els.rTradReturn.textContent = data.comparativa.rendimiento_tradicional_label;
      animateNumber(els.rDelta, 0, data.comparativa.delta, (v) => fmtMXN(v));
      els.deltaBanner.hidden = false;
    } else {
      els.deltaBanner.hidden = true;
    }

    renderChart(data.chart_data);
    renderPlanCards(data.asignaciones);

    // Smooth-scroll into view on mobile (single-column layout)
    if (window.innerWidth < 980) {
      requestAnimationFrame(() => {
        els.results.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
  }

  // When the user scrolls back to the controls area on mobile,
  // bring back the sticky CTA so they can recalculate without finding it.
  if ('IntersectionObserver' in window) {
    const sentinel = document.querySelector('#paso-2');
    if (sentinel) {
      const io = new IntersectionObserver((entries) => {
        if (window.innerWidth >= 721) return;
        for (const e of entries) {
          if (e.isIntersecting && e.intersectionRatio > 0.25) {
            document.body.classList.remove('results-visible');
          }
        }
      }, { threshold: [0, 0.25, 0.5] });
      io.observe(sentinel);
    }
  }

  function renderPlanCards(asignaciones) {
    if (!asignaciones.length) {
      els.planCards.innerHTML = '<p class="results-sub">Sin instituciones a las que asignar capital.</p>';
      return;
    }
    els.planCards.innerHTML = asignaciones.map((a) => {
      const tiers = a.tramos.map((t) => `
        <li class="tier">
          <span class="tier-num">${t.numero}</span>
          <span class="tier-amount">${escapeHtml(t.monto_label)}</span>
          <span class="tier-rate">${escapeHtml(t.tasa_label)}</span>
          <span class="tier-yield">rinde ${escapeHtml(t.rendimiento_label)}</span>
        </li>
      `).join('');

      const condBlock = a.tiene_condicion
        ? `<div class="plan-card-condition">⚠️ <span><strong>Para acceder a esta tasa necesitas:</strong> ${escapeHtml(a.condicion)}</span></div>`
        : '';

      const multiTier = a.tramos.length > 1
        ? `<p class="plan-card-instr">La institución distribuye tu depósito automáticamente entre sus tramos:</p>`
        : '';

      return `
        <article class="plan-card">
          <header class="plan-card-head">
            <div>
              <h4 class="plan-card-name">Abre una cuenta en ${escapeHtml(a.institucion)} ${tagFor(a.tipo)}</h4>
              <p class="plan-card-instr">Deposita <strong>${escapeHtml(a.monto_total_label)}</strong>.</p>
            </div>
            <div class="plan-card-deposit">${escapeHtml(a.monto_total_label)}</div>
          </header>
          ${multiTier}
          <ul class="tier-list">${tiers}</ul>
          <div class="plan-card-foot">
            <span>Ganarás aprox. <strong>${escapeHtml(a.rendimiento_label)}</strong> en el año</span>
            <span>·</span>
            <span>Cobertura ${escapeHtml(a.cobertura_label)}</span>
          </div>
          ${condBlock}
        </article>
      `;
    }).join('');
  }

  function renderChart(chartData) {
    if (!window.Chart) {
      setTimeout(() => renderChart(chartData), 80);
      return;
    }
    if (state.chart) state.chart.destroy();

    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue('--accent').trim() || '#00b779';
    const ink = styles.getPropertyValue('--ink-soft').trim() || '#3a4a45';
    const line = styles.getPropertyValue('--line').trim() || '#e2e6e1';

    state.chart = new Chart(els.chartCanvas, {
      type: 'bar',
      data: {
        labels: chartData.labels,
        datasets: [{
          label: 'Monto asignado',
          data: chartData.montos,
          backgroundColor: accent,
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: 36,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 600 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => fmtMXN(ctx.parsed.x),
            },
          },
        },
        scales: {
          x: {
            ticks: {
              color: ink,
              callback: (v) => '$' + Number(v).toLocaleString('es-MX'),
            },
            grid: { color: line },
          },
          y: {
            ticks: { color: ink },
            grid: { display: false },
          },
        },
      },
    });
  }

  function animateNumber(el, from, to, formatter) {
    const duration = 600;
    const start = performance.now();
    function step(t) {
      const p = Math.min((t - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      const value = from + (to - from) * eased;
      el.textContent = formatter(value);
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  // ── escaping ──────────────────────────────────────────────────────────────

  function escapeHtml(s) {
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }
  function escapeAttr(s) { return escapeHtml(s); }

  // ── noticias ──────────────────────────────────────────────────────────────

  async function loadNoticias() {
    if (!els.noticiasList) return;
    try {
      const res = await fetch('/noticias');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      renderNoticias(data.noticias || []);
    } catch (err) {
      els.noticiasList.innerHTML = '<p class="noticias-empty">No se pudieron cargar las noticias.</p>';
      console.error(err);
    }
  }

  function renderNoticias(items) {
    if (!items.length) {
      els.noticiasList.innerHTML = '<p class="noticias-empty">Sin cambios de tasa registrados aún.</p>';
      return;
    }
    els.noticiasList.innerHTML = items.map((n) => {
      const dir = n.subio ? 'up' : 'down';
      const arrow = n.subio ? '▲' : '▼';
      return `
        <div class="noticia">
          <span class="noticia-arrow noticia-${dir}" aria-hidden="true">${arrow}</span>
          <div class="noticia-body">
            <p class="noticia-title">
              <strong>${escapeHtml(n.institucion)}</strong>
              <span class="noticia-tramo">tramo ${escapeHtml(n.tramo)}</span>
            </p>
            <p class="noticia-detail">
              ${escapeHtml(n.tasa_anterior_label)} → <strong class="noticia-${dir}">${escapeHtml(n.tasa_nueva_label)}</strong>
              · efectivo el ${escapeHtml(n.fecha_label)}
            </p>
          </div>
        </div>
      `;
    }).join('');
  }

  // ── init ──────────────────────────────────────────────────────────────────

  loadInstitutions();
  loadNoticias();
})();
