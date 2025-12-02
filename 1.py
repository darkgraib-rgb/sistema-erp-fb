import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import time
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import os

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="ERP Maestro Nube", layout="wide", page_icon="☁️")

# Configuración Google
NOMBRE_HOJA_DRIVE = "DB_ERP_MASTER"
ARCHIVO_CREDENCIALES = "credenciales.json"

# --- 2. CONEXIÓN Y DATOS ---
@st.cache_resource
def conectar_google_sheet():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        else:
            if not os.path.exists(ARCHIVO_CREDENCIALES):
                st.error("❌ Falta archivo credenciales.json"); st.stop()
            creds = Credentials.from_service_account_file(ARCHIVO_CREDENCIALES, scopes=scope)
        return gspread.authorize(creds).open(NOMBRE_HOJA_DRIVE)
    except Exception as e:
        st.error(f"Error conexión: {e}"); st.stop()

def load_data(pestana):
    try:
        sh = conectar_google_sheet()
        ws = sh.worksheet(pestana)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # --- LIMPIEZA DE DATOS (CRÍTICO PARA DASHBOARD) ---
        if pestana == "ventas" and not df.empty:
            # Convertir todo lo que parezca dinero a número flotante
            for col in ['Total_Venta', 'Ganancia', 'Cantidad']:
                if col in df.columns:
                    # Quitamos '$' y ',' y convertimos a número
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)
            
            # Rellenar vacíos
            if 'Ubicacion' not in df.columns: df['Ubicacion'] = 'Local 1'
            if 'Categoria' not in df.columns: df['Categoria'] = 'General'

        if pestana == "menu" and not df.empty:
             for c in ['Stock_Local1', 'Stock_Local2', 'Stock_Feria', 'Precio', 'Costo']:
                if c in df.columns: 
                    df[c] = pd.to_numeric(df[c].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)

        if pestana == "recetas" and not df.empty:
             for c in ['Costo_Ref', 'Cantidad_Base']:
                if c in df.columns:
                    df[c] = pd.to_numeric(df[c].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)

        return df
    except: return pd.DataFrame()

def save_data(df, pestana):
    try:
        sh = conectar_google_sheet()
        ws = sh.worksheet(pestana)
        df = df.astype(str) # Convertir a texto para evitar errores de JSON
        lista = [df.columns.values.tolist()] + df.values.tolist()
        ws.clear()
        ws.update(lista)
        return True
    except Exception as e:
        st.error(f"Error guardando: {e}")
        return False

def cancelar_ticket(ticket_id):
    df_v = load_data("ventas")
    df_m = load_data("menu")
    
    df_v['Ticket_ID'] = df_v['Ticket_ID'].astype(str)
    t_data = df_v[df_v['Ticket_ID'] == str(ticket_id)]
    
    if t_data.empty: return False, "No existe."

    for _, row in t_data.iterrows():
        prod = row['Producto']
        cant = float(row['Cantidad'])
        ubic = row['Ubicacion']
        col_map = {"Local 1": "Stock_Local1", "Local 2": "Stock_Local2", "Feria": "Stock_Feria"}
        col_stk = col_map.get(ubic, "Stock_Local1")
        
        idx = df_m.index[df_m['Producto'] == prod]
        if not idx.empty:
            act = float(df_m.at[idx[0], col_stk])
            df_m.at[idx[0], col_stk] = act + cant

    df_clean = df_v[df_v['Ticket_ID'] != str(ticket_id)]
    save_data(df_clean, "ventas")
    save_data(df_m, "menu")
    return True, "Ticket eliminado."

# --- 3. DASHBOARD (Con Llaves Únicas para evitar errores) ---

