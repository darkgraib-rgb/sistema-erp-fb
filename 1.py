import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go

# --- 1. CONFIGURACIÓN ---
st.set_page_config(page_title="ERP Nube F&B", layout="wide", page_icon="☁️")

# Nombre exacto de tu Google Sheet y del archivo de credenciales
NOMBRE_HOJA_DRIVE = "DB_ERP_MASTER"
ARCHIVO_CREDENCIALES = "credenciales"

# --- 2. CONEXIÓN A GOOGLE SHEETS (EL MOTOR NUEVO) ---

# --- BUSCA ESTA PARTE EN TU CÓDIGO Y REEMPLÁZALA POR ESTO ---

@st.cache_resource
def conectar_google_sheet():
    """Conecta con Google Drive (Compatible con Local y Nube)."""
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    try:
        # INTENTO 1: Buscar en Secretos de Nube (Streamlit Cloud)
        if "gcp_service_account" in st.secrets:
            creds_dict = dict(st.secrets["gcp_service_account"])
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        
        # INTENTO 2: Buscar archivo local (Tu laptop)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name(ARCHIVO_CREDENCIALES, scope)
            
        client = gspread.authorize(creds)
        sheet = client.open(NOMBRE_HOJA_DRIVE)
        return sheet
        
    except FileNotFoundError:
        st.error(f"❌ Error Local: No encuentro '{ARCHIVO_CREDENCIALES}'.")
        st.stop()
    except Exception as e:
        st.error(f"❌ Error de Conexión: {e}")
        st.stop()

def load_data(pestana):
    """Descarga los datos de una pestaña de Google Sheet a un DataFrame."""
    try:
        sh = conectar_google_sheet()
        worksheet = sh.worksheet(pestana)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        # --- LIMPIEZA DE DATOS ---
        if pestana == "ventas" and not df.empty:
            for col in ['Total_Venta', 'Ganancia', 'Cantidad']:
                if col in df.columns: 
                    # Forzar conversión a números, quitando signos de $ o comas si los hubiera
                    df[col] = pd.to_numeric(df[col].astype(str).str.replace(r'[$,]', '', regex=True), errors='coerce').fillna(0)
            if 'Ubicacion' not in df.columns: df['Ubicacion'] = 'Local 1'
            if 'Categoria' not in df.columns: df['Categoria'] = 'General'

        if pestana == "menu" and not df.empty:
             for col in ['Stock_Local1', 'Stock_Local2', 'Stock_Feria', 'Precio', 'Costo']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        return df
    except gspread.WorksheetNotFound:
        st.error(f"⚠️ No encuentro la pestaña '{pestana}' en tu Excel. ¡Créala!")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Error leyendo nube: {e}")
        return pd.DataFrame()

def save_data(df, pestana):
    """Sube los datos a Google Sheet (Borra y reescribe la pestaña)."""
    try:
        sh = conectar_google_sheet()
        worksheet = sh.worksheet(pestana)
        
        # Convertir tipos de datos no JSON-serializables (como fechas) a string
        df = df.astype(str) 
        
        # Preparamos los datos: Encabezados + Filas
        datos_lista = [df.columns.values.tolist()] + df.values.tolist()
        
        # Borramos contenido viejo y subimos el nuevo
        worksheet.clear()
        worksheet.update(datos_lista)
        return True
    except Exception as e:
        st.error(f"❌ Error guardando en nube: {e}")
        return False

def cancelar_ticket(ticket_id):
    df_v = load_data("ventas")
    df_m = load_data("menu")
    
    # Filtrar ticket (asegurando que sea string para comparar)
    df_v['Ticket_ID'] = df_v['Ticket_ID'].astype(str)
    ticket_data = df_v[df_v['Ticket_ID'] == str(ticket_id)]
    
    if ticket_data.empty: return False, "No encontrado."

    for _, row in ticket_data.iterrows():
        prod = row['Producto']
        cant = float(row['Cantidad'])
        ubic = row['Ubicacion']
        
        col_map = {"Local 1": "Stock_Local1", "Local 2": "Stock_Local2", "Feria": "Stock_Feria"}
        col_stock = col_map.get(ubic, "Stock_Local1")
        
        idx = df_m.index[df_m['Producto'] == prod]
        if not idx.empty:
            actual = float(df_m.at[idx[0], col_stock])
            df_m.at[idx[0], col_stock] = actual + cant

    df_clean = df_v[df_v['Ticket_ID'] != str(ticket_id)]
    
    save_data(df_clean, "ventas")
    save_data(df_m, "menu")
    return True, "Ticket eliminado de la nube."

# --- 3. VISTAS (FRONTEND) ---

