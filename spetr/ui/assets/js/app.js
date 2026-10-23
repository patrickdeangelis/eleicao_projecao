/**
 * SPETR — Painel de apuração e projeção (tela única com abas).
 * Carrega o histórico da execução atual, recebe atualizações via SSE e redesenha o painel.
 * Só a aba visível é desenhada a cada atualização; ao trocar de aba, ela é desenhada na hora.
 */
const G = Graficos;

const state = {
  historico: [],          // resultados resumidos por ciclo (curvas)
  atual: null,            // último resultado completo
  info: {},               // dados da sessão/eleição
  eixo: 'tempo',
  aba: 'geral',
  modoMapa: 'lider',
  modoCorrida: 'votos',
  versaoCrescimento: 'subestratificado',  // estratificação usada na razão de crescimento (aba Modelos e mapa)
  ufSelecionada: null,
  ordemUf: { chave: 'restantes', desc: true },
  slots: {},              // número do candidato -> slot de cor (fixo para a entidade)
  marcados: null,         // Set de números exibidos nos gráficos (null = ainda não definido)
  candidatos: {},         // número -> {nome, partido}
  chave: 'spetr',         // prefixo de armazenamento por eleição
};

const SLOTS = 8;
const PRINCIPAIS = 4;
const fmtInt = new Intl.NumberFormat('pt-BR');
const fmt1 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmt2 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt3 = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
/** Percentual com casas adaptativas: valores pequenos (candidatos nanicos) ganham mais casas. */
const pct = (v, casas = 2) => {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  let f = casas === 1 ? fmt1 : fmt2;
  if (a > 0 && a < 0.1) f = fmt3;
  else if (a > 0 && a < 1) f = fmt2;
  return `${f.format(v)}%`;
};
const prob = (p) => {
  if (p === null || p === undefined) return '—';
  const v = p * 100;
  if (v > 0 && v < 0.1) return '<0,1%';
  if (v < 100 && v > 99.9) return '>99,9%';
  return `${fmt1.format(v)}%`;
};
function compacto(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—';
  const a = Math.abs(n);
  if (a >= 1e6) return `${fmt2.format(n / 1e6)} mi`;
  if (a >= 1e3) return `${fmt1.format(n / 1e3)} mil`;
  return fmtInt.format(Math.round(n));
}

const NOMES_UF = {
  AC: 'Acre', AL: 'Alagoas', AM: 'Amazonas', AP: 'Amapá', BA: 'Bahia', CE: 'Ceará', DF: 'Distrito Federal',
  ES: 'Espírito Santo', GO: 'Goiás', MA: 'Maranhão', MG: 'Minas Gerais', MS: 'Mato Grosso do Sul',
  MT: 'Mato Grosso', PA: 'Pará', PB: 'Paraíba', PE: 'Pernambuco', PI: 'Piauí', PR: 'Paraná',
  RJ: 'Rio de Janeiro', RN: 'Rio Grande do Norte', RO: 'Rondônia', RR: 'Roraima', RS: 'Rio Grande do Sul',
  SC: 'Santa Catarina', SE: 'Sergipe', SP: 'São Paulo', TO: 'Tocantins', ZZ: 'Exterior',
};
const ROTULO_TIPO = {
  CAPITAL: 'Capitais',
  GRANDE_CIDADE: 'Cidades com 100 mil+ eleitores',
  INTERIOR: 'Interior',
  SUBESTRATO: 'Parte do interior',
  SUBESTRATO_CIDADES: 'Cidades grandes da região',
  UF_INTEIRA: 'Exterior / UF inteira',
  SEM_DADOS: 'Sem dados',
};
const ORDEM_TIPO = { CAPITAL: 0, GRANDE_CIDADE: 1, INTERIOR: 2, SUBESTRATO: 3, SUBESTRATO_CIDADES: 3, UF_INTEIRA: 4, SEM_DADOS: 5 };
const GRAFICOS = ['g-corrida', 'g-intervalos', 'g-projecao', 'g-prob', 'g-mapa', 'g-uf-barras', 'g-dist', 'g-margem',
  'g-restantes', 'g-apurado', 'g-ritmo', 'g-apuracao-uf', 'g-regioes', 'g-tipos', 'g-composicao', 'g-exterior',
  'g-sub-intervalos', 'g-sub-uf', 'g-sub-nacional', 'g-cresc', 'g-cresc-dif', 'g-modelos'];
const ROTULO_VERSAO = { subestratificado: 'subestratificado', normal: 'normal' };

// ------------------------------------------------------------------ utilidades

function armazenar(chave, valor) {
  try { localStorage.setItem(chave, JSON.stringify(valor)); } catch (e) { /* armazenamento indisponível */ }
}
function recuperar(chave, padrao) {
  try { const v = localStorage.getItem(chave); return v ? JSON.parse(v) : padrao; } catch (e) { return padrao; }
}

function el(tag, attrs = {}, filhos = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null) continue;
    if (k === 'texto') n.textContent = v;
    else if (k === 'classe') n.className = v;
    else if (k === 'estilo') Object.assign(n.style, v);
    else n.setAttribute(k, v);
  }
  for (const f of [].concat(filhos)) if (f) n.appendChild(typeof f === 'string' ? document.createTextNode(f) : f);
  return n;
}

function tituloProprio(t) {
  const minusculas = new Set(['de', 'da', 'do', 'das', 'dos', 'e']);
  return String(t || '').toLowerCase().split(/\s+/)
    .map((p, i) => (i > 0 && minusculas.has(p)) ? p : p.charAt(0).toUpperCase() + p.slice(1)).join(' ');
}

