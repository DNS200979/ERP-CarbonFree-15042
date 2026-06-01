"""
app/services/ecf.py

Leitura automática da ECF (Escrituração Contábil Fiscal) — o arquivo SPED que
as empresas transmitem anualmente à Receita Federal (substituiu a DIPJ) para
apuração do IRPJ/CSLL. A partir dele extraímos, sem digitação manual, os dados
que alimentam o cálculo de emissões por balanço (motor_ia.calcular_por_balanco):

    • CNPJ e razão social ............... registro 0000
    • Período de apuração / ano ......... registro 0000 (datas ddmmaaaa)
    • Regime de tributação .............. presença do bloco L (Lucro Real)
                                          ou P (Lucro Presumido)
    • Receita bruta anual ............... linha da DRE (L300 / P150)
    • Gasto com energia elétrica ........ linha da DRE  -> refina o Escopo 2
    • Gasto com combustíveis ............ linha da DRE  -> refina o Escopo 1

Formato do arquivo: texto, um registro por linha, campos entre pipes "|":
    |REG|campo1|campo2|...|
Valores monetários usam vírgula decimal (padrão SPED): 50000000,00

----------------------------------------------------------------------------
SOBRE O LEIAUTE
O leiaute da ECF é publicado a cada ano pela RFB (Manual da ECF). Posições de
campos podem variar entre versões. Por isso este parser NÃO depende de posições
fixas para os valores financeiros: localiza a receita e as despesas pela
DESCRIÇÃO da conta na DRE (texto estável entre versões) e a identificação por
máscara (CNPJ = 14 dígitos, data = ddmmaaaa). Todo valor extraído é devolvido
para CONFERÊNCIA do usuário — nada é arquivado automaticamente sem revisão.

Empresas do Simples Nacional, em geral, não transmitem ECF; para elas use a
receita declarada na DEFIS/PGDAS-D e o caminho de entrada manual.
----------------------------------------------------------------------------
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


# -- utilidades ---------------------------------------------------------------

def _normalizar(texto: str) -> str:
    """MAIÚSCULAS sem acento, para casar descrições de contas."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.upper().strip()


def _num(valor: str) -> float:
    """Converte valor monetário SPED ('1.234.567,89' ou '1234567,89') em float."""
    if not valor:
        return 0.0
    v = valor.strip().replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return 0.0


def _eh_numero(s: str) -> bool:
    return bool(s) and bool(re.fullmatch(r"-?[\d.,]+", s)) and any(c.isdigit() for c in s)


# -- modelos ------------------------------------------------------------------

@dataclass
class LinhaDRE:
    codigo: str
    descricao: str
    valor: float
    indicador: str = ""   # 'D' (devedor/despesa) | 'C' (credor/receita)


@dataclass
class DadosECF:
    cnpj: str = ""
    razao_social: str = ""
    dt_inicial: str = ""          # ddmmaaaa
    dt_final: str = ""            # ddmmaaaa
    ano_referencia: int = 0
    regime: str = "desconhecido"  # 'lucro_real' | 'lucro_presumido' | 'desconhecido'
    receita_bruta: float = 0.0
    gasto_energia_eletrica: float = 0.0
    gasto_combustivel: float = 0.0
    dre: list[LinhaDRE] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def periodo(self) -> str:
        def f(d):
            return f"{d[:2]}/{d[2:4]}/{d[4:]}" if len(d) == 8 else d
        return f"{f(self.dt_inicial)} a {f(self.dt_final)}" if self.dt_inicial else ""

    def resumo(self) -> dict:
        return {
            "cnpj": self.cnpj,
            "razao_social": self.razao_social,
            "ano_referencia": self.ano_referencia,
            "periodo": self.periodo,
            "regime": self.regime,
            "receita_bruta": round(self.receita_bruta, 2),
            "gasto_energia_eletrica": round(self.gasto_energia_eletrica, 2),
            "gasto_combustivel": round(self.gasto_combustivel, 2),
            "avisos": self.avisos,
        }


# -- heurísticas de classificação de contas da DRE ----------------------------

def _eh_receita_bruta(desc_norm: str) -> bool:
    if "RECEITA" not in desc_norm:
        return False
    return any(t in desc_norm for t in ("BRUTA", "VENDA", "REVENDA", "PRESTACAO DE SERVICO"))


def _eh_energia(desc_norm: str) -> bool:
    return "ENERGIA ELETRICA" in desc_norm or ("ENERGIA" in desc_norm and "ELETRIC" in desc_norm)


def _eh_combustivel(desc_norm: str) -> bool:
    return "COMBUSTIVEL" in desc_norm or "COMBUSTIVEIS" in desc_norm


