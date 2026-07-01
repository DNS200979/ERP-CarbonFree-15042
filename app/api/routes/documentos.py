"""
Endpoints de anexo de evidências (NF-e, laudos, faturas, MTR, certificados de
calibração etc.) vinculadas a um cálculo salvo (historico_calculos) ou a um
fechamento mensal MRV (fechamentos_mensais), com escopo opcional a um insumo
específico dentro do fechamento.

Tabelas/infra necessárias no Supabase (ver plano de implementação — não há
tooling de migração neste repo, o SQL deve ser rodado manualmente):
  • bucket de Storage `evidencias-compliance` (privado, 10 MB por arquivo);
  • tabela `documentos_evidencia`.

Todo acesso ao bucket é feito pelo backend com a service key — o frontend
nunca fala diretamente com o Storage (mesmo padrão do restante do projeto:
RLS é ignorada pela service key, e a autorização real acontece aqui, checando
que o usuario_id do alvo bate com o usuário autenticado).
"""

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.api.auth import usuario_autenticado
from app.config import (
    EVIDENCIA_MIME_PERMITIDOS,
    EVIDENCIA_TAMANHO_MAX_BYTES,
    SUPABASE_BUCKET_EVIDENCIAS,
)
from app.database.client import get_db_client, get_storage_client

router = APIRouter()

TIPOS_ALVO_VALIDOS = {"historico", "fechamento"}

# Assinaturas de bytes (magic numbers) para checagem cruzada com o Content-Type
# declarado pelo cliente — não confiar cegamente no header. Mimes sem
# assinatura fixa (xml/txt/xls legado) passam sem essa checagem adicional.
_MAGIC_BYTES: dict[bytes, set[str]] = {
    b"%PDF-": {"application/pdf"},
    b"\x89PNG\r\n\x1a\n": {"image/png"},
    b"\xff\xd8\xff": {"image/jpeg"},
    b"PK\x03\x04": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
}


def _sanitizar_nome(nome: str) -> str:
    """Remove separadores de caminho e caracteres de controle do nome do arquivo."""
    nome = (nome or "arquivo").strip()
    nome = nome.replace("/", "_").replace("\\", "_")
    nome = re.sub(r"[\x00-\x1f]", "", nome)
    return nome[-120:] or "arquivo"


def _checar_magic_bytes(conteudo: bytes, mime: str) -> None:
    for assinatura, mimes_ok in _MAGIC_BYTES.items():
        if conteudo.startswith(assinatura) and mime not in mimes_ok:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Conteúdo do arquivo não corresponde ao tipo declarado ({mime}).",
            )


