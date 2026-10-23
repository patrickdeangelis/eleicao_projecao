/**
 * SPETR — Tela inicial: escolhe entre coleta real (padrão) e replay de uma apuração real.
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
  botao.textContent = { real: 'Iniciar coleta real', replay: 'Iniciar replay' }[modo];
  if (modo === 'replay' && !form.fonte.options.length) botao.disabled = true;
  else botao.disabled = false;
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
  const replays = Object.entries(o.replays || {});
  for (const [k, v] of replays) opcao(form.fonte, k, v);
  if (!replays.length) {
    document.getElementById('nota-replay').innerHTML =
      'Nenhum replay preparado. Rode <code>python scripts/preparar_replay.py --ano 2026 --turno 1</code> e recarregue esta tela.';
  }
  for (const [k, v] of Object.entries(o.velocidades_replay || {})) {
    opcao(form.velocidade_replay, k, `${{ lenta: 'Lenta', normal: 'Normal', rapida: 'Rápida' }[k] || k} (${v})`);
  }
  form.velocidade_replay.value = 'normal';

  if (s.ativa) {
    const aviso = document.getElementById('sessao-atual');
    aviso.hidden = false;
    aviso.textContent = `Sessão em andamento: ${{ replay: 'replay de eleição real' }[s.modo] || 'coleta real'}` +
      ` desde ${s.iniciada_em}. Iniciar outra encerra a atual.`;
    document.getElementById('voltar-painel').hidden = false;
  }
}

form.addEventListener('change', (e) => {
  if (e.target.name === 'modo') atualizarModo();
  if (e.target.name === 'pronta') aplicarPronta(e.target.value);
  if (['ano', 'turno', 'eleicao'].includes(e.target.name)) sincronizarPronta();
});

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
