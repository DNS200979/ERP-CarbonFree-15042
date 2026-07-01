"""
Endpoints atômicos das calculadoras do Motor IA.

Cada endpoint expõe UMA função pura do motor_ia.py, permitindo:
- Uso autônomo (Hub de calculadoras no frontend)
- Acoplamento contextual (botão 🧮 nos campos do Inventário GEE)
- Integração externa (SAP/TOTVS chamando uma calculadora isolada)

Esta versão acrescenta a RASTREABILIDADE "grau Inmetro / ISO 14064": cada
resposta traz a quebra por gás, a fonte oficial do fator, o conjunto de GWP, o
nível metodológico (Tier), a incerteza indicativa e a MEMÓRIA DE CÁLCULO
passo-a-passo (evidência de verificação).

Todos os endpoints aceitam `salvar` (bool) para gravar no histórico do usuário.
"""

from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.auth import usuario_autenticado
from app.database.client import get_db_client
from app.services.motor_ia import (
    calcular_combustivel,
    calcular_eletricidade,
    calcular_refrigerante,
    calcular_cadeia_fornecimento,
    calcular_transporte_rodoviario,
    listar_anos_eletricidade,
    FATORES_COMBUSTIVEIS,
    FATORES_REFRIGERANTES,
    FATORES_CADEIA_FORNECIMENTO,
    FATORES_TRANSPORTE_TKM,
    FATOR_ELETRICIDADE_SIN,
    ANO_ELETRICIDADE_PADRAO,
    GWP_SETS,
    FONTES,
    REF_VERIFICACAO,
)

router = APIRouter()


# ── Schemas Pydantic ──────────────────────────────────────────────────────────

class CombustivelEntrada(BaseModel):
    combustivel: str = Field(..., description="Tipo: diesel, gasolina, etanol, gnv, glp, etc.")
    quantidade: float = Field(..., gt=0, description="Quantidade no consumo")
    escopo: int = Field(1, ge=1, le=3)
    categoria: str = Field("combustivel_estacionario",
                            description="combustivel_estacionario | combustivel_movel")
    gwp_set: str = Field("AR6", description="Conjunto de GWP: AR6 (padrão) ou AR5")
    salvar: bool = Field(False, description="Persistir no histórico do usuário")
    aplicado_em_emissao_id: Optional[int] = None
    campo_destino: Optional[str] = None


class EletricidadeEntrada(BaseModel):
    kwh: float = Field(..., gt=0, description="Consumo em quilowatts-hora")
    ano: Optional[int] = Field(None, description="Ano do fator médio do SIN (MCTI/SIRENE)")
    fator_customizado: Optional[float] = Field(
        None, description="Fator tCO₂e/MWh manual (ex.: contrato mercado livre / I-REC)")
    base: str = Field("location", description="location (grid médio) | market (contratual)")
    salvar: bool = False
    aplicado_em_emissao_id: Optional[int] = None
    campo_destino: Optional[str] = None


class RefrigeranteEntrada(BaseModel):
    refrigerante: str = Field(..., description="Ex: r-134a, r-410a, r-22")
    kg_vazados: float = Field(..., gt=0)
    salvar: bool = False
    aplicado_em_emissao_id: Optional[int] = None
    campo_destino: Optional[str] = None


class CadeiaEntrada(BaseModel):
    setor: str = Field(..., description="Ex: agropecuaria, industria_alimenticia")
    valor_reais: float = Field(..., gt=0)
    salvar: bool = False
    aplicado_em_emissao_id: Optional[int] = None
    campo_destino: Optional[str] = None


class TransporteEntrada(BaseModel):
    km: float = Field(..., gt=0)
    toneladas: float = Field(1.0, gt=0)
    veiculo: str = Field("caminhao_diesel",
                          description="caminhao_diesel | caminhao_leve | van_diesel | trem | navio | aviao_carga")
    salvar: bool = False
    aplicado_em_emissao_id: Optional[int] = None
    campo_destino: Optional[str] = None


# ── Helper: salvar no histórico ──────────────────────────────────────────────

def _salvar_historico(usuario: dict, tipo: str, escopo: int,
                      entrada: dict, resultado, dados_extra: dict | None = None) -> Optional[int]:
    """Persiste o cálculo no Supabase. Falha silenciosa para não bloquear o cálculo.

    Retorna o id da linha gravada (ou None se falhar), para permitir anexar
    evidências ao cálculo logo em seguida.
    """
    try:
        payload = {
            "usuario_id": usuario["id"],
            "tipo": tipo,
            "escopo": escopo,
            "entrada": entrada,
            "tco2e": float(resultado.tco2e),
            "fator_utilizado": float(resultado.fator_utilizado or 0),
            "unidade_fator": resultado.unidade_fator,
            "detalhamento": resultado.detalhamento or {},
            "nota": resultado.nota,
        }
        if dados_extra:
            payload.update(dados_extra)
        resp = get_db_client().table("historico_calculos").insert(payload).execute()
        return resp.data[0]["id"] if resp.data else None
    except Exception as e:
        print(f"[historico] Falha ao salvar: {e}")
        return None


