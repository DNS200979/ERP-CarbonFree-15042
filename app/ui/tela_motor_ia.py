"""
Módulo 2 — Interface do Motor de IA para cálculo preciso de emissões.
Permite adicionar atividades individuais e calcular o inventário completo.
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


TIPOS_CALCULO = ["combustivel", "eletricidade", "refrigerante", "cadeia", "transporte"]

LABELS_TIPO = {
    "combustivel":   "Combustível",
    "eletricidade":  "Energia Elétrica",
    "refrigerante":  "Emissão Fugitiva (Refrigerante)",
    "cadeia":        "Cadeia de Fornecimento",
    "transporte":    "Transporte Rodoviário",
}

STATUS_COR = {
    "ISENTO":                           "#27ae60",
    "MONITORAMENTO OBRIGATÓRIO":        "#e67e22",
    "CONFORMIDADE TOTAL OBRIGATÓRIA":   "#e74c3c",
}


class TelaMotorIA(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COR_FUNDO)
        self._atividades: list[dict] = []
        self._build()

    def _build(self):
        tk.Label(
            self, text="Motor IA — Cálculo Preciso de Emissões",
            font=("Arial", 13, "bold"), fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(pady=(16, 2))

        tk.Label(
            self,
            text="Informe as atividades da empresa. O motor calcula tCO2e com fatores IPCC AR6 + MCTI.",
            font=("Arial", 9, "italic"), fg="#7f8c8d", bg=COR_FUNDO,
        ).pack(pady=(0, 10))

        # ── Painel de entrada de atividade ────────────────────────────────
        frame_entrada = tk.LabelFrame(
            self, text=" Nova Atividade ",
            font=("Arial", 10, "bold"), bg=COR_FUNDO, fg=COR_VERDE_ESCURO,
        )
        frame_entrada.pack(padx=24, fill=tk.X, pady=(0, 8))

        # Linha 1: tipo de cálculo + escopo
        linha1 = tk.Frame(frame_entrada, bg=COR_FUNDO)
        linha1.pack(fill=tk.X, padx=10, pady=6)

        tk.Label(linha1, text="Tipo:", font=FONTE_NORMAL, bg=COR_FUNDO, fg=COR_TEXTO, width=12, anchor="e").pack(side=tk.LEFT)
        self._var_tipo = tk.StringVar(value="combustivel")
        combo_tipo = ttk.Combobox(
            linha1, textvariable=self._var_tipo,
            values=[LABELS_TIPO[t] for t in TIPOS_CALCULO],
            width=28, state="readonly", font=FONTE_NORMAL,
        )
        combo_tipo.pack(side=tk.LEFT, padx=(4, 20))
        combo_tipo.bind("<<ComboboxSelected>>", lambda _: self._atualizar_campos())

        # Campos dinâmicos — frame que muda com o tipo
        self._frame_campos = tk.Frame(frame_entrada, bg=COR_FUNDO)
        self._frame_campos.pack(fill=tk.X, padx=10, pady=(0, 4))
        self._widgets_dinamicos: dict[str, tk.Widget] = {}
        self._atualizar_campos()

        tk.Button(
            frame_entrada, text="+ Adicionar Atividade",
            command=self._adicionar_atividade,
            bg=COR_AZUL, fg="white", font=("Arial", 9, "bold"),
            relief=tk.FLAT, cursor="hand2", padx=10, pady=4,
        ).pack(pady=(0, 8))

        # ── Lista de atividades adicionadas ───────────────────────────────
        frame_lista = tk.LabelFrame(
            self, text=" Atividades Adicionadas ",
            font=("Arial", 10, "bold"), bg=COR_FUNDO, fg=COR_VERDE_ESCURO,
        )
        frame_lista.pack(padx=24, fill=tk.BOTH, expand=True, pady=(0, 6))

        cols = ttk.Treeview(
            frame_lista,
            columns=("escopo", "tipo", "detalhe", "tco2e"),
            show="headings", height=6,
        )
        cols.heading("escopo",  text="Escopo")
        cols.heading("tipo",    text="Tipo")
        cols.heading("detalhe", text="Detalhe")
        cols.heading("tco2e",   text="tCO2e")
        cols.column("escopo",  width=70,  anchor="center")
        cols.column("tipo",    width=160, anchor="w")
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
        self._label_totais.pack()

        # Botões finais
        btn_frame = tk.Frame(self, bg=COR_FUNDO)
        btn_frame.pack(pady=10)

        tk.Button(
            btn_frame, text="CALCULAR E SALVAR",
            command=self._calcular_e_salvar,
            bg=COR_VERDE, fg="white", font=("Arial", 10, "bold"),
            width=22, height=2, relief=tk.FLAT, cursor="hand2",
        ).grid(row=0, column=0, padx=8)

        tk.Button(
            btn_frame, text="← Voltar", command=self.master.ir_para_principal,
            bg=COR_CINZA, fg="white", font=("Arial", 10, "bold"),
            width=12, height=2, relief=tk.FLAT, cursor="hand2",
        ).grid(row=0, column=1, padx=8)

    # ── Campos dinâmicos por tipo ─────────────────────────────────────────

    def _limpar_frame_campos(self):
        for w in self._frame_campos.winfo_children():
            w.destroy()
        self._widgets_dinamicos.clear()

    def _label_entry(self, parent, row, col_offset, texto, key, width=12):
        tk.Label(parent, text=texto, font=FONTE_NORMAL, bg=COR_FUNDO, fg=COR_TEXTO,
                 width=16, anchor="e").grid(row=row, column=col_offset, pady=4, padx=(0, 4))
        e = tk.Entry(parent, width=width, font=FONTE_NORMAL)
        e.grid(row=row, column=col_offset + 1, pady=4, padx=(0, 16))
        self._widgets_dinamicos[key] = e
        return e

    def _label_combo(self, parent, row, col_offset, texto, key, valores, width=20):
        tk.Label(parent, text=texto, font=FONTE_NORMAL, bg=COR_FUNDO, fg=COR_TEXTO,
                 width=16, anchor="e").grid(row=row, column=col_offset, pady=4, padx=(0, 4))
        cb = ttk.Combobox(parent, values=valores, width=width, state="readonly", font=FONTE_NORMAL)
        if valores:
            cb.current(0)
        cb.grid(row=row, column=col_offset + 1, pady=4, padx=(0, 16))
        self._widgets_dinamicos[key] = cb
        return cb

    def _atualizar_campos(self):
        self._limpar_frame_campos()
        label = self._var_tipo.get()
        tipo = next((t for t, l in LABELS_TIPO.items() if l == label), "combustivel")
        self._var_tipo_interno = tipo
        f = self._frame_campos

        if tipo == "combustivel":
            self._label_combo(f, 0, 0, "Combustível:", "combustivel", listar_combustiveis(), width=22)
            self._label_entry(f, 0, 2, "Quantidade:", "quantidade", 10)
            self._label_combo(f, 1, 0, "Categoria:", "categoria",
                              ["combustivel_estacionario", "combustivel_movel"], width=22)
            self._label_combo(f, 1, 2, "Escopo:", "escopo", ["1", "2", "3"], width=6)

        elif tipo == "eletricidade":
            self._label_entry(f, 0, 0, "Consumo (kWh):", "kwh", 14)

        elif tipo == "refrigerante":
            self._label_combo(f, 0, 0, "Refrigerante:", "refrigerante", listar_refrigerantes(), width=16)
            self._label_entry(f, 0, 2, "Kg vazados:", "kg_vazados", 10)

        elif tipo == "cadeia":
            self._label_combo(f, 0, 0, "Setor:", "setor", listar_setores_cadeia(), width=26)
            self._label_entry(f, 0, 2, "Valor (R$):", "valor_reais", 12)

        elif tipo == "transporte":
            self._label_entry(f, 0, 0, "Distância (km):", "km", 10)
            self._label_entry(f, 0, 2, "Toneladas:", "toneladas", 8)
            self._label_combo(f, 1, 0, "Veículo:", "veiculo",
                              ["caminhao_diesel", "caminhao_leve", "van_diesel",
                               "trem", "navio", "aviao_carga"], width=20)

    def _get_valor(self, key: str, default="") -> str:
        w = self._widgets_dinamicos.get(key)
        if w is None:
            return default
        if isinstance(w, ttk.Combobox):
            return w.get()
        return w.get().strip()

    def _adicionar_atividade(self):
        tipo = getattr(self, "_var_tipo_interno", "combustivel")
        item: dict = {"tipo_calculo": tipo}

        try:
            if tipo == "combustivel":
                item["combustivel"] = self._get_valor("combustivel")
                item["quantidade"] = float(self._get_valor("quantidade") or "0")
                item["categoria"] = self._get_valor("categoria")
                item["escopo"] = int(self._get_valor("escopo") or "1")
                detalhe = f"{item['combustivel']} — {item['quantidade']} un"
            elif tipo == "eletricidade":
                item["kwh"] = float(self._get_valor("kwh") or "0")
                detalhe = f"{item['kwh']:,.1f} kWh"
            elif tipo == "refrigerante":
                item["refrigerante"] = self._get_valor("refrigerante")
                item["kg_vazados"] = float(self._get_valor("kg_vazados") or "0")
                detalhe = f"{item['refrigerante']} — {item['kg_vazados']} kg"
            elif tipo == "cadeia":
                item["setor"] = self._get_valor("setor")
                item["valor_reais"] = float(self._get_valor("valor_reais") or "0")
                detalhe = f"{item['setor']} — R$ {item['valor_reais']:,.2f}"
            elif tipo == "transporte":
                item["km"] = float(self._get_valor("km") or "0")
                item["toneladas"] = float(self._get_valor("toneladas") or "1")
                item["veiculo"] = self._get_valor("veiculo")
                detalhe = f"{item['veiculo']} — {item['km']} km × {item['toneladas']} t"
        except ValueError:
            messagebox.showwarning("Atenção", "Preencha os valores numéricos corretamente.")
            return

        # Preview do tCO2e antes de adicionar
        relatorio = calcular_inventario([item])
        tco2e = relatorio.total_tco2e
        escopo = item.get("escopo", 2 if tipo == "eletricidade" else 3 if tipo in ("cadeia", "transporte") else 1)

        self._atividades.append(item)
        self._tree.insert("", tk.END, values=(
            f"Escopo {escopo}",
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
            f"Escopo 1: {relatorio.escopo1_total:>12,.4f} tCO2e  |  "
            f"Escopo 2: {relatorio.escopo2_total:>12,.4f} tCO2e  |  "
            f"Escopo 3: {relatorio.escopo3_total:>12,.4f} tCO2e  |  "
            f"TOTAL: {total:>12,.4f} tCO2e  →  {status}"
        )
        self._label_totais.config(text=texto, fg=cor)

    def _calcular_e_salvar(self):
        if not self._atividades:
            messagebox.showwarning("Atenção", "Adicione pelo menos uma atividade.")
            return

        relatorio = calcular_inventario(self._atividades)
        campos = relatorio.para_emissao_dict()

        # Navegar para tela de emissões pré-preenchida
        self.master.ir_para_emissoes_preenchidas(campos, relatorio.total_tco2e)


class DialogoEmpresa(tk.Toplevel):
    """Diálogo para coletar dados da empresa antes de salvar o inventário IA."""
    def __init__(self, parent, campos: dict, total_tco2e: float):
        super().__init__(parent)
        self.title("Dados da Empresa — Inventário IA")
        self.geometry("440x260")
        self.resizable(False, False)
        self.configure(bg=COR_FUNDO)
        self.grab_set()
        self._campos = campos
        self._total = total_tco2e
        self.resultado = None
        self._build()

    def _build(self):
        tk.Label(self, text="Complete os dados da empresa:", font=("Arial", 11, "bold"),
                 fg=COR_VERDE_ESCURO, bg=COR_FUNDO).pack(pady=(16, 10))

        form = tk.Frame(self, bg=COR_FUNDO)
        form.pack(padx=30)

        def campo(row, label, key):
            tk.Label(form, text=label, font=FONTE_NORMAL, bg=COR_FUNDO, fg=COR_TEXTO,
                     anchor="e", width=18).grid(row=row, column=0, pady=6, padx=(0, 8))
            e = tk.Entry(form, width=24, font=FONTE_NORMAL)
            e.grid(row=row, column=1, pady=6)
            return e

        self._empresa = campo(0, "Empresa / Razão Social:", "empresa")
        self._cnpj    = campo(1, "CNPJ / CPF:", "cnpj")
        self._ano     = campo(2, "Ano de Referência:", "ano")
        self._ano.insert(0, "2024")

        btn_frame = tk.Frame(self, bg=COR_FUNDO)
        btn_frame.pack(pady=14)

        tk.Button(btn_frame, text="SALVAR", command=self._salvar,
                  bg=COR_VERDE, fg="white", font=("Arial", 10, "bold"),
                  width=14, relief=tk.FLAT).grid(row=0, column=0, padx=8)

        tk.Button(btn_frame, text="Cancelar", command=self.destroy,
                  bg=COR_CINZA, fg="white", font=("Arial", 10, "bold"),
                  width=10, relief=tk.FLAT).grid(row=0, column=1, padx=8)

    def _salvar(self):
        empresa = self._empresa.get().strip()
        cnpj    = self._cnpj.get().strip()
        try:
            ano = int(self._ano.get().strip())
        except ValueError:
            messagebox.showwarning("Atenção", "Ano inválido.", parent=self)
            return
        if not empresa:
            messagebox.showwarning("Atenção", "Informe a empresa.", parent=self)
            return
        self.resultado = {
            "empresa": empresa,
            "cnpj_cpf": cnpj,
            "ano_referencia": ano,
            **self._campos,
        }
        self.destroy()