def render_dashboard_section(df_ventas, key_suffix):
    if df_ventas.empty:
        st.info("Sin datos.")
        return

    tot_venta = df_ventas['Total_Venta'].sum()
    tot_ganancia = df_ventas['Ganancia'].sum()
    tot_costo = tot_venta - tot_ganancia
    num_tickets = df_ventas['Ticket_ID'].nunique()
    ticket_prom = tot_venta / num_tickets if num_tickets > 0 else 0
    
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Ventas", f"${tot_venta:,.0f}")
    k2.metric("Ganancia", f"${tot_ganancia:,.0f}")
    k3.metric("Costos", f"${tot_costo:,.0f}")
    k4.metric("Ticket Promedio", f"${ticket_prom:,.0f}")
    
    st.divider()
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("##### 💰 Dinero")
        fig = go.Figure(data=[go.Pie(labels=['Costo', 'Ganancia'], values=[tot_costo, tot_ganancia], hole=.4, marker_colors=['#EF553B', '#00CC96'])])
        st.plotly_chart(fig, use_container_width=True, key=f"pie_{key_suffix}")
    
    with c2:
        st.markdown("##### 🕒 Hora Pico")
        # Procesamiento seguro de hora
        df_ventas['Hora_Simple'] = df_ventas['Hora'].astype(str).str.split(':').str[0]
        v_hora = df_ventas.groupby('Hora_Simple')['Total_Venta'].sum().reset_index()
        fig2 = px.bar(v_hora, x='Hora_Simple', y='Total_Venta')
        st.plotly_chart(fig2, use_container_width=True, key=f"bar_{key_suffix}")

    # Tabla Matriz
    with st.expander("📊 Ver Detalle de Productos"):
        prod_an = df_ventas.groupby('Producto').agg({'Total_Venta':'sum', 'Ganancia':'sum', 'Cantidad':'sum'}).reset_index()
        prod_an['Margen %'] = (prod_an['Ganancia'] / prod_an['Total_Venta'] * 100).fillna(0)
        st.dataframe(prod_an.sort_values('Ganancia', ascending=False), use_container_width=True)

def view_pos(df_menu):
    st.markdown("### 🛒 Punto de Venta (Nube)")
    
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
                        color = "green" if stk > 5 else "red"
                        c2.markdown(f"${row['Precio']} | :{color}[{int(stk)}]")
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
                    if st.button("✅ COBRAR (Subir a Nube)", type="primary", use_container_width=True):
                        with st.spinner("Sincronizando con Google Drive..."):
                            tid = datetime.now().strftime("%Y%m%d-%H%M%S")
                            nuevas_ventas = []
                            hoy = datetime.now()
                            
                            for p, c in st.session_state.pedido.items():
                                idx = df_menu.index[df_menu['Producto'] == p][0]
                                row = df_menu.iloc[idx]
                                gan = (float(row['Precio']) - float(row['Costo'])) * c
                                
                                nuevas_ventas.append({
                                    "Ticket_ID": tid, "Fecha": hoy.strftime("%Y-%m-%d"), "Hora": hoy.strftime("%H:%M:%S"),
                                    "Ubicacion": ubi_db, "Categoria": row['Categoria'], "Producto": p, "Cantidad": c,
                                    "Total_Venta": float(row['Precio'])*c, "Ganancia": gan
                                })
                                # Restar stock localmente primero
                                df_menu.at[idx, col_stk] = float(row[col_stk]) - c
                            
                            # Subir a la nube
                            # 1. Descargar historial actual para no borrarlo
                            df_v_old = load_data("ventas")
                            df_v_new = pd.concat([df_v_old, pd.DataFrame(nuevas_ventas)], ignore_index=True)
                            
                            if save_data(df_v_new, "ventas"):
                                save_data(df_menu, "menu") # Guardar stock actualizado
                                st.session_state.pedido = {}
                                st.balloons()
                                st.toast("✅ Venta registrada en la Nube")
                                time.sleep(1)
                                st.rerun()
                else: st.error("Falta dinero")
            else: st.info("Vacío")

        with t2:
            st.caption("Últimos tickets en la nube")
            df_h = load_data("ventas")
            if not df_h.empty:
                # Asegurar ID como string
                df_h['Ticket_ID'] = df_h['Ticket_ID'].astype(str)
                resumen = df_h.groupby(['Ticket_ID', 'Ubicacion'])['Total_Venta'].sum().reset_index().sort_values('Ticket_ID', ascending=False).head(10)
                st.dataframe(resumen, hide_index=True)
                sel = st.selectbox("ID Ticket", resumen['Ticket_ID'])
                if st.button("🚫 CANCELAR TICKET"):
                    with st.spinner("Cancelando en la nube..."):
                        ok, msg = cancelar_ticket(sel)
                        if ok: st.success(msg); time.sleep(1); st.rerun()

