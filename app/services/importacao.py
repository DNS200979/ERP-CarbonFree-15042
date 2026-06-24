"""
Módulo de importação de dados de emissões a partir de arquivos CSV.
Suporta mapeamento de colunas e validação antes de salvar no Supabase.
"""

import csv
import io
from dataclasses import dataclass
from typing import Any


# Colunas esperadas no CSV padrão MBV (case-insensitive)
COLUNAS_CSV = {
    "empresa":          ["empresa", "razao social", "razão social", "company"],
    "cnpj_cpf":         ["cnpj", "cpf", "cnpj_cpf", "documento"],
    "ano_referencia":   ["ano", "year", "ano_referencia", "ano referencia"],
    "e1_estacionario":  ["escopo1_estacionario", "e1_estacionario", "combustivel_estacionario", "escopo 1 estacionario"],
    "e1_movel":         ["escopo1_movel", "e1_movel", "frota", "combustivel_movel", "escopo 1 movel"],
    "e1_processos":     ["escopo1_processos", "e1_processos", "processos", "escopo 1 processos"],
    "e1_fugitivas":     ["escopo1_fugitivas", "e1_fugitivas", "fugitivas", "escopo 1 fugitivas"],
    "e2_eletrica":      ["escopo2_eletrica", "e2_eletrica", "energia_eletrica", "eletrica", "escopo 2 eletrica"],
    "e2_vapor":         ["escopo2_vapor", "e2_vapor", "vapor", "escopo 2 vapor"],
    "e3_cadeia":        ["escopo3_cadeia", "e3_cadeia", "cadeia_fornecimento", "escopo 3 cadeia"],
    "e3_transporte":    ["escopo3_transporte", "e3_transporte", "transporte", "escopo 3 transporte"],
    "e3_residuos":      ["escopo3_residuos", "e3_residuos", "residuos", "escopo 3 residuos"],
    "cbe_disponiveis":  ["cbe", "cbe_disponiveis", "cotas_brasileiras"],
    "crve_disponiveis": ["crve", "crve_disponiveis", "certificados_reducao"],
}

OBRIGATORIOS = {"empresa", "cnpj_cpf", "ano_referencia"}
NUMERICOS = {
    "e1_estacionario", "e1_movel", "e1_processos", "e1_fugitivas",
    "e2_eletrica", "e2_vapor",
    "e3_cadeia", "e3_transporte", "e3_residuos",
    "cbe_disponiveis", "crve_disponiveis",
}


@dataclass
class ResultadoImportacao:
    total_linhas: int = 0
    importados: int = 0
    erros: list[str] = None

    def __post_init__(self):
        if self.erros is None:
            self.erros = []

    @property
    def sucesso(self) -> bool:
        return self.importados > 0

    def resumo(self) -> str:
        linhas = [
            f"Total de linhas lidas  : {self.total_linhas}",
            f"Registros importados   : {self.importados}",
            f"Erros encontrados      : {len(self.erros)}",
        ]
        if self.erros:
            linhas.append("\nDetalhes dos erros:")
            for e in self.erros[:10]:
                linhas.append(f"  • {e}")
            if len(self.erros) > 10:
                linhas.append(f"  ... e mais {len(self.erros) - 10} erros")
        return "\n".join(linhas)


def _mapear_cabecalho(cabecalho: list[str]) -> dict[str, str]:
    """Retorna mapeamento {coluna_csv → campo_interno}."""
    mapa = {}
    for col_csv in cabecalho:
        col_norm = col_csv.strip().lower().replace("-", "_").replace(" ", "_")
        for campo, aliases in COLUNAS_CSV.items():
            aliases_norm = [a.lower().replace(" ", "_") for a in aliases]
            if col_norm in aliases_norm:
                mapa[col_csv] = campo
                break
    return mapa


def _converter_numero(valor: str, campo: str, linha: int) -> tuple[float, str | None]:
    try:
        return float(str(valor).strip().replace(",", ".") or "0"), None
    except ValueError:
        return 0.0, f"Linha {linha}: '{campo}' com valor inválido '{valor}' — substituído por 0"


