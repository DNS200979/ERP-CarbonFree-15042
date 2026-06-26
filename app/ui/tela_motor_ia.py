"""
Módulo 2 — Interface do Motor de IA para cálculo preciso de emissões.

REORGANIZAÇÃO: as calculadoras agora ficam separadas em ABAS por ESCOPO
(GHG Protocol). Cada aba contém somente as calculadoras pertinentes àquele
escopo, e cada cálculo, ao ser adicionado, alimenta o inventário consolidado
no rodapé. O botão "Gerar Inventário" envia os totais já agrupados por escopo
diretamente para a Tela de Emissões — integração automática e auditável.
"""

import tkinter as tk
from tkinter import messagebox, ttk

from app.ui.app import (
    COR_FUNDO, COR_VERDE, COR_VERDE_ESCURO, COR_AZUL,
    COR_CINZA, COR_TEXTO, FONTE_NORMAL, FONTE_PEQUENA,
)
from app.services.motor_ia import (
    calcular_inventario,
    listar_combustiveis, listar_refrigerantes, listar_setores_cadeia,
)


# ── Configuração visual por escopo ──────────────────────────────────────────
LABELS_TIPO = {
    "combustivel":   "Combustível",
    "eletricidade":  "Energia Elétrica",
    "refrigerante":  "Emissão Fugitiva (Refrigerante)",
    "cadeia":        "Cadeia de Fornecimento",
    "transporte":    "Transporte Rodoviário",
}

# Mapeia cada escopo às calculadoras que pertencem a ele
CALCULADORAS_POR_ESCOPO = {
    1: ["combustivel", "refrigerante"],   # Combustão direta + fugitivas
    2: ["eletricidade"],                  # Energia comprada
    3: ["cadeia", "transporte"],          # Cadeia de valor
}

DESCRICAO_ESCOPO = {
    1: ("Emissões Diretas — fontes sob controle operacional da empresa "
        "(combustão estacionária/móvel, processos e emissões fugitivas)."),
    2: ("Emissões Indiretas de Energia — eletricidade, vapor ou calor "
        "adquiridos de terceiros."),
    3: ("Outras Emissões Indiretas — cadeia de fornecimento, transporte "
        "terceirizado, viagens, resíduos etc."),
}

COR_ESCOPO = {1: "#c0392b", 2: "#d35400", 3: "#2980b9"}

STATUS_COR = {
    "ISENTO":                           "#27ae60",
    "MONITORAMENTO OBRIGATÓRIO":        "#e67e22",
    "CONFORMIDADE TOTAL OBRIGATÓRIA":   "#e74c3c",
}


