/**
 * SPETR — Painel de apuração e projeção.
 * Carrega o histórico da execução atual, recebe atualizações via SSE e redesenha o painel.
 */
const G = Graficos;

const state = {
  historico: [],          // resultados resumidos por ciclo (curvas)
  atual: null,            // último resultado completo (com análise detalhada)
  eixo: 'tempo',
  ufSelecionada: null,
  ordemUf: { chave: 'restantes', desc: true },
  slots: {},              // número do candidato -> slot de cor (fixo para a entidade)
  candidatos: {},         // número -> {nome, partido}
};

const SLOTS = 7;
const fmtInt = new Intl.NumberFormat('pt-BR');
const fmtPct1 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmtPct2 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = (v, casas = 2) => (v === null || v === undefined || Number.isNaN(v)) ? '—' : `${(casas === 1 ? fmtPct1 : fmtPct2).format(v)}%`;
const prob = (p) => {
  if (p === null || p === undefined) return '—';
  const v = p * 100;
  if (v > 0 && v < 0.1) return '<0,1%';
  if (v < 100 && v > 99.9) return '>99,9%';
  return `${fmtPct1.format(v)}%`;
};
function compacto(n) {
  if (n === null || n === undefined) return '—';
  const a = Math.abs(n);
  if (a >= 1e6) return `${fmtPct2.format(n / 1e6)} mi`;
  if (a >= 1e3) return `${fmtPct1.format(n / 1e3)} mil`;
  return fmtInt.format(Math.round(n));
}

const ROTULO_TIPO = {
  CAPITAL: 'Capitais',
  GRANDE_CIDADE: 'Cidades ≥ 100 mil eleitores',
  INTERIOR: 'Interior remanescente',
  UF_INTEIRA: 'UF sem decomposição',
  SEM_DADOS: 'Sem dados',
};

// Grade aproximada do mapa do Brasil (linha, coluna)
const MAPA = {
  RR: [0, 1], AP: [0, 3],
  AM: [1, 1], PA: [1, 2], MA: [1, 4], CE: [1, 5], RN: [1, 6],
  AC: [2, 0], RO: [2, 1], MT: [2, 2], TO: [2, 3], PI: [2, 4], PE: [2, 5], PB: [2, 6],
  MS: [3, 2], GO: [3, 3], DF: [3, 4], BA: [3, 5], AL: [3, 6],
  PR: [4, 2], SP: [4, 3], MG: [4, 4], ES: [4, 5], SE: [4, 6],
  SC: [5, 2], RJ: [5, 4],
  RS: [6, 2], ZZ: [6, 7],
};

// ----------------------------------------------------------------- utilidades

function armazenar(chave, valor) {
  try { localStorage.setItem(chave, JSON.stringify(valor)); } catch (e) { /* armazenamento indisponível */ }
}
function recuperar(chave, padrao) {
  try { const v = localStorage.getItem(chave); return v ? JSON.parse(v) : padrao; } catch (e) { return padrao; }
}

function cor(numero) {
  const s = state.slots[numero];
  return s === undefined ? G.token('--neutro') : G.token(`--s${s + 1}`);
}

function nome(numero) {
  const c = state.candidatos[numero];
  return c ? c.nome : `Nº ${numero}`;
}

function nomeCurto(numero) {
  const partes = nome(numero).split(/\s+/);
  return partes.length > 1 ? partes[partes.length - 1] : partes[0];
}

/** Cores seguem a entidade: atribuídas uma vez, por ordem de projeção no primeiro aparecimento. */
function atribuirCores(candidatos) {
  for (const c of candidatos) state.candidatos[c.numero] = { nome: c.nome, partido: c.partido };
  const usados = new Set(Object.values(state.slots));
  for (const c of [...candidatos].sort((a, b) => b.perc_projetado - a.perc_projetado)) {
    if (state.slots[c.numero] !== undefined) continue;
    let livre = -1;
    for (let i = 0; i < SLOTS; i++) if (!usados.has(i)) { livre = i; break; }
    if (livre < 0) break;
    state.slots[c.numero] = livre;
    usados.add(livre);
  }
}

function el(tag, attrs = {}, filhos = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'texto') n.textContent = v;
    else if (k === 'classe') n.className = v;
    else if (k === 'estilo') Object.assign(n.style, v);
    else n.setAttribute(k, v);
  }
  for (const f of [].concat(filhos)) if (f) n.appendChild(f);
  return n;
}

function luminancia(hex) {
  const m = hex.replace('#', '');
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(m.slice(i, i + 2), 16) / 255)
    .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

