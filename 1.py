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
st.set_page_config(page_title="ERP Nube Maestro", layout="wide", page_icon="☁️")

# Configuración de Google Drive
NOMBRE_HOJA_DRIVE = "DB_ERP_MASTER"
ARCHIVO_CREDENCIALES = "credenciales.json"

# --- 2. CONEXIÓN A GOOGLE SHEETS ---
@st.cache_resource
def conectar_google_sheet():
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        # Intento Nube (Secrets) vs Local (Archivo)
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
        else:
            if not os.path.exists(ARCHIVO_CREDENCIALES):
                st.error("❌ Falta archivo de credenciales."); st.stop()
            creds = Credentials.from_service_account_file(ARCHIVO_CREDENCIALES, scopes=scope)
            
        client = gspread.authorize(creds)
        return client.open(NOMBRE_HOJA_DRIVE)
    except Exception as e:
        st.error(f"❌ Error conexión: {e}"); st.stop()

def load_data(pestana):
    try:
        sh = conectar_google_sheet()
        ws = sh.worksheet(pestana)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
        
        # Limpieza de Tipos
        if pestana == "ventas" and not df.empty:
            for c in ['Total_Venta', 'Ganancia', 'Cantidad']:
                if c in df.columns: 
                    df[c] = pd.to_numeric(df[c].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)
            if 'Ubicacion' not in df.columns: df['Ubicacion'] = 'Local 1'
            if 'Categoria' not in df.columns: df['Categoria'] = 'General'

        if pestana == "menu" and not df.empty:
             for c in ['Stock_Local1', 'Stock_Local2', 'Stock_Feria', 'Precio', 'Costo']:
                if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

        return df
    except gspread.WorksheetNotFound:
        # Si no existe la pestaña, devolvemos DF vacío (el sistema pedirá inicializar)
        return pd.DataFrame()
    except Exception: return pd.DataFrame()

def save_data(df, pestana):
    try:
        sh = conectar_google_sheet()
        ws = sh.worksheet(pestana)
        df = df.astype(str)
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
    
    # Filtrar (como string)
    df_v['Ticket_ID'] = df_v['Ticket_ID'].astype(str)
    ticket_id = str(ticket_id)
    
    t_data = df_v[df_v['Ticket_ID'] == ticket_id]
    if t_data.empty: return False, "No encontrado."

    # Devolver Stock
    for _, row in t_data.iterrows():
        prod = row['Producto']
        cant = float(row['Cantidad'])
        ubic = row['Ubicacion']
        col_map = {"Local 1": "Stock_Local1", "Local 2": "Stock_Local2", "Feria": "Stock_Feria"}
        col_stk = col_map.get(ubic, "Stock_Local1")
        
        idx = df_m.index[df_m['Producto'] == prod]
        if not idx.empty:
            curr = float(df_m.at[idx[0], col_stk])
            df_m.at[idx[0], col_stk] = curr + cant

    df_clean = df_v[df_v['Ticket_ID'] != ticket_id]
    save_data(df_clean, "ventas")
    save_data(df_m, "menu")
    return True, "Ticket eliminado."

# --- 3. VISTAS (LÓGICA v22 RESTAURADA) ---

def render_dashboard_section(df_ventas, key_suffix):
    if df_ventas.empty: st.info("Sin datos."); return

    tot_v = df_ventas['Total_Venta'].sum()
    tot_g = df_ventas['Ganancia'].sum()
    tot_c = tot_v - tot_g
    n_tkt = df_ventas['Ticket_ID'].nunique()
    prom = tot_v / n_tkt if n_tkt > 0 else 0
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Venta", f"${tot_v:,.0f}")
    k2.metric("Ganancia", f"${tot_g:,.0f}")
    k3.metric("Costos", f"${tot_c:,.0f}")
    k4.metric("Ticket Promedio", f"${prom:,.0f}")
    
    st.divider()
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 💰 Dinero")
        fig = go.Figure(data=[go.Pie(labels=['Costo', 'Ganancia'], values=[tot_c, tot_g], hole=.4, marker_colors=['#EF553B', '#00CC96'])])
        st.plotly_chart(fig, use_container_width=True, key=f"pie_{key_suffix}")
    
    with c2:
        st.markdown("##### 🕒 Horas Pico")
        # Hora simple
        df_ventas['H'] = df_ventas['Hora'].astype(str).str.split(':').str[0]
        v_h = df_ventas.groupby('H')['Total_Venta'].sum().reset_index()
        fig2 = px.bar(v_h, x='H', y='Total_Venta')
        st.plotly_chart(fig2, use_container_width=True, key=f"bar_{key_suffix}")

