import pandas as pd
import streamlit as st
import altair as alt
import xmlrpc.client
from datetime import timedelta

# --- Streamlit Configuration ---
st.set_page_config(
    page_title="RJE Pipeline Resource Planning",
    page_icon=":factory:",
    layout="wide"
)
st.title("RJE Manufacturing Pipeline Resource Capacity Planning")

# --- Odoo Connection & Data ---
@st.cache_resource(show_spinner=False)
def connect_odoo():
    url = 'http://localhost:8069'
    db = 'rje'
    username = 'admin'
    password = 'admin'
    try:
        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        uid = common.authenticate(db, username, password, {})
        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
        if uid:
            return models, db, uid, password
        else:
            st.error("❌ Failed to authenticate with Odoo")
            return None, None, None, None
    except Exception as e:
        st.error(f"❌ Connection error: {str(e)}")
        return None, None, None, None

def clean_odoo_data(df):
    if df.empty:
        return df
    def safe_convert(val):
        if isinstance(val, (list, tuple)) and len(val) >= 2:
            return str(val[1])
        elif isinstance(val, (list, tuple)) and len(val) == 1:
            return str(val[0])
        elif val is False or val is None:
            return ''
        else:
            return str(val)
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].apply(safe_convert)
    return df

def fetch_odoo_data(model_name, fields=None, domain=None):
    models, db, uid, password = connect_odoo()
    if not models:
        return pd.DataFrame()
    try:
        ids = models.execute_kw(db, uid, password, model_name, 'search', [domain or []])
        if not ids:
            return pd.DataFrame()
        records = models.execute_kw(db, uid, password, model_name, 'read', [ids], {'fields': fields})
        df = pd.DataFrame(records)
        return clean_odoo_data(df)
    except Exception as e:
        st.error(f"Error fetching {model_name}: {str(e)}")
        return pd.DataFrame()

def normalize_certainty(certainty_value):
    if pd.isna(certainty_value) or certainty_value is False or certainty_value is None:
        return 25
    try:
        cert = float(certainty_value)
        if 0 <= cert <= 1:
            cert = cert * 100
        cert = max(0, min(cert, 100))
        if cert == 100:
            return 100
        elif 51 <= cert <= 75:
            return 75
        elif 26 <= cert <= 50:
            return 50
        else:
            return 25
    except (ValueError, TypeError):
        if isinstance(certainty_value, str):
            cert_str = certainty_value.lower().strip()
            if cert_str in ['confirmed', '100%', 'certain']:
                return 100
            elif cert_str in ['probable', 'likely', '75%']:
                return 75
            elif cert_str in ['possible', 'maybe', '50%']:
                return 50
            elif cert_str in ['planning', 'potential', '25%']:
                return 25
            elif cert_str in ['cancelled', 'uncertain', '0%']:
                return 0
        return 25

# --- Caching for Monthly Capacity (3600 minutes = 60 hours) ---
@st.cache_data(ttl=3600 * 60, show_spinner=False)
def get_cached_category_capacities():
    return {}

def set_cached_category_capacities(category_capacities):
    # Streamlit does not directly support "set cache", so we mimic this by using session_state and cache
    st.session_state['category_capacities'] = category_capacities

# --- Load Data from Odoo ---
manufacturing_orders = fetch_odoo_data(
    'mrp.production',
    fields=['id', 'date_start', 'name', 'project_number', 'origin', 'state', 'certainty', 'product_tmpl_id', 'product_qty'],
    domain=[('state', 'in', ['draft', 'quoted', 'confirmed', 'progress', 'to_close'])]
)
products = fetch_odoo_data(
    'product.product',
    fields=['name','categ_id', 'product_tmpl_id'],
    domain=[('active', '=', True)]
)

