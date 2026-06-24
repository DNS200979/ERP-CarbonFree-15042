from app.config import BIOMAS, ATIVIDADES, VALOR_BASE_HECTARE


def calcular_cota_carbono(area_hectares: float, bioma: str, atividade: str) -> dict:
    """
    Fórmula base (Jornada do Usuário MBV):
        valor = (área - área × %bioma) × valor_por_hectare × multiplicador_atividade

    O %bioma representa a Reserva Legal obrigatória por lei (Lei 12.651/2012),
    que não compõe o crédito elegível.
    """
    percentual_bioma = BIOMAS.get(bioma, 0.20)
    config = ATIVIDADES.get(atividade, list(ATIVIDADES.values())[0])

    area_util = area_hectares * (1.0 - percentual_bioma)
    valor_cota = area_util * VALOR_BASE_HECTARE * config["multiplicador"]

    return {
        "area_hectares": area_hectares,
        "bioma": bioma,
        "percentual_bioma": percentual_bioma,
        "area_util": round(area_util, 4),
        "atividade": atividade,
        "multiplicador": config["multiplicador"],
        "descricao": config["descricao"],
        "valor_cota": round(valor_cota, 2),
    }
