#!/usr/bin/env bash
# ============================================================================
# instalar_backend.sh
# Alinha os arquivos do backend que estavam desatualizados em disco:
#   - app/services/motor_ia.py   (cálculo por atividade + por balanço)
#   - app/services/cnpj.py       (consultar_cnpj + cnae_para_categoria)
#   - app/services/ecf.py        (parser da ECF, lê CNAE do registro 0020)
# Grava cada um no caminho certo (com backup .bak.<timestamp>), confirma que
# importam, e reinicia a API. NAO depende do editor.
#
# Uso:
#   1) coloque este arquivo em ~/Desktop/ERP15042
#   2) cd ~/Desktop/ERP15042
#   3) bash instalar_backend.sh
# ============================================================================
set -e
cd "$(dirname "$0")"
if [ ! -d "app/services" ] && [ -d "$HOME/Desktop/ERP15042/app/services" ]; then
  cd "$HOME/Desktop/ERP15042"
fi
if [ ! -d "app/services" ] || [ ! -d "app/api/routes" ]; then
  echo "ERRO: rode dentro de ~/Desktop/ERP15042 (nao achei app/services e app/api/routes)."
  exit 1
fi
echo ">> Projeto: $(pwd)"

grava() {  # $1 = caminho de destino ; conteudo vem do heredoc no stdin
  local alvo="$1"
  cp "$alvo" "$alvo.bak.$(date +%s)" 2>/dev/null && echo ">> backup: $alvo.bak.*" || true
  cat > "$alvo"
  echo ">> gravado: $alvo"
}

grava app/services/motor_ia.py <<'MOTOR_EOF'
"""
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
MOTOR_EOF

grava app/services/cnpj.py <<'CNPJ_EOF'
"""
Consulta de CNPJ na base PÚBLICA da Receita Federal (via BrasilAPI) e
mapeamento do CNAE principal para a categoria setorial usada no cálculo
por balanço (PERFIS_SETORIAIS em app/services/motor_ia.py).

Sem dependências externas: usa urllib (biblioteca padrão do Python).
Fonte: https://brasilapi.com.br/api/cnpj/v1/{cnpj}  (Dados Públicos CNPJ / RFB)