# --- Merge and Prepare Data ---
if not manufacturing_orders.empty and not products.empty:
    manufacturing_orders['product_tmpl_id'] = manufacturing_orders['product_tmpl_id'].astype(str)
    products['product_tmpl_id'] = products['product_tmpl_id'].astype(str)
    df = pd.merge(
        manufacturing_orders,
        products,
        left_on='product_tmpl_id',
        right_on='product_tmpl_id',
        how='left',
        suffixes=('', '_prod')
    )
    df = df.drop(columns=['product_tmpl_id', 'id_prod','id'], errors='ignore')
    df['Date'] = pd.to_datetime(df['date_start'], errors='coerce')
    df['Product Category'] = df['categ_id'].apply(lambda x: x[1] if isinstance(x, (list, tuple)) and len(x) >= 2 else x)
    df['Item'] = df['name_prod'].apply(lambda x: x[1] if isinstance(x, (list, tuple)) and len(x) >= 2 else x)
    df['Project_ID'] = df['project_number'] if 'project_number' in df.columns else ''
    df['Demand'] = 1
    df['certainty'] = df['certainty'].apply(normalize_certainty)
    df['Year_Month'] = df['Date'].dt.to_period('M')
    df = df[['Date', 'Product Category', 'Item', 'Project_ID', 'Demand', 'certainty', 'Year_Month']].dropna()
else:
    st.error("❌ No data after merge - manufacturing orders and products could not be merged")
    df = pd.DataFrame()

