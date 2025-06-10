import streamlit as st
import xmlrpc.client
import pandas as pd

st.set_page_config(
    page_title="Odoo Manufacturing Dashboard",
    page_icon=":factory:",
    layout="wide"
)
st.title('Odoo Manufacturing Dashboard')

# @st.cache_data
def connect_odoo():
    url = 'http://localhost:8069' 
    db = 'rje'
    username = 'admin'
    password = 'admin'
    
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, username, password, {})
    models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
    
    # st.success("✅ Connected to Odoo")
    return models, db, uid, password

# # @st.cache_data
def fetch_odoo_data(model_name, fields=None, domain=None):
    models, db, uid, password = connect_odoo()
    
    # Search and read records
    ids = models.execute_kw(db, uid, password, model_name, 'search', [domain or []])
    records = models.execute_kw(db, uid, password, model_name, 'read', [ids], {'fields': fields})
    
    df = pd.DataFrame(records)

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

manufacturing_orders = fetch_odoo_data(
    'mrp.production',
    fields=['id', 'date_start' ,'name', 'project_number', 'origin', 'state', 'certainty', 'product_id', 'product_qty'],
    domain=[('state', '!=', 'cancel')]
)  

work_orders = fetch_odoo_data(
    'mrp.workorder',
    fields=['id', 'name', 'workcenter_id', 'production_id', 'project_number', 'mo_state_display'],
    domain=[('state', '!=', 'cancel')]
)

st.dataframe(manufacturing_orders)
st.dataframe(work_orders)

def clean_odoo_data(records):
    """Clean and format Odoo data for Streamlit display"""
    if not records:
        return pd.DataFrame()
    
    df = pd.DataFrame(records)
    
    # Handle Many2one fields and mixed data types
    for col in df.columns:
        if df[col].dtype == 'object':
            # Convert Many2one fields (tuples/lists) to strings
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

@st.cache_data(ttl=300)  # Cache for 5 minutes
def fetch_odoo_data(model_name, fields=None, domain=None):
    models, db, uid, password = connect_odoo()
    
    if not models:
        return []
    
    try:
        # Search and read records
        ids = models.execute_kw(db, uid, password, model_name, 'search', [domain or []])
        if not ids:
            return []
        
        records = models.execute_kw(db, uid, password, model_name, 'read', [ids], {'fields': fields})
        return records
    except Exception as e:
        st.error(f"Error fetching {model_name}: {str(e)}")
        return []


# Test connection first
with st.spinner("Connecting to Odoo..."):
    models, db, uid, password = connect_odoo()

if not models:
    st.error("❌ Cannot connect to Odoo")
    st.stop()

st.success("✅ Connected to Odoo")

# Manufacturing Orders
st.subheader("📋 Manufacturing Orders")
manufacturing_data = fetch_odoo_data(
    'mrp.production',
    fields=['id', 'name', 'project_number', 'state', 'product_id', 'product_qty'],
    domain=[('state', '!=', 'cancel')]
)

if manufacturing_data:
    manufacturing_orders = clean_odoo_data(manufacturing_data)
    st.dataframe(manufacturing_orders, use_container_width=True)
else:
    st.info("No manufacturing orders found")

# Work Orders
st.subheader("⚙️ Work Orders")
work_orders_data = fetch_odoo_data(
    'mrp.workorder',
    fields=['id', 'name', 'state', 'production_id', 'workcenter_id'],
    domain=[('state', '!=', 'cancel')]
)

if work_orders_data:
    work_orders = clean_odoo_data(work_orders_data)
    st.dataframe(work_orders, use_container_width=True)
else:
    st.info("No work orders found")

# Add some metrics
if manufacturing_data:
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_orders = len(manufacturing_data)
        st.metric("Total Manufacturing Orders", total_orders)
    
    with col2:
        confirmed = len([r for r in manufacturing_data if r.get('state') == 'confirmed'])
        st.metric("Confirmed Orders", confirmed)
    
    with col3:
        in_progress = len([r for r in manufacturing_data if r.get('state') == 'progress'])
        st.metric("In Progress", in_progress)