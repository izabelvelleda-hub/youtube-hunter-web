import streamlit as st
from googleapiclient.discovery import build
import pandas as pd
import os
import requests
import random
import time
from datetime import datetime, timedelta

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="YouTube Outlier Hunter", layout="wide", page_icon="💎")
ARQUIVO_SALVOS = "canais_salvos.csv"

# --- FUNÇÕES DE BANCO DE DADOS (CSV) ---
def carregar_salvos():
    colunas = ['Nome', 'Inscritos', 'Vídeos', 'Média Views', 'País', 'Criação', 'Dias Vida', 'Link', 'Data Descoberta']
    if not os.path.exists(ARQUIVO_SALVOS):
        return pd.DataFrame(columns=colunas)
    return pd.read_csv(ARQUIVO_SALVOS)

def salvar_canal(dados_canal):
    df = carregar_salvos()
    # Verifica duplicidade pelo Link
    if dados_canal['Link'] not in df['Link'].values:
        # Filtra apenas as colunas que existem no CSV
        linha_limpa = {k: v for k, v in dados_canal.items() if k in df.columns}
        novo_df = pd.DataFrame([linha_limpa])
        df = pd.concat([df, novo_df], ignore_index=True)
        df.to_csv(ARQUIVO_SALVOS, index=False)
        return True
    return False

# --- FUNÇÃO DE INTELIGÊNCIA (AUTOCOMPLETE) ---
def get_google_suggestions(termo_raiz):
    url = "http://suggestqueries.google.com/complete/search"
    sugestoes = set()
    alfabeto = "abcdefghijklmnopqrstuvwxyz"
    
    # 1. Busca direta
    try:
        r = requests.get(url, params={'client': 'firefox', 'ds': 'yt', 'q': termo_raiz})
        if r.status_code == 200: [sugestoes.add(item) for item in r.json()[1]]
    except: pass

    # 2. Busca exploratória (Termo + Letra aleatória)
    for letra in random.sample(alfabeto, 3):
        try:
            r = requests.get(url, params={'client': 'firefox', 'ds': 'yt', 'q': f"{termo_raiz} {letra}"})
            if r.status_code == 200: [sugestoes.add(item) for item in r.json()[1]]
            time.sleep(0.1)
        except: pass
    return list(sugestoes)

# --- MOTOR DE BUSCA (CORE) - VERSÃO VIRAL FACELESS ---
def executar_busca(api_key, query, max_results, duration, min_subs, max_subs, min_videos, max_videos, region_code, usar_proxima_pagina=False):
    try:
        from datetime import datetime, timedelta
        youtube = build('youtube', 'v3', developerKey=api_key)
        token = st.session_state['next_page_token'] if usar_proxima_pagina else None
        
        # 1. BUSCA DE VÍDEOS (Calcula 7 dias atrás para pegar o que é NOVO e VIRAL)
        st.session_state['quota_usada'] += 100
        data_corte = (datetime.utcnow() - timedelta(days=7)).isoformat() + "Z"
        
        search_params = {
            'q': ' ', # Busca ampla sem travar em palavra-chave
            'part': 'snippet', 
            'type': 'video',
            'maxResults': max_results, 
            'order': 'viewCount', # Ordena pelos mais vistos (o "Viral")
            'pageToken': token,
            'regionCode': region_code,
            'publishedAfter': data_corte, # Apenas vídeos de "poucos dias de vida"
            'videoCategoryId': '24' # Categoria Entretenimento (onde estão os virais faceless)
        }
        
        # Se você selecionar uma duração na tela do app, ela ainda funciona
        if duration: search_params['videoDuration'] = duration

        request = youtube.search().list(**search_params)
        response = request.execute()
        
        st.session_state['next_page_token'] = response.get('nextPageToken')
        
        # 2. VAMOS BUSCAR AS VIEWS REAIS DE CADA VÍDEO (Essencial para ver o viral)
        video_ids = [item['id']['videoId'] for item in response['items']]
        if not video_ids: return []

        st.session_state['quota_usada'] += 1
        request_videos = youtube.videos().list(
            id=','.join(video_ids),
            part='snippet,statistics'
        )
        videos_response = request_videos.execute()
        
        novos = []
        for video in videos_response['items']:
            stats = video['statistics']
            snippet = video['snippet']
            
            views = int(stats.get('viewCount', 0))
            data_pub = datetime.strptime(snippet['publishedAt'][:10], "%Y-%m-%d")
            dias_vida = (datetime.utcnow() - data_pub).days
            if dias_vida == 0: dias_vida = 1 # Evita divisão por zero
            
            # Métrica de Ouro: Views por Dia (VPD)
            vph = int(views / dias_vida)

            novos.append({
                'Nome': snippet['title'],
                'Inscritos': views, # Usando este campo para mostrar as VIEWS no lugar
                'Vídeos': vph,      # Usando este para mostrar VIEWS/DIA
                'Total Views': views,
                'Média Views': vph,
                'País': region_code,
                'Criação': data_pub.strftime("%d/%m/%Y"),
                'Dias Vida': dias_vida,
                'Link': f"https://www.youtube.com/watch?v={video['id']}",
                'Data Descoberta': datetime.now().strftime("%Y-%m-%d"),
                'Thumb': snippet['thumbnails']['high']['url'],
                'Desc': snippet.get('channelTitle', '') # Mostra o nome do canal aqui
            })
            
        return novos
    except Exception as e:
        st.error(f"Erro na API: {e}")
        return []