def render_dashboard_section(df_ventas, key_id):
    """
    key_id: Identificador único (ej. 'Gen', 'L1') para que las gráficas no choquen.
    """
    if df_ventas.empty:
        st.info("Esperando ventas...")
        return

    # KPIs
    tot_v = df_ventas['Total_Venta'].sum()
    tot_g = df_ventas['Ganancia'].sum()
    tot_c = tot_v - tot_g
    n_tk = df_ventas['Ticket_ID'].nunique()
    prom = tot_v / n_tk if n_tk > 0 else 0
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ventas", f"${tot_v:,.0f}", border=True)
    k2.metric("Ganancia", f"${tot_g:,.0f}", border=True)
    k3.metric("Costo Insumo", f"${tot_c:,.0f}", border=True)
    k4.metric("Ticket Promedio", f"${prom:,.0f}", help="Gasto por cliente", border=True)
    
    st.divider()
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 💰 Inversión vs Ganancia")
        # Gráfica Pastel Dinero
        fig = go.Figure(data=[go.Pie(labels=['Costo (Recuperación)', 'Utilidad Neta'], 
                                    values=[tot_c, tot_g], 
                                    hole=.4, 
                                    marker_colors=['#EF553B', '#00CC96'])])
        st.plotly_chart(fig, use_container_width=True, key=f"pie_money_{key_id}")
    
    with c2:
        st.markdown("##### 🕒 Horas Pico")
        # Procesar hora
        df_ventas['H'] = df_ventas['Hora'].astype(str).str.split(':').str[0]
        v_h = df_ventas.groupby('H')['Total_Venta'].sum().reset_index()
        
        fig2 = px.bar(v_h, x='H', y='Total_Venta', title="Venta por Hora", color='Total_Venta')
        st.plotly_chart(fig2, use_container_width=True, key=f"bar_hour_{key_id}")

    # Tabla Matriz Rentabilidad
    with st.expander(f"📊 Ver Detalle Productos ({key_id})"):
        matriz = df_ventas.groupby('Producto').agg({'Cantidad':'sum', 'Total_Venta':'sum', 'Ganancia':'sum'}).reset_index()
        matriz['Margen %'] = (matriz['Ganancia'] / matriz['Total_Venta'] * 100).fillna(0)
        st.dataframe(matriz.sort_values('Ganancia', ascending=False), use_container_width=True)

# --- 4. VISTAS ---

