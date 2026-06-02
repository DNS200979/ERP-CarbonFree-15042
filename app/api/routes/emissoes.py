"""
Endpoints de Emissões de Carbono.
Compatível com integração SAP/TOTVS — aceita payload padrão GHG Protocol.

Inclui o endpoint POST /importar-ecf, que lê o arquivo da ECF (o SPED do
imposto de renda da pessoa jurídica), extrai CNPJ, razão social, receita,
gastos com energia/combustível e o CNAE (registro 0020), resolve a categoria
setorial — primeiro pela consulta do CNPJ na BrasilAPI e, em fallback, pelo
próprio CNAE da ECF — e devolve o inventário calculado por balanço, sem
digitação manual. Nada é gravado: o usuário confere e usa POST /emissoes/.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File
from pydantic import BaseModel, Field

from app.api.auth import usuario_autenticado
from app.database.client import get_db_client
from app.services.motor_ia import (
    calcular_inventario,
    calcular_por_balanco,
    DeclaracaoEmpresa,
    listar_categorias_setoriais,
)
from app.services.ecf import parse_ecf
from app.services.cnpj import consultar_cnpj, cnae_para_categoria

router = APIRouter()


# ── Schemas Pydantic ──────────────────────────────────────────────────────────

class DeclaracaoBalancoEntrada(BaseModel):
    empresa: str = Field(..., description="Razão social ou nome fantasia")
    cnpj_cpf: Optional[str] = Field(None, description="CNPJ ou CPF do responsável")
    ano_referencia: int = Field(..., description="Ano do inventário (ex: 2026)")
    categoria: str = Field(
        ...,
        description="Categoria econômica (ex: 'construcao_civil', 'transporte_logistica', "
                    "'agronegocio'). Use GET /emissoes/categorias para a lista.",
    )
    faturamento_bruto: float = Field(
        ..., description="Receita bruta anual em R$ (base principal do cálculo)"
    )
    # Refinamentos opcionais — quando > 0, têm prioridade sobre a estimativa por receita
    gasto_combustivel: float = Field(0.0, description="Gasto anual com combustível (R$) — refina Escopo 1")
    gasto_energia_eletrica: float = Field(0.0, description="Gasto anual com energia elétrica (R$) — refina Escopo 2")
    compras_insumos: float = Field(0.0, description="Compras de insumos/materiais (R$) — refina Escopo 3")

    class Config:
        json_schema_extra = {
            "example": {
                "empresa": "Construtora Exemplo Ltda",
                "cnpj_cpf": "12.345.678/0001-99",
                "ano_referencia": 2026,
                "categoria": "construcao_civil",
                "faturamento_bruto": 50_000_000.0,
                "compras_insumos": 28_000_000.0,
            }
        }


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
    # Campos do modo balanço (quando tipo_calculo == "balanco")
    empresa: Optional[str] = None
    ano_referencia: Optional[int] = None
    faturamento_bruto: Optional[float] = None
    gasto_combustivel: Optional[float] = None
    gasto_energia_eletrica: Optional[float] = None
    compras_insumos: Optional[float] = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/categorias", summary="Listar categorias setoriais disponíveis")
def listar_categorias(usuario: dict = Depends(usuario_autenticado)):
    """Retorna as categorias (chave + rótulo) aceitas no cálculo por balanço."""
    return [{"chave": chave, "rotulo": rotulo} for chave, rotulo in listar_categorias_setoriais()]


@router.get("/cnpj/{cnpj}", summary="Consultar CNPJ (dados cadastrais + categoria sugerida)")
def consultar_cnpj_endpoint(cnpj: str, usuario: dict = Depends(usuario_autenticado)):
    """
    Consulta dados PÚBLICOS do CNPJ (BrasilAPI/RFB) e sugere a categoria
    setorial a partir do CNAE principal.

    NÃO retorna faturamento — esse dado não é público; deve ser informado
    pelo usuário (ou obtido via CVM, para companhias abertas).
    """
    try:
        dados = consultar_cnpj(cnpj)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Acrescenta o rótulo amigável da categoria sugerida
    rotulo = ""
    if dados.get("categoria_sugerida"):
        for chave, rot in listar_categorias_setoriais():
            if chave == dados["categoria_sugerida"]:
                rotulo = rot
                break
    dados["categoria_rotulo"] = rotulo
    return dados


@router.post("/calcular-balanco", summary="Calcular inventário por balanço/declaração (sem salvar)")
def calcular_balanco(
    dados: DeclaracaoBalancoEntrada,
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Estima o inventário a partir da declaração da empresa.

    A categoria define a distribuição entre escopos; o faturamento define o
    tamanho. Gastos específicos (combustível, energia, compras), quando
    informados, refinam o escopo correspondente.

    Método spend-based/EEIO — adequado para triagem e nível de monitoramento.
    Para >25.000 tCO2e/ano, refine os Escopos 1 e 2 com dado de atividade
    via POST /emissoes/calcular-ia.
    """
    decl = DeclaracaoEmpresa(
        empresa=dados.empresa,
        categoria=dados.categoria,
        ano_referencia=dados.ano_referencia,
        cnpj_cpf=dados.cnpj_cpf or "",
        faturamento_bruto=dados.faturamento_bruto,
        gasto_combustivel=dados.gasto_combustivel,
        gasto_energia_eletrica=dados.gasto_energia_eletrica,
        compras_insumos=dados.compras_insumos,
    )
    relatorio = calcular_por_balanco(decl)
    return {
        "metodo": relatorio.metodo,
        "categoria": relatorio.categoria,
        "escopo1_total": relatorio.escopo1_total,
        "escopo2_total": relatorio.escopo2_total,
        "escopo3_total": relatorio.escopo3_total,
        "total_tco2e": relatorio.total_tco2e,
        "campos_emissao": relatorio.para_emissao_dict(),
        "detalhes": [
            {
                "escopo": r.atividade.escopo,
                "tco2e": r.tco2e,
                "fator": r.fator_utilizado,
                "unidade_fator": r.unidade_fator,
                "nota": r.nota,
            }
            for r in relatorio.resultados
        ],
    }


