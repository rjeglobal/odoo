from typing import List
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import numpy as np
import io
import datetime as dt
import altair as alt
import xmlrpc.client

# Streamlit Configuration
st.set_page_config(
    page_title="RJE Pipeline Resource Planning",
    page_icon=":factory:",
    layout="wide")

st.title("RJE Manufacturing Pipeline Resource Capacity Planning")

# Odoo Connection Functions
def connect_odoo():
    """Connect to Odoo - not cached due to XML-RPC serialization issues"""
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
    """Clean and format Odoo data for processing"""
    if df.empty:
        return df
    
    for col in df.columns:
        if df[col].dtype == 'object':
            def safe_convert(val):
                if isinstance(val, (list, tuple)) and len(val) >= 2:
                    return str(val[1]) 
                elif isinstance(val, (list, tuple)) and len(val) == 1:
                    return str(val[0])
                elif val is False or val is None:
                    return ''
                else:
                    return str(val)
            
            df[col] = df[col].apply(safe_convert)
    
    return df

def fetch_odoo_data(model_name, fields=None, domain=None):
    """Fetch data from Odoo model"""
    models, db, uid, password = connect_odoo()
    
    if not models:
        return pd.DataFrame()
    
    try:
        # Search and read records
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
    """Convert Odoo certainty values to standard certainty ranges"""
    if pd.isna(certainty_value) or certainty_value is False or certainty_value is None:
        return 25  # Default for missing values (low certainty)
    
    try:
        # Convert to float first to handle various formats
        cert = float(certainty_value)
        
        # Handle decimal format (0.0 to 1.0) - convert to percentage
        if 0 <= cert <= 1:
            cert = cert * 100
        
        # Cap values at reasonable bounds
        if cert > 100:
            cert = 100
        elif cert < 0:
            cert = 0
        
        # Map to certainty ranges
        if cert == 100:
            return 100 
        elif 51 <= cert <= 75:
            return 75   
        elif 26 <= cert <= 50:
            return 50   
        else:  
            return 25  
            
    except (ValueError, TypeError):
        # Handle text formats
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

        # Default fallback
        return 25

# Load data from Odoo
manufacturing_orders = fetch_odoo_data(
    'mrp.production',
    fields=['id', 'date_start', 'name', 'project_number', 'origin', 'state', 'certainty', 'product_tmpl_id', 'product_qty'],
    domain=[('state', 'in', ['draft', 'quoted', 'confirmed', 'progress', 'to_close'])]
)

products = fetch_odoo_data(
    'product.product',
    fields=['name','categ_id', 'product_tmpl_id'],
    domain=[('active', '=', True)])

# Data Processing
if not manufacturing_orders.empty and not products.empty:
    manufacturing_orders['product_tmpl_id'] = manufacturing_orders['product_tmpl_id'].astype(str)
    products['product_tmpl_id'] = products['product_tmpl_id'].astype(str)

    manufacturing_orders_df = pd.merge(
        manufacturing_orders,
        products,
        left_on='product_tmpl_id',
        right_on='product_tmpl_id',
        how='left',
        suffixes=('', '_prod')
    )

    # drop unnecessary columns
    manufacturing_orders_df = manufacturing_orders_df.drop(columns=['product_tmpl_id', 'id_prod','id'], errors='ignore')
    
    manufacturing_orders_df['Date'] = pd.to_datetime(manufacturing_orders_df['date_start'], errors='coerce')
    manufacturing_orders_df['Product Category'] = manufacturing_orders_df['categ_id'].apply(lambda x: x[1] if isinstance(x, (list, tuple)) and len(x) >= 2 else x)
    manufacturing_orders_df['Item'] = manufacturing_orders_df['name_prod'].apply(lambda x: x[1] if isinstance(x, (list, tuple)) and len(x) >= 2 else x)
    manufacturing_orders_df['Project_ID'] = manufacturing_orders_df['project_number'] if 'project_number' in manufacturing_orders_df.columns else ''
    manufacturing_orders_df['Demand'] = 1
    manufacturing_orders_df['certainty'] = manufacturing_orders_df['certainty'].apply(normalize_certainty)
    manufacturing_orders_df['Year_Month'] = manufacturing_orders_df['Date'].dt.to_period('M')
    
    # Clean up columns
    manufacturing_orders_df = manufacturing_orders_df[['Date', 'Product Category', 'Item', 'Project_ID', 'Demand', 'certainty', 'Year_Month']].dropna()
            
    proceed_with_dashboard = True