def view_pos(df_menu):
    st.markdown("### 🛒 Punto de Venta")
    tiendas = {"🏠 Local 1": "Stock_Local1", "🏪 Local 2": "Stock_Local2", "🎪 Feria": "Stock_Feria"}
    ubi_ui = st.selectbox("📍 Ubicación:", list(tiendas.keys()))
    col_stk = tiendas[ubi_ui]
    ubi_db = ubi_ui.replace("🏠 ", "").replace("🏪 ", "").replace("🎪 ", "")

    c_cat, c_tkt = st.columns([2, 1])
    with c_cat:
        # EMOJIS AGREGADOS
        cats = ["🌽 Tamales", "🍔 Comida", "🥤 Bebidas", "🍬 Postres", "🍟 Snacks"]
        tabs = st.tabs(cats)
        for i, cat in enumerate(cats):
            with tabs[i]:
                items = df_menu[df_menu['Categoria'] == cat]
                for _, row in items.iterrows():
                    prod = row['Producto']
                    stk = float(row.get(col_stk, 0))
                    with st.container():
                        c1, c2, c3 = st.columns([3, 2, 1], vertical_alignment="center")
                        c1.markdown(f"**{prod}**")
                        clr = "green" if stk > 5 else "red"
                        c2.caption(f"${row['Precio']} | :{clr}[{int(stk)}]")
                        if stk > 0:
                            if c3.button("➕", key=f"btn_{prod}_{ubi_db}"):
                                st.session_state.pedido[prod] = st.session_state.pedido.get(prod, 0) + 1
                                st.rerun()
                        else: c3.error("0")

    with c_tkt:
        t1, t2 = st.tabs(["🧾 Cuenta", "clock/Historial"])
        with t1:
            if st.session_state.pedido:
                total = 0
                for p, c in list(st.session_state.pedido.items()):
                    row = df_menu[df_menu['Producto'] == p].iloc[0]
                    sub = float(row['Precio']) * c
                    total += sub
                    cc1, cc2, cc3 = st.columns([4, 2, 1])
                    cc1.text(f"{p} x{c}")
                    cc2.text(f"${sub:,.0f}")
                    if cc3.button("🗑️", key=f"del_{p}"):
                        del st.session_state.pedido[p]; st.rerun()
                st.divider()
                st.metric("TOTAL", f"${total:,.0f}")
                pago = st.number_input("Pago", value=float(total))
                cambio = pago - total
                
                if cambio >= 0:
                    st.success(f"CAMBIO: ${cambio:,.2f}")
                    if st.button("✅ COBRAR (Nube)", type="primary", use_container_width=True):
                        with st.spinner("Guardando..."):
                            tid = datetime.now().strftime("%Y%m%d-%H%M%S")
                            nuevas = []
                            hoy = datetime.now()
                            for p, c in st.session_state.pedido.items():
                                idx = df_menu.index[df_menu['Producto'] == p][0]
                                row = df_menu.iloc[idx]
                                gan = (float(row['Precio']) - float(row['Costo'])) * c
                                nuevas.append({
                                    "Ticket_ID": tid, "Fecha": hoy.strftime("%Y-%m-%d"), "Hora": hoy.strftime("%H:%M:%S"),
                                    "Ubicacion": ubi_db, "Categoria": row['Categoria'], "Producto": p, "Cantidad": c,
                                    "Total_Venta": float(row['Precio'])*c, "Ganancia": gan
                                })
                                df_menu.at[idx, col_stk] = float(row[col_stk]) - c
                            
                            df_old = load_data("ventas")
                            df_new = pd.concat([df_old, pd.DataFrame(nuevas)], ignore_index=True)
                            
                            if save_data(df_new, "ventas"):
                                save_data(df_menu, "menu")
                                st.session_state.pedido = {}
                                st.toast("Venta OK"); time.sleep(1); st.rerun()
                else: st.error("Falta")
            else: st.info("Vacío")

        with t2:
            st.caption("Últimos tickets")
            df_h = load_data("ventas")
            if not df_h.empty:
                df_h['Ticket_ID'] = df_h['Ticket_ID'].astype(str)
                # MOSTRAR UBICACION EN HISTORIAL
                res = df_h.groupby(['Ticket_ID', 'Ubicacion'])['Total_Venta'].sum().reset_index().sort_values('Ticket_ID', ascending=False).head(10)
                st.dataframe(res, hide_index=True)
                sel = st.selectbox("ID Ticket", res['Ticket_ID'])
                if st.button("🚫 CANCELAR TICKET"):
                    ok, msg = cancelar_ticket(sel)
                    if ok: st.success(msg); time.sleep(1); st.rerun()

def view_dashboard(df_menu):
    st.markdown("### 📊 Dashboard")
    df_v = load_data("ventas")
    if df_v.empty: st.warning("Sin datos."); return

    t1, t2, t3, t4 = st.tabs(["🌎 GENERAL", "🏠 LOCAL 1", "🏪 LOCAL 2", "🎪 FERIA"])
    
    # Pasamos llaves únicas para que los gráficos no choquen
    with t1: render_dashboard_section(df_v, "GEN")
    with t2: render_dashboard_section(df_v[df_v['Ubicacion'] == 'Local 1'], "L1")
    with t3: render_dashboard_section(df_v[df_v['Ubicacion'] == 'Local 2'], "L2")
    with t4: render_dashboard_section(df_v[df_v['Ubicacion'] == 'Feria'], "FER")