@router.post("/importar-ecf", summary="Importar ECF (imposto de renda/SPED) e calcular por balanço")
async def importar_ecf(
    arquivo: UploadFile = File(..., description="Arquivo .txt da ECF transmitida à Receita"),
    calcular: bool = Query(True, description="Se True, já devolve o inventário calculado"),
    usuario: dict = Depends(usuario_autenticado),
):
    """
    Lê o arquivo da ECF (Escrituração Contábil Fiscal — o SPED que substituiu a
    DIPJ na entrega do imposto de renda da pessoa jurídica) e extrai, sem
    digitação manual:

      • CNPJ e razão social
      • CNAE principal (registro 0020), quando presente
      • período / ano de referência e regime (Lucro Real ou Presumido)
      • receita bruta (base do cálculo por balanço)
      • gastos com energia e combustível (refinam Escopos 2 e 1, quando presentes)

    A categoria setorial é resolvida nesta ordem:
      1) consulta do CNAE pelo CNPJ (BrasilAPI) — caminho primário p/ CNPJ real;
      2) se a consulta falhar (ex.: CNPJ fictício, offline), usa o CNAE lido da
         própria ECF (registro 0020) como fallback.
    Isso permite testar o fluxo completo com CNPJs fictícios.

    Se `calcular=True` e houver categoria + receita, já devolve o inventário
    estimado (mesmo formato de /calcular-balanco).

    Nada é gravado: o usuário confere os valores e usa POST /emissoes/ para salvar.
    """
    # 1) Ler e parsear a ECF
    try:
        conteudo = await arquivo.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler o arquivo: {e}")

    dados = parse_ecf(conteudo)
    if not dados.cnpj and dados.receita_bruta <= 0 and not dados.dre:
        raise HTTPException(
            status_code=422,
            detail="Arquivo não reconhecido como ECF (nenhum registro 0000/L300/P150 encontrado). "
                   "Confirme que é o .txt da ECF transmitida ao SPED.",
        )

    # 2) Consultar CNAE pelo CNPJ → sugerir categoria (falha graciosa)
    cnpj_info: dict = {}
    categoria_sugerida = None
    if dados.cnpj:
        try:
            cnpj_info = consultar_cnpj(dados.cnpj)
            categoria_sugerida = cnpj_info.get("categoria_sugerida")
            if categoria_sugerida:
                for chave, rot in listar_categorias_setoriais():
                    if chave == categoria_sugerida:
                        cnpj_info["categoria_rotulo"] = rot
                        break
        except Exception as e:
            # CNPJ inválido / não encontrado / rede indisponível — não bloqueia
            cnpj_info = {"erro": str(e)}

    # 2b) Fallback: usar o CNAE lido da própria ECF (registro 0020) quando a
    #     consulta por CNPJ não resolveu a categoria. Viabiliza testes com
    #     CNPJ fictício e funcionamento offline.
    if not categoria_sugerida and getattr(dados, "cnae", ""):
        categoria_ecf = cnae_para_categoria(dados.cnae)
        if categoria_ecf:
            categoria_sugerida = categoria_ecf
            rotulo = ""
            for chave, rot in listar_categorias_setoriais():
                if chave == categoria_ecf:
                    rotulo = rot
                    break
            cnpj_info = {
                "cnae_fiscal": dados.cnae,
                "categoria_sugerida": categoria_ecf,
                "categoria_rotulo": rotulo,
                "origem_categoria": "CNAE da própria ECF (registro 0020)",
            }

    # 3) Calcular por balanço (opcional)
    calculo = None
    aviso_calculo = None
    if calcular:
        if not categoria_sugerida:
            aviso_calculo = (
                "CNAE sem mapeamento automático para categoria — selecione a "
                "categoria manualmente e clique em Calcular."
            )
        elif dados.receita_bruta <= 0:
            aviso_calculo = (
                "Receita bruta não localizada na ECF — informe o faturamento "
                "manualmente e clique em Calcular."
            )
        else:
            decl = DeclaracaoEmpresa(
                empresa=dados.razao_social or "Empresa",
                categoria=categoria_sugerida,
                ano_referencia=dados.ano_referencia or 0,
                cnpj_cpf=dados.cnpj,
                faturamento_bruto=dados.receita_bruta,
                gasto_combustivel=dados.gasto_combustivel,
                gasto_energia_eletrica=dados.gasto_energia_eletrica,
                compras_insumos=0.0,
            )
            relatorio = calcular_por_balanco(decl)
            calculo = {
                "metodo": relatorio.metodo,
                "categoria": relatorio.categoria,
                "escopo1_total": relatorio.escopo1_total,
                "escopo2_total": relatorio.escopo2_total,
                "escopo3_total": relatorio.escopo3_total,
                "total_tco2e": relatorio.total_tco2e,
                "campos_emissao": relatorio.para_emissao_dict(),
                "detalhes": [
                    {
                        "escopo": r.atividade.escopo,
                        "tco2e": r.tco2e,
                        "fator": r.fator_utilizado,
                        "unidade_fator": r.unidade_fator,
                        "nota": r.nota,
                    }
                    for r in relatorio.resultados
                ],
            }

    return {
        "arquivo": arquivo.filename,
        "ecf": dados.resumo(),
        "cnpj_info": cnpj_info,
        "categoria_sugerida": categoria_sugerida,
        "calculo": calculo,
        "aviso_calculo": aviso_calculo,
    }


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
