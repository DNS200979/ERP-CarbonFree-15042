"""
Módulo 3 — API REST para integração com SAP, TOTVS e outros ERPs.

Iniciar servidor:
    uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --reload

Autenticação: Bearer token (JWT Supabase) no header Authorization.
"""

try:
    from fastapi import FastAPI, Depends, HTTPException, status
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    _FASTAPI_OK = True
except ImportError:
    _FASTAPI_OK = False

if not _FASTAPI_OK:
    raise ImportError(
        "FastAPI não instalado. Execute:\n"
        "  pip install fastapi uvicorn\n"
        "ou: uv pip install fastapi uvicorn"
    )

from app.api.routes import emissoes, certificados, integracao, calculadoras, mrv_mensal, documentos
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import SUPABASE_URL, SUPABASE_KEY


app = FastAPI(
    title="MBV ERP — API de Integração",
    description=(
        "API REST para integração do ERP Movimento Brasil Verde com sistemas externos "
        "(SAP, TOTVS, Oracle, etc.). Autenticação via JWT Supabase."
    ),
    version="1.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(emissoes.router,      prefix="/api/v1/emissoes",      tags=["Emissões de Carbono"])
app.include_router(certificados.router,  prefix="/api/v1/certificados",  tags=["Certificados Ambientais"])
app.include_router(integracao.router,    prefix="/api/v1/integracao",    tags=["Integração SAP / TOTVS"])
app.include_router(calculadoras.router,  prefix="/api/v1/calculadoras",  tags=["Calculadoras IA (atômicas)"])
app.include_router(mrv_mensal.router,    prefix="/api/v1/mrv",           tags=["MRV Mensal (Etapa 1 SBCE)"])
app.include_router(documentos.router,    prefix="/api/v1/documentos",    tags=["Evidências (upload de documentos)"])

app.mount("/static", StaticFiles(directory="."), name="static")


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}


@app.get("/api/v1/public-config", tags=["Health"])
def public_config():
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_anon_key": SUPABASE_KEY,
        "api_base": "",
    }


@app.get("/mrv", include_in_schema=False)
def mrv_page():
    """Serve a página do módulo de Fechamento Mensal MRV."""
    return FileResponse("mrv_mensal.html")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse("index.html")