const tsParaMs = (ts) => {
  const d = new Date((ts || '').replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
};
const fmtHora = (ms) => new Date(ms).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
const fmtHoraSeg = (ms) => new Date(ms).toLocaleTimeString('pt-BR');

function valorX(r) {
  return state.eixo === 'tempo' ? tsParaMs(r.timestamp) : r.perc_secoes_apuradas;
}
function fmtHoraAdaptativo() {
  const xs = state.historico.map((r) => tsParaMs(r.timestamp));
  const curto = xs.length && Math.max(...xs) - Math.min(...xs) < 15 * 60 * 1000;
  return curto ? fmtHoraSeg : fmtHora;
}

function cfgEixoX() {
  return state.eixo === 'tempo'
    ? { xFmt: fmtHoraAdaptativo(), xTitulo: fmtHoraSeg }
    : { xFmt: (v) => `${fmtPct1.format(v)}%`, xTitulo: (v) => `${fmtPct2.format(v)}% das seções apuradas` };
}

function topoCandidatos(n) {
  const cands = state.atual ? state.atual.candidatos : [];
  return cands.slice(0, n).map((c) => c.numero);
}

// ------------------------------------------------------------- renderizações

function renderCabecalho(info) {
  const e = info.eleicao || {};
  state.info = e;
  const selo = document.getElementById('selo-modo');
  if (info.modo) {
    selo.hidden = false;
    selo.textContent = info.modo === 'simulado' ? 'SIMULAÇÃO' : 'COLETA REAL';
    selo.classList.toggle('simulado', info.modo === 'simulado');
  }
  const linkSim = document.getElementById('link-simulador');
  if (info.simulador_url) {
    linkSim.hidden = false;
    linkSim.href = info.simulador_url;
  }
  if (info.ultimo_aviso) mostrarAviso(info.ultimo_aviso);
  const partes = [];
  if (e.simulado) {
    const ritmos = { lenta: 'lento', normal: 'normal', rapida: 'rápido' };
    document.getElementById('info-eleicao').textContent = `Dados fictícios · ${e.descricao || ''} · ritmo ${ritmos[e.velocidade] || e.velocidade || ''}`;
    document.getElementById('rodape-fonte').textContent = 'Fonte: simulador local com candidatos fictícios. Não representa nenhuma eleição real.';
    state.chaveSlots = `spetr-slots:simulado:${e.cenario || ''}`;
    state.slots = recuperar(state.chaveSlots, {});
    if (e.simulacoes) document.getElementById('n-sim').textContent = fmtInt.format(e.simulacoes);
    return;
  }
  if (e.mock) partes.push('MOCK');
  if (e.ano) partes.push(`Eleições ${e.ano}`);
  partes.push(e.cargo === '1' || !e.cargo ? 'Presidente' : `Cargo ${e.cargo}`);
  if (e.turno) partes.push(`${e.turno}º turno`);
  if (e.codigo) partes.push(`eleição ${e.codigo}`);
  if (e.jws) partes.push(`JWS ${e.jws}`);
  document.getElementById('info-eleicao').textContent = partes.join(' · ');
  // Cores por candidato ficam guardadas por pleito (mock e eleição real não se misturam)
  state.chaveSlots = `spetr-slots:${e.ambiente || ''}:${e.ano || ''}:${e.codigo || 'auto'}:${e.cargo || ''}:${e.turno || ''}:${e.mock ? 'mock' : ''}`;
  state.slots = recuperar(state.chaveSlots, {});
  if (e.simulacoes) document.getElementById('n-sim').textContent = fmtInt.format(e.simulacoes);
}

function renderChamada(d) {
  const caixa = document.getElementById('chamada');
  const titulo = document.getElementById('chamada-titulo');
  const sub = document.getElementById('chamada-sub');
  const ic = document.getElementById('chamada-ic');
  caixa.className = 'chamada';
  const lider = d.candidatos[0];
  const vencedor = d.vencedor_projetado ? `${nome(d.vencedor_projetado)} (${d.vencedor_projetado})` : '';
  const semDados = d.ufs_sem_dados || [];

  if (d.status_call === 'MATEMATICAMENTE_ELEITO') {
    caixa.classList.add('eleito');
    titulo.textContent = `✓ Matematicamente eleito: ${vencedor}`;
    sub.textContent = 'Mesmo que todos os votos restantes fossem para os adversários, manteria mais de 50% dos válidos.';
  } else if (d.status_call === 'VITORIA_PROJETADA') {
    caixa.classList.add('projetada');
    titulo.textContent = `Vitória projetada: ${vencedor}`;
    sub.textContent = `Probabilidade ≥ 99,5% de terminar com mais de 50% dos válidos (${prob(lider.prob_vitoria)}).`;
  } else if (d.status_call === 'SEGUNDO_TURNO_PROJETADO') {
    caixa.classList.add('segundo-turno');
    const [a, b] = d.candidatos;
    titulo.textContent = '↻ Segundo turno projetado';
    sub.textContent = `Chance de ninguém atingir 50% dos válidos: ${prob(d.prob_segundo_turno)}. ` +
      (a && b ? `Mais prováveis no 2º turno: ${a.nome} e ${b.nome}.` : '');
  } else {
    titulo.textContent = 'Apuração em andamento · disputa em aberto';
    sub.textContent = `Líder projetado: ${lider ? `${lider.nome} (${pct(lider.perc_projetado)})` : '—'} · ` +
      `chance de 2º turno ${prob(d.prob_segundo_turno)}` +
      (semDados.length ? ` · ${semDados.length} UF(s) ainda sem dados (${semDados.join(', ')}), projetadas pelo prior` : '');
  }
  ic.textContent = lider ? `Margem projetada 1º–2º: ${fmtPct2.format(d.lider_margem)} p.p.` : '';
}

function kpi(rotulo, valor, detalhe, medidor) {
  const filhos = [el('div', { classe: 'kpi-rotulo', texto: rotulo }), el('div', { classe: 'kpi-valor', texto: valor })];
  if (medidor !== undefined) {
    filhos.push(el('div', { classe: 'medidor' }, [el('span', { estilo: { width: `${Math.min(100, Math.max(0, medidor))}%` } })]));
  }
  if (detalhe) filhos.push(el('div', { classe: 'kpi-detalhe', texto: detalhe }));
  return el('div', { classe: 'kpi' }, filhos);
}

function renderKpis(d) {
  const n = (d.analise && d.analise.nacional) || {};
  const f = (d.analise && d.analise.faltam) || {};
  const caixa = document.getElementById('kpis');
  caixa.textContent = '';
  caixa.append(
    kpi('Seções apuradas', pct(d.perc_secoes_apuradas), `${fmtInt.format(d.secoes_apuradas)} de ${fmtInt.format(d.total_secoes)}`, d.perc_secoes_apuradas),
    kpi('Votos válidos apurados', compacto(d.total_validos_apurados), `Projeção final: ${compacto(d.total_validos_projetados)}`),
    kpi('Comparecimento', pct(n.pct_comparecimento), `Abstenção ${pct(n.pct_abstencao)} · ${compacto(n.comparecimento)} votantes`),
    kpi('Brancos e nulos', pct((n.pct_brancos || 0) + (n.pct_nulos || 0)), `Brancos ${pct(n.pct_brancos)} · nulos ${pct(n.pct_nulos)}`),
    kpi('Votos anulados (sub judice)', pct(n.pct_anulados), `${compacto(n.votos_anulados)} votos fora dos válidos`),
    kpi('Chance de 2º turno', prob(d.prob_segundo_turno), 'ninguém com > 50% dos válidos'),
    kpi('Válidos que faltam', compacto(f.validos_restantes_esperados), `Máximo possível: ${compacto(f.votos_restantes_maximos)}`),
  );
}

function faixaIc(c, escMin, escMax) {
  const pos = (v) => `${((v - escMin) / (escMax - escMin)) * 100}%`;
  const corC = cor(c.numero);
  const filhos = [el('span', { classe: 'trilho' })];
  if (escMin < 50 && escMax > 50) filhos.push(el('span', { classe: 'cinquenta', estilo: { left: pos(50) }, title: '50%' }));
  filhos.push(
    el('span', { classe: 'ic', estilo: { left: pos(c.ic_inferior_95), width: `calc(${pos(c.ic_superior_95)} - ${pos(c.ic_inferior_95)})`, background: corC } }),
    el('span', { classe: 'media', estilo: { left: pos(c.perc_projetado), background: corC } }),
    el('span', { classe: 'apur', estilo: { left: pos(c.perc_apurado) } }),
  );
  return el('div', {
    classe: 'faixa',
    title: `Apurado ${pct(c.perc_apurado)} (círculo) · projetado ${pct(c.perc_projetado)} · IC 95% ${pct(c.ic_inferior_95)} – ${pct(c.ic_superior_95)}`,
  }, filhos);
}

function tituloProprio(t) {
  const minusculas = new Set(['de', 'da', 'do', 'das', 'dos', 'e']);
  return String(t || '').toLowerCase().split(/\s+/)
    .map((p, i) => (i > 0 && minusculas.has(p)) ? p : p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
}

function descricaoChapa(c) {
  const partes = [c.nome_completo || c.nome];
  if (c.vice) partes.push(`Vice: ${c.vice}`);
  if (c.coligacao) partes.push(`${c.coligacao}: ${c.composicao}`);
  return partes.join(' · ');
}

function renderCandidatosAguardando(d) {
  document.getElementById('nota-candidatos').textContent =
    'Candidatos cadastrados nos arquivos do TSE, em ordem alfabética. Votos e projeção aparecem com o início da apuração.';
  const corpo = document.querySelector('#tabela-candidatos tbody');
  corpo.textContent = '';
  for (const c of d.candidatos) {
    corpo.appendChild(el('tr', {}, [
      el('td', {}, [el('div', { classe: 'cand-nome' }, [
        el('span', { classe: 'chave-bloco', estilo: { background: G.token('--neutro-claro') } }),
        el('div', { title: descricaoChapa(c) }, [
          el('strong', { texto: c.nome }),
          el('small', { texto: `${c.partido || '—'} · Nº ${c.numero}${c.vice ? ` · vice ${tituloProprio(c.vice)}` : ''}` }),
          c.coligacao ? el('small', { texto: `${tituloProprio(c.coligacao)} (${c.composicao})` }) : null,
        ]),
      ])]),
      el('td', { classe: 'num', texto: '0' }),
      ...Array.from({ length: 7 }, () => el('td', { classe: 'num', texto: '—' })),
    ]));
  }
}

function renderCandidatos(d) {
  const nota = document.getElementById('nota-candidatos');
  if (!nota.querySelector('#n-sim')) {
    nota.textContent = '';
    nota.append('Valores já apurados e projeção final (média de ', el('span', { id: 'n-sim', texto: fmtInt.format((state.info && state.info.simulacoes) || 10000) }), ' simulações). Ordenado pela projeção.');
  }
  const corpo = document.querySelector('#tabela-candidatos tbody');
  corpo.textContent = '';
  const top2 = (d.analise && d.analise.prob_top2) || {};
  const escMax = Math.min(100, Math.max(55, ...d.candidatos.map((c) => c.ic_superior_95)) + 2);
  for (const c of d.candidatos) {
    const delta = c.perc_projetado - c.perc_apurado;
    const tr = el('tr', {}, [
      el('td', {}, [el('div', { classe: 'cand-nome' }, [
        el('span', { classe: 'chave-bloco', estilo: { background: cor(c.numero) } }),
        el('div', { title: descricaoChapa(c) }, [
          el('strong', { texto: c.nome }),
          el('small', { texto: `${c.partido || '—'} · Nº ${c.numero}${c.vice ? ` · vice ${tituloProprio(c.vice)}` : ''}` }),
          c.coligacao ? el('small', { texto: `${tituloProprio(c.coligacao)} (${c.composicao})` }) : null,
        ]),
      ])]),
      el('td', { classe: 'num', texto: fmtInt.format(c.votos_apurados) }),
      el('td', { classe: 'num', texto: pct(c.perc_apurado) }),
      el('td', { classe: 'num' }, [el('strong', { texto: pct(c.perc_projetado) })]),
      el('td', {}, [faixaIc(c, 0, escMax)]),
      el('td', { classe: `num ${delta >= 0 ? 'delta-pos' : 'delta-neg'}`, texto: `${delta >= 0 ? '+' : '−'}${fmtPct2.format(Math.abs(delta))} p.p.` }),
      el('td', { classe: 'num', texto: prob(c.prob_vitoria) }),
      el('td', { classe: 'num', texto: prob(c.prob_lideranca) }),
      el('td', { classe: 'num', texto: prob(top2[c.numero]) }),
    ]);
    corpo.appendChild(tr);
  }
}

function legenda(id, itens, tipo = 'linha') {
  const caixa = document.getElementById(id);
  if (!caixa) return;
  caixa.textContent = '';
  for (const it of itens) {
    caixa.appendChild(el('span', {}, [
      el('span', { classe: tipo === 'linha' ? 'chave-linha' : 'chave-bloco', estilo: { background: it.cor } }),
      document.createTextNode(it.rotulo),
    ]));
  }
}

function serie(numero, fn) {
  const pontos = state.historico
    .filter((r) => r.candidatos.some((c) => c.numero === numero))
    .map((r) => fn(r, r.candidatos.find((c) => c.numero === numero)))
    .sort((a, b) => a.x - b.x);
  return { id: numero, rotulo: `${nome(numero)} (${numero})`, rotuloCurto: nomeCurto(numero), cor: cor(numero), pontos };
}

function renderCurvas() {
  const eixoX = cfgEixoX();
  const coloridos = Object.keys(state.slots).filter((n) => topoCandidatos(99).includes(n))
    .sort((a, b) => topoCandidatos(99).indexOf(a) - topoCandidatos(99).indexOf(b));

  // Apuração real
  const sApur = coloridos.map((n) => serie(n, (r, c) => ({ x: valorX(r), y: c.perc_apurado })));
  G.linhas(document.getElementById('g-apurado'), {
    series: sApur, ...eixoX, yFmt: (v) => `${fmtPct1.format(v)}%`, yPiso: 0, vazio: 'Aguardando a primeira atualização',
  });
  legenda('l-apurado', sApur.map((s) => ({ cor: s.cor, rotulo: s.rotulo }))
    .concat(topoCandidatos(99).length > coloridos.length ? [{ cor: G.token('--neutro'), rotulo: 'demais: ver tabela' }] : []));

  // Curva de projeção com IC
  const top4 = topoCandidatos(4);
  const sProj = top4.map((n) => ({ ...serie(n, (r, c) => ({ x: valorX(r), y: c.perc_projetado, lo: c.ic_inferior_95, hi: c.ic_superior_95 })), banda: true }));
  G.linhas(document.getElementById('g-projecao'), {
    series: sProj, ...eixoX, yFmt: (v) => `${fmtPct1.format(v)}%`, yPiso: 0, yTeto: 100,
    refs: [{ y: 50, rotulo: '50% dos válidos' }],
  });
  legenda('l-projecao', sProj.map((s) => ({ cor: s.cor, rotulo: s.rotulo })));

  // Probabilidades
  const sProb = [{
    id: '2t', rotulo: 'Chance de 2º turno', rotuloCurto: '2º turno', cor: G.token('--texto-2'), espessura: 2,
    pontos: state.historico.map((r) => ({ x: valorX(r), y: (r.prob_segundo_turno || 0) * 100 })).sort((a, b) => a.x - b.x),
  }].concat(topoCandidatos(2).map((n) => {
    const s = serie(n, (r, c) => ({ x: valorX(r), y: c.prob_vitoria * 100 }));
    return { ...s, rotulo: `P(eleito) ${s.rotulo}`, rotuloCurto: `${s.rotuloCurto} eleito` };
  }));
  G.linhas(document.getElementById('g-prob'), { series: sProb, ...eixoX, yMin: 0, yMax: 100, yFmt: (v) => `${fmtPct1.format(v)}%` });
  legenda('l-prob', sProb.map((s) => ({ cor: s.cor, rotulo: s.rotulo })));

  // Ritmo (sempre no tempo)
  const pts = state.historico.map((r) => ({ x: tsParaMs(r.timestamp), y: r.perc_secoes_apuradas })).sort((a, b) => a.x - b.x);
  G.linhas(document.getElementById('g-ritmo'), {
    series: [{ id: 'ritmo', rotulo: 'Seções apuradas', rotuloCurto: 'Seções', cor: G.token('--seq'), pontos: pts }],
    xFmt: fmtHoraAdaptativo(), xTitulo: fmtHoraSeg, yMin: 0, yMax: 100, yFmt: (v) => `${fmtPct1.format(v)}%`,
  });
  renderRitmoKpis(pts);
}

function renderRitmoKpis(pts) {
  const caixa = document.getElementById('ritmo-kpis');
  caixa.textContent = '';
  if (pts.length < 2) return;
  const ult = pts[pts.length - 1];
  const janelaIni = pts.find((p) => p.x >= ult.x - 10 * 60 * 1000) || pts[0];
  const minutos = (ult.x - janelaIni.x) / 60000;
  const ritmo = minutos > 0 ? (ult.y - janelaIni.y) / minutos : 0;
  const restante = ritmo > 0 ? (100 - ult.y) / ritmo : null;
  const mini = (r, v) => el('div', { classe: 'mini-kpi' }, [el('div', { classe: 'kpi-rotulo', texto: r }), el('div', { classe: 'kpi-valor', texto: v })]);
  caixa.append(
    mini('Ritmo (últimos 10 min)', `${fmtPct2.format(ritmo)} p.p./min`),
    mini('Previsão de 100% no ritmo atual', restante === null ? '—' : (ult.y >= 100 ? 'concluída' : fmtHora(ult.x + restante * 60000))),
    mini('Atualizações', fmtInt.format(pts.length)),
  );
}

function renderDistribuicoes(d) {
  const a = d.analise || {};
  const dist = a.distribuicao_final || {};
  const series = Object.entries(dist).map(([n, h]) => ({ rotulo: `${nome(n)} (${n})`, cor: cor(n), ...h }));
  const ext = series.flatMap((s) => [s.inicio, s.inicio + s.passo * s.freq.length]);
  const refs = ext.length && Math.min(...ext) - 6 < 50 && Math.max(...ext) + 6 > 50 ? [{ x: 50, rotulo: '50%' }] : [];
  G.histograma(document.getElementById('g-dist'), { series, refs, xFmt: (v) => `${fmtPct1.format(v)}%` });
  legenda('l-dist', series.map((s) => ({ cor: s.cor, rotulo: s.rotulo })), 'bloco');

  const m = a.distribuicao_margem;
  const nota = document.getElementById('nota-margem');
  if (m) {
    nota.textContent = `${nome(m.lider)} − ${nome(m.segundo)}, em p.p. · P(${nomeCurto(m.lider)} à frente) = ${prob(m.prob_positiva)}`;
    G.histograma(document.getElementById('g-margem'), {
      series: [{ rotulo: `Margem ${nomeCurto(m.lider)} − ${nomeCurto(m.segundo)}`, cor: G.token('--seq'), ...m }],
      refs: [{ x: 0, rotulo: 'empate' }],
      xFmt: (v) => `${v >= 0 ? '+' : '−'}${fmtPct1.format(Math.abs(v))}`,
    });
  } else {
    G.histograma(document.getElementById('g-margem'), { series: [] });
  }
}

function renderFalta(d) {
  const a = d.analise || {};
  const f = a.faltam || {};
  const caixa = document.getElementById('falta-kpis');
  caixa.textContent = '';
  const mini = (r, v, det) => el('div', { classe: 'mini-kpi' }, [
    el('div', { classe: 'kpi-rotulo', texto: r }), el('div', { classe: 'kpi-valor', texto: v }),
    det ? el('div', { classe: 'kpi-detalhe', texto: det }) : null,
  ]);
  caixa.append(mini('Válidos esperados nas seções restantes', compacto(f.validos_restantes_esperados), `Total final esperado: ${compacto(f.validos_finais_esperados)}`));
  if (f.lider) {
    const precisa = f.lider_precisa_pct_restantes;
    caixa.append(mini(
      `${nome(f.lider)} precisa, dos votos restantes, de`,
      precisa === null || precisa === undefined ? '—' : (precisa <= 0 ? 'já tem > 50%' : pct(precisa)),
      'para terminar com 50% dos válidos',
    ));
  }
  if (f.segundo) {
    caixa.append(mini(
      `Diferença apurada ${nomeCurto(f.lider)} − ${nomeCurto(f.segundo)}`,
      `${f.diferenca_votos_apurados >= 0 ? '+' : '−'}${compacto(Math.abs(f.diferenca_votos_apurados))} votos`,
      f.segundo_precisa_vantagem_pp_restantes === null ? '' :
        `${nomeCurto(f.segundo)} precisa superar ${nomeCurto(f.lider)} por ${fmtPct2.format(Math.max(0, f.segundo_precisa_vantagem_pp_restantes))} p.p. nos restantes`,
    ));
  }
  const linhas = (a.ufs || []).map((u) => ({
    rotulo: u.uf, valor: u.restantes_esperados,
    detalhe: `${pct(u.secoes_apuradas / Math.max(1, u.secoes_total) * 100, 1)} apurado · ${compacto(u.restantes_esperados)} válidos esperados`,
  })).filter((l) => l.valor > 0).sort((x, y) => y.valor - x.valor);
  G.barrasH(document.getElementById('g-restantes'), {
    linhas, fmt: compacto, margemRotulo: 40, vazio: 'Apuração concluída: não há votos restantes',
  });
}

function liderProjetadoUf(u) {
  let melhor = null;
  for (const [n, v] of Object.entries(u.proj_pct || {})) if (!melhor || v > melhor[1]) melhor = [n, v];
  return melhor;
}

function renderMapa(d) {
  const a = d.analise || {};
  const caixa = document.getElementById('mapa');
  caixa.textContent = '';
  const porUf = Object.fromEntries((a.ufs || []).map((u) => [u.uf, u]));
  const grade = Array.from({ length: 7 }, () => Array(8).fill(null));
  for (const [uf, [l, c]] of Object.entries(MAPA)) grade[l][c] = uf;
  const lideres = new Set();
  for (const linha of grade) {
    for (const uf of linha) {
      if (!uf) { caixa.appendChild(el('div', { classe: 'uf-vazio' })); continue; }
      const u = porUf[uf];
      const lider = u ? liderProjetadoUf(u) : null;
      const pctApur = u ? u.secoes_apuradas / Math.max(1, u.secoes_total) * 100 : 0;
      const tile = el('button', {
        type: 'button',
        classe: `uf-tile${!u || u.sem_dados ? ' sem-dados' : ''}${state.ufSelecionada === uf ? ' selecionada' : ''}`,
        'aria-label': `${uf}: ${pct(pctApur, 1)} apurado${lider ? `, líder projetado ${nome(lider[0])} ${pct(lider[1])}` : ''}`,
      }, [document.createTextNode(uf), el('small', { texto: u ? `${fmtPct1.format(pctApur)}%` : '—' })]);
      if (lider && u && !u.sem_dados) {
        const c = cor(lider[0]);
        tile.style.background = c;
        tile.style.color = luminancia(c) > 0.3 ? '#0b0b0b' : '#ffffff';
        lideres.add(lider[0]);
      }
      const dica = (evt) => {
        if (!u) return;
        const tops = Object.entries(u.proj_pct).sort((x, y) => y[1] - x[1]).slice(0, 3);
        const totalApur = Object.values(u.votos).reduce((s, v) => s + v, 0) || 1;
        G.mostrarTooltip(evt, `${uf} · ${pct(pctApur, 1)} das seções · ${compacto(u.restantes_esperados)} válidos restantes`, tops.map(([n, v]) => ({
          cor: cor(n), valor: pct(v), rotulo: `${nome(n)} · apurado ${pct(u.votos[n] / totalApur * 100)} · P(lidera) ${prob(u.prob_lider[n])}`,
        })));
      };
      tile.addEventListener('pointermove', dica);
      tile.addEventListener('pointerleave', G.esconderTooltip);
      tile.addEventListener('click', () => { state.ufSelecionada = uf; renderMapa(state.atual); renderEstratos(state.atual); sincronizarSelect(); });
      caixa.appendChild(tile);
    }
  }
  legenda('l-mapa', [...lideres].map((n) => ({ cor: cor(n), rotulo: `${nome(n)} (${n})` }))
    .concat([{ cor: G.token('--neutro-claro'), rotulo: 'sem dados' }]), 'bloco');
}

function segmentos(fracoes, ordem) {
  const coloridos = ordem.filter((n) => state.slots[n] !== undefined);
  const segs = coloridos.map((n) => ({ rotulo: `${nome(n)} (${n})`, cor: cor(n), valor: fracoes[n] || 0 }));
  const demais = Object.entries(fracoes).filter(([n]) => !coloridos.includes(n)).reduce((s, [, v]) => s + v, 0);
  if (demais > 0.005) segs.push({ rotulo: 'Demais candidatos', cor: G.token('--neutro'), valor: demais });
  return segs;
}

function partes(votos) {
  const total = Object.values(votos || {}).reduce((s, v) => s + v, 0);
  return Object.fromEntries(Object.entries(votos || {}).map(([n, v]) => [n, total ? v / total * 100 : 0]));
}

function legendaCandidatos(id, ordem) {
  const coloridos = ordem.filter((n) => state.slots[n] !== undefined);
  const itens = coloridos.map((n) => ({ cor: cor(n), rotulo: nome(n) }));
  if (ordem.length > coloridos.length) itens.push({ cor: G.token('--neutro'), rotulo: 'Demais' });
  legenda(id, itens, 'bloco');
}

function renderRegioes(d) {
  const a = d.analise || {};
  const ordem = topoCandidatos(99);
  const linhas = [];
  for (const r of (a.regioes || [])) {
    const apur = r.secoes_apuradas / Math.max(1, r.secoes_total) * 100;
    linhas.push({ rotulo: `${r.regiao} · A (${fmtPct1.format(apur)}%)`, segmentos: segmentos(partes(r.votos), ordem), grupoInicio: linhas.length > 0 });
    linhas.push({ rotulo: `${r.regiao} · P`, segmentos: segmentos(r.proj_pct || {}, ordem) });
  }
  G.barrasEmpilhadas(document.getElementById('g-regioes'), { linhas, margemRotulo: 150, alturaBarra: 16, gap: 6 });
  legendaCandidatos('l-regioes', ordem);
}

function renderTipos(d) {
  const a = d.analise || {};
  const ordem = topoCandidatos(99);
  const linhas = (a.tipos_estrato || []).filter((t) => t.tipo !== 'SEM_DADOS').map((t) => ({
    rotulo: `${ROTULO_TIPO[t.tipo] || t.tipo} (${fmtPct1.format(t.secoes_apuradas / Math.max(1, t.secoes_total) * 100)}% apur.)`,
    segmentos: segmentos(partes(t.votos), ordem),
  }));
  G.barrasEmpilhadas(document.getElementById('g-tipos'), { linhas, margemRotulo: 230, alturaBarra: 20, gap: 10 });
  legendaCandidatos('l-tipos', ordem);
}

function sincronizarSelect() {
  const sel = document.getElementById('sel-uf');
  if (state.ufSelecionada) sel.value = state.ufSelecionada;
}

function renderEstratos(d) {
  const a = d.analise || {};
  const sel = document.getElementById('sel-uf');
  const ufs = (a.ufs || []).map((u) => u.uf);
  if (!state.ufSelecionada || !ufs.includes(state.ufSelecionada)) {
    state.ufSelecionada = ufs.includes('SP') ? 'SP' : ufs[0];
  }
  if (sel.options.length !== ufs.length) {
    sel.textContent = '';
    for (const uf of ufs) sel.appendChild(el('option', { value: uf, texto: uf }));
  }
  sincronizarSelect();

  const top3 = topoCandidatos(3);
  const thead = document.querySelector('#tabela-estratos thead');
  thead.textContent = '';
  thead.appendChild(el('tr', {}, [
    el('th', { texto: 'Estrato' }), el('th', { texto: 'Tipo' }), el('th', { texto: '% apurado' }),
    el('th', { classe: 'num', texto: 'Válidos apur.' }),
    ...top3.map((n) => el('th', { classe: 'num', texto: nomeCurto(n) })),
    el('th', { classe: 'num', texto: 'Válidos restantes' }),
  ]));
  const corpo = document.querySelector('#tabela-estratos tbody');
  corpo.textContent = '';
  const ordemTipo = { CAPITAL: 0, GRANDE_CIDADE: 1, INTERIOR: 2, UF_INTEIRA: 3, SEM_DADOS: 4 };
  const estratos = (a.estratos || []).filter((e) => e.uf === state.ufSelecionada)
    .sort((x, y) => (ordemTipo[x.tipo] - ordemTipo[y.tipo]) || (y.eleitores_aptos - x.eleitores_aptos));
  for (const e of estratos) {
    const apur = e.secoes_apuradas / Math.max(1, e.secoes_total) * 100;
    const fr = partes(e.votos);
    corpo.appendChild(el('tr', { classe: e.tipo === 'INTERIOR' ? 'destaque' : '' }, [
      el('td', { texto: e.nome }),
      el('td', { texto: ROTULO_TIPO[e.tipo] || e.tipo }),
      el('td', {}, [el('span', { classe: 'mini-medidor' }, [el('span', { estilo: { width: `${apur}%` } })]), document.createTextNode(pct(apur, 1))]),
      el('td', { classe: 'num', texto: fmtInt.format(e.votos_validos) }),
      ...top3.map((n) => el('td', { classe: 'num', texto: e.votos_validos ? pct(fr[n]) : '—' })),
      el('td', { classe: 'num', texto: compacto(e.restantes_esperados) }),
    ]));
  }
}

const COLUNAS_UF = [
  { chave: 'uf', rotulo: 'UF', valor: (u) => u.uf },
  { chave: 'regiao', rotulo: 'Região', valor: (u) => u.regiao },
  { chave: 'apurado', rotulo: '% apurado', num: true, valor: (u) => u.secoes_apuradas / Math.max(1, u.secoes_total) * 100, fmt: (v) => pct(v, 1) },
  { chave: 'validos', rotulo: 'Válidos apurados', num: true, valor: (u) => u.votos_validos, fmt: (v) => fmtInt.format(v) },
  { chave: 'lider_apur', rotulo: 'Líder apurado', valor: (u) => liderApurado(u), fmt: (v) => v || '—' },
  { chave: 'lider_proj', rotulo: 'Líder projetado', valor: (u) => { const l = liderProjetadoUf(u); return l ? `${nomeCurto(l[0])} ${pct(l[1])}` : '—'; } },
  { chave: 'prob', rotulo: 'P(líder proj. vence UF)', num: true, valor: (u) => { const l = liderProjetadoUf(u); return l ? u.prob_lider[l[0]] : 0; }, fmt: prob },
  { chave: 'restantes', rotulo: 'Válidos restantes', num: true, valor: (u) => u.restantes_esperados, fmt: compacto },
];

function liderApurado(u) {
  const total = Object.values(u.votos).reduce((s, v) => s + v, 0);
  if (!total) return '';
  const [n, v] = Object.entries(u.votos).sort((x, y) => y[1] - x[1])[0];
  return `${nomeCurto(n)} ${pct(v / total * 100)}`;
}

function renderUfs(d) {
  const a = d.analise || {};
  const thead = document.querySelector('#tabela-ufs thead');
  thead.textContent = '';
  const tr = el('tr');
  for (const col of COLUNAS_UF) {
    const th = el('th', { classe: col.num ? 'num' : '', 'data-ordem': col.chave, tabindex: '0', texto: col.rotulo });
    if (state.ordemUf.chave === col.chave) th.setAttribute('aria-sort', state.ordemUf.desc ? 'descending' : 'ascending');
    const ordenar = () => {
      state.ordemUf = { chave: col.chave, desc: state.ordemUf.chave === col.chave ? !state.ordemUf.desc : !!col.num };
      renderUfs(state.atual);
    };
    th.addEventListener('click', ordenar);
    th.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ordenar(); } });
    tr.appendChild(th);
  }
  thead.appendChild(tr);

  const col = COLUNAS_UF.find((c) => c.chave === state.ordemUf.chave) || COLUNAS_UF[0];
  const ufs = [...(a.ufs || [])].sort((x, y) => {
    const vx = col.valor(x), vy = col.valor(y);
    const cmp = typeof vx === 'number' ? vx - vy : String(vx).localeCompare(String(vy), 'pt-BR');
    return state.ordemUf.desc ? -cmp : cmp;
  });
  const corpo = document.querySelector('#tabela-ufs tbody');
  corpo.textContent = '';
  for (const u of ufs) {
    corpo.appendChild(el('tr', { classe: u.sem_dados ? 'destaque' : '' }, COLUNAS_UF.map((c) => {
      const v = c.valor(u);
      return el('td', { classe: c.num ? 'num' : '', texto: c.fmt ? c.fmt(v) : v });
    })));
  }
}

