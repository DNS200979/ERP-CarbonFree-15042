import tkinter as tk
from app.ui.app import (
    COR_FUNDO, COR_VERDE, COR_VERDE_ESCURO, COR_AZUL,
    COR_VERMELHO, COR_CINZA, COR_TEXTO,
)


class TelaPrincipal(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COR_FUNDO)
        self._build()

    def _build(self):
        usuario = self.master.usuario_atual

        tk.Label(
            self, text="MOVIMENTO BRASIL VERDE",
            font=("Arial", 17, "bold"), fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(pady=(35, 4))

        tk.Label(
            self, text="Sistema ERP — Conformidade Ambiental",
            font=("Arial", 10, "italic"), fg="#7f8c8d", bg=COR_FUNDO,
        ).pack()

        tk.Label(
            self, text=f"Bem-vindo(a), {usuario.email if usuario else 'Usuário'}",
            font=("Arial", 11), fg=COR_TEXTO, bg=COR_FUNDO,
        ).pack(pady=(10, 24))

        btn_cfg = dict(font=("Arial", 11, "bold"), width=34, height=2, relief=tk.FLAT, cursor="hand2")

        tk.Button(
            self, text="📄  Emitir Certificado Ambiental",
            command=self.master.ir_para_certificado,
            bg=COR_VERDE, fg="white", **btn_cfg,
        ).pack(pady=5)

        tk.Button(
            self, text="🌿  Registrar Emissões de Carbono",
            command=self.master.ir_para_emissoes,
            bg="#16a085", fg="white", **btn_cfg,
        ).pack(pady=5)

        tk.Button(
            self, text="📥  Importar Emissões via CSV",
            command=self.master.ir_para_importacao,
            bg="#8e44ad", fg="white", **btn_cfg,
        ).pack(pady=5)

        tk.Button(
            self, text="🤖  Motor IA — Cálculo Preciso",
            command=self.master.ir_para_motor_ia,
            bg="#2980b9", fg="white", **btn_cfg,
        ).pack(pady=5)

        tk.Button(
            self, text="🗂  Consultar Histórico",
            command=self.master.ir_para_historico,
            bg=COR_AZUL, fg="white", **btn_cfg,
        ).pack(pady=5)

        tk.Button(
            self, text="⏻  Sair",
            command=self.master.fazer_logout,
            bg=COR_VERMELHO, fg="white", **btn_cfg,
        ).pack(pady=5)
