#!/usr/bin/env python3
"""
aplicar_patch_index.py

Adiciona o recurso "Importar ECF" diretamente no index.html (view Inventário GEE),
para não depender da página balanco.html separada.

Uso:
    python aplicar_patch_index.py            # edita ./index.html
    python aplicar_patch_index.py caminho/index.html

O script é seguro:
  • Faz backup em index.html.bak antes de gravar.
  • Cada uma das 4 inserções é validada: o ponto de ancoragem precisa existir
    EXATAMENTE uma vez. Se algo não bater (ou se o patch já foi aplicado),
    ele aborta sem alterar nada.

São 4 mudanças:
  1) CSS do #ecf-modal (reaproveita o visual do modal de calculadora)
  2) Botão "Importar ECF" no cabeçalho do Inventário GEE
  3) HTML do modal de importação
  4) Bloco JavaScript que chama /api/v1/emissoes/importar-ecf e preenche o form
"""

import sys
import os

# ── 1) CSS ───────────────────────────────────────────────────────────────────
CSS_ANCHOR = "  .calc-modal-body { padding: 1.3rem; }"
CSS_ADD = CSS_ANCHOR + """

  /* Modal Importar ECF (reaproveita .calc-modal-card / -header / -body) */
  #ecf-modal {
    position: fixed; inset: 0; z-index: 110;
    background: rgba(12,23,14,.7); backdrop-filter: blur(4px);
    display: flex; align-items: center; justify-content: center;
    padding: 1rem; animation: modalFade .2s ease;
  }
  #ecf-modal.hidden { display: none; }"""

# ── 2) Botão no cabeçalho do Inventário GEE ──────────────────────────────────
BTN_ANCHOR = """          <button class="btn-accent" onclick="abrirFormEmissao()">
            <i data-lucide="plus-circle" class="w-4 h-4"></i>Novo inventário
          </button>"""
BTN_ADD = """          <div class="flex gap-2 flex-wrap">
            <button class="btn-secondary" onclick="abrirModalECF()">
              <i data-lucide="file-up" class="w-4 h-4"></i>Importar ECF
            </button>
            <button class="btn-accent" onclick="abrirFormEmissao()">
              <i data-lucide="plus-circle" class="w-4 h-4"></i>Novo inventário
            </button>
          </div>"""

# ── 3) HTML do modal ─────────────────────────────────────────────────────────
MODAL_ANCHOR = "<!-- ===================== MODAL DE LOGIN ===================== -->"
MODAL_ADD = """<!-- ===================== MODAL IMPORTAR ECF ===================== -->
<div id="ecf-modal" class="hidden">
  <div class="calc-modal-card">
    <div class="calc-modal-header">
      <div>
        <div class="text-mbv-green text-[10px] uppercase tracking-widest font-bold">Motor IA</div>
        <div class="font-display text-lg">Importar ECF (imposto de renda)</div>
      </div>
      <button onclick="fecharModalECF()" class="text-mbv-lime hover:text-white"><i data-lucide="x"></i></button>
    </div>
    <div class="calc-modal-body">
      <p class="text-xs text-stone-500 mb-3">
        Envie o arquivo <code class="font-mono">.txt</code> da ECF transmitida ao SPED. O sistema lê CNPJ,
        receita e gastos, consulta o CNAE e estima as emissões por balanço — sem digitação manual.
      </p>
      <div class="flex gap-2 items-center flex-wrap">
        <input type="file" id="ecf-file-inv" accept=".txt,.ecf" class="field-input" style="flex:1 1 220px; padding:.4rem;" />
        <button id="btn-ler-ecf" onclick="lerECFInventario()" class="btn-primary text-sm">
          <i data-lucide="upload" class="w-4 h-4"></i> Ler ECF
        </button>
      </div>

      <div id="ecf-modal-result" class="hidden mt-4 p-3 rounded-lg bg-stone-50 border border-stone-200 text-sm space-y-1">
        <div id="ecf-modal-summary"></div>
      </div>

      <div class="flex gap-2 mt-4">
        <button id="btn-aplicar-ecf" onclick="aplicarECFnoInventario()" class="btn-accent flex-1 justify-center text-sm hidden">
          <i data-lucide="check" class="w-4 h-4"></i> Aplicar no inventário
        </button>
        <button onclick="fecharModalECF()" class="btn-secondary flex-1 justify-center text-sm">Fechar</button>
      </div>
      <p class="text-[11px] text-stone-400 mt-3">
        Empresas do Simples (sem ECF) preenchem o inventário manualmente.
        Método spend-based é de triagem: refine Escopos 1 e 2 com dado físico acima de 25.000 tCO₂e/ano.
      </p>
    </div>
  </div>
</div>

""" + MODAL_ANCHOR

