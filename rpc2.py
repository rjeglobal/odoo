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
    layout="wide"
)

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
                    return str(val[1])  # Use the display name
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
    fields=['id', 'date_start', 'name', 'project_number', 'origin', 'state', 'certainty', 'product_id', 'product_qty'],
    domain=[('state', 'in', ['draft', 'quoted', 'confirmed', 'progress', 'to_close'])]
)

work_orders = fetch_odoo_data(
    'mrp.workorder',
    fields=['id', 'name', 'workcenter_id', 'production_id', 'project_number', 'mo_state_display', 'state'],
    domain=[('state', 'in', ['pending', 'ready', 'progress'])]
)

workcenters = fetch_odoo_data(
    'mrp.workcenter',
    fields=['id', 'name']
)

# Data Processing
if not manufacturing_orders.empty and not work_orders.empty:
    # Correct merge: work_order.production_id = manufacturing_order.name
    work_orders['production_id_str'] = work_orders['production_id'].astype(str)
    manufacturing_orders['name_str'] = manufacturing_orders['name'].astype(str)
    
    wf_df = pd.merge(work_orders, manufacturing_orders, 
                    left_on='production_id_str', right_on='name_str', 
                    how='inner', suffixes=('_wo', '_mo'))
    
    # st.dataframe(wf_df, use_container_width=True)
    
    if not wf_df.empty:
        # Create the expected columns
        wf_df['Date'] = pd.to_datetime(wf_df['date_start'], errors='coerce')
        wf_df['Workcenter'] = wf_df['workcenter_id']
        wf_df['Item'] = wf_df['product_id']
        wf_df['Project_ID'] = wf_df['project_number'] if 'project_number' in wf_df.columns else wf_df['production_id_str']
        wf_df['Demand'] = 1  
        
        # Apply robust certainty normalization
        wf_df['certainty'] = wf_df['certainty'].apply(normalize_certainty)
        
        # Convert to monthly aggregation for capacity planning
        wf_df['Year_Month'] = wf_df['Date'].dt.to_period('M')
        
        # Clean up columns
        wf_df = wf_df[['Date', 'Workcenter', 'Item', 'Project_ID', 'Demand', 'certainty', 'Year_Month']].dropna()
        
        proceed_with_dashboard = True
    else:
        st.error("❌ No data after merge - production_id values don't match name values")
        proceed_with_dashboard = False
        wf_df = pd.DataFrame()

else:
    st.warning("⚠️ No data found in Odoo or connection failed.")
    proceed_with_dashboard = False
    wf_df = pd.DataFrame()