LIMITAÇÃO IMPORTANTE: a base pública traz apenas dados CADASTRAIS
(razão social, CNAE, capital social, porte, situação). Ela NÃO traz
faturamento nem balanço — esses dados são sigilosos (SPED/ECF) e não têm
API pública. O faturamento continua sendo informado pelo usuário (ou, para
companhias abertas, obtido via dados abertos da CVM).
"""

import json
import re
import urllib.request
import urllib.error

BRASILAPI_CNPJ = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"

# Mapa: divisão CNAE (2 primeiros dígitos do código) → categoria de PERFIS_SETORIAIS.
# CNAE tem 7 dígitos; a "divisão" são os 2 primeiros e já define bem o setor.
_DIVISAO_PARA_CATEGORIA: dict[str, str] = {
    # Agropecuária
    "01": "agronegocio", "02": "agronegocio", "03": "agronegocio",
    # Indústrias extrativas (mineração)
    "05": "mineracao", "06": "mineracao", "07": "mineracao",
    "08": "mineracao", "09": "mineracao",
    # Alimentos e bebidas
    "10": "industria_alimenticia", "11": "industria_alimenticia",
    # Têxtil / vestuário / couro e calçados
    "13": "textil", "14": "textil", "15": "textil",
    # Papel e celulose
    "17": "papel_celulose",
    # Química e farmoquímica
    "20": "industria_quimica", "21": "industria_quimica",
    # Minerais não-metálicos (cimento, cerâmica, vidro)
    "23": "industria_cimento",
    # Metalurgia e produtos de metal
    "24": "industria_metalurgica", "25": "industria_metalurgica",
    # Eletricidade e gás
    "35": "energia_geracao",
    # Construção
    "41": "construcao_civil", "42": "construcao_civil", "43": "construcao_civil",
    # Comércio (atacado e varejo)
    "45": "comercio_varejo", "46": "comercio_varejo", "47": "comercio_varejo",
    # Transporte e armazenagem
    "49": "transporte_logistica", "50": "transporte_logistica",
    "51": "transporte_logistica", "52": "transporte_logistica",
    "53": "transporte_logistica",
    # Informação e comunicação (TI)
    "58": "servicos_ti", "59": "servicos_ti", "60": "servicos_ti",
    "61": "servicos_ti", "62": "servicos_ti", "63": "servicos_ti",
    # Atividades financeiras e seguros
    "64": "servicos_financeiros", "65": "servicos_financeiros", "66": "servicos_financeiros",
}


def cnae_para_categoria(cnae) -> str | None:
    """
    Recebe um código CNAE (int ou str, com ou sem máscara) e devolve a chave
    de categoria de PERFIS_SETORIAIS, ou None se não houver mapeamento.
    """
    if cnae is None:
        return None
    digitos = re.sub(r"\D", "", str(cnae))
    if not digitos:
        return None
    # O CNAE tem 7 dígitos. Quando vem como número (ex.: BrasilAPI), divisões
    # 01–09 perdem o zero à esquerda (0111301 → 111301). Restauramos com zfill.
    digitos = digitos.zfill(7)
    return _DIVISAO_PARA_CATEGORIA.get(digitos[:2])


def consultar_cnpj(cnpj: str, timeout: float = 8.0) -> dict:
    """
    Consulta dados cadastrais públicos do CNPJ via BrasilAPI.

    Retorna dict normalizado com: cnpj, razao_social, nome_fantasia,
    cnae_fiscal, cnae_descricao, categoria_sugerida (chave ou None) e os
    campos auxiliares capital_social, porte, situacao.

    Lança ValueError se o CNPJ for inválido, não encontrado, ou se houver
    falha de rede.
    """
    digitos = re.sub(r"\D", "", cnpj or "")
    if len(digitos) != 14:
        raise ValueError("CNPJ deve ter 14 dígitos.")

    url = BRASILAPI_CNPJ.format(cnpj=digitos)
    req = urllib.request.Request(url, headers={"User-Agent": "ERP-CarbonFree/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError("CNPJ não encontrado na base pública.")
        raise ValueError(f"Erro na consulta CNPJ (HTTP {e.code}).")
    except urllib.error.URLError as e:
        raise ValueError(f"Falha de rede ao consultar CNPJ: {e.reason}")
    except Exception as e:  # JSON inválido, etc.
        raise ValueError(f"Resposta inesperada da consulta CNPJ: {e}")

    cnae = dados.get("cnae_fiscal")
    return {
        "cnpj": digitos,
        "razao_social": dados.get("razao_social") or dados.get("nome") or "",
        "nome_fantasia": dados.get("nome_fantasia") or "",
        "cnae_fiscal": cnae,
        "cnae_descricao": dados.get("cnae_fiscal_descricao") or "",
        "categoria_sugerida": cnae_para_categoria(cnae),  # pode ser None
        "capital_social": dados.get("capital_social"),
        "porte": dados.get("porte") or dados.get("descricao_porte") or "",
        "situacao": dados.get("descricao_situacao_cadastral") or "",
    }
CNPJ_EOF

grava app/services/ecf.py <<'ECF_EOF'
"""
app/services/ecf.py