# ── 4) Bloco JavaScript ──────────────────────────────────────────────────────
JS_ANCHOR = "/* ---------- Inicialização ---------- */"
JS_ADD = r"""/* ========================================================================
 *  IMPORTAR ECF — preenche o Inventário GEE a partir do imposto de renda
 * ====================================================================== */
const ECF_STATE = { ultimo: null };

function abrirModalECF() {
  if (!state.token) { abrirModalLogin(); return; }
  ECF_STATE.ultimo = null;
  document.getElementById('ecf-file-inv').value = '';
  document.getElementById('ecf-modal-result').classList.add('hidden');
  document.getElementById('ecf-modal-summary').innerHTML = '';
  document.getElementById('btn-aplicar-ecf').classList.add('hidden');
  document.getElementById('ecf-modal').classList.remove('hidden');
  if (typeof lucide !== 'undefined') lucide.createIcons();
}
function fecharModalECF() {
  document.getElementById('ecf-modal').classList.add('hidden');
}

function ecfStatusBadge(total) {
  let st, c;
  if (total < 10000) { st = 'ISENTO'; c = 'badge-isento'; }
  else if (total <= 25000) { st = 'MONITORAMENTO OBRIGATÓRIO'; c = 'badge-monit'; }
  else { st = 'CONFORMIDADE TOTAL OBRIGATÓRIA'; c = 'badge-obrig'; }
  return `<span class="badge ${c}">${st}</span>`;
}

async function lerECFInventario() {
  if (!state.token) { abrirModalLogin(); return; }
  const input = document.getElementById('ecf-file-inv');
  const file = input.files && input.files[0];
  if (!file) { toast('Selecione o arquivo .txt da ECF.', 'warn'); return; }
  if (!state.apiUrl) { toast('Configure a URL da API.', 'error'); return; }

  const btn = document.getElementById('btn-ler-ecf');
  btn.disabled = true;
  const txtOrig = btn.innerHTML;
  btn.innerHTML = 'Lendo…';

  try {
    const fd = new FormData();
    fd.append('arquivo', file);
    const resp = await fetch(`${state.apiUrl}/api/v1/emissoes/importar-ecf?calcular=true`, {
      method: 'POST',
      headers: state.token ? { 'Authorization': `Bearer ${state.token}` } : {},
      body: fd,
    });
    if (resp.status === 401) {
      toast('Sessão expirada. Faça login novamente.', 'warn');
      state.token = ''; state.user = null; saveConfig(); atualizarUIUsuario(); abrirModalLogin();
      return;
    }
    if (!resp.ok) {
      let d = ''; try { d = (await resp.json()).detail || ''; } catch (e) {}
      throw new Error(`${resp.status}${d ? ' — ' + d : ''}`);
    }
    const data = await resp.json();
    ECF_STATE.ultimo = data;
    mostrarResumoECF(data);
  } catch (e) {
    toast('Erro ao importar ECF: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = txtOrig;
  }
}

function mostrarResumoECF(data) {
  const ecf = data.ecf || {};
  const ci = data.cnpj_info || {};
  const linhas = [];
  linhas.push(`<div><b>${ecf.razao_social || '—'}</b> · CNPJ ${ecf.cnpj || '—'}</div>`);
  linhas.push(`<div class="text-stone-500">Período ${ecf.periodo || '—'} · regime ${ecf.regime || '—'}</div>`);
  linhas.push(`<div>Receita bruta: <b>R$ ${fmt(ecf.receita_bruta, 2)}</b>`
    + (ecf.gasto_energia_eletrica ? ` · Energia: R$ ${fmt(ecf.gasto_energia_eletrica, 2)}` : '')
    + (ecf.gasto_combustivel ? ` · Combustível: R$ ${fmt(ecf.gasto_combustivel, 2)}` : '') + `</div>`);
  if (data.categoria_sugerida) {
    linhas.push(`<div>Categoria (CNAE ${ci.cnae_fiscal || '—'}): <b>${ci.categoria_rotulo || data.categoria_sugerida}</b></div>`);
  } else {
    linhas.push(`<div class="text-amber-700">CNAE sem mapeamento automático — abra "Inventário por Balanço" para escolher a categoria manualmente.</div>`);
  }
  if (ecf.avisos && ecf.avisos.length) {
    linhas.push(`<div class="text-amber-700">⚠ ${ecf.avisos.join(' · ')}</div>`);
  }

  let totaisHtml = '';
  if (data.calculo) {
    const r = data.calculo;
    totaisHtml = `
      <div class="bg-mbv-dark text-white rounded-lg p-3 grid grid-cols-4 gap-2 text-sm mt-3">
        <div><div class="text-mbv-olive text-[10px] uppercase tracking-wider font-bold">Escopo 1</div><div class="font-mono">${fmt(r.escopo1_total, 4)}</div></div>
        <div><div class="text-mbv-olive text-[10px] uppercase tracking-wider font-bold">Escopo 2</div><div class="font-mono">${fmt(r.escopo2_total, 4)}</div></div>
        <div><div class="text-mbv-olive text-[10px] uppercase tracking-wider font-bold">Escopo 3</div><div class="font-mono">${fmt(r.escopo3_total, 4)}</div></div>
        <div><div class="text-mbv-green text-[10px] uppercase tracking-wider font-bold">Total</div><div class="font-mono text-mbv-green">${fmt(r.total_tco2e, 4)}</div></div>
      </div>
      <div class="mt-2">${ecfStatusBadge(r.total_tco2e)}</div>`;
    document.getElementById('btn-aplicar-ecf').classList.remove('hidden');
  } else {
    totaisHtml = `<div class="text-amber-700 mt-2">${data.aviso_calculo || 'Não foi possível calcular automaticamente.'}</div>`;
    document.getElementById('btn-aplicar-ecf').classList.add('hidden');
  }

  document.getElementById('ecf-modal-summary').innerHTML = linhas.join('') + totaisHtml;
  document.getElementById('ecf-modal-result').classList.remove('hidden');
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function aplicarECFnoInventario() {
  const data = ECF_STATE.ultimo;
  if (!data || !data.calculo) { toast('Nada para aplicar.', 'warn'); return; }

  abrirFormEmissao();
  const form = document.getElementById('emissao-form');

  const ecf = data.ecf || {};
  if (form.empresa)        form.empresa.value        = ecf.razao_social || '';
  if (form.cnpj_cpf)       form.cnpj_cpf.value       = ecf.cnpj || '';
  if (form.ano_referencia) form.ano_referencia.value = ecf.ano_referencia || 2025;

  const campos = data.calculo.campos_emissao || {};
  Object.entries(campos).forEach(([k, v]) => {
    if (form[k] !== undefined && form[k] !== null) form[k].value = Number(v).toFixed(4);
  });

  atualizarPreview();
  fecharModalECF();
  toast('Inventário preenchido a partir da ECF. Revise e clique em "Enviar ao backend".', 'success');
  document.getElementById('form-emissao').scrollIntoView({ behavior: 'smooth' });
}

""" + JS_ANCHOR