function renderRodape(d) {
  document.getElementById('rodape-ciclo').textContent = `Ciclo ${d.ciclo_id} · calculado às ${d.timestamp}`;
  document.getElementById('rodape-mc').textContent = `Motor Monte Carlo: ${fmtInt.format(Math.round(d.tempo_computacao_ms))} ms`;
  const info = document.getElementById('ultima-atualizacao');
  info.classList.remove('aviso-coleta');
  info.textContent = `Última atualização: ${d.timestamp}`;
}

function emEspera(d) {
  return Boolean(d && d.analise && d.analise.aguardando);
}

function renderTudo() {
  const d = state.atual;
  if (!d || !d.candidatos || !d.candidatos.length) return;
  if (emEspera(d)) {
    // Sem votos ainda: as cores são atribuídas só quando a ordem dos candidatos tiver sentido
    for (const c of d.candidatos) state.candidatos[c.numero] = { nome: c.nome, partido: c.partido };
    renderEsperaCompleta(d);
    return;
  }
  atribuirCores(d.candidatos);
  renderChamada(d);
  renderKpis(d);
  renderCandidatos(d);
  renderCurvas();
  renderDistribuicoes(d);
  renderFalta(d);
  renderMapa(d);
  renderRegioes(d);
  renderTipos(d);
  renderEstratos(d);
  renderUfs(d);
  renderRodape(d);
  if (state.chaveSlots) armazenar(state.chaveSlots, state.slots);
}

