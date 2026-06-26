"""
app/services/mrv_mensal.py

Módulo de MRV MENSAL — 1ª Etapa do SBCE (2027), Lei 15.042/2024.

Implementa o framework operacional do documento "SBCE — Estrutura de
Declaração Mensal & Emulador de Dados":

  • Catálogo dos 6 setores regulados da Etapa 1, cada um com os insumos /
    fluxos de processo e fatores de emissão médios dos layouts oficiais
    (SBCE-PAP-01, SBCE-ACO-02, SBCE-CIM-03, SBCE-ALU-04, SBCE-PET-0506,
    SBCE-AER-07).

  • Balanço de massa do fechamento mensal:
        Estoque Inicial + Entradas (NF-e) − Estoque Final = Consumo Mensal

  • Conciliação fiscal: o consumo apurado deve bater com a quantidade
    reportada no Bloco K (SPED Fiscal). O módulo calcula a divergência
    percentual por insumo e classifica o fechamento como CONCILIADO,
    DIVERGENTE ou SEM_BLOCO_K (quando o usuário não informou o Bloco K).

  • Mapeamento de cada insumo para os campos do inventário anual
    (e1_estacionario, e1_processos, e1_movel, e1_fugitivas, e2_eletrica),
    permitindo CONSOLIDAR os 12 fechamentos mensais no mesmo formato que
    POST /api/v1/emissoes/ já aceita — a automação mensal alimenta a anual.

Emissões biogênicas (licor negro, biomassa) são RASTREADAS (memória de
cálculo) mas contam 0,000 tCO2e, conforme isenção do SBCE.

Sem dependências externas além da biblioteca padrão.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────────────────
# Catálogo dos setores da 1ª Etapa (2027) — fatores do framework SBCE
# fator em tCO2e por unidade | escopo: 1, 2 ou "biogenico"
# campo_emissao: campo do inventário anual (Emissao) que recebe o valor
# medicao_direta: True quando o balanço de massa de estoque não se aplica
#                 (ex.: produção de clínquer, MWh, m³ de flare, kg fugitivos)
# ─────────────────────────────────────────────────────────────────────────────

SETORES_ETAPA1: dict[str, dict] = {
    "papel_celulose": {
        "layout": "SBCE-PAP-01",
        "rotulo": "Papel e Celulose",
        "descricao": "Combustíveis para geração de vapor/energia e emissões de processo na caustificação.",
        "insumos": {
            "licor_negro": {
                "rotulo": "Licor Negro (Black Liquor)",
                "tipo_emissao": "Combustão (Biogênica)",
                "unidade": "t", "fator": 0.0, "escopo": "biogenico",
                "campo_emissao": None, "medicao_direta": False,
                "nota": "Biogênico — isento SBCE; rastreado para memória de cálculo.",
            },
            "oleo_combustivel_bte": {
                "rotulo": "Óleo Combustível BTE",
                "tipo_emissao": "Combustão Estacionária",
                "unidade": "t", "fator": 3.180, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": False,
                "nota": "Fator médio 3,180 tCO2/t.",
            },
            "gas_natural_industrial": {
                "rotulo": "Gás Natural Industrial",
                "tipo_emissao": "Combustão Caldeiras",
                "unidade": "m³", "fator": 0.002, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": False,
                "nota": "Fator médio 0,002 tCO2/m³.",
            },
            "calcario_caustificacao": {
                "rotulo": "Calcário (Caustificação)",
                "tipo_emissao": "Emissão de Processo",
                "unidade": "t", "fator": 0.440, "escopo": 1,
                "campo_emissao": "e1_processos", "medicao_direta": False,
                "nota": "Fator médio 0,440 tCO2/t.",
            },
        },
    },

    "ferro_aco": {
        "layout": "SBCE-ACO-02",
        "rotulo": "Ferro e Aço (Siderurgia)",
        "descricao": "Agentes redutores (coque) geram altas taxas de emissão de processo e combustão combinadas.",
        "insumos": {
            "coque_metalurgico": {
                "rotulo": "Coque Metalúrgico",
                "tipo_emissao": "Agente Redutor / Processo",
                "unidade": "t", "fator": 3.150, "escopo": 1,
                "campo_emissao": "e1_processos", "medicao_direta": False,
                "nota": "Fator médio 3,150 tCO2/t.",
            },
            "carvao_mineral_pci": {
                "rotulo": "Carvão Mineral (Injeção PCI)",
                "tipo_emissao": "Combustão Alto Forno",
                "unidade": "t", "fator": 2.420, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": False,
                "nota": "Fator médio 2,420 tCO2/t.",
            },
            "eletrodos_grafite": {
                "rotulo": "Eletrodos de Grafite",
                "tipo_emissao": "Consumo de Processo (Aciaria)",
                "unidade": "t", "fator": 3.600, "escopo": 1,
                "campo_emissao": "e1_processos", "medicao_direta": False,
                "nota": "Fator médio 3,600 tCO2/t.",
            },
            "gas_alto_forno": {
                "rotulo": "Gás de Alto Forno (Recuperado)",
                "tipo_emissao": "Combustão / Energia",
                "unidade": "m³", "fator": 0.0013, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": True,
                "nota": "Fator médio 0,0013 tCO2/m³ — medição por telemetria de vazão.",
            },
        },
    },

    "cimento": {
        "layout": "SBCE-CIM-03",
        "rotulo": "Cimento",
        "descricao": "Maior parte das emissões advém da descarbonatação do calcário (clínquer) e do coprocessamento.",
        "insumos": {
            "descarbonatacao_calcario": {
                "rotulo": "Descarbonatação de Calcário",
                "tipo_emissao": "Emissão de Processo (Clínquer)",
                "unidade": "t clínquer", "fator": 0.520, "escopo": 1,
                "campo_emissao": "e1_processos", "medicao_direta": True,
                "nota": "Fator 0,520 tCO2/t de clínquer produzido (Bloco K — produto acabado).",
            },
            "petcoke": {
                "rotulo": "Coque de Petróleo (Petcoke)",
                "tipo_emissao": "Combustão Térmica Forno",
                "unidade": "t", "fator": 3.250, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": False,
                "nota": "Fator médio 3,250 tCO2/t.",
            },
            "pneus_inserviveis": {
                "rotulo": "Pneus Inservíveis (Coprocessamento)",
                "tipo_emissao": "Combustão Alternativa (Fóssil)",
                "unidade": "t", "fator": 2.200, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": False,
                "nota": "Fator médio 2,200 tCO2/t.",
            },
            "biomassa_residuos": {
                "rotulo": "Biomassa / Resíduos Agrícolas",
                "tipo_emissao": "Combustão Alternativa (Biogênica)",
                "unidade": "t", "fator": 0.0, "escopo": "biogenico",
                "campo_emissao": None, "medicao_direta": False,
                "nota": "Biogênico — isento SBCE; rastreado para memória de cálculo.",
            },
        },
    },

    "aluminio": {
        "layout": "SBCE-ALU-04",
        "rotulo": "Alumínio Primário",
        "descricao": "Consumo de anodos de carbono no processo Hall-Héroult e uso massivo de energia elétrica.",
        "insumos": {
            "anodos_carbono": {
                "rotulo": "Anodos de Carbono (Pré-cozidos)",
                "tipo_emissao": "Emissão de Processo (Redução)",
                "unidade": "t", "fator": 1.550, "escopo": 1,
                "campo_emissao": "e1_processos", "medicao_direta": False,
                "nota": "Fator médio 1,550 tCO2/t.",
            },
            "glp_refino": {
                "rotulo": "Combustível de Refino (Gás GLP)",
                "tipo_emissao": "Combustão Calcinadores",
                "unidade": "t", "fator": 2.980, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": False,
                "nota": "Fator médio 2,980 tCO2/t.",
            },
            "energia_grid_sin": {
                "rotulo": "Consumo de Energia (GRID SIN)",
                "tipo_emissao": "Escopo 2 (Indireto)",
                "unidade": "MWh", "fator": 0.0420, "escopo": 2,
                "campo_emissao": "e2_eletrica", "medicao_direta": True,
                "nota": "Fator 0,0420 tCO2/MWh — fatura de energia / contratos ACL (XML NF-e entrada).",
            },
        },
    },

    "petroleo_gas": {
        "layout": "SBCE-PET-0506",
        "rotulo": "Exploração, Produção e Refino de Petróleo e Gás",
        "descricao": "Foco em flaring, emissões fugitivas (venting) e consumo interno de refinaria.",
        "insumos": {
            "flaring": {
                "rotulo": "Queima de Gás em Flare (Flaring)",
                "tipo_emissao": "Queima de Rotina / Segurança",
                "unidade": "m³", "fator": 0.0024, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": True,
                "nota": "Fator 0,0024 tCO2/m³ — telemetria de vazão do flare.",
            },
            "gas_refinaria": {
                "rotulo": "Gás de Refinaria (Self-consumption)",
                "tipo_emissao": "Combustão em Processo",
                "unidade": "t", "fator": 2.850, "escopo": 1,
                "campo_emissao": "e1_estacionario", "medicao_direta": False,
                "nota": "Fator médio 2,850 tCO2/t.",
            },
            "fugitivas_metano": {
                "rotulo": "Emissões Fugitivas (Metano — CH₄)",
                "tipo_emissao": "Fugitiva (Convertida para CO₂e)",
                "unidade": "t CH₄", "fator": 28.0, "escopo": 1,
                "campo_emissao": "e1_fugitivas", "medicao_direta": True,
                "nota": "GWP CH₄ = 28 (conversão para tCO2e).",
            },
        },
    },

    "transporte_aereo": {
        "layout": "SBCE-AER-07",
        "rotulo": "Transporte Aéreo",
        "descricao": "Emissões móveis: volume total de QAV/GAV queimado em rotas domésticas reguladas.",
        "insumos": {
            "qav": {
                "rotulo": "Querosene de Aviação (QAV)",
                "tipo_emissao": "Combustão Móvel (Rotas Nac.)",
                "unidade": "L", "fator": 0.00252, "escopo": 1,
                "campo_emissao": "e1_movel", "medicao_direta": False,
                "nota": "Fator 0,00252 tCO2/L.",
            },
            "gav": {
                "rotulo": "Gasolina de Aviação (GAV)",
                "tipo_emissao": "Combustão Móvel (Piston)",
                "unidade": "L", "fator": 0.00221, "escopo": 1,
                "campo_emissao": "e1_movel", "medicao_direta": False,
                "nota": "Fator 0,00221 tCO2/L.",
            },
        },
    },
}

# Tolerância padrão da conciliação consumo apurado × Bloco K (em %)
TOLERANCIA_BLOCO_K_PCT = 2.0

MESES_PT = {
    1: "Janeiro", 2: "Fevereiro", 3: "Março", 4: "Abril", 5: "Maio",
    6: "Junho", 7: "Julho", 8: "Agosto", 9: "Setembro", 10: "Outubro",
    11: "Novembro", 12: "Dezembro",
}


# ─────────────────────────────────────────────────────────────────────────────
# Estruturas de resultado
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ItemFechamento:
    """Linha do fechamento mensal de um insumo, já calculada."""
    insumo: str
    rotulo: str
    tipo_emissao: str
    unidade: str
    fator: float
    escopo: str | int
    campo_emissao: str | None

    estoque_inicial: float = 0.0
    entradas_nfe: float = 0.0
    estoque_final: float = 0.0
    consumo_informado: float | None = None   # medição direta (override do balanço)
    bloco_k_consumo: float | None = None     # quantidade reportada no Bloco K

    consumo_apurado: float = 0.0             # resultado do balanço (ou medição)
    origem_consumo: str = "balanco_massa"    # 'balanco_massa' | 'medicao_direta'
    emissao_tco2e: float = 0.0
    divergencia_pct: float | None = None
    status_conciliacao: str = "SEM_BLOCO_K"  # CONCILIADO | DIVERGENTE | SEM_BLOCO_K
    avisos: list[str] = field(default_factory=list)

    def para_dict(self) -> dict:
        return {
            "insumo": self.insumo,
            "rotulo": self.rotulo,
            "tipo_emissao": self.tipo_emissao,
            "unidade": self.unidade,
            "fator": self.fator,
            "escopo": self.escopo,
            "campo_emissao": self.campo_emissao,
            "estoque_inicial": round(self.estoque_inicial, 6),
            "entradas_nfe": round(self.entradas_nfe, 6),
            "estoque_final": round(self.estoque_final, 6),
            "consumo_informado": self.consumo_informado,
            "bloco_k_consumo": self.bloco_k_consumo,
            "consumo_apurado": round(self.consumo_apurado, 6),
            "origem_consumo": self.origem_consumo,
            "emissao_tco2e": round(self.emissao_tco2e, 6),
            "divergencia_pct": (round(self.divergencia_pct, 4)
                                if self.divergencia_pct is not None else None),
            "status_conciliacao": self.status_conciliacao,
            "avisos": self.avisos,
        }


@dataclass
class FechamentoMensal:
    """Resultado completo do fechamento de um mês para um setor."""
    setor: str
    layout: str
    rotulo_setor: str
    ano: int
    mes: int
    itens: list[ItemFechamento] = field(default_factory=list)
    tolerancia_pct: float = TOLERANCIA_BLOCO_K_PCT

    @property
    def total_e1(self) -> float:
        return round(sum(i.emissao_tco2e for i in self.itens if i.escopo == 1), 6)

    @property
    def total_e2(self) -> float:
        return round(sum(i.emissao_tco2e for i in self.itens if i.escopo == 2), 6)

    @property
    def total_biogenico_qtd(self) -> float:
        """Quantidade física consumida de insumos biogênicos (rastreio)."""
        return round(sum(i.consumo_apurado for i in self.itens
                         if i.escopo == "biogenico"), 6)

    @property
    def total_tco2e(self) -> float:
        return round(self.total_e1 + self.total_e2, 6)

    @property
    def divergencia_max_pct(self) -> float | None:
        divs = [abs(i.divergencia_pct) for i in self.itens
                if i.divergencia_pct is not None]
        return round(max(divs), 4) if divs else None

    @property
    def status_conciliacao(self) -> str:
        sts = [i.status_conciliacao for i in self.itens]
        if "DIVERGENTE" in sts:
            return "DIVERGENTE"
        if "CONCILIADO" in sts:
            return "CONCILIADO"
        return "SEM_BLOCO_K"

    def campos_emissao(self) -> dict[str, float]:
        """Distribui as emissões do mês nos campos do inventário anual."""
        campos = {
            "e1_estacionario": 0.0, "e1_movel": 0.0,
            "e1_processos": 0.0, "e1_fugitivas": 0.0,
            "e2_eletrica": 0.0, "e2_vapor": 0.0,
            "e3_cadeia": 0.0, "e3_transporte": 0.0, "e3_residuos": 0.0,
        }
        for i in self.itens:
            if i.campo_emissao and i.campo_emissao in campos:
                campos[i.campo_emissao] += i.emissao_tco2e
        return {k: round(v, 6) for k, v in campos.items()}

    def para_dict(self) -> dict:
        return {
            "setor": self.setor,
            "layout": self.layout,
            "rotulo_setor": self.rotulo_setor,
            "ano": self.ano,
            "mes": self.mes,
            "mes_nome": MESES_PT.get(self.mes, str(self.mes)),
            "tolerancia_pct": self.tolerancia_pct,
            "itens": [i.para_dict() for i in self.itens],
            "total_e1": self.total_e1,
            "total_e2": self.total_e2,
            "total_tco2e": self.total_tco2e,
            "total_biogenico_qtd": self.total_biogenico_qtd,
            "divergencia_max_pct": self.divergencia_max_pct,
            "status_conciliacao": self.status_conciliacao,
            "campos_emissao": self.campos_emissao(),
        }

    def hash_auditoria(self) -> str:
        """Hash SHA-256 da memória de cálculo (trilha de auditoria imutável)."""
        payload = json.dumps(self.para_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# Funções públicas
# ─────────────────────────────────────────────────────────────────────────────

def listar_setores() -> list[dict]:
    """Catálogo completo para popular o frontend (selects + tabela de insumos)."""
    out = []
    for chave, s in SETORES_ETAPA1.items():
        out.append({
            "chave": chave,
            "layout": s["layout"],
            "rotulo": s["rotulo"],
            "descricao": s["descricao"],
            "insumos": [
                {"chave": ik, **iv} for ik, iv in s["insumos"].items()
            ],
        })
    return out


def calcular_fechamento(
    setor: str,
    ano: int,
    mes: int,
    itens: list[dict],
    tolerancia_pct: float = TOLERANCIA_BLOCO_K_PCT,
) -> FechamentoMensal:
    """
    Calcula o fechamento mensal de um setor.

    Cada item de `itens` é um dict:
        {
          "insumo": "petcoke",                # chave do catálogo do setor
          "estoque_inicial": 1200.0,          # balanço de massa
          "entradas_nfe": 8000.0,
          "estoque_final": 800.0,
          "consumo_informado": null,          # opcional: medição direta
          "bloco_k_consumo": 8400.0           # opcional: conciliação fiscal
        }

    Regras:
      • consumo_informado > 0 tem prioridade (medição direta — telemetria,
        fatura de energia, produção de clínquer do Bloco K, etc.);
      • senão, consumo = estoque_inicial + entradas_nfe − estoque_final;
      • consumo negativo gera aviso e é truncado em 0 (estoque inconsistente);
      • divergência = (consumo_apurado − bloco_k) / bloco_k × 100.
    """
    chave_setor = (setor or "").strip().lower().replace(" ", "_").replace("-", "_")
    cfg = SETORES_ETAPA1.get(chave_setor)
    if not cfg:
        raise ValueError(
            f"Setor '{setor}' não pertence à 1ª Etapa do SBCE. "
            f"Disponíveis: {list(SETORES_ETAPA1.keys())}"
        )
    if not (1 <= int(mes) <= 12):
        raise ValueError("Mês deve estar entre 1 e 12.")
    if not (2000 <= int(ano) <= 2100):
        raise ValueError("Ano de referência inválido.")

    fech = FechamentoMensal(
        setor=chave_setor,
        layout=cfg["layout"],
        rotulo_setor=cfg["rotulo"],
        ano=int(ano),
        mes=int(mes),
        tolerancia_pct=float(tolerancia_pct),
    )

    catalogo = cfg["insumos"]

    for entrada in itens:
        ik = (entrada.get("insumo") or "").strip()
        meta = catalogo.get(ik)
        if not meta:
            # Insumo fora do layout do setor: ignorado com transparência
            item = ItemFechamento(
                insumo=ik, rotulo=ik, tipo_emissao="—", unidade="—",
                fator=0.0, escopo=0, campo_emissao=None,
            )
            item.avisos.append(
                f"Insumo '{ik}' não pertence ao layout {cfg['layout']} — ignorado."
            )
            fech.itens.append(item)
            continue

        item = ItemFechamento(
            insumo=ik,
            rotulo=meta["rotulo"],
            tipo_emissao=meta["tipo_emissao"],
            unidade=meta["unidade"],
            fator=meta["fator"],
            escopo=meta["escopo"],
            campo_emissao=meta["campo_emissao"],
            estoque_inicial=float(entrada.get("estoque_inicial") or 0),
            entradas_nfe=float(entrada.get("entradas_nfe") or 0),
            estoque_final=float(entrada.get("estoque_final") or 0),
        )

        ci = entrada.get("consumo_informado")
        item.consumo_informado = float(ci) if ci not in (None, "", 0) else None
        bk = entrada.get("bloco_k_consumo")
        item.bloco_k_consumo = float(bk) if bk not in (None, "") else None

        # 1) Consumo: medição direta > balanço de massa
        if item.consumo_informado is not None and item.consumo_informado > 0:
            item.consumo_apurado = item.consumo_informado
            item.origem_consumo = "medicao_direta"
        else:
            bruto = item.estoque_inicial + item.entradas_nfe - item.estoque_final
            if bruto < 0:
                item.avisos.append(
                    "Balanço de massa negativo (estoque final maior que "
                    "inicial + entradas). Consumo truncado em 0 — revise os "
                    "estoques ou as NF-e de entrada."
                )
                bruto = 0.0
            item.consumo_apurado = bruto
            item.origem_consumo = "balanco_massa"
            if meta.get("medicao_direta") and item.consumo_apurado == 0:
                item.avisos.append(
                    "Este insumo normalmente é apurado por medição direta "
                    "(telemetria/fatura) — informe o consumo medido."
                )

        # 2) Emissão
        item.emissao_tco2e = round(item.consumo_apurado * item.fator, 6)

        # 3) Conciliação com Bloco K
        if item.bloco_k_consumo is not None and item.bloco_k_consumo > 0:
            div = ((item.consumo_apurado - item.bloco_k_consumo)
                   / item.bloco_k_consumo * 100.0)
            item.divergencia_pct = div
            if abs(div) <= tolerancia_pct:
                item.status_conciliacao = "CONCILIADO"
            else:
                item.status_conciliacao = "DIVERGENTE"
                item.avisos.append(
                    f"Consumo apurado diverge {div:+.2f}% do Bloco K "
                    f"(tolerância ±{tolerancia_pct}%). Risco de passivo em "
                    "cruzamento RFB (SPED/EFD/NF-e) — corrija estoques ou "
                    "retifique o Bloco K."
                )
        else:
            item.status_conciliacao = "SEM_BLOCO_K"

        fech.itens.append(item)

    return fech


def consolidar_ano(fechamentos: list[dict]) -> dict:
    """
    Consolida os fechamentos mensais (registros do banco) de um ano em um
    inventário anual no MESMO formato aceito por POST /api/v1/emissoes/.

    `fechamentos` = lista de rows da tabela fechamentos_mensais (cada row
    contém 'campos_emissao' dentro do JSON 'resultado', além de mes/setor).
    """
    campos = {
        "e1_estacionario": 0.0, "e1_movel": 0.0,
        "e1_processos": 0.0, "e1_fugitivas": 0.0,
        "e2_eletrica": 0.0, "e2_vapor": 0.0,
        "e3_cadeia": 0.0, "e3_transporte": 0.0, "e3_residuos": 0.0,
    }
    meses_presentes: set[int] = set()
    setores: set[str] = set()
    total = 0.0
    biogenico = 0.0
    divergentes = 0

    por_mes: dict[int, float] = {m: 0.0 for m in range(1, 13)}

    for f in fechamentos:
        res = f.get("resultado") or {}
        ce = res.get("campos_emissao") or {}
        for k in campos:
            campos[k] += float(ce.get(k) or 0)
        m = int(f.get("mes") or 0)
        if 1 <= m <= 12:
            meses_presentes.add(m)
            por_mes[m] += float(f.get("total_tco2e") or 0)
        setores.add(f.get("setor") or "?")
        total += float(f.get("total_tco2e") or 0)
        biogenico += float(res.get("total_biogenico_qtd") or 0)
        if f.get("status_conciliacao") == "DIVERGENTE":
            divergentes += 1

    faltantes = sorted(set(range(1, 13)) - meses_presentes)

    if total < 10_000:
        status = "ISENTO"
    elif total <= 25_000:
        status = "MONITORAMENTO OBRIGATÓRIO"
    else:
        status = "CONFORMIDADE TOTAL OBRIGATÓRIA"

    return {
        "campos_emissao": {k: round(v, 6) for k, v in campos.items()},
        "total_tco2e": round(total, 6),
        "total_biogenico_qtd": round(biogenico, 6),
        "status_projetado": status,
        "meses_presentes": sorted(meses_presentes),
        "meses_faltantes": faltantes,
        "completo": not faltantes,
        "fechamentos_divergentes": divergentes,
        "setores": sorted(setores),
        "serie_mensal": [
            {"mes": m, "mes_nome": MESES_PT[m], "tco2e": round(por_mes[m], 6)}
            for m in range(1, 13)
        ],
    }
