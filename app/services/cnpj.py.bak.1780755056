"""
Consulta de CNPJ na base PÚBLICA da Receita Federal (via BrasilAPI) e
mapeamento do CNAE principal para a categoria setorial usada no cálculo
por balanço (PERFIS_SETORIAIS em app/services/motor_ia.py).

Sem dependências externas: usa urllib (biblioteca padrão do Python).
Fonte: https://brasilapi.com.br/api/cnpj/v1/{cnpj}  (Dados Públicos CNPJ / RFB)

LIMITAÇÃO IMPORTANTE: a base pública traz apenas dados CADASTRAIS
(razão social, CNAE, capital social, porte, situação). Ela NÃO traz
faturamento nem balanço — esses dados são sigilosos (SPED/ECF) e não têm
API pública. O faturamento continua sendo informado pelo usuário (ou, para
companhias abertas, obtido via dados abertos da CVM).
"""

import json
import re
import urllib.request
import urllib.error

BRASILAPI_CNPJ = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"

# Mapa: divisão CNAE (2 primeiros dígitos do código) → categoria de PERFIS_SETORIAIS.
# CNAE tem 7 dígitos; a "divisão" são os 2 primeiros e já define bem o setor.
_DIVISAO_PARA_CATEGORIA: dict[str, str] = {
    # Agropecuária
    "01": "agronegocio", "02": "agronegocio", "03": "agronegocio",
    # Indústrias extrativas (mineração)
    "05": "mineracao", "06": "mineracao", "07": "mineracao",
    "08": "mineracao", "09": "mineracao",
    # Alimentos e bebidas
    "10": "industria_alimenticia", "11": "industria_alimenticia",
    # Têxtil / vestuário / couro e calçados
    "13": "textil", "14": "textil", "15": "textil",
    # Papel e celulose
    "17": "papel_celulose",
    # Química e farmoquímica
    "20": "industria_quimica", "21": "industria_quimica",
    # Minerais não-metálicos (cimento, cerâmica, vidro)
    "23": "industria_cimento",
    # Metalurgia e produtos de metal
    "24": "industria_metalurgica", "25": "industria_metalurgica",
    # Eletricidade e gás
    "35": "energia_geracao",
    # Construção
    "41": "construcao_civil", "42": "construcao_civil", "43": "construcao_civil",
    # Comércio (atacado e varejo)
    "45": "comercio_varejo", "46": "comercio_varejo", "47": "comercio_varejo",
    # Transporte e armazenagem
    "49": "transporte_logistica", "50": "transporte_logistica",
    "51": "transporte_logistica", "52": "transporte_logistica",
    "53": "transporte_logistica",
    # Informação e comunicação (TI)
    "58": "servicos_ti", "59": "servicos_ti", "60": "servicos_ti",
    "61": "servicos_ti", "62": "servicos_ti", "63": "servicos_ti",
    # Atividades financeiras e seguros
    "64": "servicos_financeiros", "65": "servicos_financeiros", "66": "servicos_financeiros",
}


def cnae_para_categoria(cnae) -> str | None:
    """
    Recebe um código CNAE (int ou str, com ou sem máscara) e devolve a chave
    de categoria de PERFIS_SETORIAIS, ou None se não houver mapeamento.
    """
    if cnae is None:
        return None
    digitos = re.sub(r"\D", "", str(cnae))
    if not digitos:
        return None
    # O CNAE tem 7 dígitos. Quando vem como número (ex.: BrasilAPI), divisões
    # 01–09 perdem o zero à esquerda (0111301 → 111301). Restauramos com zfill.
    digitos = digitos.zfill(7)
    return _DIVISAO_PARA_CATEGORIA.get(digitos[:2])


def consultar_cnpj(cnpj: str, timeout: float = 8.0) -> dict:
    """
    Consulta dados cadastrais públicos do CNPJ via BrasilAPI.

    Retorna dict normalizado com: cnpj, razao_social, nome_fantasia,
    cnae_fiscal, cnae_descricao, categoria_sugerida (chave ou None) e os
    campos auxiliares capital_social, porte, situacao.

    Lança ValueError se o CNPJ for inválido, não encontrado, ou se houver
    falha de rede.
    """
    digitos = re.sub(r"\D", "", cnpj or "")
    if len(digitos) != 14:
        raise ValueError("CNPJ deve ter 14 dígitos.")

    url = BRASILAPI_CNPJ.format(cnpj=digitos)
    req = urllib.request.Request(url, headers={"User-Agent": "ERP-CarbonFree/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            dados = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ValueError("CNPJ não encontrado na base pública.")
        raise ValueError(f"Erro na consulta CNPJ (HTTP {e.code}).")
    except urllib.error.URLError as e:
        raise ValueError(f"Falha de rede ao consultar CNPJ: {e.reason}")
    except Exception as e:  # JSON inválido, etc.
        raise ValueError(f"Resposta inesperada da consulta CNPJ: {e}")

    cnae = dados.get("cnae_fiscal")
    return {
        "cnpj": digitos,
        "razao_social": dados.get("razao_social") or dados.get("nome") or "",
        "nome_fantasia": dados.get("nome_fantasia") or "",
        "cnae_fiscal": cnae,
        "cnae_descricao": dados.get("cnae_fiscal_descricao") or "",
        "categoria_sugerida": cnae_para_categoria(cnae),  # pode ser None
        "capital_social": dados.get("capital_social"),
        "porte": dados.get("porte") or dados.get("descricao_porte") or "",
        "situacao": dados.get("descricao_situacao_cadastral") or "",
    }
