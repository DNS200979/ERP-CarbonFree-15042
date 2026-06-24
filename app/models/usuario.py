from dataclasses import dataclass


@dataclass
class Usuario:
    id: str
    email: str
    nome: str = ""