const tsParaMs = (ts) => {
  const d = new Date((ts || '').replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? 0 : d.getTime();
};
const fmtHora = (ms) => new Date(ms).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
const fmtHoraSeg = (ms) => new Date(ms).toLocaleTimeString('pt-BR');

function fmtHoraAdaptativo() {
  const xs = state.historico.map((r) => tsParaMs(r.timestamp));
  return xs.length && Math.max(...xs) - Math.min(...xs) < 15 * 60 * 1000 ? fmtHoraSeg : fmtHora;
}
function valorX(r) { return state.eixo === 'tempo' ? tsParaMs(r.timestamp) : r.perc_secoes_apuradas; }
function cfgEixoX() {
  return state.eixo === 'tempo'
    ? { xFmt: fmtHoraAdaptativo(), xTitulo: fmtHoraSeg }
    : { xFmt: (v) => `${fmt1.format(v)}%`, xTitulo: (v) => `${fmt2.format(v)}% das seções apuradas` };
}

// ------------------------------------------------------- candidatos, cores e seleção

function nome(n) { return state.candidatos[n] ? state.candidatos[n].nome : `Nº ${n}`; }
function nomeCurto(n) {
  const partes = nome(n).split(/\s+/);
  return partes[partes.length - 1];
}
function cor(n) {
  const s = state.slots[n];
  return s === undefined ? G.token('--neutro') : G.token(`--s${s + 1}`);
}

function segundoTurno() {
  const d = state.atual;
  return Number(state.info.turno) === 2 || Boolean(d && d.candidatos && d.candidatos.length === 2);
}

/** Ordem atual por projeção (ou por nome, antes dos votos). */
function ordemCandidatos() {
  return state.atual ? state.atual.candidatos.map((c) => c.numero) : [];
}

function marcadosEmOrdem() {
  return ordemCandidatos().filter((n) => state.marcados && state.marcados.has(n));
}

/** Cores seguem a entidade: dadas na primeira aparição (ordem de projeção) e nunca repintadas à vista. */
function atribuirCores(candidatos) {
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

/** Ao marcar um candidato sem cor, usa um slot livre ou o de um candidato desmarcado (que não aparece). */
function garantirCor(n) {
  if (state.slots[n] !== undefined) return;
  const usados = new Set(Object.values(state.slots));
  for (let i = 0; i < SLOTS; i++) {
    if (!usados.has(i)) { state.slots[n] = i; return; }
  }
  const doador = [...ordemCandidatos()].reverse().find((m) => state.slots[m] !== undefined && !state.marcados.has(m));
  if (doador) {
    state.slots[n] = state.slots[doador];
    delete state.slots[doador];
  }
}

function salvarSelecao() {
  armazenar(`${state.chave}:slots`, state.slots);
  armazenar(`${state.chave}:marcados`, [...(state.marcados || [])]);
}

function definirSelecao(tipo) {
  const ordem = ordemCandidatos();
  if (tipo === 'todos') state.marcados = new Set(ordem);
  else if (tipo === 'nenhum') state.marcados = new Set();
  else state.marcados = new Set(ordem.slice(0, segundoTurno() ? 2 : PRINCIPAIS));
  for (const n of state.marcados) garantirCor(n);
  salvarSelecao();
  renderTudo();
}

function alternarCandidato(n) {
  if (state.marcados.has(n)) state.marcados.delete(n);
  else { state.marcados.add(n); garantirCor(n); }
  salvarSelecao();
  renderTudo();
}

// ------------------------------------------------------------------ cabeçalho

function renderCabecalho(info) {
  const e = info.eleicao || {};
  state.info = e;
  const selo = document.getElementById('selo-modo');
  if (info.modo) {
    selo.hidden = false;
    selo.textContent = { simulado: 'SIMULAÇÃO', replay: 'REPLAY' }[info.modo] || 'COLETA REAL';
    selo.classList.toggle('simulado', info.modo !== 'real');
  }
  const linkSim = document.getElementById('link-simulador');
  if (info.simulador_url) { linkSim.hidden = false; linkSim.href = info.simulador_url; }
  if (info.ultimo_aviso) mostrarAviso(info.ultimo_aviso);

  let texto;
  if (e.simulado) {
    const ritmos = { lenta: 'lento', normal: 'normal', rapida: 'rápido' };
    texto = `${e.replay ? '' : 'Dados fictícios · '}${e.descricao || ''} · ritmo ${ritmos[e.velocidade] || e.velocidade || ''}`;
    state.chave = `spetr:sim:${e.cenario || ''}`;
  } else {
    const partes = [];
    if (e.mock) partes.push('Teste');
    if (e.ano) partes.push(`Eleições ${e.ano}`);
    partes.push(e.cargo === '1' || !e.cargo ? 'Presidente' : `Cargo ${e.cargo}`);
    if (e.turno) partes.push(`${e.turno}º turno`);
    texto = partes.join(' · ');
    state.chave = `spetr:${e.ambiente || ''}:${e.ano || ''}:${e.codigo || 'auto'}:${e.cargo || ''}:${e.turno || ''}`;
  }
  document.getElementById('info-eleicao').textContent = texto;
  state.slots = recuperar(`${state.chave}:slots`, {});
  const salvos = recuperar(`${state.chave}:marcados`, null);
  state.marcados = salvos ? new Set(salvos) : null;
}

function mostrarAviso(aviso) {
  const info = document.getElementById('ultima-atualizacao');
  info.textContent = `${aviso.mensagem} (${aviso.timestamp})`;
  info.classList.add('aviso-coleta');
  if (!state.atual) {
    document.getElementById('chamada-sub').textContent =
      `Ainda sem resultados. Último aviso da coleta: ${aviso.mensagem}. Nova tentativa a cada ciclo.`;
  }
}

// ------------------------------------------------------------ faixa de status

function renderChamada(d) {
  const caixa = document.getElementById('chamada');
  const titulo = document.getElementById('chamada-titulo');
  const sub = document.getElementById('chamada-sub');
  caixa.className = 'chamada';
  const [a, b] = d.candidatos;
  const vencedor = d.vencedor_projetado ? nome(d.vencedor_projetado) : '';
  const semDados = d.ufs_sem_dados || [];

  if (d.status_call === 'MATEMATICAMENTE_ELEITO') {
    caixa.classList.add('eleito');
    titulo.textContent = `✓ ${vencedor} eleito`;
    sub.textContent = 'Os votos que faltam não são suficientes para mudar o resultado.';
  } else if (d.status_call === 'VITORIA_PROJETADA') {
    caixa.classList.add('projetada');
    titulo.textContent = `Vitória projetada: ${vencedor}`;
    sub.textContent = `Chance de vitória de ${prob(a.prob_vitoria)}, considerando os votos que faltam.`;
  } else if (d.status_call === 'SEGUNDO_TURNO_PROJETADO') {
    caixa.classList.add('segundo-turno');
    titulo.textContent = '↻ Segundo turno projetado';
    sub.textContent = `Chance de ninguém passar de 50% dos válidos: ${prob(d.prob_segundo_turno)}` +
      (a && b ? ` · mais prováveis no 2º turno: ${a.nome} e ${b.nome}.` : '.');
  } else {
    titulo.textContent = 'Apuração em andamento · disputa em aberto';
    const pedacos = [];
    if (a) pedacos.push(`${a.nome} à frente na projeção (${pct(a.perc_projetado, 1)})`);
    pedacos.push(segundoTurno() ? `chance de vitória ${prob(a && a.prob_vitoria)}` : `chance de 2º turno ${prob(d.prob_segundo_turno)}`);
    if (semDados.length) pedacos.push(`${semDados.length} UF(s) ainda sem dados, estimadas pela média nacional`);
    sub.textContent = `${pedacos.join(' · ')}.`;
  }
}

function kpi(rotulo, valor, detalhe, titulo) {
  return el('div', { classe: 'kpi', title: titulo }, [
    el('div', { classe: 'kpi-rotulo', texto: rotulo }),
    el('div', { classe: 'kpi-valor', texto: valor }),
    detalhe ? el('div', { classe: 'kpi-detalhe', texto: detalhe }) : null,
  ]);
}

function renderStatus(d) {
  const n = (d.analise && d.analise.nacional) || {};
  const f = (d.analise && d.analise.faltam) || {};
  G.anel(document.getElementById('g-anel'), d.perc_secoes_apuradas || 0);
  document.getElementById('anel-detalhe').textContent = `${fmtInt.format(d.secoes_apuradas)} de ${fmtInt.format(d.total_secoes)}`;

  // Chance de virada: o líder da apuração não terminar em 1º
  const liderApur = [...d.candidatos].sort((x, y) => y.votos_apurados - x.votos_apurados)[0];
  const virada = liderApur ? 1 - (liderApur.prob_lideranca || 0) : null;

  const caixa = document.getElementById('kpis');
  caixa.textContent = '';
  const anulados = (n.votos_anulados || 0) > 0 ? ` · anulados ${pct(n.pct_anulados, 1)}` : '';
  caixa.append(
    kpi('Votos válidos', compacto(d.total_validos_apurados), `final ≈ ${compacto(d.total_validos_projetados)}${anulados}`,
      anulados ? 'Anulados: votos de candidatos com registro anulado ou em julgamento, que não entram nos válidos' : undefined),
    kpi('Comparecimento', pct(n.pct_comparecimento, 1), `abstenção ${pct(n.pct_abstencao, 1)}`),
    kpi('Brancos e nulos', pct((n.pct_brancos || 0) + (n.pct_nulos || 0), 1), `brancos ${pct(n.pct_brancos, 1)} · nulos ${pct(n.pct_nulos, 1)}`),
  );
  if (segundoTurno()) {
    const lider = d.candidatos[0];
    caixa.append(kpi('Chance de vitória', prob(lider && lider.prob_vitoria), lider ? lider.nome : ''));
  } else {
    caixa.append(kpi('Chance de 2º turno', prob(d.prob_segundo_turno), 'ninguém com mais de 50%'));
  }
  caixa.append(
    kpi('Chance de virada', prob(virada), liderApur ? `${nomeCurto(liderApur.numero)} lidera agora` : '',
      'Chance de quem lidera a apuração agora não terminar em 1º lugar'),
    kpi('Válidos que faltam', compacto(f.validos_restantes_esperados), `máximo ${compacto(f.votos_restantes_maximos)}`),
  );
  const info = document.getElementById('ultima-atualizacao');
  info.classList.remove('aviso-coleta');
  info.textContent = `Atualizado às ${d.timestamp.slice(11)} · ciclo ${d.ciclo_id}`;
}

// -------------------------------------------------------------- lista lateral

function descricaoChapa(c) {
  const partes = [c.nome_completo || c.nome];
  if (c.vice) partes.push(`Vice: ${c.vice}`);
  if (c.coligacao) partes.push(`${c.coligacao}: ${c.composicao}`);
  return partes.join(' · ');
}

function renderListaCandidatos(d, aguardando) {
  const dois = segundoTurno();
  document.querySelector('.atalhos').hidden = dois || aguardando;
  document.getElementById('nota-candidatos').textContent = aguardando
    ? 'Cadastrados nos arquivos do TSE, em ordem alfabética.'
    : (dois ? 'Disputa do 2º turno.' : 'Marque para exibir nos gráficos.');
  const top2 = (d.analise && d.analise.prob_top2) || {};
  const lista = document.getElementById('lista-candidatos');
  lista.textContent = '';
  for (const c of d.candidatos) {
    const marcado = !aguardando && (dois || state.marcados.has(c.numero));
    const corC = aguardando ? G.token('--neutro-claro') : cor(c.numero);
    const chave = el('span', { classe: 'cand-chave', estilo: { borderColor: corC, background: marcado ? corC : 'transparent' } });
    let probs = '';
    if (!aguardando) {
      probs = dois
        ? `Chance de vitória ${prob(c.prob_vitoria)}`
        : `1º lugar ${prob(c.prob_lideranca)} · 2º turno ${prob(top2[c.numero])}`;
    }
    const info = el('div', { classe: 'cand-info', title: descricaoChapa(c) }, [
      el('strong', { texto: c.nome }),
      el('small', { texto: `${c.partido || '—'} · ${c.numero}${c.vice ? ` · vice ${tituloProprio(c.vice)}` : ''}` }),
      probs ? el('small', { classe: 'cand-probs', texto: probs }) : null,
    ]);
    const nums = el('div', { classe: 'cand-num' }, [
      el('span', { classe: 'proj', texto: aguardando ? '—' : pct(c.perc_projetado, 1), title: 'Projeção do resultado final' }),
      el('span', { classe: 'apur', texto: aguardando ? 'sem votos' : `apurado ${pct(c.perc_apurado, 1)}` }),
    ]);
    const entrada = el('input', { type: 'checkbox', 'aria-label': `Exibir ${c.nome} nos gráficos` });
    entrada.checked = marcado;
    entrada.disabled = dois || aguardando;
    entrada.addEventListener('change', () => alternarCandidato(c.numero));
    lista.appendChild(el('li', {}, [
      el('label', { classe: `cand${marcado ? ' marcado' : ''}` }, [entrada, chave, info, nums]),
    ]));
  }
}

/** 2º turno: barra apurado × projetado entre os dois e números do confronto. */
function renderConfronto(d) {
  const caixa = document.getElementById('confronto');
  caixa.hidden = !segundoTurno() || !d.candidatos || d.candidatos.length !== 2;
  if (caixa.hidden) return;
  const [a, b] = d.candidatos;
  G.barrasEmpilhadas(document.getElementById('g-confronto'), {
    margemRotulo: 70, alturaBarra: 22, gap: 12,
    linhas: [
      { rotulo: 'Apurado', segmentos: [{ rotulo: a.nome, cor: cor(a.numero), valor: a.perc_apurado }, { rotulo: b.nome, cor: cor(b.numero), valor: b.perc_apurado }] },
      { rotulo: 'Projetado', segmentos: [{ rotulo: a.nome, cor: cor(a.numero), valor: a.perc_projetado }, { rotulo: b.nome, cor: cor(b.numero), valor: b.perc_projetado }] },
    ],
  });
  const f = (d.analise && d.analise.faltam) || {};
  const mini = (r, v, det) => el('div', { classe: 'mini-kpi' }, [
    el('div', { classe: 'kpi-rotulo', texto: r }), el('div', { classe: 'kpi-valor', texto: v }),
    det ? el('div', { classe: 'kpi-detalhe', texto: det }) : null,
  ]);
  const k = document.getElementById('confronto-kpis');
  k.textContent = '';
  k.append(
    mini('Vantagem projetada', `${nomeCurto(a.numero)} +${fmt1.format(a.perc_projetado - b.perc_projetado)} pontos`,
      `faixa provável de ${nomeCurto(a.numero)}: ${pct(a.ic_inferior_95, 1)} a ${pct(a.ic_superior_95, 1)}`),
  );
  if (f.diferenca_votos_apurados !== undefined) {
    const lider = a.votos_apurados >= b.votos_apurados ? a : b;
    k.append(mini('Diferença na apuração', `${nomeCurto(lider.numero)} +${compacto(Math.abs(a.votos_apurados - b.votos_apurados))} votos`,
      `${compacto(f.validos_restantes_esperados)} válidos ainda a apurar`));
  }
}

// ------------------------------------------------------------------- séries

function serieHistorico(n, fn) {
  const pontos = state.historico
    .filter((r) => r.candidatos.some((c) => c.numero === n))
    .map((r) => fn(r, r.candidatos.find((c) => c.numero === n)))
    .filter(Boolean)
    .sort((a, b) => a.x - b.x);
  return { id: n, rotulo: nome(n), rotuloCurto: nomeCurto(n), cor: cor(n), pontos };
}

function candidatosDosGraficos() {
  return segundoTurno() ? ordemCandidatos().slice(0, 2) : marcadosEmOrdem();
}

const fmtPctEixo = (v) => pct(v, 1);
const SEM_SELECAO = 'Marque candidatos na lista à esquerda para exibir aqui';

// ----------------------------------------------------------------- abas

function renderGeral(d) {
  const nums = candidatosDosGraficos();
  const atualPor = Object.fromEntries(d.candidatos.map((c) => [c.numero, c]));

  // Corrida até 100%: votos acumulados ou % dos válidos, com projeção pontilhada até 100%
  const total = d.total_validos_projetados || 0;
  const emVotos = state.modoCorrida !== 'pct';
  G.corrida(document.getElementById('g-corrida'), {
    vazio: SEM_SELECAO,
    xFmt: (v) => `${fmt1.format(v)}%`,
    yFmt: emVotos ? compacto : (v) => pct(v, 1),
    yFmtEixo: emVotos ? (v) => (v >= 1e6 ? `${fmtInt.format(v / 1e6)} mi` : compacto(v)) : (v) => `${v}%`,
    margemDireita: emVotos ? 160 : 118,
    opacidadeArea: emVotos ? 0.22 : 0.08,
    series: nums.map((n) => {
      const c = atualPor[n];
      const s = serieHistorico(n, (r, h) => (emVotos
        ? { x: r.perc_secoes_apuradas, y: h.votos_apurados, det: pct(h.perc_apurado, 1) }
        : { x: r.perc_secoes_apuradas, y: h.perc_apurado, det: `${compacto(h.votos_apurados)} votos` }));
      if (emVotos) s.pontos.unshift({ x: 0, y: 0 });
      s.final = emVotos
        ? { y: c.media_projetada, lo: c.ic_inferior_95 / 100 * total, hi: c.ic_superior_95 / 100 * total,
            rotulo: `${fmt1.format(c.media_projetada / 1e6)} mi · ${pct(c.perc_projetado, 1)}` }
        : { y: c.perc_projetado, lo: c.ic_inferior_95, hi: c.ic_superior_95 };
      return s;
    }),
  });

  // Intervalos
  G.intervalos(document.getElementById('g-intervalos'), {
    vazio: SEM_SELECAO,
    fmt: (v) => pct(v, 1),
    refs: [{ x: 50, rotulo: '50%' }],
    itens: nums.map((n) => {
      const c = atualPor[n];
      return { rotulo: c.nome, cor: cor(n), lo: c.ic_inferior_95, hi: c.ic_superior_95, media: c.perc_projetado, apurado: c.perc_apurado };
    }),
  });

  // Curva de projeção (faixa só para os 4 primeiros, para não embaralhar)
  G.linhas(document.getElementById('g-projecao'), {
    vazio: SEM_SELECAO, ...cfgEixoX(), yFmt: fmtPctEixo, yPiso: 0, yTeto: 100,
    refs: [{ y: 50, rotulo: '50% dos válidos' }],
    series: nums.map((n, i) => ({
      ...serieHistorico(n, (r, c) => ({ x: valorX(r), y: c.perc_projetado, lo: c.ic_inferior_95, hi: c.ic_superior_95 })),
      banda: i < 4,
    })),
  });

  renderProbabilidades();
}

function renderProbabilidades() {
  const nums = candidatosDosGraficos();
  const nota = document.getElementById('nota-prob');
  let series;
  if (segundoTurno()) {
    nota.textContent = 'Chance de vitória de cada candidato, a cada atualização';
    series = nums.map((n) => serieHistorico(n, (r, c) => ({ x: valorX(r), y: c.prob_vitoria * 100 })));
  } else {
    nota.textContent = 'Chance de haver 2º turno e de cada candidato marcado ir ao 2º turno';
    series = [{
      id: '2t', rotulo: 'Haver 2º turno', rotuloCurto: '2º turno', cor: G.token('--texto-2'),
      pontos: state.historico.map((r) => ({ x: valorX(r), y: (r.prob_segundo_turno || 0) * 100 })).sort((a, b) => a.x - b.x),
    }].concat(nums.map((n) => {
      const s = serieHistorico(n, (r) => {
        const v = r.analise && r.analise.prob_top2 ? r.analise.prob_top2[n] : null;
        return v === null || v === undefined ? null : { x: valorX(r), y: v * 100 };
      });
      return { ...s, rotulo: `${s.rotulo} no 2º turno` };
    }));
  }
  G.linhas(document.getElementById('g-prob'), { series, ...cfgEixoX(), yMin: 0, yMax: 100, yFmt: fmtPctEixo });
}

function liderProjetadoUf(u) {
  let melhor = null;
  for (const [n, v] of Object.entries(u.proj_pct || {})) if (!melhor || v > melhor[1]) melhor = [n, v];
  return melhor;
}

function partes(votos) {
  const total = Object.values(votos || {}).reduce((s, v) => s + v, 0);
  return Object.fromEntries(Object.entries(votos || {}).map(([n, v]) => [n, total ? v / total * 100 : 0]));
}

function pctApurado(u) { return u.secoes_apuradas / Math.max(1, u.secoes_total) * 100; }

function renderMapa(d) {
  const a = d.analise || {};
  const ufs = (a.ufs || []).filter((u) => u.uf !== 'ZZ');
  const ordem = ordemCandidatos();
  const nums = candidatosDosGraficos();
  const [A, B] = nums.length >= 2 ? nums : ordem.slice(0, 2);

  const tooltipUf = (u) => {
    const fr = partes(u.votos);
    const tops = Object.entries(u.proj_pct).sort((x, y) => y[1] - x[1]).slice(0, 3);
    return {
      titulo: `${pct(pctApurado(u), 1)} apurado · ${compacto(u.restantes_esperados)} válidos a apurar`,
      linhas: tops.map(([n, v]) => ({
        cor: cor(n), valor: pct(v, 1),
        rotulo: `${nome(n)} · apurado ${pct(fr[n], 1)} · chance de vencer na UF ${prob(u.prob_lider[n])}`,
      })),
    };
  };

  let dados, escala;
  if (state.modoMapa === 'apurado') {
    dados = ufs.map((u) => ({ uf: u.uf, valor: +pctApurado(u).toFixed(1), tooltip: tooltipUf(u) }));
    escala = { min: 0, max: 100, cores: ['--seq-1', '--seq-2', '--seq-3', '--seq-4', '--seq-5'].map(G.token), rotulos: ['100%', '0%'] };
  } else if (state.modoMapa === 'vantagem' && A && B) {
    const difs = ufs.map((u) => (u.proj_pct[A] || 0) - (u.proj_pct[B] || 0));
    const lim = Math.max(5, Math.ceil(Math.max(...difs.map(Math.abs)) / 5) * 5);
    dados = ufs.map((u, i) => ({ uf: u.uf, valor: +difs[i].toFixed(1), tooltip: tooltipUf(u) }));
    escala = { min: -lim, max: lim, cores: [cor(B), G.token('--div-meio'), cor(A)], rotulos: [`${nomeCurto(A)} +${lim}`, `${nomeCurto(B)} +${lim}`] };
  } else if (state.modoMapa === 'crescimento' && A && B) {
    const cr = crescimentoUfs(a, state.versaoCrescimento);
    const comDados = ufs.filter((u) => cr[u.uf]);
    const difs = comDados.map((u) => (cr[u.uf][A] || 0) - (cr[u.uf][B] || 0));
    const lim = Math.max(5, Math.ceil(Math.max(0, ...difs.map(Math.abs)) / 5) * 5);
    dados = comDados.map((u, i) => ({
      uf: u.uf, valor: +difs[i].toFixed(1),
      tooltip: {
        titulo: `Razão de crescimento (${state.versaoCrescimento}) · ${pct(pctApurado(u), 1)} apurado`,
        linhas: Object.entries(cr[u.uf]).sort((x, y) => y[1] - x[1]).slice(0, 3)
          .map(([n, v]) => ({ cor: cor(n), valor: pct(v, 1), rotulo: nome(n) })),
      },
    }));
    escala = { min: -lim, max: lim, cores: [cor(B), G.token('--div-meio'), cor(A)], rotulos: [`${nomeCurto(A)} +${lim}`, `${nomeCurto(B)} +${lim}`] };
  } else {
    dados = ufs.filter((u) => !u.sem_dados).map((u) => {
      const l = liderProjetadoUf(u);
      return { uf: u.uf, cor: l ? cor(l[0]) : G.token('--neutro'), tooltip: tooltipUf(u) };
    });
  }
  G.mapa(document.getElementById('g-mapa'), {
    dados, escala, selecionada: state.ufSelecionada,
    aoClicar: (uf) => { if (NOMES_UF[uf]) { state.ufSelecionada = uf; renderDetalheUf(state.atual); } },
  });

  // Rodapé: legenda dos líderes (modo líder) e o exterior, que não aparece no mapa
  const rodape = document.getElementById('mapa-rodape');
  rodape.textContent = '';
  if (state.modoMapa === 'lider') {
    const lideres = [...new Set(ufs.filter((u) => !u.sem_dados).map((u) => (liderProjetadoUf(u) || [])[0]).filter(Boolean))];
    for (const n of lideres) {
      const qtd = ufs.filter((u) => (liderProjetadoUf(u) || [])[0] === n).length;
      rodape.appendChild(el('span', {}, [el('span', { classe: 'chave-tab', estilo: { background: cor(n) } }), `${nome(n)}: ${qtd} UF${qtd > 1 ? 's' : ''}`]));
    }
  }
  const zz = (a.ufs || []).find((u) => u.uf === 'ZZ');
  if (zz) {
    const l = liderProjetadoUf(zz);
    rodape.appendChild(el('span', { texto: `Exterior: ${pct(pctApurado(zz), 1)} apurado${l ? ` · ${nomeCurto(l[0])} ${pct(l[1], 1)}` : ''}` }));
  }
  renderDetalheUf(d);
}

function renderDetalheUf(d) {
  const a = d.analise || {};
  const ufs = (a.ufs || []).map((u) => u.uf);
  if (!state.ufSelecionada || !ufs.includes(state.ufSelecionada)) {
    const maior = [...(a.ufs || [])].sort((x, y) => y.restantes_esperados - x.restantes_esperados)[0];
    state.ufSelecionada = maior ? maior.uf : ufs[0];
  }
  const u = (a.ufs || []).find((x) => x.uf === state.ufSelecionada);
  if (!u) return;
  document.getElementById('uf-titulo').textContent = `${NOMES_UF[u.uf] || u.uf} (${u.uf})`;
  const l = liderProjetadoUf(u);
  const mini = (r, v) => el('div', { classe: 'mini-kpi' }, [el('div', { classe: 'kpi-rotulo', texto: r }), el('div', { classe: 'kpi-valor', texto: v })]);
  const caixa = document.getElementById('uf-kpis');
  caixa.textContent = '';
  caixa.append(
    mini('Seções apuradas', pct(pctApurado(u), 1)),
    mini('Válidos apurados', compacto(u.votos_validos)),
    mini('Válidos a apurar', compacto(u.restantes_esperados)),
    mini('Líder projetado', l ? `${nomeCurto(l[0])} · ${prob(u.prob_lider[l[0]])}` : '—'),
  );

  const nums = candidatosDosGraficos();
  const mostrar = (nums.length ? nums : ordemCandidatos().slice(0, PRINCIPAIS)).slice(0, 6);
  const fr = partes(u.votos);
  G.apuradoProjetado(document.getElementById('g-uf-barras'), {
    fmt: (v) => pct(v, 1),
    itens: mostrar.map((n) => ({ rotulo: nome(n), cor: cor(n), apurado: fr[n] || 0, projetado: u.proj_pct[n] || 0 })),
  });

  const top = mostrar.slice(0, 3);
  const thead = document.querySelector('#tabela-estratos thead');
  thead.textContent = '';
  thead.appendChild(el('tr', {}, [
    el('th', { texto: 'Cidade / interior' }), el('th', { texto: '% apurado' }),
    ...top.map((n) => el('th', { classe: 'num' }, [el('span', { classe: 'chave-tab', estilo: { background: cor(n) } }), nomeCurto(n)])),
    el('th', { classe: 'num', texto: 'A apurar' }),
  ]));
  const corpo = document.querySelector('#tabela-estratos tbody');
  corpo.textContent = '';
  const estratos = consolidarInterior((a.estratos || []).filter((e) => e.uf === u.uf))
    .sort((x, y) => (ORDEM_TIPO[x.tipo] - ORDEM_TIPO[y.tipo]) || (y.eleitores_aptos - x.eleitores_aptos));
  for (const e of estratos) {
    const apur = e.secoes_apuradas / Math.max(1, e.secoes_total) * 100;
    const fe = partes(e.votos);
    const rotulo = e.tipo === 'CAPITAL' ? `${e.nome} (capital)` : e.nome;
    corpo.appendChild(el('tr', { classe: e.tipo === 'INTERIOR' ? 'destaque' : '' }, [
      el('td', { texto: rotulo, title: ROTULO_TIPO[e.tipo] || '' }),
      el('td', {}, [el('span', { classe: 'mini-medidor' }, [el('span', { estilo: { width: `${apur}%` } })]), pct(apur, 1)]),
      ...top.map((n) => el('td', { classe: 'num', texto: e.votos_validos ? pct(fe[n], 1) : '—' })),
      el('td', { classe: 'num', texto: compacto(e.restantes_esperados) }),
    ]));
  }
}

function consolidarInterior(estratos) {
  const partes = estratos.filter((e) => e.tipo === 'SUBESTRATO');
  if (!partes.length || estratos.some((e) => e.tipo === 'INTERIOR')) return estratos;
  const campos = ['secoes_total', 'secoes_apuradas', 'eleitores_aptos', 'comparecimento', 'abstencao',
    'votos_validos', 'votos_brancos', 'votos_nulos', 'votos_anulados', 'restantes_esperados'];
  const soma = (campo) => partes.reduce((total, e) => total + (Number(e[campo]) || 0), 0);
  const votos = {};
  for (const e of partes) {
    for (const [numero, quantidade] of Object.entries(e.votos || {})) votos[numero] = (votos[numero] || 0) + (Number(quantidade) || 0);
  }
  const interior = Object.fromEntries(campos.map((campo) => [campo, soma(campo)]));
  return [...estratos, {
    id: `${partes[0].uf}_INTERIOR_CONSOLIDADO`, uf: partes[0].uf, tipo: 'INTERIOR',
    nome: 'Interior (consolidado)', ...interior, votos,
  }];
}

function renderCenarios(d) {
  const a = d.analise || {};
  const dist = a.distribuicao_final || {};
  const nums = candidatosDosGraficos();
  let chaves = Object.keys(dist).filter((n) => nums.includes(n));
  if (!chaves.length) chaves = Object.keys(dist);
  const series = chaves.map((n) => ({ rotulo: nome(n), cor: cor(n), ...dist[n] }));
  const ext = series.flatMap((s) => [s.inicio, s.inicio + s.passo * s.freq.length]);
  const refs = ext.length && Math.min(...ext) - 6 < 50 && Math.max(...ext) + 6 > 50 ? [{ x: 50, rotulo: '50%' }] : [];
  G.histograma(document.getElementById('g-dist'), { series, refs, xFmt: (v) => `${fmt1.format(v)}%` });

  const m = a.distribuicao_margem;
  const nota = document.getElementById('nota-margem');
  if (m) {
    nota.textContent = `${nome(m.lider)} − ${nome(m.segundo)}, em pontos percentuais · ${nomeCurto(m.lider)} à frente em ${prob(m.prob_positiva)} dos cenários`;
    G.histograma(document.getElementById('g-margem'), {
      series: [{ rotulo: `Margem ${nomeCurto(m.lider)} − ${nomeCurto(m.segundo)}`, cor: G.token('--seq'), ...m }],
      refs: [{ x: 0, rotulo: 'empate' }],
      xFmt: (v) => `${v >= 0 ? '+' : '−'}${fmt1.format(Math.abs(v))}`,
    });
  } else {
    G.vazio(document.getElementById('g-margem'));
  }

  const f = a.faltam || {};
  const caixa = document.getElementById('falta-kpis');
  caixa.textContent = '';
  const mini = (r, v, det) => el('div', { classe: 'mini-kpi' }, [
    el('div', { classe: 'kpi-rotulo', texto: r }), el('div', { classe: 'kpi-valor', texto: v }),
    det ? el('div', { classe: 'kpi-detalhe', texto: det }) : null,
  ]);
  caixa.append(mini('Válidos ainda a apurar', compacto(f.validos_restantes_esperados), `total final esperado: ${compacto(f.validos_finais_esperados)}`));
  if (f.lider) {
    const precisa = f.lider_precisa_pct_restantes;
    caixa.append(mini(`${nome(f.lider)} precisa de`,
      precisa === null || precisa === undefined ? '—' : (precisa <= 0 ? 'já tem mais de 50%' : pct(precisa, 1)),
      'dos votos restantes para passar de 50%'));
  }
  if (f.segundo) {
    caixa.append(mini(`Diferença ${nomeCurto(f.lider)} − ${nomeCurto(f.segundo)}`,
      `${f.diferenca_votos_apurados >= 0 ? '+' : '−'}${compacto(Math.abs(f.diferenca_votos_apurados))} votos`,
      f.segundo_precisa_vantagem_pp_restantes === null ? '' :
        `para virar, ${nomeCurto(f.segundo)} precisa de ${fmt1.format(Math.max(0, f.segundo_precisa_vantagem_pp_restantes))} pontos a mais nos votos restantes`));
  }
  const lista = (a.ufs || []).filter((u) => u.restantes_esperados > 0).sort((x, y) => y.restantes_esperados - x.restantes_esperados);
  G.colunas(document.getElementById('g-restantes'), {
    vazio: 'Apuração concluída: não há votos a apurar',
    categorias: lista.map((u) => u.uf),
    titulos: lista.map((u) => NOMES_UF[u.uf] || u.uf),
    valores: lista.map((u) => u.restantes_esperados),
    detalhes: lista.map((u) => `válidos a apurar · ${pct(pctApurado(u), 1)} apurado`),
    fmt: compacto,
  });
}

function renderApuracao(d) {
  const nums = candidatosDosGraficos();
  G.linhas(document.getElementById('g-apurado'), {
    vazio: SEM_SELECAO, ...cfgEixoX(), yFmt: fmtPctEixo, yPiso: 0,
    series: nums.map((n) => serieHistorico(n, (r, c) => ({ x: valorX(r), y: c.perc_apurado }))),
  });

  const pts = state.historico.map((r) => ({ x: tsParaMs(r.timestamp), y: r.perc_secoes_apuradas })).sort((a, b) => a.x - b.x);
  G.linhas(document.getElementById('g-ritmo'), {
    series: [{ id: 'ritmo', rotulo: 'Seções apuradas', rotuloCurto: 'Seções', cor: G.token('--seq'), pontos: pts }],
    xFmt: fmtHoraAdaptativo(), xTitulo: fmtHoraSeg, yMin: 0, yMax: 100, yFmt: fmtPctEixo,
  });
  const caixa = document.getElementById('ritmo-kpis');
  caixa.textContent = '';
  if (pts.length >= 2) {
    const ult = pts[pts.length - 1];
    const ini = pts.find((p) => p.x >= ult.x - 10 * 60 * 1000) || pts[0];
    const minutos = (ult.x - ini.x) / 60000;
    const ritmo = minutos > 0 ? (ult.y - ini.y) / minutos : 0;
    const resta = ritmo > 0 ? (100 - ult.y) / ritmo : null;
    const mini = (r, v) => el('div', { classe: 'mini-kpi' }, [el('div', { classe: 'kpi-rotulo', texto: r }), el('div', { classe: 'kpi-valor', texto: v })]);
    caixa.append(
      mini('Ritmo (últimos 10 min)', `${fmt1.format(ritmo)} pontos/min`),
      mini('Término previsto', resta === null ? '—' : (ult.y >= 100 ? 'concluída' : fmtHora(ult.x + resta * 60000))),
      mini('Atualizações', fmtInt.format(pts.length)),
    );
  }

  // UFs agrupadas por região (ordem geográfica), cada grupo com a média da região
  const a = d.analise || {};
  const ORDEM_REGIAO = ['Norte', 'Nordeste', 'Centro-Oeste', 'Sudeste', 'Sul', 'Exterior'];
  const ufs = [...(a.ufs || [])].sort((x, y) => (ORDEM_REGIAO.indexOf(x.regiao) - ORDEM_REGIAO.indexOf(y.regiao))
    || (pctApurado(y) - pctApurado(x)));
  const grupos = [];
  ufs.forEach((u, i) => {
    const g = grupos[grupos.length - 1];
    if (g && g.regiao === u.regiao) g.fim = i;
    else grupos.push({ regiao: u.regiao, inicio: i, fim: i });
  });
  for (const g of grupos) {
    const r = (a.regioes || []).find((x) => x.regiao === g.regiao);
    g.media = r ? +pctApurado(r).toFixed(1) : undefined;
    g.nome = g.regiao === 'Exterior' ? 'Ext.' : `${g.regiao}${g.media !== undefined ? ` ${fmt1.format(g.media)}%` : ''}`;
  }
  G.colunas(document.getElementById('g-apuracao-uf'), {
    grupos,
    categorias: ufs.map((u) => u.uf),
    titulos: ufs.map((u) => NOMES_UF[u.uf] || u.uf),
    valores: ufs.map((u) => +pctApurado(u).toFixed(1)),
    detalhes: ufs.map((u) => `das seções · ${u.regiao} · ${compacto(u.restantes_esperados)} válidos a apurar`),
    fmt: (v) => pct(v, 1), fmtEixo: (v) => `${v}%`, max: 100,
    ref: d.perc_secoes_apuradas, refRotulo: `Brasil ${pct(d.perc_secoes_apuradas, 1)}`,
  });
}

function segmentos(fracoes) {
  const nums = candidatosDosGraficos();
  const mostrar = nums.length ? nums : ordemCandidatos().slice(0, PRINCIPAIS);
  const segs = mostrar.map((n) => ({ rotulo: nome(n), cor: cor(n), valor: fracoes[n] || 0 }));
  const demais = Object.entries(fracoes).filter(([n]) => !mostrar.includes(n)).reduce((s, [, v]) => s + v, 0);
  if (demais > 0.005) segs.push({ rotulo: 'Demais candidatos', cor: G.token('--neutro'), valor: demais });
  return segs;
}

function renderEstratos(d) {
  const a = d.analise || {};
  const linhas = [];
  for (const r of (a.regioes || [])) {
    linhas.push({ rotulo: `${r.regiao} · A (${fmt1.format(pctApurado(r))}%)`, segmentos: segmentos(partes(r.votos)), grupoInicio: linhas.length > 0 });
    linhas.push({ rotulo: `${r.regiao} · P`, segmentos: segmentos(r.proj_pct || {}) });
  }
  G.barrasEmpilhadas(document.getElementById('g-regioes'), { linhas, margemRotulo: 150, alturaBarra: 16, gap: 6 });

  const tipos = (a.tipos_estrato || []).filter((t) => t.tipo !== 'SEM_DADOS')
    .sort((x, y) => ORDEM_TIPO[x.tipo] - ORDEM_TIPO[y.tipo])
    .map((t) => ({ rotulo: `${ROTULO_TIPO[t.tipo] || t.tipo} (${fmt1.format(pctApurado(t))}% apur.)`, segmentos: segmentos(partes(t.votos)) }));
  G.barrasEmpilhadas(document.getElementById('g-tipos'), { linhas: tipos, margemRotulo: 230, alturaBarra: 22, gap: 14 });
}

const COLUNAS_UF = [
  { chave: 'uf', rotulo: 'UF', valor: (u) => u.uf },
  { chave: 'regiao', rotulo: 'Região', valor: (u) => u.regiao },
  { chave: 'apurado', rotulo: '% apurado', num: true, valor: pctApurado, fmt: (v) => pct(v, 1) },
  { chave: 'validos', rotulo: 'Válidos apurados', num: true, valor: (u) => u.votos_validos, fmt: (v) => fmtInt.format(v) },
  { chave: 'lider_apur', rotulo: 'Líder na apuração', valor: (u) => liderApurado(u), fmt: (v) => v || '—' },
  { chave: 'lider_proj', rotulo: 'Líder projetado', valor: (u) => { const l = liderProjetadoUf(u); return l ? `${nomeCurto(l[0])} ${pct(l[1], 1)}` : '—'; } },
  { chave: 'prob', rotulo: 'Chance do líder na UF', num: true, valor: (u) => { const l = liderProjetadoUf(u); return l ? u.prob_lider[l[0]] : 0; }, fmt: prob },
  { chave: 'restantes', rotulo: 'Válidos a apurar', num: true, valor: (u) => u.restantes_esperados, fmt: compacto },
];

function liderApurado(u) {
  const total = Object.values(u.votos).reduce((s, v) => s + v, 0);
  if (!total) return '';
  const [n, v] = Object.entries(u.votos).sort((x, y) => y[1] - x[1])[0];
  return `${nomeCurto(n)} ${pct(v / total * 100, 1)}`;
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

function situacaoCandidato(d, c, posicao) {
  const status = d.status_call;
  if (d.vencedor_projetado === c.numero) {
    return status === 'MATEMATICAMENTE_ELEITO' ? ['Eleito', 'eleito'] : ['Vitória projetada', 'eleito'];
  }
  if (status === 'SEGUNDO_TURNO_PROJETADO' && posicao < 2) {
    return [d.perc_secoes_apuradas >= 100 ? '2º turno' : '2º turno (projeção)', 'segundo'];
  }
  return null;
}

function renderConsolidado(d) {
  const thead = document.querySelector('#tabela-consolidado thead');
  thead.textContent = '';
  thead.appendChild(el('tr', {}, [
    el('th', { texto: '#' }), el('th', { texto: 'Candidato' }),
    el('th', { classe: 'num', texto: 'Votos' }), el('th', { classe: 'num', texto: '% válidos' }),
    el('th', { classe: 'num', texto: '% proj.' }), el('th', { classe: 'num', texto: 'Faixa provável (%)' }),
    el('th', { texto: 'Situação' }),
  ]));
  const corpo = document.querySelector('#tabela-consolidado tbody');
  corpo.textContent = '';
  // ordem pelo apurado (como no TSE); a projeção fica ao lado
  const ordem = [...d.candidatos].sort((a, b) => b.votos_apurados - a.votos_apurados);
  const porProjecao = d.candidatos.map((c) => c.numero);
  ordem.forEach((c, i) => {
    const sit = situacaoCandidato(d, c, porProjecao.indexOf(c.numero));
    corpo.appendChild(el('tr', {}, [
      el('td', { classe: 'num', texto: `${i + 1}º` }),
      el('td', { classe: 'cand-cel', title: descricaoChapa(c) }, [
        el('strong', {}, [el('span', { classe: 'chave-tab', estilo: { background: cor(c.numero) } }), c.nome]),
        el('small', { texto: `${c.partido || '—'} · ${c.numero}${c.vice ? ` · vice ${tituloProprio(c.vice)}` : ''}` }),
      ]),
      el('td', { classe: 'num', texto: fmtInt.format(c.votos_apurados) }),
      el('td', { classe: 'num' }, [el('strong', { texto: pct(c.perc_apurado) })]),
      el('td', { classe: 'num', texto: pct(c.perc_projetado) }),
      el('td', { classe: 'num', texto: `${pct(c.ic_inferior_95).replace('%', '')}–${pct(c.ic_superior_95).replace('%', '')}` }),
      el('td', {}, [sit ? el('span', { classe: `situacao ${sit[1]}`, texto: sit[0] }) : '—']),
    ]));
  });
  const pe = document.querySelector('#tabela-consolidado tfoot');
  pe.textContent = '';
  pe.appendChild(el('tr', {}, [
    el('td', {}), el('td', { texto: 'Total de votos válidos' }),
    el('td', { classe: 'num', texto: fmtInt.format(d.total_validos_apurados) }),
    el('td', { classe: 'num', texto: '100%' }), el('td', {}), el('td', {}), el('td', {}),
  ]));
  document.getElementById('nota-consolidado').textContent =
    `${pct(d.perc_secoes_apuradas)} das seções apuradas · ordenado pelos votos apurados`;

  const n = (d.analise && d.analise.nacional) || {};
  const f = (d.analise && d.analise.faltam) || {};
  const eleitApur = (n.comparecimento || 0) + (n.abstencao || 0);
  const linhas = [
    ['Eleitorado', fmtInt.format(d.total_eleitores), ''],
    ['Seções apuradas', `${fmtInt.format(d.secoes_apuradas)} / ${fmtInt.format(d.total_secoes)}`, pct(d.perc_secoes_apuradas)],
    ['Comparecimento', fmtInt.format(n.comparecimento || 0), pct(n.pct_comparecimento)],
    ['Abstenção', fmtInt.format(n.abstencao || 0), pct(n.pct_abstencao)],
    ['Votos válidos', fmtInt.format(n.votos_validos || 0), pct(n.pct_validos)],
    ['Brancos', fmtInt.format(n.votos_brancos || 0), pct(n.pct_brancos)],
    ['Nulos', fmtInt.format(n.votos_nulos || 0), pct(n.pct_nulos)],
  ];
  if ((n.votos_anulados || 0) > 0) linhas.push(['Anulados (sub judice)', fmtInt.format(n.votos_anulados), pct(n.pct_anulados)]);
  if (d.perc_secoes_apuradas < 100) linhas.push(['Válidos no final (proj.)', fmtInt.format(f.validos_finais_esperados || 0), '']);
  const corpoT = document.querySelector('#tabela-totais tbody');
  corpoT.textContent = '';
  for (const [r, v, p] of linhas) {
    corpoT.appendChild(el('tr', {}, [el('td', { texto: r }), el('td', { classe: 'num', texto: v }), el('td', { classe: 'num', texto: p })]));
  }

  const comp = n.comparecimento || 0;
  const parte = (x, t) => (t ? x / t * 100 : 0);
  G.barrasEmpilhadas(document.getElementById('g-composicao'), {
    margemRotulo: 92, alturaBarra: 22, gap: 18,
    linhas: [
      { rotulo: 'Eleitores', segmentos: [
        { rotulo: 'Compareceram', cor: G.token('--seq'), valor: parte(comp, eleitApur) },
        { rotulo: 'Abstenção', cor: G.token('--neutro'), valor: parte(n.abstencao || 0, eleitApur) },
      ] },
      { rotulo: 'Votos', segmentos: [
        { rotulo: 'Válidos', cor: G.token('--seq'), valor: parte(n.votos_validos || 0, comp) },
        { rotulo: 'Brancos', cor: G.token('--seq-2'), valor: parte(n.votos_brancos || 0, comp) },
        { rotulo: 'Nulos', cor: G.token('--neutro'), valor: parte(n.votos_nulos || 0, comp) },
        ...((n.votos_anulados || 0) > 0 ? [{ rotulo: 'Anulados (sub judice)', cor: G.token('--neutro-claro'), valor: parte(n.votos_anulados, comp) }] : []),
      ] },
    ],
  });
}

function somarExterior(cidades) {
  const t = { secoes_total: 0, secoes_apuradas: 0, eleitores: 0, comparecimento: 0, abstencao: 0, votos_validos: 0, votos: {} };
  for (const c of cidades) {
    for (const k of ['secoes_total', 'secoes_apuradas', 'eleitores', 'comparecimento', 'abstencao', 'votos_validos']) t[k] += c[k] || 0;
    for (const [n, v] of Object.entries(c.votos || {})) t.votos[n] = (t.votos[n] || 0) + v;
  }
  return t;
}

function liderVotos(votos) {
  const total = Object.values(votos).reduce((s, v) => s + v, 0);
  if (!total) return null;
  const [n, v] = Object.entries(votos).sort((a, b) => b[1] - a[1])[0];
  return [n, v / total * 100];
}

function renderExterior(d) {
  const cidades = (d.analise && d.analise.exterior) || [];
  const kpis = document.getElementById('exterior-kpis');
  kpis.textContent = '';
  const tbody = document.querySelector('#tabela-exterior tbody');
  const thead = document.querySelector('#tabela-exterior thead');
  if (!cidades.length) {
    G.vazio(document.getElementById('g-exterior'), 'Aguardando o resultado das cidades do exterior (baixado a cada 2 minutos)');
    thead.textContent = '';
    tbody.textContent = '';
    return;
  }
  // Agrupa por país
  const paises = {};
  for (const c of cidades) (paises[c.pais] = paises[c.pais] || { pais: c.pais, continente: c.continente, cidades: [] }).cidades.push(c);
  const lista = Object.values(paises).map((p) => ({ ...p, ...somarExterior(p.cidades) }))
    .sort((a, b) => (b.votos_validos - a.votos_validos) || (b.eleitores - a.eleitores));

  const total = somarExterior(cidades);
  const lider = liderVotos(total.votos);
  const mini = (r, v) => el('div', { classe: 'mini-kpi' }, [el('div', { classe: 'kpi-rotulo', texto: r }), el('div', { classe: 'kpi-valor', texto: v })]);
  kpis.append(
    mini('Eleitores no exterior', compacto(total.eleitores)),
    mini('Seções apuradas', pct(total.secoes_apuradas / Math.max(1, total.secoes_total) * 100, 1)),
    mini('Comparecimento', pct(total.comparecimento / Math.max(1, total.comparecimento + total.abstencao) * 100, 1)),
    mini('Votos válidos', compacto(total.votos_validos)),
    mini('Líder no exterior', lider ? `${nomeCurto(lider[0])} ${pct(lider[1], 1)}` : '—'),
    mini('Países', `${lista.length} · ${cidades.length} cidades`),
  );

  // Gráfico: países com mais votos (partes dos candidatos marcados + demais)
  const comVotos = lista.filter((p) => p.votos_validos > 0).slice(0, 18);
  document.getElementById('nota-exterior').textContent = comVotos.length
    ? `${comVotos.length} países com mais votos válidos apurados` : 'Nenhum voto apurado no exterior ainda';
  G.barrasEmpilhadas(document.getElementById('g-exterior'), {
    margemRotulo: 190, alturaBarra: 14, gap: 6, vazio: 'Nenhum voto apurado no exterior ainda',
    linhas: comVotos.map((p) => ({
      rotulo: `${p.pais} · ${compacto(p.votos_validos)}`,
      segmentos: segmentos(partes(p.votos)),
    })),
  });

  // Tabela: países (clique abre as cidades)
  const destaques = candidatosDosGraficos().slice(0, 2);
  thead.textContent = '';
  thead.appendChild(el('tr', {}, [
    el('th', { texto: 'País / cidade' }), el('th', { classe: 'num', texto: 'Apur.' }),
    el('th', { classe: 'num', texto: 'Válidos' }),
    ...destaques.map((n) => el('th', { classe: 'num' }, [el('span', { classe: 'chave-tab', estilo: { background: cor(n) } }), nomeCurto(n)])),
  ]));
  tbody.textContent = '';
  state.paisesAbertos = state.paisesAbertos || new Set();
  const linha = (rotulo, x, classe, continente) => {
    const fr = partes(x.votos);
    const l = liderVotos(x.votos);
    return el('tr', { classe, title: continente || '' }, [
      el('td', { texto: rotulo }),
      el('td', { classe: 'num', texto: pct(x.secoes_apuradas / Math.max(1, x.secoes_total) * 100, 1) }),
      el('td', { classe: 'num', texto: fmtInt.format(x.votos_validos) }),
      ...destaques.map((n) => el('td', { classe: 'num', texto: x.votos_validos ? pct(fr[n], 1) : '—',
        estilo: l && l[0] === n ? { fontWeight: '700' } : {} })),
    ]);
  };
  for (const p of lista) {
    const aberto = state.paisesAbertos.has(p.pais);
    const tr = linha(`${p.pais} (${p.cidades.length})`, p, `pais${aberto ? ' aberto' : ''}`, p.continente);
    tr.tabIndex = 0;
    const alternar = () => {
      if (state.paisesAbertos.has(p.pais)) state.paisesAbertos.delete(p.pais); else state.paisesAbertos.add(p.pais);
      renderExterior(state.atual);
    };
    tr.addEventListener('click', alternar);
    tr.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); alternar(); } });
    tbody.appendChild(tr);
    if (aberto) {
      for (const c of [...p.cidades].sort((a, b) => b.votos_validos - a.votos_validos)) {
        tbody.appendChild(linha(tituloProprio(c.cidade), c, 'cidade', ''));
      }
    }
  }
}