def view_inventory(df_menu):
    st.markdown("### 📦 Inventario")
    t1, t2 = st.tabs(["📝 Stock", "🚚 Transferir"])
    
    with t1:
        # Precios sugeridos
        df_menu['Ganancia'] = df_menu['Precio'] - df_menu['Costo']
        df_menu['Sug_33'] = df_menu['Costo'] * 1.5
        df_menu['Sug_66'] = df_menu['Costo'] * 3.0
        
        cfg = {
            "Categoria": st.column_config.SelectboxColumn(options=["🌽 Tamales", "🍔 Comida", "🥤 Bebidas", "🍬 Postres", "🍟 Snacks"], required=True),
            "Precio": st.column_config.NumberColumn(format="$%.2f"),
            "Costo": st.column_config.NumberColumn(format="$%.2f"),
            "Ganancia": st.column_config.NumberColumn(format="$%.2f", disabled=True),
            "Sug_33": st.column_config.NumberColumn("Sug 33%", format="$%.2f", disabled=True),
            "Sug_66": st.column_config.NumberColumn("Sug 66%", format="$%.2f", disabled=True),
        }
        df_ed = st.data_editor(df_menu, num_rows="dynamic", use_container_width=True, column_config=cfg)
        if st.button("💾 Sincronizar"):
            cols = ['Categoria', 'Producto', 'Precio', 'Costo', 'Stock_Local1', 'Stock_Local2', 'Stock_Feria']
            save_data(df_ed[cols], "menu")
            st.success("Hecho."); time.sleep(1); st.rerun()

    with t2:
        c1, c2, c3, c4 = st.columns(4)
        orig = c1.selectbox("De:", ["Local 1", "Local 2", "Feria"])
        dest = c2.selectbox("A:", ["Feria", "Local 2", "Local 1"])
        prod = c3.selectbox("Prod:", df_menu['Producto'].unique())
        cant = c4.number_input("Cant:", 1)
        if st.button("Transferir"):
            c_o = f"Stock_{orig.replace(' ','')}"
            c_d = f"Stock_{dest.replace(' ','')}"
            idx = df_menu.index[df_menu['Producto'] == prod][0]
            if df_menu.at[idx, c_o] >= cant:
                df_menu.at[idx, c_o] -= cant
                df_menu.at[idx, c_d] += cant
                save_data(df_menu, "menu")
                st.success("Listo.")
            else: st.error("Stock insuficiente.")

