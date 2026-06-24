"""
Endpoints de integração com SAP, TOTVS e outros ERPs.

Padrões suportados:
- SAP: via BAPI/RFC HTTP wrapper (RFC over REST)
- TOTVS: via TOTVS Fluig / RM REST API
- Genérico: payload normalizado MBV
"""

from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from pydantic import BaseModel, Field

from app.api.auth import usuario_autenticado
from app.database.client import get_client

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────────────

class PushSAPEmissao(BaseModel):
    """Payload no formato esperado por integrações SAP Environment, Health & Safety."""
    CompanyCode: str = Field(..., alias="CompanyCode")
    FiscalYear: int  = Field(..., alias="FiscalYear")
    GHGScope1: float = Field(0.0, alias="GHGScope1")
    GHGScope2: float = Field(0.0, alias="GHGScope2")
    GHGScope3: float = Field(0.0, alias="GHGScope3")
    CBEAssets: float = Field(0.0, alias="CBEAssets")
    CRVEAssets: float= Field(0.0, alias="CRVEAssets")
    Remarks: Optional[str] = Field(None, alias="Remarks")

    class Config:
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "CompanyCode": "1000",
                "FiscalYear": 2024,
                "GHGScope1": 5200.0,
                "GHGScope2": 3400.0,
                "GHGScope3": 800.0,
                "CBEAssets": 2000.0,
                "CRVEAssets": 0.0,
                "Remarks": "Importado via SAP EHS"
            }
        }


class PushTOTVSEmissao(BaseModel):
    """Payload no formato TOTVS RM / Fluig."""
    codEmpresa: str
    anoReferencia: int
    escopo1: float = 0.0
    escopo2: float = 0.0
    escopo3: float = 0.0
    ativos_cbe: float = 0.0
    ativos_crve: float = 0.0
    observacoes: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "codEmpresa": "T0001",
                "anoReferencia": 2024,
                "escopo1": 5200.0,
                "escopo2": 3400.0,
                "escopo3": 800.0,
                "ativos_cbe": 2000.0,
            }
        }


class WebhookConfig(BaseModel):
    """Configura um webhook para notificação de eventos MBV."""
    url: str = Field(..., description="URL de destino do webhook")
    eventos: list[str] = Field(
        ..., description="Eventos a monitorar: 'emissao.criada', 'certificado.emitido', 'conformidade.violada'"
    )
    secret: Optional[str] = Field(None, description="Chave HMAC para assinatura do payload")


# ── Endpoints SAP ──────────────────────────────────────────────────────────────

@router.post("/sap/emissoes",
             status_code=status.HTTP_201_CREATED,
             summary="Receber emissões no formato SAP EHS")
