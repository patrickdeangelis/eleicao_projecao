/**
 * Graficos — camada de gráficos do painel SPETR sobre o Apache ECharts (vendor/echarts.min.js).
 * Linhas com faixa de incerteza e crosshair, histogramas, barras horizontais e empilhadas.
 * Cores e textos vêm dos tokens CSS (tema claro/escuro). Todo texto vindo de dados (nomes do
 * TSE) é escapado antes de entrar nos tooltips do ECharts, que aceitam HTML.
 */
const Graficos = (() => {
  const tooltip = document.getElementById('tooltip');

  const token = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();

  function escapar(valor) {
    return String(valor ?? '').replace(/[&<>"'`]/g, (ch) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;',
    }[ch]));
  }

  function textoSobre(hex) {
    const m = (hex || '').replace('#', '');
    if (m.length !== 6) return '#ffffff';
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(m.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 ? '#0b0b0b' : '#ffffff';
  }

  // ------------------------------------------------------------ infraestrutura

  /** Instância ECharts do container (criada uma vez; redimensionada a cada desenho). */
  function instancia(container, altura) {
    const msg = container.querySelector(':scope > .vazio');
    if (msg) msg.remove();
    container.style.height = `${altura}px`;
    let grafico = echarts.getInstanceByDom(container);
    if (!grafico) grafico = echarts.init(container, null, { renderer: 'svg' });
    else grafico.resize();
    return grafico;
  }

  function vazio(container, mensagem) {
    const g = echarts.getInstanceByDom(container);
    if (g) g.dispose();
    container.style.height = '';
    container.textContent = '';
    const d = document.createElement('div');
    d.className = 'vazio';
    d.textContent = mensagem || 'Aguardando dados';
    container.appendChild(d);
  }

  /** Opções comuns: fonte, tooltip e eixos recessivos nos tokens do tema atual. */
  function base() {
    const texto3 = token('--texto-3');
    return {
      animationDurationUpdate: 300,
      aria: { enabled: true },
      textStyle: { fontFamily: token('--fonte') || 'system-ui, sans-serif', color: token('--texto-2') },
      tooltip: {
        backgroundColor: token('--superficie'),
        borderColor: token('--borda'),
        borderWidth: 1,
        padding: [8, 10],
        textStyle: { color: token('--texto'), fontSize: 12 },
        extraCssText: 'box-shadow: 0 6px 24px rgba(0,0,0,.18); border-radius: 8px;',
        confine: true,
      },
      eixo: {
        axisLine: { lineStyle: { color: token('--eixo') } },
        axisTick: { show: false },
        axisLabel: { color: texto3, fontSize: 11 },
        splitLine: { lineStyle: { color: token('--grade'), type: 'solid' } },
      },
    };
  }

  /** Arredonda [min, max] para múltiplos de um passo "bonito" (1, 2, 5 × 10^n). */
  function limitesBonitos(min, max, alvo = 5) {
    if (!(max > min)) return [min, max];
    const bruto = (max - min) / alvo;
    const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
    const r = bruto / mag;
    const passo = (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * mag;
    return [Math.floor(min / passo + 1e-9) * passo, Math.ceil(max / passo - 1e-9) * passo];
  }

  function semEixo(b) {
    const { eixo, ...resto } = b;
    return resto;
  }

  function linhaTooltip(cor, valor, rotulo) {
    return '<div style="display:flex;align-items:center;gap:6px;white-space:nowrap">' +
      `<span style="display:inline-block;width:14px;height:2px;background:${escapar(cor)}"></span>` +
      `<strong style="min-width:52px;font-variant-numeric:tabular-nums">${escapar(valor)}</strong>` +
      `<span style="color:${token('--texto-2')}">${escapar(rotulo)}</span></div>`;
  }

  function tituloTooltip(t) {
    return `<div style="color:${token('--texto-2')};font-size:11px;margin-bottom:4px">${escapar(t)}</div>`;
  }

  /** Linha de referência tracejada (50% dos válidos, empate…) via markLine. */
  function referencias(refs, eixo) {
    if (!refs || !refs.length) return undefined;
    return {
      silent: true,
      symbol: 'none',
      lineStyle: { color: token('--texto-3'), type: [4, 4], width: 1 },
      label: { color: token('--texto-2'), fontSize: 11, position: eixo === 'x' ? 'end' : 'insideStartTop', rotate: 0 },
      data: refs.map((r) => (eixo === 'x'
        ? { xAxis: r.x, label: { formatter: r.rotulo || '' } }
        : { yAxis: r.y, label: { formatter: r.rotulo || '' } })),
    };
  }

  // -------------------------------------------------------------- linhas
  /**
   * series: [{id, rotulo, rotuloCurto, cor, pontos: [{x, y, lo, hi}], banda, espessura}]
   * cfg: xFmt, xTitulo, yFmt, yMin, yMax, yPiso, yTeto, refs [{y, rotulo}], rotulosFim
   */
  function linhas(container, cfg) {
    const series = cfg.series.filter((s) => s.pontos.length);
    if (!series.length) return vazio(container, cfg.vazio);
    const grafico = instancia(container, cfg.altura || 260);
    const b = base();

    const todosY = series.flatMap((s) => s.pontos.flatMap((p) => [p.y, p.lo ?? p.y, p.hi ?? p.y]))
      .concat((cfg.refs || []).map((r) => r.y));
    let yMin = cfg.yMin, yMax = cfg.yMax;
    if (yMin === undefined || yMax === undefined) {
      const lo = Math.min(...todosY), hi = Math.max(...todosY);
      const folga = (hi - lo) * 0.08 || 1;
      const [bMin, bMax] = limitesBonitos(lo - folga, hi + folga);
      if (yMin === undefined) yMin = Math.max(cfg.yPiso ?? -Infinity, bMin);
      if (yMax === undefined) yMax = Math.min(cfg.yTeto ?? Infinity, bMax);
    }

    const rotulosFim = cfg.rotulosFim !== false;
    const maxRotulos = cfg.maxRotulos || 6;
    const opcoesSeries = [];
    series.forEach((s, i) => {
      // Faixa de incerteza: base invisível (lo) + espessura (hi − lo) empilhada com preenchimento
      if (s.banda && s.pontos.some((p) => p.lo !== undefined)) {
        const pilha = `banda-${s.id}`;
        const comum = { type: 'line', stack: pilha, symbol: 'none', silent: true, lineStyle: { opacity: 0 }, tooltip: { show: false }, z: 1 };
        opcoesSeries.push({ ...comum, id: `lo-${s.id}`, data: s.pontos.map((p) => [p.x, p.lo]) });
        opcoesSeries.push({
          ...comum, id: `faixa-${s.id}`, areaStyle: { color: s.cor, opacity: 0.14 },
          data: s.pontos.map((p) => [p.x, p.hi - p.lo]),
        });
      }
      opcoesSeries.push({
        id: `s-${s.id}`,
        name: s.rotulo,
        type: 'line',
        data: s.pontos.map((p) => [p.x, p.y, p.lo, p.hi]),
        showSymbol: false,
        symbolSize: 8,
        lineStyle: { width: s.espessura || 2, color: s.cor },
        itemStyle: { color: s.cor, borderColor: token('--superficie'), borderWidth: 2 },
        emphasis: { focus: 'series' },
        endLabel: rotulosFim && i < maxRotulos ? {
          show: true,
          formatter: (p) => `${s.rotuloCurto || s.rotulo} ${cfg.yFmt(p.value[1])}`,
          color: token('--texto-2'), fontSize: 11, fontWeight: 600, distance: 6,
        } : { show: false },
        labelLayout: { moveOverlap: 'shiftY' },
        markLine: i === 0 ? referencias(cfg.refs, 'y') : undefined,
        z: 3,
      });
    });

    const xs = series.flatMap((s) => s.pontos.map((p) => p.x));
    let xMin = cfg.xMin ?? Math.min(...xs), xMax = cfg.xMax ?? Math.max(...xs);
    if (xMax === xMin) xMax = xMin + 1;

    grafico.setOption({
      ...semEixo(b),
      grid: { left: 48, right: rotulosFim ? 124 : 16, top: 14, bottom: 28 },
      xAxis: {
        type: 'value', min: xMin, max: xMax, ...b.eixo,
        splitLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => cfg.xFmt(v), hideOverlap: true, showMinLabel: false, showMaxLabel: false },
      },
      yAxis: {
        type: 'value', min: yMin, max: yMax, ...b.eixo,
        axisLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => cfg.yFmt(v) },
      },
      tooltip: {
        ...b.tooltip,
        trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: token('--texto-3'), width: 1 } },
        formatter: (itens) => {
          const visiveis = itens.filter((it) => String(it.seriesId).startsWith('s-'))
            .sort((a, c) => c.value[1] - a.value[1]);
          if (!visiveis.length) return '';
          const x = visiveis[0].value[0];
          const corpo = visiveis.map((it) => {
            const s = series.find((ss) => `s-${ss.id}` === it.seriesId);
            const [, y, lo, hi] = it.value;
            const faixa = s && s.banda && lo !== undefined && lo !== null ? `  [${cfg.yFmt(lo)} – ${cfg.yFmt(hi)}]` : '';
            return linhaTooltip(s ? s.cor : it.color, cfg.yFmt(y), `${it.seriesName}${faixa}`);
          }).join('');
          return tituloTooltip(cfg.xTitulo ? cfg.xTitulo(x) : cfg.xFmt(x)) + corpo;
        },
      },
      series: opcoesSeries,
    }, { notMerge: true });
  }

  // ---------------------------------------------------------- histograma
  /** series: [{rotulo, cor, inicio, passo, freq: []}] — áreas em degrau, em densidade (% por unidade de X). */
  function histograma(container, cfg) {
    const series = (cfg.series || []).filter((s) => s && s.freq && s.freq.length);
    if (!series.length) return vazio(container, cfg.vazio);
    const grafico = instancia(container, cfg.altura || 260);
    const b = base();

    let xMin = Math.min(...series.map((s) => s.inicio));
    let xMax = Math.max(...series.map((s) => s.inicio + s.passo * s.freq.length));
    for (const r of cfg.refs || []) { xMin = Math.min(xMin, r.x); xMax = Math.max(xMax, r.x); }
    const pad = (xMax - xMin) * 0.03 || 0.5;

    const opcoesSeries = series.map((s, i) => {
      const dados = s.freq.map((f, k) => [s.inicio + k * s.passo, f / s.passo, f]);
      dados.push([s.inicio + s.freq.length * s.passo, 0, 0]);
      return {
        name: s.rotulo,
        type: 'line',
        step: 'end',
        data: dados,
        showSymbol: false,
        lineStyle: { color: s.cor, width: 1.5 },
        itemStyle: { color: s.cor },
        areaStyle: { color: s.cor, opacity: 0.22 },
        markLine: i === 0 ? referencias(cfg.refs, 'x') : undefined,
      };
    });

    grafico.setOption({
      ...semEixo(b),
      grid: { left: 48, right: 16, top: 18, bottom: 28 },
      xAxis: {
        type: 'value', min: xMin - pad, max: xMax + pad, ...b.eixo, splitLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => cfg.xFmt(v), hideOverlap: true, showMinLabel: false, showMaxLabel: false },
      },
      yAxis: {
        type: 'value', min: 0, ...b.eixo, axisLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => `${(v * 100).toFixed(v * 100 < 10 ? 1 : 0).replace('.', ',')}%` },
      },
      tooltip: {
        ...b.tooltip,
        trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: token('--texto-3'), width: 1 } },
        formatter: (itens) => {
          if (!itens.length) return '';
          const x = itens[0].value[0];
          const corpo = itens.map((it) => {
            const s = series[it.seriesIndex];
            return linhaTooltip(s.cor, `${((it.value[2] || 0) * 100).toFixed(1).replace('.', ',')}%`,
              `${s.rotulo} (classe de ${String(s.passo).replace('.', ',')} p.p.)`);
          }).join('');
          return tituloTooltip(`a partir de ${cfg.xFmt(x)}`) + corpo;
        },
      },
      series: opcoesSeries,
    }, { notMerge: true });
  }

  // ------------------------------------------------------ barras horiz.
  /** linhas: [{rotulo, valor, detalhe}] — uma série, uma cor. */
  function barrasH(container, cfg) {
    const linhasDados = cfg.linhas || [];
    if (!linhasDados.length) return vazio(container, cfg.vazio);
    const grafico = instancia(container, 16 + linhasDados.length * 22);
    const b = base();
    const cor = cfg.cor || token('--seq');
    grafico.setOption({
      ...semEixo(b),
      grid: { left: cfg.margemRotulo || 60, right: 86, top: 4, bottom: 4 },
      xAxis: { type: 'value', show: false },
      yAxis: {
        type: 'category', inverse: true, data: linhasDados.map((l) => l.rotulo),
        ...b.eixo, axisLine: { show: false }, splitLine: { show: false },
      },
      tooltip: {
        ...b.tooltip, trigger: 'item',
        formatter: (it) => {
          const l = linhasDados[it.dataIndex];
          return tituloTooltip(l.rotulo) + linhaTooltip(cor, cfg.fmt(l.valor), l.detalhe || '');
        },
      },
      series: [{
        type: 'bar',
        data: linhasDados.map((l) => l.valor),
        barWidth: 14,
        itemStyle: { color: cor, borderRadius: [0, 3, 3, 0] },
        emphasis: { itemStyle: { opacity: 0.85 } },
        label: { show: true, position: 'right', formatter: (p) => cfg.fmt(p.value), color: token('--texto-2'), fontSize: 11, fontWeight: 600 },
      }],
    }, { notMerge: true });
  }

  // ------------------------------------------------- barras empilhadas
  /** linhas: [{rotulo, segmentos: [{rotulo, cor, valor (0-100)}], grupoInicio}] — partes de 100%. */
  function barrasEmpilhadas(container, cfg) {
    const linhasDados = cfg.linhas || [];
    if (!linhasDados.length) return vazio(container, cfg.vazio);

    // Linha em branco entre grupos (ex.: regiões, cada uma com apurado e projetado)
    const categorias = [];
    const linhasComEspaco = [];
    for (const l of linhasDados) {
      if (l.grupoInicio) {
        categorias.push(' '.repeat(categorias.length + 1));
        linhasComEspaco.push(null);
      }
      categorias.push(l.rotulo);
      linhasComEspaco.push(l);
    }
    const alturaBarra = cfg.alturaBarra || 18;
    const grafico = instancia(container, 8 + categorias.length * (alturaBarra + (cfg.gap || 8)));
    const b = base();

    const nomes = [];
    const corPorNome = {};
    for (const l of linhasDados) {
      for (const s of l.segmentos) {
        if (!(s.rotulo in corPorNome)) { nomes.push(s.rotulo); corPorNome[s.rotulo] = s.cor; }
      }
    }
    const series = nomes.map((nome) => ({
      name: nome,
      type: 'bar',
      stack: 'total',
      barWidth: alturaBarra,
      data: linhasComEspaco.map((l) => {
        if (!l) return null;
        const seg = l.segmentos.find((s) => s.rotulo === nome);
        return seg ? +seg.valor.toFixed(4) : 0;
      }),
      itemStyle: { color: corPorNome[nome], borderColor: token('--superficie'), borderWidth: 1 },
      emphasis: { focus: 'self' },
      label: {
        show: true,
        color: textoSobre(corPorNome[nome]),
        fontSize: 11,
        fontWeight: 600,
        formatter: (p) => (p.value >= 7 ? `${p.value.toFixed(1).replace('.', ',')}%` : ''),
      },
    }));

    grafico.setOption({
      ...semEixo(b),
      grid: { left: cfg.margemRotulo || 120, right: 10, top: 4, bottom: 4 },
      xAxis: { type: 'value', show: false, max: 100 },
      yAxis: {
        type: 'category', inverse: true, data: categorias,
        ...b.eixo, axisLine: { show: false }, splitLine: { show: false },
      },
      tooltip: {
        ...b.tooltip, trigger: 'item',
        formatter: (it) => tituloTooltip(categorias[it.dataIndex]) +
          linhaTooltip(corPorNome[it.seriesName], `${(+it.value).toFixed(2).replace('.', ',')}%`, it.seriesName),
      },
      series,
    }, { notMerge: true });
  }

  // --------------------------------------------- tooltip HTML (mapa de UFs)
  function mostrarTooltip(evt, titulo, linhasTt) {
    tooltip.textContent = '';
    if (titulo) {
      const t = document.createElement('div');
      t.className = 'tt-titulo';
      t.textContent = titulo;
      tooltip.appendChild(t);
    }
    for (const l of linhasTt) {
      const row = document.createElement('div');
      row.className = 'tt-linha';
      if (l.cor) {
        const k = document.createElement('span');
        k.className = 'chave-linha';
        k.style.background = l.cor;
        row.appendChild(k);
      }
      const v = document.createElement('span');
      v.className = 'tt-valor';
      v.textContent = l.valor;
      const r = document.createElement('span');
      r.className = 'tt-rotulo';
      r.textContent = l.rotulo;
      row.append(v, r);
      tooltip.appendChild(row);
    }
    tooltip.hidden = false;
    const pad = 14;
    const w = tooltip.offsetWidth, h = tooltip.offsetHeight;
    let x = evt.clientX + pad, y = evt.clientY + pad;
    if (x + w > window.innerWidth - 8) x = evt.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = evt.clientY - h - pad;
    tooltip.style.left = `${Math.max(8, x)}px`;
    tooltip.style.top = `${Math.max(8, y)}px`;
  }

  function esconderTooltip() { tooltip.hidden = true; }

  return { linhas, histograma, barrasH, barrasEmpilhadas, vazio, mostrarTooltip, esconderTooltip, token };
})();
