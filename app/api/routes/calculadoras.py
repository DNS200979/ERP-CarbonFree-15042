"""
Endpoints atômicos das calculadoras do Motor IA.

Cada endpoint expõe UMA função pura do motor_ia.py, permitindo:
- Uso autônomo (Hub de calculadoras no frontend)
- Acoplamento contextual (botão 🧮 nos campos do Inventário GEE)
- Integração externa (SAP/TOTVS chamando uma calculadora isolada)

Todos os endpoints aceitam o parâmetro `salvar` (bool) para gravar
opcionalmente no histórico do usuário.
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
    listar_combustiveis,
    listar_refrigerantes,
    listar_setores_cadeia,
    FATORES_COMBUSTIVEIS,
    FATORES_REFRIGERANTES,
    FATORES_CADEIA_FORNECIMENTO,
    FATOR_ELETRICIDADE_SIN,
)

router = APIRouter()


# ── Schemas Pydantic ──────────────────────────────────────────────────────────

class CombustivelEntrada(BaseModel):
    combustivel: str = Field(..., description="Tipo: diesel, gasolina, etanol, gnv, glp, etc.")
    quantidade: float = Field(..., gt=0, description="Quantidade no consumo")
    escopo: int = Field(1, ge=1, le=3)
    categoria: str = Field("combustivel_estacionario",
                            description="combustivel_estacionario | combustivel_movel")
    salvar: bool = Field(False, description="Persistir no histórico do usuário")
    aplicado_em_emissao_id: Optional[int] = None
    campo_destino: Optional[str] = None


class EletricidadeEntrada(BaseModel):
    kwh: float = Field(..., gt=0, description="Consumo em quilowatts-hora")
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
                      entrada: dict, resultado, dados_extra: dict | None = None):
    """Persiste o cálculo no Supabase. Falha silenciosa para não bloquear o cálculo."""
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
        get_db_client().table("historico_calculos").insert(payload).execute()
    except Exception as e:
        print(f"[historico] Falha ao salvar: {e}")


def _serializar(resultado, tipo: str, escopo: int) -> dict:
    """Converte ResultadoCalculo (dataclass) em dict para a resposta REST."""
    return {
        "tipo": tipo,
        "escopo": escopo,
        "tco2e": round(resultado.tco2e, 6),
        "fator_utilizado": round(resultado.fator_utilizado or 0, 6),
        "unidade_fator": resultado.unidade_fator,
        "detalhamento": resultado.detalhamento or {},
        "nota": resultado.nota,
    }


# ── Endpoints atômicos ──────────────────────────────────────────────────────

@router.post("/combustivel", status_code=status.HTTP_200_OK,
             summary="Calcular emissão por consumo de combustível")
def calc_combustivel(dados: CombustivelEntrada, usuario: dict = Depends(usuario_autenticado)):
    """
    Calcula tCO₂e a partir do consumo de combustível.
    Fatores: IPCC AR6 (CO₂ + CH₄ × GWP + N₂O × GWP).
    """
    if dados.combustivel.lower().replace(" ", "_").replace("-", "_") not in FATORES_COMBUSTIVEIS:
        raise HTTPException(400, f"Combustível desconhecido. Disponíveis: {list(FATORES_COMBUSTIVEIS.keys())}")

    r = calcular_combustivel(dados.combustivel, dados.quantidade, dados.escopo, dados.categoria)
    if dados.salvar:
        _salvar_historico(usuario, "combustivel", dados.escopo,
                          {"combustivel": dados.combustivel, "quantidade": dados.quantidade,
                           "categoria": dados.categoria}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    return _serializar(r, "combustivel", dados.escopo)


@router.post("/eletricidade", status_code=status.HTTP_200_OK,
             summary="Calcular emissão por consumo elétrico")
def calc_eletricidade(dados: EletricidadeEntrada, usuario: dict = Depends(usuario_autenticado)):
    """Escopo 2 — fator do SIN brasileiro (MCTI 2024)."""
    r = calcular_eletricidade(dados.kwh)
    if dados.salvar:
        _salvar_historico(usuario, "eletricidade", 2,
                          {"kwh": dados.kwh}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    return _serializar(r, "eletricidade", 2)


@router.post("/refrigerante", status_code=status.HTTP_200_OK,
             summary="Calcular emissão fugitiva de refrigerante")
def calc_refrigerante(dados: RefrigeranteEntrada, usuario: dict = Depends(usuario_autenticado)):
    """Escopo 1 fugitivo — vazamento de gases HFC com GWP AR6."""
    r = calcular_refrigerante(dados.refrigerante, dados.kg_vazados)
    if dados.salvar:
        _salvar_historico(usuario, "refrigerante", 1,
                          {"refrigerante": dados.refrigerante, "kg_vazados": dados.kg_vazados}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    return _serializar(r, "refrigerante", 1)


@router.post("/cadeia", status_code=status.HTTP_200_OK,
             summary="Estimar emissão de cadeia de fornecimento (Escopo 3)")
def calc_cadeia(dados: CadeiaEntrada, usuario: dict = Depends(usuario_autenticado)):
    """Escopo 3 — estimativa EEIO por valor de compras."""
    r = calcular_cadeia_fornecimento(dados.setor, dados.valor_reais)
    if dados.salvar:
        _salvar_historico(usuario, "cadeia", 3,
                          {"setor": dados.setor, "valor_reais": dados.valor_reais}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    return _serializar(r, "cadeia", 3)


@router.post("/transporte", status_code=status.HTTP_200_OK,
             summary="Calcular emissão de transporte rodoviário (Escopo 3)")
def calc_transporte(dados: TransporteEntrada, usuario: dict = Depends(usuario_autenticado)):
    """Escopo 3 — fator tCO₂e/tkm (toneladas × km) por tipo de veículo."""
    r = calcular_transporte_rodoviario(dados.km, dados.veiculo, dados.toneladas)
    if dados.salvar:
        _salvar_historico(usuario, "transporte", 3,
                          {"km": dados.km, "toneladas": dados.toneladas, "veiculo": dados.veiculo}, r,
                          {"aplicado_em_emissao_id": dados.aplicado_em_emissao_id,
                           "campo_destino": dados.campo_destino})
    return _serializar(r, "transporte", 3)


# ── Endpoints auxiliares ────────────────────────────────────────────────────

@router.get("/catalogo", summary="Listar opções disponíveis em cada calculadora")
def catalogo(usuario: dict = Depends(usuario_autenticado)):
    """Devolve todas as opções aceitas (para popular selects no frontend)."""
    return {
        "combustiveis": [
            {"id": k, "label": v.get("desc", k), "unidade": v["uni"]}
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
        "veiculos_transporte": [
            "caminhao_diesel", "caminhao_leve", "van_diesel",
            "trem", "navio", "aviao_carga",
        ],
        "fator_eletricidade_sin": FATOR_ELETRICIDADE_SIN,
        "categorias_combustivel": ["combustivel_estacionario", "combustivel_movel"],
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
