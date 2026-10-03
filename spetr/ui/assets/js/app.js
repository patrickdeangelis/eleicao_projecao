/**
 * SPETR Desktop Dashboard - Frontend Client
 * Consome o stream SSE e atualiza a interface a 60 FPS.
 */

const state = {
  conectado: false,
  historicoProjecoes: [],
  ultimoDado: null
};

const numberFormatter = new Intl.NumberFormat('pt-BR');
const percentFormatter = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

function formatarVotos(num) {
  return numberFormatter.format(Math.round(num));
}

function formatarPct(num) {
  return percentFormatter.format(num) + '%';
}

function inicializarSSE() {
  const statusDot = document.getElementById('status-dot');
  const statusText = document.getElementById('status-text');

  console.log("Conectando ao stream SSE local...");
  const evtSource = new EventSource('/api/v1/projecao/stream');

  evtSource.onopen = () => {
    state.conectado = true;
    statusDot.style.backgroundColor = 'var(--accent-green)';
    statusDot.style.boxShadow = '0 0 10px var(--accent-green)';
    statusText.innerText = 'CONECTADO // FLUXO AO VIVO';
  };

  evtSource.addEventListener('projecao_update', (event) => {
    try {
      const data = JSON.parse(event.data);
      state.ultimoDado = data;
      state.historicoProjecoes.push(data);
      if (state.historicoProjecoes.length > 50) {
        state.historicoProjecoes.shift();
      }
      atualizarInterface(data);
      desenharGraficoEvolucao();
      desenharFaixaIncerteza(data);
    } catch (err) {
      console.error("Erro ao processar dados da projeção:", err);
    }
  });

  evtSource.onerror = (err) => {
    state.conectado = false;
    statusDot.style.backgroundColor = 'var(--accent-red)';
    statusDot.style.boxShadow = '0 0 10px var(--accent-red)';
    statusText.innerText = 'RECONECTANDO AO COLETOR...';
  };
}

function atualizarInterface(data) {
  // 1. Barra de Apuração
  const barFill = document.getElementById('secoes-bar');
  const pctApuradoText = document.getElementById('pct-secoes-texto');
  const secoesDetalheText = document.getElementById('secoes-detalhes');

  const pct = data.perc_secoes_apuradas || 0;
  barFill.style.width = `${pct}%`;
  pctApuradoText.innerText = formatarPct(pct);
  secoesDetalheText.innerText = `${formatarVotos(data.secoes_apuradas)} de ${formatarVotos(data.total_secoes)} seções apuradas`;

  // 2. Banner de Chamada (Call Desk)
  const callBanner = document.getElementById('call-banner');
  const callTitle = document.getElementById('call-title');
  const callSubtitle = document.getElementById('call-subtitle');

  callBanner.className = 'call-banner';
  if (data.status_call === 'MATEMATICAMENTE_ELEITO') {
    callBanner.classList.add('eleito');
    callTitle.innerHTML = `🏆 MATEMATICAMENTE ELEITO: ${data.vencedor_projetado || 'LÍDER'}`;
    callSubtitle.innerText = 'Não há mais votos suficientes em disputa para alterar o resultado matemático.';
  } else if (data.status_call === 'VITORIA_PROJETADA') {
    callBanner.classList.add('vitoria');
    callTitle.innerHTML = `⚡ PROJEÇÃO SPETR: VITÓRIA PROJETADA (${data.vencedor_projetado || 'LÍDER'})`;
    callSubtitle.innerText = `Incerteza estatística superada (Probabilidade > 99.5% e IC 95% acima do limiar).`;
  } else {
    callTitle.innerHTML = `⏳ APURAÇÃO EM ANDAMENTO // DISPUTA EM ABERTO`;
    callSubtitle.innerText = `Margem projetada do líder: +${formatarPct(data.lider_margem)}. Aguardando mais seções.`;
  }

  // 3. Grid de Candidatos
  const candContainer = document.getElementById('candidates-container');
  candContainer.innerHTML = '';

  data.candidatos.forEach((cand, idx) => {
    const isLider = idx === 0;
    const card = document.createElement('div');
    card.className = `cand-card ${isLider ? 'leading' : ''}`;
    
    // Cor do candidato
    const cor = cand.cor_hex || (idx === 0 ? '#38BDF8' : '#F43F5E');

    card.innerHTML = `
      <div class="cand-header">
        <div>
          <div class="cand-name" style="color: ${cor}">${cand.nome}</div>
          <span class="cand-party">${cand.partido} &bull; Nº ${cand.numero}</span>
        </div>
        ${isLider ? '<span style="font-size:0.75rem; background:#1E3A8A; color:#93C5FD; padding:0.25rem 0.6rem; border-radius:999px; font-weight:700;">PROJEÇÃO LÍDER</span>' : ''}
      </div>

      <div class="cand-numbers">
        <div>
          <div class="cand-proj-pct" style="color: ${cor}">${formatarPct(cand.perc_projetado)}</div>
          <div class="cand-proj-label">PROJEÇÃO FINAL ESTIMADA</div>
        </div>
      </div>

      <div class="cand-apurado-row">
        <span>Apurado na urna: <strong>${formatarPct(cand.perc_apurado)}</strong></span>
        <span>${formatarVotos(cand.votos_apurados)} votos válidos</span>
      </div>

      <div class="cand-metrics-grid">
        <div class="metric-pill">
          <div class="metric-label">Intervalo Confiança 95%</div>
          <div class="metric-val">[${cand.ic_inferior_95}% - ${cand.ic_superior_95}%]</div>
        </div>
        <div class="metric-pill">
          <div class="metric-label">Probabilidade de Vitória</div>
          <div class="metric-val" style="color:${cand.prob_vitoria > 0.9 ? 'var(--accent-green)' : 'var(--text-main)'}">
            ${formatarPct(cand.prob_vitoria * 100)}
          </div>
        </div>
        <div class="metric-pill">
          <div class="metric-label">Votos Finais Projetados</div>
          <div class="metric-val">${formatarVotos(cand.media_projetada)}</div>
        </div>
        <div class="metric-pill">
          <div class="metric-label">Status Matemático</div>
          <div class="metric-val">${cand.prob_vitoria >= 0.995 ? 'Favorito Seguro' : 'Em Disputa'}</div>
        </div>
      </div>
    `;
    candContainer.appendChild(card);
  });

  // 4. Rodapé
  document.getElementById('footer-ts').innerText = `Última sincronização TSE: ${data.timestamp}`;
  document.getElementById('footer-tempo-mc').innerText = `Simulação de Monte Carlo (10.000 iterações): ${data.tempo_computacao_ms} ms`;
}

