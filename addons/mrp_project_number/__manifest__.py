{
    'name': 'MRP Project Number',
    'version': '1.0',
    'category': 'Manufacturing',
    'summary': 'Add Project Number field to Manufacturing Orders',
    'description': """
        Simple module that adds a Project Number field to Manufacturing Orders.
        Users can manually enter project numbers for tracking purposes.
    """,
    'author': 'Your Company',
    'depends': ['mrp'],
    'data': [
        'views/mrp_production_views.xml',
    ],
    'installable': True,
    'auto_install': False,
}