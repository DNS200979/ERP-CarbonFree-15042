"""
Módulo 2 — Motor de IA para cálculo preciso de emissões de carbono.

>>> VERSÃO "GRAU INMETRO / ISO 14064" <<<
Esta versão mantém TODA a API anterior (mesmas funções, mesmas assinaturas
compatíveis) e acrescenta a camada de RASTREABILIDADE exigida por um Organismo
de Validação e Verificação (OVV) acreditado pelo Inmetro:

  • cada resultado carrega a FONTE oficial do fator (norma + publicação + ano);
  • o CONJUNTO de GWP usado (AR6 por padrão, AR5 disponível) fica explícito;
  • a quebra POR GÁS (CO₂, CH₄, N₂O / HFC) é preservada;
  • o NÍVEL metodológico (Tier 1/2/3) e a INCERTEZA indicativa são informados;
  • é gerada uma MEMÓRIA DE CÁLCULO passo-a-passo (texto + estrutura), que é a
    evidência que o auditor lê na verificação (ISO 14064-3).

Correção importante desta versão
--------------------------------
O cálculo de combustível tratava os fatores (kg CO₂/unidade) como se fossem
toneladas, gerando resultado ~1000× maior. Aqui os fatores de combustão são
convertidos corretamente de kg para tonelada (÷1000), ficando coerentes com os
demais cálculos (eletricidade, refrigerante, transporte). 1.000 L de diesel
passa a resultar ~2,63 tCO₂e (e não 2.633).

Dois modos de cálculo, complementares:

  1. POR ATIVIDADE: consumo físico (litros, kWh, km, kg) → tCO₂e com fatores
     IPCC, GHG Protocol Brasil e MCTI. Método primário, exigido para o mercado
     regulado (>25.000 tCO₂e/ano, Lei 15.042/2024) nos Escopos 1 e 2.

  2. POR BALANÇO / DECLARAÇÃO: a empresa declara CATEGORIA econômica e dados do
     balanço (faturamento e, opcionalmente, gastos). O sistema estima tCO₂e por
     escopo via intensidades setoriais (spend-based/EEIO). É método de TRIAGEM.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════════════════
#  REGISTRO DE FONTES NORMATIVAS  (rastreabilidade exigida pela ISO 14064-3)
# ═══════════════════════════════════════════════════════════════════════════
# Cada fator usado no motor aponta para uma destas chaves. A memória de cálculo
# imprime o texto completo, de modo que o verificador consiga rastrear a origem.

FONTES: dict[str, str] = {
    "ipcc_2006_v2": "IPCC 2006 Guidelines for National GHG Inventories, Vol. 2 (Energia) — fatores de combustão",
    "ghg_brasil": "Programa Brasileiro GHG Protocol (FGV/WRI) — Ferramenta de Cálculo, edição vigente",
    "mcti_sin": "MCTI/SIRENE — Fator médio de emissão de CO₂ do SIN para inventários corporativos",
    "ipcc_ar6": "IPCC AR6 (2021) — GWP-100 anos (CO₂=1; CH₄≈27,9; N₂O=273)",
    "ipcc_ar5": "IPCC AR5 (2014) — GWP-100 anos (CO₂=1; CH₄=28; N₂O=265)",
    "ipcc_ar4_hfc": "IPCC AR4/AR5 — GWP de HFC/refrigerantes (100 anos)",
    "eeio_setorial": "Estimativa EEIO/spend-based (intensidade setorial) — método de TRIAGEM",
    "ghg_scope2": "GHG Protocol Scope 2 Guidance — abordagens location-based e market-based",
    "ghg_scope3": "GHG Protocol Corporate Value Chain (Scope 3) Standard",
}

# Referência normativa de enquadramento (verificação) usada nas notas.
REF_VERIFICACAO = "ABNT NBR ISO 14064-1 (quantificação) · ISO 14064-3 (verificação) · ISO 14065/14066 (OVV)"


# ═══════════════════════════════════════════════════════════════════════════
#  CONJUNTOS DE GWP  (Global Warming Potential, 100 anos)
# ═══════════════════════════════════════════════════════════════════════════
# AR6 é o padrão recomendado. AR5 fica disponível porque o Programa Brasileiro
# GHG Protocol ainda aceita AR5; a escolha deve ser consistente na série
# histórica (não misturar anos AR5 com AR6 sem recalcular o ano-base).

GWP_SETS: dict[str, dict[str, float]] = {
    "AR6": {"CO2": 1.0, "CH4": 27.9, "N2O": 273.0, "fonte": "ipcc_ar6"},
    "AR5": {"CO2": 1.0, "CH4": 28.0, "N2O": 265.0, "fonte": "ipcc_ar5"},
}

# Compatibilidade retroativa (código antigo importava estes nomes diretamente):
GWP_CH4 = GWP_SETS["AR6"]["CH4"]
GWP_N2O = GWP_SETS["AR6"]["N2O"]


# ═══════════════════════════════════════════════════════════════════════════
#  FATORES DE EMISSÃO — COMBUSTÍVEIS
# ═══════════════════════════════════════════════════════════════════════════
# Unidade dos fatores: kg do gás por unidade de atividade (litro, m³, kg).
# O motor converte para tonelada (÷1000) na hora de agregar em tCO₂e.
# 'bio' = combustível de origem biogênica → CO₂ de combustão é reportado à
# parte (não entra no total fóssil), mas CH₄/N₂O entram normalmente.

FATORES_COMBUSTIVEIS: dict[str, dict[str, Any]] = {
    "gasolina":         {"co2": 2.212, "ch4": 0.0004, "n2o": 0.00014, "uni": "litro", "bio": False, "desc": "Gasolina automotiva (parcela fóssil)", "fonte": "ghg_brasil"},
    "etanol":           {"co2": 1.526, "ch4": 0.0003, "n2o": 0.00011, "uni": "litro", "bio": True,  "desc": "Etanol hidratado (biogênico)",        "fonte": "ghg_brasil"},
    "diesel":           {"co2": 2.603, "ch4": 0.0002, "n2o": 0.00009, "uni": "litro", "bio": False, "desc": "Óleo diesel (parcela fóssil)",        "fonte": "ghg_brasil"},
    "biodiesel":        {"co2": 2.490, "ch4": 0.0002, "n2o": 0.00009, "uni": "litro", "bio": True,  "desc": "Biodiesel B100 (biogênico)",          "fonte": "ghg_brasil"},
    "gnv":              {"co2": 1.937, "ch4": 0.0066, "n2o": 0.00003, "uni": "m3",    "bio": False, "desc": "Gás Natural Veicular",                "fonte": "ipcc_2006_v2"},
    "gas_natural":      {"co2": 1.937, "ch4": 0.0029, "n2o": 0.00003, "uni": "m3",    "bio": False, "desc": "Gás Natural estacionário",            "fonte": "ipcc_2006_v2"},
    "glp":              {"co2": 2.932, "ch4": 0.0002, "n2o": 0.00001, "uni": "kg",    "bio": False, "desc": "GLP (gás de cozinha/industrial)",     "fonte": "ipcc_2006_v2"},
    "oleo_combustivel": {"co2": 3.123, "ch4": 0.0003, "n2o": 0.00012, "uni": "litro", "bio": False, "desc": "Óleo combustível pesado",            "fonte": "ipcc_2006_v2"},
    "carvao_mineral":   {"co2": 2.422, "ch4": 0.0010, "n2o": 0.00042, "uni": "kg",    "bio": False, "desc": "Carvão mineral",                      "fonte": "ipcc_2006_v2"},
    "biomassa":         {"co2": 1.747, "ch4": 0.0300, "n2o": 0.00400, "uni": "kg",    "bio": True,  "desc": "Biomassa (lenha, bagaço — biogênico)","fonte": "ipcc_2006_v2"},
    "querosene":        {"co2": 2.543, "ch4": 0.0005, "n2o": 0.00010, "uni": "litro", "bio": False, "desc": "Querosene de aviação (QAV)",          "fonte": "ipcc_2006_v2"},
}
# NB.: os fatores acima são valores de referência IPCC/GHG Protocol Brasil. Em
# produção (verificação real), reconcilie com a edição vigente da Ferramenta do
# Programa Brasileiro GHG Protocol antes de publicar o inventário.


# ═══════════════════════════════════════════════════════════════════════════
#  FATOR DE EMISSÃO — ELETRICIDADE (SIN, fator MÉDIO para inventário)
# ═══════════════════════════════════════════════════════════════════════════
# IMPORTANTE — leia antes de confiar no número:
#   • Para INVENTÁRIO corporativo (location-based) usa-se o FATOR MÉDIO anual do
#     SIN publicado pelo MCTI/SIRENE — NÃO a "margem de operação" (essa é para
#     projetos de MDL).
#   • O MCTI publica com ~1 ano de defasagem. Sempre confirme o valor do ano de
#     referência em: https://www.gov.br/mcti/.../fatores-de-emissao (SIRENE).
#   • Empresa no mercado livre com I-REC/atributo renovável pode reportar
#     Escopo 2 market-based ~0 — ver `base="market"` em calcular_eletricidade().
#
# Tabela por ano (tCO₂/MWh). Preencha os anos faltantes com o valor OFICIAL do
# SIRENE — a estrutura já está pronta, basta acrescentar a linha.
FATORES_ELETRICIDADE_ANUAIS: dict[int, dict[str, Any]] = {
    2023: {"fator_mwh": 0.0385, "fonte": "mcti_sin", "obs": "Fator médio anual 2023 (menor em 12 anos) — confirmado MCTI/SIRENE"},
    2011: {"fator_mwh": 0.0292, "fonte": "mcti_sin", "obs": "Referência histórica (mínimo anterior a 2023)"},
    # 2024: {"fator_mwh": <oficial SIRENE>, "fonte": "mcti_sin", "obs": "..."},
    # 2022: {"fator_mwh": <oficial SIRENE>, "fonte": "mcti_sin", "obs": "..."},
    # 2021: {"fator_mwh": <oficial SIRENE>, "fonte": "mcti_sin", "obs": "ano de crise hídrica — fator alto"},
}
ANO_ELETRICIDADE_PADRAO = 2023
# Compatibilidade: valor escalar usado pelo código antigo (tCO₂e/MWh do ano padrão).
FATOR_ELETRICIDADE_SIN = FATORES_ELETRICIDADE_ANUAIS[ANO_ELETRICIDADE_PADRAO]["fator_mwh"]


# ═══════════════════════════════════════════════════════════════════════════
#  FATORES — REFRIGERANTES (GWP = tCO₂e por tonelada de gás)
# ═══════════════════════════════════════════════════════════════════════════
FATORES_REFRIGERANTES: dict[str, float] = {
    "r-22":      1_810,
    "r-134a":    1_430,
    "r-404a":    3_922,
    "r-410a":    2_088,
    "r-407c":    1_774,
    "r-32":        675,
    "hfo-1234yf":    4,
}


# ═══════════════════════════════════════════════════════════════════════════
#  FATORES — CADEIA DE FORNECIMENTO (Escopo 3, tCO₂e por R$ 1.000)
# ═══════════════════════════════════════════════════════════════════════════
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


# ═══════════════════════════════════════════════════════════════════════════
#  FATORES — TRANSPORTE (Escopo 3, tCO₂e por t·km)
# ═══════════════════════════════════════════════════════════════════════════
FATORES_TRANSPORTE_TKM: dict[str, float] = {
    "caminhao_diesel": 0.000096,
    "caminhao_leve":   0.000142,
    "van_diesel":      0.000180,
    "trem":            0.000028,
    "navio":           0.000016,
    "aviao_carga":     0.000800,
}


# ── Perfis setoriais para cálculo POR BALANÇO (declaração) ───────────────────
PERFIL_PADRAO = {"rotulo": "Categoria não especificada", "i_e1": 0.050, "i_e2": 0.030, "i_e3": 0.150}

PERFIS_SETORIAIS: dict[str, dict] = {
    "agronegocio":           {"rotulo": "Agronegócio / Produção primária",      "i_e1": 0.450, "i_e2": 0.030, "i_e3": 0.320},
    "industria_alimenticia": {"rotulo": "Indústria alimentícia / Frigoríficos", "i_e1": 0.120, "i_e2": 0.080, "i_e3": 0.180},
    "industria_metalurgica": {"rotulo": "Indústria metalúrgica / Siderurgia",   "i_e1": 0.350, "i_e2": 0.100, "i_e3": 0.420},
    "industria_quimica":     {"rotulo": "Indústria química",                    "i_e1": 0.220, "i_e2": 0.090, "i_e3": 0.350},
    "industria_cimento":     {"rotulo": "Indústria de cimento",                 "i_e1": 0.650, "i_e2": 0.080, "i_e3": 0.200},
    "comercio_varejo":       {"rotulo": "Comércio / Varejo",                    "i_e1": 0.020, "i_e2": 0.040, "i_e3": 0.085},
    "servicos_ti":           {"rotulo": "Serviços / TI",                        "i_e1": 0.005, "i_e2": 0.030, "i_e3": 0.040},
    "servicos_financeiros":  {"rotulo": "Serviços financeiros",                 "i_e1": 0.004, "i_e2": 0.020, "i_e3": 0.030},
    "construcao_civil":      {"rotulo": "Construção civil",                     "i_e1": 0.045, "i_e2": 0.020, "i_e3": 0.380},
    "transporte_logistica":  {"rotulo": "Transporte e logística",              "i_e1": 0.260, "i_e2": 0.010, "i_e3": 0.060},
    "mineracao":             {"rotulo": "Mineração",                            "i_e1": 0.300, "i_e2": 0.120, "i_e3": 0.250},
    "papel_celulose":        {"rotulo": "Papel e celulose",                     "i_e1": 0.200, "i_e2": 0.100, "i_e3": 0.220},
    "textil":                {"rotulo": "Indústria têxtil",                     "i_e1": 0.100, "i_e2": 0.090, "i_e3": 0.180},
    "energia_geracao":       {"rotulo": "Geração de energia",                   "i_e1": 0.500, "i_e2": 0.020, "i_e3": 0.100},
}

FATOR_GASTO_ENERGIA = 0.13       # tCO₂e / R$ 1.000 gastos em energia elétrica
FATOR_GASTO_COMBUSTIVEL = 0.43   # tCO₂e / R$ 1.000 gastos em combustível


# ═══════════════════════════════════════════════════════════════════════════
#  ESTRUTURAS DE DADOS
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class EntradaAtividade:
    """Descreve uma atividade com consumo mensurável."""
    escopo: int
    categoria: str
    tipo: str
    quantidade: float
    descricao: str = ""


@dataclass
class ResultadoCalculo:
    """
    Resultado de um cálculo, com a camada de rastreabilidade ISO 14064.

    Os campos `tco2e`, `detalhamento`, `fator_utilizado`, `unidade_fator` e
    `nota` existem desde a versão anterior (compatibilidade). Os demais são a
    camada de auditoria nova.
    """
    atividade: EntradaAtividade
    tco2e: float
    detalhamento: dict[str, float] = field(default_factory=dict)
    fator_utilizado: float = 0.0
    unidade_fator: str = ""
    nota: str = ""

    # ── Camada de rastreabilidade (novo) ─────────────────────────────────────
    gases: list[dict] = field(default_factory=list)   # quebra por gás
    fonte_fator: str = ""                              # texto da fonte do FE
    referencia_normativa: str = ""                     # norma de enquadramento
    gwp_set: str = "AR6"                               # conjunto de GWP usado
    nivel_tier: str = ""                               # Tier 1 | 2 | 3
    qualidade_dado: str = "estimado"                   # medido | calculado | estimado
    incerteza_pct: Optional[float] = None              # incerteza indicativa (%)
    co2_biogenico_t: float = 0.0                       # CO₂ biogênico (reportado à parte)
    memoria_calculo: list[str] = field(default_factory=list)   # passo-a-passo

    def memoria_texto(self) -> str:
        return "\n".join(self.memoria_calculo)


@dataclass
class RelatorioIA:
    entradas: list[EntradaAtividade] = field(default_factory=list)
    resultados: list[ResultadoCalculo] = field(default_factory=list)
    metodo: str = "atividade"
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
    def co2_biogenico_total(self) -> float:
        return round(sum(r.co2_biogenico_t for r in self.resultados), 6)

    @property
    def total_tco2e(self) -> float:
        return round(self.escopo1_total + self.escopo2_total + self.escopo3_total, 6)

    def para_emissao_dict(self) -> dict:
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
                else:
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


# ═══════════════════════════════════════════════════════════════════════════
#  HELPERS DE MEMÓRIA DE CÁLCULO
# ═══════════════════════════════════════════════════════════════════════════

def _fmt(n: float, casas: int = 6) -> str:
    """Formata número no padrão pt-BR (vírgula decimal)."""
    s = f"{n:,.{casas}f}"
    return s.replace(",", "·").replace(".", ",").replace("·", ".")


def _fonte_txt(chave: str) -> str:
    return FONTES.get(chave, chave)


# ═══════════════════════════════════════════════════════════════════════════
#  CÁLCULO POR ATIVIDADE
# ═══════════════════════════════════════════════════════════════════════════

def calcular_combustivel(
    combustivel: str,
    quantidade: float,
    escopo: int = 1,
    categoria: str = "combustivel_estacionario",
    gwp_set: str = "AR6",
) -> ResultadoCalculo:
    """
    Calcula tCO₂e a partir do consumo de combustível.

    Equação (por gás g):  E_g [t] = (FE_g [kg/un] × Quantidade [un]) ÷ 1000 × GWP_g
    Total fóssil = ΣE_g (exceto CO₂ biogênico, que é reportado à parte).
    """
    entrada = EntradaAtividade(escopo=escopo, categoria=categoria, tipo=combustivel, quantidade=quantidade)
    chave = combustivel.lower().replace(" ", "_").replace("-", "_")
    fator = FATORES_COMBUSTIVEIS.get(chave)
    if not fator:
        for k in FATORES_COMBUSTIVEIS:
            if k in chave or chave in k:
                fator = FATORES_COMBUSTIVEIS[k]
                break
    if not fator:
        return ResultadoCalculo(atividade=entrada, tco2e=0.0,
                                nota=f"Combustível '{combustivel}' não encontrado na base.")

    gwp = GWP_SETS.get(gwp_set, GWP_SETS["AR6"])
    uni = fator["uni"]
    bio = fator.get("bio", False)

    # tonelada de cada gás = kg/un × un ÷ 1000
    t_co2 = fator["co2"] * quantidade / 1000.0
    t_ch4 = fator["ch4"] * quantidade / 1000.0
    t_n2o = fator["n2o"] * quantidade / 1000.0

    co2e_co2 = 0.0 if bio else t_co2 * gwp["CO2"]
    co2e_ch4 = t_ch4 * gwp["CH4"]
    co2e_n2o = t_n2o * gwp["N2O"]
    co2_biogenico = t_co2 if bio else 0.0

    total = round(co2e_co2 + co2e_ch4 + co2e_n2o, 6)
    fator_total_t = ((0.0 if bio else fator["co2"] * gwp["CO2"]) +
                     fator["ch4"] * gwp["CH4"] + fator["n2o"] * gwp["N2O"]) / 1000.0

    gases = [
        {"gas": "CO₂", "fe_kg_un": fator["co2"], "gwp": gwp["CO2"],
         "tco2e": round(co2e_co2, 6), "biogenico": bio},
        {"gas": "CH₄", "fe_kg_un": fator["ch4"], "gwp": gwp["CH4"], "tco2e": round(co2e_ch4, 6)},
        {"gas": "N₂O", "fe_kg_un": fator["n2o"], "gwp": gwp["N2O"], "tco2e": round(co2e_n2o, 6)},
    ]

    mem = [
        f"FONTE DE EMISSÃO: {fator.get('desc', combustivel)} — Escopo {escopo} ({categoria.replace('_', ' ')}).",
        f"DADO DE ATIVIDADE (DA): {_fmt(quantidade, 2)} {uni}.",
        f"FATOR DE EMISSÃO (FE): {_fonte_txt(fator['fonte'])}.",
        f"GWP ({gwp_set}): CO₂={gwp['CO2']} · CH₄={gwp['CH4']} · N₂O={gwp['N2O']} ({_fonte_txt(gwp['fonte'])}).",
        "EQUAÇÃO: E_g (t) = FE_g (kg/un) × DA (un) ÷ 1000 × GWP_g.",
        f"  CO₂ : {fator['co2']} × {_fmt(quantidade, 2)} ÷ 1000 × {gwp['CO2']} = {_fmt(co2e_co2)} tCO₂e"
        + ("   [BIOGÊNICO — reportado à parte, fora do total fóssil]" if bio else ""),
        f"  CH₄ : {fator['ch4']} × {_fmt(quantidade, 2)} ÷ 1000 × {gwp['CH4']} = {_fmt(co2e_ch4)} tCO₂e",
        f"  N₂O : {fator['n2o']} × {_fmt(quantidade, 2)} ÷ 1000 × {gwp['N2O']} = {_fmt(co2e_n2o)} tCO₂e",
        f"RESULTADO (fóssil): {_fmt(total)} tCO₂e."
        + (f"  CO₂ biogênico à parte: {_fmt(co2_biogenico)} t." if bio else ""),
        f"ENQUADRAMENTO: {REF_VERIFICACAO}.",
    ]

    return ResultadoCalculo(
        atividade=entrada, tco2e=total,
        detalhamento={"CO2": round(co2e_co2, 6), "CH4_eq": round(co2e_ch4, 6), "N2O_eq": round(co2e_n2o, 6)},
        fator_utilizado=round(fator_total_t, 9),
        unidade_fator=f"tCO₂e/{uni}",
        nota=fator.get("desc", ""),
        gases=gases, fonte_fator=_fonte_txt(fator["fonte"]),
        referencia_normativa=REF_VERIFICACAO, gwp_set=gwp_set,
        nivel_tier="Tier 1 (fator default IPCC/GHG Protocol)",
        qualidade_dado="calculado", incerteza_pct=7.5,
        co2_biogenico_t=round(co2_biogenico, 6),
        memoria_calculo=mem,
    )


def calcular_eletricidade(
    kwh: float,
    ano: Optional[int] = None,
    fator_customizado: Optional[float] = None,
    base: str = "location",
) -> ResultadoCalculo:
    """
    Calcula tCO₂e do consumo de energia elétrica (Escopo 2).

    Parâmetros:
      ano               → escolhe o fator médio anual do SIN (MCTI/SIRENE).
      fator_customizado → fator em tCO₂e/MWh fornecido pelo usuário (ex.: contrato
                          de mercado livre, I-REC). Tem prioridade sobre `ano`.
      base              → "location" (fator médio do grid) ou "market" (fator
                          contratual / atributo renovável). GHG Protocol Scope 2
                          recomenda reportar AMBOS.
    """
    entrada = EntradaAtividade(escopo=2, categoria="eletricidade", tipo="SIN", quantidade=kwh)

    if fator_customizado is not None:
        fator_mwh = float(fator_customizado)
        ano_ref = ano or ANO_ELETRICIDADE_PADRAO
        origem = (f"Fator contratual/market-based informado ({base})" if base == "market"
                  else f"Fator manual informado ({base})")
        fonte_chave = "ghg_scope2"
        obs = "Valor fornecido pelo usuário — anexar evidência (contrato/I-REC) ao dossiê."
    else:
        ano_ref = ano or ANO_ELETRICIDADE_PADRAO
        reg = FATORES_ELETRICIDADE_ANUAIS.get(ano_ref) or FATORES_ELETRICIDADE_ANUAIS[ANO_ELETRICIDADE_PADRAO]
        if ano_ref not in FATORES_ELETRICIDADE_ANUAIS:
            ano_ref = ANO_ELETRICIDADE_PADRAO
        fator_mwh = reg["fator_mwh"]
        origem = f"Fator médio anual do SIN — {ano_ref} (location-based)"
        fonte_chave = reg["fonte"]
        obs = reg.get("obs", "")

    tco2e = round(kwh * fator_mwh / 1000.0, 6)  # kWh → MWh (÷1000)

    gases = [{"gas": "CO₂", "fe_kg_un": fator_mwh, "gwp": 1.0, "tco2e": tco2e}]
    mem = [
        f"FONTE DE EMISSÃO: Energia elétrica adquirida da rede — Escopo 2 ({base}).",
        f"DADO DE ATIVIDADE (DA): {_fmt(kwh, 2)} kWh = {_fmt(kwh/1000.0, 4)} MWh.",
        f"FATOR DE EMISSÃO (FE): {_fmt(fator_mwh, 4)} tCO₂/MWh — {origem}.",
        f"  Fonte: {_fonte_txt(fonte_chave)}." + (f" {obs}" if obs else ""),
        "EQUAÇÃO: E = DA (kWh) × FE (tCO₂/MWh) ÷ 1000.",
        f"  {_fmt(kwh, 2)} × {_fmt(fator_mwh, 4)} ÷ 1000 = {_fmt(tco2e)} tCO₂e.",
        "OBS.: para inventário use o fator MÉDIO do SIN (não a margem de operação, que é para MDL). "
        "GHG Protocol Scope 2 recomenda reportar location-based E market-based.",
        f"ENQUADRAMENTO: {REF_VERIFICACAO}.",
    ]

    return ResultadoCalculo(
        atividade=entrada, tco2e=tco2e,
        detalhamento={"CO2e_eletrica": tco2e},
        fator_utilizado=fator_mwh, unidade_fator="tCO₂e/MWh",
        nota=origem,
        gases=gases, fonte_fator=_fonte_txt(fonte_chave),
        referencia_normativa=REF_VERIFICACAO, gwp_set="AR6",
        nivel_tier="Tier 1 (fator médio do grid)",
        qualidade_dado="medido" if fator_customizado is None else "calculado",
        incerteza_pct=5.0,
        memoria_calculo=mem,
    )


def calcular_refrigerante(tipo_refrigerante: str, kg_vazados: float) -> ResultadoCalculo:
    """Emissão fugitiva por vazamento de refrigerante (Escopo 1)."""
    entrada = EntradaAtividade(escopo=1, categoria="refrigerante", tipo=tipo_refrigerante, quantidade=kg_vazados)
    chave = tipo_refrigerante.lower().replace(" ", "-")
    gwp = FATORES_REFRIGERANTES.get(chave, 1_500)
    tco2e = round(kg_vazados * gwp / 1000.0, 6)  # kg → t

    gases = [{"gas": chave.upper(), "fe_kg_un": gwp, "gwp": gwp, "tco2e": tco2e}]
    mem = [
        f"FONTE DE EMISSÃO: Vazamento de gás refrigerante {chave.upper()} — Escopo 1 (fugitivas).",
        f"DADO DE ATIVIDADE (DA): {_fmt(kg_vazados, 3)} kg recarregados/repostos no período.",
        f"GWP DO GÁS: {gwp} tCO₂e por tonelada de {chave.upper()} — {_fonte_txt('ipcc_ar4_hfc')}.",
        "EQUAÇÃO: E = DA (kg) × GWP ÷ 1000.",
        f"  {_fmt(kg_vazados, 3)} × {gwp} ÷ 1000 = {_fmt(tco2e)} tCO₂e.",
        "OBS.: o DA deve refletir a reposição de gás (proxy de vazamento) registrada em manutenção.",
        f"ENQUADRAMENTO: {REF_VERIFICACAO}.",
    ]

    return ResultadoCalculo(
        atividade=entrada, tco2e=tco2e,
        detalhamento={"HFC_eq": tco2e},
        fator_utilizado=gwp, unidade_fator="GWP (tCO₂e/t)",
        nota=f"Refrigerante {tipo_refrigerante} — GWP 100 anos",
        gases=gases, fonte_fator=_fonte_txt("ipcc_ar4_hfc"),
        referencia_normativa=REF_VERIFICACAO, gwp_set="AR5/AR6",
        nivel_tier="Tier 1 (método por reposição)",
        qualidade_dado="calculado", incerteza_pct=12.5,
        memoria_calculo=mem,
    )


def calcular_cadeia_fornecimento(setor: str, valor_compras_reais: float) -> ResultadoCalculo:
    """Estima Escopo 3 (cadeia) a partir do valor de compras por setor (EEIO)."""
    entrada = EntradaAtividade(escopo=3, categoria="cadeia", tipo=setor, quantidade=valor_compras_reais)
    chave = setor.lower().replace(" ", "_")
    fator = FATORES_CADEIA_FORNECIMENTO.get(chave, 0.150)
    tco2e = round(valor_compras_reais / 1000.0 * fator, 6)

    gases = [{"gas": "CO₂e (agregado)", "fe_kg_un": fator, "gwp": 1.0, "tco2e": tco2e}]
    mem = [
        f"FONTE DE EMISSÃO: Cadeia de fornecimento — setor '{setor}' — Escopo 3 (compras de bens/serviços).",
        f"DADO DE ATIVIDADE (DA): R$ {_fmt(valor_compras_reais, 2)} em compras no período.",
        f"FATOR DE EMISSÃO (FE): {_fmt(fator, 3)} tCO₂e por R$ 1.000 — {_fonte_txt('eeio_setorial')}.",
        "EQUAÇÃO: E = DA (R$) ÷ 1.000 × FE.",
        f"  {_fmt(valor_compras_reais, 2)} ÷ 1.000 × {_fmt(fator, 3)} = {_fmt(tco2e)} tCO₂e.",
        "OBS.: método de TRIAGEM (spend-based). Não aceito como dado primário para Escopos 1 e 2 "
        "no mercado regulado — refine com dado de atividade quando o item for material.",
        f"ENQUADRAMENTO: {_fonte_txt('ghg_scope3')} · {REF_VERIFICACAO}.",
    ]

    return ResultadoCalculo(
        atividade=entrada, tco2e=tco2e,
        detalhamento={"Escopo3_cadeia": tco2e},
        fator_utilizado=fator, unidade_fator="tCO₂e/R$ 1000",
        nota=f"Setor: {setor} — estimativa EEIO",
        gases=gases, fonte_fator=_fonte_txt("eeio_setorial"),
        referencia_normativa=f"{_fonte_txt('ghg_scope3')} · {REF_VERIFICACAO}",
        gwp_set="—", nivel_tier="Triagem (spend-based / EEIO)",
        qualidade_dado="estimado", incerteza_pct=40.0,
        memoria_calculo=mem,
    )


def calcular_transporte_rodoviario(
    km: float,
    tipo_veiculo: str = "caminhao_diesel",
    toneladas_carga: float = 1.0,
) -> ResultadoCalculo:
    """Calcula Escopo 3 para transporte (t·km)."""
    entrada = EntradaAtividade(escopo=3, categoria="transporte", tipo=tipo_veiculo,
                               quantidade=km * toneladas_carga)
    fator = FATORES_TRANSPORTE_TKM.get(tipo_veiculo.lower(), 0.000096)
    tkm = km * toneladas_carga
    tco2e = round(tkm * fator, 6)

    gases = [{"gas": "CO₂e (well-to-wheel)", "fe_kg_un": fator, "gwp": 1.0, "tco2e": tco2e}]
    mem = [
        f"FONTE DE EMISSÃO: Transporte de carga ({tipo_veiculo.replace('_', ' ')}) — Escopo 3.",
        f"DADO DE ATIVIDADE (DA): {_fmt(km, 2)} km × {_fmt(toneladas_carga, 2)} t = {_fmt(tkm, 2)} t·km.",
        f"FATOR DE EMISSÃO (FE): {_fmt(fator, 6)} tCO₂e por t·km — {_fonte_txt('ghg_scope3')}.",
        "EQUAÇÃO: E = (km × toneladas) × FE.",
        f"  {_fmt(tkm, 2)} × {_fmt(fator, 6)} = {_fmt(tco2e)} tCO₂e.",
        f"ENQUADRAMENTO: {_fonte_txt('ghg_scope3')} · {REF_VERIFICACAO}.",
    ]

    return ResultadoCalculo(
        atividade=entrada, tco2e=tco2e,
        detalhamento={"Escopo3_transporte": tco2e},
        fator_utilizado=fator, unidade_fator="tCO₂e/t·km",
        nota=f"Transporte {tipo_veiculo} — GHG Protocol",
        gases=gases, fonte_fator=_fonte_txt("ghg_scope3"),
        referencia_normativa=f"{_fonte_txt('ghg_scope3')} · {REF_VERIFICACAO}",
        gwp_set="AR6", nivel_tier="Tier 1 (fator por modal)",
        qualidade_dado="calculado", incerteza_pct=20.0,
        memoria_calculo=mem,
    )


# ═══════════════════════════════════════════════════════════════════════════
#  CÁLCULO POR BALANÇO / DECLARAÇÃO
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DeclaracaoEmpresa:
    empresa: str
    categoria: str
    ano_referencia: int
    cnpj_cpf: str = ""
    faturamento_bruto: float = 0.0
    gasto_combustivel: float = 0.0
    gasto_energia_eletrica: float = 0.0
    compras_insumos: float = 0.0


def _chave_categoria(categoria: str) -> str:
    return (categoria or "").strip().lower().replace(" ", "_").replace("-", "_")


def calcular_por_balanco(decl: DeclaracaoEmpresa) -> RelatorioIA:
    """Estima o inventário (Escopos 1, 2 e 3) a partir da declaração da empresa."""
    chave = _chave_categoria(decl.categoria)
    perfil = PERFIS_SETORIAIS.get(chave, PERFIL_PADRAO)
    rotulo = perfil.get("rotulo", decl.categoria)
    receita_mil = (decl.faturamento_bruto or 0.0) / 1000.0

    rel = RelatorioIA(metodo="balanco", categoria=chave)

    # ── Escopo 1 ──
    if decl.gasto_combustivel and decl.gasto_combustivel > 0:
        base_e1 = decl.gasto_combustivel
        e1 = round(base_e1 / 1000.0 * FATOR_GASTO_COMBUSTIVEL, 6)
        fator_e1, fonte_e1, uni_e1 = FATOR_GASTO_COMBUSTIVEL, "gasto com combustível (R$)", "tCO₂e/R$ 1000"
    else:
        base_e1 = decl.faturamento_bruto or 0.0
        e1 = round(receita_mil * perfil["i_e1"], 6)
        fator_e1, fonte_e1, uni_e1 = perfil["i_e1"], "faturamento (R$)", "tCO₂e/R$ 1000 receita"

    # ── Escopo 2 ──
    if decl.gasto_energia_eletrica and decl.gasto_energia_eletrica > 0:
        base_e2 = decl.gasto_energia_eletrica
        e2 = round(base_e2 / 1000.0 * FATOR_GASTO_ENERGIA, 6)
        fator_e2, fonte_e2, uni_e2 = FATOR_GASTO_ENERGIA, "gasto com energia (R$)", "tCO₂e/R$ 1000"
    else:
        base_e2 = decl.faturamento_bruto or 0.0
        e2 = round(receita_mil * perfil["i_e2"], 6)
        fator_e2, fonte_e2, uni_e2 = perfil["i_e2"], "faturamento (R$)", "tCO₂e/R$ 1000 receita"

    # ── Escopo 3 ──
    if decl.compras_insumos and decl.compras_insumos > 0:
        base_e3 = decl.compras_insumos
        fator_cadeia = FATORES_CADEIA_FORNECIMENTO.get(chave, 0.150)
        e3 = round(base_e3 / 1000.0 * fator_cadeia, 6)
        fator_e3, fonte_e3, uni_e3 = fator_cadeia, "compras de insumos (R$)", "tCO₂e/R$ 1000"
    else:
        base_e3 = decl.faturamento_bruto or 0.0
        e3 = round(receita_mil * perfil["i_e3"], 6)
        fator_e3, fonte_e3, uni_e3 = perfil["i_e3"], "faturamento (R$)", "tCO₂e/R$ 1000 receita"

    def _mem(escopo, base, fator, fonte):
        return [
            f"MÉTODO: triagem por balanço (spend-based/EEIO) — {rotulo}.",
            f"BASE (Escopo {escopo}): {fonte} = R$ {_fmt(base, 2)}.",
            f"FATOR: {_fmt(fator, 4)} {('tCO₂e/R$ 1000')}.",
            f"E{escopo} = R$ {_fmt(base, 2)} ÷ 1000 × {_fmt(fator, 4)}.",
            "OBS.: estimativa de triagem; não substitui dado de atividade no mercado regulado.",
        ]

    r1 = ResultadoCalculo(
        atividade=EntradaAtividade(1, "combustivel_estacionario", f"balanco:{chave}", base_e1, f"Escopo 1 estimado — {rotulo}"),
        tco2e=e1, fator_utilizado=fator_e1, unidade_fator=uni_e1, nota=f"Base: {fonte_e1} | {rotulo}",
        fonte_fator=_fonte_txt("eeio_setorial"), referencia_normativa=REF_VERIFICACAO,
        nivel_tier="Triagem (balanço)", qualidade_dado="estimado", incerteza_pct=50.0,
        memoria_calculo=_mem(1, base_e1, fator_e1, fonte_e1))
    r2 = ResultadoCalculo(
        atividade=EntradaAtividade(2, "eletricidade", f"balanco:{chave}", base_e2, f"Escopo 2 estimado — {rotulo}"),
        tco2e=e2, fator_utilizado=fator_e2, unidade_fator=uni_e2, nota=f"Base: {fonte_e2} | {rotulo}",
        fonte_fator=_fonte_txt("eeio_setorial"), referencia_normativa=REF_VERIFICACAO,
        nivel_tier="Triagem (balanço)", qualidade_dado="estimado", incerteza_pct=50.0,
        memoria_calculo=_mem(2, base_e2, fator_e2, fonte_e2))
    r3 = ResultadoCalculo(
        atividade=EntradaAtividade(3, "cadeia", f"balanco:{chave}", base_e3, f"Escopo 3 estimado — {rotulo}"),
        tco2e=e3, fator_utilizado=fator_e3, unidade_fator=uni_e3, nota=f"Base: {fonte_e3} | {rotulo}",
        fonte_fator=_fonte_txt("eeio_setorial"), referencia_normativa=REF_VERIFICACAO,
        nivel_tier="Triagem (balanço)", qualidade_dado="estimado", incerteza_pct=50.0,
        memoria_calculo=_mem(3, base_e3, fator_e3, fonte_e3))

    rel.entradas.extend([r1.atividade, r2.atividade, r3.atividade])
    rel.resultados.extend([r1, r2, r3])
    return rel


# ═══════════════════════════════════════════════════════════════════════════
#  PONTO DE ENTRADA UNIFICADO
# ═══════════════════════════════════════════════════════════════════════════

def calcular_inventario(atividades: list[dict[str, Any]]) -> RelatorioIA:
    """Recebe lista de atividades e retorna RelatorioIA (mistura métodos)."""
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
                    gwp_set=item.get("gwp_set", "AR6"),
                )
            elif tipo == "eletricidade":
                r = calcular_eletricidade(
                    kwh=float(item["kwh"]),
                    ano=item.get("ano"),
                    fator_customizado=item.get("fator_customizado"),
                    base=item.get("base", "location"),
                )
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


# ═══════════════════════════════════════════════════════════════════════════
#  LISTAGENS PARA A UI
# ═══════════════════════════════════════════════════════════════════════════

def listar_combustiveis() -> list[str]:
    return sorted(FATORES_COMBUSTIVEIS.keys())


def listar_refrigerantes() -> list[str]:
    return sorted(FATORES_REFRIGERANTES.keys())


def listar_setores_cadeia() -> list[str]:
    return sorted(FATORES_CADEIA_FORNECIMENTO.keys())


def listar_anos_eletricidade() -> list[dict]:
    """[(ano, fator, obs)] dos fatores SIN disponíveis (mais recente primeiro)."""
    return [
        {"ano": ano, "fator_mwh": reg["fator_mwh"], "obs": reg.get("obs", ""),
         "fonte": _fonte_txt(reg["fonte"])}
        for ano, reg in sorted(FATORES_ELETRICIDADE_ANUAIS.items(), reverse=True)
    ]


def listar_categorias_setoriais() -> list[tuple[str, str]]:
    return sorted(((k, v["rotulo"]) for k, v in PERFIS_SETORIAIS.items()), key=lambda x: x[1])