function desenharFaixaIncerteza(data) {
  const canvas = document.getElementById('ciCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.parentElement.clientWidth - 48;
  const h = canvas.height = 160;

  ctx.clearRect(0, 0, w, h);

  if (!data || !data.candidatos || data.candidatos.length < 2) return;

  // Escala horizontal de 40% a 60%
  const minP = 40.0;
  const maxP = 60.0;
  const toX = (p) => ((p - minP) / (maxP - minP)) * w;

  // Linha de referência 50%
  const x50 = toX(50.0);
  ctx.strokeStyle = '#EAB308';
  ctx.lineWidth = 1.5;
  ctx.setLineDash([4, 4]);
  ctx.beginPath();
  ctx.moveTo(x50, 20);
  ctx.lineTo(x50, h - 25);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.fillStyle = '#EAB308';
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('50.0% (Maioria)', x50, 14);

  // Faixas dos candidatos
  data.candidatos.slice(0, 2).forEach((cand, idx) => {
    const y = 50 + idx * 48;
    const xLow = Math.max(0, toX(cand.ic_inferior_95));
    const xHigh = Math.min(w, toX(cand.ic_superior_95));
    const xMean = toX(cand.perc_projetado);
    const cor = cand.cor_hex || (idx === 0 ? '#38BDF8' : '#F43F5E');

    // Barra do IC 95%
    ctx.fillStyle = cor + '33';
    ctx.fillRect(xLow, y - 10, xHigh - xLow, 20);

    ctx.strokeStyle = cor;
    ctx.lineWidth = 2;
    ctx.strokeRect(xLow, y - 10, xHigh - xLow, 20);

    // Ponto Médio
    ctx.fillStyle = '#FFF';
    ctx.beginPath();
    ctx.arc(xMean, y, 6, 0, Math.PI * 2);
    ctx.fill();

    // Rótulos
    ctx.fillStyle = '#FFF';
    ctx.font = 'bold 12px sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(`${cand.nome} (${cand.perc_projetado}%)`, 10, y - 14);

    ctx.fillStyle = 'var(--text-muted)';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(`IC 95%: [${cand.ic_inferior_95}% - ${cand.ic_superior_95}%]`, w - 10, y - 14);
  });
}

function desenharGraficoEvolucao() {
  const canvas = document.getElementById('historyCanvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.parentElement.clientWidth - 48;
  const h = canvas.height = 160;

  ctx.clearRect(0, 0, w, h);

  const hist = state.historicoProjecoes;
  if (hist.length < 2) {
    ctx.fillStyle = 'var(--text-muted)';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Aguardando acúmulo de ciclos para traçar curva temporal...', w / 2, h / 2);
    return;
  }

  // Desenha curva de % projetado ao longo dos ciclos
  const numPontos = hist.length;
  const getX = (i) => (i / (numPontos - 1)) * (w - 60) + 40;
  const toY = (pct) => h - 20 - ((pct - 45.0) / 15.0) * (h - 40);

  // Linha 50%
  const y50 = toY(50.0);
  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(40, y50);
  ctx.lineTo(w, y50);
  ctx.stroke();

  // Curvas para os 2 primeiros candidatos
  [0, 1].forEach((candIdx) => {
    ctx.beginPath();
    hist.forEach((item, i) => {
      if (item.candidatos && item.candidatos[candIdx]) {
        const p = item.candidatos[candIdx].perc_projetado;
        const x = getX(i);
        const y = toY(p);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
    });
    ctx.strokeStyle = candIdx === 0 ? '#38BDF8' : '#F43F5E';
    ctx.lineWidth = 2.5;
    ctx.stroke();
  });
}

window.addEventListener('DOMContentLoaded', () => {
  inicializarSSE();
  window.addEventListener('resize', () => {
    if (state.ultimoDado) {
      desenharFaixaIncerteza(state.ultimoDado);
      desenharGraficoEvolucao();
    }
  });
});
