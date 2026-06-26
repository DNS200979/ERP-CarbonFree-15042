"""
Módulo 2 — Motor de IA para cálculo preciso de emissões de carbono.

Utiliza fatores de emissão do IPCC AR6, GHG Protocol Brasil e MCTI
para converter dados de atividade (consumo de combustível, energia, etc.)
em tCO2e, sem necessidade de entrada manual dos valores finais.
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
FATORES_CADEIA_FORNECIMENTO: dict[str, float] = {
    "agropecuaria":              0.320,
    "industria_alimenticia":     0.180,
    "industria_metalurgica":     0.420,
    "industria_quimica":         0.350,
    "industria_cimento":         0.850,
    "comercio_varejo":           0.085,
    "servicos_ti":               0.040,
    "servicos_financeiros":      0.030,
    "construcao_civil":          0.380,
    "transporte_logistica":      0.290,
}


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


def calcular_inventario(atividades: list[dict[str, Any]]) -> RelatorioIA:
    """
    Ponto de entrada principal. Recebe lista de atividades e retorna RelatorioIA.

    Cada atividade é um dict com campos:
        tipo_calculo: "combustivel" | "eletricidade" | "refrigerante" | "cadeia" | "transporte"
        + parâmetros específicos de cada tipo
    """
    relatorio = RelatorioIA()

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
            else:
                continue
            relatorio.entradas.append(r.atividade)
            relatorio.resultados.append(r)
        except (KeyError, ValueError):
            continue

    return relatorio


def listar_combustiveis() -> list[str]:
    return sorted(FATORES_COMBUSTIVEIS.keys())


def listar_refrigerantes() -> list[str]:
    return sorted(FATORES_REFRIGERANTES.keys())


def listar_setores_cadeia() -> list[str]:
    return sorted(FATORES_CADEIA_FORNECIMENTO.keys())