class TelaMotorIA(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COR_FUNDO)
        self._atividades: list[dict] = []
        # Para cada aba (escopo), um conjunto independente de widgets dinâmicos
        self._abas: dict[int, dict] = {}
        self._build()

    # ── Construção da tela ─────────────────────────────────────────────────
    def _build(self):
        # Cabeçalho
        tk.Label(
            self, text="Motor IA — Cálculo Preciso de Emissões",
            font=("Arial", 13, "bold"), fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(pady=(12, 2))

        tk.Label(
            self,
            text="Calculadoras separadas por Escopo (GHG Protocol). "
                 "Tudo é consolidado no inventário automaticamente.",
            font=("Arial", 9, "italic"), fg="#7f8c8d", bg=COR_FUNDO,
        ).pack(pady=(0, 8))

        # ── Notebook com 3 abas (uma por escopo) ──────────────────────────
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(padx=18, fill=tk.BOTH, expand=False, pady=(0, 6))

        for escopo in (1, 2, 3):
            frame = tk.Frame(self._notebook, bg=COR_FUNDO)
            self._notebook.add(frame, text=f"  ESCOPO {escopo}  ")
            self._build_aba_escopo(frame, escopo)

        # ── Lista consolidada de atividades adicionadas ───────────────────
        frame_lista = tk.LabelFrame(
            self, text=" Inventário Consolidado (todas as atividades) ",
            font=("Arial", 10, "bold"), bg=COR_FUNDO, fg=COR_VERDE_ESCURO,
        )
        frame_lista.pack(padx=18, fill=tk.BOTH, expand=True, pady=(2, 6))

        cols = ttk.Treeview(
            frame_lista,
            columns=("escopo", "tipo", "detalhe", "tco2e"),
            show="headings", height=5,
        )
        cols.heading("escopo",  text="Escopo")
        cols.heading("tipo",    text="Tipo de Atividade")
        cols.heading("detalhe", text="Detalhe")
        cols.heading("tco2e",   text="tCO2e")
        cols.column("escopo",  width=70,  anchor="center")
        cols.column("tipo",    width=180, anchor="w")
        cols.column("detalhe", width=280, anchor="w")
        cols.column("tco2e",   width=120, anchor="e")
        sb = ttk.Scrollbar(frame_lista, orient=tk.VERTICAL, command=cols.yview)
        cols.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        cols.pack(fill=tk.BOTH, expand=True)
        self._tree = cols

        frame_acoes = tk.Frame(frame_lista, bg=COR_FUNDO)
        frame_acoes.pack(fill=tk.X, pady=4, padx=6)
        tk.Button(
            frame_acoes, text="Remover selecionada",
            command=self._remover_atividade,
            bg="#e74c3c", fg="white", font=FONTE_PEQUENA,
            relief=tk.FLAT, cursor="hand2", padx=6,
        ).pack(side=tk.LEFT)
        tk.Button(
            frame_acoes, text="Limpar tudo",
            command=self._limpar_tudo,
            bg=COR_CINZA, fg="white", font=FONTE_PEQUENA,
            relief=tk.FLAT, cursor="hand2", padx=6,
        ).pack(side=tk.LEFT, padx=6)

        # Totais em tempo real
        self._label_totais = tk.Label(
            self, text="", font=("Courier", 10), fg=COR_TEXTO, bg=COR_FUNDO,
        )
        self._label_totais.pack(pady=(0, 4))

        # ── Botões finais (integração com inventário) ────────────────────
        frame_btns = tk.Frame(self, bg=COR_FUNDO)
        frame_btns.pack(pady=(0, 12))

        tk.Button(
            frame_btns,
            text="✓ Gerar Inventário Automatizado",
            command=self._calcular_e_salvar,
            bg=COR_VERDE, fg="white", font=("Arial", 10, "bold"),
            width=30, height=2, relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=6)

        tk.Button(
            frame_btns, text="← Voltar",
            command=self.master.ir_para_principal,
            bg=COR_CINZA, fg="white", font=("Arial", 10, "bold"),
            width=14, height=2, relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=6)

    # ── Construção de cada aba (escopo) ────────────────────────────────────
    def _build_aba_escopo(self, parent: tk.Frame, escopo: int):
        cor = COR_ESCOPO[escopo]

        # Cabeçalho da aba
        cab = tk.Frame(parent, bg=COR_FUNDO)
        cab.pack(fill=tk.X, padx=10, pady=(8, 4))

        tk.Label(
            cab, text=f"ESCOPO {escopo}",
            font=("Arial", 12, "bold"), fg=cor, bg=COR_FUNDO,
        ).pack(side=tk.LEFT)

        tk.Label(
            cab, text=DESCRICAO_ESCOPO[escopo],
            font=("Arial", 9, "italic"), fg="#7f8c8d", bg=COR_FUNDO,
            wraplength=600, justify="left",
        ).pack(side=tk.LEFT, padx=(12, 0))

        # Seletor de calculadora dentro do escopo
        sel_frame = tk.Frame(parent, bg=COR_FUNDO)
        sel_frame.pack(fill=tk.X, padx=10, pady=(4, 4))

        tk.Label(sel_frame, text="Calculadora:", font=FONTE_NORMAL,
                 bg=COR_FUNDO, fg=COR_TEXTO).pack(side=tk.LEFT, padx=(0, 6))

        tipos_disponiveis = CALCULADORAS_POR_ESCOPO[escopo]
        var_tipo = tk.StringVar(value=LABELS_TIPO[tipos_disponiveis[0]])
        combo = ttk.Combobox(
            sel_frame, textvariable=var_tipo,
            values=[LABELS_TIPO[t] for t in tipos_disponiveis],
            width=32, state="readonly", font=FONTE_NORMAL,
        )
        combo.pack(side=tk.LEFT)
        combo.bind("<<ComboboxSelected>>", lambda _e, esc=escopo: self._atualizar_campos(esc))

        # Frame onde os campos dinâmicos serão renderizados
        frame_campos = tk.LabelFrame(
            parent, text=" Dados da Atividade ",
            font=("Arial", 9, "bold"), bg=COR_FUNDO, fg=cor,
        )
        frame_campos.pack(fill=tk.X, padx=10, pady=4)

        btn_add = tk.Button(
            parent, text="+ Adicionar ao Inventário",
            command=lambda esc=escopo: self._adicionar_atividade(esc),
            bg=cor, fg="white", font=("Arial", 9, "bold"),
            relief=tk.FLAT, cursor="hand2", padx=10, pady=4,
        )
        btn_add.pack(pady=(2, 8))

        # Guarda o estado da aba
        self._abas[escopo] = {
            "var_tipo": var_tipo,
            "var_tipo_interno": tipos_disponiveis[0],
            "frame_campos": frame_campos,
            "widgets": {},
        }
        self._atualizar_campos(escopo)

    # ── Renderização dos campos dinâmicos por calculadora ─────────────────
    def _label_entry(self, parent, row, col, label, key, width=10, escopo=1):
        tk.Label(parent, text=label, font=FONTE_NORMAL,
                 bg=COR_FUNDO, fg=COR_TEXTO).grid(
            row=row, column=col, sticky="e", padx=4, pady=4)
        e = tk.Entry(parent, width=width, font=FONTE_NORMAL)
        e.grid(row=row, column=col + 1, sticky="w", padx=4, pady=4)
        self._abas[escopo]["widgets"][key] = e
        return e

    def _label_combo(self, parent, row, col, label, key, valores, width=18, escopo=1):
        tk.Label(parent, text=label, font=FONTE_NORMAL,
                 bg=COR_FUNDO, fg=COR_TEXTO).grid(
            row=row, column=col, sticky="e", padx=4, pady=4)
        cb = ttk.Combobox(parent, values=valores, width=width,
                          state="readonly", font=FONTE_NORMAL)
        if valores:
            cb.set(valores[0])
        cb.grid(row=row, column=col + 1, sticky="w", padx=4, pady=4)
        self._abas[escopo]["widgets"][key] = cb
        return cb

    def _atualizar_campos(self, escopo: int):
        aba = self._abas[escopo]
        # Limpa frame e widgets registrados
        for w in aba["frame_campos"].winfo_children():
            w.destroy()
        aba["widgets"] = {}

        label_atual = aba["var_tipo"].get()
        tipo = next((t for t, l in LABELS_TIPO.items() if l == label_atual),
                    CALCULADORAS_POR_ESCOPO[escopo][0])
        aba["var_tipo_interno"] = tipo
        f = aba["frame_campos"]

        if tipo == "combustivel":
            self._label_combo(f, 0, 0, "Combustível:", "combustivel",
                              listar_combustiveis(), width=22, escopo=escopo)
            self._label_entry(f, 0, 2, "Quantidade:", "quantidade", 10, escopo=escopo)
            self._label_combo(f, 1, 0, "Categoria:", "categoria",
                              ["combustivel_estacionario", "combustivel_movel"],
                              width=22, escopo=escopo)
            # Escopo já fixo no contexto da aba (1)
            tk.Label(f, text=f"Escopo: {escopo} (fixo)", font=FONTE_PEQUENA,
                     bg=COR_FUNDO, fg="#7f8c8d").grid(row=1, column=2, columnspan=2,
                                                       sticky="w", padx=4)

        elif tipo == "eletricidade":
            self._label_entry(f, 0, 0, "Consumo (kWh):", "kwh", 14, escopo=escopo)

        elif tipo == "refrigerante":
            self._label_combo(f, 0, 0, "Refrigerante:", "refrigerante",
                              listar_refrigerantes(), width=16, escopo=escopo)
            self._label_entry(f, 0, 2, "Kg vazados:", "kg_vazados", 10, escopo=escopo)

        elif tipo == "cadeia":
            self._label_combo(f, 0, 0, "Setor:", "setor",
                              listar_setores_cadeia(), width=26, escopo=escopo)
            self._label_entry(f, 0, 2, "Valor (R$):", "valor_reais", 12, escopo=escopo)

        elif tipo == "transporte":
            self._label_entry(f, 0, 0, "Distância (km):", "km", 10, escopo=escopo)
            self._label_entry(f, 0, 2, "Toneladas:", "toneladas", 8, escopo=escopo)
            self._label_combo(f, 1, 0, "Veículo:", "veiculo",
                              ["caminhao_diesel", "caminhao_leve", "van_diesel",
                               "trem", "navio", "aviao_carga"], width=20, escopo=escopo)

    def _get_valor(self, escopo: int, key: str, default="") -> str:
        w = self._abas[escopo]["widgets"].get(key)
        if w is None:
            return default
        if isinstance(w, ttk.Combobox):
            return w.get()
        return w.get().strip()

    # ── Adição/remoção de atividades ──────────────────────────────────────
    def _adicionar_atividade(self, escopo: int):
        tipo = self._abas[escopo]["var_tipo_interno"]
        item: dict = {"tipo_calculo": tipo}

        try:
            if tipo == "combustivel":
                item["combustivel"] = self._get_valor(escopo, "combustivel")
                item["quantidade"] = float(self._get_valor(escopo, "quantidade") or "0")
                item["categoria"] = self._get_valor(escopo, "categoria")
                item["escopo"] = escopo
                detalhe = f"{item['combustivel']} — {item['quantidade']} un"
            elif tipo == "eletricidade":
                item["kwh"] = float(self._get_valor(escopo, "kwh") or "0")
                detalhe = f"{item['kwh']:,.1f} kWh"
            elif tipo == "refrigerante":
                item["refrigerante"] = self._get_valor(escopo, "refrigerante")
                item["kg_vazados"] = float(self._get_valor(escopo, "kg_vazados") or "0")
                detalhe = f"{item['refrigerante']} — {item['kg_vazados']} kg"
            elif tipo == "cadeia":
                item["setor"] = self._get_valor(escopo, "setor")
                item["valor_reais"] = float(self._get_valor(escopo, "valor_reais") or "0")
                detalhe = f"{item['setor']} — R$ {item['valor_reais']:,.2f}"
            elif tipo == "transporte":
                item["km"] = float(self._get_valor(escopo, "km") or "0")
                item["toneladas"] = float(self._get_valor(escopo, "toneladas") or "1")
                item["veiculo"] = self._get_valor(escopo, "veiculo")
                detalhe = f"{item['veiculo']} — {item['km']} km × {item['toneladas']} t"
        except ValueError:
            messagebox.showwarning("Atenção", "Preencha os valores numéricos corretamente.")
            return

        # Calcula tCO2e desta atividade isoladamente (para preview)
        relatorio = calcular_inventario([item])
        tco2e = relatorio.total_tco2e
        escopo_real = item.get("escopo",
                               2 if tipo == "eletricidade"
                               else 3 if tipo in ("cadeia", "transporte") else 1)

        self._atividades.append(item)
        self._tree.insert("", tk.END, values=(
            f"Escopo {escopo_real}",
            LABELS_TIPO.get(tipo, tipo),
            detalhe,
            f"{tco2e:,.6f} tCO2e",
        ))
        self._atualizar_totais()

    def _remover_atividade(self):
        sel = self._tree.selection()
        if not sel:
            return
        idx = self._tree.index(sel[0])
        self._tree.delete(sel[0])
        if 0 <= idx < len(self._atividades):
            self._atividades.pop(idx)
        self._atualizar_totais()

    def _limpar_tudo(self):
        if not self._atividades:
            return
        if not messagebox.askyesno("Limpar", "Remover todas as atividades adicionadas?"):
            return
        self._atividades.clear()
        for item in self._tree.get_children():
            self._tree.delete(item)
        self._atualizar_totais()

    def _atualizar_totais(self):
        if not self._atividades:
            self._label_totais.config(text="")
            return
        relatorio = calcular_inventario(self._atividades)
        total = relatorio.total_tco2e
        if total < 10_000:
            status = "ISENTO"
        elif total <= 25_000:
            status = "MONITORAMENTO OBRIGATÓRIO"
        else:
            status = "CONFORMIDADE TOTAL OBRIGATÓRIA"
        cor = STATUS_COR.get(status, COR_TEXTO)
        texto = (
            f"Escopo 1: {relatorio.escopo1_total:>10,.4f}  |  "
            f"Escopo 2: {relatorio.escopo2_total:>10,.4f}  |  "
            f"Escopo 3: {relatorio.escopo3_total:>10,.4f}  |  "
            f"TOTAL: {total:>10,.4f} tCO2e  →  {status}"
        )
        self._label_totais.config(text=texto, fg=cor)

    # ── INTEGRAÇÃO AUTOMATIZADA com a Tela de Emissões ────────────────────
    def _calcular_e_salvar(self):
        if not self._atividades:
            messagebox.showwarning(
                "Atenção",
                "Adicione pelo menos uma atividade em alguma das abas de Escopo "
                "antes de gerar o inventário.",
            )
            return

        relatorio = calcular_inventario(self._atividades)
        campos = relatorio.para_emissao_dict()

        # Mostra resumo e confirma envio para inventário
        resumo = (
            f"As atividades calculadas serão enviadas ao Inventário:\n\n"
            f"  • Escopo 1: {relatorio.escopo1_total:,.4f} tCO2e\n"
            f"  • Escopo 2: {relatorio.escopo2_total:,.4f} tCO2e\n"
            f"  • Escopo 3: {relatorio.escopo3_total:,.4f} tCO2e\n"
            f"  ───────────────────────────────────\n"
            f"  TOTAL: {relatorio.total_tco2e:,.4f} tCO2e\n\n"
            f"Continuar?"
        )
        if not messagebox.askyesno("Gerar Inventário Automatizado", resumo):
            return

        # Navega para tela de emissões pré-preenchida
        self.master.ir_para_emissoes_preenchidas(campos, relatorio.total_tco2e)
