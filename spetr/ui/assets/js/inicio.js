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
  botao.textContent = modo === 'real' ? 'Iniciar coleta real' : 'Iniciar simulação';
}

async function carregar() {
  const s = await fetch('/api/v1/sessao').then((r) => r.json());
  const o = s.opcoes || {};
  const p = o.padroes_reais || {};
  form.ano.value = p.ano || '2026';
  form.turno.value = String(p.turno || 1);
  form.eleicao.value = p.eleicao || '';
  form.tse_url.value = p.tse_url || 'https://resultados.tse.jus.br';
  form.ambiente.value = p.ambiente || 'oficial';
  for (const chave of o.jws || []) opcao(form.jws, chave, `Chave ${chave} do TSE`);
  form.jws.value = p.jws || '';
  for (const [k, v] of Object.entries(o.cenarios || {})) opcao(form.cenario, k, v);
  const nomesVel = { lenta: 'Lenta', normal: 'Normal', rapida: 'Rápida' };
  for (const [k, v] of Object.entries(o.velocidades || {})) opcao(form.velocidade, k, `${nomesVel[k] || k} (${v})`);
  form.velocidade.value = 'normal';

  if (s.ativa) {
    const aviso = document.getElementById('sessao-atual');
    aviso.hidden = false;
    aviso.textContent = `Sessão em andamento: ${s.modo === 'simulado' ? 'simulação local' : 'coleta real'}` +
      ` desde ${s.iniciada_em}. Iniciar outra encerra a atual.`;
    document.getElementById('voltar-painel').hidden = false;
  }
}

form.addEventListener('change', (e) => { if (e.target.name === 'modo') atualizarModo(); });

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
  const opcoes = modo === 'real'
    ? {
      ano: form.ano.value.trim(), turno: Number(form.turno.value), eleicao: form.eleicao.value.trim(),
      tse_url: form.tse_url.value.trim(), ambiente: form.ambiente.value.trim(), jws: form.jws.value,
    }
    : { cenario: form.cenario.value, velocidade: form.velocidade.value, inicio: Number(form.inicio.value || 0) };
  botao.disabled = true;
  botao.textContent = modo === 'real' ? 'Iniciando coleta…' : 'Abrindo simulador…';
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
