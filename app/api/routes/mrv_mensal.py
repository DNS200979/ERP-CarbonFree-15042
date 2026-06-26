"""
app/api/routes/mrv_mensal.py

Endpoints do módulo de MRV MENSAL — 1ª Etapa do SBCE (2027).

Fluxo:
  GET    /api/v1/mrv/setores              → catálogo (setores + insumos + fatores)
  POST   /api/v1/mrv/calcular             → calcula fechamento (NÃO grava)
  POST   /api/v1/mrv/fechamentos          → grava o fechamento mensal (upsert lógico)
  GET    /api/v1/mrv/fechamentos          → lista fechamentos (filtros ano/setor/cnpj)
  GET    /api/v1/mrv/fechamentos/{id}     → detalha um fechamento
  DELETE /api/v1/mrv/fechamentos/{id}     → remove um fechamento
  GET    /api/v1/mrv/consolidado/{ano}    → consolida os 12 meses no formato do
                                            inventário anual (POST /emissoes/)

Tabela necessária no Supabase: fechamentos_mensais (ver sql/mrv_mensal.sql).
Autenticação: Bearer JWT Supabase (mesmo padrão dos demais módulos).
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.auth import usuario_autenticado
from app.database.client import get_db_client
from app.services.mrv_mensal import (
    listar_setores,
    calcular_fechamento,
    consolidar_ano,
    TOLERANCIA_BLOCO_K_PCT,
    SETORES_ETAPA1,
)

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class ItemEntrada(BaseModel):
    insumo: str = Field(..., description="Chave do insumo no layout do setor (ex: 'petcoke')")
    estoque_inicial: float = Field(0.0, ge=0, description="Estoque no início do mês")
    entradas_nfe: float = Field(0.0, ge=0, description="Entradas via XML de NF-e no mês")
    estoque_final: float = Field(0.0, ge=0, description="Estoque no fechamento do mês")
    consumo_informado: Optional[float] = Field(
        None, description="Medição direta (telemetria/fatura) — substitui o balanço de massa")
    bloco_k_consumo: Optional[float] = Field(
        None, description="Quantidade reportada no Bloco K (SPED) para conciliação")


class FechamentoEntrada(BaseModel):
    empresa: str = Field(..., description="Razão social do operador regulado")
    cnpj_cpf: Optional[str] = Field(None, description="CNPJ do estabelecimento")
    setor: str = Field(..., description="Setor da Etapa 1 (ex: 'cimento', 'ferro_aco')")
    ano: int = Field(..., ge=2000, le=2100)
    mes: int = Field(..., ge=1, le=12)
    tolerancia_pct: float = Field(
        TOLERANCIA_BLOCO_K_PCT, gt=0, le=100,
        description="Tolerância (%) da conciliação consumo × Bloco K")
    itens: list[ItemEntrada] = Field(..., min_length=1)

    class Config:
        json_schema_extra = {
            "example": {
                "empresa": "Cimentos Exemplo S.A.",
                "cnpj_cpf": "12.345.678/0001-99",
                "setor": "cimento",
                "ano": 2027,
                "mes": 1,
                "itens": [
                    {"insumo": "descarbonatacao_calcario", "consumo_informado": 65000},
                    {"insumo": "petcoke", "estoque_inicial": 1200,
                     "entradas_nfe": 8000, "estoque_final": 800,
                     "bloco_k_consumo": 8400},
                    {"insumo": "pneus_inserviveis", "estoque_inicial": 0,
                     "entradas_nfe": 1100, "estoque_final": 0},
                    {"insumo": "biomassa_residuos", "estoque_inicial": 500,
                     "entradas_nfe": 3200, "estoque_final": 200},
                ],
            }
        }


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/setores", summary="Catálogo dos setores da 1ª Etapa (insumos + fatores)")
def setores(usuario: dict = Depends(usuario_autenticado)):
    """Devolve os 6 layouts (SBCE-PAP-01 … SBCE-AER-07) para popular o frontend."""
    return {"tolerancia_padrao_pct": TOLERANCIA_BLOCO_K_PCT, "setores": listar_setores()}


@router.post("/calcular", summary="Calcular fechamento mensal (sem salvar)")
def calcular(dados: FechamentoEntrada, usuario: dict = Depends(usuario_autenticado)):
    """
    Aplica o balanço de massa (Estoque Inicial + Entradas NF-e − Estoque Final),
    a conciliação contra o Bloco K e os fatores de emissão do setor.
    Nada é gravado — o usuário confere e usa POST /fechamentos para arquivar.
    """
    try:
        fech = calcular_fechamento(
            setor=dados.setor, ano=dados.ano, mes=dados.mes,
            itens=[i.model_dump() for i in dados.itens],
            tolerancia_pct=dados.tolerancia_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    out = fech.para_dict()
    out["hash_auditoria"] = fech.hash_auditoria()
    return out


@router.post("/fechamentos", status_code=status.HTTP_201_CREATED,
             summary="Gravar fechamento mensal (memória de cálculo auditável)")
def gravar_fechamento(dados: FechamentoEntrada,
                      usuario: dict = Depends(usuario_autenticado)):
    """
    Calcula e PERSISTE o fechamento do mês. Se já existir fechamento do mesmo
    usuário/CNPJ/setor/ano/mês, ele é substituído (retificação), preservando o
    novo hash SHA-256 como trilha de auditoria.
    """
    try:
        fech = calcular_fechamento(
            setor=dados.setor, ano=dados.ano, mes=dados.mes,
            itens=[i.model_dump() for i in dados.itens],
            tolerancia_pct=dados.tolerancia_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    resultado = fech.para_dict()
    payload = {
        "usuario_id": usuario["id"],
        "empresa": dados.empresa,
        "cnpj_cpf": dados.cnpj_cpf or "",
        "setor": fech.setor,
        "layout": fech.layout,
        "ano": fech.ano,
        "mes": fech.mes,
        "resultado": resultado,
        "total_e1": fech.total_e1,
        "total_e2": fech.total_e2,
        "total_tco2e": fech.total_tco2e,
        "divergencia_max_pct": fech.divergencia_max_pct,
        "status_conciliacao": fech.status_conciliacao,
        "hash_auditoria": fech.hash_auditoria(),
    }

    db = get_db_client()
    try:
        # Retificação: remove fechamento anterior do mesmo período/setor/CNPJ
        (db.table("fechamentos_mensais").delete()
           .eq("usuario_id", usuario["id"])
           .eq("cnpj_cpf", payload["cnpj_cpf"])
           .eq("setor", fech.setor)
           .eq("ano", fech.ano)
           .eq("mes", fech.mes)
           .execute())
        resp = db.table("fechamentos_mensais").insert(payload).execute()
        return {
            "id": resp.data[0]["id"] if resp.data else None,
            "total_tco2e": fech.total_tco2e,
            "status_conciliacao": fech.status_conciliacao,
            "divergencia_max_pct": fech.divergencia_max_pct,
            "hash_auditoria": payload["hash_auditoria"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao gravar fechamento: {e}")


@router.get("/fechamentos", summary="Listar fechamentos mensais")
def listar_fechamentos(
    ano: Optional[int] = Query(None),
    setor: Optional[str] = Query(None),
    cnpj_cpf: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    usuario: dict = Depends(usuario_autenticado),
):
    try:
        q = (get_db_client().table("fechamentos_mensais")
             .select("id,empresa,cnpj_cpf,setor,layout,ano,mes,total_e1,total_e2,"
                     "total_tco2e,divergencia_max_pct,status_conciliacao,"
                     "hash_auditoria,criado_em")
             .eq("usuario_id", usuario["id"])
             .order("ano", desc=True).order("mes", desc=True)
             .range(offset, offset + limit - 1))
        if ano:
            q = q.eq("ano", ano)
        if setor:
            q = q.eq("setor", setor)
        if cnpj_cpf:
            q = q.eq("cnpj_cpf", cnpj_cpf)
        resp = q.execute()
        return {"total": len(resp.data), "dados": resp.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fechamentos/{fech_id}", summary="Detalhar fechamento (memória de cálculo)")
def detalhar_fechamento(fech_id: int, usuario: dict = Depends(usuario_autenticado)):
    try:
        resp = (get_db_client().table("fechamentos_mensais")
                .select("*").eq("id", fech_id).single().execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail="Fechamento não encontrado.")
        if resp.data.get("usuario_id") != usuario["id"]:
            raise HTTPException(status_code=403, detail="Sem permissão para este registro.")
        return resp.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/fechamentos/{fech_id}", summary="Remover fechamento mensal")
def remover_fechamento(fech_id: int, usuario: dict = Depends(usuario_autenticado)):
    try:
        (get_db_client().table("fechamentos_mensais").delete()
         .eq("id", fech_id).eq("usuario_id", usuario["id"]).execute())
        return {"removido": fech_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/consolidado/{ano}",
            summary="Consolidar 12 meses no formato do inventário anual")
def consolidado(
    ano: int,
    cnpj_cpf: Optional[str] = Query(None, description="Filtrar por CNPJ"),
    setor: Optional[str] = Query(None, description="Filtrar por setor"),
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Soma os fechamentos mensais do ano e devolve `campos_emissao` no MESMO
    formato aceito por POST /api/v1/emissoes/ — basta acrescentar empresa,
    CNPJ e ativos (CBE/CRVE) e enviar. A automação mensal alimenta a anual.
    """
    if setor and setor not in SETORES_ETAPA1:
        raise HTTPException(status_code=400,
                            detail=f"Setor inválido. Disponíveis: {list(SETORES_ETAPA1.keys())}")
    try:
        q = (get_db_client().table("fechamentos_mensais")
             .select("setor,ano,mes,total_tco2e,status_conciliacao,resultado")
             .eq("usuario_id", usuario["id"]).eq("ano", ano))
        if cnpj_cpf:
            q = q.eq("cnpj_cpf", cnpj_cpf)
        if setor:
            q = q.eq("setor", setor)
        resp = q.execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    cons = consolidar_ano(resp.data or [])
    cons["ano"] = ano
    cons["fechamentos_encontrados"] = len(resp.data or [])
    return cons
