"""
Módulo 1 — Importação automatizada de dados de emissões via CSV.
Permite carregar planilhas e inserir em lote na tabela emissoes_carbono.
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.ui.app import (
    COR_FUNDO, COR_VERDE, COR_VERDE_ESCURO, COR_AZUL,
    COR_CINZA, COR_TEXTO, FONTE_NORMAL,
)
from app.services.importacao import parse_csv, importar_para_supabase, TEMPLATE_CSV


class TelaImportacao(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COR_FUNDO)
        self._arquivo_path: str | None = None
        self._registros_parseados: list[dict] = []
        self._build()

    def _build(self):
        tk.Label(
            self, text="Importação de Emissões — CSV",
            font=("Arial", 13, "bold"), fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(pady=(20, 4))

        tk.Label(
            self,
            text="Carregue um arquivo CSV com os dados de emissões para importação em lote.",
            font=("Arial", 9, "italic"), fg="#7f8c8d", bg=COR_FUNDO,
        ).pack(pady=(0, 14))

        # Seleção de arquivo
        frame_sel = tk.Frame(self, bg=COR_FUNDO)
        frame_sel.pack(padx=30, fill=tk.X)

        tk.Label(frame_sel, text="Arquivo CSV:", font=FONTE_NORMAL, bg=COR_FUNDO, fg=COR_TEXTO).grid(
            row=0, column=0, sticky="w", pady=6)

        self._label_arquivo = tk.Label(
            frame_sel, text="Nenhum arquivo selecionado",
            font=("Arial", 9), fg="#7f8c8d", bg=COR_FUNDO, anchor="w",
        )
        self._label_arquivo.grid(row=0, column=1, sticky="w", padx=8)

        tk.Button(
            frame_sel, text="Selecionar arquivo…", command=self._selecionar_arquivo,
            bg=COR_AZUL, fg="white", font=("Arial", 9, "bold"),
            relief=tk.FLAT, cursor="hand2", padx=8,
        ).grid(row=0, column=2, padx=(8, 0))

        tk.Button(
            frame_sel, text="Baixar template CSV", command=self._baixar_template,
            bg="#8e44ad", fg="white", font=("Arial", 9, "bold"),
            relief=tk.FLAT, cursor="hand2", padx=8,
        ).grid(row=0, column=3, padx=(8, 0))

        # Área de prévia
        tk.Label(
            self, text="Prévia dos dados:", font=("Arial", 10, "bold"),
            fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(anchor="w", padx=30, pady=(16, 4))

        frame_txt = tk.Frame(self, bg=COR_FUNDO)
        frame_txt.pack(fill=tk.BOTH, expand=True, padx=30)

        sb_y = tk.Scrollbar(frame_txt)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        sb_x = tk.Scrollbar(frame_txt, orient=tk.HORIZONTAL)
        sb_x.pack(side=tk.BOTTOM, fill=tk.X)

        self._texto = tk.Text(
            frame_txt, font=("Courier", 9), bg="#fafffe",
            yscrollcommand=sb_y.set, xscrollcommand=sb_x.set,
            relief=tk.FLAT, wrap=tk.NONE, height=14,
        )
        self._texto.pack(fill=tk.BOTH, expand=True)
        sb_y.config(command=self._texto.yview)
        sb_x.config(command=self._texto.xview)

        self._label_status = tk.Label(
            self, text="", font=("Arial", 9), fg="#27ae60", bg=COR_FUNDO,
        )
        self._label_status.pack(pady=(4, 0))

        # Botões de ação
        btn_frame = tk.Frame(self, bg=COR_FUNDO)
        btn_frame.pack(pady=14)

        self._btn_importar = tk.Button(
            btn_frame, text="IMPORTAR DADOS",
            command=self._importar,
            bg=COR_VERDE, fg="white", font=("Arial", 10, "bold"),
            width=20, height=2, relief=tk.FLAT, cursor="hand2",
            state=tk.DISABLED,
        )
        self._btn_importar.grid(row=0, column=0, padx=8)

        tk.Button(
            btn_frame, text="← Voltar", command=self.master.ir_para_principal,
            bg=COR_CINZA, fg="white", font=("Arial", 10, "bold"),
            width=12, height=2, relief=tk.FLAT, cursor="hand2",
        ).grid(row=0, column=1, padx=8)

    def _selecionar_arquivo(self):
        path = filedialog.askopenfilename(
            title="Selecionar arquivo CSV",
            filetypes=[("Arquivo CSV", "*.csv"), ("Todos os arquivos", "*.*")],
        )
        if not path:
            return
        self._arquivo_path = path
        self._label_arquivo.config(text=os.path.basename(path), fg=COR_TEXTO)
        self._processar_arquivo()

    def _processar_arquivo(self):
        try:
            with open(self._arquivo_path, "rb") as f:
                conteudo = f.read()
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível ler o arquivo.\n{e}")
            return

        registros, erros = parse_csv(conteudo)
        self._registros_parseados = registros

        self._texto.config(state=tk.NORMAL)
        self._texto.delete("1.0", tk.END)

        if not registros and erros:
            self._texto.insert(tk.END, "ERROS ENCONTRADOS — Nenhum registro válido:\n\n")
            for e in erros:
                self._texto.insert(tk.END, f"  • {e}\n")
            self._btn_importar.config(state=tk.DISABLED)
            self._label_status.config(
                text=f"0 registros válidos | {len(erros)} erros", fg="#e74c3c")
        else:
            hdr = (
                f"  {'#':<4}  {'Empresa':<28}  {'CNPJ':<16}  {'Ano':<6}  "
                f"{'Total tCO2e':>14}  Status\n"
                f"  {'─'*90}\n"
            )
            self._texto.insert(tk.END, hdr)
            for i, reg in enumerate(registros, 1):
                linha = (
                    f"  {i:<4}  "
                    f"{str(reg.get('empresa',''))[:26]:<28}  "
                    f"{str(reg.get('cnpj_cpf',''))[:14]:<16}  "
                    f"{reg.get('ano_referencia', 0):<6}  "
                    f"{float(reg.get('total_tco2e', 0)):>14,.4f}  "
                    f"{reg.get('status_conformidade','')}\n"
                )
                self._texto.insert(tk.END, linha)
            if erros:
                self._texto.insert(tk.END, f"\n  AVISOS ({len(erros)}):\n")
                for e in erros[:5]:
                    self._texto.insert(tk.END, f"  • {e}\n")
            self._btn_importar.config(state=tk.NORMAL)
            self._label_status.config(
                text=f"{len(registros)} registros válidos | {len(erros)} avisos",
                fg="#27ae60" if not erros else "#e67e22",
            )

        self._texto.config(state=tk.DISABLED)

    def _importar(self):
        if not self._registros_parseados:
            return

        confirmacao = messagebox.askyesno(
            "Confirmar Importação",
            f"Deseja importar {len(self._registros_parseados)} registro(s) para o banco de dados?",
        )
        if not confirmacao:
            return

        try:
            from app.database.client import get_client
            usuario = self.master.usuario_atual
            uid = usuario.id if usuario else None
            resultado = importar_para_supabase(
                self._registros_parseados, uid, get_client()
            )
        except Exception as e:
            messagebox.showerror("Erro", f"Falha na importação.\n{e}")
            return

        messagebox.showinfo("Importação Concluída", resultado.resumo())
        if resultado.sucesso:
            self._registros_parseados = []
            self._arquivo_path = None
            self._label_arquivo.config(text="Nenhum arquivo selecionado", fg="#7f8c8d")
            self._texto.config(state=tk.NORMAL)
            self._texto.delete("1.0", tk.END)
            self._texto.config(state=tk.DISABLED)
            self._btn_importar.config(state=tk.DISABLED)
            self._label_status.config(text="")

    def _baixar_template(self):
        path = filedialog.asksaveasfilename(
            title="Salvar template CSV",
            defaultextension=".csv",
            initialfile="template_emissoes_mbv.csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write(TEMPLATE_CSV)
            messagebox.showinfo("Template Salvo", f"Template salvo em:\n{path}")
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível salvar.\n{e}")
