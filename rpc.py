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
    fields=['id', 'date_start' ,'name', 'project_number', 'origin', 'state', 'certainty', 'product_id', 'product_qty', 'certainty'],
    domain=[('state', '!=', 'cancel')]
)  

work_orders = fetch_odoo_data(
    'mrp.workorder',
    fields=['id', 'name', 'workcenter_id', 'production_id', 'project_number', 'mo_state_display', 'mo_date_start', 'state'],
    domain=[('state', '!=', 'cancel')]
)

workcenters = fetch_odoo_data(
    'mrp.workcenter',
    fields=['id', 'name', 'code', 'company_id'],
    domain=[('active', '=', True)]
)

st.dataframe(manufacturing_orders)
st.dataframe(work_orders)
st.dataframe(workcenters)

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


