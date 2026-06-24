import hashlib
import tkinter as tk
from tkinter import messagebox, ttk

from app.ui.app import (
    COR_FUNDO, COR_VERDE, COR_VERDE_ESCURO, COR_AZUL,
    COR_CINZA, COR_TEXTO, FONTE_NORMAL, FONTE_PEQUENA,
)
from app.models.emissao import Emissao

# Cores de conformidade
COR_ISENTO     = "#27ae60"
COR_MONITORA   = "#e67e22"
COR_OBRIGATORIO = "#e74c3c"


class TelaEmissoes(tk.Frame):
    def __init__(self, master, campos_ia: dict | None = None):
        super().__init__(master, bg=COR_FUNDO)
        self._entradas: dict[str, tk.Entry] = {}
        self._build()
        if campos_ia:
            self._preencher_campos_ia(campos_ia)

    # ── construção da tela ────────────────────────────────────────────────

    def _build(self):
        # Cabeçalho fixo
        tk.Label(
            self, text="Registro de Emissões de Carbono",
            font=("Arial", 13, "bold"), fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(pady=(14, 2))
        tk.Label(
            self, text="GHG Protocol Brasil · ISO 14064-1:2018 · Lei 15.042/2024",
            font=("Arial", 8, "italic"), fg="#95a5a6", bg=COR_FUNDO,
        ).pack(pady=(0, 8))

        # Área rolável
        container = tk.Frame(self, bg=COR_FUNDO)
        container.pack(fill=tk.BOTH, expand=True, padx=16)

        canvas = tk.Canvas(container, bg=COR_FUNDO, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._inner = tk.Frame(canvas, bg=COR_FUNDO)
        win_id = canvas.create_window((0, 0), window=self._inner, anchor="nw")

        self._inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # Seções do formulário
        self._secao_empresa()
        self._secao_escopo("ESCOPO 1 — Emissões Diretas (tCO2e)",
                           "GHG Protocol · fontes sob controle operacional direto",
                           [("Combustíveis Estacionários", "e1_estacionario",
                             "Caldeiras, fornos, geradores"),
                            ("Combustíveis Móveis / Frota", "e1_movel",
                             "Veículos e máquinas próprias"),
                            ("Processos Industriais", "e1_processos",
                             "Reações químicas, produção de cimento, aço etc."),
                            ("Emissões Fugitivas", "e1_fugitivas",
                             "Refrigeração, ar-condicionado, vazamentos")])

        self._secao_escopo("ESCOPO 2 — Energia Indireta (tCO2e)",
                           "Emissões associadas à energia comprada de terceiros",
                           [("Energia Elétrica Comprada", "e2_eletrica",
                             "Fator de emissão da rede elétrica nacional"),
                            ("Vapor / Calor Comprado", "e2_vapor",
                             "Geração de calor por fornecedor externo")])

        self._secao_escopo("ESCOPO 3 — Outras Indiretas (tCO2e) · opcional",
                           "Cadeia de valor — upstream e downstream",
                           [("Cadeia de Fornecimento", "e3_cadeia",
                             "Extração e produção de matérias-primas"),
                            ("Transporte e Distribuição", "e3_transporte",
                             "Logística de entrada/saída terceirizada"),
                            ("Tratamento de Resíduos", "e3_residuos",
                             "Resíduos gerados nas operações")])

        self._secao_ativos()

        # Painel de resultado (fixo na base)
        self._build_resultado()

    def _secao_empresa(self):
        frame = self._frame_secao("DADOS DA EMPRESA")
        campos = [
            ("Empresa / Razão Social", "empresa", ""),
            ("CNPJ / CPF",             "cnpj_cpf", "Ex: 00.000.000/0001-00"),
            ("Ano de Referência",      "ano_referencia", "Ex: 2025"),
        ]
        for i, (label, chave, placeholder) in enumerate(campos):
            tk.Label(frame, text=label + ":", font=FONTE_NORMAL,
                     bg="#eaf4ea", fg=COR_TEXTO, anchor="w").grid(
                row=i, column=0, sticky="w", pady=5, padx=(8, 12))
            e = tk.Entry(frame, width=40, font=FONTE_NORMAL)
            e.grid(row=i, column=1, pady=5, sticky="w")
            if placeholder:
                e.insert(0, placeholder)
                e.config(fg="#aaa")
                e.bind("<FocusIn>",  lambda ev, ph=placeholder: self._clear_placeholder(ev, ph))
                e.bind("<FocusOut>", lambda ev, ph=placeholder: self._set_placeholder(ev, ph))
            self._entradas[chave] = e

    def _secao_escopo(self, titulo: str, subtitulo: str, campos: list):
        frame = self._frame_secao(titulo, subtitulo)
        for i, (label, chave, dica) in enumerate(campos):
            tk.Label(frame, text=label + ":", font=FONTE_NORMAL,
                     bg="#eaf4ea", fg=COR_TEXTO, anchor="w", width=32).grid(
                row=i, column=0, sticky="w", pady=4, padx=(8, 8))
            e = tk.Entry(frame, width=14, font=FONTE_NORMAL, justify="right")
            e.insert(0, "0")
            e.grid(row=i, column=1, pady=4, sticky="w")
            e.bind("<KeyRelease>", lambda _: self._atualizar_totais())
            tk.Label(frame, text=dica, font=FONTE_PEQUENA,
                     bg="#eaf4ea", fg="#7f8c8d", anchor="w").grid(
                row=i, column=2, sticky="w", padx=(8, 0))
            self._entradas[chave] = e

    def _secao_ativos(self):
        frame = self._frame_secao(
            "ATIVOS DE CARBONO DISPONÍVEIS",
            "CBE = Cota Brasileira de Emissão  ·  CRVE = Certificado de Redução/Remoção Verificada",
        )
        for i, (label, chave, dica) in enumerate([
            ("CBE Disponíveis (tCO2e)", "cbe_disponiveis", "Cotas alocadas pelo governo (SBCE)"),
            ("CRVE Disponíveis (tCO2e)", "crve_disponiveis", "Certificados de projetos verificados"),
        ]):
            tk.Label(frame, text=label + ":", font=FONTE_NORMAL,
                     bg="#eaf4ea", fg=COR_TEXTO, anchor="w", width=32).grid(
                row=i, column=0, sticky="w", pady=4, padx=(8, 8))
            e = tk.Entry(frame, width=14, font=FONTE_NORMAL, justify="right")
            e.insert(0, "0")
            e.grid(row=i, column=1, pady=4)
            e.bind("<KeyRelease>", lambda _: self._atualizar_totais())
            tk.Label(frame, text=dica, font=FONTE_PEQUENA,
                     bg="#eaf4ea", fg="#7f8c8d").grid(row=i, column=2, sticky="w", padx=(8, 0))
            self._entradas[chave] = e

    def _build_resultado(self):
        painel = tk.Frame(self, bg="#d5e8d4", relief=tk.GROOVE, bd=1)
        painel.pack(fill=tk.X, padx=16, pady=(6, 4))

        # Totais por escopo
        totais_frame = tk.Frame(painel, bg="#d5e8d4")
        totais_frame.pack(side=tk.LEFT, padx=14, pady=8)

        self._lbl_e1 = tk.Label(totais_frame, text="Escopo 1: 0,00 tCO2e",
                                 font=FONTE_PEQUENA, bg="#d5e8d4", fg=COR_TEXTO)
        self._lbl_e1.pack(anchor="w")
        self._lbl_e2 = tk.Label(totais_frame, text="Escopo 2: 0,00 tCO2e",
                                 font=FONTE_PEQUENA, bg="#d5e8d4", fg=COR_TEXTO)
        self._lbl_e2.pack(anchor="w")
        self._lbl_e3 = tk.Label(totais_frame, text="Escopo 3: 0,00 tCO2e",
                                 font=FONTE_PEQUENA, bg="#d5e8d4", fg=COR_TEXTO)
        self._lbl_e3.pack(anchor="w")

        # Total geral
        self._lbl_total = tk.Label(painel, text="TOTAL\n0,00 tCO2e",
                                    font=("Arial", 11, "bold"), bg="#d5e8d4", fg=COR_TEXTO)
        self._lbl_total.pack(side=tk.LEFT, padx=20)

        # Status de conformidade
        self._lbl_status = tk.Label(painel, text="—",
                                     font=("Arial", 10, "bold"), bg="#d5e8d4", fg=COR_TEXTO,
                                     width=26, wraplength=200, justify="center")
        self._lbl_status.pack(side=tk.LEFT, padx=10)

        # Déficit / Superávit
        self._lbl_deficit = tk.Label(painel, text="Déficit: —",
                                      font=("Arial", 10, "bold"), bg="#d5e8d4", fg=COR_TEXTO)
        self._lbl_deficit.pack(side=tk.LEFT, padx=10)

        # Botões
        btn_frame = tk.Frame(painel, bg="#d5e8d4")
        btn_frame.pack(side=tk.RIGHT, padx=10, pady=6)

        tk.Button(btn_frame, text="💾 Salvar", command=self._salvar,
                  bg=COR_VERDE, fg="white", font=("Arial", 9, "bold"),
                  width=10, relief=tk.FLAT, cursor="hand2").pack(pady=2)

        tk.Button(btn_frame, text="📄 Relatório PDF", command=self._gerar_pdf,
                  bg=COR_AZUL, fg="white", font=("Arial", 9, "bold"),
                  width=10, relief=tk.FLAT, cursor="hand2").pack(pady=2)

        tk.Button(btn_frame, text="← Voltar", command=self.master.ir_para_principal,
                  bg=COR_CINZA, fg="white", font=("Arial", 9, "bold"),
                  width=10, relief=tk.FLAT, cursor="hand2").pack(pady=2)

    def _preencher_campos_ia(self, campos: dict):
        """Preenche os campos de emissão com valores calculados pelo Motor IA."""
        for chave, valor in campos.items():
            if chave in self._entradas:
                e = self._entradas[chave]
                e.delete(0, tk.END)
                e.insert(0, f"{float(valor):.4f}")
        self._atualizar_totais()
        tk.messagebox.showinfo(
            "Motor IA",
            "Campos preenchidos automaticamente com base nas atividades calculadas.\n"
            "Preencha os dados da empresa e salve o inventário.",
        )

    # ── helpers de layout ─────────────────────────────────────────────────

    def _frame_secao(self, titulo: str, subtitulo: str = "") -> tk.Frame:
        wrapper = tk.Frame(self._inner, bg=COR_FUNDO)
        wrapper.pack(fill=tk.X, pady=(8, 0))

        tk.Label(wrapper, text=titulo, font=("Arial", 10, "bold"),
                 bg=COR_VERDE_ESCURO, fg="white", anchor="w", padx=8).pack(fill=tk.X)
        if subtitulo:
            tk.Label(wrapper, text=subtitulo, font=("Arial", 8, "italic"),
                     bg="#c8e6c9", fg="#555", anchor="w", padx=8).pack(fill=tk.X)

        frame = tk.Frame(wrapper, bg="#eaf4ea", pady=4)
        frame.pack(fill=tk.X, padx=2)
        return frame

    def _clear_placeholder(self, ev, placeholder):
        if ev.widget.get() == placeholder:
            ev.widget.delete(0, tk.END)
            ev.widget.config(fg=COR_TEXTO)

    def _set_placeholder(self, ev, placeholder):
        if not ev.widget.get():
            ev.widget.insert(0, placeholder)
            ev.widget.config(fg="#aaa")

    # ── lógica ────────────────────────────────────────────────────────────

    def _ler_float(self, chave: str) -> float:
        try:
            val = self._entradas[chave].get().strip().replace(",", ".")
            return max(0.0, float(val))
        except ValueError:
            return 0.0

    def _construir_emissao(self) -> Emissao:
        e = Emissao(
            empresa=self._entradas["empresa"].get().strip(),
            cnpj_cpf=self._entradas["cnpj_cpf"].get().strip(),
            ano_referencia=int(self._ler_float("ano_referencia") or 2025),
            e1_estacionario=self._ler_float("e1_estacionario"),
            e1_movel=self._ler_float("e1_movel"),
            e1_processos=self._ler_float("e1_processos"),
            e1_fugitivas=self._ler_float("e1_fugitivas"),
            e2_eletrica=self._ler_float("e2_eletrica"),
            e2_vapor=self._ler_float("e2_vapor"),
            e3_cadeia=self._ler_float("e3_cadeia"),
            e3_transporte=self._ler_float("e3_transporte"),
            e3_residuos=self._ler_float("e3_residuos"),
            cbe_disponiveis=self._ler_float("cbe_disponiveis"),
            crve_disponiveis=self._ler_float("crve_disponiveis"),
        )
        e.calcular()
        usuario = self.master.usuario_atual
        if usuario:
            e.usuario_id = usuario.id
        return e

    def _atualizar_totais(self):
        e = self._construir_emissao()
        self._lbl_e1.config(text=f"Escopo 1: {e.escopo1_total:,.2f} tCO2e")
        self._lbl_e2.config(text=f"Escopo 2: {e.escopo2_total:,.2f} tCO2e")
        self._lbl_e3.config(text=f"Escopo 3: {e.escopo3_total:,.2f} tCO2e")
        self._lbl_total.config(text=f"TOTAL\n{e.total_tco2e:,.2f} tCO2e")

        cor_status = {
            "ISENTO": COR_ISENTO,
            "MONITORAMENTO OBRIGATÓRIO": COR_MONITORA,
            "CONFORMIDADE TOTAL OBRIGATÓRIA": COR_OBRIGATORIO,
        }.get(e.status_conformidade, COR_TEXTO)

        self._lbl_status.config(text=e.status_conformidade, fg=cor_status)

        if e.total_tco2e == 0:
            self._lbl_deficit.config(text="Déficit: —", fg=COR_TEXTO)
        elif e.deficit_tco2e > 0:
            self._lbl_deficit.config(
                text=f"⚠ Déficit: {e.deficit_tco2e:,.2f} tCO2e",
                fg=COR_OBRIGATORIO)
        else:
            self._lbl_deficit.config(
                text=f"✔ Superávit: {abs(e.deficit_tco2e):,.2f} tCO2e",
                fg=COR_ISENTO)

    def _validar(self) -> Emissao | None:
        empresa = self._entradas["empresa"].get().strip()
        ano_txt = self._entradas["ano_referencia"].get().strip()
        if not empresa or empresa in ("", ):
            messagebox.showwarning("Atenção", "Informe a Empresa / Razão Social.")
            return None
        try:
            ano = int(ano_txt)
            if ano < 2000 or ano > 2100:
                raise ValueError
        except ValueError:
            messagebox.showerror("Erro", "Ano de referência inválido (ex: 2025).")
            return None
        return self._construir_emissao()

    def _salvar(self):
        emissao = self._validar()
        if not emissao:
            return
        try:
            import hashlib, json
            payload = {
                "empresa": emissao.empresa,
                "ano": emissao.ano_referencia,
                "total": emissao.total_tco2e,
            }
            emissao.hash_auditoria = hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()

            from app.database.client import get_client
            get_client().table("emissoes_carbono").insert({
                "usuario_id": emissao.usuario_id or None,
                "empresa": emissao.empresa,
                "cnpj_cpf": emissao.cnpj_cpf,
                "ano_referencia": emissao.ano_referencia,
                "e1_estacionario": emissao.e1_estacionario,
                "e1_movel": emissao.e1_movel,
                "e1_processos": emissao.e1_processos,
                "e1_fugitivas": emissao.e1_fugitivas,
                "e2_eletrica": emissao.e2_eletrica,
                "e2_vapor": emissao.e2_vapor,
                "e3_cadeia": emissao.e3_cadeia,
                "e3_transporte": emissao.e3_transporte,
                "e3_residuos": emissao.e3_residuos,
                "total_tco2e": emissao.total_tco2e,
                "cbe_disponiveis": emissao.cbe_disponiveis,
                "crve_disponiveis": emissao.crve_disponiveis,
                "deficit_tco2e": emissao.deficit_tco2e,
                "status_conformidade": emissao.status_conformidade,
                "hash_auditoria": emissao.hash_auditoria,
            }).execute()

            messagebox.showinfo("Salvo", f"Emissão de {emissao.empresa} ({emissao.ano_referencia}) "
                                         f"registrada com sucesso!\nTotal: {emissao.total_tco2e:,.2f} tCO2e")
        except Exception as ex:
            messagebox.showerror("Erro ao Salvar", str(ex))

    def _gerar_pdf(self):
        emissao = self._validar()
        if not emissao:
            return
        try:
            from app.services.pdf import gerar_relatorio_emissoes, salvar_pdf
            import hashlib
            pdf_bytes = gerar_relatorio_emissoes(emissao)
            emissao.hash_auditoria = hashlib.sha256(pdf_bytes).hexdigest()
            pdf_bytes = gerar_relatorio_emissoes(emissao)
            nome = f"emissoes_{emissao.empresa[:20].replace(' ', '_')}_{emissao.ano_referencia}"
            caminho = salvar_pdf(pdf_bytes, nome)
            messagebox.showinfo("PDF Gerado", f"Relatório salvo em:\n{caminho}")
        except Exception as ex:
            messagebox.showerror("Erro ao Gerar PDF", str(ex))