else:
    st.error("❌ No data after merge - manufacturing orders and products could not be merged")
    proceed_with_dashboard = False
    manufacturing_orders_df = pd.DataFrame()

# Only proceed with dashboard if we have data
if proceed_with_dashboard and not manufacturing_orders_df.empty and 'Product Category' in manufacturing_orders_df.columns:    
    # Get unique product categories
    unique_categories = manufacturing_orders_df['Product Category'].unique()
    
    # Initialize session state for capacity if not exists
    if 'category_capacities' not in st.session_state:
        st.session_state.category_capacities = {}
    
    # Display current manufacturing orders summary
    with st.expander("📋 Current Manufacturing Orders Summary", expanded=False):
        # Filter to include certainty 25% and above for capacity assessment
        capacity_assessment_df = manufacturing_orders_df[manufacturing_orders_df['certainty'] >= 25]
        
        category_summary = capacity_assessment_df.groupby('Product Category').agg({
            'Item': 'count',
            'Date': ['min', 'max']
        }).round(2)
        category_summary.columns = ['Total Demand', 'Earliest Date', 'Latest Date']
        st.dataframe(category_summary, use_container_width=True)
    
    with st.expander("📊 Product Category Capacity Planning", expanded=False):
        st.markdown("🎛️ Set Monthly Capacity by Product Category")

        if len(unique_categories) > 0:
            # Create columns for capacity inputs (3 per row)
            num_categories = len(unique_categories)
            rows_needed = (num_categories + 2) // 3  # Round up division
            
            for row in range(rows_needed):
                capacity_cols = st.columns(3)
                
                for col_idx in range(3):
                    category_idx = row * 3 + col_idx
                    if category_idx < num_categories:
                        category = unique_categories[category_idx]
                        
                        with capacity_cols[col_idx]:
                            st.markdown(f"**{category}**")
                            
                            # Get current operations count for this category (include all certainty levels 25-100%)
                            current_operations = len(manufacturing_orders_df[(manufacturing_orders_df['Product Category'] == category) & (manufacturing_orders_df['certainty'] >= 25)])
                            
                            # Default capacity based on current workload
                            default_capacity = max(current_operations, 20)
                            
                            # Capacity input
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
                            
                            # Show current operations count
                            st.caption(f"Current operations: {current_operations}")
            
            # Apply button
            st.markdown("---")
            col1, col2, col3 = st.columns([1, 1, 1])
            with col2:
                if st.button("🔄 Apply Capacity Settings", type="primary", use_container_width=True):
                    st.success("✅ Capacity settings applied!")
                    st.rerun()
        else:
            st.warning("No product categories found in the merged data.")

    # Apply user-defined capacity to dataframe
    def get_monthly_capacity(category_name):
        return st.session_state.category_capacities.get(category_name, 100)
    
    manufacturing_orders_df['Capacity'] = manufacturing_orders_df['Product Category'].apply(get_monthly_capacity)
    
    # Get min and max date values from the DataFrame
    from datetime import timedelta
    min_date = manufacturing_orders_df['Date'].min().date()
    max_date = manufacturing_orders_df['Date'].max().date() + timedelta(days=1)
    
    # Filter Controls
    col1, col2, col3 = st.columns(3)

    with col1:
        with st.container(border=True, height=150):
            st.text("")
            selected_dates = st.date_input("Select Date Range", value=[min_date, max_date], min_value=min_date, max_value=max_date, help="Select the date range for manufacturing orders",
                                            key="date_range_filter")
            
            # Extract the start and end dates
            start_date, end_date = selected_dates
            start_date_timestamp = pd.Timestamp(start_date)
            end_date_timestamp = pd.Timestamp(end_date)
    
    # Filter by date first
    mfg_df_dt = manufacturing_orders_df[(manufacturing_orders_df["Date"] >= start_date_timestamp) & (manufacturing_orders_df["Date"] <= end_date_timestamp)]
    
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
    
    # Apply certainty filter
    mfg_df_lk = mfg_df_dt[mfg_df_dt['certainty'] >= selected_certainty]
    
    # Grouping for capacity analysis - use MONTHLY aggregation
    mfg_kpi_grp_2 = mfg_df_lk.groupby(['Product Category','Year_Month'], as_index=False).agg({'Capacity':'first','Demand':'sum'})
    mfg_kpi_grp_2['Over Capacity'] = mfg_kpi_grp_2['Demand'] - mfg_kpi_grp_2['Capacity']
    mfg_kpi_grp_2 = mfg_kpi_grp_2[mfg_kpi_grp_2['Over Capacity'] > 0].reset_index()
    
    # Grouping for KPI cards
    mfg_kpi_grp = mfg_kpi_grp_2.groupby('Product Category', as_index=False)["Over Capacity"].sum()
    
    # KPI cards
    if len(mfg_kpi_grp) == 0:
        st.markdown(f"""
                        <div style="text-align: center; white-space: normal; word-wrap: break-word;
                                    background-color: #d4d9ee; border: 2px solid #d4d9ee; border-radius: 10px; padding: 10px;">                    
                            <h5>No Over Capacity Product Categories for selected date range and certainty</h5>
                        </div>
                        """,
                        unsafe_allow_html=True)
    else:    
        columns = st.columns(len(mfg_kpi_grp['Product Category'].unique()))
        
        for i, col in enumerate(columns):
            with col:
                if len(mfg_kpi_grp) > 0:
                    st.markdown(
                        f"""
                        <div style="text-align: center; white-space: normal; word-wrap: break-word;
                                    background-color: #d4d9ee; border: 2px solid #d4d9ee; border-radius: 10px; padding: 10px;">
                            <h4>{mfg_kpi_grp['Product Category'].iloc[i]} </h4>
                            <h5>{int(mfg_kpi_grp['Over Capacity'].iloc[i])} operations over capacity</h5>
                            <h6>For date range: {start_date} to {end_date}</h6>
                            <h6>and {selected_certainty}% certainty</h6>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    
                    # Filter data for the current category - show monthly over-capacity details
                    monthly_df = mfg_kpi_grp_2[mfg_kpi_grp_2['Product Category'] == mfg_kpi_grp['Product Category'].iloc[i]].copy()
                    
                    if monthly_df.empty:
                        st.write("No over-capacity data available for this category.")
                        continue
                    
                    # Show monthly over-capacity breakdown
                    monthly_display = monthly_df[['Year_Month', 'Demand', 'Capacity', 'Over Capacity']].copy()
                    monthly_display['Year_Month'] = monthly_display['Year_Month'].astype(str)
                    monthly_display.columns = ['Month', 'Demand', 'Capacity', 'Over Capacity']
                    
                    # Display the monthly over-capacity DataFrame
                    st.text("")
                    st.dataframe(monthly_display, use_container_width=True)
    
    # Product Category filter
    with col3:
        with st.container(border=True, height=150):
            category_list = mfg_df_lk['Product Category'].unique().tolist()
            default_category = category_list[1] if category_list else None
            selected_categories = st.multiselect("Select Product Category(s) to Generate Time-Series", 
                                                category_list, 
                                                default=default_category, help="Select one or more product categories to generate time-series charts",
                                                key="product_category_filter")
            if st.button("🔄 Refresh Charts", use_container_width=True):
                st.success("✅ Charts refreshed!")
                st.rerun()

    # Filter data based on selected categories
    mfg_df_filtered = mfg_df_lk[mfg_df_lk['Product Category'].isin(selected_categories)]
    
    st.text("")
    st.text("")
    
    def create_chart_altair(df: pd.DataFrame, producer):
        if df.empty:
            st.warning(f"⚠️ No data for {producer}")
            return
        
        # Get the actual certainty levels in this specific dataset
        dataset_certainties = sorted([l for l in df['certainty'].unique() if pd.notna(l)])
        
        # Filter to only include certainties >= selected_certainty threshold
        usable_certainties = [l for l in dataset_certainties if l >= selected_certainty]
        
        if not usable_certainties:
            st.info(f"ℹ️ No data for {producer} with minimum {selected_certainty}% certainty")
            return
        
        # Filter dataframe to include all certainty levels >= selected_certainty
        df_filtered = df[df['certainty'] >= selected_certainty].copy()
        
        if df_filtered.empty:
            st.warning(f"⚠️ No operations for {producer} after filtering")
            return
        
        # Create pivot table
        piv = df_filtered.pivot_table(index=['Date'], columns='certainty', values='Demand', aggfunc='sum', fill_value=0).reset_index()
        
        # Get certainty columns that actually exist in pivot (excluding 'Date')
        actual_certainty_cols = [col for col in piv.columns if col != 'Date']
        
        # Complete color mapping for all possible levels
        all_colors = {
            0: '#F0F0F0',    
            25: '#87CEEB',   # Sky blue for 25% (potential)  
            50: '#FFE4B5',   # Moccasin for 50% (possible)
            75: '#FFB6C1',   # Light pink for 75% (probable)
            100: '#90EE90'   # Light green for 100% (confirmed)
        }
        
        # Use colors only for levels that exist in this chart
        colors = {level: all_colors[level] for level in actual_certainty_cols if level in all_colors}
        
        # Melt for Altair
        piv_melted = piv.melt(id_vars=['Date'], value_vars=actual_certainty_cols, var_name='Certainty', value_name='Demand')

        # Remove zero demand entries for cleaner visualization
        piv_melted = piv_melted[piv_melted['Demand'] > 0]
        
        if piv_melted.empty:
            st.info(f"ℹ️ No non-zero demand for {producer}")
            return
        
        # Calculate total demand across all included certainty levels
        total_demand = piv[actual_certainty_cols].sum(axis=1)
        
        # Get capacity data for this category
        capacity_data = df_filtered.groupby('Date').agg({'Capacity': 'first'}).reset_index()

        # Merge total demand with capacity
        capacity_data = capacity_data.merge(
            pd.DataFrame({'Date': piv['Date'], 'Total_Demand': total_demand}), on='Date', how='left').fillna(0)
        
        # Calculate over-capacity
        capacity_data['Over_Cap'] = capacity_data['Total_Demand'] - capacity_data['Capacity']
        capacity_data['Over_Cap'] = capacity_data['Over_Cap'].apply(lambda x: max(0, x) if pd.notna(x) else 0)
        
        # Create stacked bar chart
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
        
        # Add capacity line
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
        
        # Add over-capacity warning labels
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
        
        # Configure chart
        final_chart = final_chart.properties(
            title=f"Product Category Demand: {producer} (Certainty ≥ {selected_certainty}%)", width=800, height=450).resolve_scale(color='independent')
        
        # Display chart
        st.altair_chart(final_chart, use_container_width=True)
        
        # Simple export option
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
    
    # Create charts for selected categories
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
    # Show message when no valid data for dashboard
    if not proceed_with_dashboard:
        st.warning("⚠️ Cannot proceed with dashboard - no valid merged data available.")
        st.info("Please check the debug information above to resolve data issues.")
    else:
        st.error("❌ Dashboard data is missing required 'Product Category' column.")

# # Create dataframe for conflicting manufacturing orders
# with st.expander("🚨 Conflicting Manufacturing Orders (Over-Capacity)", expanded=True):
#     if not mfg_kpi_grp_2.empty:
#         over_capacity_months = mfg_kpi_grp_2[['Product Category', 'Year_Month']].copy()
#         conflicting_orders = mfg_df_lk.merge(
#             over_capacity_months, 
#             on=['Product Category', 'Year_Month'], 
#         how='inner'
#     )
    
#     # Add over-capacity information
#     conflicting_orders = conflicting_orders.merge(
#         mfg_kpi_grp_2[['Product Category', 'Year_Month', 'Over Capacity']], 
#         on=['Product Category', 'Year_Month'], 
#         how='left'
#     )
    
#     if not conflicting_orders.empty:
#         # st.write("🚨 Conflicting Manufacturing Orders (Contributing to Over-Capacity):")
#         st.dataframe(conflicting_orders, use_container_width=True)
