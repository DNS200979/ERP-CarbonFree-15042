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

from app.api.routes import emissoes, certificados, integracao
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse


app = FastAPI(
    title="MBV ERP — API de Integração",
    description=(
        "API REST para integração do ERP Movimento Brasil Verde com sistemas externos "
        "(SAP, TOTVS, Oracle, etc.). Autenticação via JWT Supabase."
    ),
    version="1.0.0",
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
app.include_router(integracao.router,    prefix="/api/v1/integracao",     tags=["Integração SAP / TOTVS"])
app.mount("/static", StaticFiles(directory="."), name="static")


@app.get("/", tags=["Health"])
def raiz():
    return {"status": "ok", "sistema": "MBV ERP API", "versao": "1.0.0"}


@app.get("/health", tags=["Health"])
def health():
    return {"status": "healthy"}
    
@app.get("/", include_in_schema=False)
def index():
    return FileResponse("index.html")
