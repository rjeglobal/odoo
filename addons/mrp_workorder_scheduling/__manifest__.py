{
    'name': 'MRP Work Order Scheduling',
    'version': '1.0',
    'category': 'Manufacturing',
    'summary': 'Add scheduling dates and views to work orders',
    'description': """
        This module adds:
        - Planned start and end dates to work orders
        - Calendar view for work orders
        - Proper date propagation from MOs
    """,
    'author': 'Your Company',
    'depends': ['mrp', 'mrp_quoted_state'],
    'data': [
        'views/mrp_workorder_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}