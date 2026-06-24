import hashlib
import uuid
import tkinter as tk
from tkinter import messagebox, ttk

from app.ui.app import (
    COR_FUNDO, COR_VERDE, COR_VERDE_ESCURO, COR_CINZA, COR_TEXTO,
    FONTE_NORMAL, FONTE_PEQUENA,
)
from app.config import BIOMAS, ATIVIDADES
from app.models.certificado import Certificado
from app.services.calculo import calcular_cota_carbono
from app.services.pdf import gerar_pdf, salvar_pdf


class TelaCertificado(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COR_FUNDO)
        self._build()

    def _build(self):
        tk.Label(
            self, text="Emissão de Certificado Ambiental",
            font=("Arial", 13, "bold"), fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(pady=(20, 15))

        form = tk.Frame(self, bg=COR_FUNDO)
        form.pack(padx=50)

        campos = [
            ("Titular / Razão Social:", "entry"),
            ("Área Preservada (Hectares):", "entry"),
            ("Bioma:", "combo_bioma"),
            ("Atividade:", "combo_atividade"),
        ]

        self._titular   = self._campo(form, "Titular / Razão Social:", 0, "entry")
        self._area      = self._campo(form, "Área Preservada (Hectares):", 1, "entry")
        self._bioma     = self._campo(form, "Bioma:", 2, "combo", list(BIOMAS.keys()))
        self._atividade = self._campo(form, "Atividade:", 3, "combo", list(ATIVIDADES.keys()))

        # Painel de prévia do cálculo
        self._label_previa = tk.Label(
            self, text="", font=("Arial", 10), fg="#27ae60", bg=COR_FUNDO,
        )
        self._label_previa.pack(pady=(6, 0))

        self._bioma.bind("<<ComboboxSelected>>", lambda _: self._atualizar_previa())
        self._atividade.bind("<<ComboboxSelected>>", lambda _: self._atualizar_previa())
        self._area.bind("<KeyRelease>", lambda _: self._atualizar_previa())

        # Botões
        btn_frame = tk.Frame(self, bg=COR_FUNDO)
        btn_frame.pack(pady=18)

        tk.Button(
            btn_frame, text="GERAR CERTIFICADO", command=self._gerar,
            bg=COR_VERDE, fg="white", font=("Arial", 10, "bold"),
            width=22, height=2, relief=tk.FLAT, cursor="hand2",
        ).grid(row=0, column=0, padx=8)

        tk.Button(
            btn_frame, text="← Voltar", command=self.master.ir_para_principal,
            bg=COR_CINZA, fg="white", font=("Arial", 10, "bold"),
            width=12, height=2, relief=tk.FLAT, cursor="hand2",
        ).grid(row=0, column=1, padx=8)

    def _campo(self, parent, label: str, row: int, tipo: str, opcoes=None):
        tk.Label(parent, text=label, font=FONTE_NORMAL, bg=COR_FUNDO, fg=COR_TEXTO, anchor="w").grid(
            row=row, column=0, sticky="w", pady=7, padx=(0, 12))
        if tipo == "entry":
            widget = tk.Entry(parent, width=38, font=FONTE_NORMAL)
        else:
            widget = ttk.Combobox(parent, values=opcoes, width=36, state="readonly", font=FONTE_NORMAL)
        widget.grid(row=row, column=1, pady=7)
        return widget

    def _atualizar_previa(self):
        try:
            area = float(self._area.get().replace(",", "."))
            bioma = self._bioma.get()
            atividade = self._atividade.get()
            if not bioma or not atividade or area <= 0:
                self._label_previa.config(text="")
                return
            c = calcular_cota_carbono(area, bioma, atividade)
            self._label_previa.config(
                text=f"Prévia: área útil {c['area_util']:.2f} ha → "
                     f"R$ {c['valor_cota']:,.2f}"
            )
        except ValueError:
            self._label_previa.config(text="")

    def _gerar(self):
        titular   = self._titular.get().strip()
        area_txt  = self._area.get().strip()
        bioma     = self._bioma.get()
        atividade = self._atividade.get()

        if not all([titular, area_txt, bioma, atividade]):
            messagebox.showwarning("Atenção", "Preencha todos os campos.")
            return

        try:
            area = float(area_txt.replace(",", "."))
            if area <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Erro", "Área deve ser um número positivo (ex: 16.5).")
            return

        calculo = calcular_cota_carbono(area, bioma, atividade)
        codigo  = str(uuid.uuid4()).split("-")[0].upper()

        cert = Certificado(
            codigo=codigo,
            titular=titular,
            area_hectares=area,
            bioma=bioma,
            atividade=atividade,
            percentual_bioma=calculo["percentual_bioma"],
            valor_cota=calculo["valor_cota"],
            descricao_atividade=calculo["descricao"],
        )

        try:
            # 1ª geração sem hash para calcular o SHA-256
            pdf_bytes         = gerar_pdf(cert)
            cert.hash_sha256  = hashlib.sha256(pdf_bytes).hexdigest()
            # 2ª geração incluindo o hash no bloco de autenticidade
            pdf_bytes         = gerar_pdf(cert)
            cert.caminho_pdf  = salvar_pdf(pdf_bytes, codigo)

            self._salvar_supabase(cert)
            self._limpar()

            messagebox.showinfo(
                "Certificado Gerado",
                f"Código: {codigo}\n"
                f"Bioma: {bioma} (Reserva Legal: {calculo['percentual_bioma']*100:.0f}%)\n"
                f"Área útil: {calculo['area_util']:.2f} ha\n"
                f"Valor cota-carbono: R$ {calculo['valor_cota']:,.2f}\n\n"
                f"PDF salvo em:\n{cert.caminho_pdf}",
            )
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível gerar o certificado.\n\n{e}")

    def _salvar_supabase(self, cert: Certificado):
        from app.database.client import get_client
        usuario = self.master.usuario_atual
        dados = {
            "usuario_id": usuario.id if usuario else None,
            "pessoa_id": 1,
            "calculo_area": cert.area_hectares,
            "calculo_valor_cota": cert.valor_cota,
            "car_local_documento": cert.caminho_pdf,
            "hash_auditoria": cert.hash_sha256,
        }
        get_client().table("documentos_compliance").insert(dados).execute()

    def _limpar(self):
        self._titular.delete(0, tk.END)
        self._area.delete(0, tk.END)
        self._bioma.set("")
        self._atividade.set("")
        self._label_previa.config(text="")