def _serializar(resultado, tipo: str, escopo: int) -> dict:
    """Converte ResultadoCalculo (dataclass) em dict para a resposta REST.

    Inclui a camada de rastreabilidade (gases, fonte, GWP, Tier, incerteza,
    memória de cálculo) sem quebrar os campos antigos.
    """
    return {
        "tipo": tipo,
        "escopo": escopo,
        "tco2e": round(resultado.tco2e, 6),
        "fator_utilizado": round(resultado.fator_utilizado or 0, 9),
        "unidade_fator": resultado.unidade_fator,
        "detalhamento": resultado.detalhamento or {},
        "nota": resultado.nota,
        # ── camada de auditoria ──
        "gases": resultado.gases or [],
        "fonte_fator": resultado.fonte_fator,
        "referencia_normativa": resultado.referencia_normativa,
        "gwp_set": resultado.gwp_set,
        "nivel_tier": resultado.nivel_tier,
        "qualidade_dado": resultado.qualidade_dado,
        "incerteza_pct": resultado.incerteza_pct,
        "co2_biogenico_t": round(resultado.co2_biogenico_t or 0, 6),
        "memoria_calculo": resultado.memoria_calculo or [],
    }


# ── Endpoints atômicos ──────────────────────────────────────────────────────

@router.post("/combustivel", status_code=status.HTTP_200_OK,
             summary="Calcular emissão por consumo de combustível")
