/**
 * Graficos — mini biblioteca SVG do painel SPETR (sem dependências externas).
 * Linhas com faixa de incerteza e crosshair, histogramas, barras horizontais e empilhadas.
 * Todo texto vindo de dados é inserido com textContent.
 */
const Graficos = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const tooltip = document.getElementById('tooltip');

  function el(tag, attrs, pai) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v !== undefined && v !== null) n.setAttribute(k, v);
    }
    if (pai) pai.appendChild(n);
    return n;
  }

  function texto(pai, x, y, conteudo, attrs) {
    const t = el('text', { x, y, ...attrs }, pai);
    t.textContent = conteudo;
    return t;
  }

  function textoSobre(hex) {
    const m = (hex || '').replace('#', '');
    if (m.length !== 6) return '#ffffff';
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(m.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 ? '#0b0b0b' : '#ffffff';
  }

  const token = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();

  function passoBonito(intervalo, alvo) {
    const bruto = intervalo / Math.max(1, alvo);
    const mag = Math.pow(10, Math.floor(Math.log10(bruto)));
    const r = bruto / mag;
    return (r < 1.5 ? 1 : r < 3 ? 2 : r < 7 ? 5 : 10) * mag;
  }

  function marcas(min, max, alvo) {
    if (!(max > min)) return [min];
    const passo = passoBonito(max - min, alvo);
    const out = [];
    for (let v = Math.ceil(min / passo) * passo; v <= max + passo * 1e-6; v += passo) out.push(+v.toFixed(10));
    return out;
  }

  function preparar(container, altura) {
    container.textContent = '';
    const largura = Math.max(280, container.clientWidth || 600);
    const svg = el('svg', { viewBox: `0 0 ${largura} ${altura}`, height: altura, role: 'img' }, container);
    return { svg, largura };
  }

  function vazio(container, msg) {
    container.textContent = '';
    const d = document.createElement('div');
    d.className = 'vazio';
    d.textContent = msg || 'Aguardando dados';
    container.appendChild(d);
  }

  // ------------------------------------------------------------- tooltip
  function mostrarTooltip(evt, titulo, linhas) {
    tooltip.textContent = '';
    if (titulo) {
      const t = document.createElement('div');
      t.className = 'tt-titulo';
      t.textContent = titulo;
      tooltip.appendChild(t);
    }
    for (const l of linhas) {
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

  function eixos(g, { x0, x1, y0, y1, xs, ys, xEsc, yEsc, xFmt, yFmt }) {
    const grade = token('--grade'), eixo = token('--eixo');
    for (const v of ys) {
      const y = yEsc(v);
      el('line', { x1: x0, x2: x1, y1: y, y2: y, stroke: grade, 'stroke-width': 1 }, g);
      texto(g, x0 - 6, y + 4, yFmt(v), { class: 'eixo-texto', 'text-anchor': 'end' });
    }
    el('line', { x1: x0, x2: x1, y1: y0, y2: y0, stroke: eixo, 'stroke-width': 1 }, g);
    for (const v of xs) {
      texto(g, xEsc(v), y0 + 16, xFmt(v), { class: 'eixo-texto', 'text-anchor': 'middle' });
    }
  }

  function linhaRef(g, { horizontal, valor, esc, de, ate, rotulo }) {
    const cor = token('--texto-3');
    if (horizontal) {
      const y = esc(valor);
      el('line', { x1: de, x2: ate, y1: y, y2: y, stroke: cor, 'stroke-width': 1, 'stroke-dasharray': '4 4' }, g);
      if (rotulo) texto(g, de + 4, y - 4, rotulo, { class: 'ref-texto' });
    } else {
      const x = esc(valor);
      el('line', { x1: x, x2: x, y1: de, y2: ate, stroke: cor, 'stroke-width': 1, 'stroke-dasharray': '4 4' }, g);
      if (rotulo) texto(g, x + 4, de + 10, rotulo, { class: 'ref-texto' });
    }
  }

  function separarRotulos(itens, minDist, topo, base) {
    itens.sort((a, b) => a.y - b.y);
    for (let i = 1; i < itens.length; i++) {
      if (itens[i].y - itens[i - 1].y < minDist) itens[i].y = itens[i - 1].y + minDist;
    }
    const excesso = itens.length ? itens[itens.length - 1].y - base : 0;
    if (excesso > 0) for (const it of itens) it.y = Math.max(topo, it.y - excesso);
    return itens;
  }

  // -------------------------------------------------------------- linhas
  /**
   * series: [{id, rotulo, rotuloCurto, cor, pontos: [{x, y, lo, hi}], banda, espessura}]
   */
  function linhas(container, cfg) {
    const altura = cfg.altura || 250;
    const series = cfg.series.filter((s) => s.pontos.length);
    if (!series.length) return vazio(container, cfg.vazio);
    const { svg, largura } = preparar(container, altura);
    const m = { esq: 46, dir: cfg.rotulosFim === false ? 14 : 118, topo: 12, base: 28 };
    const x0 = m.esq, x1 = largura - m.dir, yTopo = m.topo, y0 = altura - m.base;

    const todosX = series.flatMap((s) => s.pontos.map((p) => p.x));
    let xMin = cfg.xMin ?? Math.min(...todosX), xMax = cfg.xMax ?? Math.max(...todosX);
    if (xMax === xMin) xMax = xMin + 1;
    const todosY = series.flatMap((s) => s.pontos.flatMap((p) => [p.y, p.lo ?? p.y, p.hi ?? p.y]));
    let yMin = cfg.yMin ?? Math.min(...todosY), yMax = cfg.yMax ?? Math.max(...todosY);
    for (const r of cfg.refs || []) { yMin = Math.min(yMin, r.y); yMax = Math.max(yMax, r.y); }
    if (cfg.yMin === undefined || cfg.yMax === undefined) {
      const folga = (yMax - yMin) * 0.08 || 1;
      if (cfg.yMin === undefined) yMin = Math.max(cfg.yPiso ?? -Infinity, yMin - folga);
      if (cfg.yMax === undefined) yMax = Math.min(cfg.yTeto ?? Infinity, yMax + folga);
    }
    const xEsc = (v) => x0 + ((v - xMin) / (xMax - xMin)) * (x1 - x0);
    const yEsc = (v) => y0 - ((v - yMin) / (yMax - yMin || 1)) * (y0 - yTopo);

    const g = el('g', {}, svg);
    eixos(g, {
      x0, x1, y0, y1: yTopo, xEsc, yEsc,
      xs: marcas(xMin, xMax, Math.max(2, Math.floor((x1 - x0) / 90))),
      ys: marcas(yMin, yMax, 5),
      xFmt: cfg.xFmt, yFmt: cfg.yFmt,
    });
    for (const r of cfg.refs || []) linhaRef(g, { horizontal: true, valor: r.y, esc: yEsc, de: x0, ate: x1, rotulo: r.rotulo });

    const sup = token('--superficie');
    for (const s of series) {
      if (s.banda) {
        const pts = s.pontos.filter((p) => p.lo !== undefined && p.hi !== undefined);
        if (pts.length > 1) {
          const d = pts.map((p, i) => `${i ? 'L' : 'M'}${xEsc(p.x)},${yEsc(p.hi)}`).join('') +
            pts.slice().reverse().map((p) => `L${xEsc(p.x)},${yEsc(p.lo)}`).join('') + 'Z';
          el('path', { d, fill: s.cor, 'fill-opacity': 0.14, stroke: 'none' }, g);
        }
      }
    }
    for (const s of series) {
      const d = s.pontos.map((p, i) => `${i ? 'L' : 'M'}${xEsc(p.x)},${yEsc(p.y)}`).join('');
      el('path', { d, fill: 'none', stroke: s.cor, 'stroke-width': s.espessura || 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, g);
      const ult = s.pontos[s.pontos.length - 1];
      el('circle', { cx: xEsc(ult.x), cy: yEsc(ult.y), r: 4, fill: s.cor, stroke: sup, 'stroke-width': 2 }, g);
    }

    if (cfg.rotulosFim !== false) {
      const itens = series.slice(0, cfg.maxRotulos || 6).map((s) => {
        const ult = s.pontos[s.pontos.length - 1];
        return { s, y: yEsc(ult.y) + 4, valor: ult.y };
      });
      for (const it of separarRotulos(itens, 13, yTopo + 4, y0)) {
        texto(g, x1 + 8, it.y, `${it.s.rotuloCurto || it.s.rotulo} ${cfg.yFmt(it.valor)}`, { class: 'rotulo-direto' });
      }
    }

    // Crosshair + tooltip com todas as séries no X mais próximo
    const xsUnicos = [...new Set(todosX)].sort((a, b) => a - b);
    const cruz = el('line', { y1: yTopo, y2: y0, stroke: token('--texto-3'), 'stroke-width': 1, visibility: 'hidden' }, g);
    const alvo = el('rect', { x: x0, y: yTopo, width: Math.max(1, x1 - x0), height: y0 - yTopo, fill: 'transparent' }, svg);
    alvo.addEventListener('pointermove', (evt) => {
      const r = svg.getBoundingClientRect();
      const px = ((evt.clientX - r.left) / r.width) * largura;
      const vx = xMin + ((px - x0) / (x1 - x0)) * (xMax - xMin);
      let melhor = xsUnicos[0];
      for (const v of xsUnicos) if (Math.abs(v - vx) < Math.abs(melhor - vx)) melhor = v;
      cruz.setAttribute('x1', xEsc(melhor));
      cruz.setAttribute('x2', xEsc(melhor));
      cruz.setAttribute('visibility', 'visible');
      const linhasTt = [];
      for (const s of series) {
        let p = s.pontos[0];
        for (const q of s.pontos) if (Math.abs(q.x - melhor) < Math.abs(p.x - melhor)) p = q;
        const faixa = (p.lo !== undefined && s.banda) ? `  [${cfg.yFmt(p.lo)} – ${cfg.yFmt(p.hi)}]` : '';
        linhasTt.push({ cor: s.cor, valor: cfg.yFmt(p.y), rotulo: `${s.rotulo}${faixa}`, ordem: p.y });
      }
      linhasTt.sort((a, b) => b.ordem - a.ordem);
      mostrarTooltip(evt, cfg.xTitulo ? cfg.xTitulo(melhor) : cfg.xFmt(melhor), linhasTt);
    });
    alvo.addEventListener('pointerleave', () => { cruz.setAttribute('visibility', 'hidden'); esconderTooltip(); });
  }

  // ---------------------------------------------------------- histograma
  /** series: [{rotulo, cor, inicio, passo, freq: []}] desenhadas como áreas em degrau sobrepostas. */
  function histograma(container, cfg) {
    const altura = cfg.altura || 250;
    const series = (cfg.series || []).filter((s) => s && s.freq && s.freq.length);
    if (!series.length) return vazio(container, cfg.vazio);
    const { svg, largura } = preparar(container, altura);
    const m = { esq: 46, dir: 14, topo: 14, base: 28 };
    const x0 = m.esq, x1 = largura - m.dir, yTopo = m.topo, y0 = altura - m.base;

    let xMin = Math.min(...series.map((s) => s.inicio));
    let xMax = Math.max(...series.map((s) => s.inicio + s.passo * s.freq.length));
    for (const r of cfg.refs || []) { xMin = Math.min(xMin, r.x); xMax = Math.max(xMax, r.x); }
    const pad = (xMax - xMin) * 0.03 || 0.5;
    xMin -= pad; xMax += pad;
    // Densidade (% das simulações por unidade do eixo X) — classes de larguras diferentes ficam comparáveis
    const dens = (s, f) => f / s.passo;
    const yMax = Math.max(...series.flatMap((s) => s.freq.map((f) => dens(s, f)))) * 1.08 || 1;
    const xEsc = (v) => x0 + ((v - xMin) / (xMax - xMin)) * (x1 - x0);
    const yEsc = (v) => y0 - (v / yMax) * (y0 - yTopo);

    const g = el('g', {}, svg);
    eixos(g, {
      x0, x1, y0, y1: yTopo, xEsc, yEsc,
      xs: marcas(xMin, xMax, Math.max(2, Math.floor((x1 - x0) / 80))),
      ys: marcas(0, yMax, 4),
      xFmt: cfg.xFmt, yFmt: (v) => `${(v * 100).toFixed(v * 100 < 10 ? 1 : 0).replace('.', ',')}%`,
    });
    for (const r of cfg.refs || []) linhaRef(g, { horizontal: false, valor: r.x, esc: xEsc, de: yTopo, ate: y0, rotulo: r.rotulo });

    for (const s of series) {
      let d = `M${xEsc(s.inicio)},${y0}`;
      s.freq.forEach((f, i) => {
        const xa = xEsc(s.inicio + i * s.passo), xb = xEsc(s.inicio + (i + 1) * s.passo);
        d += `L${xa},${yEsc(dens(s, f))}L${xb},${yEsc(dens(s, f))}`;
      });
      d += `L${xEsc(s.inicio + s.freq.length * s.passo)},${y0}Z`;
      el('path', { d, fill: s.cor, 'fill-opacity': 0.22, stroke: s.cor, 'stroke-width': 1.5, 'stroke-linejoin': 'round' }, g);
    }

    const cruz = el('line', { y1: yTopo, y2: y0, stroke: token('--texto-3'), 'stroke-width': 1, visibility: 'hidden' }, g);
    const alvo = el('rect', { x: x0, y: yTopo, width: x1 - x0, height: y0 - yTopo, fill: 'transparent' }, svg);
    alvo.addEventListener('pointermove', (evt) => {
      const r = svg.getBoundingClientRect();
      const px = ((evt.clientX - r.left) / r.width) * largura;
      const vx = xMin + ((px - x0) / (x1 - x0)) * (xMax - xMin);
      cruz.setAttribute('x1', px); cruz.setAttribute('x2', px); cruz.setAttribute('visibility', 'visible');
      const linhasTt = series.map((s) => {
        const i = Math.floor((vx - s.inicio) / s.passo);
        const f = i >= 0 && i < s.freq.length ? s.freq[i] : 0;
        return { cor: s.cor, valor: `${(f * 100).toFixed(1).replace('.', ',')}%`, rotulo: `${s.rotulo} (classe de ${String(s.passo).replace('.', ',')} p.p.)` };
      });
      mostrarTooltip(evt, `em torno de ${cfg.xFmt(vx)}`, linhasTt);
    });
    alvo.addEventListener('pointerleave', () => { cruz.setAttribute('visibility', 'hidden'); esconderTooltip(); });
  }

  // ------------------------------------------------------ barras horiz.
  /** linhas: [{rotulo, valor, detalhe}] — uma série, uma cor. */
  function barrasH(container, cfg) {
    const linhasDados = cfg.linhas || [];
    if (!linhasDados.length) return vazio(container, cfg.vazio);
    const alturaBarra = cfg.alturaBarra || 16, gap = 6;
    const altura = 10 + linhasDados.length * (alturaBarra + gap) + 6;
    const { svg, largura } = preparar(container, altura);
    const x0 = cfg.margemRotulo || 60, x1 = largura - 86;
    const max = Math.max(...linhasDados.map((l) => l.valor)) || 1;
    const g = el('g', {}, svg);
    const cor = cfg.cor || token('--seq');
    linhasDados.forEach((l, i) => {
      const y = 8 + i * (alturaBarra + gap);
      texto(g, x0 - 8, y + alturaBarra - 4, l.rotulo, { class: 'eixo-texto', 'text-anchor': 'end' });
      const w = Math.max(l.valor > 0 ? 2 : 0, ((x1 - x0) * l.valor) / max);
      el('rect', { x: x0, y, width: w, height: alturaBarra, rx: 3, fill: cor }, g);
      texto(g, x0 + w + 6, y + alturaBarra - 4, cfg.fmt(l.valor), { class: 'rotulo-direto' });
      const alvo = el('rect', { x: 0, y: y - gap / 2, width: largura, height: alturaBarra + gap, fill: 'transparent' }, svg);
      alvo.addEventListener('pointermove', (evt) => mostrarTooltip(evt, l.rotulo, [{ cor, valor: cfg.fmt(l.valor), rotulo: l.detalhe || '' }]));
      alvo.addEventListener('pointerleave', esconderTooltip);
    });
  }

  // ------------------------------------------------- barras empilhadas
  /** linhas: [{rotulo, segmentos: [{rotulo, cor, valor (0-100)}]}] — partes de 100%. */
  function barrasEmpilhadas(container, cfg) {
    const linhasDados = cfg.linhas || [];
    if (!linhasDados.length) return vazio(container, cfg.vazio);
    const alturaBarra = cfg.alturaBarra || 18, gap = cfg.gap || 8;
    const gapGrupo = 10;
    const grupos = linhasDados.filter((l) => l.grupoInicio).length;
    const altura = 8 + linhasDados.length * (alturaBarra + gap) + grupos * gapGrupo + 4;
    const { svg, largura } = preparar(container, altura);
    const x0 = cfg.margemRotulo || 120, x1 = largura - 10;
    const g = el('g', {}, svg);
    const sup = token('--superficie');
    let deslocamento = 0;
    linhasDados.forEach((l, i) => {
      if (l.grupoInicio) deslocamento += gapGrupo;
      const y = 6 + i * (alturaBarra + gap) + deslocamento;
      texto(g, x0 - 8, y + alturaBarra - 5, l.rotulo, { class: 'eixo-texto', 'text-anchor': 'end' });
      const total = l.segmentos.reduce((a, s) => a + s.valor, 0) || 1;
      let acc = 0;
      for (const s of l.segmentos) {
        const xa = x0 + ((x1 - x0) * acc) / total;
        const w = ((x1 - x0) * s.valor) / total;
        acc += s.valor;
        if (w <= 0) continue;
        const r = el('rect', { x: xa, y, width: Math.max(0, w - 2), height: alturaBarra, rx: 2, fill: s.cor, stroke: sup, 'stroke-width': 0 }, g);
        if (w > 46) {
          texto(g, xa + 5, y + alturaBarra - 5, `${s.valor.toFixed(1).replace('.', ',')}%`, {
            fill: textoSobre(s.cor), 'font-size': 11, 'font-weight': 600,
          });
        }
        const alvo = el('rect', { x: xa, y: y - gap / 2, width: Math.max(4, w), height: alturaBarra + gap, fill: 'transparent' }, svg);
        alvo.addEventListener('pointermove', (evt) => {
          r.setAttribute('opacity', 0.8);
          mostrarTooltip(evt, l.rotulo, [{ cor: s.cor, valor: `${s.valor.toFixed(2)}%`, rotulo: s.rotulo }]);
        });
        alvo.addEventListener('pointerleave', () => { r.removeAttribute('opacity'); esconderTooltip(); });
      }
    });
  }

  return { linhas, histograma, barrasH, barrasEmpilhadas, mostrarTooltip, esconderTooltip, token };
})();
