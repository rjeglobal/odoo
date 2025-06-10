{
    'name': 'MRP Workorder Project Status',
    'version': '18.0.1.0.0',
    'category': 'Manufacturing',
    'summary': 'Add Project Number and MO Status to Work Orders',
    'description': """
        This module adds:
        - Project Number field to work orders (from parent MO)
        - MO Status field to work orders
        - Enhanced views with these fields
        - Search and filter capabilities
    """,
    'author': 'Your Company',
    'depends': ['mrp', 'mrp_project_number'],
    'data': [
        'security/ir.model.access.csv',
        'views/mrp_workorder_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}