/* Merqurio — Wizard v2 · Mobile-first 3-step calculator. Vanilla JS. */
(function () {
  'use strict';

  // Provisional affiliate links — replace with real referral URLs once registered.
  const AFFILIATE = {
    'DiDi':         'https://moneydidi.mx/ahorra/',
    'Revolut':      'https://www.revolut.com/es-MX/',
    'Nu':           'https://nu.com.mx/',
    'Openbank':     'https://www.openbank.mx/',
    'Mercado Pago': 'https://www.mercadopago.com.mx/cuenta-de-ahorro',
    'Klar':         'https://www.klar.mx/',
    'Uala':         'https://www.uala.com.mx/',
    'PlataCard':    'https://www.platacard.mx/',
    'Stori':        'https://www.storicard.com/',
    'Mifel':        'https://www.mifel.com.mx/',
    'BONDDIA':      'https://www.gbmhomebroker.com/bonddia',
    'Supertasas':   'https://www.supertasas.com/',
  };

  // ── DOM refs ──────────────────────────────────────────────────────────────

  const $ = (id) => document.getElementById(id);

  const els = {
    // Step 1
    slider:       $('amount-slider'),
    amountInput:  $('amount-input'),
    step1Next:    $('step1-next'),

    // Step 2
    step2Back:    $('step2-back'),
    step2Calc:    $('step2-calc'),
    countChips:   $('count-chips'),
    countHint:    $('count-hint'),
    instList:     $('inst-list-v2'),
    condSummary:  $('cond-summary'),
    condSummaryBody: $('cond-summary-body'),

    // Step 3
    resLoading:      $('res-loading'),
    resError:        $('res-error'),
    resErrorMsg:     $('res-error-msg'),
    resRetry:        $('res-retry'),
    resContent:      $('res-content'),
    resFooter:       $('res-footer'),

    rRate:           $('r-rate'),
    rTotal:          $('r-total'),
    rSubtitle:       $('r-subtitle'),
    rReturn:         $('r-return'),
    deltaV2:         $('delta-v2'),
    rDelta:          $('r-delta'),
    rCetesRate:      $('r-cetes-rate'),
    accountsCallout: $('accounts-callout'),
    accountsCount:   $('accounts-count'),
    accountsNames:   $('accounts-names'),
    chartWrap:       $('chart-wrap'),
    chartCanvas:     $('alloc-chart'),
    planCards:       $('plan-cards'),
    affiliateDisc:   $('affiliate-disc'),

    step3Back:    $('step3-back'),
    wizRestart:   $('wiz-restart'),

    // Progress
    dots:  [null, $('dot-1'), $('dot-2'), $('dot-3')],
    conns: [null, $('conn-1'), $('conn-2')],
  };

  // ── State ─────────────────────────────────────────────────────────────────

  const state = {
    currentStep: 1,
    institutions: [],
    selected: new Set(),
    countMode: 'all',
    chart: null,
    pendingChartData: null,
  };

  // ── Formatting ────────────────────────────────────────────────────────────

  const fmtMXN     = (n) => '$' + Math.round(n).toLocaleString('es-MX') + ' MXN';
  const fmtNumber  = (n) => Math.round(n).toLocaleString('es-MX');
  const fmtPct     = (v) => (v * 100).toFixed(2) + '%';
  const fmtPctUnit = (v) => fmtPct(v) + '<span class="metric-unit">anual</span>';
  const fmtMXNUnit = (n) => '$' + Math.round(n).toLocaleString('es-MX') + '<span class="metric-unit">MXN</span>';

  const parseAmount = (s) => {
    const n = parseInt(String(s).replace(/[^\d]/g, ''), 10);
    if (!n) return 0;
    return Math.min(Math.max(n, Number(els.slider.min)), Number(els.slider.max));
  };

  function escapeHtml(s) {
    return String(s)
      .replaceAll('&', '&amp;').replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;').replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }
  const escapeAttr = escapeHtml;

  // ── Wizard navigation ─────────────────────────────────────────────────────

  function gtag_event(name, params) {
    if (typeof gtag === 'function') gtag('event', name, params || {});
  }

  function goTo(step) {
    const panels = document.querySelectorAll('.wiz-panel');
    panels.forEach((p, i) => {
      const n = i + 1;
      if (n < step) p.dataset.state = 'before';
      else if (n === step) p.dataset.state = 'active';
      else p.dataset.state = 'after';
    });
    gtag_event('wizard_step', { step });

    for (let i = 1; i <= 3; i++) {
      const dot = els.dots[i];
      dot.classList.toggle('is-done',   i < step);
      dot.classList.toggle('is-active', i === step);
      dot.textContent = String(i); // restore number (overridden in showResults for dot-3)
      dot.removeAttribute('aria-current');
      if (i === step) dot.setAttribute('aria-current', 'step');
    }
    for (let i = 1; i <= 2; i++) {
      els.conns[i].classList.toggle('is-done', i < step);
    }

    state.currentStep = step;
    const activePanel = document.querySelector('.wiz-panel[data-state="active"] .wiz-panel-inner');
    if (activePanel) activePanel.scrollTop = 0;
  }

  // ── Step 1 — Amount ───────────────────────────────────────────────────────

  function updateSliderTrack() {
    const min = Number(els.slider.min);
    const max = Number(els.slider.max);
    const val = Number(els.slider.value);
    const pct = ((val - min) / (max - min)) * 100;
    els.slider.style.setProperty('--pct', pct + '%');
  }

  els.slider.addEventListener('input', (e) => {
    const n = Number(e.target.value);
    els.amountInput.value = fmtNumber(n);
    updateSliderTrack();
  });

  els.amountInput.addEventListener('input', (e) => {
    const n = parseAmount(e.target.value);
    if (n) { els.slider.value = n; updateSliderTrack(); }
  });

  els.amountInput.addEventListener('blur', (e) => {
    els.amountInput.value = fmtNumber(parseAmount(e.target.value));
  });

  els.amountInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); els.amountInput.blur(); }
  });

  els.step1Next.addEventListener('click', () => {
    const n = parseAmount(els.amountInput.value);
    if (!n) return;
    goTo(2);
  });

  updateSliderTrack();

  // ── Step 2 — Institutions (which-first) ──────────────────────────────────

  async function loadInstitutions() {
    try {
      const res = await fetch('/instituciones');
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      state.institutions = data.instituciones;
      updateChipAll();
      applyCountMode(state.countMode);
      renderInstList(); // list always visible
    } catch (err) {
      els.instList.innerHTML = '<p class="count-hint" style="color:var(--warning);padding:.25rem">No se pudo cargar la lista. Recarga la página.</p>';
      console.error(err);
    }
  }

  function updateChipAll() {
    const total = state.institutions.length;
    const chip = document.querySelector('.count-chip[data-count="all"]');
    if (chip) chip.textContent = `Todas (${total})`;
    document.querySelectorAll('.count-chip[data-count]').forEach((c) => {
      const n = Number(c.dataset.count);
      if (!isNaN(n)) c.hidden = n > total;
    });
  }

  function applyCountMode(mode) {
    state.countMode = mode;
    const total = state.institutions.length;

    state.selected.clear();
    const limit = (mode === 'all') ? total : Math.min(Number(mode), total);
    state.institutions.slice(0, limit).forEach((i) => state.selected.add(i.nombre));

    document.querySelectorAll('.count-chip').forEach((c) => {
      const isActive = String(c.dataset.count) === String(mode);
      c.classList.toggle('active', isActive);
      c.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });

    if (mode === 'all') {
      els.countHint.textContent = `Incluye todas las instituciones disponibles.`;
    } else {
      const n = Math.min(Number(mode), total);
      els.countHint.textContent = n === 1
        ? 'Solo la institución con mayor tasa.'
        : `Las ${n} instituciones con mayor tasa.`;
    }

    renderInstList();
    updateCondSummary();
    updateStep2Cta();
  }

  els.countChips.addEventListener('click', (e) => {
    const chip = e.target.closest('.count-chip');
    if (!chip) return;
    const mode = chip.dataset.count === 'all' ? 'all' : Number(chip.dataset.count);
    applyCountMode(mode);
  });

  function tagFor(tipo) {
    if (tipo === 'sofipo') return '<span class="tag tag-sofipo">SOFIPO</span>';
    if (tipo === 'banco')  return '<span class="tag tag-banco">Banco</span>';
    return '<span class="tag">Fintech</span>';
  }

  function renderInstList() {
    if (!state.institutions.length) return;

    els.instList.innerHTML = state.institutions.map((inst) => {
      const active = state.selected.has(inst.nombre);
      const condClass = inst.tiene_condicion ? 'inst-cond-warn' : 'inst-cond-ok';
      const condIcon  = inst.tiene_condicion ? '⚠️ Requisito:' : '✓';
      return `
        <div class="inst-card-v2 ${active ? 'is-active' : ''}"
             data-name="${escapeAttr(inst.nombre)}"
             role="checkbox"
             aria-checked="${active}"
             tabindex="0">
          <div class="inst-check-v2" aria-hidden="true"></div>
          <div class="inst-card-body">
            <div class="inst-row-v2">
              <span class="inst-name-v2">${escapeHtml(inst.nombre)}</span>
              ${tagFor(inst.tipo)}
              <span class="inst-rate-v2">${escapeHtml(inst.tasa_max_label)}</span>
            </div>
            <div class="inst-cond-block">
              <span class="${condClass}">${condIcon} ${escapeHtml(inst.condicion)}</span>
            </div>
          </div>
        </div>
      `;
    }).join('');

    els.instList.querySelectorAll('.inst-card-v2').forEach((card) => {
      const toggle = () => {
        const name = card.dataset.name;
        if (state.selected.has(name)) state.selected.delete(name);
        else state.selected.add(name);
        card.classList.toggle('is-active', state.selected.has(name));
        card.setAttribute('aria-checked', state.selected.has(name));
        updateCondSummary();
        updateStep2Cta();
        // Custom selection: deactivate preset chips
        document.querySelectorAll('.count-chip').forEach((c) => {
          c.classList.remove('active');
          c.setAttribute('aria-pressed', 'false');
        });
        els.countHint.textContent = `${state.selected.size} institución${state.selected.size !== 1 ? 'es' : ''} seleccionada${state.selected.size !== 1 ? 's' : ''}.`;
      };
      card.addEventListener('click', toggle);
      card.addEventListener('keydown', (e) => {
        if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); toggle(); }
      });
    });
  }

  function updateCondSummary() {
    const withCond = state.institutions
      .filter((i) => state.selected.has(i.nombre) && i.tiene_condicion)
      .map((i) => i.nombre);

    if (withCond.length) {
      els.condSummaryBody.textContent =
        `${withCond.join(', ')} — revisa sus requisitos en la lista de arriba antes de calcular.`;
      els.condSummary.hidden = false;
    } else {
      els.condSummary.hidden = true;
    }
  }

  function updateStep2Cta() {
    els.step2Calc.disabled = state.selected.size === 0;
  }

  els.step2Back.addEventListener('click', () => goTo(1));

  els.step2Calc.addEventListener('click', () => {
    goTo(3);
    calculate();
  });

  // ── Step 3 — Calculation + Results ───────────────────────────────────────

  function showLoading() {
    els.resLoading.hidden  = false;
    els.resError.hidden    = true;
    els.resContent.hidden  = true;
    els.resFooter.hidden   = true;
  }

  function showError(msg) {
    els.resLoading.hidden  = true;
    els.resError.hidden    = false;
    els.resErrorMsg.textContent = msg;
    els.resContent.hidden  = true;
    els.resFooter.hidden   = false; // back button still usable
    gtag_event('plan_error');
  }

  function showResults() {
    els.resLoading.hidden = true;
    els.resError.hidden   = true;
    els.resContent.hidden = false;
    els.resFooter.hidden  = false;

    // Render chart now that the container is visible
    if (state.pendingChartData) {
      renderChart(state.pendingChartData);
      state.pendingChartData = null;
    }

    // Dot 3 → completed state (✓)
    els.dots[3].textContent = '✓';
    els.dots[3].classList.add('is-done');
    els.dots[3].classList.remove('is-active');

    gtag_event('plan_shown');
  }

  async function calculate() {
    showLoading();

    const total = parseAmount(els.amountInput.value);
    if (!total || state.selected.size === 0) {
      showError('Selecciona al menos una institución e ingresa un monto válido.');
      return;
    }

    els.step2Calc.classList.add('is-loading');

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
        const body = await res.json().catch(() => ({}));
        const detail = body.detail;
        const msg = detail && typeof detail === 'object' && detail.mensaje_usuario
          ? detail.mensaje_usuario
          : (typeof detail === 'string' ? detail : 'Error del servidor (HTTP ' + res.status + ')');
        throw new Error(msg);
      }

      const data = await res.json();
      renderResults(total, data);
    } catch (err) {
      showError(err.message || 'No se pudo calcular el plan. Intenta de nuevo.');
      console.error(err);
    } finally {
      els.step2Calc.classList.remove('is-loading');
    }
  }

  function renderResults(total, data) {
    if (data.total_asignado < 1) {
      showError('No se pudo generar un plan con las instituciones seleccionadas. Prueba incluyendo más.');
      return;
    }

    const asig = data.asignaciones || [];

    // ── Veredicto ────────────────────────────────────────────────────────────

    els.rRate.textContent = fmtPct(data.tasa_efectiva);
    els.rTotal.textContent = fmtMXN(total);
    els.rSubtitle.innerHTML = `Invirtiendo <strong>${fmtMXN(total)}</strong> según este plan.`;

    animateNumber(els.rReturn, 0, data.rendimiento_esperado, fmtMXNUnit);

    if (data.comparativa && data.comparativa.delta > 0) {
      els.rCetesRate.textContent = data.comparativa.tasa_cetes_label;
      animateNumber(els.rDelta, 0, data.comparativa.delta, (v) => fmtMXN(v));
      els.deltaV2.hidden = false;
    } else {
      els.deltaV2.hidden = true;
    }

    if (asig.length) {
      const n = asig.length;
      els.accountsCount.textContent = `${n} cuenta${n !== 1 ? 's' : ''} nueva${n !== 1 ? 's' : ''}`;
      els.accountsNames.textContent = asig.map((a) => a.institucion).join(' · ');
      els.accountsCallout.hidden = false;
    } else {
      els.accountsCallout.hidden = true;
    }

    // ── Distribución ─────────────────────────────────────────────────────────

    // Store chart data — rendered in showResults() once container is visible
    if (data.chart_data && asig.length > 0) {
      state.pendingChartData = data.chart_data;
      els.chartWrap.hidden = false;
    } else {
      state.pendingChartData = null;
      els.chartWrap.hidden = true;
    }

    renderPlanCards(asig);

    const hasAffiliate = asig.some((a) => AFFILIATE[a.institucion]);
    if (els.affiliateDisc) els.affiliateDisc.hidden = !hasAffiliate;

    gtag_event('plan_calculated', { instituciones: asig.length });
    showResults();
  }

  function renderPlanCards(asignaciones) {
    if (!asignaciones.length) {
      els.planCards.innerHTML = '<p class="wiz-sub">Sin instituciones asignadas.</p>';
      return;
    }

    els.planCards.innerHTML = asignaciones.map((a) => {
      const tiers = a.tramos.map((t, idx) => `
        <div class="tier-v2">
          <span class="tier-badge-v2">${idx + 1}</span>
          <span>${escapeHtml(t.monto_label)}</span>
          <span>·</span>
          <span class="tier-rate-v2">${escapeHtml(t.tasa_label)}</span>
          <span class="tier-yield-v2">→ rinde ${escapeHtml(t.rendimiento_label)}</span>
        </div>
      `).join('');

      const condBlock = a.tiene_condicion ? `
        <div class="plan-cond-v2">
          <span aria-hidden="true">⚠️</span>
          <div class="plan-cond-v2-texts">
            <p class="plan-cond-v2-title">Requisito para acceder a esta tasa:</p>
            <p class="plan-cond-v2-text">${escapeHtml(a.condicion)}</p>
          </div>
        </div>
      ` : '';

      const multiInstr = a.tramos.length > 1
        ? `<p class="count-hint" style="margin-bottom:.25rem">La institución distribuye tu depósito entre sus tramos automáticamente:</p>`
        : '';

      const affiliateUrl = AFFILIATE[a.institucion];
      // Action: affiliate link replaces static text when available
      const actionLine = affiliateUrl
        ? `<a href="${escapeAttr(affiliateUrl)}"
              target="_blank"
              rel="noopener sponsored"
              data-inst="${escapeAttr(a.institucion)}"
              class="plan-card-action-link">
             Abrir cuenta en ${escapeHtml(a.institucion)} →
           </a>`
        : `<p class="plan-card-action-v2">Abre una cuenta y deposita esta cantidad</p>`;

      return `
        <article class="plan-card-v2">
          <header class="plan-card-head-v2">
            <div>
              <p class="plan-card-inst-v2">
                ${escapeHtml(a.institucion)} ${tagFor(a.tipo)}
              </p>
              ${actionLine}
            </div>
            <div class="plan-card-amount-v2">${escapeHtml(a.monto_total_label)}</div>
          </header>
          <div class="plan-card-body-v2">
            ${multiInstr}
            ${tiers}
          </div>
          <div class="plan-card-yield-v2">
            <span>Cobertura ${escapeHtml(a.cobertura_label)}</span>
            <span>Ganarás aprox. <strong>${escapeHtml(a.rendimiento_label)}</strong></span>
          </div>
          ${condBlock}
        </article>
      `;
    }).join('');

    // GA4: track affiliate link clicks
    els.planCards.querySelectorAll('.plan-card-action-link').forEach((link) => {
      link.addEventListener('click', () => {
        gtag_event('affiliate_click', { institution: link.dataset.inst });
      });
    });
  }

  function renderChart(chartData) {
    if (!window.Chart) { setTimeout(() => renderChart(chartData), 80); return; }
    if (state.chart) { state.chart.destroy(); state.chart = null; }

    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue('--primary').trim() || '#1e7a4d';
    const ink    = styles.getPropertyValue('--ink-soft').trim() || '#4a4843';
    const line   = styles.getPropertyValue('--line').trim() || '#e5e2d9';

    state.chart = new Chart(els.chartCanvas, {
      type: 'bar',
      data: {
        labels: chartData.labels,
        datasets: [{
          label: 'Monto',
          data: chartData.montos,
          backgroundColor: accent,
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: 32,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 500 },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (ctx) => fmtMXN(ctx.parsed.x) } },
        },
        scales: {
          x: {
            ticks: { color: ink, callback: (v) => '$' + Number(v).toLocaleString('es-MX') },
            grid: { color: line },
          },
          y: { ticks: { color: ink }, grid: { display: false } },
        },
      },
    });
  }

  function animateNumber(el, from, to, formatter) {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      el.innerHTML = formatter(to);
      return;
    }
    const duration = 550;
    const start = performance.now();
    const step = (t) => {
      const p = Math.min((t - start) / duration, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.innerHTML = formatter(from + (to - from) * eased);
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ── Step 3 navigation ─────────────────────────────────────────────────────

  els.step3Back.addEventListener('click', () => goTo(2));
  els.resRetry.addEventListener('click', () => goTo(2));

  els.wizRestart.addEventListener('click', () => {
    applyCountMode('all');
    els.amountInput.value = fmtNumber(Number(els.slider.value));
    gtag_event('wizard_restart');
    goTo(1);
  });

  // ── Init ──────────────────────────────────────────────────────────────────

  loadInstitutions();
})();