# Only proceed with dashboard if we have data
if proceed_with_dashboard and not wf_df.empty and 'Workcenter' in wf_df.columns:    
    # Get unique workcenters from work orders
    unique_workcenters = wf_df['Workcenter'].unique()
    
    # Initialize session state for capacity if not exists
    if 'workcenter_capacities' not in st.session_state:
        st.session_state.workcenter_capacities = {}
    
    # Display current work order summary (include all certainty levels 25-100%)
    with st.expander("📋 Current Work Orders Summary", expanded=False):
        # Filter to include certainty 25% and above for capacity assessment
        capacity_assessment_df = wf_df[wf_df['certainty'] >= 25]
        
        workcenter_summary = capacity_assessment_df.groupby('Workcenter').agg({
            'Item': 'count',
            'Date': ['min', 'max']
        }).round(2)
        workcenter_summary.columns = ['Total Operations', 'Earliest Date', 'Latest Date']
        st.dataframe(workcenter_summary, use_container_width=True)
    

    with st.expander("📊 Work Order Capacity Planning", expanded=False):
    # Create capacity configuration in columns
        st.markdown("🎛️ Set Monthly Capacity by Workcenter")

        if len(unique_workcenters) > 0:
            # Create columns for capacity inputs (3 per row)
            num_workcenters = len(unique_workcenters)
            rows_needed = (num_workcenters + 2) // 3  # Round up division
            
            for row in range(rows_needed):
                capacity_cols = st.columns(3)
                
                for col_idx in range(3):
                    workcenter_idx = row * 3 + col_idx
                    if workcenter_idx < num_workcenters:
                        workcenter = unique_workcenters[workcenter_idx]
                        
                        with capacity_cols[col_idx]:
                            st.markdown(f"**{workcenter}**")
                            
                            # Get current operations count for this workcenter (include all certainty levels 25-100%)
                            current_operations = len(wf_df[(wf_df['Workcenter'] == workcenter) & (wf_df['certainty'] >= 25)])
                            
                            # Default capacity based on current workload
                            default_capacity = max(current_operations, 20)
                            
                            # Capacity input
                            capacity_key = f"capacity_{workcenter.replace(' ', '_')}"
                            current_capacity = st.session_state.workcenter_capacities.get(workcenter, default_capacity)
                            
                            new_capacity = st.number_input(
                                f"Monthly Capacity",
                                min_value=1,
                                max_value=1000,
                                value=int(current_capacity),
                                step=1,
                                key=capacity_key,
                                help=f"Monthly capacity for {workcenter} (operations per month)"
                            )
                            
                            st.session_state.workcenter_capacities[workcenter] = new_capacity
                            
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
            st.warning("No workcenters found in the merged data.")
    
    # Apply user-defined capacity to dataframe
    def get_monthly_capacity(workcenter_name):
        return st.session_state.workcenter_capacities.get(workcenter_name, 100)
    
    wf_df['Capacity'] = wf_df['Workcenter'].apply(get_monthly_capacity)
    
    # Get min and max date values from the DataFrame
    from datetime import timedelta
    min_date = wf_df['Date'].min().date()
    max_date = wf_df['Date'].max().date() + timedelta(days=1)
    
    # Filter Controls
    col1, col2, col3 = st.columns(3)
    
    with col1:
        with st.container(border=True, height=100):
            selected_dates = st.date_input("Select Date Range", value=[min_date, max_date], min_value=min_date, max_value=max_date)
            
            # Extract the start and end dates
            start_date, end_date = selected_dates
            start_date_timestamp = pd.Timestamp(start_date)
            end_date_timestamp = pd.Timestamp(end_date)
    
    # Filter by date first
    wf_df_dt = wf_df[(wf_df["Date"] >= start_date_timestamp) & (wf_df["Date"] <= end_date_timestamp)]
    
    with col2:
        with st.container(border=True, height=100):
            selected_certainty = st.slider(
                "Select Minimum Certainty", 
                min_value=25, 
                max_value=100, 
                value=25,  # Start at 25 to include all levels
                step=25,
                help="Include all orders with this certainty % and higher"
            )
    
    # Apply certainty filter - include ALL jobs with certainty >= selected_certainty
    wf_df_lk = wf_df_dt[wf_df_dt['certainty'] >= selected_certainty]
    
    # Grouping for Each Item (using Workcenter) - use MONTHLY aggregation for proper capacity comparison
    wf_df_kpi_grp_2 = wf_df_lk.groupby(['Workcenter','Year_Month'], as_index=False).agg({'Capacity':'first','Demand':'sum'})
    wf_df_kpi_grp_2['Over Capacity'] = wf_df_kpi_grp_2['Demand'] - wf_df_kpi_grp_2['Capacity']
    wf_df_kpi_grp_2 = wf_df_kpi_grp_2[wf_df_kpi_grp_2['Over Capacity'] > 0].reset_index()
    
    # Grouping for KPI cards
    wf_df_kpi_grp = wf_df_kpi_grp_2.groupby('Workcenter', as_index=False)["Over Capacity"].sum()
    
    # KPI cards
    if len(wf_df_kpi_grp) == 0:
        st.markdown(f"""
                        <div style="text-align: center; white-space: normal; word-wrap: break-word;
                                    background-color: #d4d9ee; border: 2px solid #d4d9ee; border-radius: 10px; padding: 10px;">                    
                            <h5>No Over Capacity Workcenters for selected date range and certainty</h5>
                        </div>
                        """,
                        unsafe_allow_html=True)
    else:    
        columns = st.columns(len(wf_df_kpi_grp['Workcenter'].unique()))
        
        for i, col in enumerate(columns):
            with col:
                if len(wf_df_kpi_grp) > 0:
                    st.markdown(
                        f"""
                        <div style="text-align: center; white-space: normal; word-wrap: break-word;
                                    background-color: #d4d9ee; border: 2px solid #d4d9ee; border-radius: 10px; padding: 10px;">
                            <h4>{wf_df_kpi_grp['Workcenter'].iloc[i]} Workcenter</h4>
                            <h5>{int(wf_df_kpi_grp['Over Capacity'].iloc[i])} operations over capacity</h5>
                            <h6>For date range: {start_date} to {end_date}</h6>
                            <h6>and {selected_certainty}% certainty</h6>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                    
                    # Filter data for the current workcenter - show monthly over-capacity details
                    monthly_df = wf_df_kpi_grp_2[wf_df_kpi_grp_2['Workcenter'] == wf_df_kpi_grp['Workcenter'].iloc[i]].copy()
                    
                    if monthly_df.empty:
                        st.write("No over-capacity data available for this workcenter.")
                        continue
                    
                    # Show monthly over-capacity breakdown
                    monthly_display = monthly_df[['Year_Month', 'Demand', 'Capacity', 'Over Capacity']].copy()
                    monthly_display['Year_Month'] = monthly_display['Year_Month'].astype(str)
                    monthly_display.columns = ['Month', 'Demand', 'Capacity', 'Over Capacity']
                    
                    # Display the monthly over-capacity DataFrame
                    st.dataframe(monthly_display, use_container_width=True)
    
    # Workcenter filter
    with col3:
        with st.container(border=True, height=100):
            workcenter_list = wf_df_lk['Workcenter'].unique().tolist()
            default_workcenter = workcenter_list[0] if workcenter_list else None
            selected_workcenters = st.multiselect("Select Workcenter(s) to Generate Time-Series", 
                                                workcenter_list, 
                                                default=default_workcenter)
    
    # Filter data based on selected Workcenters
    wf_df_filtered = wf_df_lk[wf_df_lk['Workcenter'].isin(selected_workcenters)]
    
    st.text("")
    st.text("")
    
    def create_chart_altair(df: pd.DataFrame, producer):
        """Create chart that adapts to whatever certainty levels exist in the data"""
        
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
        piv = df_filtered.pivot_table(
            index=['Date'], 
            columns='certainty', 
            values='Demand', 
            aggfunc='sum',
            fill_value=0
        ).reset_index()
        
        # Get certainty columns that actually exist in pivot (excluding 'Date')
        actual_certainty_cols = [col for col in piv.columns if col != 'Date']
        
        # Complete color mapping for all possible levels
        all_colors = {
            0: '#F0F0F0',    # Light gray for 0% (planning)
            25: '#87CEEB',   # Sky blue for 25% (potential)  
            50: '#FFE4B5',   # Moccasin for 50% (possible)
            75: '#FFB6C1',   # Light pink for 75% (probable)
            100: '#90EE90'   # Light green for 100% (confirmed)
        }
        
        # Use colors only for levels that exist in this chart
        colors = {level: all_colors[level] for level in actual_certainty_cols if level in all_colors}
        
        # Melt for Altair
        piv_melted = piv.melt(
            id_vars=['Date'], 
            value_vars=actual_certainty_cols,
            var_name='Certainty', 
            value_name='Demand'
        )
        
        # Remove zero demand entries for cleaner visualization
        piv_melted = piv_melted[piv_melted['Demand'] > 0]
        
        if piv_melted.empty:
            st.info(f"ℹ️ No non-zero demand for {producer}")
            return
        
        # Calculate total demand across all included certainty levels
        total_demand = piv[actual_certainty_cols].sum(axis=1)
        
        # Get capacity data for this workcenter
        capacity_data = df_filtered.groupby('Date').agg({
            'Capacity': 'first'
        }).reset_index()
        
        # Merge total demand with capacity
        capacity_data = capacity_data.merge(
            pd.DataFrame({'Date': piv['Date'], 'Total_Demand': total_demand}),
            on='Date', 
            how='left'
        ).fillna(0)
        
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
            title=f"Workcenter Demand: {producer} (Certainty ≥ {selected_certainty}%)",
            width=800,
            height=450
        ).resolve_scale(
            color='independent'
        )
        
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
    
    # Create charts for selected workcenters
    if selected_workcenters and not wf_df_filtered.empty:
        for workcenter in selected_workcenters:
            workcenter_df = wf_df_filtered[wf_df_filtered['Workcenter'] == workcenter]
            if not workcenter_df.empty:
                create_chart_altair(workcenter_df, workcenter)
    else:
        if not selected_workcenters:
            st.warning("⚠️ Please select at least one workcenter to generate time-series charts.")
        elif wf_df_filtered.empty:
            st.warning("⚠️ No data available for the selected workcenters and filters.")

    

else:
    # Show message when no valid data for dashboard
    if not proceed_with_dashboard:
        st.warning("⚠️ Cannot proceed with dashboard - no valid merged data available.")
        st.info("Please check the debug information above to resolve data issues.")
    else:
        st.error("❌ Dashboard data is missing required 'Workcenter' column.")