"""
app/services/orgaos_ambientais.py

Integração de consulta de TITULAR RURAL por documento (CNPJ ou CPF), orquestrando
as fontes públicas disponíveis para autopreencher o formulário de Certificado
Rural (view Agro): Titular/Razão social, Bioma, Atividade e (quando possível)
Área preservada.

------------------------------------------------------------------------------
REALIDADE DAS FONTES (importante — leia antes de "ligar" cada órgão)
------------------------------------------------------------------------------
Não existe uma API pública unificada keyed por CPF/CNPJ que devolva área
preservada + bioma + atividade. Os dados são fragmentados e, sobretudo,
geoespaciais. Esta camada deixa isso explícito no campo `fontes`, devolvendo o
status real de cada órgão:

  • Receita Federal (via BrasilAPI) ...... FUNCIONA por CNPJ:
        razão social, CNAE principal, município e UF. (CPF não é público.)
  • IBGE (inferência) .................... bioma predominante por UF/município.
  • SICAR / CAR .......................... área preservada (RL + APP) vive aqui,
        mas a Consulta Pública exige o Nº DO CAR ou a geometria do imóvel — não
        há API por documento. Devolvemos status 'requer_car' com instrução.
  • INCRA (SIGEF / Acervo Fundiário) ..... dados geo (WFS); sem lookup por doc.
  • IBAMA (Áreas Embargadas) ............. consulta pública traz CPF/CNPJ do
        responsável; útil como ALERTA de passivo, não como área preservada.
  • IMA-SC (ex-FATMA) .................... licenciamento estadual; sem API por doc.

Quando você obtiver convênio/credenciais (SICAR institucional, API do IBAMA CTF,
webservice do IMA-SC), basta implementar as funções `consultar_car()`,
`consultar_embargos_ibama()` etc. — a estrutura de retorno já está pronta para
recebê-las sem mexer no resto do sistema.

------------------------------------------------------------------------------
Sem dependências externas: usa urllib (biblioteca padrão).
------------------------------------------------------------------------------
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error

BRASILAPI_CNPJ = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"

# Opções EXATAS do <select name="atividade"> no index.html (view Agro).
ATIV_AGRICULTURA = "Agricultura de Baixo Carbono"
ATIV_ILPF        = "ILPF (Integração Lavoura-Pecuária-Floresta)"
ATIV_PLANTIO     = "Plantio Direto na Palha"
ATIV_AGROFLOR    = "Agrofloresta / Sistemas Agroflorestais"
ATIV_PASTAGEM    = "Restauração de Pastagens Degradadas"
ATIV_REFLOR      = "Reflorestamento Comercial"
ATIV_DEJETOS     = "Manejo de Dejetos Animais"
ATIV_RL          = "Conservação de Reserva Legal"
ATIV_APP         = "Conservação de APP"

# Opções EXATAS do <select name="bioma"> no index.html.
BIOMAS_VALIDOS = {
    "Amazônia", "Cerrado", "Mata Atlântica", "Caatinga", "Pampa", "Pantanal",
}

# ── Inferência de bioma predominante por UF ──────────────────────────────────
# Heurística por estado. Vários estados são multi-bioma (ex.: MT, MG, BA, RS);
# nesses devolvemos o predominante + aviso para o usuário confirmar.
_UF_BIOMA: dict[str, str] = {
    "AC": "Amazônia", "AP": "Amazônia", "AM": "Amazônia", "PA": "Amazônia",
    "RO": "Amazônia", "RR": "Amazônia",
    "TO": "Cerrado", "GO": "Cerrado", "DF": "Cerrado",
    "MA": "Cerrado", "MT": "Cerrado", "MS": "Cerrado",
    "PI": "Caatinga", "CE": "Caatinga", "RN": "Caatinga", "PB": "Caatinga",
    "PE": "Caatinga", "AL": "Caatinga", "SE": "Caatinga", "BA": "Caatinga",
    "MG": "Cerrado",
    "ES": "Mata Atlântica", "RJ": "Mata Atlântica", "SP": "Mata Atlântica",
    "PR": "Mata Atlântica", "SC": "Mata Atlântica", "RS": "Mata Atlântica",
}
# Estados reconhecidamente multi-bioma — disparam aviso de confirmação.
_UF_MULTIBIOMA = {"MT", "MS", "MA", "MG", "BA", "RS", "TO"}


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _bioma_por_uf(uf: str) -> tuple[str, bool]:
    """Retorna (bioma_predominante, eh_multibioma). bioma vazio se UF desconhecida."""
    uf = (uf or "").strip().upper()
    return _UF_BIOMA.get(uf, ""), uf in _UF_MULTIBIOMA


def _atividade_por_cnae(cnae) -> str:
    """
    Sugere a atividade do certificado a partir do CNAE principal.
    Mapeia pelas divisões agropecuárias/florestais (2 primeiros dígitos).
    Retorna "" se não houver correspondência rural.
    """
    dig = _so_digitos(str(cnae)) if cnae is not None else ""
    if not dig:
        return ""
    dig = dig.zfill(7)
    div = dig[:2]      # divisão CNAE
    grp = dig[:3]      # grupo CNAE

    if div == "02":                      # Produção florestal
        return ATIV_REFLOR
    if div == "01":                      # Agricultura, pecuária e serviços
        if grp in ("015",):              # Pecuária / criação de animais
            return ATIV_PASTAGEM
        if grp in ("011", "012", "013", "014"):  # Lavouras
            return ATIV_PLANTIO
        return ATIV_AGRICULTURA          # 016/017 serviços e caça → genérico
    return ""                            # 03 (pesca/aquicultura) e demais: sem match


def _fetch_brasilapi_cnpj(cnpj14: str, timeout: float = 8.0) -> dict:
    """
    Busca o payload completo da BrasilAPI (inclui município/UF, além do que
    app/services/cnpj.consultar_cnpj já normaliza). Lança ValueError em falha.
    """
    url = BRASILAPI_CNPJ.format(cnpj=cnpj14)
    req = urllib.request.Request(url, headers={"User-Agent": "ERP-CarbonFree/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError("CNPJ não encontrado na base pública da Receita.")
        raise ValueError(f"Erro na consulta CNPJ (HTTP {e.code}).")
    except urllib.error.URLError as e:
        raise ValueError(f"Falha de rede ao consultar a Receita: {e.reason}")
    except Exception as e:
        raise ValueError(f"Resposta inesperada da Receita: {e}")


# ── Encaixes para integrações futuras (convênio/credenciais) ─────────────────

def consultar_car(documento: str, numero_car: str | None = None) -> dict:
    """
    PLACEHOLDER HONESTO. A Consulta Pública do SICAR
    (https://consultapublica.car.gov.br) exige o NÚMERO DO CAR ou a geometria
    do imóvel — não há API por CPF/CNPJ. Quando houver acesso institucional ao
    SICAR (ou um nº de CAR informado), implemente aqui o fetch da área de
    Reserva Legal + APP e devolva {'area_preservada_ha': float, ...}.
    """
    return {
        "orgao": "SICAR / CAR",
        "status": "requer_car",
        "detalhe": (
            "Área preservada (Reserva Legal + APP) está no CAR, que só é "
            "consultável pelo Nº do CAR ou pela geometria do imóvel — não há "
            "consulta por CPF/CNPJ. Informe a área manualmente ou cadastre o "
            "Nº do CAR para integração institucional."
        ),
        "area_preservada_ha": None,
    }


def consultar_embargos_ibama(documento: str) -> dict:
    """
    PLACEHOLDER HONESTO. O IBAMA publica a lista de Áreas Embargadas (com CPF/CNPJ
    do responsável) em dados abertos / consulta pública. É um ALERTA DE PASSIVO,
    não a área preservada. Habilite quando quiser cruzar o documento contra essa
    base (download do CSV oficial ou webservice CTF).
    """
    return {
        "orgao": "IBAMA — Áreas Embargadas",
        "status": "nao_integrado",
        "detalhe": (
            "Cruzamento opcional contra a lista pública de áreas embargadas do "
            "IBAMA (alerta de passivo). Requer baixar o CSV oficial / acesso ao "
            "CTF; não fornece área preservada."
        ),
    }


# ── Orquestrador principal ───────────────────────────────────────────────────

def consultar_documento(documento: str) -> dict:
    """
    Recebe CNPJ (14 dígitos) ou CPF (11 dígitos) e devolve os dados consolidados
    para preencher o formulário de Certificado Rural, com transparência total
    sobre a origem de cada campo.

    Estrutura de retorno:
        {
          "documento": "...",
          "tipo_documento": "CNPJ" | "CPF",
          "titular": str,
          "campos_certificado": {
              "titular": str, "bioma": str, "atividade": str,
              "area_hectares": float | None
          },
          "cnae": str, "cnae_descricao": str,
          "municipio": str, "uf": str,
          "fontes":  [ {"orgao","status","detalhe"}, ... ],
          "avisos":  [ str, ... ],
        }
    """
    dig = _so_digitos(documento)
    if len(dig) == 14:
        return _consultar_por_cnpj(dig)
    if len(dig) == 11:
        return _consultar_por_cpf(dig)
    raise ValueError("Informe um CNPJ (14 dígitos) ou um CPF (11 dígitos).")


def _consultar_por_cnpj(cnpj14: str) -> dict:
    fontes: list[dict] = []
    avisos: list[str] = []

    # 1) Receita Federal (BrasilAPI) — único lookup que realmente funciona por doc
    dados = _fetch_brasilapi_cnpj(cnpj14)
    razao = dados.get("razao_social") or dados.get("nome") or ""
    cnae = dados.get("cnae_fiscal")
    cnae_desc = dados.get("cnae_fiscal_descricao") or ""
    municipio = dados.get("municipio") or ""
    uf = (dados.get("uf") or "").upper()
    fontes.append({
        "orgao": "Receita Federal (BrasilAPI)",
        "status": "ok",
        "detalhe": f"Razão social, CNAE {cnae or '—'} e município ({municipio}/{uf}) obtidos.",
    })

    # 2) IBGE — inferência de bioma por UF
    bioma, multi = _bioma_por_uf(uf)
    if bioma:
        det = f"Bioma predominante inferido pela UF ({uf}): {bioma}."
        if multi:
            det += " Estado multi-bioma — confirme se confere com a localização do imóvel."
            avisos.append(
                f"{uf} possui mais de um bioma. Confirmei '{bioma}' como predominante, "
                "mas verifique o bioma real da propriedade (idealmente pelo CAR/MapBiomas)."
            )
        fontes.append({"orgao": "IBGE (inferência por UF)", "status": "ok", "detalhe": det})
    else:
        fontes.append({
            "orgao": "IBGE (inferência por UF)",
            "status": "indisponivel",
            "detalhe": "UF não identificada — selecione o bioma manualmente.",
        })
        avisos.append("Não foi possível inferir o bioma — selecione manualmente.")

    # 3) Atividade sugerida pelo CNAE
    atividade = _atividade_por_cnae(cnae)
    if atividade:
        fontes.append({
            "orgao": "Atividade (via CNAE)",
            "status": "ok",
            "detalhe": f"Atividade sugerida a partir do CNAE: '{atividade}'. Confirme a prática real.",
        })
        avisos.append(
            "A atividade foi sugerida pelo CNAE e pode não refletir a prática "
            "regenerativa específica do imóvel — revise antes de emitir."
        )
    else:
        fontes.append({
            "orgao": "Atividade (via CNAE)",
            "status": "indisponivel",
            "detalhe": "CNAE sem correspondência rural direta — selecione a atividade manualmente.",
        })

    # 4) SICAR/CAR — área preservada (não disponível por documento)
    car = consultar_car(cnpj14)
    fontes.append({"orgao": car["orgao"], "status": car["status"], "detalhe": car["detalhe"]})
    area_ha = car.get("area_preservada_ha")
    if area_ha is None:
        avisos.append(
            "Área preservada NÃO vem por CNPJ — está no CAR (Nº do CAR/geometria). "
            "Informe manualmente ou habilite a integração institucional do SICAR."
        )

    # 5) IBAMA / INCRA / IMA-SC — sem lookup por documento (alertas/encaixes)
    fontes.append(consultar_embargos_ibama(cnpj14))
    fontes.append({
        "orgao": "INCRA (SIGEF/Acervo) · IMA-SC",
        "status": "nao_integrado",
        "detalhe": "Sem API pública por documento; integração requer convênio/credenciais.",
    })

    return {
        "documento": cnpj14,
        "tipo_documento": "CNPJ",
        "titular": razao,
        "campos_certificado": {
            "titular": razao,
            "bioma": bioma,
            "atividade": atividade,
            "area_hectares": area_ha,
        },
        "cnae": str(cnae or ""),
        "cnae_descricao": cnae_desc,
        "municipio": municipio,
        "uf": uf,
        "fontes": fontes,
        "avisos": avisos,
    }


def _consultar_por_cpf(cpf11: str) -> dict:
    """
    CPF não tem base cadastral pública (sigilo/LGPD). Não há de onde puxar razão
    social, bioma ou atividade só com o CPF. Devolvemos a estrutura preenchível
    manualmente, com transparência sobre o motivo.
    """
    return {
        "documento": cpf11,
        "tipo_documento": "CPF",
        "titular": "",
        "campos_certificado": {
            "titular": "", "bioma": "", "atividade": "", "area_hectares": None,
        },
        "cnae": "", "cnae_descricao": "", "municipio": "", "uf": "",
        "fontes": [
            {
                "orgao": "Receita Federal",
                "status": "indisponivel",
                "detalhe": "Dados de pessoa física (CPF) não são públicos (LGPD) — "
                           "não há consulta automática de nome/atividade por CPF.",
            },
            {
                "orgao": "SICAR / CAR",
                "status": "requer_car",
                "detalhe": "Imóveis de pessoa física também só são consultáveis pelo "
                           "Nº do CAR ou geometria — não por CPF.",
            },
        ],
        "avisos": [
            "Para CPF, preencha titular, bioma, atividade e área manualmente "
            "(ou use o Nº do CAR quando a integração institucional estiver ativa).",
        ],
    }
