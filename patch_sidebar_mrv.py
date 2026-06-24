#!/usr/bin/env python3
"""
patch_sidebar_mrv.py

Adiciona o link "Fechamento Mensal MRV" (→ /mrv) na sidebar do index.html,
logo abaixo do item "Inventário GEE".

Uso:
    python patch_sidebar_mrv.py            # edita ./index.html
    python patch_sidebar_mrv.py caminho/para/index.html

Seguro:
  • Faz backup em index.html.bak-mrv antes de gravar.
  • Aborta (sem alterar nada) se o ponto de ancoragem não existir exatamente 1x.
  • Aborta se o patch já tiver sido aplicado (procura href="/mrv").
"""

import sys
import os

# Âncora: a linha do item "Inventário GEE" na sidebar (6 espaços de indentação).
ANCHOR = (
    '      <a class="sidebar-link" data-view="emissoes">'
    '<i data-lucide="factory"></i> Inventário GEE</a>'
)

# A âncora + a nova linha logo abaixo, com a mesma indentação.
ADD = (
    ANCHOR
    + '\n      <a class="sidebar-link" href="/mrv">'
      '<i data-lucide="calendar-check"></i> Fechamento Mensal MRV</a>'
)


def aplicar(caminho: str) -> int:
    if not os.path.isfile(caminho):
        print(f"ERRO: arquivo não encontrado: {caminho}")
        return 1

    with open(caminho, "r", encoding="utf-8") as f:
        html = f.read()

    if 'href="/mrv"' in html:
        print('O link já existe (encontrei href="/mrv"). Nada a fazer.')
        return 0

    n = html.count(ANCHOR)
    if n != 1:
        print(f"ERRO: ponto de ancoragem encontrado {n}x (esperado 1x).")
        print("      Seu index.html difere do esperado — nada foi alterado.")
        print("      Alternativa: edição manual (cole a linha do link logo")
        print("      após a linha do 'Inventário GEE' na sidebar).")
        return 1

    backup = caminho + ".bak-mrv"
    with open(backup, "w", encoding="utf-8") as f:
        f.write(html)

    html = html.replace(ANCHOR, ADD, 1)
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✓ Link 'Fechamento Mensal MRV' adicionado em {caminho}")
    print(f"  Backup do original em {backup}")
    print("  Recarregue o painel (Ctrl+Shift+R); o item aparece na sidebar, em Operação.")
    return 0


if __name__ == "__main__":
    caminho = sys.argv[1] if len(sys.argv) > 1 else "index.html"
    sys.exit(aplicar(caminho))
