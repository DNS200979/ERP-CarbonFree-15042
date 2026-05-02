import tkinter as tk
from tkinter import ttk

from app.ui.app import (
    COR_FUNDO, COR_VERDE_ESCURO, COR_AZUL, COR_CINZA, COR_TEXTO,
)


class TelaHistorico(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COR_FUNDO)
        self._build()
        self._carregar()

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

        frame_cert = tk.Frame(self._notebook, bg=COR_FUNDO)
        self._notebook.add(frame_cert, text="  Certificados Ambientais  ")
        self._texto_cert = self._criar_texto(frame_cert)

        frame_emis = tk.Frame(self._notebook, bg=COR_FUNDO)
        self._notebook.add(frame_emis, text="  Emissões de Carbono  ")
        self._texto_emis = self._criar_texto(frame_emis)

        tk.Button(
            self, text="← Voltar", command=self.master.ir_para_principal,
            bg=COR_CINZA, fg="white", font=("Arial", 10, "bold"),
            width=14, height=1, relief=tk.FLAT, cursor="hand2",
        ).pack(pady=(0, 14))

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
            if not registros:
                self._escrever(self._texto_cert, "  Nenhum certificado encontrado.\n")
                return
            hdr = (
                f"  {'ID':<6}  {'Área (ha)':<12}  {'Valor Cota (R$)':>16}  "
                f"{'Arquivo':<40}  Hash SHA-256\n"
                f"  {'─'*110}\n"
            )
            self._escrever(self._texto_cert, hdr)
            for reg in registros:
                hash_trecho = (reg.get("hash_auditoria") or "")[:20]
                arquivo = str(reg.get("car_local_documento") or "")
                arquivo_curto = ("..." + arquivo[-37:]) if len(arquivo) > 40 else arquivo
                linha = (
                    f"  {str(reg.get('id','')):<6}  "
                    f"{str(reg.get('calculo_area', 0)):<12}  "
                    f"R$ {float(reg.get('calculo_valor_cota', 0)):>13,.2f}  "
                    f"{arquivo_curto:<40}  "
                    f"{hash_trecho}...\n"
                )
                self._escrever(self._texto_cert, linha)
        except Exception as e:
            self._limpar(self._texto_cert)
            erro = str(e)
            msg = f"  Erro ao carregar certificados:\n  {erro}\n\n"
            if "42501" in erro or "row-level security" in erro.lower():
                msg += (
                    "  CAUSA: Política RLS bloqueando registros com usuario_id NULL.\n\n"
                    "  SOLUÇÃO — Execute no Supabase SQL Editor:\n\n"
                    "  DROP POLICY IF EXISTS \"ver proprios documentos\" ON documentos_compliance;\n"
                    "  CREATE POLICY \"ver proprios documentos\"\n"
                    "    ON documentos_compliance FOR SELECT TO authenticated\n"
                    "    USING (usuario_id = auth.uid() OR usuario_id IS NULL);\n"
                )
            self._escrever(self._texto_cert, msg)

    def _carregar_emissoes(self):
        self._limpar(self._texto_emis)
        try:
            from app.database.client import get_client
            resp = (
                get_client()
                .table("emissoes_carbono")
                .select("id,empresa,cnpj_cpf,ano_referencia,total_tco2e,status_conformidade,deficit_tco2e")
                .order("id", desc=True)
                .limit(50)
                .execute()
            )
            registros = resp.data or []
            if not registros:
                self._escrever(self._texto_emis, "  Nenhuma emissão registrada.\n")
                return
            hdr = (
                f"  {'ID':<6}  {'Empresa':<28}  {'CNPJ/CPF':<16}  "
                f"{'Ano':<6}  {'Total tCO2e':>14}  {'Déficit tCO2e':>14}  Status\n"
                f"  {'─'*115}\n"
            )
            self._escrever(self._texto_emis, hdr)
            for reg in registros:
                empresa = str(reg.get("empresa") or "")[:26]
                cnpj = str(reg.get("cnpj_cpf") or "")[:14]
                status = str(reg.get("status_conformidade") or "")
                total = float(reg.get("total_tco2e") or 0)
                deficit = float(reg.get("deficit_tco2e") or 0)
                linha = (
                    f"  {str(reg.get('id','')):<6}  "
                    f"{empresa:<28}  "
                    f"{cnpj:<16}  "
                    f"{str(reg.get('ano_referencia','')):<6}  "
                    f"{total:>14,.4f}  "
                    f"{deficit:>14,.4f}  "
                    f"{status}\n"
                )
                self._escrever(self._texto_emis, linha)
        except Exception as e:
            self._limpar(self._texto_emis)
            erro = str(e)
            msg = f"  Erro ao carregar emissões:\n  {erro}\n\n"
            if "PGRST205" in erro or "does not exist" in erro.lower():
                msg += (
                    "  CAUSA: Tabela 'emissoes_carbono' não existe no banco.\n\n"
                    "  SOLUÇÃO — Execute o SQL de criação no Supabase SQL Editor.\n"
                )
            self._escrever(self._texto_emis, msg)
