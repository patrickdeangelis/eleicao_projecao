/**
 * SPETR — Tela inicial: escolhe entre coleta real (padrão) e simulação local.
 */
const form = document.getElementById('form-inicio');
const erro = document.getElementById('erro');
const botao = document.getElementById('botao-iniciar');

function tema() {
  try {
    const t = JSON.parse(localStorage.getItem('spetr-tema') || 'null');
    if (t) document.documentElement.setAttribute('data-theme', t);
  } catch (e) { /* armazenamento indisponível */ }
  document.getElementById('botao-tema').addEventListener('click', () => {
    const escuro = getComputedStyle(document.documentElement).colorScheme.includes('dark');
    const novo = escuro ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', novo);
    try { localStorage.setItem('spetr-tema', JSON.stringify(novo)); } catch (e) { /* ignora */ }
  });
}

function opcao(select, valor, texto) {
  const o = document.createElement('option');
  o.value = valor;
  o.textContent = texto;
  select.appendChild(o);
}

function preencherEleicoesProntas() {
  form.pronta.textContent = '';
  opcao(form.pronta, '', 'Personalizada (preencha abaixo)');
  const grupos = {};
  for (const e of eleicoesProntas) {
    if (!grupos[e.ano]) {
      grupos[e.ano] = document.createElement('optgroup');
      grupos[e.ano].label = e.ano;
      form.pronta.appendChild(grupos[e.ano]);
    }
    opcao(grupos[e.ano], e.id, e.rotulo.replace(`${e.ano} · `, ''));
  }
}

function modoSelecionado() {
  return form.querySelector('input[name="modo"]:checked').value;
}

function atualizarModo() {
  const modo = modoSelecionado();
  for (const card of document.querySelectorAll('.opcao-modo')) {
    const ativo = card.dataset.modo === modo;
    card.classList.toggle('selecionada', ativo);
    for (const campo of card.querySelectorAll('.campos input, .campos select')) campo.disabled = !ativo;
    card.querySelector('details')?.toggleAttribute('inert', !ativo);
  }
  botao.textContent = { real: 'Iniciar coleta real', simulado: 'Iniciar simulação', replay: 'Iniciar replay' }[modo];
  if (modo === 'replay' && !form.fonte.options.length) botao.disabled = true;
  else botao.disabled = false;
}

// ------------------------------------------------ configuração da simulação
const config = { perfis: {}, regioes: {} };
const fmtNum = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
let temporizadorPrevia = null;

function el(tag, attrs = {}, filhos = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'texto') n.textContent = v;
    else if (k === 'classe') n.className = v;
    else n.setAttribute(k, v);
  }
  for (const f of [].concat(filhos)) if (f) n.appendChild(typeof f === 'string' ? document.createTextNode(f) : f);
  return n;
}

function sobrenome(nome) {
  const partes = nome.split(/\s+/);
  return partes[partes.length - 1];
}

/** Monta a tabela regiões × candidatos com os valores do cenário escolhido. */
function preencherConfig() {
  const perfil = config.perfis[form.cenario.value];
  if (!perfil) return;
  const cands = perfil.candidatos;
  const thead = document.querySelector('#tabela-config thead');
  const tbody = document.querySelector('#tabela-config tbody');
  thead.textContent = '';
  tbody.textContent = '';
  thead.appendChild(el('tr', {}, [
    el('th', { texto: 'Região' }),
    ...cands.map((c) => el('th', { classe: 'num', title: `${c.nm} (${c.n})${c.sub_judice ? ' · sub judice: votos anulados' : ''}`,
      texto: `${sobrenome(c.nm)}${c.sub_judice ? '*' : ''} %` })),
    el('th', { classe: 'num', texto: 'Soma' }),
    el('th', { classe: 'num vel', texto: 'Velocidade', title: '1 = ritmo médio · 2 = começa no dobro · 0,5 = começa na metade' }),
    el('th', { classe: 'num', texto: 'Viés de ordem',
      title: `Pontos a mais para ${cands[0].nm} nas primeiras urnas de cada cidade (negativo favorece ${cands[1].nm}); some até o fim da apuração` }),
  ]));
  for (const [reg, nomeReg] of Object.entries(config.regioes)) {
    const valores = perfil.ajustes.regioes[reg] || { percentuais: {}, velocidade: 1 };
    const tr = el('tr', { 'data-regiao': reg });
    tr.appendChild(el('td', { texto: nomeReg }));
    for (const c of cands) {
      const entrada = el('input', {
        type: 'number', min: '0', max: '100', step: '0.1', 'data-cand': c.n,
        'aria-label': `${nomeReg}: % de ${c.nm}`, value: String(valores.percentuais[c.n] ?? 0),
      });
      tr.appendChild(el('td', { classe: 'num' }, [entrada]));
    }
    const soma = el('td', { classe: 'num soma' });
    tr.appendChild(soma);
    tr.appendChild(el('td', { classe: 'num vel' }, [el('input', {
      type: 'number', min: '0.2', max: '5', step: '0.1', 'data-vel': '1',
      'aria-label': `${nomeReg}: razão de velocidade da apuração`, value: String(valores.velocidade ?? 1),
    })]));
    tr.appendChild(el('td', { classe: 'num' }, [el('input', {
      type: 'number', min: '-40', max: '40', step: '1', 'data-vies': '1',
      'aria-label': `${nomeReg}: viés de ordem em pontos`, value: String(valores.vies ?? 0),
    })]));
    tbody.appendChild(tr);
  }
  form.cidades_primeiro.checked = perfil.ajustes.cidades_primeiro !== false;
  atualizarSomas();
  agendarPrevia();
}