// ------------------------------------------------------------------- dados

function chave(r) { return `${r.ciclo_id}|${r.timestamp}`; }

const GRAFICOS = ['g-apurado', 'g-projecao', 'g-prob', 'g-ritmo', 'g-dist', 'g-margem', 'g-restantes', 'g-regioes', 'g-tipos'];

function renderEsperaCompleta(d) {
  renderAguardando(d);
  renderCandidatosAguardando(d);
  const n = (d.analise && d.analise.nacional) || {};
  const caixa = document.getElementById('kpis');
  caixa.textContent = '';
  caixa.append(
    kpi('Seções apuradas', pct(0), `0 de ${fmtInt.format(d.total_secoes)}`, 0),
    kpi('Eleitorado', compacto(d.total_eleitores), `${fmtInt.format(d.total_eleitores)} eleitores aptos`),
    kpi('Candidatos', fmtInt.format(d.candidatos.length), 'cadastrados nos arquivos do TSE'),
  );
  for (const id of GRAFICOS) G.vazio(document.getElementById(id), 'Aguardando os primeiros votos apurados');
  for (const id of ['mapa', 'falta-kpis', 'ritmo-kpis']) document.getElementById(id).textContent = '';
  document.getElementById('rodape-ciclo').textContent = `Ciclo ${d.ciclo_id} · verificado às ${d.timestamp}`;
}