# --- INICIALIZAÇÃO DE ESTADO ---
vars_iniciais = ['quota_usada', 'resultados_busca', 'next_page_token', 'termo_atual', 'sugestoes_cache']
for v in vars_iniciais:
    if v not in st.session_state:
        st.session_state[v] = [] if v == 'resultados_busca' else (None if v == 'next_page_token' else 0)

# ================= INTERFACE GRÁFICA =================

st.title("💎 YouTube Outlier Hunter Pro")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("⚙️ Configuração")
    
    # Gestão de API Key (Segredos ou Input Manual)
    if "GOOGLE_API_KEY" in st.secrets:
        api_key = st.secrets["GOOGLE_API_KEY"]
        st.success("✅ API Key carregada do sistema")
    else:
        api_key = st.text_input("API Key", type="password", help="Cole sua chave AIza...")
    
    st.divider()
    st.subheader("Filtros Globais")
    region = st.selectbox("Região do Canal", ["Qualquer", "BR", "US", "PT"], index=0)
    region_param = None if region == "Qualquer" else region
    
    st.divider()
    st.metric("Custo Sessão (Estimado)", f"{st.session_state['quota_usada']}")
    st.caption("Limite grátis diário: 10.000 unidades")

# --- ABAS ---
tab_busca, tab_discovery, tab_salvos = st.tabs(["🔍 Busca Avançada", "🧠 Descobrir Nichos", "💾 Biblioteca"])

# === ABA 1: BUSCA MANUAL ===
with tab_busca:
    # Linha 1: Texto e Duração
    c1, c2 = st.columns([3, 1])
    query = c1.text_input("Palavra-chave / Nicho", "Inteligência Artificial")
    duracao = c2.selectbox("Filtro de Duração", ["Qualquer", "Médio (4-20m)", "Longo (>20m)"], index=1, help="Evita Shorts")
    
    st.markdown("---")
    
    # Linha 2: Filtros de Range
    st.markdown("**📏 Filtros de Tamanho**")
    col_sub1, col_sub2, col_vid1, col_vid2 = st.columns(4)
    
    min_subs = col_sub1.number_input("Mín. Inscritos", value=1000, step=100)
    max_subs = col_sub2.number_input("Máx. Inscritos", value=10000000, step=1000)
    
    min_videos = col_vid1.number_input("Mín. Vídeos", value=1, step=1)
    max_videos = col_vid2.number_input("Máx. Vídeos", value=50, step=1)
    
    st.markdown("")
    max_results = st.slider("Amostra por busca", 10, 50, 50)
    
    mapa_dur = {"Qualquer": None, "Médio (4-20m)": "medium", "Longo (>20m)": "long"}

    # Botões de Ação
    col_btn1, col_btn2 = st.columns([1, 3])
    
    # Botão 1: Nova Busca
    if col_btn1.button("🔍 Buscar", type="primary"):
        if api_key:
            st.session_state['resultados_busca'] = []
            st.session_state['next_page_token'] = None
            res = executar_busca(
                api_key, query, max_results, mapa_dur[duracao], 
                min_subs, max_subs, min_videos, max_videos, region_param, False
            )
            st.session_state['resultados_busca'] = res
            if not res: st.warning("Nenhum canal encontrado.")
        else: st.error("Falta a API Key!")

    # Botão 2: Carregar Mais
    if st.session_state['next_page_token'] and st.session_state['termo_atual']:
        if col_btn2.button(f"🔄 Carregar Mais para '{st.session_state['termo_atual']}'"):
             res = executar_busca(
                api_key, st.session_state['termo_atual'], max_results, mapa_dur[duracao], 
                min_subs, max_subs, min_videos, max_videos, region_param, True
             )
             
             # --- FILTRO ANTI-DUPLICIDADE (NOVO) ---
             # Pega os links que já estão na tela
             links_existentes = {c['Link'] for c in st.session_state['resultados_busca']}
             # Filtra os novos que não estão na lista
             novos_filtrados = [c for c in res if c['Link'] not in links_existentes]
             
             st.session_state['resultados_busca'].extend(novos_filtrados)
             
             if not res: 
                 st.toast("Fim dos resultados no YouTube.")
             elif not novos_filtrados: 
                 st.toast("Canais encontrados já estavam na lista.")
             else:
                 st.toast(f"{len(novos_filtrados)} novos canais adicionados!")

    # Exibição dos Cards
    if st.session_state['resultados_busca']:
        st.divider()
        st.write(f"Canais na lista: **{len(st.session_state['resultados_busca'])}**")
        
        # --- LOOP COM CORREÇÃO DE CHAVE DUPLICADA ---
        # Usamos enumerate(..., start=0) para ter o índice 'i'
        for i, canal in enumerate(st.session_state['resultados_busca']):
            with st.container(border=True):
                col_img, col_info, col_metrics, col_btn = st.columns([1, 4, 2, 1])
                
                col_img.image(canal['Thumb'], width=70)
                
                with col_info:
                    st.markdown(f"### [{canal['Nome']}]({canal['Link']})")
                    if canal['Dias Vida'] < 90:
                        st.caption(f"👶 **Novo!** Criado em {canal['Criação']} ({canal['Dias Vida']} dias)")
                    else:
                        st.caption(f"📅 Criado em {canal['Criação']}")
                    st.markdown(f"📍 País: **{canal['País']}**")
                
                with col_metrics:
                    is_viral = canal['Média Views'] > canal['Inscritos']
                    cor = "green" if is_viral else "off"
                    emoji = "🔥" if is_viral else ""
                    
                    st.markdown(f"**Subs:** {canal['Inscritos']}")
                    st.markdown(f"**Vídeos:** {canal['Vídeos']}")
                    st.markdown(f"**Média:** :{cor}[{canal['Média Views']}] {emoji}")
                
                # AQUI ESTAVA O ERRO, AGORA CORRIGIDO COM O ÍNDICE 'i'
                if col_btn.button("Salvar 💾", key=f"save_{i}_{canal['Link']}"):
                    if salvar_canal(canal): st.toast("Canal Salvo!")
                    else: st.toast("Já estava salvo.")

