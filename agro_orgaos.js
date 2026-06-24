/* =============================================================================
 *  agro_orgaos.js — Consulta de titular rural por CNPJ/CPF (órgãos ambientais)
 *
 *  Arquivo AUTÔNOMO. Não altera nenhuma lógica existente do index.html.
 *  Ao carregar, ele:
 *    1) injeta um cartão de busca por CNPJ/CPF no topo do formulário
 *       de Certificado Rural (#cert-form), na view "Certificados Rurais";
 *    2) chama GET /api/v1/certificados/consultar-documento/{doc};
 *    3) autopreenche Titular, Bioma e Atividade (e Área, quando disponível),
 *       mostrando a origem/status de cada órgão consultado.
 *
 *  Reutiliza as funções globais já definidas no index.html:
 *    api(), toast(), fmt(), state, abrirModalLogin()
 *
 *  COMO USAR (uma linha só, sem mexer no resto):
 *    Adicione, logo antes de </body> no index.html:
 *        <script src="agro_orgaos.js"></script>      (GitHub Pages / mesma pasta)
 *    ou, quando servido pelo FastAPI:
 *        <script src="/static/agro_orgaos.js"></script>
 * ========================================================================== */
(function () {
  'use strict';

  // ---- Helpers locais (não dependem do index.html) -------------------------
  function $(id) { return document.getElementById(id); }

  function setSelectValue(sel, valor) {
    if (!sel || !valor) return false;
    const alvo = String(valor).trim();
    const opt = Array.from(sel.options).find(
      o => o.value === alvo || o.text.trim() === alvo
    );
    if (opt) { sel.value = opt.value; return true; }
    return false;
  }

  function statusPill(st) {
    const map = {
      ok:          ['#15803d', '#dcfce7', 'ok'],
      indisponivel:['#b45309', '#fef3c7', 'indisponível'],
      requer_car:  ['#b45309', '#fef3c7', 'requer Nº CAR'],
      nao_integrado:['#6b7280', '#f3f4f6', 'não integrado'],
    };
    const [cor, bg, txt] = map[st] || ['#6b7280', '#f3f4f6', st || '—'];
    return `<span style="display:inline-block;padding:.05rem .45rem;border-radius:999px;`
         + `font-size:.62rem;font-weight:700;color:${cor};background:${bg};">${txt}</span>`;
  }

  // ---- Injeção do cartão de busca no formulário ----------------------------
  function injetarCartao() {
    const form = $('cert-form');
    if (!form || $('agro-doc')) return;   // só injeta uma vez

    const card = document.createElement('div');
    card.className = 'bg-mbv-lime/10 border border-mbv-green/30 rounded-lg p-4';
    card.innerHTML = `
      <label class="field-label flex items-center gap-2">
        <i data-lucide="search" class="w-3.5 h-3.5"></i>
        Buscar nos órgãos ambientais por CNPJ / CPF
      </label>
      <div class="flex gap-2 flex-wrap">
        <input class="field-input" id="agro-doc" style="flex:1 1 240px"
               placeholder="00.000.000/0001-00 ou CPF (somente números também servem)" />
        <button type="button" class="btn-secondary" id="agro-doc-btn">
          <i data-lucide="download" class="w-4 h-4"></i> Buscar dados
        </button>
      </div>
      <div id="agro-doc-info" class="text-xs mt-2 leading-relaxed"
           style="display:none;background:#faf9f3;border:1px solid #ecebe0;border-radius:8px;padding:.6rem .8rem;"></div>
    `;
    // Insere como primeiro filho do formulário (acima da grade de campos)
    form.insertBefore(card, form.firstElementChild);

    $('agro-doc-btn').addEventListener('click', buscarDadosAgro);
    $('agro-doc').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); buscarDadosAgro(); }
    });

    if (typeof lucide !== 'undefined') lucide.createIcons();
  }

  // ---- Ação principal ------------------------------------------------------
  async function buscarDadosAgro() {
    // Reusa o estado/login do index.html
    if (typeof state === 'undefined' || !state.token) {
      if (typeof abrirModalLogin === 'function') abrirModalLogin();
      return;
    }
    const doc = ($('agro-doc').value || '').replace(/\D/g, '');
    const info = $('agro-doc-info');
    info.style.display = 'block';

    if (doc.length !== 11 && doc.length !== 14) {
      info.innerHTML = '<span style="color:#b91c1c">Informe um CNPJ (14 dígitos) ou CPF (11 dígitos).</span>';
      return;
    }

    const btn = $('agro-doc-btn');
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = 'Consultando órgãos…';
    info.innerHTML = 'Consultando Receita, IBGE e órgãos ambientais…';

    try {
      const d = await api('/api/v1/certificados/consultar-documento/' + doc);
      const form = $('cert-form');
      const campos = d.campos_certificado || {};

      // Autopreenchimento
      let preenchidos = [];
      if (campos.titular && form.titular) { form.titular.value = campos.titular; preenchidos.push('titular'); }
      if (campos.bioma && form.bioma && setSelectValue(form.bioma, campos.bioma)) preenchidos.push('bioma');
      if (campos.atividade && form.atividade && setSelectValue(form.atividade, campos.atividade)) preenchidos.push('atividade');
      if (campos.area_hectares != null && form.area_hectares) {
        form.area_hectares.value = campos.area_hectares; preenchidos.push('área');
      }

      // Resumo transparente das fontes
      const cab = `<div style="color:#152417;font-weight:700;margin-bottom:.35rem">`
        + `${d.titular || '(titular não disponível por este documento)'} `
        + `<span style="font-weight:500;color:#6b7280">· ${d.tipo_documento}`
        + `${d.municipio ? ' · ' + d.municipio + '/' + d.uf : ''}`
        + `${d.cnae ? ' · CNAE ' + d.cnae : ''}</span></div>`;

      const fontes = (d.fontes || []).map(s =>
        `<div style="margin:.15rem 0">${statusPill(s.status)} <b>${s.orgao}</b> — ${s.detalhe}</div>`
      ).join('');

      const avisos = (d.avisos || []).map(a =>
        `<div style="color:#b45309;margin-top:.25rem">⚠ ${a}</div>`
      ).join('');

      info.innerHTML = cab + fontes + avisos;

      if (typeof toast === 'function') {
        if (preenchidos.length) {
          toast('Preenchido automaticamente: ' + preenchidos.join(', ') + '. Confira e complete a área preservada.', 'success');
        } else {
          toast('Documento consultado, mas não há dados públicos para autopreencher. Preencha manualmente.', 'warn');
        }
      }
    } catch (e) {
      info.innerHTML = '<span style="color:#b91c1c">Erro: ' + (e.message || e) + '</span>';
      if (typeof toast === 'function') toast('Erro ao consultar órgãos: ' + (e.message || e), 'error');
    } finally {
      btn.disabled = false;
      btn.innerHTML = orig;
    }
  }

  // Expõe no escopo global (útil para chamar manualmente / depurar)
  window.buscarDadosAgro = buscarDadosAgro;

  // ---- Inicialização -------------------------------------------------------
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injetarCartao);
  } else {
    injetarCartao();
  }
})();