function atualizarSomas() {
  for (const tr of document.querySelectorAll('#tabela-config tbody tr')) {
    const soma = [...tr.querySelectorAll('input[data-cand]')].reduce((t, i) => t + (parseFloat(i.value) || 0), 0);
    const celula = tr.querySelector('.soma');
    celula.textContent = `${fmtNum.format(soma)}%`;
    const errada = Math.abs(soma - 100) > 0.5;
    celula.classList.toggle('erro', errada);
    if (errada) {
      const ajustar = el('button', { type: 'button', classe: 'botao-mini', texto: '= 100', title: 'Reescalar a linha para somar 100%' });
      ajustar.addEventListener('click', () => {
        const entradas = [...tr.querySelectorAll('input[data-cand]')];
        const total = entradas.reduce((t, i) => t + (parseFloat(i.value) || 0), 0);
        if (total > 0) for (const i of entradas) i.value = (Math.round((parseFloat(i.value) || 0) / total * 1000) / 10).toString();
        atualizarSomas();
        agendarPrevia();
      });
      celula.appendChild(ajustar);
    }
  }
}

function coletarAjustes() {
  if (!document.getElementById('personalizar').open) return null;
  const regioes = {};
  for (const tr of document.querySelectorAll('#tabela-config tbody tr')) {
    const percentuais = {};
    for (const i of tr.querySelectorAll('input[data-cand]')) percentuais[i.dataset.cand] = parseFloat(i.value) || 0;
    regioes[tr.dataset.regiao] = {
      percentuais,
      velocidade: parseFloat(tr.querySelector('input[data-vel]').value) || 1,
      vies: parseFloat(tr.querySelector('input[data-vies]').value) || 0,
    };
  }
  return { regioes, cidades_primeiro: form.cidades_primeiro.checked };
}

function agendarPrevia() {
  clearTimeout(temporizadorPrevia);
  temporizadorPrevia = setTimeout(atualizarPrevia, 300);
}

async function atualizarPrevia() {
  const caixa = document.getElementById('previa');
  if (!document.getElementById('personalizar').open) return;
  const perfil = config.perfis[form.cenario.value];
  const nomes = Object.fromEntries((perfil ? perfil.candidatos : []).map((c) => [c.n, c.nm]));
  try {
    const r = await fetch('/api/v1/simulador/previa', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cenario: form.cenario.value, ajustes: coletarAjustes() }),
    });
    const p = await r.json();
    caixa.textContent = '';
    if (!r.ok) { caixa.appendChild(el('span', { classe: 'erro', texto: p.detail || 'Configuração inválida' })); return; }
    const final = Object.entries(p.final).sort((a, b) => b[1] - a[1]);
    caixa.appendChild(el('div', {}, [
      'Resultado final esperado: ',
      el('strong', { texto: final.slice(0, 4).map(([n, v]) => `${nomes[n] || n} ${fmtNum.format(v)}%`).join(' · ') }),
    ]));
    const lista = el('ul');
    for (const marco of Object.values(p.ritmo)) {
      const lider = Object.entries(marco.parcial).sort((a, b) => b[1] - a[1])[0];
      const regs = Object.entries(marco.regioes).map(([reg, v]) => `${config.regioes[reg] || reg} ${fmtNum.format(v)}%`).join(' · ');
      lista.appendChild(el('li', {}, [
        el('strong', { texto: `País com ${fmtNum.format(marco.nacional)}% apurado` }),
        `: ${regs}. Na parcial, ${nomes[lider[0]] || lider[0]} tem ${fmtNum.format(lider[1])}%.`,
      ]));
    }
    caixa.appendChild(lista);
  } catch (e) {
    caixa.textContent = `Não foi possível calcular a prévia: ${e.message}`;
  }
}

// ------------------------------------------------ eleições prontas (coleta real)
let eleicoesProntas = [];

function aplicarPronta(id) {
  const e = eleicoesProntas.find((x) => x.id === id);
  if (!e) return;
  form.ano.value = e.ano;
  form.turno.value = String(e.turno);
  form.eleicao.value = e.eleicao;
}

/** Marca o atalho que corresponde aos campos (ou "Personalizada"). */
function sincronizarPronta() {
  const e = eleicoesProntas.find((x) => x.ano === form.ano.value.trim() && String(x.turno) === form.turno.value
    && x.eleicao === form.eleicao.value.trim());
  form.pronta.value = e ? e.id : '';
}

