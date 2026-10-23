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

  // Medição de texto: as margens dos gráficos acompanham o maior rótulo, para nenhum valor ser cortado
  const contextoMedida = document.createElement('canvas').getContext('2d');
  function larguraTexto(texto, px = 11, peso = 400) {
    contextoMedida.font = `${peso} ${px}px ${token('--fonte') || 'system-ui, sans-serif'}`;
    return contextoMedida.measureText(String(texto)).width;
  }
  /** Margem (px) que comporta o maior dos textos, limitada a uma fração da largura do gráfico. */
  function margemTextos(container, textos, { px = 11, peso = 400, extra = 0, minimo = 0, fracao = 0.45 } = {}) {
    const maior = Math.max(0, ...textos.map((t) => larguraTexto(t, px, peso)));
    const teto = Math.max(minimo, (container.clientWidth || 600) * fracao);
    return Math.min(Math.max(minimo, Math.ceil(maior + extra)), teto);
  }

  // ------------------------------------------------------------ infraestrutura

  /** Instância ECharts do container (criada uma vez; redimensionada a cada desenho). */
  function instancia(container, altura) {
    const msg = container.querySelector(':scope > .vazio');
    if (msg) msg.remove();
    // Blocos "preenche" e o anel têm a altura dada pelo layout (CSS); os demais, pela quantidade de dados
    if (altura && !container.classList.contains('preenche') && !container.classList.contains('grafico-anel')) {
      container.style.height = `${altura}px`;
    }
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
      grid: {
        left: 48, top: 14, bottom: 28,
        right: rotulosFim ? margemTextos(container, series.slice(0, maxRotulos).map((s) => {
          const u = s.pontos[s.pontos.length - 1];
          return `${s.rotuloCurto || s.rotulo} ${cfg.yFmt(u.y)}`;
        }), { peso: 600, extra: 16, minimo: 80 }) : 16,
      },
      xAxis: {
        type: 'value', min: xMin, max: xMax, ...b.eixo,
        splitLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => cfg.xFmt(v), hideOverlap: true, showMinLabel: false, showMaxLabel: false },
      },
      yAxis: {
        type: 'value', min: yMin, max: yMax, ...b.eixo,
        axisLine: { show: false },
        interval: yMin === 0 && yMax === 100 ? 20 : undefined, splitNumber: 4,
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
      grid: { left: 16, right: 16, top: 18, bottom: 28 },
      legend: series.length > 1 ? { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: token('--texto-2'), fontSize: 11 } } : undefined,
      xAxis: {
        type: 'value', min: xMin - pad, max: xMax + pad, ...b.eixo, splitLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => cfg.xFmt(v), hideOverlap: true, showMinLabel: false, showMaxLabel: false },
      },
      yAxis: {
        type: 'value', min: 0, ...b.eixo, axisLine: { show: false },
        axisLabel: { show: false },
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
              `${s.rotulo} · dos cenários nesta faixa`);
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
      grid: {
        left: margemTextos(container, linhasDados.map((l) => l.rotulo), { extra: 14, minimo: cfg.margemRotulo || 60 }),
        right: margemTextos(container, linhasDados.map((l) => cfg.fmt(l.valor)), { peso: 600, extra: 18, minimo: 86 }),
        top: 4, bottom: 4,
      },
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
      grid: { left: margemTextos(container, categorias, { extra: 14, minimo: cfg.margemRotulo || 120 }), right: 10, top: 4, bottom: 4 },
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

  // ------------------------------------------------- corrida até 100%
  /**
   * Votos acumulados × % das seções apuradas. Área preenchida = caminho real até agora;
   * pontilhado = do ponto atual até a projeção em 100%, com barra do IC 95% no fim.
   * series: [{id, rotulo, rotuloCurto, cor, pontos: [{x, y}], final: {y, lo, hi}}]
   */
  function corrida(container, cfg) {
    const series = cfg.series.filter((s) => s.pontos.length);
    if (!series.length) return vazio(container, cfg.vazio);
    const grafico = instancia(container, 300);
    const b = base();
    const agora = Math.max(...series.map((s) => s.pontos[s.pontos.length - 1].x));
    const maxY = Math.max(...series.map((s) => Math.max(s.final.hi || 0, s.final.y, ...s.pontos.map((p) => p.y))));
    const [, yMax] = limitesBonitos(0, maxY * 1.04);

    const opcoes = [];
    series.forEach((s, i) => {
      const ult = s.pontos[s.pontos.length - 1];
      opcoes.push({
        id: `real-${s.id}`, name: s.rotulo, type: 'line', data: s.pontos.map((p) => [p.x, p.y, p.det ?? '']),
        showSymbol: false, smooth: 0.2, z: 3,
        lineStyle: { color: s.cor, width: 2 },
        itemStyle: { color: s.cor },
        areaStyle: { color: s.cor, opacity: cfg.opacidadeArea ?? 0.22 },
        markLine: i === 0 ? {
          silent: true, symbol: 'none',
          lineStyle: { color: token('--texto-3'), type: [4, 4], width: 1 },
          label: { formatter: `agora · ${cfg.xFmt(agora)}`, color: token('--texto-2'), fontSize: 11, position: 'end' },
          data: [{ xAxis: agora }],
        } : undefined,
      });
      opcoes.push({
        id: `proj-${s.id}`, name: s.rotulo, type: 'line', data: [[ult.x, ult.y], [100, s.final.y]],
        showSymbol: false, z: 2, silent: true, tooltip: { show: false },
        lineStyle: { color: s.cor, width: 2, type: [2, 4] },
        endLabel: i < (cfg.maxRotulos || 6) ? {
          show: true, formatter: () => `${s.rotuloCurto || s.rotulo} ${s.final.rotulo || cfg.yFmt(s.final.y)}`,
          color: token('--texto-2'), fontSize: 11, fontWeight: 600, distance: 8,
        } : { show: false },
        labelLayout: { moveOverlap: 'shiftY' },
      });
      if (s.final.lo !== undefined) {
        opcoes.push({
          id: `ic-${s.id}`, type: 'line', data: [[100, s.final.lo], [100, s.final.hi]],
          showSymbol: true, symbol: 'rect', symbolSize: [8, 2], silent: true, tooltip: { show: false }, z: 4,
          lineStyle: { color: s.cor, width: 2 }, itemStyle: { color: s.cor },
        });
      }
    });

    grafico.setOption({
      ...semEixo(b),
      grid: {
        left: 52, top: 18, bottom: 28,
        right: margemTextos(container, series.map((s) => `${s.rotuloCurto || s.rotulo} ${s.final.rotulo || cfg.yFmt(s.final.y)}`),
          { peso: 600, extra: 20, minimo: cfg.margemDireita || 118 }),
      },
      xAxis: {
        type: 'value', min: 0, max: 100, interval: 20, ...b.eixo, splitLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => `${v}%` },
      },
      yAxis: {
        type: 'value', min: 0, max: yMax, ...b.eixo, axisLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => (cfg.yFmtEixo || cfg.yFmt)(v) },
        splitNumber: 4,
      },
      tooltip: {
        ...b.tooltip, trigger: 'axis',
        axisPointer: { type: 'line', lineStyle: { color: token('--texto-3'), width: 1 } },
        formatter: (itens) => {
          const reais = itens.filter((it) => String(it.seriesId).startsWith('real-'));
          if (!reais.length) return '';
          const linhasTt = reais.sort((a, c) => c.value[1] - a.value[1]).map((it) => {
            const s = series.find((ss) => `real-${ss.id}` === it.seriesId);
            const det = it.value[2] ? ` (${it.value[2]})` : '';
            return linhaTooltip(s.cor, `${cfg.yFmt(it.value[1])}${det}`,
              `${s.rotulo} · final projetado ${s.final.rotulo || cfg.yFmt(s.final.y)} [${cfg.yFmt(s.final.lo)} – ${cfg.yFmt(s.final.hi)}]`);
          }).join('');
          return tituloTooltip(`${cfg.xFmt(reais[0].value[0])} das seções apuradas`) + linhasTt;
        },
      },
      series: opcoes,
    }, { notMerge: true });
  }

  // ------------------------------------------------ intervalos de projeção
  /** itens: [{rotulo, cor, lo, hi, media, apurado}] — um intervalo horizontal por candidato. */
  function intervalos(container, cfg) {
    const itens = cfg.itens || [];
    if (!itens.length) return vazio(container, cfg.vazio);
    const grafico = instancia(container, 40 + itens.length * 30);
    const b = base();
    const sup = token('--superficie');
    const [, xMax] = limitesBonitos(0, Math.max(55, ...itens.map((i) => i.hi)) * 1.02);
    const categorias = itens.map((i) => i.rotulo);
    const margemEsq = margemTextos(container, categorias, { extra: 30, minimo: 118 });
    grafico.setOption({
      ...semEixo(b),
      grid: {
        left: margemEsq, top: 10, bottom: 26,
        right: margemTextos(container, itens.map((i) => cfg.fmt(i.media)), { peso: 700, extra: 28, minimo: 56 }),
      },
      xAxis: {
        type: 'value', min: 0, max: xMax, ...b.eixo,
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => `${v}%` },
      },
      yAxis: {
        type: 'category', inverse: true, data: categorias, ...b.eixo, axisLine: { show: false }, splitLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, color: token('--texto-2'), width: margemEsq - 12, overflow: 'break', interval: 0 },
      },
      tooltip: {
        ...b.tooltip, trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: token('--grade'), opacity: 0.5 } },
        formatter: (ps) => {
          const it = itens[ps[0].dataIndex];
          return tituloTooltip(it.rotulo) +
            linhaTooltip(it.cor, `${cfg.fmt(it.media)}`, 'projeção') +
            linhaTooltip(it.cor, `${cfg.fmt(it.lo)} – ${cfg.fmt(it.hi)}`, 'faixa provável') +
            linhaTooltip(token('--texto-3'), `${cfg.fmt(it.apurado)}`, 'apurado até agora');
        },
      },
      series: [
        { type: 'bar', stack: 'ic', silent: true, itemStyle: { color: 'transparent' }, data: itens.map((i) => i.lo), barWidth: 12 },
        {
          type: 'bar', stack: 'ic', barWidth: 12,
          data: itens.map((i) => ({ value: Math.max(0.05, i.hi - i.lo), itemStyle: { color: i.cor, opacity: 0.35, borderRadius: 6 } })),
          markLine: (cfg.refs || []).length ? {
            silent: true, symbol: 'none', lineStyle: { color: token('--texto-3'), type: [4, 4], width: 1 },
            label: { show: false },
            data: cfg.refs.map((r) => ({ xAxis: r.x })),
          } : undefined,
        },
        {
          type: 'scatter', symbol: 'circle', symbolSize: 11, z: 4,
          data: itens.map((i, k) => ({ value: [i.media, k], itemStyle: { color: i.cor, borderColor: sup, borderWidth: 2 } })),
          encode: { x: 0, y: 1 },
          label: { show: true, position: 'right', distance: 10, formatter: (p) => cfg.fmt(p.value[0]), color: token('--texto'), fontSize: 11, fontWeight: 700 },
        },
        {
          type: 'scatter', symbol: 'circle', symbolSize: 8, z: 5,
          data: itens.map((i, k) => [i.apurado, k]), encode: { x: 0, y: 1 },
          itemStyle: { color: sup, borderColor: token('--texto-2'), borderWidth: 2 },
        },
      ],
    }, { notMerge: true });
  }

  // ------------------------------------------------------- anel (gauge)
  function anel(container, valor) {
    const grafico = instancia(container);
    grafico.setOption({
      series: [{
        type: 'gauge', startAngle: 90, endAngle: -270, min: 0, max: 100, radius: '96%',
        pointer: { show: false },
        progress: { show: true, roundCap: true, width: 8, itemStyle: { color: token('--seq') } },
        axisLine: { lineStyle: { width: 8, color: [[1, token('--neutro-claro')]] } },
        splitLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false },
        title: { show: false },
        detail: {
          valueAnimation: true, offsetCenter: [0, 0], fontSize: 14, fontWeight: 700, color: token('--texto'),
          fontFamily: token('--fonte') || 'system-ui', formatter: (v) => `${v.toFixed(1).replace('.', ',')}%`,
        },
        data: [{ value: +(valor || 0).toFixed(2) }],
      }],
    }, { notMerge: true });
  }

  // ----------------------------------------------------------------- mapa
  let mapaRegistrado = null;

  async function garantirMapa() {
    if (!mapaRegistrado) {
      mapaRegistrado = fetch('/static/geo/brasil-ufs.json').then((r) => r.json()).then((geo) => {
        echarts.registerMap('brasil', geo);
        return Object.fromEntries(geo.features.map((f) => [f.properties.name, f.properties.nome]));
      });
    }
    return mapaRegistrado;
  }

  /**
   * cfg.dados: [{uf, cor (modo categórico) | valor (modo contínuo), tooltip: {titulo, linhas}}]
   * cfg.escala: undefined (cores por item) ou {min, max, cores: [...], rotulos: [baixo, alto]}
   */
  async function mapa(container, cfg) {
    const nomes = await garantirMapa();
    const grafico = instancia(container);
    const b = base();
    const porUf = Object.fromEntries((cfg.dados || []).map((d) => [d.uf, d]));
    const vazioCor = token('--neutro-claro');
    const serieDados = Object.keys(nomes).map((uf) => {
      const d = porUf[uf];
      const item = { name: uf, selected: uf === cfg.selecionada };
      if (!d) return { ...item, value: null, itemStyle: { areaColor: vazioCor } };
      if (cfg.escala) return { ...item, value: d.valor };
      return { ...item, value: 1, itemStyle: { areaColor: d.cor } };
    });
    grafico.setOption({
      ...semEixo(b),
      tooltip: {
        ...b.tooltip, trigger: 'item',
        formatter: (p) => {
          const d = porUf[p.name];
          if (!d) return tituloTooltip(`${nomes[p.name] || p.name} · sem dados`);
          return tituloTooltip(`${nomes[p.name]} (${p.name}) · ${d.tooltip.titulo}`) +
            d.tooltip.linhas.map((l) => linhaTooltip(l.cor, l.valor, l.rotulo)).join('');
        },
      },
      visualMap: cfg.escala ? {
        type: 'continuous', min: cfg.escala.min, max: cfg.escala.max, calculable: false, orient: 'horizontal',
        left: 'center', bottom: 0, itemWidth: 10, itemHeight: 160, text: cfg.escala.rotulos,
        textStyle: { color: token('--texto-2'), fontSize: 11 }, inRange: { color: cfg.escala.cores },
        seriesIndex: 0,
      } : undefined,
      series: [{
        type: 'map', map: 'brasil', roam: false, selectedMode: 'single',
        layoutCenter: ['50%', cfg.escala ? '47%' : '50%'], layoutSize: cfg.escala ? '92%' : '98%',
        label: { show: true, fontSize: 9, fontWeight: 600, color: token('--texto') },
        labelLayout: { hideOverlap: true },
        itemStyle: { borderColor: token('--superficie'), borderWidth: 1, areaColor: vazioCor },
        emphasis: { label: { show: true, color: token('--texto') }, itemStyle: { areaColor: undefined, borderColor: token('--texto'), borderWidth: 1.5 } },
        select: { label: { show: true, color: token('--texto') }, itemStyle: { borderColor: token('--texto'), borderWidth: 2.5 } },
        data: serieDados,
      }],
    }, { notMerge: true });
    grafico.off('click');
    if (cfg.aoClicar) grafico.on('click', (p) => cfg.aoClicar(p.name));
  }

  // --------------------------------------------------------------- colunas
  /** Barras verticais: categorias × valores (uma cor, ou cor por item). */
  function colunas(container, cfg) {
    const cats = cfg.categorias || [];
    if (!cats.length) return vazio(container, cfg.vazio);
    const grafico = instancia(container, 240);
    const b = base();
    const cor = cfg.cor || token('--seq');
    grafico.setOption({
      ...semEixo(b),
      grid: {
        left: 48, top: (cfg.grupos || []).length ? 40 : 22, bottom: 24,
        right: cfg.ref !== undefined && cfg.refRotulo ? margemTextos(container, [cfg.refRotulo], { px: 10, extra: 14, minimo: 14 }) : 14,
      },
      xAxis: { type: 'category', data: cats, ...b.eixo, axisLabel: { ...b.eixo.axisLabel, interval: 0, fontSize: 10 } },
      yAxis: {
        type: 'value', min: 0, max: cfg.max, ...b.eixo, axisLine: { show: false },
        axisLabel: { ...b.eixo.axisLabel, formatter: (v) => cfg.fmtEixo ? cfg.fmtEixo(v) : cfg.fmt(v) },
      },
      tooltip: {
        ...b.tooltip, trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: token('--grade'), opacity: 0.5 } },
        formatter: (ps) => {
          const i = ps[0].dataIndex;
          return tituloTooltip(cfg.titulos ? cfg.titulos[i] : cats[i]) +
            linhaTooltip(cfg.cores ? cfg.cores[i] : cor, cfg.fmt(cfg.valores[i]), cfg.detalhes ? cfg.detalhes[i] : '');
        },
      },
      series: [{
        type: 'bar', barMaxWidth: 22,
        data: cfg.valores.map((v, i) => ({ value: v, itemStyle: { color: cfg.cores ? cfg.cores[i] : cor, borderRadius: [3, 3, 0, 0] } })),
        markLine: cfg.ref !== undefined || (cfg.grupos || []).length ? {
          silent: true, symbol: 'none',
          lineStyle: { color: token('--texto-3'), type: [4, 4], width: 1 },
          label: { color: token('--texto-2'), fontSize: 10 },
          data: [
            ...(cfg.ref !== undefined ? [{ yAxis: cfg.ref, label: { formatter: cfg.refRotulo || '', position: 'end' } }] : []),
            // média de cada grupo: segmento só sobre as colunas da região
            ...(cfg.grupos || []).filter((g) => g.media !== undefined).map((g) => [
              { coord: [cats[g.inicio], g.media], lineStyle: { type: 'solid', width: 2, color: token('--texto-2') },
                label: { show: false } },
              { coord: [cats[g.fim], g.media] },
            ]),
          ],
        } : undefined,
        markArea: (cfg.grupos || []).length ? {
          silent: true,
          label: { color: token('--texto-2'), fontSize: 11, fontWeight: 600, position: 'top', distance: 4 },
          data: cfg.grupos.map((g, i) => [
            { xAxis: cats[g.inicio], name: g.nome, itemStyle: { color: i % 2 ? 'transparent' : token('--superficie-2') } },
            { xAxis: cats[g.fim] },
          ]),
        } : undefined,
      }],
    }, { notMerge: true });
  }

  // ----------------------------------------- barras agrupadas (apurado × projetado)
  /** itens: [{rotulo, cor, apurado, projetado}] */
  function apuradoProjetado(container, cfg) {
    const itens = cfg.itens || [];
    if (!itens.length) return vazio(container, cfg.vazio);
    const grafico = instancia(container, 40 + itens.length * 34);
    const b = base();
    const margemEsq = margemTextos(container, itens.map((i) => i.rotulo), { extra: 30, minimo: 108 });
    const [, xMax] = limitesBonitos(0, Math.max(...itens.flatMap((i) => [i.apurado, i.projetado])) * 1.1);
    grafico.setOption({
      ...semEixo(b),
      legend: { top: 0, right: 0, itemWidth: 10, itemHeight: 10, textStyle: { color: token('--texto-2'), fontSize: 11 },
        data: [{ name: 'Apurado', itemStyle: { color: token('--neutro'), opacity: 0.45 } }, { name: 'Projetado', itemStyle: { color: token('--neutro') } }] },
      grid: {
        left: margemEsq, top: 22, bottom: 4,
        right: margemTextos(container, itens.map((i) => cfg.fmt(i.projetado)), { px: 10, peso: 600, extra: 18, minimo: 48 }),
      },
      xAxis: { type: 'value', show: false, max: xMax },
      yAxis: {
        type: 'category', inverse: true, data: itens.map((i) => i.rotulo), ...b.eixo, axisLine: { show: false },
        splitLine: { show: false }, axisLabel: { ...b.eixo.axisLabel, color: token('--texto-2'), width: margemEsq - 12, overflow: 'break' },
      },
      tooltip: {
        ...b.tooltip, trigger: 'axis', axisPointer: { type: 'shadow', shadowStyle: { color: token('--grade'), opacity: 0.5 } },
        formatter: (ps) => {
          const it = itens[ps[0].dataIndex];
          return tituloTooltip(it.rotulo) + linhaTooltip(it.cor, cfg.fmt(it.apurado), 'apurado') + linhaTooltip(it.cor, cfg.fmt(it.projetado), 'projetado');
        },
      },
      series: [
        {
          name: 'Apurado', type: 'bar', barGap: '15%', barWidth: 9,
          data: itens.map((i) => ({ value: i.apurado, itemStyle: { color: i.cor, opacity: 0.45, borderRadius: [0, 3, 3, 0] } })),
        },
        {
          name: 'Projetado', type: 'bar', barWidth: 9,
          data: itens.map((i) => ({ value: i.projetado, itemStyle: { color: i.cor, borderRadius: [0, 3, 3, 0] } })),
          label: { show: true, position: 'right', formatter: (p) => cfg.fmt(p.value), color: token('--texto-2'), fontSize: 10, fontWeight: 600 },
        },
      ],
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

  return {
    linhas, histograma, barrasH, barrasEmpilhadas, corrida, intervalos, anel, mapa, colunas, apuradoProjetado,
    vazio, mostrarTooltip, esconderTooltip, token,
  };
})();
