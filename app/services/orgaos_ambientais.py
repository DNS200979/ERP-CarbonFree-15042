"""
app/services/orgaos_ambientais.py

Consulta de TITULAR RURAL por documento (CNPJ ou CPF), orquestrando as fontes
públicas para autopreencher o Certificado Rural: Titular/Razão social, Bioma,
Atividade e (quando possível) Área preservada.

Resiliência: timeout generoso + provedor de fallback (BrasilAPI → Minha Receita)
+ degradação graciosa (se nenhuma fonte responder, devolve a estrutura
preenchível manualmente, sem derrubar a tela).

CNAE: o código vem automaticamente da Receita (cnae_fiscal). Esta versão também
lê os CNAEs SECUNDÁRIOS — se o principal for comércio/serviço mas houver um
secundário de produção rural, a atividade é sugerida a partir dele. Tudo é
exposto em `fontes` para conferência (princípio de transparência).

Limites honestos: área preservada vive no CAR (Nº do CAR/geometria), não há API
por documento; INCRA/IBAMA/IMA-SC idem — encaixes deixados prontos.
Sem dependências externas: urllib (biblioteca padrão).
"""

from __future__ import annotations

import json
import re
import socket
import urllib.request
import urllib.error

PROVEDORES_CNPJ = [
    ("BrasilAPI",     "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"),
    ("Minha Receita", "https://minhareceita.org/{cnpj}"),
]

_TIMEOUT_S = 15.0
_TENTATIVAS = 2

# Opções EXATAS do <select name="atividade"> no index.html.
ATIV_AGRICULTURA = "Agricultura de Baixo Carbono"
ATIV_ILPF        = "ILPF (Integração Lavoura-Pecuária-Floresta)"
ATIV_PLANTIO     = "Plantio Direto na Palha"
ATIV_AGROFLOR    = "Agrofloresta / Sistemas Agroflorestais"
ATIV_PASTAGEM    = "Restauração de Pastagens Degradadas"
ATIV_REFLOR      = "Reflorestamento Comercial"
ATIV_DEJETOS     = "Manejo de Dejetos Animais"
ATIV_RL          = "Conservação de Reserva Legal"
ATIV_APP         = "Conservação de APP"

BIOMAS_VALIDOS = {
    "Amazônia", "Cerrado", "Mata Atlântica", "Caatinga", "Pampa", "Pantanal",
}

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
_UF_MULTIBIOMA = {"MT", "MS", "MA", "MG", "BA", "RS", "TO"}


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _fmt_cnae(cnae) -> str:
    """7 dígitos -> 'XXXX-X/XX' (formato oficial). Mantém como veio se não casar."""
    d = _so_digitos(str(cnae)) if cnae is not None else ""
    if len(d) == 7:
        return f"{d[:4]}-{d[4]}/{d[5:]}"
    return d


def _bioma_por_uf(uf: str) -> tuple[str, bool]:
    uf = (uf or "").strip().upper()
    return _UF_BIOMA.get(uf, ""), uf in _UF_MULTIBIOMA


def _atividade_por_cnae(cnae) -> str:
    """
    Sugere a atividade do certificado a partir de UM código CNAE.
    Cobre apenas PRODUÇÃO rural/florestal (divisões 01 e 02). Comércio/serviço
    (ex.: 47xx) devolve "" — não há prática regenerativa a inferir.
    """
    dig = _so_digitos(str(cnae)) if cnae is not None else ""
    if not dig:
        return ""
    dig = dig.zfill(7)
    div, grp = dig[:2], dig[:3]
    if div == "02":                       # Produção florestal
        return ATIV_REFLOR
    if div == "01":                       # Agricultura, pecuária e apoio
        if grp == "015":                  # Pecuária / criação
            return ATIV_PASTAGEM
        if grp in ("011", "012", "013", "014"):   # Lavouras / horticultura / floricultura
            return ATIV_PLANTIO
        return ATIV_AGRICULTURA           # 016/017 apoio e caça
    return ""


def _coletar_cnaes(dados: dict) -> tuple[str, str, list[dict]]:
    """
    Extrai o CNAE principal (codigo, descricao) e a lista de secundários
    (cada um {codigo_fmt, raw, descricao}). Compatível com BrasilAPI e Minha Receita.
    """
    principal = dados.get("cnae_fiscal")
    desc_princ = dados.get("cnae_fiscal_descricao") or ""

    secundarios: list[dict] = []
    for c in (dados.get("cnaes_secundarios") or []):
        if not isinstance(c, dict):
            continue
        cod = c.get("codigo") or c.get("cnae") or c.get("cnae_fiscal")
        if not cod:
            continue
        raw = _so_digitos(str(cod)).zfill(7)
        # Ignora o "0000000" que alguns provedores usam quando não há secundário
        if raw == "0000000":
            continue
        secundarios.append({
            "codigo": _fmt_cnae(cod),
            "raw": raw,
            "descricao": c.get("descricao") or c.get("cnae_descricao") or "",
        })
    return (str(principal or ""), desc_princ, secundarios)