EDICOES = [
    ("CSS do modal ECF",            CSS_ANCHOR,   CSS_ADD),
    ("Botão Importar ECF",          BTN_ANCHOR,   BTN_ADD),
    ("HTML do modal ECF",           MODAL_ANCHOR, MODAL_ADD),
    ("Bloco JavaScript do ECF",     JS_ANCHOR,    JS_ADD),
]


def aplicar(caminho: str) -> int:
    if not os.path.isfile(caminho):
        print(f"ERRO: arquivo não encontrado: {caminho}")
        return 1

    with open(caminho, "r", encoding="utf-8") as f:
        html = f.read()

    if "id=\"ecf-modal\"" in html or "abrirModalECF" in html:
        print("Parece que o patch JÁ foi aplicado (encontrei 'ecf-modal'/'abrirModalECF'). "
              "Nada a fazer.")
        return 1

    # Validação: cada âncora precisa existir exatamente uma vez
    for nome, ancora, _ in EDICOES:
        n = html.count(ancora)
        if n != 1:
            print(f"ERRO em '{nome}': ponto de ancoragem encontrado {n}x (esperado 1x).")
            print("       O index.html difere do esperado. Nada foi alterado.")
            return 1

    # Backup
    backup = caminho + ".bak"
    with open(backup, "w", encoding="utf-8") as f:
        f.write(html)

    # Aplica
    for nome, ancora, novo in EDICOES:
        html = html.replace(ancora, novo, 1)
        print(f"  ✓ {nome}")

    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nPatch aplicado em {caminho}")
    print(f"Backup do original salvo em {backup}")
    print("Reinicie o uvicorn (se estiver com --reload, já recarrega) e abra o painel.")
    print("No Inventário GEE, use o botão 'Importar ECF'.")
    return 0


if __name__ == "__main__":
    caminho = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    sys.exit(aplicar(caminho))