# -- parsing de registros -----------------------------------------------------

def _parse_0000(campos: list[str], dados: DadosECF) -> None:
    valores = [c.strip() for c in campos]
    # CNPJ = primeiro campo com exatamente 14 dígitos (aparece cedo, antes do nº do recibo)
    for v in valores[2:]:
        if re.fullmatch(r"\d{14}", v):
            dados.cnpj = v
            break
    # Razão social = campo imediatamente após o CNPJ
    if dados.cnpj:
        try:
            i = valores.index(dados.cnpj)
            if i + 1 < len(valores) and valores[i + 1]:
                dados.razao_social = valores[i + 1]
        except ValueError:
            pass
    # Datas ddmmaaaa válidas -> menor = início, maior = fim, ano = do fim
    datas = []
    for v in valores:
        if re.fullmatch(r"\d{8}", v):
            dd, mm, aaaa = int(v[:2]), int(v[2:4]), int(v[4:])
            if 1 <= dd <= 31 and 1 <= mm <= 12 and 1900 <= aaaa <= 2100:
                datas.append((aaaa, mm, dd, v))
    if datas:
        datas.sort()
        dados.dt_inicial = datas[0][3]
        dados.dt_final = datas[-1][3]
        dados.ano_referencia = datas[-1][0]


def _coletar_dre(campos: list[str], dados: DadosECF, candidatos: list) -> None:
    valores = [c.strip() for c in campos]
    # descrição = primeiro campo com letras (>= índice 2)
    idx_desc = None
    for i in range(2, len(valores)):
        if re.search(r"[A-Za-zÀ-ÿ]", valores[i]):
            idx_desc = i
            break
    if idx_desc is None:
        return
    descricao = valores[idx_desc]
    codigo = valores[2] if idx_desc != 2 else ""
    # valor = primeiro campo numérico depois da descrição; indicador D/C, se houver
    valor, indicador = 0.0, ""
    for j in range(idx_desc + 1, len(valores)):
        if _eh_numero(valores[j]):
            valor = _num(valores[j])
            if j + 1 < len(valores) and valores[j + 1] in ("D", "C"):
                indicador = valores[j + 1]
            break

    dados.dre.append(LinhaDRE(codigo, descricao, valor, indicador))

    d = _normalizar(descricao)
    if _eh_receita_bruta(d):
        candidatos.append((descricao, valor))
    if _eh_energia(d):
        dados.gasto_energia_eletrica += abs(valor)
    if _eh_combustivel(d):
        dados.gasto_combustivel += abs(valor)


def _consolidar_receita(dados: DadosECF, candidatos: list) -> None:
    if not candidatos:
        dados.avisos.append(
            "Receita bruta não localizada automaticamente na DRE — informe o "
            "faturamento manualmente antes de calcular."
        )
        return
    com_bruta = [c for c in candidatos if "BRUTA" in _normalizar(c[0])]
    escolha = max(com_bruta or candidatos, key=lambda c: c[1])
    dados.receita_bruta = escolha[1]
    if not com_bruta:
        dados.avisos.append(
            f"Não havia linha explícita de 'Receita Bruta'; usei '{escolha[0]}'. "
            "Confira se corresponde à receita bruta total."
        )


# -- ponto de entrada ---------------------------------------------------------

def parse_ecf(conteudo) -> DadosECF:
    """Lê o conteúdo de um arquivo ECF e devolve os dados extraídos."""
    if isinstance(conteudo, (bytes, bytearray)):
        texto = None
        for enc in ("utf-8-sig", "latin-1"):
            try:
                texto = bytes(conteudo).decode(enc)
                break
            except UnicodeDecodeError:
                continue
        conteudo = texto if texto is not None else bytes(conteudo).decode("latin-1", errors="replace")

    dados = DadosECF()
    candidatos_receita: list = []

    for linha in conteudo.splitlines():
        linha = linha.strip()
        if not linha.startswith("|"):
            continue
        campos = linha.split("|")
        if len(campos) < 2:
            continue
        reg = campos[1].strip().upper()

        if reg == "0000":
            _parse_0000(campos, dados)
        elif reg == "L300":            # DRE do Lucro Real
            if dados.regime == "desconhecido":
                dados.regime = "lucro_real"
            _coletar_dre(campos, dados, candidatos_receita)
        elif reg == "P150":            # DRE do Lucro Presumido
            if dados.regime == "desconhecido":
                dados.regime = "lucro_presumido"
            _coletar_dre(campos, dados, candidatos_receita)

    _consolidar_receita(dados, candidatos_receita)
    return dados