// --------------------------------------------- subestratos (normal × subestratificado)

function cabecalhoTabela(seletor, colunas) {
  const thead = document.querySelector(`${seletor} thead`);
  thead.textContent = '';
  thead.appendChild(el('tr', {}, colunas));
  const corpo = document.querySelector(`${seletor} tbody`);
  corpo.textContent = '';
  return corpo;
}
function thCandidato(n, sufixo = '') {
  return el('th', { classe: 'num' }, [el('span', { classe: 'chave-tab', estilo: { background: cor(n) } }), nomeCurto(n) + sufixo]);
}
const fmtDif = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${fmt2.format(Math.abs(v))}`;

function renderSubestratos(d) {
  const sub = (d.analise || {}).subestratificacao;
  const ids = ['g-sub-intervalos', 'g-sub-uf', 'g-sub-nacional'];
  const controle = document.getElementById('controle-versao');
  if (!sub) {
    controle.hidden = true;
    document.getElementById('sub-kpis').textContent = '';
    for (const id of ids) G.vazio(document.getElementById(id), 'Sem subestratos nesta apuração (ou ainda sem os arquivos dos municípios do grupo)');
    cabecalhoTabela('#tabela-sub', []);
    document.getElementById('sub-explicacao').textContent = '';
    return;
  }
  controle.hidden = false;
  for (const b of controle.querySelectorAll('[data-versao]')) {
    const ativo = b.dataset.versao === sub.versao_principal;
    b.classList.toggle('ativo', ativo);
    b.setAttribute('aria-pressed', String(ativo));
  }
  const uf = sub.ufs[0];
  const nomeUf = NOMES_UF[uf] || uf;
  document.getElementById('sub-titulo').textContent = `${nomeUf}: normal × subestratificado`;
  document.getElementById('sub-hist-titulo').textContent = `${nomeUf} ao longo da apuração`;
  const versoes = ['subestratificado', 'normal'];
  const v = sub.versoes;
  const nums = candidatosDosGraficos().slice(0, 4);

  // KPIs: líder em cada versão e status nacional de cada versão
  const mini = (r, val, det) => el('div', { classe: 'mini-kpi' }, [
    el('div', { classe: 'kpi-rotulo', texto: r }), el('div', { classe: 'kpi-valor', texto: val }),
    det ? el('div', { classe: 'kpi-detalhe', texto: det }) : null]);
  const caixa = document.getElementById('sub-kpis');
  caixa.textContent = '';
  for (const ver of versoes) {
    const dados = (v[ver].ufs || {})[uf] || {};
    const lider = Object.entries(dados).sort((a, b) => b[1].pct - a[1].pct)[0];
    caixa.append(mini(
      `${nomeUf} · ${ROTULO_VERSAO[ver]}${ver === sub.versao_principal ? ' (principal)' : ''}`,
      lider ? `${nomeCurto(lider[0])} ${pct(lider[1].pct, 1)}` : '—',
      lider ? `chance de liderar ${prob(lider[1].prob_lider)}` : '',
    ));
  }
  if (nums.length) {
    const n = nums[0];
    const dif = (v.subestratificado.nacional[n] || {}).pct - (v.normal.nacional[n] || {}).pct;
    caixa.append(mini(`Efeito no Brasil (${nomeCurto(n)})`, `${fmtDif(dif)} p.p.`, 'subestratificado − normal'));
  }

  // Intervalos de cada candidato nas duas versões
  G.intervalos(document.getElementById('g-sub-intervalos'), {
    vazio: SEM_SELECAO, fmt: (x) => pct(x, 1), refs: [{ x: 50, rotulo: '50%' }],
    itens: nums.flatMap((n) => versoes.map((ver) => {
      const c = ((v[ver].ufs || {})[uf] || {})[n];
      return c ? { rotulo: `${nomeCurto(n)} · ${ROTULO_VERSAO[ver]}`, cor: cor(n), lo: c.ic[0], hi: c.ic[1], media: c.pct } : null;
    }).filter(Boolean)),
  });

  // Tabela: o interior em cada versão
  const top = nums.slice(0, 2);
  const corpo = cabecalhoTabela('#tabela-sub', [
    el('th', { texto: 'Parte' }), el('th', { texto: 'Versão' }), el('th', { texto: '% apurado' }),
    ...top.map((n) => thCandidato(n, ' apurado')), ...top.map((n) => thCandidato(n, ' cresc.')),
  ]);
  for (const ver of versoes) {
    for (const e of v[ver].estratos.filter((x) => x.tipo === 'INTERIOR' || x.tipo === 'SUBESTRATO' || x.tipo === 'SUBESTRATO_CIDADES')) {
      const apur = e.secoes_apuradas / Math.max(1, e.secoes_total) * 100;
      corpo.appendChild(el('tr', { classe: ver === sub.versao_principal ? 'destaque' : '' }, [
        el('td', { texto: e.nome }), el('td', { texto: ROTULO_VERSAO[ver] }),
        el('td', {}, [el('span', { classe: 'mini-medidor' }, [el('span', { estilo: { width: `${apur}%` } })]), pct(apur, 1)]),
        ...top.map((n) => el('td', { classe: 'num', texto: e.secoes_apuradas ? pct(e.pct_apurado[n], 1) : '—' })),
        ...top.map((n) => el('td', { classe: 'num', texto: e.crescimento ? pct(e.crescimento[n], 1) : '—' })),
      ]));
    }
  }
  document.getElementById('sub-explicacao').textContent =
    `A versão normal projeta cada cidade grande de ${nomeUf} e o interior inteiro. A versão subestratificada divide o estado ` +
    'em regiões e projeta, em cada uma, as cidades grandes e o interior com a própria tendência, o que corrige o viés quando ' +
    'uma região é apurada mais devagar. ' +
    'A versão principal define os números do painel e a chamada da disputa.';

  // Histórico: UF e Brasil nas duas versões
  const serieVersao = (n, ver, onde) => {
    const s = serieHistorico(n, (r) => {
      const vr = r.analise && r.analise.versoes_resumo && r.analise.versoes_resumo[ver];
      const val = vr && vr[onde] ? vr[onde][n] : undefined;
      return val === undefined ? null : { x: valorX(r), y: val };
    });
    return { ...s, id: `${n}-${ver}`, rotulo: `${s.rotulo} · ${ROTULO_VERSAO[ver]}`,
      rotuloCurto: `${s.rotuloCurto} ${ver === 'normal' ? 'norm.' : 'sub.'}`, espessura: ver === 'normal' ? 1 : 2.5 };
  };
  for (const [id, onde] of [['g-sub-uf', uf], ['g-sub-nacional', 'nacional']]) {
    G.linhas(document.getElementById(id), {
      vazio: SEM_SELECAO, ...cfgEixoX(), yFmt: fmtPctEixo, refs: [{ y: 50, rotulo: '50%' }],
      series: nums.slice(0, 2).flatMap((n) => versoes.map((ver) => serieVersao(n, ver, onde))),
    });
  }
}

async function definirVersao(versao) {
  try {
    const r = await fetch('/api/v1/projecao/versao', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ versao }),
    });
    const corpo = await r.json();
    if (!r.ok) throw new Error(corpo.detail || r.statusText);
    document.getElementById('sub-explicacao').textContent =
      `Versão principal: ${ROTULO_VERSAO[versao]}. Os números do painel mudam na próxima atualização.`;
  } catch (e) {
    document.getElementById('sub-explicacao').textContent = `Não foi possível trocar a versão: ${e.message}`;
  }
}

// ------------------------------------------------- projeção por crescimento (extra)

function renderCrescimento(d) {
  const a = d.analise || {};
  const cresc = a.crescimento;
  const nums = candidatosDosGraficos();
  if (!cresc) {
    for (const id of ['g-cresc', 'g-cresc-dif']) G.vazio(document.getElementById(id), 'Aguardando votos apurados');
    return;
  }
  const serieCresc = (n, fn) => serieHistorico(n, (r, c) => {
    const v = r.analise && r.analise.crescimento_nacional ? r.analise.crescimento_nacional[n] : undefined;
    return v === undefined ? null : fn(r, c, v);
  });
  G.linhas(document.getElementById('g-cresc'), {
    vazio: SEM_SELECAO, ...cfgEixoX(), yFmt: fmtPctEixo, refs: [{ y: 50, rotulo: '50%' }],
    series: nums.flatMap((n) => {
      const principal = serieHistorico(n, (r, c) => ({ x: valorX(r), y: c.perc_projetado }));
      const s = serieCresc(n, (r, c, v) => ({ x: valorX(r), y: v }));
      return [{ ...principal, id: `${n}-p`, rotuloCurto: `${principal.rotuloCurto} princ.`, espessura: 2.5 },
        { ...s, id: `${n}-c`, rotulo: `${s.rotulo} · crescimento`, rotuloCurto: `${s.rotuloCurto} cresc.`, espessura: 1 }];
    }),
  });
  G.linhas(document.getElementById('g-cresc-dif'), {
    vazio: SEM_SELECAO, ...cfgEixoX(), yFmt: (v) => `${fmtDif(v)} p.p.`, refs: [{ y: 0, rotulo: 'iguais' }],
    series: nums.map((n) => serieCresc(n, (r, c, v) => ({ x: valorX(r), y: v - c.perc_projetado }))),
  });

  const top = nums.slice(0, 2);
  const corpoUf = cabecalhoTabela('#tabela-cresc-uf', [
    el('th', { texto: 'UF' }), el('th', { classe: 'num', texto: '% apurado' }),
    ...top.flatMap((n) => [thCandidato(n, ' princ.'), thCandidato(n, ' cresc.')]),
    el('th', { classe: 'num', texto: 'Diferença' }),
  ]);
  const ufs = [...(a.ufs || [])].sort((x, y) => y.restantes_esperados - x.restantes_esperados);
  for (const u of ufs) {
    const c = cresc.ufs[u.uf];
    const n0 = top[0];
    const dif = c && n0 ? c[n0] - (u.proj_pct[n0] || 0) : null;
    corpoUf.appendChild(el('tr', {}, [
      el('td', { texto: u.uf }), el('td', { classe: 'num', texto: pct(pctApurado(u), 1) }),
      ...top.flatMap((n) => [el('td', { classe: 'num', texto: pct(u.proj_pct[n] || 0, 1) }),
        el('td', { classe: 'num', texto: c ? pct(c[n], 1) : '—' })]),
      el('td', { classe: 'num', texto: dif === null ? '—' : `${fmtDif(dif)} p.p.`, title: n0 ? `${nome(n0)}: crescimento − principal` : '' }),
    ]));
  }

  const corpoEst = cabecalhoTabela('#tabela-cresc-estratos', [
    el('th', { texto: 'Estrato' }), el('th', { classe: 'num', texto: 'Eleitores a computar' }),
    ...top.flatMap((n) => [thCandidato(n, ' apur.'), thCandidato(n, ' cresc.')]),
    el('th', { texto: 'Base' }),
  ]);
  const nomes = Object.fromEntries((a.estratos || []).map((e) => [e.id, e.nome]));
  const linhasEst = Object.entries(cresc.estratos).sort((x, y) => y[1].eleitores_faltantes - x[1].eleitores_faltantes);
  for (const [id, e] of linhasEst) {
    corpoEst.appendChild(el('tr', {}, [
      el('td', { texto: nomes[id] || id }), el('td', { classe: 'num', texto: compacto(e.eleitores_faltantes) }),
      ...top.flatMap((n) => [el('td', { classe: 'num', texto: pct(e.pct_apurado[n], 1) }), el('td', { classe: 'num', texto: pct(e.pct[n], 1) })]),
      el('td', { texto: e.base === 'recente' ? `recente (${fmtInt.format(e.secoes_janela)} seções)` : 'acumulada',
        title: 'Recente: seções apuradas nos últimos 15% do estrato · acumulada: desde o início' }),
    ]));
  }
}

// ------------------------------------------------------------------ modelos lado a lado

const MODELOS = [
  { id: 'parcial', rotulo: 'Parcial apurada', nota: 'Só o que já foi contado', token: '--neutro' },
  { id: 'mc-normal', rotulo: 'Monte Carlo normal', nota: 'Cidades grandes e interior inteiro', token: '--s2' },
  { id: 'mc-sub', rotulo: 'Monte Carlo subestratificado', nota: 'Seu modelo: regiões separadas em MG', token: '--s1', principal: true },
  { id: 'cresc', rotulo: 'Razão de crescimento', nota: '', token: '--s3' },
];
const STATUS_TEXTO = {
  MATEMATICAMENTE_ELEITO: 'Matematicamente eleito',
  VITORIA_PROJETADA: 'Vitória projetada',
  SEGUNDO_TURNO_PROJETADO: 'Segundo turno projetado',
};

/** Números do Monte Carlo de uma versão; sem subestratos as duas versões são a própria projeção principal. */
function resumoMonteCarlo(d, versao) {
  const sub = (d.analise || {}).subestratificacao;
  if (sub && sub.versoes && sub.versoes[versao]) {
    const v = sub.versoes[versao];
    return { por: v.nacional, status: v.status_call, vencedor: v.vencedor_projetado };
  }
  return {
    por: Object.fromEntries(d.candidatos.map((c) => [c.numero, { pct: c.perc_projetado, ic: [c.ic_inferior_95, c.ic_superior_95], prob_vitoria: c.prob_vitoria }])),
    status: d.status_call, vencedor: d.vencedor_projetado,
  };
}

function modeloCrescimento(a, versao) {
  const m = a.modelos && a.modelos.crescimento && a.modelos.crescimento[versao];
  return m || (a.crescimento ? { nacional: a.crescimento.nacional, votos_nacionais: a.crescimento.votos_nacionais, ufs: a.crescimento.ufs, ufs_detalhe: {} } : null);
}
function crescimentoUfs(a, versao) {
  const m = modeloCrescimento(a, versao);
  return m ? m.ufs : {};
}

function cartaoModelo(m, nums, linhas, rodape, nota) {
  const raiz = el('article', { classe: `cartao-modelo${m.principal ? ' principal' : ''}` }, [
    el('h4', { texto: m.rotulo }), el('span', { classe: 'nota', texto: nota || m.nota, title: nota || m.nota }),
  ]);
  raiz.style.setProperty('--cor-modelo', G.token(m.token));
  for (const n of nums) {
    const l = linhas[n];
    raiz.appendChild(el('div', { classe: 'linha-cand' }, [
      el('span', { classe: 'chave-tab', estilo: { background: cor(n) } }),
      el('span', { texto: nomeCurto(n) }),
      el('span', { classe: 'valor', texto: l ? pct(l.valor, 1) : '—' }),
      l && l.detalhe ? el('span', { classe: 'detalhe', texto: l.detalhe }) : null,
    ].filter(Boolean)));
  }
  if (rodape) raiz.appendChild(el('div', { classe: 'rodape-cartao', texto: rodape }));
  return raiz;
}

function renderModelos(d) {
  const a = d.analise || {};
  const nums = candidatosDosGraficos().slice(0, 4);
  const ver = state.versaoCrescimento;
  for (const b of document.querySelectorAll('[data-cresc-versao]')) {
    const ativo = b.dataset.crescVersao === ver;
    b.classList.toggle('ativo', ativo);
    b.setAttribute('aria-pressed', String(ativo));
  }
  const caixa = document.getElementById('cartoes-modelos');
  caixa.textContent = '';
  if (!nums.length) {
    G.vazio(document.getElementById('g-modelos'), SEM_SELECAO);
    caixa.appendChild(el('p', { classe: 'nota', texto: SEM_SELECAO }));
    return;
  }
  const textoStatus = (r) => {
    const t = STATUS_TEXTO[r.status] || 'Em aberto';
    return r.vencedor ? `${t}: ${nome(r.vencedor)}` : t;
  };
  const mcSub = resumoMonteCarlo(d, 'subestratificado');
  const refSub = (n) => (mcSub.por[n] || {}).pct;
  const dif = (n, v) => (refSub(n) === undefined || v === undefined ? '' : `${fmtDif(v - refSub(n))} p.p. vs seu modelo`);
  const detalheMC = (v) => `IC ${pct(v.ic[0], 1)} a ${pct(v.ic[1], 1)} · chance de vencer ${prob(v.prob_vitoria)}`;

  const porId = {};
  porId.parcial = Object.fromEntries(d.candidatos.map((c) => [c.numero, { valor: c.perc_apurado, detalhe: `${compacto(c.votos_apurados)} votos` }]));
  for (const [id, versao] of [['mc-normal', 'normal'], ['mc-sub', 'subestratificado']]) {
    porId[id] = Object.fromEntries(Object.entries(resumoMonteCarlo(d, versao).por).map(([n, v]) => [n, { valor: v.pct, detalhe: detalheMC(v) }]));
  }
  const cresc = modeloCrescimento(a, ver);
  porId.cresc = cresc ? Object.fromEntries(Object.entries(cresc.nacional).map(([n, v]) => [n, {
    valor: v, detalhe: cresc.votos_nacionais ? `${compacto(cresc.votos_nacionais[n])} votos projetados` : '',
  }])) : {};

  const n0 = nums[0];
  const unir = (...partes) => partes.filter(Boolean).join(' · ');
  const rodapes = {
    parcial: `Faltam ${pct(100 - d.perc_secoes_apuradas, 1)} das seções`,
    'mc-normal': unir(textoStatus(resumoMonteCarlo(d, 'normal')), dif(n0, (porId['mc-normal'][n0] || {}).valor)),
    'mc-sub': textoStatus(mcSub),
    cresc: cresc ? unir(dif(n0, porId.cresc[n0] && porId.cresc[n0].valor), 'leitura extra, fora da chamada') : 'Aguardando votos apurados',
  };
  for (const m of MODELOS) {
    const nota = m.id === 'cresc' ? `Estratificação ${ver}` : (m.id === 'parcial' ? m.nota : null);
    caixa.appendChild(cartaoModelo(m, nums, porId[m.id], rodapes[m.id], nota));
  }

  // Evolução do primeiro candidato selecionado nos quatro modelos
  document.getElementById('modelos-hist-titulo').textContent = `${nome(n0)}: modelos ao longo da apuração`;
  const linha = (m, espessura, fn) => {
    const s = serieHistorico(n0, (r, c) => {
      const y = fn(r, c);
      return y === undefined || y === null ? null : { x: valorX(r), y };
    });
    return { ...s, id: `${n0}-${m.id}`, rotulo: `${nome(n0)} · ${m.rotulo}`, rotuloCurto: m.rotulo, cor: G.token(m.token), espessura };
  };
  const resumoVersao = (r, v) => r.analise && r.analise.versoes_resumo && r.analise.versoes_resumo[v];
  G.linhas(document.getElementById('g-modelos'), {
    vazio: SEM_SELECAO, ...cfgEixoX(), yFmt: fmtPctEixo, refs: [{ y: 50, rotulo: '50%' }],
    series: [
      linha(MODELOS[0], 1, (r, c) => c.perc_apurado),
      linha(MODELOS[1], 1.5, (r, c) => { const v = resumoVersao(r, 'normal'); return v ? v.nacional[n0] : c.perc_projetado; }),
      linha(MODELOS[2], 3, (r, c) => { const v = resumoVersao(r, 'subestratificado'); return v ? v.nacional[n0] : c.perc_projetado; }),
      linha(MODELOS[3], 1.5, (r) => {
        const an = r.analise || {};
        const v = an.crescimento_versoes && an.crescimento_versoes[ver];
        return v ? v[n0] : (an.crescimento_nacional ? an.crescimento_nacional[n0] : null);
      }),
    ],
  });

  // Estados pela razão de crescimento, ao lado da projeção principal
  const top = nums.slice(0, 2);
  const crUf = cresc ? cresc.ufs : {};
  const detUf = (cresc && cresc.ufs_detalhe) || {};
  const corpo = cabecalhoTabela('#tabela-modelos-uf', [
    el('th', { texto: 'UF' }), el('th', { classe: 'num', texto: '% apurado' }),
    ...top.flatMap((n) => [thCandidato(n, ' MC'), thCandidato(n, ' cresc.')]),
    el('th', { classe: 'num', texto: 'Diferença' }), el('th', { classe: 'num', texto: 'Faltam' }), el('th', { classe: 'num', texto: 'Recente', title: 'Estratos da UF com razão da janela recente / total de estratos' }),
  ]);
  const ufs = [...(a.ufs || [])].sort((x, y) => y.restantes_esperados - x.restantes_esperados);
  for (const u of ufs) {
    const c = crUf[u.uf];
    const det = detUf[u.uf];
    const difUf = c ? c[n0] - (u.proj_pct[n0] || 0) : null;
    const total = det ? det.estratos_recentes + det.estratos_acumulados : 0;
    corpo.appendChild(el('tr', {}, [
      el('td', { texto: u.uf }), el('td', { classe: 'num', texto: pct(pctApurado(u), 1) }),
      ...top.flatMap((n) => [el('td', { classe: 'num', texto: pct(u.proj_pct[n] || 0, 1) }),
        el('td', { classe: 'num', texto: c ? pct(c[n], 1) : '—' })]),
      el('td', { classe: 'num', texto: difUf === null ? '—' : `${fmtDif(difUf)} p.p.`, title: `${nome(n0)}: crescimento − Monte Carlo` }),
      el('td', { classe: 'num', texto: det ? compacto(det.eleitores_faltantes) : '—' }),
      el('td', { classe: 'num', texto: total ? `${det.estratos_recentes}/${total}` : '—',
        title: 'Estratos da UF com razão da janela recente (últimos 15% das seções); os demais usam a razão acumulada' }),
    ]));
  }
  document.getElementById('modelos-explicacao').textContent =
    'MC = projeção principal do Monte Carlo (versão definida na aba Subestratos). Crescimento = votos ganhos por eleitor nas seções ' +
    'apuradas recentemente × eleitores que faltam, em cada estrato da estratificação escolhida. É uma leitura extra: não entra no ' +
    'Monte Carlo, no intervalo nem na chamada. Sem subestratos na apuração, as duas estratificações coincidem.';
}

const RENDER_ABA = {
  geral: renderGeral, consolidado: renderConsolidado, mapa: renderMapa, simulacao: renderCenarios,
  apuracao: renderApuracao, estratos: renderEstratos, ufs: renderUfs, exterior: renderExterior,
  subestratos: renderSubestratos, crescimento: renderCrescimento, modelos: renderModelos,
};

// --------------------------------------------------------------- orquestração

function emEspera(d) { return Boolean(d && d.analise && d.analise.aguardando); }

function renderAguardando(d) {
  document.getElementById('chamada').className = 'chamada';
  document.getElementById('chamada-titulo').textContent = 'Aguardando o início da apuração';
  document.getElementById('chamada-sub').textContent =
    `Arquivos do TSE disponíveis: 0 de ${fmtInt.format(d.total_secoes)} seções apuradas · ` +
    `${fmtInt.format(d.total_eleitores)} eleitores. A projeção começa com os primeiros votos.`;
  const info = document.getElementById('ultima-atualizacao');
  info.classList.remove('aviso-coleta');
  info.textContent = `Última verificação às ${(d.timestamp || '').slice(11)}`;
}

function renderEsperaCompleta(d) {
  renderAguardando(d);
  G.anel(document.getElementById('g-anel'), 0);
  document.getElementById('anel-detalhe').textContent = `0 de ${fmtInt.format(d.total_secoes)}`;
  const caixa = document.getElementById('kpis');
  caixa.textContent = '';
  caixa.append(
    kpi('Eleitorado', compacto(d.total_eleitores), `${fmtInt.format(d.total_eleitores)} eleitores aptos`),
    kpi('Seções', fmtInt.format(d.total_secoes), 'a apurar'),
    kpi('Candidatos', fmtInt.format(d.candidatos.length), 'nos arquivos do TSE'),
  );
  renderListaCandidatos(d, true);
  for (const id of GRAFICOS) G.vazio(document.getElementById(id), 'Aguardando os primeiros votos apurados');
}

function renderAbaAtual() {
  const d = state.atual;
  if (!d || !d.candidatos || !d.candidatos.length || emEspera(d)) return;
  RENDER_ABA[state.aba](d);
}

function renderTudo() {
  const d = state.atual;
  if (!d || !d.candidatos || !d.candidatos.length) return;
  for (const c of d.candidatos) state.candidatos[c.numero] = { nome: c.nome, partido: c.partido };
  if (emEspera(d)) {
    renderEsperaCompleta(d);
    return;
  }
  atribuirCores(d.candidatos);
  if (!state.marcados) {
    state.marcados = new Set(ordemCandidatos().slice(0, segundoTurno() ? 2 : PRINCIPAIS));
    salvarSelecao();
  }
  for (const n of state.marcados) garantirCor(n);
  renderChamada(d);
  renderStatus(d);
  renderListaCandidatos(d, false);
  renderConfronto(d);
  document.getElementById('controle-eixo').hidden = !['geral', 'apuracao'].includes(state.aba);
  renderAbaAtual();
  salvarSelecao();
  // Notas truncadas no cabeçalho dos blocos: texto completo ao passar o mouse
  for (const n of document.querySelectorAll('.bloco > header .nota')) n.title = n.textContent;
}

function chave(r) { return `${r.ciclo_id}|${r.timestamp}`; }

function adicionarAoHistorico(r) {
  if (!r.total_validos_apurados || emEspera(r)) return;
  const k = chave(r);
  if (state.historico.some((h) => chave(h) === k)) return;
  state.historico.push(r);
}

async function carregarInicial() {
  const sessao = await fetch('/api/v1/sessao').then((r) => r.json()).catch(() => ({ ativa: true }));
  if (!sessao.ativa) { location.replace('/inicio'); return; }
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

// ------------------------------------------------------------------ controles

function aplicarTema(tema) {
  if (tema) document.documentElement.setAttribute('data-theme', tema);
  else document.documentElement.removeAttribute('data-theme');
}

function selecionarAba(aba, foco) {
  state.aba = aba;
  armazenar('spetr-aba', aba);
  for (const t of document.querySelectorAll('[role="tab"]')) {
    const ativa = t.dataset.aba === aba;
    t.setAttribute('aria-selected', String(ativa));
    t.tabIndex = ativa ? 0 : -1;
    if (ativa && foco) t.focus();
  }
  for (const p of document.querySelectorAll('.aba')) p.hidden = p.dataset.aba !== aba;
  document.getElementById('controle-eixo').hidden = !['geral', 'apuracao'].includes(aba);
  // Desenha depois que a aba fica visível (o ECharts precisa do tamanho real do bloco)
  requestAnimationFrame(renderAbaAtual);
}

function iniciarControles() {
  aplicarTema(recuperar('spetr-tema', null));
  document.getElementById('botao-tema').addEventListener('click', () => {
    const escuro = getComputedStyle(document.documentElement).colorScheme.includes('dark');
    const novo = escuro ? 'light' : 'dark';
    aplicarTema(novo);
    armazenar('spetr-tema', novo);
    renderTudo();
  });

  const abas = [...document.querySelectorAll('[role="tab"]')];
  for (const t of abas) {
    t.addEventListener('click', () => selecionarAba(t.dataset.aba));
    t.addEventListener('keydown', (e) => {
      const i = abas.indexOf(t);
      if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault();
        const prox = abas[(i + (e.key === 'ArrowRight' ? 1 : abas.length - 1)) % abas.length];
        selecionarAba(prox.dataset.aba, true);
      }
    });
  }

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
      renderAbaAtual();
    });
  }

  state.modoMapa = recuperar('spetr-mapa', 'lider');
  for (const b of document.querySelectorAll('[data-mapa]')) {
    b.classList.toggle('ativo', b.dataset.mapa === state.modoMapa);
    b.setAttribute('aria-pressed', String(b.dataset.mapa === state.modoMapa));
    b.addEventListener('click', () => {
      state.modoMapa = b.dataset.mapa;
      armazenar('spetr-mapa', state.modoMapa);
      for (const o of document.querySelectorAll('[data-mapa]')) {
        o.classList.toggle('ativo', o === b);
        o.setAttribute('aria-pressed', String(o === b));
      }
      if (state.atual) renderMapa(state.atual);
    });
  }

  const versaoSalva = recuperar('spetr-cresc-versao', 'subestratificado');
  state.versaoCrescimento = versaoSalva === 'normal' ? 'normal' : 'subestratificado';
  for (const b of document.querySelectorAll('[data-cresc-versao]')) {
    b.addEventListener('click', () => {
      state.versaoCrescimento = b.dataset.crescVersao;
      armazenar('spetr-cresc-versao', state.versaoCrescimento);
      renderAbaAtual();
    });
  }

  state.modoCorrida = recuperar('spetr-corrida', 'votos');
  for (const b of document.querySelectorAll('[data-corrida]')) {
    b.classList.toggle('ativo', b.dataset.corrida === state.modoCorrida);
    b.setAttribute('aria-pressed', String(b.dataset.corrida === state.modoCorrida));
    b.addEventListener('click', () => {
      state.modoCorrida = b.dataset.corrida;
      armazenar('spetr-corrida', state.modoCorrida);
      for (const o of document.querySelectorAll('[data-corrida]')) {
        o.classList.toggle('ativo', o === b);
        o.setAttribute('aria-pressed', String(o === b));
      }
      if (state.atual && !emEspera(state.atual)) renderGeral(state.atual);
    });
  }

  for (const b of document.querySelectorAll('[data-versao]')) {
    b.addEventListener('click', () => definirVersao(b.dataset.versao));
  }

  for (const b of document.querySelectorAll('[data-selecao]')) {
    b.addEventListener('click', () => definirSelecao(b.dataset.selecao));
  }

  let temporizador = null;
  window.addEventListener('resize', () => {
    clearTimeout(temporizador);
    temporizador = setTimeout(() => { renderAbaAtual(); if (state.atual) G.anel(document.getElementById('g-anel'), state.atual.perc_secoes_apuradas || 0); }, 150);
  });

  const abaSalva = recuperar('spetr-aba', 'geral');
  selecionarAba(RENDER_ABA[abaSalva] ? abaSalva : 'geral');
}

iniciarControles();

// ?estatico=1 desenha o estado atual sem abrir o stream (impressão, captura de tela)
const params = new URLSearchParams(location.search);
const estatico = params.has('estatico');
const temaUrl = params.get('tema');
if (temaUrl === 'escuro' || temaUrl === 'claro') aplicarTema(temaUrl === 'escuro' ? 'dark' : 'light');
const abaUrl = params.get('aba');
if (abaUrl && RENDER_ABA[abaUrl]) selecionarAba(abaUrl);
carregarInicial().then(() => {
  if (estatico) document.getElementById('conexao-texto').textContent = 'Modo estático';
  else conectarSSE();
});