def receber_sap(
    payload: PushSAPEmissao,
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Endpoint para push de dados vindos do SAP Environment Health & Safety (EHS).
    Converte o payload SAP para o formato MBV e salva no banco.
    """
    total = payload.GHGScope1 + payload.GHGScope2 + payload.GHGScope3
    ativos = payload.CBEAssets + payload.CRVEAssets
    deficit = round(total - ativos, 4)

    if total < 10_000:
        status_conf = "ISENTO"
    elif total <= 25_000:
        status_conf = "MONITORAMENTO OBRIGATÓRIO"
    else:
        status_conf = "CONFORMIDADE TOTAL OBRIGATÓRIA"

    dados = {
        "empresa": f"SAP CompanyCode {payload.CompanyCode}",
        "cnpj_cpf": None,
        "ano_referencia": payload.FiscalYear,
        "e1_estacionario": payload.GHGScope1,
        "e1_movel": 0.0,
        "e1_processos": 0.0,
        "e1_fugitivas": 0.0,
        "e2_eletrica": payload.GHGScope2,
        "e2_vapor": 0.0,
        "e3_cadeia": payload.GHGScope3,
        "e3_transporte": 0.0,
        "e3_residuos": 0.0,
        "cbe_disponiveis": payload.CBEAssets,
        "crve_disponiveis": payload.CRVEAssets,
        "total_tco2e": total,
        "deficit_tco2e": deficit,
        "status_conformidade": status_conf,
        "usuario_id": usuario["id"],
    }
    try:
        resp = get_client().table("emissoes_carbono").insert(dados).execute()
        return {
            "mbv_id": resp.data[0]["id"],
            "total_tco2e": total,
            "status_conformidade": status_conf,
            "fonte": "SAP-EHS",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Endpoints TOTVS ────────────────────────────────────────────────────────────

@router.post("/totvs/emissoes",
             status_code=status.HTTP_201_CREATED,
             summary="Receber emissões no formato TOTVS RM")
def receber_totvs(
    payload: PushTOTVSEmissao,
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Endpoint para push de dados vindos do TOTVS RM / Fluig.
    Converte o payload TOTVS para o formato MBV.
    """
    total = payload.escopo1 + payload.escopo2 + payload.escopo3
    ativos = payload.ativos_cbe + payload.ativos_crve
    deficit = round(total - ativos, 4)

    if total < 10_000:
        status_conf = "ISENTO"
    elif total <= 25_000:
        status_conf = "MONITORAMENTO OBRIGATÓRIO"
    else:
        status_conf = "CONFORMIDADE TOTAL OBRIGATÓRIA"

    dados = {
        "empresa": f"TOTVS Empresa {payload.codEmpresa}",
        "cnpj_cpf": None,
        "ano_referencia": payload.anoReferencia,
        "e1_estacionario": payload.escopo1,
        "e1_movel": 0.0,
        "e1_processos": 0.0,
        "e1_fugitivas": 0.0,
        "e2_eletrica": payload.escopo2,
        "e2_vapor": 0.0,
        "e3_cadeia": payload.escopo3,
        "e3_transporte": 0.0,
        "e3_residuos": 0.0,
        "cbe_disponiveis": payload.ativos_cbe,
        "crve_disponiveis": payload.ativos_crve,
        "total_tco2e": total,
        "deficit_tco2e": deficit,
        "status_conformidade": status_conf,
        "usuario_id": usuario["id"],
    }
    try:
        resp = get_client().table("emissoes_carbono").insert(dados).execute()
        return {
            "mbv_id": resp.data[0]["id"],
            "total_tco2e": total,
            "status_conformidade": status_conf,
            "fonte": "TOTVS-RM",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Status e conformidade ──────────────────────────────────────────────────────

@router.get("/conformidade/{empresa_id}",
            summary="Consultar status de conformidade SBCE")
def consultar_conformidade(
    empresa_id: int,
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Retorna o status de conformidade mais recente de uma empresa.
    Endpoint usado por dashboards SAP/TOTVS para alerta de compliance.
    """
    try:
        resp = (
            get_client()
            .table("emissoes_carbono")
            .select("id,empresa,ano_referencia,total_tco2e,deficit_tco2e,status_conformidade")
            .eq("id", empresa_id)
            .single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Empresa não encontrada.")
        dados = resp.data
        alerta = dados["status_conformidade"] != "ISENTO"
        return {
            **dados,
            "alerta_conformidade": alerta,
            "lei_aplicavel": "Lei 15.042/2024 — SBCE",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schema/sap",
            summary="Schema de integração SAP (documentação)")
def schema_sap(usuario: dict = Depends(usuario_autenticado)):
    """Retorna o mapeamento de campos SAP EHS → MBV para facilitar a integração."""
    return {
        "endpoint": "POST /api/v1/integracao/sap/emissoes",
        "autenticacao": "Bearer token JWT Supabase no header Authorization",
        "mapeamento_campos": {
            "CompanyCode":  "Código da empresa no SAP",
            "FiscalYear":   "Ano de referência (4 dígitos)",
            "GHGScope1":    "Total Escopo 1 em tCO2e",
            "GHGScope2":    "Total Escopo 2 em tCO2e",
            "GHGScope3":    "Total Escopo 3 em tCO2e",
            "CBEAssets":    "Cotas Brasileiras de Emissão disponíveis",
            "CRVEAssets":   "Certificados de Redução disponíveis",
        },
        "resposta": {
            "mbv_id":               "ID gerado no banco MBV",
            "total_tco2e":          "Total calculado",
            "status_conformidade":  "ISENTO | MONITORAMENTO OBRIGATÓRIO | CONFORMIDADE TOTAL OBRIGATÓRIA",
        }
    }


@router.get("/schema/totvs",
            summary="Schema de integração TOTVS (documentação)")
def schema_totvs(usuario: dict = Depends(usuario_autenticado)):
    """Retorna o mapeamento de campos TOTVS RM → MBV para facilitar a integração."""
    return {
        "endpoint": "POST /api/v1/integracao/totvs/emissoes",
        "autenticacao": "Bearer token JWT Supabase no header Authorization",
        "mapeamento_campos": {
            "codEmpresa":    "Código da empresa no TOTVS RM",
            "anoReferencia": "Ano de referência (4 dígitos)",
            "escopo1":       "Total Escopo 1 em tCO2e",
            "escopo2":       "Total Escopo 2 em tCO2e",
            "escopo3":       "Total Escopo 3 em tCO2e",
            "ativos_cbe":    "CBE disponíveis",
            "ativos_crve":   "CRVE disponíveis",
        },
    }
