"""
Inicia o servidor da API REST para integração SAP/TOTVS.

Uso:
    python start_api.py
    python start_api.py --host 0.0.0.0 --port 8000

Documentação interativa: http://localhost:8000/docs
"""

import sys

def checar_deps():
    faltando = []
    try:
        import fastapi
    except ImportError:
        faltando.append("fastapi")
    try:
        import uvicorn
    except ImportError:
        faltando.append("uvicorn")
    if faltando:
        print("Dependências da API não instaladas. Execute:")
        print(f"  pip install {' '.join(faltando)}")
        print("ou:")
        print(f"  uv pip install {' '.join(faltando)}")
        sys.exit(1)

if __name__ == "__main__":
    checar_deps()
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="MBV ERP — API REST")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    print(f"\nMBV ERP API iniciando em http://{args.host}:{args.port}")
    print(f"Documentação: http://{args.host}:{args.port}/docs\n")

    uvicorn.run(
        "app.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