# === ABA 2: DESCOBERTA ===
with tab_discovery:
    st.markdown("### ⛏️ Mineração de Nichos")
    termo = st.text_input("Tema Raiz (ex: 'ASMR', 'Finanças', 'Roblox')")
    
    if st.button("Minerar Ideias"):
        st.session_state['sugestoes_cache'] = get_google_suggestions(termo)
    
    if st.session_state.get('sugestoes_cache'):
        st.write("Clique para buscar outliers nestes sub-nichos:")
        cols = st.columns(3)
        for i, sug in enumerate(st.session_state['sugestoes_cache']):
            if cols[i%3].button(f"🔎 {sug}", key=f"sug_{i}"):
                if api_key:
                    st.session_state['resultados_busca'] = []
                    st.session_state['next_page_token'] = None
                    res = executar_busca(api_key, sug, 50, "medium", min_subs, max_subs, min_videos, max_videos, region_param, False)
                    st.session_state['resultados_busca'] = res
                    st.success(f"Resultados carregados na aba Busca!")

    st.divider()
    if st.button("🎲 Estou sem ideias (Modo Aleatório)"):
        rand_terms = ["Tutorial iniciante", "Review honesto", "Vlog de viagem", "Rotina produtiva", "Setup gaming", "Receita facil"]
        sorteado = random.choice(rand_terms)
        if api_key:
            st.session_state['resultados_busca'] = []
            st.session_state['next_page_token'] = None
            res = executar_busca(api_key, sorteado, 50, "medium", min_subs, max_subs, min_videos, max_videos, region_param, False)
            st.session_state['resultados_busca'] = res
            st.success(f"Busca aleatória por '{sorteado}' feita! Veja na aba Busca.")

# === ABA 3: BIBLIOTECA ===
with tab_salvos:
    df = carregar_salvos()
    if not df.empty:
        st.data_editor(
            df,
            column_config={
                "Link": st.column_config.LinkColumn("Link Youtube"),
                "Média Views": st.column_config.NumberColumn("Média Views", format="%d")
            },
            hide_index=True,
            use_container_width=True
        )
        
        c1, c2 = st.columns(2)
        csv = df.to_csv(index=False).encode('utf-8')
        c1.download_button("📥 Baixar Planilha (CSV)", csv, "outliers_encontrados.csv", "text/csv")
        
        if c2.button("🗑️ Limpar Biblioteca Inteira"):
            os.remove(ARQUIVO_SALVOS)
            st.rerun()
    else:
        st.info("Nenhum canal salvo ainda. Vá buscar!")