async function carregar() {
  const s = await fetch('/api/v1/sessao').then((r) => r.json());
  const o = s.opcoes || {};
  const p = o.padroes_reais || {};
  eleicoesProntas = o.eleicoes_prontas || [];
  preencherEleicoesProntas();
  const anos = [...new Set(eleicoesProntas.map((e) => String(e.ano)))].sort((a, b) => b.localeCompare(a));
  form.ano.textContent = '';
  for (const ano of anos) opcao(form.ano, ano, ano);
  const anoAtual = String(p.ano || '');
  form.ano.value = anos.includes(anoAtual) ? anoAtual : (anos[0] || '2022');
  form.turno.value = String(p.turno || 1);
  form.eleicao.value = p.eleicao || '';
  // Sem nada pedido na linha de comando, já começa no 1º atalho (o pleito em andamento)
  if (eleicoesProntas.length && (!anos.includes(anoAtual) || !p.eleicao)) aplicarPronta(eleicoesProntas[0].id);
  sincronizarPronta();
  form.tse_url.value = p.tse_url || 'https://resultados.tse.jus.br';
  form.ambiente.value = p.ambiente || 'oficial';
  for (const chave of o.jws || []) opcao(form.jws, chave, chave === 'oficial' ? 'Sim (chave oficial)' : `Sim (chave de ${chave})`);
  form.jws.value = p.jws || '';
  for (const [k, v] of Object.entries(o.cenarios || {})) opcao(form.cenario, k, v);
  const replays = Object.entries(o.replays || {});
  for (const [k, v] of replays) opcao(form.fonte, k, v);
  if (!replays.length) {
    document.getElementById('nota-replay').innerHTML =
      'Nenhum replay preparado. Rode <code>python scripts/preparar_replay.py --ano 2022 --turno 2</code> e recarregue esta tela.';
  }
  for (const [k, v] of Object.entries(o.velocidades_replay || {})) {
    opcao(form.velocidade_replay, k, `${{ lenta: 'Lenta', normal: 'Normal', rapida: 'Rápida' }[k] || k} (${v})`);
  }
  form.velocidade_replay.value = 'normal';
  config.perfis = o.perfis || {};
  config.regioes = o.regioes || {};
  preencherConfig();
  const nomesVel = { lenta: 'Lenta', normal: 'Normal', rapida: 'Rápida' };
  for (const [k, v] of Object.entries(o.velocidades || {})) opcao(form.velocidade, k, `${nomesVel[k] || k} (${v})`);
  form.velocidade.value = 'normal';

  if (s.ativa) {
    const aviso = document.getElementById('sessao-atual');
    aviso.hidden = false;
    aviso.textContent = `Sessão em andamento: ${{ simulado: 'simulação local', replay: 'replay de eleição real' }[s.modo] || 'coleta real'}` +
      ` desde ${s.iniciada_em}. Iniciar outra encerra a atual.`;
    document.getElementById('voltar-painel').hidden = false;
  }
}

form.addEventListener('change', (e) => {
  if (e.target.name === 'modo') atualizarModo();
  if (e.target.name === 'pronta') aplicarPronta(e.target.value);
  if (['ano', 'turno', 'eleicao'].includes(e.target.name)) sincronizarPronta();
  if (e.target.name === 'cenario') preencherConfig();
  if (e.target.name === 'cidades_primeiro') agendarPrevia();
});
document.getElementById('tabela-config').addEventListener('input', () => { atualizarSomas(); agendarPrevia(); });
document.getElementById('personalizar').addEventListener('toggle', agendarPrevia);

// Clicar em qualquer parte do cartão (fora de um campo ativo) seleciona aquele modo
for (const card of document.querySelectorAll('.opcao-modo')) {
  card.addEventListener('click', (e) => {
    const campoAtivo = e.target.closest('input, select, summary, button, a') && !e.target.disabled;
    const radio = card.querySelector('input[type="radio"]');
    if (!radio.checked && !campoAtivo) {
      radio.checked = true;
      atualizarModo();
    }
  });
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  erro.textContent = '';
  const modo = modoSelecionado();
  const opcoes = {
    real: () => ({
      ano: form.ano.value.trim(), turno: Number(form.turno.value), eleicao: form.eleicao.value.trim(),
      tse_url: form.tse_url.value.trim(), ambiente: form.ambiente.value.trim(), jws: form.jws.value,
    }),
    simulado: () => ({ cenario: form.cenario.value, velocidade: form.velocidade.value, inicio: Number(form.inicio.value || 0), ajustes: coletarAjustes() }),
    replay: () => ({ fonte: form.fonte.value, velocidade: form.velocidade_replay.value }),
  }[modo]();
  botao.disabled = true;
  botao.textContent = modo === 'real' ? 'Iniciando coleta…' : 'Abrindo servidor local…';
  try {
    const r = await fetch('/api/v1/sessao/iniciar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ modo, opcoes }),
    });
    const corpo = await r.json();
    if (!r.ok) throw new Error(corpo.detail || `Erro ${r.status}`);
    location.href = '/';
  } catch (err) {
    erro.textContent = err.message;
    botao.disabled = false;
    atualizarModo();
  }
});

tema();
atualizarModo();
carregar().catch((e) => { erro.textContent = `Não foi possível falar com o SPETR: ${e.message}`; });