def _buscar_alvo(tipo_alvo: str, alvo_id: int, usuario_id: str) -> dict:
    """Confirma que o alvo (historico_calculos ou fechamentos_mensais) existe e
    pertence ao usuário autenticado (ou não tem dono). Levanta 404 caso
    contrário — este é o ponto real de autorização, já que a service key
    ignora RLS (mesmo padrão do resto do projeto)."""
    tabela = "historico_calculos" if tipo_alvo == "historico" else "fechamentos_mensais"
    try:
        resp = (
            get_db_client()
            .table(tabela)
            .select("id,usuario_id")
            .eq("id", alvo_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
    linha = resp.data if resp else None
    if not linha:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{tabela} #{alvo_id} não encontrado.")
    dono = linha.get("usuario_id")
    if dono and dono != usuario_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{tabela} #{alvo_id} não encontrado.")
    return linha


def _buscar_documento(doc_id: int, usuario_id: str) -> dict:
    try:
        resp = (
            get_db_client()
            .table("documentos_evidencia")
            .select("*")
            .eq("id", doc_id)
            .maybe_single()
            .execute()
        )
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
    doc = resp.data if resp else None
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado.")
    dono = doc.get("usuario_id")
    if dono and dono != usuario_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento não encontrado.")
    return doc


def _montar_path(usuario_id: str, tipo_alvo: str, alvo_id: int, nome_arquivo: str) -> str:
    nome = _sanitizar_nome(nome_arquivo)
    return f"{usuario_id}/{tipo_alvo}/{alvo_id}/{uuid.uuid4().hex}_{nome}"


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=status.HTTP_201_CREATED,
             summary="Anexar um documento de evidência a um cálculo ou fechamento MRV")
async def upload_documento(
    arquivo: UploadFile = File(...),
    tipo_alvo: str = Form(..., description="historico | fechamento"),
    alvo_id: int = Form(...),
    insumo_chave: Optional[str] = Form(None),
    descricao: Optional[str] = Form(None),
    usuario: dict = Depends(usuario_autenticado),
):
    """Recebe um arquivo (NF-e, laudo, fatura, MTR etc.), valida tipo/tamanho e
    grava no bucket privado de evidências, registrando a linha em
    `documentos_evidencia` para a trilha de auditoria. Diferente do histórico
    de cálculos, aqui a falha NÃO é silenciosa — o upload é a ação principal."""
    if tipo_alvo not in TIPOS_ALVO_VALIDOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                             f"tipo_alvo inválido. Use: {sorted(TIPOS_ALVO_VALIDOS)}")

    mime = (arquivo.content_type or "").split(";")[0].strip().lower()
    if mime not in EVIDENCIA_MIME_PERMITIDOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                             f"Tipo de arquivo não permitido: {mime or 'desconhecido'}.")

    conteudo = await arquivo.read()
    if not conteudo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Arquivo vazio.")
    if len(conteudo) > EVIDENCIA_TAMANHO_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                             f"Arquivo excede o limite de {EVIDENCIA_TAMANHO_MAX_BYTES // (1024*1024)} MB.")
    _checar_magic_bytes(conteudo, mime)

    _buscar_alvo(tipo_alvo, alvo_id, usuario["id"])

    nome_original = _sanitizar_nome(arquivo.filename or "arquivo")
    caminho = _montar_path(usuario["id"], tipo_alvo, alvo_id, nome_original)
    hash_sha256 = hashlib.sha256(conteudo).hexdigest()

    try:
        get_storage_client().storage.from_(SUPABASE_BUCKET_EVIDENCIAS).upload(
            caminho, conteudo, file_options={"content-type": mime},
        )
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Falha ao enviar ao Storage: {e}")

    payload = {
        "usuario_id": usuario["id"],
        "tipo_alvo": tipo_alvo,
        "historico_id": alvo_id if tipo_alvo == "historico" else None,
        "fechamento_id": alvo_id if tipo_alvo == "fechamento" else None,
        "insumo_chave": insumo_chave or None,
        "nome_arquivo": nome_original,
        "mime_type": mime,
        "tamanho_bytes": len(conteudo),
        "storage_bucket": SUPABASE_BUCKET_EVIDENCIAS,
        "storage_path": caminho,
        "descricao": descricao or None,
        "hash_sha256": hash_sha256,
    }
    try:
        resp = get_db_client().table("documentos_evidencia").insert(payload).execute()
    except Exception as e:
        try:
            get_storage_client().storage.from_(SUPABASE_BUCKET_EVIDENCIAS).remove([caminho])
        except Exception as cleanup_err:
            print(f"[documentos] Falha ao limpar objeto órfão {caminho}: {cleanup_err}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                             f"Upload feito, mas falhou ao registrar no banco: {e}")

    if not resp.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                             "Upload feito, mas o banco não retornou a linha gravada.")
    return resp.data[0]


@router.get("/", summary="Listar documentos anexados a um cálculo ou fechamento")
def listar_documentos(
    tipo_alvo: str = Query(..., description="historico | fechamento"),
    alvo_id: int = Query(...),
    insumo_chave: Optional[str] = Query(None),
    usuario: dict = Depends(usuario_autenticado),
):
    if tipo_alvo not in TIPOS_ALVO_VALIDOS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                             f"tipo_alvo inválido. Use: {sorted(TIPOS_ALVO_VALIDOS)}")
    coluna = "historico_id" if tipo_alvo == "historico" else "fechamento_id"
    try:
        q = (
            get_db_client()
            .table("documentos_evidencia")
            .select("id,tipo_alvo,historico_id,fechamento_id,insumo_chave,nome_arquivo,"
                    "mime_type,tamanho_bytes,descricao,hash_sha256,criado_em")
            .eq(coluna, alvo_id)
            .is_("removido_em", "null")
            .or_(f"usuario_id.eq.{usuario['id']},usuario_id.is.null")
            .order("criado_em", desc=True)
        )
        if insumo_chave:
            q = q.eq("insumo_chave", insumo_chave)
        resp = q.execute()
        return {"total": len(resp.data), "dados": resp.data}
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))


@router.get("/{doc_id}/url", summary="Gerar URL assinada para baixar um documento")
def obter_url_documento(doc_id: int, usuario: dict = Depends(usuario_autenticado)):
    doc = _buscar_documento(doc_id, usuario["id"])
    try:
        assinado = (
            get_storage_client()
            .storage.from_(doc["storage_bucket"])
            .create_signed_url(doc["storage_path"], expires_in=300)
        )
    except Exception as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Falha ao gerar URL: {e}")
    url = assinado.get("signedURL") or assinado.get("signedUrl")
    if not url:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Storage não retornou URL assinada.")
    return {"url": url, "expira_em_segundos": 300}


@router.delete("/{doc_id}", summary="Remover um documento anexado")
def remover_documento(doc_id: int, usuario: dict = Depends(usuario_autenticado)):
    doc = _buscar_documento(doc_id, usuario["id"])
    try:
        get_db_client().table("documentos_evidencia").update(
            {"removido_em": datetime.now(timezone.utc).isoformat()}
        ).eq("id", doc_id).execute()
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e))
    try:
        get_storage_client().storage.from_(doc["storage_bucket"]).remove([doc["storage_path"]])
    except Exception as e:
        print(f"[documentos] Falha ao remover objeto do Storage {doc['storage_path']}: {e}")
    return {"removido": doc_id}