def view_dashboard(df_menu):
    st.markdown("### 📊 Dashboard Nube")
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
        # Columnas calculadas
        df_menu['Ganancia_Unit'] = df_menu['Precio'] - df_menu['Costo']
        df_menu['Sug_33'] = df_menu['Costo'] * 1.5
        df_menu['Sug_66'] = df_menu['Costo'] * 3.0
        
        cfg = {
            "Categoria": st.column_config.SelectboxColumn(options=["🌽 Tamales", "🍔 Comida", "🥤 Bebidas", "🍬 Postres", "🍟 Snacks"], required=True),
            "Precio": st.column_config.NumberColumn(format="$%.2f"),
            "Costo": st.column_config.NumberColumn(format="$%.2f"),
            "Ganancia_Unit": st.column_config.NumberColumn("Ganancia", format="$%.2f", disabled=True),
            "Sug_33": st.column_config.NumberColumn("Sug 33%", format="$%.2f", disabled=True),
            "Sug_66": st.column_config.NumberColumn("Sug 66%", format="$%.2f", disabled=True),
        }
        df_ed = st.data_editor(df_menu, num_rows="dynamic", use_container_width=True, column_config=cfg)
        
        if st.button("💾 Sincronizar Inventario"):
            cols_save = ['Categoria', 'Producto', 'Precio', 'Costo', 'Stock_Local1', 'Stock_Local2', 'Stock_Feria']
            save_data(df_ed[cols_save], "menu")
            st.success("Nube actualizada.")
            time.sleep(1); st.rerun()

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
                st.success("Transferencia en Nube exitosa.")
            else: st.error("Stock insuficiente.")

def view_recipes(df_menu):
    st.markdown("### 🧪 Recetas Nube")
    df_rec = load_data("recetas")
    
    t_calc, t_edit = st.tabs(["🧮 Calculadora", "📝 Editar BD"])
    
    with t_calc:
        c1, c2 = st.columns(2)
        with c1:
            prod = st.selectbox("Producto:", df_menu['Producto'].unique(), key="s_p")
            # Auto-carga
            if 'last_pr' not in st.session_state or st.session_state.last_pr != prod:
                st.session_state.lista_insumos = []
                if not df_rec.empty:
                    filtro = df_rec[df_rec['Producto'] == prod]
                    for _, r in filtro.iterrows():
                        st.session_state.lista_insumos.append({"Ingrediente": r['Ingrediente'], "Costo": float(r['Costo_Ref']), "Cantidad": float(r['Cantidad_Base'])})
                st.session_state.last_pr = prod

            with st.form("a_ing"):
                ing = st.text_input("Ingrediente")
                cost = st.number_input("Costo Compra", 0.0)
                uso = st.number_input("Uso", 0.0, format="%.3f")
                if st.form_submit_button("Agregar"):
                    st.session_state.lista_insumos.append({"Ingrediente": ing, "Costo": cost, "Cantidad": uso}) # Simplificado para demo
                    st.rerun()
        
        with c2:
            if st.session_state.lista_insumos:
                df_i = pd.DataFrame(st.session_state.lista_insumos)
                st.dataframe(df_i, use_container_width=True)
                suma = df_i['Costo'].sum()
                st.success(f"Costo: ${suma:.2f}")
                
                if st.button("💾 Guardar en Nube"):
                    # Update Menú
                    idx = df_menu.index[df_menu['Producto'] == prod]
                    df_menu.at[idx[0], 'Costo'] = suma
                    save_data(df_menu, "menu")
                    
                    # Update Recetas
                    # 1. Bajar recetas actuales, filtrar y añadir nuevas
                    df_rec_full = load_data("recetas")
                    df_rec_clean = df_rec_full[df_rec_full['Producto'] != prod]
                    nuevas = [{"Producto": prod, "Ingrediente": i['Ingrediente'], "Cantidad_Base": i['Cantidad'], "Costo_Ref": i['Costo']} for i in st.session_state.lista_insumos]
                    df_final = pd.concat([df_rec_clean, pd.DataFrame(nuevas)])
                    save_data(df_final, "recetas")
                    st.toast("Guardado en Drive")

    with t_edit:
        st.info("Edita la base de datos de recetas directamente en la nube.")
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

    # Cargar Menú de Nube al inicio
    df_menu = load_data("menu")
    if df_menu.empty:
        st.warning("Cargando base de datos inicial o error de conexión...")
        if st.button("Inicializar DB en Drive (Solo primera vez)"):
            # Crear estructura inicial y subir
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