def view_pos(df_menu):
    st.markdown("### 🛒 Punto de Venta")
    tiendas = {"🏠 Local 1": "Stock_Local1", "🏪 Local 2": "Stock_Local2", "🎪 Feria": "Stock_Feria"}
    ubi_ui = st.selectbox("📍 Ubicación:", list(tiendas.keys()))
    col_stk = tiendas[ubi_ui]
    ubi_db = ubi_ui.replace("🏠 ", "").replace("🏪 ", "").replace("🎪 ", "")

    c_cat, c_tkt = st.columns([2, 1])
    with c_cat:
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
                        c2.markdown(f"${row['Precio']} | :{clr}[{int(stk)}]")
                        if stk > 0:
                            if c3.button("➕", key=f"btn_{prod}"):
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
                    if st.button("✅ COBRAR", type="primary", use_container_width=True):
                        with st.spinner("Guardando en Nube..."):
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
                            
                            df_v_old = load_data("ventas")
                            df_v_new = pd.concat([df_v_old, pd.DataFrame(nuevas)], ignore_index=True)
                            
                            if save_data(df_v_new, "ventas"):
                                save_data(df_menu, "menu")
                                st.session_state.pedido = {}
                                st.toast("✅ Venta OK"); time.sleep(1); st.rerun()
                else: st.error("Falta dinero")
            else: st.info("Vacío")

        with t2:
            st.caption("Últimos tickets")
            df_h = load_data("ventas")
            if not df_h.empty:
                df_h['Ticket_ID'] = df_h['Ticket_ID'].astype(str)
                res = df_h.groupby(['Ticket_ID', 'Ubicacion'])['Total_Venta'].sum().reset_index().sort_values('Ticket_ID', ascending=False).head(10)
                st.dataframe(res, hide_index=True)
                sel = st.selectbox("ID Ticket", res['Ticket_ID'])
                if st.button("🚫 CANCELAR"):
                    with st.spinner("Cancelando..."):
                        ok, msg = cancelar_ticket(sel)
                        if ok: st.success(msg); time.sleep(1); st.rerun()

def view_dashboard(df_menu):
    st.markdown("### 📊 Dashboard Maestro")
    df_v = load_data("ventas")
    if df_v.empty: st.warning("Sin datos."); return

    t1, t2, t3, t4 = st.tabs(["🌎 GENERAL", "🏠 LOCAL 1", "🏪 LOCAL 2", "🎪 FERIA"])
    with t1: render_dashboard_section(df_v, "G")
    with t2: render_dashboard_section(df_v[df_v['Ubicacion'] == 'Local 1'], "L1")
    with t3: render_dashboard_section(df_v[df_v['Ubicacion'] == 'Local 2'], "L2")
    with t4: render_dashboard_section(df_v[df_v['Ubicacion'] == 'Feria'], "F")