/** Arquivos já publicados, mas nenhuma seção apurada (antes das 17h do dia da eleição). */
function renderAguardando(d) {
  document.getElementById('chamada-titulo').textContent = 'Aguardando o início da apuração';
  document.getElementById('chamada-sub').textContent =
    `Arquivos do TSE disponíveis: 0 de ${fmtInt.format(d.total_secoes)} seções apuradas · ` +
    `${fmtInt.format(d.total_eleitores)} eleitores. A projeção começa com os primeiros votos.`;
  const info = document.getElementById('ultima-atualizacao');
  info.classList.remove('aviso-coleta');
  info.textContent = `Última verificação: ${d.timestamp}`;
}

function mostrarAviso(aviso) {
  state.ultimoAviso = aviso;
  const info = document.getElementById('ultima-atualizacao');
  info.textContent = `${aviso.mensagem} (${aviso.timestamp})`;
  info.classList.add('aviso-coleta');
  if (!state.atual) {
    document.getElementById('chamada-sub').textContent =
      `Ainda sem resultados. Último aviso da coleta: ${aviso.mensagem}. Nova tentativa a cada ciclo.`;
  }
}

function adicionarAoHistorico(r) {
  if (!r.total_validos_apurados || emEspera(r)) return;
  const k = chave(r);
  if (state.historico.some((h) => chave(h) === k)) return;
  state.historico.push(r);
}

