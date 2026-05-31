from dataclasses import dataclass, field


@dataclass
class Emissao:
    empresa: str
    cnpj_cpf: str
    ano_referencia: int

    # Categoria econômica da empresa (define o perfil setorial usado no
    # cálculo por balanço). Ex.: "construcao_civil", "transporte_logistica",
    # "agronegocio". Ver PERFIS_SETORIAIS em app/services/motor_ia.py.
    categoria: str = ""

    # Método de origem do inventário: "atividade" | "balanco" | "misto" | "manual"
    metodo_calculo: str = "manual"

    # Escopo 1 — Emissões Diretas (tCO2e)
    e1_estacionario: float = 0.0   # combustíveis em caldeiras, fornos, geradores
    e1_movel: float = 0.0          # frota própria
    e1_processos: float = 0.0      # processos industriais
    e1_fugitivas: float = 0.0      # vazamentos, refrigeração

    # Escopo 2 — Energia Indireta (tCO2e)
    e2_eletrica: float = 0.0       # energia elétrica comprada
    e2_vapor: float = 0.0          # vapor/calor comprado

    # Escopo 3 — Outras Indiretas (tCO2e)
    e3_cadeia: float = 0.0         # cadeia de fornecimento
    e3_transporte: float = 0.0     # transporte e distribuição
    e3_residuos: float = 0.0       # tratamento de resíduos

    # Dados de balanço declarados (R$) — guardados para auditoria/rastreio
    # quando o inventário é calculado pelo método "balanco".
    faturamento_bruto: float = 0.0
    gasto_combustivel: float = 0.0
    gasto_energia_eletrica: float = 0.0
    compras_insumos: float = 0.0

    # Ativos de carbono disponíveis
    cbe_disponiveis: float = 0.0   # Cotas Brasileiras de Emissão
    crve_disponiveis: float = 0.0  # Certificados de Redução/Remoção Verificada

    # Calculados
    total_tco2e: float = 0.0
    deficit_tco2e: float = 0.0     # > 0 = passivo (CBE); < 0 = superávit (gera/sobra CRVE)
    status_conformidade: str = ""
    hash_auditoria: str = ""
    usuario_id: str = ""

    def calcular(self):
        escopo1 = self.e1_estacionario + self.e1_movel + self.e1_processos + self.e1_fugitivas
        escopo2 = self.e2_eletrica + self.e2_vapor
        escopo3 = self.e3_cadeia + self.e3_transporte + self.e3_residuos
        self.total_tco2e = round(escopo1 + escopo2 + escopo3, 4)

        # Balanço de carbono: emissões líquidas menos ativos detidos.
        # deficit > 0  → precisa adquirir CBE para conciliar (passivo)
        # deficit < 0  → superávit; potencial de gerar/vender CRVE
        ativos = self.cbe_disponiveis + self.crve_disponiveis
        self.deficit_tco2e = round(self.total_tco2e - ativos, 4)

        if self.total_tco2e < 10_000:
            self.status_conformidade = "ISENTO"
        elif self.total_tco2e <= 25_000:
            self.status_conformidade = "MONITORAMENTO OBRIGATÓRIO"
        else:
            self.status_conformidade = "CONFORMIDADE TOTAL OBRIGATÓRIA"

        return self

    @property
    def escopo1_total(self) -> float:
        return self.e1_estacionario + self.e1_movel + self.e1_processos + self.e1_fugitivas

    @property
    def escopo2_total(self) -> float:
        return self.e2_eletrica + self.e2_vapor

    @property
    def escopo3_total(self) -> float:
        return self.e3_cadeia + self.e3_transporte + self.e3_residuos

    @property
    def superavit_tco2e(self) -> float:
        """Excedente de ativos sobre emissões (potencial de CRVE). 0 se houver déficit."""
        return round(max(0.0, -self.deficit_tco2e), 4)

    @property
    def passivo_cbe_tco2e(self) -> float:
        """Passivo a conciliar com CBE. 0 se houver superávit."""
        return round(max(0.0, self.deficit_tco2e), 4)