Leitura automática da ECF (Escrituração Contábil Fiscal) — o arquivo SPED que
as empresas transmitem anualmente à Receita Federal (substituiu a DIPJ) para
apuração do IRPJ/CSLL. A partir dele extraímos, sem digitação manual, os dados
que alimentam o cálculo de emissões por balanço (motor_ia.calcular_por_balanco):

    • CNPJ e razão social ............... registro 0000
    • Período de apuração / ano ......... registro 0000 (datas ddmmaaaa)
    • Regime de tributação .............. presença do bloco L (Lucro Real)
                                          ou P (Lucro Presumido)
    • Receita bruta anual ............... linha da DRE (L300 / P150)
    • Gasto com energia elétrica ........ linha da DRE  -> refina o Escopo 2
    • Gasto com combustíveis ............ linha da DRE  -> refina o Escopo 1

Formato do arquivo: texto, um registro por linha, campos entre pipes "|":
    |REG|campo1|campo2|...|
Valores monetários usam vírgula decimal (padrão SPED): 50000000,00

----------------------------------------------------------------------------
SOBRE O LEIAUTE
O leiaute da ECF é publicado a cada ano pela RFB (Manual da ECF). Posições de
campos podem variar entre versões. Por isso este parser NÃO depende de posições
fixas para os valores financeiros: localiza a receita e as despesas pela
DESCRIÇÃO da conta na DRE (texto estável entre versões) e a identificação por
máscara (CNPJ = 14 dígitos, data = ddmmaaaa). Todo valor extraído é devolvido
para CONFERÊNCIA do usuário — nada é arquivado automaticamente sem revisão.

Empresas do Simples Nacional, em geral, não transmitem ECF; para elas use a
receita declarada na DEFIS/PGDAS-D e o caminho de entrada manual.
----------------------------------------------------------------------------
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


# -- utilidades ---------------------------------------------------------------

