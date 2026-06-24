import tkinter as tk
from app.models.usuario import Usuario

# Paleta de cores MBV
COR_FUNDO        = "#f0f4f0"
COR_VERDE        = "#2ecc71"
COR_VERDE_ESCURO = "#27ae60"
COR_AZUL         = "#3498db"
COR_CINZA        = "#95a5a6"
COR_VERMELHO     = "#e74c3c"
COR_TEXTO        = "#2c3e50"

FONTE_TITULO  = ("Arial", 14, "bold")
FONTE_NORMAL  = ("Arial", 11)
FONTE_PEQUENA = ("Arial", 9)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(" ERP CarbonFree 15.042 by DNS-TI")
        self.geometry("860x640")
        self.resizable(False, False)
        self.configure(bg=COR_FUNDO)

        self.usuario_atual: Usuario | None = None
        self._frame: tk.Frame | None = None
        self._campos_ia_pendentes: dict | None = None

        self._ir_para("login")

    # ── navegação ──────────────────────────────────────────────────────────
    def _ir_para(self, destino: str, **kwargs):
        if self._frame:
            self._frame.destroy()

        match destino:
            case "login":
                from app.ui.tela_login import TelaLogin
                self._frame = TelaLogin(self)
            case "principal":
                from app.ui.tela_principal import TelaPrincipal
                self._frame = TelaPrincipal(self)
            case "certificado":
                from app.ui.tela_certificado import TelaCertificado
                self._frame = TelaCertificado(self)
            case "historico":
                from app.ui.tela_historico import TelaHistorico
                self._frame = TelaHistorico(self)
            case "emissoes":
                from app.ui.tela_emissoes import TelaEmissoes
                self._frame = TelaEmissoes(self, campos_ia=kwargs.get("campos_ia"))
            case "importacao":
                from app.ui.tela_importacao import TelaImportacao
                self._frame = TelaImportacao(self)
            case "motor_ia":
                from app.ui.tela_motor_ia import TelaMotorIA
                self._frame = TelaMotorIA(self)
            case _:
                raise ValueError(f"Destino desconhecido: {destino}")

        self._frame.pack(fill=tk.BOTH, expand=True)

    # ── ações públicas chamadas pelas telas ────────────────────────────────
    def registrar_login(self, usuario: Usuario):
        self.usuario_atual = usuario
        self._ir_para("principal")

    def ir_para_certificado(self):
        self._ir_para("certificado")

    def ir_para_historico(self):
        self._ir_para("historico")

    def ir_para_emissoes(self):
        self._ir_para("emissoes")

    def ir_para_importacao(self):
        self._ir_para("importacao")

    def ir_para_motor_ia(self):
        self._ir_para("motor_ia")

    def ir_para_emissoes_preenchidas(self, campos: dict, total: float):
        self._ir_para("emissoes", campos_ia=campos)

    def ir_para_principal(self):
        self._ir_para("principal")

    def fazer_logout(self):
        try:
            from app.database.client import get_client
            get_client().auth.sign_out()
        except Exception:
            pass
        self.usuario_atual = None
        self._ir_para("login")
