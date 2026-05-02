"""
Endpoints de Certificados Ambientais.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from typing import Optional

from app.api.auth import usuario_autenticado
from app.database.client import get_db_client

router = APIRouter()


class CertificadoEntrada(BaseModel):
    titular: str = Field(..., description="Nome ou razão social do titular")
    area_hectares: float = Field(..., gt=0, description="Área preservada em hectares")
    bioma: str = Field(..., description="Bioma da propriedade")
    atividade: str = Field(..., description="Atividade registrada")

    class Config:
        json_schema_extra = {
            "example": {
                "titular": "Fazenda Boa Vista Ltda",
                "area_hectares": 250.0,
                "bioma": "Cerrado",
                "atividade": "Agricultura de Baixo Carbono",
            }
        }


@router.post("/", status_code=status.HTTP_201_CREATED,
             summary="Emitir certificado ambiental via API")
def emitir_certificado(
    dados: CertificadoEntrada,
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Gera e registra um certificado de conformidade ambiental.
    Retorna o código do certificado e o valor da cota-carbono estimada.
    """
    import uuid, hashlib
    from app.models.certificado import Certificado
    from app.services.calculo import calcular_cota_carbono
    from app.services.pdf import gerar_pdf, salvar_pdf

    calculo = calcular_cota_carbono(dados.area_hectares, dados.bioma, dados.atividade)
    codigo = str(uuid.uuid4()).split("-")[0].upper()

    cert = Certificado(
        codigo=codigo,
        titular=dados.titular,
        area_hectares=dados.area_hectares,
        bioma=dados.bioma,
        atividade=dados.atividade,
        percentual_bioma=calculo["percentual_bioma"],
        valor_cota=calculo["valor_cota"],
        descricao_atividade=calculo["descricao"],
    )

    pdf_bytes = gerar_pdf(cert)
    cert.hash_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_bytes = gerar_pdf(cert)
    cert.caminho_pdf = salvar_pdf(pdf_bytes, codigo)

    try:
        resp = get_db_client().table("documentos_compliance").insert({
            "usuario_id": usuario["id"],
            "pessoa_id": 1,
            "calculo_area": cert.area_hectares,
            "calculo_valor_cota": cert.valor_cota,
            "car_local_documento": cert.caminho_pdf,
            "hash_auditoria": cert.hash_sha256,
        }).execute()
        db_id = resp.data[0]["id"] if resp.data else None
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao salvar no banco: {e}")

    return {
        "id": db_id,
        "codigo": codigo,
        "titular": cert.titular,
        "bioma": cert.bioma,
        "atividade": cert.atividade,
        "area_hectares": cert.area_hectares,
        "area_util_ha": round(cert.area_hectares * (1 - cert.percentual_bioma), 4),
        "valor_cota": cert.valor_cota,
        "valor_cota_reais": cert.valor_cota,
        "caminho_pdf": cert.caminho_pdf,
        "hash_sha256": cert.hash_sha256,
    }


@router.get("/", summary="Listar certificados emitidos")
def listar_certificados(
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    usuario: dict = Depends(usuario_autenticado),
):
    try:
        resp = (
            get_db_client()
            .table("documentos_compliance")
            .select("id,calculo_area,calculo_valor_cota,car_local_documento,hash_auditoria,usuario_id")
            .or_(f"usuario_id.eq.{usuario['id']},usuario_id.is.null")
            .order("id", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return {"total": len(resp.data), "dados": resp.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{cert_id}", summary="Detalhar certificado por ID")
def detalhar_certificado(
    cert_id: int,
    usuario: dict = Depends(usuario_autenticado),
):
    try:
        resp = (
            get_db_client()
            .table("documentos_compliance")
            .select("*")
            .eq("id", cert_id)
            .single()
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail="Certificado não encontrado.")
        return resp.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