async function carregarInicial() {
  const sessao = await fetch('/api/v1/sessao').then((r) => r.json()).catch(() => ({ ativa: true }));
  if (!sessao.ativa) {
    location.replace('/inicio');
    return;
  }
  try {
    const [status, hist, atual] = await Promise.all([
      fetch('/api/v1/status').then((r) => r.json()),
      fetch('/api/v1/projecao/historico?limite=5000').then((r) => r.json()),
      fetch('/api/v1/projecao/atual').then((r) => r.json()),
    ]);
    renderCabecalho(status);
    for (const r of hist) if (r.candidatos && r.candidatos.length) adicionarAoHistorico(r);
    if (atual && atual.candidatos && atual.candidatos.length) {
      state.atual = atual;
      adicionarAoHistorico(atual);
    } else if (atual && atual.total_secoes) {
      renderAguardando(atual);
    }
    renderTudo();
  } catch (e) {
    console.error('Falha ao carregar dados iniciais', e);
  }
}

function conectarSSE() {
  const caixa = document.getElementById('conexao');
  const txt = document.getElementById('conexao-texto');
  const fonte = new EventSource('/api/v1/projecao/stream');
  fonte.onopen = () => { caixa.className = 'conexao on'; txt.textContent = 'Ao vivo'; };
  fonte.onerror = () => { caixa.className = 'conexao off'; txt.textContent = 'Reconectando…'; };
  // Sessão iniciada, parada ou trocada de modo: recarrega (sem sessão, a raiz leva à tela inicial)
  fonte.addEventListener('sessao', () => location.reload());
  fonte.addEventListener('aviso', (evt) => {
    try { mostrarAviso(JSON.parse(evt.data)); } catch (e) { /* ignora aviso malformado */ }
  });
  fonte.addEventListener('projecao_update', (evt) => {
    try {
      const d = JSON.parse(evt.data);
      if (!d.candidatos || !d.candidatos.length) {
        if (d.total_secoes && !state.atual) renderAguardando(d);
        return;
      }
      state.atual = d;
      adicionarAoHistorico(d);
      renderTudo();
    } catch (e) {
      console.error('Erro ao processar atualização', e);
    }
  });
}