def parse_csv(conteudo: str | bytes) -> tuple[list[dict], list[str]]:
    """
    Lê um CSV e retorna (registros_validados, erros).
    Cada registro é um dict pronto para inserção em emissoes_carbono.
    """
    if isinstance(conteudo, bytes):
        conteudo = conteudo.decode("utf-8-sig", errors="replace")

    amostra = conteudo[:4096]
    delimitador = ";" if amostra.count(";") > amostra.count(",") else ","
    leitor = csv.DictReader(io.StringIO(conteudo), delimiter=delimitador)

    cabecalho = leitor.fieldnames or []
    mapa = _mapear_cabecalho(cabecalho)

    registros, erros = [], []

    for num_linha, linha_csv in enumerate(leitor, start=2):
        reg: dict[str, Any] = {}
        linha_erros = []

        for col_csv, campo in mapa.items():
            valor = linha_csv.get(col_csv, "").strip()
            if campo in NUMERICOS:
                num, erro = _converter_numero(valor, campo, num_linha)
                reg[campo] = num
                if erro:
                    linha_erros.append(erro)
            elif campo == "ano_referencia":
                try:
                    reg[campo] = int(valor)
                except ValueError:
                    linha_erros.append(f"Linha {num_linha}: 'ano_referencia' inválido '{valor}'")
                    reg[campo] = 0
            else:
                reg[campo] = valor

        # Checar obrigatórios
        for campo_obrig in OBRIGATORIOS:
            if not reg.get(campo_obrig):
                linha_erros.append(f"Linha {num_linha}: campo obrigatório '{campo_obrig}' ausente")

        if any(e.startswith(f"Linha {num_linha}: campo obrigatório") for e in linha_erros):
            erros.extend(linha_erros)
            continue  # pula linha inválida

        # Preencher campos faltantes com 0
        for campo in NUMERICOS:
            reg.setdefault(campo, 0.0)

        # Calcular totais e status
        e1 = reg["e1_estacionario"] + reg["e1_movel"] + reg["e1_processos"] + reg["e1_fugitivas"]
        e2 = reg["e2_eletrica"] + reg["e2_vapor"]
        e3 = reg["e3_cadeia"] + reg["e3_transporte"] + reg["e3_residuos"]
        total = round(e1 + e2 + e3, 4)
        ativos = reg["cbe_disponiveis"] + reg["crve_disponiveis"]
        deficit = round(total - ativos, 4)

        if total < 10_000:
            status = "ISENTO"
        elif total <= 25_000:
            status = "MONITORAMENTO OBRIGATÓRIO"
        else:
            status = "CONFORMIDADE TOTAL OBRIGATÓRIA"

        reg["total_tco2e"]          = total
        reg["deficit_tco2e"]        = deficit
        reg["status_conformidade"]  = status

        erros.extend(linha_erros)
        registros.append(reg)

    return registros, erros


def importar_para_supabase(
    registros: list[dict],
    usuario_id: str | None,
    supabase_client,
) -> ResultadoImportacao:
    """Insere os registros em lotes na tabela emissoes_carbono."""
    resultado = ResultadoImportacao(total_linhas=len(registros))

    for reg in registros:
        try:
            dados = dict(reg)
            dados["usuario_id"] = usuario_id
            supabase_client.table("emissoes_carbono").insert(dados).execute()
            resultado.importados += 1
        except Exception as e:
            resultado.erros.append(f"Empresa '{reg.get('empresa', '?')}': {e}")

    return resultado


TEMPLATE_CSV = (
    "empresa;cnpj_cpf;ano_referencia;"
    "e1_estacionario;e1_movel;e1_processos;e1_fugitivas;"
    "e2_eletrica;e2_vapor;"
    "e3_cadeia;e3_transporte;e3_residuos;"
    "cbe_disponiveis;crve_disponiveis\n"
    "Empresa Exemplo Ltda;12.345.678/0001-99;2024;"
    "1200.5;800.0;0;50.0;"
    "3400.0;0;"
    "500.0;300.0;120.0;"
    "2000.0;0\n"
)
