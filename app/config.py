import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY: str = os.getenv("SUPABASE_SERVICE_KEY", "")

# Valor base por hectare (R$) — configurável pelo admin no futuro
VALOR_BASE_HECTARE: float = 160.00

# Biomas brasileiros com percentual mínimo de Reserva Legal obrigatória (Lei 12.651/2012)
BIOMAS: dict[str, float] = {
    "Amazônia":               0.80,
    "Cerrado":                0.35,
    "Mata Atlântica":         0.20,
    "Caatinga":               0.20,
    "Pampa":                  0.20,
    "Pantanal":               0.20,
    "Zona Costeira e Marinha": 0.20,
}

# Atividades com seus multiplicadores de bônus sobre o valor base
ATIVIDADES: dict[str, dict] = {
    "Preservação de Área Nativa": {
        "multiplicador": 1.00,
        "descricao": "Cálculo Padrão de Preservação",
    },
    "Preservação + Meliponicultura (Abelhas de Casca)": {
        "multiplicador": 1.40,
        "descricao": "Bônus de Biodiversidade Aplicado (Polinizadores)",
    },
    "Reflorestamento com Mudas Nativas": {
        "multiplicador": 1.25,
        "descricao": "Bônus de Reflorestamento com Espécies Nativas",
    },
    "Controle de Formigas + Plantio de Mudas": {
        "multiplicador": 1.30,
        "descricao": "Bônus de Manejo Ativo com Controle Biológico",
    },
}

DIR_CERTIFICADOS = "certificados"

# ─── Anexo de evidências (NF-e, laudos, faturas etc.) ───────────────────────
# Bucket privado no Supabase Storage. Todo acesso passa pelo backend com a
# service key — ver app/database/client.py:get_storage_client().
SUPABASE_BUCKET_EVIDENCIAS: str = os.getenv("SUPABASE_BUCKET_EVIDENCIAS", "evidencias-compliance")
EVIDENCIA_TAMANHO_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB

EVIDENCIA_MIME_PERMITIDOS: set[str] = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",        # .xlsx
    "application/vnd.ms-excel",  # .xls
    "text/xml",
    "application/xml",  # NF-e
    "text/plain",
}