// ---------------------------------------------------------------- controles

function aplicarTema(tema) {
  if (tema) document.documentElement.setAttribute('data-theme', tema);
  else document.documentElement.removeAttribute('data-theme');
}

function iniciarControles() {
  aplicarTema(recuperar('spetr-tema', null));
  document.getElementById('botao-tema').addEventListener('click', () => {
    const escuroAtual = getComputedStyle(document.documentElement).colorScheme.includes('dark');
    const novo = escuroAtual ? 'light' : 'dark';
    aplicarTema(novo);
    armazenar('spetr-tema', novo);
    renderTudo();
  });

  state.eixo = recuperar('spetr-eixo', 'tempo');
  for (const b of document.querySelectorAll('[data-eixo]')) {
    b.classList.toggle('ativo', b.dataset.eixo === state.eixo);
    b.setAttribute('aria-pressed', String(b.dataset.eixo === state.eixo));
    b.addEventListener('click', () => {
      state.eixo = b.dataset.eixo;
      armazenar('spetr-eixo', state.eixo);
      for (const o of document.querySelectorAll('[data-eixo]')) {
        o.classList.toggle('ativo', o === b);
        o.setAttribute('aria-pressed', String(o === b));
      }
      renderCurvas();
    });
  }

  document.getElementById('sel-uf').addEventListener('change', (e) => {
    state.ufSelecionada = e.target.value;
    renderMapa(state.atual);
    renderEstratos(state.atual);
  });

  let temporizador = null;
  window.addEventListener('resize', () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(renderTudo, 150);
  });
}

iniciarControles();
// ?estatico=1 desenha o estado atual sem abrir o stream (impressão, captura de tela)
const estatico = new URLSearchParams(location.search).has('estatico');
const temaUrl = new URLSearchParams(location.search).get('tema');
if (temaUrl === 'escuro' || temaUrl === 'claro') aplicarTema(temaUrl === 'escuro' ? 'dark' : 'light');
carregarInicial().then(() => {
  if (estatico) document.getElementById('conexao-texto').textContent = 'Modo estático';
  else conectarSSE();
});