def view_inventory(df_menu):
    st.markdown("### 📦 Inventario Nube")
    t1, t2 = st.tabs(["📝 Stock", "🚚 Transferir"])
    
    with t1:
        df_menu['Ganancia'] = df_menu['Precio'] - df_menu['Costo']
        df_menu['S_33'] = df_menu['Costo'] * 1.5
        df_menu['S_66'] = df_menu['Costo'] * 3.0
        
        cfg = {
            "Categoria": st.column_config.SelectboxColumn(options=["🌽 Tamales", "🍔 Comida", "🥤 Bebidas", "🍬 Postres", "🍟 Snacks"], required=True),
            "Precio": st.column_config.NumberColumn(format="$%.2f"),
            "Costo": st.column_config.NumberColumn(format="$%.2f"),
            "Ganancia": st.column_config.NumberColumn(format="$%.2f", disabled=True),
            "S_33": st.column_config.NumberColumn("Sug 33%", format="$%.2f", disabled=True),
            "S_66": st.column_config.NumberColumn("Sug 66%", format="$%.2f", disabled=True),
        }
        df_ed = st.data_editor(df_menu, num_rows="dynamic", use_container_width=True, column_config=cfg)
        
        if st.button("💾 Guardar"):
            cols_ok = ['Categoria', 'Producto', 'Precio', 'Costo', 'Stock_Local1', 'Stock_Local2', 'Stock_Feria']
            save_data(df_ed[cols_ok], "menu")
            st.success("Guardado."); time.sleep(1); st.rerun()

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
                st.success("Transferido.")
            else: st.error("Stock bajo.")

def view_recipes(df_menu):
    st.markdown("### 🧪 Recetas (Memoria)")
    df_rec = load_data("recetas")
    
    c1, c2 = st.columns(2)
    with c1:
        prod = st.selectbox("Producto:", df_menu['Producto'].unique(), key="sp")
        # Auto-carga
        if 'last_pr' not in st.session_state or st.session_state.last_pr != prod:
            st.session_state.lista_insumos = []
            if not df_rec.empty:
                filtro = df_rec[df_rec['Producto'] == prod]
                for _, r in filtro.iterrows():
                    st.session_state.lista_insumos.append({"Ingrediente": r['Ingrediente'], "Costo": float(r['Costo_Ref']), "Cantidad": float(r['Cantidad_Base'])})
            st.session_state.last_pr = prod

        with st.form("add_i"):
            ing = st.text_input("Ingrediente")
            cost = st.number_input("Costo Compra", 0.0)
            uso = st.number_input("Cantidad Usada", 0.0, format="%.3f")
            if st.form_submit_button("Agregar"):
                st.session_state.lista_insumos.append({"Ingrediente": ing, "Costo": cost, "Cantidad": uso})
                st.rerun()
    
    with c2:
        if st.session_state.lista_insumos:
            # Mostrar lista editable (borrar)
            for i, it in enumerate(st.session_state.lista_insumos):
                col_a, col_b, col_c = st.columns([3, 2, 1])
                col_a.text(it['Ingrediente'])
                col_b.text(f"${it['Costo']:.2f}")
                if col_c.button("❌", key=f"del_{i}"):
                    st.session_state.lista_insumos.pop(i); st.rerun()
            
            st.divider()
            suma = sum(x['Costo'] for x in st.session_state.lista_insumos)
            st.success(f"Costo: ${suma:.2f}")
            
            if st.button("💾 Guardar Receta y Actualizar Precio"):
                # Menú
                idx = df_menu.index[df_menu['Producto'] == prod]
                df_menu.at[idx[0], 'Costo'] = suma
                save_data(df_menu, "menu")
                # Recetas
                df_rec = load_data("recetas") # Recargar fresca
                df_rec = df_rec[df_rec['Producto'] != prod]
                nuevas = [{"Producto": prod, "Ingrediente": i['Ingrediente'], "Cantidad_Base": i['Cantidad'], "Costo_Ref": i['Costo']} for i in st.session_state.lista_insumos]
                df_fin = pd.concat([df_rec, pd.DataFrame(nuevas)])
                save_data(df_fin, "recetas")
                st.toast("Guardado!")

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
        st.warning("Base de datos nueva o vacía.")
        if st.button("Inicializar DB en Drive"):
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
