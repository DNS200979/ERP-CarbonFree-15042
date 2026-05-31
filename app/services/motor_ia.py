"""
Módulo 2 — Motor de IA para cálculo preciso de emissões de carbono.

Utiliza fatores de emissão do IPCC AR6, GHG Protocol Brasil e MCTI
para converter"""
Módulo 2 — Motor de IA para cálculo preciso de emissões de carbono.

Dois modos de cálculo, complementares:

  1. POR ATIVIDADE (preexistente): consumo físico (litros, kWh, km, kg) →
     tCO2e com fatores IPCC AR6, GHG Protocol Brasil e MCTI. Método primário,
     exigido para o mercado regulado (>25.000 tCO2e/ano, Lei 15.042/2024) nos
     Escopos 1 e 2.

  2. POR BALANÇO / DECLARAÇÃO (novo): a empresa declara sua CATEGORIA econômica
     e dados do balanço (faturamento, e opcionalmente gastos com energia,
     combustível e compras de insumos). O sistema estima tCO2e por escopo usando
     intensidades setoriais (spend-based / EEIO). É método de TRIAGEM, adequado
     ao nível de monitoramento (10k–25k tCO2e) e ao Escopo 3. A categoria define
     COMO o total se distribui entre os escopos; o balanço define o TAMANHO.

