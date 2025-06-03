{
    "name": "Manufacturing Order Quoted State",
    "version": "18.0.1.0.0",
    "category": "Manufacturing",
    "summary": "Add Quoted state to Manufacturing Orders for capacity planning",
    "description": """
        This module adds a 'Quoted' state to Manufacturing Orders:
        - Quoted state sits between Draft and Confirmed
        - Allows capacity planning without confirming orders
        - Automatically creates quoted sub-MOs for components
        - Can skip quoted state and go directly to confirmed
    """,
    "author": "Your Company",
    "depends": ["mrp"],
    "data": [
        "views/mrp_production_views.xml"
    ],
    "installable": True,
    "application": False,
}