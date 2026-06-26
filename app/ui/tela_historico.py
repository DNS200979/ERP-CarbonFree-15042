"""
Tela de Histórico — agora usa Treeview clicável para inventários de emissões,
permitindo:
  • CONSULTAR — gerar e abrir o PDF do inventário selecionado
  • EXCLUIR — remover o inventário do banco (com confirmação)
  • ATUALIZAR — recarregar a lista
"""

import os
import platform
import subprocess
import tkinter as tk
from tkinter import messagebox, ttk

from app.ui.app import (
    COR_FUNDO, COR_VERDE, COR_VERDE_ESCURO, COR_AZUL,
    COR_CINZA, COR_VERMELHO, COR_TEXTO,
)


class TelaHistorico(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COR_FUNDO)
        # cache de IDs por aba
        self._certificados: list[dict] = []
        self._emissoes: list[dict] = []
        self._build()
        self._carregar()

    # ── Construção ─────────────────────────────────────────────────────────
    def _build(self):
        topo = tk.Frame(self, bg=COR_FUNDO)
        topo.pack(fill=tk.X, padx=20, pady=(18, 6))

        tk.Label(
            topo, text="Histórico de Documentos",
            font=("Arial", 13, "bold"), fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(side=tk.LEFT)

        tk.Button(
            topo, text="↻ Atualizar", command=self._carregar,
            bg=COR_AZUL, fg="white", font=("Arial", 9, "bold"),
            relief=tk.FLAT, cursor="hand2", padx=8,
        ).pack(side=tk.RIGHT)

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 6))

        # ── Aba 1: Certificados (mantém formato anterior em texto) ────────
        frame_cert = tk.Frame(self._notebook, bg=COR_FUNDO)
        self._notebook.add(frame_cert, text="  Certificados Ambientais  ")
        self._texto_cert = self._criar_texto(frame_cert)

        # ── Aba 2: Emissões — Treeview + botões de ação ───────────────────
        frame_emis = tk.Frame(self._notebook, bg=COR_FUNDO)
        self._notebook.add(frame_emis, text="  Emissões de Carbono  ")
        self._build_aba_emissoes(frame_emis)

        tk.Button(
            self, text="← Voltar", command=self.master.ir_para_principal,
            bg=COR_CINZA, fg="white", font=("Arial", 10, "bold"),
            width=14, height=1, relief=tk.FLAT, cursor="hand2",
        ).pack(pady=(0, 14))

    def _build_aba_emissoes(self, parent):
        # Treeview com inventários
        cont = tk.Frame(parent, bg=COR_FUNDO)
        cont.pack(fill=tk.BOTH, expand=True, padx=4, pady=(6, 4))

        cols = ttk.Treeview(
            cont,
            columns=("id", "empresa", "cnpj", "ano", "total", "deficit", "status"),
            show="headings", height=14,
        )
        cols.heading("id",      text="ID")
        cols.heading("empresa", text="Empresa")
        cols.heading("cnpj",    text="CNPJ/CPF")
        cols.heading("ano",     text="Ano")
        cols.heading("total",   text="Total tCO2e")
        cols.heading("deficit", text="Déficit tCO2e")
        cols.heading("status",  text="Status SBCE")

        cols.column("id",      width=50,  anchor="center")
        cols.column("empresa", width=180, anchor="w")
        cols.column("cnpj",    width=120, anchor="w")
        cols.column("ano",     width=60,  anchor="center")
        cols.column("total",   width=110, anchor="e")
        cols.column("deficit", width=110, anchor="e")
        cols.column("status",  width=180, anchor="w")

        sb = ttk.Scrollbar(cont, orient=tk.VERTICAL, command=cols.yview)
        cols.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        cols.pack(fill=tk.BOTH, expand=True)
        cols.bind("<Double-1>", lambda _e: self._consultar_pdf())
        self._tree_emis = cols

        # Mensagem auxiliar (erros, vazio etc.)
        self._lbl_msg_emis = tk.Label(
            parent, text="", font=("Arial", 9, "italic"),
            fg="#7f8c8d", bg=COR_FUNDO, anchor="w", justify="left",
        )
        self._lbl_msg_emis.pack(fill=tk.X, padx=8)

        # Botões de ação
        frame_btns = tk.Frame(parent, bg=COR_FUNDO)
        frame_btns.pack(fill=tk.X, padx=4, pady=(4, 8))

        tk.Button(
            frame_btns, text="📄 Consultar PDF",
            command=self._consultar_pdf,
            bg=COR_AZUL, fg="white", font=("Arial", 9, "bold"),
            width=18, relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            frame_btns, text="🗑 Excluir Inventário",
            command=self._excluir_emissao,
            bg=COR_VERMELHO, fg="white", font=("Arial", 9, "bold"),
            width=20, relief=tk.FLAT, cursor="hand2",
        ).pack(side=tk.LEFT, padx=4)

        tk.Label(
            frame_btns,
            text="Dica: clique duas vezes em um inventário para abrir o PDF.",
            font=("Arial", 8, "italic"), fg="#95a5a6", bg=COR_FUNDO,
        ).pack(side=tk.RIGHT, padx=4)

    def _criar_texto(self, parent):
        container = tk.Frame(parent, bg=COR_FUNDO)
        container.pack(fill=tk.BOTH, expand=True)
        sb_y = tk.Scrollbar(container)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        sb_x = tk.Scrollbar(container, orient=tk.HORIZONTAL)
        sb_x.pack(side=tk.BOTTOM, fill=tk.X)
        txt = tk.Text(
            container, font=("Courier", 9), bg="#fafffe",
            yscrollcommand=sb_y.set, xscrollcommand=sb_x.set,
            relief=tk.FLAT, wrap=tk.NONE,
        )
        txt.pack(fill=tk.BOTH, expand=True)
        sb_y.config(command=txt.yview)
        sb_x.config(command=txt.xview)
        return txt

    def _escrever(self, widget, texto):
        widget.config(state=tk.NORMAL)
        widget.insert(tk.END, texto)
        widget.config(state=tk.DISABLED)

    def _limpar(self, widget):
        widget.config(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.config(state=tk.DISABLED)

    # ── Carregamento ───────────────────────────────────────────────────────
    def _carregar(self):
        self._carregar_certificados()
        self._carregar_emissoes()

    def _carregar_certificados(self):
        self._limpar(self._texto_cert)
        try:
            from app.database.client import get_client
            resp = (
                get_client()
                .table("documentos_compliance")
                .select("id,calculo_area,calculo_valor_cota,car_local_documento,hash_auditoria")
                .order("id", desc=True)
                .limit(50)
                .execute()
            )
            registros = resp.data or []
            self._certificados = registros
            if not registros:
                self._escrever(self._texto_cert, "  Nenhum certificado encontrado.\n")
                return
            hdr = (
                f"  {'ID':<6}  {'Área (ha)':<12}  {'Valor Cota (R$)':>16}  "
                f"{'Arquivo':<40}  Hash SHA-256\n"
                f"  {'─' * 110}\n"
            )
            self._escrever(self._texto_cert, hdr)
            for reg in registros:
                hash_trecho = (reg.get("hash_auditoria") or "")[:20]
                arquivo = str(reg.get("car_local_documento") or "")
                arquivo_curto = ("..." + arquivo[-37:]) if len(arquivo) > 40 else arquivo
                linha = (
                    f"  {str(reg.get('id', '')):<6}  "
                    f"{str(reg.get('calculo_area', 0)):<12}  "
                    f"R$ {float(reg.get('calculo_valor_cota', 0)):>13,.2f}  "
                    f"{arquivo_curto:<40}  "
                    f"{hash_trecho}...\n"
                )
                self._escrever(self._texto_cert, linha)
        except Exception as e:
            self._limpar(self._texto_cert)
            self._escrever(self._texto_cert, f"  Erro ao carregar certificados:\n  {e}\n")

    def _carregar_emissoes(self):
        # Limpa tree
        for item in self._tree_emis.get_children():
            self._tree_emis.delete(item)
        self._lbl_msg_emis.config(text="")

        try:
            from app.database.client import get_client
            resp = (
                get_client()
                .table("emissoes_carbono")
                .select("*")  # pega todos os campos para gerar PDF
                .order("id", desc=True)
                .limit(100)
                .execute()
            )
            registros = resp.data or []
            self._emissoes = registros

            if not registros:
                self._lbl_msg_emis.config(
                    text="Nenhuma emissão registrada ainda.")
                return

            for reg in registros:
                self._tree_emis.insert("", tk.END, values=(
                    reg.get("id", ""),
                    str(reg.get("empresa") or "")[:40],
                    str(reg.get("cnpj_cpf") or "")[:18],
                    reg.get("ano_referencia", ""),
                    f"{float(reg.get('total_tco2e') or 0):,.4f}",
                    f"{float(reg.get('deficit_tco2e') or 0):,.4f}",
                    str(reg.get("status_conformidade") or ""),
                ))
        except Exception as e:
            erro = str(e)
            msg = f"Erro ao carregar emissões: {erro}"
            if "PGRST205" in erro or "does not exist" in erro.lower():
                msg += "\nCausa: tabela 'emissoes_carbono' não existe — execute o SQL de criação no Supabase."
            self._lbl_msg_emis.config(text=msg, fg=COR_VERMELHO)

    # ── Ações: CONSULTA PDF ───────────────────────────────────────────────
    def _registro_selecionado(self) -> dict | None:
        sel = self._tree_emis.selection()
        if not sel:
            messagebox.showwarning(
                "Atenção", "Selecione um inventário na lista primeiro.")
            return None
        valores = self._tree_emis.item(sel[0], "values")
        try:
            id_alvo = int(valores[0])
        except (ValueError, IndexError):
            return None
        for reg in self._emissoes:
            if int(reg.get("id", -1)) == id_alvo:
                return reg
        return None

    def _consultar_pdf(self):
        reg = self._registro_selecionado()
        if not reg:
            return
        try:
            # Reconstrói objeto Emissao a partir do registro do banco
            from app.models.emissao import Emissao
            emissao = Emissao(
                empresa=reg.get("empresa") or "",
                cnpj_cpf=reg.get("cnpj_cpf") or "",
                ano_referencia=int(reg.get("ano_referencia") or 2025),
                e1_estacionario=float(reg.get("e1_estacionario") or 0),
                e1_movel=float(reg.get("e1_movel") or 0),
                e1_processos=float(reg.get("e1_processos") or 0),
                e1_fugitivas=float(reg.get("e1_fugitivas") or 0),
                e2_eletrica=float(reg.get("e2_eletrica") or 0),
                e2_vapor=float(reg.get("e2_vapor") or 0),
                e3_cadeia=float(reg.get("e3_cadeia") or 0),
                e3_transporte=float(reg.get("e3_transporte") or 0),
                e3_residuos=float(reg.get("e3_residuos") or 0),
                cbe_disponiveis=float(reg.get("cbe_disponiveis") or 0),
                crve_disponiveis=float(reg.get("crve_disponiveis") or 0),
            )
            emissao.calcular()
            emissao.hash_auditoria = reg.get("hash_auditoria") or ""

            from app.services.pdf import gerar_relatorio_emissoes, salvar_pdf
            pdf_bytes = gerar_relatorio_emissoes(emissao)
            nome = (
                f"inventario_{reg.get('id')}_"
                f"{(emissao.empresa or 'empresa')[:20].replace(' ', '_')}_"
                f"{emissao.ano_referencia}"
            )
            caminho = salvar_pdf(pdf_bytes, nome)

            # Abre o PDF no visualizador padrão do SO
            self._abrir_arquivo(caminho)
            messagebox.showinfo(
                "PDF gerado",
                f"O inventário foi gerado e aberto.\n\nArquivo:\n{caminho}",
            )
        except Exception as e:
            messagebox.showerror(
                "Erro ao gerar PDF",
                f"Não foi possível gerar/abrir o PDF do inventário.\n\n{e}",
            )

    def _abrir_arquivo(self, caminho: str):
        try:
            so = platform.system().lower()
            if "windows" in so:
                os.startfile(caminho)  # type: ignore[attr-defined]
            elif "darwin" in so:
                subprocess.Popen(["open", caminho])
            else:
                subprocess.Popen(["xdg-open", caminho])
        except Exception:
            # Falha silenciosa: usuário ainda recebe o caminho via messagebox
            pass

    # ── Ações: EXCLUSÃO ───────────────────────────────────────────────────
    def _excluir_emissao(self):
        reg = self._registro_selecionado()
        if not reg:
            return

        confirm = messagebox.askyesno(
            "Excluir Inventário",
            f"Deseja realmente excluir o inventário abaixo?\n\n"
            f"  ID: {reg.get('id')}\n"
            f"  Empresa: {reg.get('empresa')}\n"
            f"  Ano: {reg.get('ano_referencia')}\n"
            f"  Total: {float(reg.get('total_tco2e') or 0):,.4f} tCO2e\n\n"
            f"Esta ação NÃO pode ser desfeita.",
            icon="warning",
        )
        if not confirm:
            return

        try:
            from app.database.client import get_client
            get_client().table("emissoes_carbono").delete().eq("id", reg["id"]).execute()
            messagebox.showinfo(
                "Excluído",
                f"Inventário ID {reg.get('id')} removido com sucesso.",
            )
            self._carregar_emissoes()
        except Exception as e:
            messagebox.showerror(
                "Erro ao excluir",
                f"Não foi possível remover o inventário.\n\n{e}",
            )
