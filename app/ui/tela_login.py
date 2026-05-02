import tkinter as tk
from tkinter import messagebox
from app.ui.app import (
    COR_FUNDO, COR_VERDE, COR_VERDE_ESCURO, COR_AZUL, COR_TEXTO,
    FONTE_NORMAL, FONTE_PEQUENA,
)
from app.models.usuario import Usuario


class TelaLogin(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=COR_FUNDO)
        self._build()

    def _build(self):
        tk.Label(
            self, text="ERP CarbonFree 15.042 by DNS-TI",
            font=("Arial", 17, "bold"), fg=COR_VERDE_ESCURO, bg=COR_FUNDO,
        ).pack(pady=(40, 4))

        tk.Label(
            self, text="Sistema de Conformidade Ambiental",
            font=("Arial", 10, "italic"), fg="#7f8c8d", bg=COR_FUNDO,
        ).pack(pady=(0, 30))

        form = tk.Frame(self, bg=COR_FUNDO)
        form.pack()

        tk.Label(form, text="E-mail:", font=FONTE_NORMAL, bg=COR_FUNDO, fg=COR_TEXTO).grid(
            row=0, column=0, sticky="e", pady=10, padx=(0, 10))
        self._email = tk.Entry(form, width=34, font=FONTE_NORMAL)
        self._email.grid(row=0, column=1, pady=10)

        tk.Label(form, text="Senha:", font=FONTE_NORMAL, bg=COR_FUNDO, fg=COR_TEXTO).grid(
            row=1, column=0, sticky="e", pady=10, padx=(0, 10))
        self._senha = tk.Entry(form, width=34, font=FONTE_NORMAL, show="•")
        self._senha.grid(row=1, column=1, pady=10)
        self._senha.bind("<Return>", lambda _: self._entrar())

        # Botões principais
        btn_frame = tk.Frame(self, bg=COR_FUNDO)
        btn_frame.pack(pady=20)

        tk.Button(
            btn_frame, text="ENTRAR", command=self._entrar,
            bg=COR_VERDE, fg="white", font=("Arial", 11, "bold"),
            width=18, height=2, relief=tk.FLAT, cursor="hand2",
        ).grid(row=0, column=0, padx=6)

        tk.Button(
            btn_frame, text="CRIAR CONTA", command=self._criar_conta,
            bg=COR_AZUL, fg="white", font=("Arial", 11, "bold"),
            width=18, height=2, relief=tk.FLAT, cursor="hand2",
        ).grid(row=0, column=1, padx=6)

        tk.Label(
            self,
            text="Use o mesmo e-mail e senha para entrar e criar conta.",
            font=FONTE_PEQUENA, fg="#aab7b8", bg=COR_FUNDO,
        ).pack()

        tk.Button(
            self, text="Esqueci minha senha", command=self._recuperar_senha,
            bg=COR_FUNDO, fg="#7f8c8d", font=("Arial", 9, "underline"),
            relief=tk.FLAT, cursor="hand2", bd=0,
        ).pack(pady=(8, 0))

    # ── autenticação ───────────────────────────────────────────────────────

    def _entrar(self):
        email, senha = self._email.get().strip(), self._senha.get().strip()
        if not email or not senha:
            messagebox.showwarning("Atenção", "Preencha e-mail e senha.")
            return
        try:
            from app.database.client import get_client
            resp = get_client().auth.sign_in_with_password({"email": email, "password": senha})
            self.master.registrar_login(Usuario(id=resp.user.id, email=resp.user.email or email))
        except Exception as e:
            messagebox.showerror("Erro ao Entrar", f"Não foi possível entrar.\n\n{e}")

    def _recuperar_senha(self):
        email = self._email.get().strip()
        if not email:
            messagebox.showwarning("Atenção", "Digite seu e-mail no campo acima antes de recuperar a senha.")
            return
        try:
            from app.database.client import get_client
            get_client().auth.reset_password_for_email(email)
            messagebox.showinfo(
                "E-mail Enviado",
                f"Se o e-mail '{email}' estiver cadastrado,\n"
                f"você receberá um link para redefinir sua senha.\n\n"
                f"Verifique também a pasta de spam.",
            )
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível enviar o e-mail.\n\n{e}")

    def _criar_conta(self):
        email, senha = self._email.get().strip(), self._senha.get().strip()
        if not email or not senha:
            messagebox.showwarning("Atenção", "Preencha e-mail e senha antes de criar a conta.")
            return
        if len(senha) < 6:
            messagebox.showwarning("Senha fraca", "A senha deve ter pelo menos 6 caracteres.")
            return
        try:
            from app.database.client import get_client, get_admin_client
            admin = get_admin_client()

            if admin:
                # Com service role key: cria o usuário já confirmado, sem enviar e-mail
                resp = admin.auth.admin.create_user({
                    "email": email,
                    "password": senha,
                    "email_confirm": True,
                })
                if resp.user:
                    # Faz login imediato com as credenciais recém-criadas
                    login = get_client().auth.sign_in_with_password({"email": email, "password": senha})
                    self.master.registrar_login(Usuario(id=login.user.id, email=login.user.email or email))
                return

            # Sem service key: usa o fluxo padrão (pode pedir confirmação de e-mail)
            resp = get_client().auth.sign_up({"email": email, "password": senha})

            if resp.session and resp.user:
                # Confirmação desativada no Supabase → entra direto
                self.master.registrar_login(Usuario(id=resp.user.id, email=resp.user.email or email))
                return

            if resp.user:
                messagebox.showinfo(
                    "Verifique seu E-mail",
                    f"Conta criada para '{email}'.\n\n"
                    f"Confirme o e-mail recebido e depois clique em ENTRAR.\n\n"
                    f"Para evitar isso, adicione a SUPABASE_SERVICE_KEY no arquivo .env\n"
                    f"(Settings → API → service_role no painel do Supabase).",
                )

        except Exception as e:
            erro = str(e)
            if "already registered" in erro or "already been registered" in erro:
                messagebox.showwarning("E-mail já cadastrado", "Esse e-mail já possui conta. Use ENTRAR ou recupere a senha.")
            elif "rate limit" in erro.lower():
                messagebox.showerror(
                    "Limite de E-mails Atingido",
                    "O Supabase bloqueou o envio de e-mails temporariamente.\n\n"
                    "Solução: adicione a SUPABASE_SERVICE_KEY no arquivo .env\n"
                    "para criar contas sem precisar de e-mail.\n\n"
                    "Onde encontrar: Supabase → Settings → API → service_role",
                )
            else:
                messagebox.showerror("Erro ao Criar Conta", f"Não foi possível criar a conta.\n\n{e}")
