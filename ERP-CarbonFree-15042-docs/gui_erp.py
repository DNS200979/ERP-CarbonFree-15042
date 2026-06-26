import tkinter as tk
from tkinter import messagebox, ttk
import hashlib
from supabase import create_client
from fpdf import FPDF
import uuid
import os
from dotenv import load_dotenv

# Carrega as variáveis do arquivo .env
load_dotenv()

# --- CONFIGURAÇÃO ---
URL_PROJETO = os.getenv("SUPABASE_URL")
CHAVE_ANON = os.getenv("SUPABASE_KEY") 
supabase = create_client(URL_PROJETO, CHAVE_ANON)

# ==========================================
# FUNÇÃO 1: GRAVAR E GERAR CERTIFICADO
# ==========================================
def salvar_no_supabase():
    empresa = entry_empresa.get()
    area_texto = entry_area.get()
    tipo_projeto = combo_projeto.get()

    if not empresa or not area_texto or not tipo_projeto:
        messagebox.showwarning("Atenção", "Por favor, preencha todos os campos!")
        return

    try:
        area = float(area_texto.replace(",", "."))
        
        # Motor de Cálculo
        valor_base_por_hectare = 120.00 
        if tipo_projeto == "Projeto 1 Hectare + Meliponicultura (Abelhas de Casca)":
            valor_cota = area * (valor_base_por_hectare * 1.40) 
            descricao_bonus = "Bônus de Biodiversidade Aplicado (Polinizadores)"
        else:
            valor_cota = area * valor_base_por_hectare
            descricao_bonus = "Cálculo Padrão de Preservação"
            
        codigo_rastreio = str(uuid.uuid4()).split('-')[0].upper()

        # Gerador de PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 18)
        pdf.set_text_color(34, 139, 34) 
        pdf.cell(0, 10, "MOVIMENTO BRASIL VERDE", ln=True, align='C')
        
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(100, 100, 100) 
        pdf.cell(0, 8, "Certificado Oficial de Conformidade Ambiental", ln=True, align='C')
        pdf.cell(0, 8, "Base Legal: Lei 15.042/2024", ln=True, align='C')
        
        pdf.line(10, 40, 200, 40)
        pdf.ln(15)

        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(0, 0, 0) 
        pdf.cell(0, 10, f"Titular / Razão Social: {empresa}", ln=True)
        pdf.cell(0, 10, f"Área do Projeto: {area} Hectares", ln=True)
        pdf.cell(0, 10, f"Atividade Registrada: {tipo_projeto}", ln=True)
        pdf.cell(0, 10, f"Observação: {descricao_bonus}", ln=True)
        
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 10, f"Lastro Estimado da Cota-Carbono: R$ {valor_cota:.2f}", ln=True)
        pdf.ln(10)

        pdf.set_fill_color(240, 240, 240) 
        pdf.set_font("Courier", "", 10) 
        pdf.multi_cell(0, 8, 
                       f"AUTENTICIDADE E RASTREABILIDADE\n"
                       f"Código de Emissão: {codigo_rastreio}\n"
                       f"A integridade digital deste documento é garantida via Hash SHA-256.", 
                       border=1, fill=True, align='L')

        pdf_bytes = pdf.output()
        hash_seguranca = hashlib.sha256(pdf_bytes).hexdigest()

        # Gravação na Nuvem
        dados = {
            "pessoa_id": 1,
            "calculo_area": area,
            "calculo_valor_cota": valor_cota,
            "car_local_documento": f"certificado_{codigo_rastreio}.pdf",
            "hash_auditoria": hash_seguranca
        }

        supabase.table("documentos_compliance").insert(dados).execute()

        with open(f"certificado_{codigo_rastreio}.pdf", "wb") as f:
            f.write(pdf_bytes)

        messagebox.showinfo("Sucesso", f"Certificado Gerado!\nCódigo: {codigo_rastreio}")
        
        # Limpar tela
        entry_empresa.delete(0, tk.END)
        entry_area.delete(0, tk.END)
        combo_projeto.set('') 

    except ValueError:
        messagebox.showerror("Erro", "Na área, digite apenas números!")
    except Exception as e:
        messagebox.showerror("Erro", f"Não foi possível salvar: {e}")

# ==========================================
# FUNÇÃO 2: CONSULTAR HISTÓRICO NA NUVEM
# ==========================================
def consultar_historico():
    try:
        resposta = supabase.table("documentos_compliance").select("*").order("id", desc=True).limit(10).execute()
        registros = resposta.data

        janela_hist = tk.Toplevel(janela)
        janela_hist.title("Histórico de Compliance")
        janela_hist.geometry("650x400")

        tk.Label(janela_hist, text="Últimos Registros na Nuvem", font=("Arial", 12, "bold")).pack(pady=10)

        frame_texto = tk.Frame(janela_hist)
        frame_texto.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        
        scrollbar = tk.Scrollbar(frame_texto)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        texto = tk.Text(frame_texto, width=75, height=15, yscrollcommand=scrollbar.set)
        texto.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=texto.yview)

        for reg in registros:
            linha = f"ID: {reg.get('id', 'N/A')} | Área: {reg.get('calculo_area', 0)}ha | Valor Cota: R$ {reg.get('calculo_valor_cota', 0):.2f}\n"
            linha += f"Arquivo: {reg.get('car_local_documento', 'N/A')}\n"
            linha += f"Hash: {reg.get('hash_auditoria', '')[:40]}...\n"
            linha += "-"*70 + "\n"
            texto.insert(tk.END, linha)
        
        texto.config(state=tk.DISABLED) 

    except Exception as e:
        messagebox.showerror("Erro", f"Não foi possível buscar os dados: {e}")

# ==========================================
# INTERFACE PRINCIPAL (TELA)
# ==========================================
janela = tk.Tk()
janela.title("ERP CarbonFree 15.042")
janela.geometry("500x450")

tk.Label(janela, text="Sustentabilidade e Conformidade", font=("Arial", 12, "bold"), fg="green").pack(pady=10)

tk.Label(janela, text="Nome da Empresa/Pessoa:").pack()
entry_empresa = tk.Entry(janela, width=50)
entry_empresa.pack(pady=5)

tk.Label(janela, text="Área Preservada (Hectares):").pack()
entry_area = tk.Entry(janela, width=50)
entry_area.pack(pady=5)

tk.Label(janela, text="Tipo de Atividade:").pack()
opcoes_projeto = [
    "Projeto 1 Hectare (Apenas Preservação)",
    "Projeto 1 Hectare + Meliponicultura (Abelhas de Casca)"
]
combo_projeto = ttk.Combobox(janela, values=opcoes_projeto, width=47, state="readonly")
combo_projeto.pack(pady=5)

# Botão 1: Salvar e Gerar
btn_salvar = tk.Button(janela, text="GERAR CERTIFICADO", command=salvar_no_supabase, bg="#2ecc71", fg="white", font=("Arial", 10, "bold"), height=2)
btn_salvar.pack(pady=15)

# Botão 2: O botão que havia sumido!
btn_consultar = tk.Button(janela, text="CONSULTAR HISTÓRICO", command=consultar_historico, bg="#3498db", fg="white", font=("Arial", 10, "bold"))
btn_consultar.pack(pady=5)

janela.mainloop()