Os dois modos produzem a mesma estrutura (RelatorioIA) e preenchem os mesmos
campos do modelo Emissao, então podem ser misturados num único inventário.
"""

from dataclasses import dataclass, field
from typing import Any


# ── Fatores de emissão IPCC AR6 / MCTI 5ª Comunicação Nacional ──────────────
# Unidade: tCO2e por unidade de atividade
# GWP (Global Warming Potential): CO2=1, CH4=27.9, N2O=273 (AR6, 100 anos)

FATORES_COMBUSTIVEIS: dict[str, dict[str, float]] = {
    # nome: {fator_co2, fator_ch4, fator_n2o, unidade, descricao}
    "gasolina":         {"co2": 2.212, "ch4": 0.0004, "n2o": 0.00014, "uni": "litro", "desc": "Gasolina automotiva"},
    "etanol":           {"co2": 0.0,   "ch4": 0.0003, "n2o": 0.00011, "uni": "litro", "desc": "Etanol hidratado (biocombustível)"},
    "diesel":           {"co2": 2.603, "ch4": 0.0002, "n2o": 0.00009, "uni": "litro", "desc": "Óleo diesel"},
    "gnv":              {"co2": 1.937, "ch4": 0.0066, "n2o": 0.00003, "uni": "m3",    "desc": "Gás Natural Veicular"},
    "gas_natural":      {"co2": 1.937, "ch4": 0.0029, "n2o": 0.00003, "uni": "m3",    "desc": "Gás Natural estacionário"},
    "glp":              {"co2": 1.614, "ch4": 0.0002, "n2o": 0.00001, "uni": "kg",    "desc": "GLP (gás de cozinha/industrial)"},
    "oleo_combustivel": {"co2": 3.123, "ch4": 0.0003, "n2o": 0.00012, "uni": "litro", "desc": "Óleo combustível pesado"},
    "carvao_mineral":   {"co2": 2.422, "ch4": 0.0010, "n2o": 0.00042, "uni": "kg",    "desc": "Carvão mineral"},
    "biomassa":         {"co2": 0.0,   "ch4": 0.0300, "n2o": 0.00400, "uni": "kg",    "desc": "Biomassa (lenha, bagaço)"},
    "querosene":        {"co2": 2.543, "ch4": 0.0005, "n2o": 0.00010, "uni": "litro", "desc": "Querosene de aviação"},
}

# GWP AR6 100 anos
GWP_CH4 = 27.9
GWP_N2O = 273.0

# Fator de emissão da rede elétrica brasileira (SIN) — MCTI 2024
# tCO2e por MWh
FATOR_ELETRICIDADE_SIN = 0.0907  # kg CO2e/kWh → 0.0907 tCO2e/MWh

# Fatores de emissão fugitiva por equipamento
FATORES_REFRIGERANTES: dict[str, float] = {
    "r-22":      1_810,   # GWP (tCO2e/tonelada de refrigerante)
    "r-134a":    1_430,
    "r-404a":    3_922,
    "r-410a":    2_088,
    "r-407c":    1_774,
    "r-32":        675,
    "hfo-1234yf":    4,
}

# Fatores Escopo 3 — estimativas por setor (tCO2e por R$ 1000 comprados)
# Usados tanto no cálculo de cadeia por atividade quanto como refinamento de
# Escopo 3 no cálculo por balanço (quando há valor de compras declarado).
FATORES_CADEIA_FORNECIMENTO: dict[str, float] = {
    "agropecuaria":              0.320,
    "agronegocio":               0.320,
    "industria_alimenticia":     0.180,
    "industria_metalurgica":     0.420,
    "industria_quimica":         0.350,
    "industria_cimento":         0.850,
    "comercio_varejo":           0.085,
    "servicos_ti":               0.040,
    "servicos_financeiros":      0.030,
    "construcao_civil":          0.380,
    "transporte_logistica":      0.290,
    "mineracao":                 0.250,
    "papel_celulose":            0.220,
    "textil":                    0.180,
    "energia_geracao":           0.100,
}


# ── Perfis setoriais para cálculo POR BALANÇO (declaração da empresa) ──────────
# Intensidades de emissão por CATEGORIA econômica, em tCO2e por R$ 1.000 de
# RECEITA BRUTA (faturamento) declarada, separadas por escopo.
#
#   i_e1 = Escopo 1 (combustão própria, processos, frota, fugitivas)
#   i_e2 = Escopo 2 (energia elétrica/vapor comprados)
#   i_e3 = Escopo 3 (cadeia de fornecimento) — espelha FATORES_CADEIA_FORNECIMENTO
#
# >>> ATENÇÃO — CALIBRAÇÃO <<<
# Estes são valores INDICATIVOS, escolhidos para dar estrutura ao cálculo e
# guardar a proporção correta entre setores. ANTES de usar em produção, calibre
# com fontes oficiais brasileiras: SEEG, MCTI "Fatores de Emissão", matriz de
# insumo-produto (EEIO/IBGE). O método spend-based é de TRIAGEM; no mercado
# regulado os Escopos 1 e 2 devem ser refinados com dado de atividade.

PERFIL_PADRAO = {"rotulo": "Categoria não especificada", "i_e1": 0.050, "i_e2": 0.030, "i_e3": 0.150}

PERFIS_SETORIAIS: dict[str, dict] = {
    "agronegocio": {
        "rotulo": "Agronegócio / Produção primária",
        # Produção primária agropecuária é EXCLUÍDA do regime regulado (Lei 15.042),
        # mas ainda gera inventário e pode GERAR CRVE. Emissões biológicas
        # (fermentação entérica, solo) normalmente NÃO entram via balanço financeiro.
        "i_e1": 0.450, "i_e2": 0.030, "i_e3": 0.320,
    },
    "industria_alimenticia": {
        "rotulo": "Indústria alimentícia / Frigoríficos",
        "i_e1": 0.120, "i_e2": 0.080, "i_e3": 0.180,
    },
    "industria_metalurgica": {
        "rotulo": "Indústria metalúrgica / Siderurgia",
        "i_e1": 0.350, "i_e2": 0.100, "i_e3": 0.420,
    },
    "industria_quimica": {
        "rotulo": "Indústria química",
        "i_e1": 0.220, "i_e2": 0.090, "i_e3": 0.350,
    },
    "industria_cimento": {
        "rotulo": "Indústria de cimento",
        "i_e1": 0.650, "i_e2": 0.080, "i_e3": 0.200,  # E1 alto: CO2 de processo (calcinação)
    },
    "comercio_varejo": {
        "rotulo": "Comércio / Varejo",
        "i_e1": 0.020, "i_e2": 0.040, "i_e3": 0.085,
    },
    "servicos_ti": {
        "rotulo": "Serviços / TI",
        "i_e1": 0.005, "i_e2": 0.030, "i_e3": 0.040,
    },
    "servicos_financeiros": {
        "rotulo": "Serviços financeiros",
        "i_e1": 0.004, "i_e2": 0.020, "i_e3": 0.030,
    },
    "construcao_civil": {
        "rotulo": "Construção civil",
        "i_e1": 0.045, "i_e2": 0.020, "i_e3": 0.380,  # E3 alto: cimento, aço, materiais
    },
    "transporte_logistica": {
        "rotulo": "Transporte e logística",
        "i_e1": 0.260, "i_e2": 0.010, "i_e3": 0.060,  # E1 alto: combustão da frota
    },
    "mineracao": {
        "rotulo": "Mineração",
        "i_e1": 0.300, "i_e2": 0.120, "i_e3": 0.250,
    },
    "papel_celulose": {
        "rotulo": "Papel e celulose",
        "i_e1": 0.200, "i_e2": 0.100, "i_e3": 0.220,
    },
    "textil": {
        "rotulo": "Indústria têxtil",
        "i_e1": 0.100, "i_e2": 0.090, "i_e3": 0.180,
    },
    "energia_geracao": {
        "rotulo": "Geração de energia",
        "i_e1": 0.500, "i_e2": 0.020, "i_e3": 0.100,
    },
}

# Fatores de refinamento spend-based específicos (tCO2e por R$ 1.000 GASTOS
# naquele item). Diferentes das intensidades por receita acima. Indicativos:
#   - Energia: ~R$0,70/kWh e 0,0907 kgCO2e/kWh ⇒ ~0,13 tCO2e por R$1.000
#   - Combustível: diesel ~R$6/L e ~2,6 kgCO2e/L ⇒ ~0,43 tCO2e por R$1.000
FATOR_GASTO_ENERGIA = 0.13       # tCO2e / R$ 1.000 gastos em energia elétrica
FATOR_GASTO_COMBUSTIVEL = 0.43   # tCO2e / R$ 1.000 gastos em combustível


@dataclass
class EntradaAtividade:
    """Descreve uma atividade com consumo mensurável."""
    escopo: int          # 1, 2 ou 3
    categoria: str       # ex: "combustivel", "eletricidade", "refrigerante", "cadeia"
    tipo: str            # ex: "diesel", "gas_natural", "r-134a"
    quantidade: float    # valor numérico
    descricao: str = ""  # texto livre opcional


@dataclass
class ResultadoCalculo:
    atividade: EntradaAtividade
    tco2e: float
    detalhamento: dict[str, float] = field(default_factory=dict)
    fator_utilizado: float = 0.0
    unidade_fator: str = ""
    nota: str = ""


@dataclass
class RelatorioIA:
    entradas: list[EntradaAtividade] = field(default_factory=list)
    resultados: list[ResultadoCalculo] = field(default_factory=list)
    # Metadados opcionais (preenchidos pelo cálculo por balanço)
    metodo: str = "atividade"          # "atividade" | "balanco" | "misto"
    categoria: str = ""

    @property
    def escopo1_total(self) -> float:
        return sum(r.tco2e for r in self.resultados if r.atividade.escopo == 1)

    @property
    def escopo2_total(self) -> float:
        return sum(r.tco2e for r in self.resultados if r.atividade.escopo == 2)

    @property
    def escopo3_total(self) -> float:
        return sum(r.tco2e for r in self.resultados if r.atividade.escopo == 3)

    @property
    def total_tco2e(self) -> float:
        return round(self.escopo1_total + self.escopo2_total + self.escopo3_total, 6)

    def para_emissao_dict(self) -> dict:
        """Converte para o formato de campos de Emissao."""
        campos = {
            "e1_estacionario": 0.0, "e1_movel": 0.0,
            "e1_processos": 0.0, "e1_fugitivas": 0.0,
            "e2_eletrica": 0.0, "e2_vapor": 0.0,
            "e3_cadeia": 0.0, "e3_transporte": 0.0, "e3_residuos": 0.0,
        }
        for r in self.resultados:
            cat = r.atividade.categoria
            if r.atividade.escopo == 1:
                if cat == "combustivel_estacionario":
                    campos["e1_estacionario"] += r.tco2e
                elif cat == "combustivel_movel":
                    campos["e1_movel"] += r.tco2e
                elif cat == "processo_industrial":
                    campos["e1_processos"] += r.tco2e
                elif cat == "refrigerante":
                    campos["e1_fugitivas"] += r.tco2e
                else:  # E1 agregado vindo do balanço
                    campos["e1_estacionario"] += r.tco2e
            elif r.atividade.escopo == 2:
                if cat == "vapor":
                    campos["e2_vapor"] += r.tco2e
                else:
                    campos["e2_eletrica"] += r.tco2e
            elif r.atividade.escopo == 3:
                if cat == "transporte":
                    campos["e3_transporte"] += r.tco2e
                elif cat == "residuos":
                    campos["e3_residuos"] += r.tco2e
                else:
                    campos["e3_cadeia"] += r.tco2e
        return {k: round(v, 6) for k, v in campos.items()}


# ── Cálculo POR ATIVIDADE (preexistente) ────────────────────────────────────

def calcular_combustivel(
    combustivel: str,
    quantidade: float,
    escopo: int = 1,
    categoria: str = "combustivel_estacionario",
) -> ResultadoCalculo:
    """Calcula tCO2e a partir de consumo de combustível."""
    entrada = EntradaAtividade(escopo=escopo, categoria=categoria, tipo=combustivel, quantidade=quantidade)
    chave = combustivel.lower().replace(" ", "_").replace("-", "_")
    fator = FATORES_COMBUSTIVEIS.get(chave)
    if not fator:
        # tenta correspondência parcial
        for k in FATORES_COMBUSTIVEIS:
            if k in chave or chave in k:
                fator = FATORES_COMBUSTIVEIS[k]
                break

    if not fator:
        return ResultadoCalculo(
            atividade=entrada, tco2e=0.0, nota=f"Combustível '{combustivel}' não encontrado na base."
        )

    co2e_co2 = fator["co2"] * quantidade
    co2e_ch4 = fator["ch4"] * quantidade * GWP_CH4
    co2e_n2o = fator["n2o"] * quantidade * GWP_N2O
    total = round(co2e_co2 + co2e_ch4 + co2e_n2o, 6)

    fator_total = fator["co2"] + fator["ch4"] * GWP_CH4 + fator["n2o"] * GWP_N2O

    return ResultadoCalculo(
        atividade=entrada,
        tco2e=total,
        detalhamento={"CO2": co2e_co2, "CH4_eq": co2e_ch4, "N2O_eq": co2e_n2o},
        fator_utilizado=round(fator_total, 6),
        unidade_fator=f"tCO2e/{fator['uni']}",
        nota=fator.get("desc", ""),
    )


def calcular_eletricidade(kwh: float) -> ResultadoCalculo:
    """Calcula tCO2e a partir do consumo de energia elétrica (Escopo 2)."""
    entrada = EntradaAtividade(escopo=2, categoria="eletricidade", tipo="SIN", quantidade=kwh)
    tco2e = round(kwh * FATOR_ELETRICIDADE_SIN / 1000, 6)  # kWh → MWh
    return ResultadoCalculo(
        atividade=entrada,
        tco2e=tco2e,
        detalhamento={"CO2e_eletrica": tco2e},
        fator_utilizado=FATOR_ELETRICIDADE_SIN / 1000,
        unidade_fator="tCO2e/kWh",
        nota="Fator SIN Brasil — MCTI 2024",
    )


def calcular_refrigerante(tipo_refrigerante: str, kg_vazados: float) -> ResultadoCalculo:
    """Calcula emissões fugitivas por vazamento de refrigerante (Escopo 1)."""
    entrada = EntradaAtividade(
        escopo=1, categoria="refrigerante", tipo=tipo_refrigerante, quantidade=kg_vazados
    )
    chave = tipo_refrigerante.lower().replace(" ", "-")
    gwp = FATORES_REFRIGERANTES.get(chave, 1_500)  # 1500 como default conservador
    tco2e = round(kg_vazados * gwp / 1000, 6)  # kg → toneladas
    return ResultadoCalculo(
        atividade=entrada,
        tco2e=tco2e,
        detalhamento={"HFC_eq": tco2e},
        fator_utilizado=gwp,
        unidade_fator="GWP (tCO2e/t refrigerante)",
        nota=f"Refrigerante {tipo_refrigerante} — GWP AR6",
    )


def calcular_cadeia_fornecimento(setor: str, valor_compras_reais: float) -> ResultadoCalculo:
    """Estima Escopo 3 (cadeia) a partir do valor de compras por setor."""
    entrada = EntradaAtividade(
        escopo=3, categoria="cadeia", tipo=setor, quantidade=valor_compras_reais
    )
    chave = setor.lower().replace(" ", "_")
    fator = FATORES_CADEIA_FORNECIMENTO.get(chave, 0.150)
    tco2e = round(valor_compras_reais / 1000 * fator, 6)
    return ResultadoCalculo(
        atividade=entrada,
        tco2e=tco2e,
        detalhamento={"Escopo3_cadeia": tco2e},
        fator_utilizado=fator,
        unidade_fator="tCO2e/R$ 1000",
        nota=f"Setor: {setor} — estimativa EEIO",
    )


def calcular_transporte_rodoviario(
    km: float,
    tipo_veiculo: str = "caminhao_diesel",
    toneladas_carga: float = 1.0,
) -> ResultadoCalculo:
    """Calcula Escopo 3 para transporte rodoviário (tkm)."""
    fatores_tkm = {
        "caminhao_diesel":   0.000096,
        "caminhao_leve":     0.000142,
        "van_diesel":        0.000180,
        "trem":              0.000028,
        "navio":             0.000016,
        "aviao_carga":       0.000800,
    }
    entrada = EntradaAtividade(
        escopo=3, categoria="transporte", tipo=tipo_veiculo,
        quantidade=km * toneladas_carga,
    )
    fator = fatores_tkm.get(tipo_veiculo.lower(), 0.000096)
    tco2e = round(km * toneladas_carga * fator, 6)
    return ResultadoCalculo(
        atividade=entrada,
        tco2e=tco2e,
        fator_utilizado=fator,
        unidade_fator="tCO2e/tkm",
        nota=f"Transporte {tipo_veiculo} — GHG Protocol",
    )


# ── Cálculo POR BALANÇO / DECLARAÇÃO (novo) ──────────────────────────────────

@dataclass
class DeclaracaoEmpresa:
    """
    Declaração da empresa para cálculo de inventário por balanço.

    Base obrigatória: categoria + faturamento_bruto.
    Os demais campos são REFINAMENTOS OPCIONAIS — quando preenchidos (>0),
    substituem a estimativa por receita do escopo correspondente por uma
    estimativa mais precisa baseada no gasto específico.
    """
    empresa: str
    categoria: str                      # chave de PERFIS_SETORIAIS
    ano_referencia: int
    cnpj_cpf: str = ""
    faturamento_bruto: float = 0.0      # receita bruta anual (R$) — base principal

    # Refinamentos opcionais (R$):
    gasto_combustivel: float = 0.0      # → refina Escopo 1
    gasto_energia_eletrica: float = 0.0 # → refina Escopo 2
    compras_insumos: float = 0.0        # → refina Escopo 3 (fator de cadeia do setor)


def _chave_categoria(categoria: str) -> str:
    return (categoria or "").strip().lower().replace(" ", "_").replace("-", "_")


def calcular_por_balanco(decl: DeclaracaoEmpresa) -> RelatorioIA:
    """
    Estima o inventário (Escopos 1, 2 e 3) a partir da declaração da empresa.

    A CATEGORIA define a distribuição entre escopos (intensidades setoriais);
    o FATURAMENTO define o tamanho. Refinamentos por gasto, quando informados,
    têm prioridade sobre a estimativa por receita.

    Retorna um RelatorioIA — mesma estrutura do cálculo por atividade —, então
    `para_emissao_dict()`, totais por escopo e status funcionam igual.
    """
    chave = _chave_categoria(decl.categoria)
    perfil = PERFIS_SETORIAIS.get(chave, PERFIL_PADRAO)
    rotulo = perfil.get("rotulo", decl.categoria)
    receita_mil = (decl.faturamento_bruto or 0.0) / 1000.0  # R$ → milhares de R$

    rel = RelatorioIA(metodo="balanco", categoria=chave)

    # ── Escopo 1 ──
    if decl.gasto_combustivel and decl.gasto_combustivel > 0:
        base_e1 = decl.gasto_combustivel
        e1 = round(base_e1 / 1000.0 * FATOR_GASTO_COMBUSTIVEL, 6)
        fator_e1, fonte_e1, uni_e1 = FATOR_GASTO_COMBUSTIVEL, "gasto com combustível (R$)", "tCO2e/R$ 1000"
    else:
        base_e1 = decl.faturamento_bruto or 0.0
        e1 = round(receita_mil * perfil["i_e1"], 6)
        fator_e1, fonte_e1, uni_e1 = perfil["i_e1"], "faturamento (R$)", "tCO2e/R$ 1000 receita"

    # ── Escopo 2 ──
    if decl.gasto_energia_eletrica and decl.gasto_energia_eletrica > 0:
        base_e2 = decl.gasto_energia_eletrica
        e2 = round(base_e2 / 1000.0 * FATOR_GASTO_ENERGIA, 6)
        fator_e2, fonte_e2, uni_e2 = FATOR_GASTO_ENERGIA, "gasto com energia (R$)", "tCO2e/R$ 1000"
    else:
        base_e2 = decl.faturamento_bruto or 0.0
        e2 = round(receita_mil * perfil["i_e2"], 6)
        fator_e2, fonte_e2, uni_e2 = perfil["i_e2"], "faturamento (R$)", "tCO2e/R$ 1000 receita"

    # ── Escopo 3 ──
    if decl.compras_insumos and decl.compras_insumos > 0:
        base_e3 = decl.compras_insumos
        fator_cadeia = FATORES_CADEIA_FORNECIMENTO.get(chave, 0.150)
        e3 = round(base_e3 / 1000.0 * fator_cadeia, 6)
        fator_e3, fonte_e3, uni_e3 = fator_cadeia, "compras de insumos (R$)", "tCO2e/R$ 1000"
    else:
        base_e3 = decl.faturamento_bruto or 0.0
        e3 = round(receita_mil * perfil["i_e3"], 6)
        fator_e3, fonte_e3, uni_e3 = perfil["i_e3"], "faturamento (R$)", "tCO2e/R$ 1000 receita"

    # Monta resultados (categorias mapeiam direto para os campos de Emissao)
    r1 = ResultadoCalculo(
        atividade=EntradaAtividade(1, "combustivel_estacionario", f"balanco:{chave}", base_e1,
                                   f"Escopo 1 estimado — {rotulo}"),
        tco2e=e1, fator_utilizado=fator_e1, unidade_fator=uni_e1,
        nota=f"Base: {fonte_e1} | {rotulo}",
    )
    r2 = ResultadoCalculo(
        atividade=EntradaAtividade(2, "eletricidade", f"balanco:{chave}", base_e2,
                                   f"Escopo 2 estimado — {rotulo}"),
        tco2e=e2, fator_utilizado=fator_e2, unidade_fator=uni_e2,
        nota=f"Base: {fonte_e2} | {rotulo}",
    )
    r3 = ResultadoCalculo(
        atividade=EntradaAtividade(3, "cadeia", f"balanco:{chave}", base_e3,
                                   f"Escopo 3 estimado — {rotulo}"),
        tco2e=e3, fator_utilizado=fator_e3, unidade_fator=uni_e3,
        nota=f"Base: {fonte_e3} | {rotulo}",
    )

    rel.entradas.extend([r1.atividade, r2.atividade, r3.atividade])
    rel.resultados.extend([r1, r2, r3])
    return rel


# ── Ponto de entrada unificado ───────────────────────────────────────────────

def calcular_inventario(atividades: list[dict[str, Any]]) -> RelatorioIA:
    """
    Ponto de entrada principal. Recebe lista de atividades e retorna RelatorioIA.

    Cada atividade é um dict com campos:
        tipo_calculo: "combustivel" | "eletricidade" | "refrigerante"
                      | "cadeia" | "transporte" | "balanco"
        + parâmetros específicos de cada tipo

    Para "balanco", os campos esperados são os de DeclaracaoEmpresa
    (categoria, faturamento_bruto e, opcionalmente, gasto_combustivel,
    gasto_energia_eletrica, compras_insumos).

    É possível MISTURAR métodos: ex. uma entrada "balanco" para a base setorial
    + entradas "combustivel"/"eletricidade" para refinar com dado de atividade.
    """
    relatorio = RelatorioIA()
    metodos_usados: set[str] = set()

    for item in atividades:
        tipo = item.get("tipo_calculo", "")
        try:
            if tipo == "combustivel":
                r = calcular_combustivel(
                    combustivel=item["combustivel"],
                    quantidade=float(item["quantidade"]),
                    escopo=int(item.get("escopo", 1)),
                    categoria=item.get("categoria", "combustivel_estacionario"),
                )
            elif tipo == "eletricidade":
                r = calcular_eletricidade(kwh=float(item["kwh"]))
            elif tipo == "refrigerante":
                r = calcular_refrigerante(
                    tipo_refrigerante=item["refrigerante"],
                    kg_vazados=float(item["kg_vazados"]),
                )
            elif tipo == "cadeia":
                r = calcular_cadeia_fornecimento(
                    setor=item["setor"],
                    valor_compras_reais=float(item["valor_reais"]),
                )
            elif tipo == "transporte":
                r = calcular_transporte_rodoviario(
                    km=float(item["km"]),
                    tipo_veiculo=item.get("veiculo", "caminhao_diesel"),
                    toneladas_carga=float(item.get("toneladas", 1.0)),
                )
            elif tipo == "balanco":
                decl = DeclaracaoEmpresa(
                    empresa=item.get("empresa", ""),
                    categoria=item.get("categoria", ""),
                    ano_referencia=int(item.get("ano_referencia", 0)),
                    cnpj_cpf=item.get("cnpj_cpf", ""),
                    faturamento_bruto=float(item.get("faturamento_bruto", 0) or 0),
                    gasto_combustivel=float(item.get("gasto_combustivel", 0) or 0),
                    gasto_energia_eletrica=float(item.get("gasto_energia_eletrica", 0) or 0),
                    compras_insumos=float(item.get("compras_insumos", 0) or 0),
                )
                sub = calcular_por_balanco(decl)
                relatorio.entradas.extend(sub.entradas)
                relatorio.resultados.extend(sub.resultados)
                metodos_usados.add("balanco")
                continue
            else:
                continue
            relatorio.entradas.append(r.atividade)
            relatorio.resultados.append(r)
            metodos_usados.add("atividade")
        except (KeyError, ValueError):
            continue

    if metodos_usados == {"balanco"}:
        relatorio.metodo = "balanco"
    elif metodos_usados == {"atividade"}:
        relatorio.metodo = "atividade"
    elif metodos_usados:
        relatorio.metodo = "misto"

    return relatorio


# ── Listagens para a UI ──────────────────────────────────────────────────────

def listar_combustiveis() -> list[str]:
    return sorted(FATORES_COMBUSTIVEIS.keys())


def listar_refrigerantes() -> list[str]:
    return sorted(FATORES_REFRIGERANTES.keys())


def listar_setores_cadeia() -> list[str]:
    return sorted(FATORES_CADEIA_FORNECIMENTO.keys())


def listar_categorias_setoriais() -> list[tuple[str, str]]:
    """Retorna [(chave, rótulo)] das categorias disponíveis para o modo balanço."""
    return sorted(((k, v["rotulo"]) for k, v in PERFIS_SETORIAIS.items()), key=lambda x: x[1])