def _resolver_atividade(cnae_principal: str, secundarios: list[dict]) -> tuple[str, str]:
    """
    Tenta o CNAE principal; se for comércio/serviço (não mapeia), varre os
    secundários e usa o primeiro de produção rural. Retorna (atividade, cnae_que_motivou).
    """
    a = _atividade_por_cnae(cnae_principal)
    if a:
        return a, _fmt_cnae(cnae_principal)
    for s in secundarios:
        a = _atividade_por_cnae(s["raw"])
        if a:
            return a, s["codigo"]
    return "", ""


def _fetch_cnpj(cnpj14: str) -> tuple[dict | None, str | None]:
    """Consulta com fallback/timeout. Nunca lança: (dados, None) ou (None, motivo)."""
    ultimo_erro = ""
    for nome, tpl in PROVEDORES_CNPJ:
        url = tpl.format(cnpj=cnpj14)
        for _ in range(_TENTATIVAS):
            req = urllib.request.Request(
                url, headers={"User-Agent": "ERP-CarbonFree/1.0", "Accept": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                    return json.loads(resp.read().decode("utf-8")), None
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None, f"CNPJ não encontrado na base pública ({nome}, 404)."
                ultimo_erro = f"{nome}: HTTP {e.code}"
                break
            except (socket.timeout, TimeoutError):
                ultimo_erro = f"{nome}: tempo de resposta esgotado (timeout)"
                continue
            except urllib.error.URLError as e:
                ultimo_erro = f"{nome}: falha de rede ({getattr(e, 'reason', e)})"
                continue
            except Exception as e:
                ultimo_erro = f"{nome}: resposta inesperada ({e})"
                break
    return None, (ultimo_erro or "indisponível")


# ── Encaixes para integrações futuras ────────────────────────────────────────

def consultar_car(documento: str, numero_car: str | None = None) -> dict:
    return {
        "orgao": "SICAR / CAR",
        "status": "requer_car",
        "detalhe": (
            "Área preservada (Reserva Legal + APP) está no CAR, consultável só "
            "pelo Nº do CAR ou geometria — não por CPF/CNPJ. Informe a área "
            "manualmente ou cadastre o Nº do CAR para integração institucional."
        ),
        "area_preservada_ha": None,
    }


def consultar_embargos_ibama(documento: str) -> dict:
    return {
        "orgao": "IBAMA — Áreas Embargadas",
        "status": "nao_integrado",
        "detalhe": (
            "Cruzamento opcional contra a lista pública de áreas embargadas do "
            "IBAMA (alerta de passivo). Requer CSV oficial / acesso ao CTF."
        ),
    }


# ── Orquestrador ─────────────────────────────────────────────────────────────

def consultar_documento(documento: str) -> dict:
    dig = _so_digitos(documento)
    if len(dig) == 14:
        return _consultar_por_cnpj(dig)
    if len(dig) == 11:
        return _consultar_por_cpf(dig)
    raise ValueError("Informe um CNPJ (14 dígitos) ou um CPF (11 dígitos).")


def _resposta_base(documento: str, tipo: str) -> dict:
    return {
        "documento": documento,
        "tipo_documento": tipo,
        "titular": "",
        "campos_certificado": {
            "titular": "", "bioma": "", "atividade": "", "area_hectares": None,
        },
        "cnae": "", "cnae_descricao": "", "cnaes_secundarios": [],
        "municipio": "", "uf": "",
        "fontes": [], "avisos": [],
    }


def _consultar_por_cnpj(cnpj14: str) -> dict:
    out = _resposta_base(cnpj14, "CNPJ")
    fontes, avisos = out["fontes"], out["avisos"]

    dados, erro = _fetch_cnpj(cnpj14)
    if dados is None:
        fontes.append({
            "orgao": "Receita Federal",
            "status": "indisponivel",
            "detalhe": f"Consulta não concluída — {erro}. "
                       "Tente de novo em alguns segundos ou preencha manualmente.",
        })
        fontes.append(consultar_car(cnpj14))
        avisos.append(
            "A consulta pública à Receita não respondeu agora (lentidão temporária). "
            "Clique em Buscar dados de novo, ou preencha os campos manualmente."
        )
        return out

    razao = dados.get("razao_social") or dados.get("nome") or ""
    municipio = dados.get("municipio") or ""
    uf = (dados.get("uf") or "").upper()

    cnae_principal, desc_princ, secundarios = _coletar_cnaes(dados)

    out["titular"] = razao
    out["cnae"] = _fmt_cnae(cnae_principal)
    out["cnae_descricao"] = desc_princ
    out["cnaes_secundarios"] = secundarios
    out["municipio"] = municipio
    out["uf"] = uf
    out["campos_certificado"]["titular"] = razao

    fontes.append({
        "orgao": "Receita Federal",
        "status": "ok",
        "detalhe": f"Razão social e município ({municipio}/{uf}) obtidos.",
    })

    # ── CNAE principal (sempre exibido) ──
    fontes.append({
        "orgao": "CNAE principal",
        "status": "ok",
        "detalhe": f"{_fmt_cnae(cnae_principal) or '—'}"
                   + (f" — {desc_princ}" if desc_princ else ""),
    })
    # ── CNAEs secundários (quando houver) ──
    if secundarios:
        lista = "; ".join(
            f"{s['codigo']}" + (f" {s['descricao']}" if s['descricao'] else "")
            for s in secundarios[:8]
        )
        fontes.append({
            "orgao": "CNAEs secundários",
            "status": "ok",
            "detalhe": lista + ("…" if len(secundarios) > 8 else ""),
        })

    # ── Bioma por UF ──
    bioma, multi = _bioma_por_uf(uf)
    if bioma:
        out["campos_certificado"]["bioma"] = bioma
        det = f"Bioma predominante inferido pela UF ({uf}): {bioma}."
        if multi:
            det += " Estado multi-bioma — confirme com a localização do imóvel."
            avisos.append(
                f"{uf} tem mais de um bioma; sugeri '{bioma}'. Confirme o bioma real "
                "da propriedade (idealmente via CAR/MapBiomas)."
            )
        fontes.append({"orgao": "IBGE (inferência por UF)", "status": "ok", "detalhe": det})
    else:
        fontes.append({
            "orgao": "IBGE (inferência por UF)",
            "status": "indisponivel",
            "detalhe": "UF não identificada — selecione o bioma manualmente.",
        })

    # ── Atividade (principal → secundários) ──
    atividade, cnae_usado = _resolver_atividade(cnae_principal, secundarios)
    if atividade:
        out["campos_certificado"]["atividade"] = atividade
        origem = ("CNAE principal" if cnae_usado == _fmt_cnae(cnae_principal)
                  else f"CNAE secundário {cnae_usado}")
        fontes.append({
            "orgao": "Atividade (via CNAE)",
            "status": "ok",
            "detalhe": f"Sugerida pelo {origem}: '{atividade}'. Confirme a prática real.",
        })
        avisos.append(
            "A atividade foi sugerida pelo CNAE e pode não refletir a prática "
            "regenerativa específica do imóvel — revise antes de emitir."
        )
    else:
        fontes.append({
            "orgao": "Atividade (via CNAE)",
            "status": "indisponivel",
            "detalhe": f"O CNAE {_fmt_cnae(cnae_principal) or '—'} é de comércio/serviço "
                       "(não é produção rural) e não há CNAE secundário rural — "
                       "selecione a atividade manualmente.",
        })
        avisos.append(
            f"O CNAE {_fmt_cnae(cnae_principal) or '—'} não corresponde a uma prática "
            "rural geradora de CRVE (ex.: é comércio/varejo). Se a propriedade tiver "
            "atividade de conservação/produção, escolha-a manualmente."
        )

    # ── CAR / IBAMA / INCRA / IMA-SC ──
    car = consultar_car(cnpj14)
    fontes.append(car)
    if car.get("area_preservada_ha") is None:
        avisos.append(
            "Área preservada NÃO vem por CNPJ — está no CAR (Nº do CAR/geometria). "
            "Informe manualmente ou habilite a integração institucional do SICAR."
        )
    fontes.append(consultar_embargos_ibama(cnpj14))
    fontes.append({
        "orgao": "INCRA (SIGEF/Acervo) · IMA-SC",
        "status": "nao_integrado",
        "detalhe": "Sem API pública por documento; integração requer convênio/credenciais.",
    })

    return out


def _consultar_por_cpf(cpf11: str) -> dict:
    out = _resposta_base(cpf11, "CPF")
    out["fontes"] = [
        {
            "orgao": "Receita Federal",
            "status": "indisponivel",
            "detalhe": "Dados de pessoa física (CPF) não são públicos (LGPD) — "
                       "não há consulta automática de nome/CNAE por CPF.",
        },
        {
            "orgao": "SICAR / CAR",
            "status": "requer_car",
            "detalhe": "Imóveis de pessoa física também só são consultáveis pelo "
                       "Nº do CAR ou geometria — não por CPF.",
        },
    ]
    out["avisos"] = [
        "Para CPF, preencha titular, bioma, atividade e área manualmente "
        "(ou use o Nº do CAR quando a integração institucional estiver ativa).",
    ]
    return out