def calc_combustivel(dados: CombustivelEntrada, usuario: dict = Depends(usuario_autenticado)):
    """tCO₂e a partir do consumo de combustível. Fatores IPCC/GHG Protocol Brasil,
    GWP AR6 (CO₂ + CH₄×GWP + N₂O×GWP). Combustível biogênico tem CO₂ reportado à parte."""
    if dados.combustivel.lower().replace(" ", "_").replace("-", "_") not in FATORES_COMBUSTIVEIS:
        raise HTTPException(400, f"Combustível desconhecido. Disponíveis: {list(FATORES_COMBUSTIVEIS.keys())}")
    if dados.gwp_set not in GWP_SETS:
        raise HTTPException(400, f"Conjunto de GWP inválido. Use: {list(GWP_SETS.keys())}")

    r = calcular_combustivel(dados.combustivel, dados.quantidade, dados.escopo,
                             dados.categoria, dados.gwp_set)
    historico_id = None
    if dados.salvar:
        historico_id = _salvar_historico(usuario, "combustivel", dados.escopo,
                          {"combustivel": dados.combustivel, "quantidade": dados.quantidade,
                           "categoria": dados.categoria, "gwp_set": dados.gwp_set}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    out = _serializar(r, "combustivel", dados.escopo)
    out["historico_id"] = historico_id
    return out


@router.post("/eletricidade", status_code=status.HTTP_200_OK,
             summary="Calcular emissão por consumo elétrico")
def calc_eletricidade(dados: EletricidadeEntrada, usuario: dict = Depends(usuario_autenticado)):
    """Escopo 2 — fator MÉDIO do SIN por ano (MCTI/SIRENE), location-based por
    padrão. Aceita fator manual/market-based (contrato, I-REC)."""
    r = calcular_eletricidade(dados.kwh, ano=dados.ano,
                              fator_customizado=dados.fator_customizado, base=dados.base)
    historico_id = None
    if dados.salvar:
        historico_id = _salvar_historico(usuario, "eletricidade", 2,
                          {"kwh": dados.kwh, "ano": dados.ano, "base": dados.base,
                           "fator_customizado": dados.fator_customizado}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    out = _serializar(r, "eletricidade", 2)
    out["historico_id"] = historico_id
    return out


@router.post("/refrigerante", status_code=status.HTTP_200_OK,
             summary="Calcular emissão fugitiva de refrigerante")
def calc_refrigerante(dados: RefrigeranteEntrada, usuario: dict = Depends(usuario_autenticado)):
    """Escopo 1 fugitivo — vazamento de gases HFC com GWP 100 anos."""
    r = calcular_refrigerante(dados.refrigerante, dados.kg_vazados)
    historico_id = None
    if dados.salvar:
        historico_id = _salvar_historico(usuario, "refrigerante", 1,
                          {"refrigerante": dados.refrigerante, "kg_vazados": dados.kg_vazados}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    out = _serializar(r, "refrigerante", 1)
    out["historico_id"] = historico_id
    return out


@router.post("/cadeia", status_code=status.HTTP_200_OK,
             summary="Estimar emissão de cadeia de fornecimento (Escopo 3)")
def calc_cadeia(dados: CadeiaEntrada, usuario: dict = Depends(usuario_autenticado)):
    """Escopo 3 — estimativa EEIO (spend-based) por valor de compras. TRIAGEM."""
    r = calcular_cadeia_fornecimento(dados.setor, dados.valor_reais)
    historico_id = None
    if dados.salvar:
        historico_id = _salvar_historico(usuario, "cadeia", 3,
                          {"setor": dados.setor, "valor_reais": dados.valor_reais}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    out = _serializar(r, "cadeia", 3)
    out["historico_id"] = historico_id
    return out


@router.post("/transporte", status_code=status.HTTP_200_OK,
             summary="Calcular emissão de transporte rodoviário (Escopo 3)")
def calc_transporte(dados: TransporteEntrada, usuario: dict = Depends(usuario_autenticado)):
    """Escopo 3 — fator tCO₂e/t·km (toneladas × km) por tipo de veículo."""
    r = calcular_transporte_rodoviario(dados.km, dados.veiculo, dados.toneladas)
    historico_id = None
    if dados.salvar:
        historico_id = _salvar_historico(usuario, "transporte", 3,
                          {"km": dados.km, "toneladas": dados.toneladas, "veiculo": dados.veiculo}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    out = _serializar(r, "transporte", 3)
    out["historico_id"] = historico_id
    return out


# ── Endpoints auxiliares ────────────────────────────────────────────────────

@router.get("/catalogo", summary="Listar opções disponíveis em cada calculadora")
def catalogo(usuario: dict = Depends(usuario_autenticado)):
    """Devolve todas as opções aceitas (para popular selects no frontend),
    incluindo a fonte oficial de cada fator e os anos de eletricidade."""
    return {
        "combustiveis": [
            {"id": k, "label": v.get("desc", k), "unidade": v["uni"],
             "biogenico": v.get("bio", False), "fonte": FONTES.get(v.get("fonte", ""), "")}
            for k, v in FATORES_COMBUSTIVEIS.items()
        ],
        "refrigerantes": [
            {"id": k, "label": k.upper(), "gwp": v}
            for k, v in FATORES_REFRIGERANTES.items()
        ],
        "setores_cadeia": [
            {"id": k, "label": k.replace("_", " ").title(), "fator_tco2e_por_mil_reais": v}
            for k, v in FATORES_CADEIA_FORNECIMENTO.items()
        ],
        "veiculos_transporte": list(FATORES_TRANSPORTE_TKM.keys()),
        "fator_eletricidade_sin": FATOR_ELETRICIDADE_SIN,
        "ano_eletricidade_padrao": ANO_ELETRICIDADE_PADRAO,
        "anos_eletricidade": listar_anos_eletricidade(),
        "gwp_sets": {k: {kk: vv for kk, vv in v.items() if kk != "fonte"} for k, v in GWP_SETS.items()},
        "categorias_combustivel": ["combustivel_estacionario", "combustivel_movel"],
        "referencia_normativa": REF_VERIFICACAO,
        "fontes": FONTES,
    }


@router.get("/historico", summary="Listar histórico de cálculos do usuário")
def listar_historico(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    tipo: Optional[str] = Query(None, description="Filtrar por tipo de cálculo"),
    usuario: dict = Depends(usuario_autenticado),
):
    """Retorna os cálculos salvos pelo usuário, mais recentes primeiro."""
    try:
        q = (
            get_db_client()
            .table("historico_calculos")
            .select("id,tipo,escopo,entrada,tco2e,unidade_fator,nota,aplicado_em_emissao_id,campo_destino,criado_em")
            .or_(f"usuario_id.eq.{usuario['id']},usuario_id.is.null")
            .order("criado_em", desc=True)
            .range(offset, offset + limit - 1)
        )
        if tipo:
            q = q.eq("tipo", tipo)
        resp = q.execute()
        return {"total": len(resp.data), "dados": resp.data}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/historico/{calc_id}", summary="Remover um cálculo do histórico")
def remover_historico(calc_id: int, usuario: dict = Depends(usuario_autenticado)):
    try:
        get_db_client().table("historico_calculos").delete().eq("id", calc_id).execute()
        return {"removido": calc_id}
    except Exception as e:
        raise HTTPException(500, str(e))
