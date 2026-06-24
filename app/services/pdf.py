import os
from fpdf import FPDF
from app.config import DIR_CERTIFICADOS
from app.models.certificado import Certificado


def gerar_pdf(cert: Certificado) -> bytes:
    pdf = FPDF()
    pdf.add_page()

    # Cabeçalho
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(34, 139, 34)
    pdf.cell(0, 10, "MOVIMENTO BRASIL VERDE", ln=True, align="C")

    pdf.set_font("Helvetica", "I", 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, "Certificado Oficial de Conformidade Ambiental", ln=True, align="C")
    pdf.cell(0, 7, "Base Legal: Lei 15.042/2024 | Lei 14.119/2021 | Lei 12.651/2012", ln=True, align="C")

    pdf.set_draw_color(34, 139, 34)
    pdf.line(10, 40, 200, 40)
    pdf.ln(14)

    # Dados do titular e propriedade
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(0, 0, 0)

    area_util = cert.area_hectares * (1.0 - cert.percentual_bioma)

    linhas = [
        f"Titular / Razao Social : {cert.titular}",
        f"Area do Projeto        : {cert.area_hectares:.2f} Hectares",
        f"Bioma                  : {cert.bioma}",
        f"Reserva Legal Obrigat. : {cert.percentual_bioma * 100:.0f}% da area total",
        f"Area Util Computada    : {area_util:.2f} Hectares",
        f"Atividade Registrada   : {cert.atividade}",
        f"Observacao             : {cert.descricao_atividade}",
    ]
    for linha in linhas:
        pdf.cell(0, 9, linha, ln=True)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(34, 100, 34)
    pdf.cell(0, 10, f"Lastro Estimado da Cota-Carbono: R$ {cert.valor_cota:.2f}", ln=True)

    pdf.ln(8)

    # Bloco de autenticidade
    pdf.set_fill_color(240, 245, 240)
    pdf.set_text_color(50, 50, 50)
    pdf.set_font("Courier", "", 9)
    pdf.multi_cell(
        0, 7,
        f"AUTENTICIDADE E RASTREABILIDADE\n"
        f"Codigo de Emissao : {cert.codigo}\n"
        f"Hash SHA-256      : {cert.hash_sha256 or '(calculado apos geracao)'}\n"
        f"A integridade digital deste documento e garantida via criptografia SHA-256.",
        border=1, fill=True, align="L",
    )

    return bytes(pdf.output())


def salvar_pdf(pdf_bytes: bytes, codigo: str) -> str:
    os.makedirs(DIR_CERTIFICADOS, exist_ok=True)
    caminho = os.path.join(DIR_CERTIFICADOS, f"certificado_{codigo}.pdf")
    with open(caminho, "wb") as f:
        f.write(pdf_bytes)
    return caminho