def view_recipes(df_menu):
    st.markdown("### 🧪 Recetas (Restaurada)")
    df_rec = load_data("recetas")
    
    t_calc, t_edit = st.tabs(["🧮 Calculadora de Costos", "📝 Base de Datos"])
    
    with t_calc:
        st.info("Calcula costos por lotes (ej. una olla) o por unidad.")
        c1, c2 = st.columns(2)
        with c1:
            prod = st.selectbox("Producto:", df_menu['Producto'].unique(), key="s_p")
            
            # --- MEMORIA DE RECETA ---
            if 'last_pr' not in st.session_state or st.session_state.last_pr != prod:
                st.session_state.lista_insumos = []
                if not df_rec.empty:
                    filtro = df_rec[df_rec['Producto'] == prod]
                    for _, r in filtro.iterrows():
                        st.session_state.lista_insumos.append({"Ingrediente": r['Ingrediente'], "Costo": float(r['Costo_Ref']), "Cantidad": float(r['Cantidad_Base'])})
                st.session_state.last_pr = prod

            # --- SELECTOR MODO RESTAURADO ---
            modo = st.radio("Modo:", ["📦 Lote (Olla/Paquete)", "🍔 Unidad (Individual)"], horizontal=True)

            with st.form("a_ing"):
                ing = st.text_input("Ingrediente (ej. Carne)")
                costo_base = st.number_input("Costo de Compra ($)", 0.0)
                
                if "Lote" in modo:
                    uso = st.number_input("Cantidad Usada en la Olla (1 = Todo)", 0.0, format="%.3f")
                    res = costo_base * uso
                else:
                    tam_paq = st.number_input("Tamaño Paquete/Kilo (g/ml)", 1.0)
                    uso = st.number_input("Uso en Receta (g/ml)", 0.0, format="%.3f")
                    res = (costo_base / tam_paq) * uso

                if st.form_submit_button("➕ Agregar"):
                    st.session_state.lista_insumos.append({"Ingrediente": ing, "Costo": res, "Cantidad": uso})
                    st.rerun()
        
        with c2:
            st.markdown(f"#### 📝 {prod}")
            if st.session_state.lista_insumos:
                df_i = pd.DataFrame(st.session_state.lista_insumos)
                # Mostrar botón eliminar
                for i, row in df_i.iterrows():
                    col_del1, col_del2 = st.columns([4, 1])
                    col_del1.text(f"{row['Ingrediente']}: ${row['Costo']:.2f}")
                    if col_del2.button("❌", key=f"d_{i}"):
                        st.session_state.lista_insumos.pop(i); st.rerun()
                
                st.divider()
                suma = df_i['Costo'].sum()
                st.markdown(f"**Costo Insumos Total:** ${suma:.2f}")
                
                # --- RENDIMIENTO RESTAURADO ---
                rendimiento = 1
                if "Lote" in modo:
                    rendimiento = st.number_input("¿Cuántas piezas salieron de esta olla/lote?", min_value=1, value=50)
                
                costo_final = suma / rendimiento
                st.success(f"💰 Costo Unitario Final: ${costo_final:.2f}")
                
                if st.button("💾 Guardar y Actualizar Precio"):
                    # Update Menú
                    idx = df_menu.index[df_menu['Producto'] == prod]
                    df_menu.at[idx[0], 'Costo'] = costo_final
                    save_data(df_menu, "menu")
                    
                    # Update Recetas
                    df_rec_full = load_data("recetas")
                    df_rec_clean = df_rec_full[df_rec_full['Producto'] != prod]
                    nuevas = [{"Producto": prod, "Ingrediente": i['Ingrediente'], "Cantidad_Base": i['Cantidad'], "Costo_Ref": i['Costo']} for i in st.session_state.lista_insumos]
                    df_final = pd.concat([df_rec_clean, pd.DataFrame(nuevas)])
                    save_data(df_final, "recetas")
                    st.toast("Guardado en Drive")

    with t_edit:
        st.info("Base de datos de ingredientes.")
        if not df_rec.empty:
            df_r_ed = st.data_editor(df_rec, num_rows="dynamic", use_container_width=True)
            if st.button("Sincronizar Recetas"):
                save_data(df_r_ed, "recetas")
                st.success("Sincronizado.")

# --- MAIN ---
def main():
    if 'pedido' not in st.session_state: st.session_state.pedido = {}
    if 'lista_insumos' not in st.session_state: st.session_state.lista_insumos = []

    c_nav, _ = st.columns([3, 1])
    with c_nav:
        op = st.radio("Nav", ["🛒 Vendedor", "📊 Dashboard", "📦 Inventario", "🧪 Recetas"], horizontal=True, label_visibility="collapsed")
    st.divider()

    df_menu = load_data("menu")
    if df_menu.empty:
        st.warning("Cargando DB...")
        if st.button("Inicializar"):
            data = [{"Categoria": "🌽 Tamales", "Producto": "Tamal Verde", "Precio": 20, "Costo": 8.5, "Stock_Local1": 50, "Stock_Local2": 30, "Stock_Feria": 0}]
            save_data(pd.DataFrame(data), "menu")
            st.rerun()
    else:
        if op == "🛒 Vendedor": view_pos(df_menu)
        elif op == "📊 Dashboard": view_dashboard(df_menu)
        elif op == "📦 Inventario": view_inventory(df_menu)
        elif op == "🧪 Recetas": view_recipes(df_menu)

if __name__ == "__main__":
    main()
