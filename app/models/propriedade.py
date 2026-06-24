from dataclasses import dataclass, field


@dataclass
class Propriedade:
    titular: str
    area_hectares: float
    bioma: str
    atividade: str
    usuario_id: str = ""
