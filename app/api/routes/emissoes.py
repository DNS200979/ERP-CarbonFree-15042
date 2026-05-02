"""
Endpoints de Emissões de Carbono.
Compatível com integração SAP/TOTVS — aceita payload padrão GHG Protocol.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.auth import usuario_autenticado
from app.database.client import get_db_client
from app.services.motor_ia import calcular_inventario

router = APIRouter()


# ── Schemas Pydantic ──────────────────────────────────────────────────────────

class EmissaoEntrada(BaseModel):
    empresa: str = Field(..., description="Razão social ou nome fantasia")
    cnpj_cpf: Optional[str] = Field(None, description="CNPJ ou CPF do responsável")
    ano_referencia: int = Field(..., description="Ano do inventário (ex: 2024)")

    # Escopo 1
    e1_estacionario: float = Field(0.0, description="Combustíveis estacionários (tCO2e)")
    e1_movel: float        = Field(0.0, description="Frota própria (tCO2e)")
    e1_processos: float    = Field(0.0, description="Processos industriais (tCO2e)")
    e1_fugitivas: float    = Field(0.0, description="Emissões fugitivas (tCO2e)")

    # Escopo 2
    e2_eletrica: float = Field(0.0, description="Energia elétrica comprada (tCO2e)")
    e2_vapor: float    = Field(0.0, description="Vapor/calor comprado (tCO2e)")

    # Escopo 3
    e3_cadeia: float     = Field(0.0, description="Cadeia de fornecimento (tCO2e)")
    e3_transporte: float = Field(0.0, description="Transporte e distribuição (tCO2e)")
    e3_residuos: float   = Field(0.0, description="Tratamento de resíduos (tCO2e)")

    # Ativos
    cbe_disponiveis: float  = Field(0.0, description="Cotas Brasileiras de Emissão disponíveis")
    crve_disponiveis: float = Field(0.0, description="CRVEs disponíveis")

    class Config:
        json_schema_extra = {
            "example": {
                "empresa": "Exemplo Indústria Ltda",
                "cnpj_cpf": "12.345.678/0001-99",
                "ano_referencia": 2024,
                "e1_estacionario": 1200.5,
                "e1_movel": 800.0,
                "e2_eletrica": 3400.0,
                "cbe_disponiveis": 2000.0,
            }
        }


class AtividadeIA(BaseModel):
    tipo_calculo: str
    combustivel: Optional[str] = None
    quantidade: Optional[float] = None
    categoria: Optional[str] = "combustivel_estacionario"
    escopo: Optional[int] = 1
    kwh: Optional[float] = None
    refrigerante: Optional[str] = None
    kg_vazados: Optional[float] = None
    setor: Optional[str] = None
    valor_reais: Optional[float] = None
    km: Optional[float] = None
    toneladas: Optional[float] = 1.0
    veiculo: Optional[str] = "caminhao_diesel"


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", status_code=status.HTTP_201_CREATED,
             summary="Registrar inventário de emissões")
def registrar_emissao(
    dados: EmissaoEntrada,
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Registra um inventário de emissões de GEE.
    Aceito por integrações SAP/TOTVS via HTTP POST com Bearer token.
    """
    from app.models.emissao import Emissao
    em = Emissao(
        empresa=dados.empresa,
        cnpj_cpf=dados.cnpj_cpf or "",
        ano_referencia=dados.ano_referencia,
        e1_estacionario=dados.e1_estacionario,
        e1_movel=dados.e1_movel,
        e1_processos=dados.e1_processos,
        e1_fugitivas=dados.e1_fugitivas,
        e2_eletrica=dados.e2_eletrica,
        e2_vapor=dados.e2_vapor,
        e3_cadeia=dados.e3_cadeia,
        e3_transporte=dados.e3_transporte,
        e3_residuos=dados.e3_residuos,
        cbe_disponiveis=dados.cbe_disponiveis,
        crve_disponiveis=dados.crve_disponiveis,
    ).calcular()

    payload = {
        "empresa": em.empresa,
        "cnpj_cpf": em.cnpj_cpf,
        "ano_referencia": em.ano_referencia,
        "e1_estacionario": em.e1_estacionario,
        "e1_movel": em.e1_movel,
        "e1_processos": em.e1_processos,
        "e1_fugitivas": em.e1_fugitivas,
        "e2_eletrica": em.e2_eletrica,
        "e2_vapor": em.e2_vapor,
        "e3_cadeia": em.e3_cadeia,
        "e3_transporte": em.e3_transporte,
        "e3_residuos": em.e3_residuos,
        "cbe_disponiveis": em.cbe_disponiveis,
        "crve_disponiveis": em.crve_disponiveis,
        "total_tco2e": em.total_tco2e,
        "deficit_tco2e": em.deficit_tco2e,
        "status_conformidade": em.status_conformidade,
        "usuario_id": usuario["id"],
    }
    try:
        # get_db_client() usa service key se disponível (bypassa RLS).
        # Seguro porque o JWT já foi validado em usuario_autenticado.
        resp = get_db_client().table("emissoes_carbono").insert(payload).execute()
        return {"id": resp.data[0]["id"], "total_tco2e": em.total_tco2e,
                "status_conformidade": em.status_conformidade}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", summary="Listar inventários de emissões")
def listar_emissoes(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    usuario: dict = Depends(usuario_autenticado),
):
    """Lista os inventários de emissões do usuário autenticado."""
    try:
        # Filtrar por usuario_id no código (já que estamos bypassando RLS)
        resp = (
            get_db_client()
            .table("emissoes_carbono")
            .select("id,empresa,cnpj_cpf,ano_referencia,total_tco2e,status_conformidade,deficit_tco2e,cbe_disponiveis,crve_disponiveis,usuario_id")
            .or_(f"usuario_id.eq.{usuario['id']},usuario_id.is.null")
            .order("id", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return {"total": len(resp.data), "dados": resp.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{emissao_id}", summary="Detalhar um inventário")
def detalhar_emissao(
    emissao_id: int,
    usuario: dict = Depends(usuario_autenticado),
):
    try:
        resp = (
            get_db_client()
            .table("emissoes_carbono")
            .select("*")
            .eq("id", emissao_id)
            .single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Inventário não encontrado.")
        # Conferir se o usuário tem acesso
        owner = resp.data.get("usuario_id")
        if owner and owner != usuario["id"]:
            raise HTTPException(status_code=403, detail="Sem permissão para este registro.")
        return resp.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calcular-ia", summary="Calcular emissões via Motor IA (sem salvar)")
def calcular_ia(
    atividades: list[AtividadeIA],
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Recebe lista de atividades com consumos físicos (litros, kWh, km, etc.)
    e retorna tCO2e calculado com fatores IPCC AR6 + MCTI.
    Ideal para integração com SAP PM / TOTVS Backoffice.
    """
    ativ_dict = [a.model_dump(exclude_none=True) for a in atividades]
    relatorio = calcular_inventario(ativ_dict)
    return {
        "escopo1_total": relatorio.escopo1_total,
        "escopo2_total": relatorio.escopo2_total,
        "escopo3_total": relatorio.escopo3_total,
        "total_tco2e": relatorio.total_tco2e,
        "campos_emissao": relatorio.para_emissao_dict(),
        "detalhes": [
            {
                "escopo": r.atividade.escopo,
                "tipo": r.atividade.tipo,
                "tco2e": r.tco2e,
                "fator": r.fator_utilizado,
                "unidade_fator": r.unidade_fator,
                "nota": r.nota,
            }
            for r in relatorio.resultados
        ],
    }