# --- Dashboard ---
if not df.empty and 'Product Category' in df.columns:

    unique_categories = df['Product Category'].unique()

    # --- Capacity Planning Inputs ---
    if 'category_capacities' not in st.session_state:
        # Try to get from cache
        st.session_state.category_capacities = get_cached_category_capacities()

    with st.expander("📋 Current Manufacturing Orders Summary", expanded=False):
        capacity_assessment_df = df[df['certainty'] >= 25]
        category_summary = capacity_assessment_df.groupby('Product Category').agg({
            'Item': 'count',
            'Date': ['min', 'max']
        }).round(2)
        category_summary.columns = ['Total Demand', 'Earliest Date', 'Latest Date']
        st.dataframe(category_summary, use_container_width=True)

    with st.expander("📊 Product Category Capacity Planning", expanded=False):
        st.markdown("🎛️ Set Monthly Capacity by Product Category")
        num_categories = len(unique_categories)
        rows_needed = (num_categories + 2) // 3
        for row in range(rows_needed):
            capacity_cols = st.columns(3)
            for col_idx in range(3):
                category_idx = row * 3 + col_idx
                if category_idx < num_categories:
                    category = unique_categories[category_idx]
                    with capacity_cols[col_idx]:
                        st.markdown(f"**{category}**")
                        current_operations = len(df[(df['Product Category'] == category) & (df['certainty'] >= 25)])
                        default_capacity = max(current_operations, 20)
                        capacity_key = f"capacity_{category.replace(' ', '_')}"
                        current_capacity = st.session_state.category_capacities.get(category, default_capacity)
                        new_capacity = st.number_input(
                            f"Monthly Capacity",
                            min_value=1,
                            max_value=1000,
                            value=int(current_capacity),
                            step=1,
                            key=capacity_key,
                            help=f"Monthly capacity for {category} (operations per month)"
                        )
                        st.session_state.category_capacities[category] = new_capacity
                        st.caption(f"Current operations: {current_operations}")
        st.markdown("---")
        _, col2, _ = st.columns([1, 1, 1])
        with col2:
            if st.button("🔄 Apply Capacity Settings", type="primary", use_container_width=True):
                set_cached_category_capacities(st.session_state.category_capacities)
                st.success("✅ Capacity settings applied! (cached for 3600 mins)")
                st.rerun()

    # --- Apply Capacity ---
    df['Capacity'] = df['Product Category'].apply(lambda x: st.session_state.category_capacities.get(x, 100))

    # --- Controls ---
    min_date = df['Date'].min().date()
    max_date = df['Date'].max().date() + timedelta(days=1)
    col1, col2, col3 = st.columns(3)
    with col1:
        with st.container(border=True, height=150):
            st.text("")
            selected_dates = st.date_input("Select Date Range", value=[min_date, max_date], min_value=min_date, max_value=max_date, help="Select the date range for manufacturing orders", key="date_range_filter")
            start_date, end_date = selected_dates
            start_date_timestamp = pd.Timestamp(start_date)
            end_date_timestamp = pd.Timestamp(end_date)
    mfg_df_dt = df[(df["Date"] >= start_date_timestamp) & (df["Date"] <= end_date_timestamp)]
    with col2:
        with st.container(border=True, height=150):
            st.text("")
            selected_certainty = st.slider(
                "Select Minimum Certainty",
                min_value=25,
                max_value=100,
                value=25,
                step=25,
                help="Include all orders with this certainty % and higher"
            )
    mfg_df_lk = mfg_df_dt[mfg_df_dt['certainty'] >= selected_certainty]
    with col3:
        with st.container(border=True, height=150):
            category_list = mfg_df_lk['Product Category'].unique().tolist()
            default_category = category_list[1] if len(category_list) > 1 else (category_list[0] if category_list else None)
            selected_categories = st.multiselect(
                "Select Product Category(s) to Generate Time-Series",
                category_list,
                default=default_category,
                help="Select one or more product categories to generate time-series charts",
                key="product_category_filter"
            )
            if st.button("🔄 Refresh Charts", use_container_width=True):
                st.success("✅ Charts refreshed!")
                st.rerun()

    mfg_df_filtered = mfg_df_lk[mfg_df_lk['Product Category'].isin(selected_categories)]

    # --- Capacity Analysis & KPI ---
    mfg_kpi_grp_2 = mfg_df_lk.groupby(['Product Category','Year_Month'], as_index=False).agg({'Capacity':'first','Demand':'sum'})
    mfg_kpi_grp_2['Over Capacity'] = mfg_kpi_grp_2['Demand'] - mfg_kpi_grp_2['Capacity']
    mfg_kpi_grp_2 = mfg_kpi_grp_2[mfg_kpi_grp_2['Over Capacity'] > 0].reset_index()
    mfg_kpi_grp = mfg_kpi_grp_2.groupby('Product Category', as_index=False)["Over Capacity"].sum()

    if len(mfg_kpi_grp) == 0:
        st.markdown(
            """
            <div style="text-align: center; background-color: #d4d9ee; border: 2px solid #d4d9ee; border-radius: 10px; padding: 10px;">
                <h5>No Over Capacity Product Categories for selected date range and certainty</h5>
            </div>
            """,
            unsafe_allow_html=True
        )
    else:
        columns = st.columns(len(mfg_kpi_grp['Product Category'].unique()))
        for i, col in enumerate(columns):
            with col:
                cat = mfg_kpi_grp['Product Category'].iloc[i]
                overcap = int(mfg_kpi_grp['Over Capacity'].iloc[i])
                st.markdown(
                    f"""
                    <div style="text-align: center; background-color: #d4d9ee; border: 2px solid #d4d9ee; border-radius: 10px; padding: 10px;">
                        <h4>{cat} </h4>
                        <h5>{overcap} demands over capacity</h5>
                        <h6>For date range: {start_date} to {end_date}</h6>
                        <h6>and {selected_certainty}% certainty</h6>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                monthly_df = mfg_kpi_grp_2[mfg_kpi_grp_2['Product Category'] == cat].copy()
                if not monthly_df.empty:
                    monthly_display = monthly_df[['Year_Month', 'Demand', 'Capacity', 'Over Capacity']].copy()
                    monthly_display['Year_Month'] = monthly_display['Year_Month'].astype(str)
                    monthly_display.columns = ['Month', 'Demand', 'Capacity', 'Over Capacity']
                    st.text("")
                    st.dataframe(monthly_display, use_container_width=True)
                else:
                    st.write("No over-capacity data available for this category.")

    # --- Charts ---
    st.text("")
    st.text("")
    def create_chart_altair(df, producer):
        if df.empty:
            st.warning(f"⚠️ No data for {producer}")
            return
        dataset_certainties = sorted([l for l in df['certainty'].unique() if pd.notna(l)])
        usable_certainties = [l for l in dataset_certainties if l >= selected_certainty]
        if not usable_certainties:
            st.info(f"ℹ️ No data for {producer} with minimum {selected_certainty}% certainty")
            return
        df_filtered = df[df['certainty'] >= selected_certainty].copy()
        if df_filtered.empty:
            st.warning(f"⚠️ No operations for {producer} after filtering")
            return
        piv = df_filtered.pivot_table(index=['Date'], columns='certainty', values='Demand', aggfunc='sum', fill_value=0).reset_index()
        actual_certainty_cols = [col for col in piv.columns if col != 'Date']
        all_colors = {
            0: '#F0F0F0',
            25: '#87CEEB',
            50: '#FFE4B5',
            75: '#FFB6C1',
            100: '#90EE90'
        }
        colors = {level: all_colors[level] for level in actual_certainty_cols if level in all_colors}
        piv_melted = piv.melt(id_vars=['Date'], value_vars=actual_certainty_cols, var_name='Certainty', value_name='Demand')
        piv_melted = piv_melted[piv_melted['Demand'] > 0]
        if piv_melted.empty:
            st.info(f"ℹ️ No non-zero demand for {producer}")
            return
        total_demand = piv[actual_certainty_cols].sum(axis=1)
        capacity_data = df_filtered.groupby('Date').agg({'Capacity': 'first'}).reset_index()
        capacity_data = capacity_data.merge(
            pd.DataFrame({'Date': piv['Date'], 'Total_Demand': total_demand}), on='Date', how='left').fillna(0)
        capacity_data['Over_Cap'] = capacity_data['Total_Demand'] - capacity_data['Capacity']
        capacity_data['Over_Cap'] = capacity_data['Over_Cap'].apply(lambda x: max(0, x) if pd.notna(x) else 0)
        bar_chart = (
            alt.Chart(piv_melted)
            .mark_bar()
            .encode(
                x=alt.X("Date:T", title="Month", timeUnit="yearmonth"),
                y=alt.Y("sum(Demand):Q", title="Operations"),
                color=alt.Color(
                    "Certainty:N",
                    scale=alt.Scale(
                        domain=list(colors.keys()),
                        range=list(colors.values())
                    ),
                    legend=alt.Legend(
                        title="Certainty Level",
                        labelExpr="datum.label + '% Certainty'"
                    )
                ),
                tooltip=[
                    alt.Tooltip("Date:T", title="Month", timeUnit="yearmonth"),
                    alt.Tooltip("Certainty:N", title="Certainty Level", format=".0f"),
                    alt.Tooltip("sum(Demand):Q", title="Operations")
                ]
            )
        )
        capacity_line = (
            alt.Chart(capacity_data[capacity_data['Capacity'] > 0])
            .mark_line(strokeDash=[5, 5], color="red", strokeWidth=3)
            .encode(
                x=alt.X("Date:T", timeUnit="yearmonth"),
                y="Capacity:Q",
                tooltip=[
                    alt.Tooltip("Date:T", title="Month", timeUnit="yearmonth"),
                    alt.Tooltip("Capacity:Q", title="Monthly Capacity")
                ]
            )
        )
        over_cap_data = capacity_data[capacity_data['Over_Cap'] > 0]
        if not over_cap_data.empty:
            over_cap_labels = (
                alt.Chart(over_cap_data)
                .mark_text(dy=-15, fontSize=14, fontWeight='bold', color='darkred')
                .encode(
                    x=alt.X("Date:T", timeUnit="yearmonth"),
                    y="Total_Demand:Q",
                    text=alt.Text("Over_Cap:Q", format=".0f"),
                    tooltip=[
                        alt.Tooltip("Date:T", title="Month", timeUnit="yearmonth"),
                        alt.Tooltip("Over_Cap:Q", title="Operations Over Capacity")
                    ]
                )
            )
            final_chart = bar_chart + capacity_line + over_cap_labels
        else:
            final_chart = bar_chart + capacity_line
        final_chart = final_chart.properties(
            title=f"Product Category Demand: {producer} (Certainty ≥ {selected_certainty}%)", width=800, height=450).resolve_scale(color='independent')
        st.altair_chart(final_chart, use_container_width=True)
        try:
            html_str = final_chart.to_html()
            st.download_button(
                label="📄 Download Chart as HTML",
                data=html_str,
                file_name=f"{producer}_chart.html",
                mime="text/html",
                key=f"html_{producer}"
            )
        except Exception as e:
            st.error(f"Chart export error: {e}")

    if selected_categories and not mfg_df_filtered.empty:
        for category in selected_categories:
            category_df = mfg_df_filtered[mfg_df_filtered['Product Category'] == category]
            if not category_df.empty:
                create_chart_altair(category_df, category)
    else:
        if not selected_categories:
            st.warning("⚠️ Please select at least one product category to generate time-series charts.")
        elif mfg_df_filtered.empty:
            st.warning("⚠️ No data available for the selected categories and filters.")

else:
    st.warning("⚠️ Cannot proceed with dashboard - no valid merged data available.")
    st.info("Please check the debug information above to resolve data issues.")