def gerar_relatorio_emissoes(emissao) -> bytes:
    from app.models.emissao import Emissao

    COR_STATUS = {
        "ISENTO":                       (39, 174, 96),
        "MONITORAMENTO OBRIGATÓRIO":    (230, 126, 34),
        "CONFORMIDADE TOTAL OBRIGATÓRIA": (231, 76, 60),
    }

    pdf = FPDF()
    pdf.add_page()

    # Cabeçalho
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(34, 139, 34)
    pdf.cell(0, 10, "MOVIMENTO BRASIL VERDE", ln=True, align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "Relatorio de Inventario de Emissoes de Gases de Efeito Estufa", ln=True, align="C")
    pdf.cell(0, 6, "GHG Protocol Brasil  |  ISO 14064-1:2018  |  Lei 15.042/2024", ln=True, align="C")
    pdf.set_draw_color(34, 139, 34)
    pdf.line(10, 36, 200, 36)
    pdf.ln(10)

    # Dados da empresa
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.set_fill_color(212, 237, 218)
    pdf.cell(0, 8, "  DADOS DA EMPRESA", ln=True, fill=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(2)
    for label, valor in [
        ("Empresa / Razao Social", emissao.empresa),
        ("CNPJ / CPF", emissao.cnpj_cpf or "Nao informado"),
        ("Ano de Referencia", str(emissao.ano_referencia)),
    ]:
        pdf.cell(70, 8, f"  {label}:", border=0)
        pdf.cell(0, 8, str(valor), ln=True)

    pdf.ln(4)

    # Tabela de emissões por escopo
    def _ascii(text: str) -> str:
        import unicodedata
        normalizado = unicodedata.normalize("NFKD", text)
        return "".join(c for c in normalizado if ord(c) < 256).replace("—", "-").replace("–", "-")

    def tabela_escopo(titulo, linhas, total):
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_fill_color(212, 237, 218)
        pdf.cell(0, 8, f"  {_ascii(titulo)}", ln=True, fill=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.ln(1)
        for fonte, valor in linhas:
            pdf.set_fill_color(245, 250, 245)
            pdf.cell(130, 7, f"    {fonte}", border="B", fill=True)
            pdf.cell(0, 7, f"{valor:,.4f} tCO2e", ln=True, border="B", align="R")
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_fill_color(195, 230, 203)
        pdf.cell(130, 7, "    SUBTOTAL", fill=True)
        pdf.cell(0, 7, f"{total:,.4f} tCO2e", ln=True, align="R", fill=True)
        pdf.ln(3)

    tabela_escopo(
        "ESCOPO 1 — Emissoes Diretas",
        [("Combustiveis Estacionarios", emissao.e1_estacionario),
         ("Combustiveis Moveis / Frota", emissao.e1_movel),
         ("Processos Industriais", emissao.e1_processos),
         ("Emissoes Fugitivas", emissao.e1_fugitivas)],
        emissao.escopo1_total,
    )
    tabela_escopo(
        "ESCOPO 2 — Energia Indireta",
        [("Energia Eletrica Comprada", emissao.e2_eletrica),
         ("Vapor / Calor Comprado", emissao.e2_vapor)],
        emissao.escopo2_total,
    )
    tabela_escopo(
        "ESCOPO 3 — Outras Indiretas",
        [("Cadeia de Fornecimento", emissao.e3_cadeia),
         ("Transporte e Distribuicao", emissao.e3_transporte),
         ("Tratamento de Residuos", emissao.e3_residuos)],
        emissao.escopo3_total,
    )

    # Total geral
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_fill_color(34, 139, 34)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(130, 10, "  TOTAL GERAL DE EMISSOES (tCO2e)", fill=True)
    pdf.cell(0, 10, f"{emissao.total_tco2e:,.4f} tCO2e", ln=True, align="R", fill=True)
    pdf.ln(4)

    # Status de conformidade
    r, g, b = COR_STATUS.get(emissao.status_conformidade, (44, 62, 80))
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_fill_color(r, g, b)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, f"  STATUS SBCE: {_ascii(emissao.status_conformidade)}", ln=True, fill=True)
    pdf.ln(3)

    # Ativos e déficit
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_fill_color(212, 237, 218)
    pdf.cell(0, 8, "  ATIVOS DE CARBONO", ln=True, fill=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(1)
    for label, valor in [
        ("CBE Disponiveis", emissao.cbe_disponiveis),
        ("CRVE Disponiveis", emissao.crve_disponiveis),
        ("Total de Ativos", emissao.cbe_disponiveis + emissao.crve_disponiveis),
    ]:
        pdf.cell(130, 7, f"  {label}:")
        pdf.cell(0, 7, f"{valor:,.4f} tCO2e", ln=True, align="R")

    pdf.ln(2)
    deficit = emissao.deficit_tco2e
    if deficit > 0:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(231, 76, 60)
        pdf.cell(0, 8, f"  DEFICIT: {deficit:,.4f} tCO2e - necessario adquirir CBE/CRVE", ln=True)
    else:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(39, 174, 96)
        pdf.cell(0, 8, f"  SUPERAVIT: {abs(deficit):,.4f} tCO2e - posicao confortavel", ln=True)

    # Rodapé de autenticidade
    pdf.ln(6)
    pdf.set_text_color(50, 50, 50)
    pdf.set_fill_color(240, 245, 240)
    pdf.set_font("Courier", "", 8)
    pdf.multi_cell(
        0, 6,
        f"AUTENTICIDADE E RASTREABILIDADE\n"
        f"Hash SHA-256 : {emissao.hash_auditoria or '(calculado apos geracao)'}\n"
        f"Documento gerado pelo ERP Movimento Brasil Verde. Validade sujeita a verificacao pelo orgao gestor do SBCE.",
        border=1, fill=True, align="L",
    )

    return bytes(pdf.output())