def _normalizar(texto: str) -> str:
    """MAIÚSCULAS sem acento, para casar descrições de contas."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.upper().strip()


def _num(valor: str) -> float:
    """Converte valor monetário SPED ('1.234.567,89' ou '1234567,89') em float."""
    if not valor:
        return 0.0
    v = valor.strip().replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return 0.0


def _eh_numero(s: str) -> bool:
    return bool(s) and bool(re.fullmatch(r"-?[\d.,]+", s)) and any(c.isdigit() for c in s)


# -- modelos ------------------------------------------------------------------

@dataclass
class LinhaDRE:
    codigo: str
    descricao: str
    valor: float
    indicador: str = ""   # 'D' (devedor/despesa) | 'C' (credor/receita)


@dataclass
class DadosECF:
    cnpj: str = ""
    razao_social: str = ""
    cnae: str = ""                # CNAE principal lido do registro 0020 (quando presente)
    dt_inicial: str = ""          # ddmmaaaa
    dt_final: str = ""            # ddmmaaaa
    ano_referencia: int = 0
    regime: str = "desconhecido"  # 'lucro_real' | 'lucro_presumido' | 'desconhecido'
    receita_bruta: float = 0.0
    gasto_energia_eletrica: float = 0.0
    gasto_combustivel: float = 0.0
    dre: list[LinhaDRE] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def periodo(self) -> str:
        def f(d):
            return f"{d[:2]}/{d[2:4]}/{d[4:]}" if len(d) == 8 else d
        return f"{f(self.dt_inicial)} a {f(self.dt_final)}" if self.dt_inicial else ""

    def resumo(self) -> dict:
        return {
            "cnpj": self.cnpj,
            "razao_social": self.razao_social,
            "cnae": self.cnae,
            "ano_referencia": self.ano_referencia,
            "periodo": self.periodo,
            "regime": self.regime,
            "receita_bruta": round(self.receita_bruta, 2),
            "gasto_energia_eletrica": round(self.gasto_energia_eletrica, 2),
            "gasto_combustivel": round(self.gasto_combustivel, 2),
            "avisos": self.avisos,
        }


# -- heurísticas de classificação de contas da DRE ----------------------------

def _eh_receita_bruta(desc_norm: str) -> bool:
    if "RECEITA" not in desc_norm:
        return False
    return any(t in desc_norm for t in ("BRUTA", "VENDA", "REVENDA", "PRESTACAO DE SERVICO"))


def _eh_energia(desc_norm: str) -> bool:
    return "ENERGIA ELETRICA" in desc_norm or ("ENERGIA" in desc_norm and "ELETRIC" in desc_norm)


def _eh_combustivel(desc_norm: str) -> bool:
    return "COMBUSTIVEL" in desc_norm or "COMBUSTIVEIS" in desc_norm


# -- parsing de registros -----------------------------------------------------

def _parse_0000(campos: list[str], dados: DadosECF) -> None:
    valores = [c.strip() for c in campos]
    # CNPJ = primeiro campo com exatamente 14 dígitos (aparece cedo, antes do nº do recibo)
    for v in valores[2:]:
        if re.fullmatch(r"\d{14}", v):
            dados.cnpj = v
            break
    # Razão social: campo de texto adjacente ao CNPJ. O leiaute da ECF varia —
    # em algumas versões o nome vem ANTES do CNPJ (|...|NOME|CNPJ|UF|...) e em
    # outras DEPOIS. Pegamos o vizinho (anterior ou posterior) que pareça um
    # nome: tem letras, não é data de 8 dígitos e tem mais de 2 caracteres
    # (descarta a sigla da UF, ex.: "SC"). Em empate, o mais longo.
    if dados.cnpj:
        try:
            i = valores.index(dados.cnpj)
        except ValueError:
            i = -1
        if i >= 0:
            vizinhos = []
            if i - 1 >= 0:
                vizinhos.append(valores[i - 1])
            if i + 1 < len(valores):
                vizinhos.append(valores[i + 1])
            candidatos_nome = [
                c for c in vizinhos
                if c and len(c) > 2
                and re.search(r"[A-Za-zÀ-ÿ]", c)
                and not re.fullmatch(r"\d{8}", c)
            ]
            if candidatos_nome:
                dados.razao_social = max(candidatos_nome, key=len)
    # Datas ddmmaaaa válidas -> menor = início, maior = fim, ano = do fim
    datas = []
    for v in valores:
        if re.fullmatch(r"\d{8}", v):
            dd, mm, aaaa = int(v[:2]), int(v[2:4]), int(v[4:])
            if 1 <= dd <= 31 and 1 <= mm <= 12 and 1900 <= aaaa <= 2100:
                datas.append((aaaa, mm, dd, v))
    if datas:
        datas.sort()
        dados.dt_inicial = datas[0][3]
        dados.dt_final = datas[-1][3]
        dados.ano_referencia = datas[-1][0]


def _coletar_dre(campos: list[str], dados: DadosECF, candidatos: list) -> None:
    valores = [c.strip() for c in campos]
    # descrição = primeiro campo com letras (>= índice 2)
    idx_desc = None
    for i in range(2, len(valores)):
        if re.search(r"[A-Za-zÀ-ÿ]", valores[i]):
            idx_desc = i
            break
    if idx_desc is None:
        return
    descricao = valores[idx_desc]
    codigo = valores[2] if idx_desc != 2 else ""
    # valor = primeiro campo numérico depois da descrição; indicador D/C, se houver
    valor, indicador = 0.0, ""
    for j in range(idx_desc + 1, len(valores)):
        if _eh_numero(valores[j]):
            valor = _num(valores[j])
            if j + 1 < len(valores) and valores[j + 1] in ("D", "C"):
                indicador = valores[j + 1]
            break

    dados.dre.append(LinhaDRE(codigo, descricao, valor, indicador))

    d = _normalizar(descricao)
    if _eh_receita_bruta(d):
        candidatos.append((descricao, valor))
    if _eh_energia(d):
        dados.gasto_energia_eletrica += abs(valor)
    if _eh_combustivel(d):
        dados.gasto_combustivel += abs(valor)


def _consolidar_receita(dados: DadosECF, candidatos: list) -> None:
    if not candidatos:
        dados.avisos.append(
            "Receita bruta não localizada automaticamente na DRE — informe o "
            "faturamento manualmente antes de calcular."
        )
        return
    com_bruta = [c for c in candidatos if "BRUTA" in _normalizar(c[0])]
    escolha = max(com_bruta or candidatos, key=lambda c: c[1])
    dados.receita_bruta = escolha[1]
    if not com_bruta:
        dados.avisos.append(
            f"Não havia linha explícita de 'Receita Bruta'; usei '{escolha[0]}'. "
            "Confira se corresponde à receita bruta total."
        )


# -- ponto de entrada ---------------------------------------------------------

def _parse_0020(campos: list[str], dados: DadosECF) -> None:
    """Lê o CNAE principal do registro 0020 (Parâmetros Complementares).

    Atenção: tanto o CNAE quanto o código de município do IBGE têm 7 dígitos.
    O município fica no registro 0000; por isso o CNAE é lido SOMENTE do 0020,
    evitando confusão. Pegamos o primeiro campo com exatamente 7 dígitos.
    Heurística: o leiaute varia por ano; quando o CNAE não estiver aqui, o
    fluxo continua usando a consulta por CNPJ (BrasilAPI) como caminho primário.
    """
    if dados.cnae:
        return
    for v in (c.strip() for c in campos[2:]):
        if re.fullmatch(r"\d{7}", v):
            dados.cnae = v
            break


def parse_ecf(conteudo) -> DadosECF:
    """Lê o conteúdo de um arquivo ECF e devolve os dados extraídos."""
    if isinstance(conteudo, (bytes, bytearray)):
        texto = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                texto = bytes(conteudo).decode(enc)
                break
            except UnicodeDecodeError:
                continue
        conteudo = texto if texto is not None else bytes(conteudo).decode("latin-1", errors="replace")

    dados = DadosECF()
    candidatos_receita: list = []

    for linha in conteudo.splitlines():
        linha = linha.strip()
        if not linha.startswith("|"):
            continue
        campos = linha.split("|")
        if len(campos) < 2:
            continue
        reg = campos[1].strip().upper()

        if reg == "0000":
            _parse_0000(campos, dados)
        elif reg == "0020":
            _parse_0020(campos, dados)
        elif reg == "L300":            # DRE do Lucro Real
            if dados.regime == "desconhecido":
                dados.regime = "lucro_real"
            _coletar_dre(campos, dados, candidatos_receita)
        elif reg == "P150":            # DRE do Lucro Presumido
            if dados.regime == "desconhecido":
                dados.regime = "lucro_presumido"
            _coletar_dre(campos, dados, candidatos_receita)

    _consolidar_receita(dados, candidatos_receita)
    return dados
ECF_EOF

echo
echo ">> Conferindo dependencias e imports..."
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
PY=python3
if [ -x .venv/bin/python ] && .venv/bin/python -c "import fastapi" >/dev/null 2>&1; then
  PY=.venv/bin/python
fi
$PY -c "import app.services.motor_ia as M; assert hasattr(M,'calcular_por_balanco'); print('>> motor_ia OK')"
$PY -c "import app.services.cnpj as C; assert hasattr(C,'cnae_para_categoria'); print('>> cnpj OK')"
$PY -c "import app.services.ecf as E; assert hasattr(E,'parse_ecf'); print('>> ecf OK')"
$PY -c "import app.api.routes.emissoes; print('>> emissoes.py importa sem erro')"
$PY -c "import app.api.main; print('>> app.api.main importa (a API vai subir)')"

pkill -f uvicorn >/dev/null 2>&1 && echo ">> uvicorn anterior encerrado" || true
sleep 1
echo ">> Subindo a API em http://localhost:8000   (Ctrl+C para parar)"
echo ">> No navegador: http://localhost:8000/docs com Ctrl+Shift+R (recarga forcada)"
exec $PY -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000
