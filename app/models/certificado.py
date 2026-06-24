from dataclasses import dataclass


@dataclass
class Certificado:
    codigo: str
    titular: str
    area_hectares: float
    bioma: str
    atividade: str
    percentual_bioma: float
    valor_cota: float
    descricao_atividade: str
    hash_sha256: str = ""
    caminho_pdf: str = ""
