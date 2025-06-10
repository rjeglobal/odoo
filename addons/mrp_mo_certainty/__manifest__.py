{
    'name': 'MRP Manufacturing Order Certainty',
    'version': '1.0',
    'category': 'Manufacturing',
    'summary': 'Add Certainty field to Manufacturing Orders',
    'description': """
        This module adds a Certainty field to Manufacturing Orders with options:
        - 25%
        - 50%
        - 75%
        - 100%
        
        This can be used to track the probability or confidence level of manufacturing orders.
    """,
    'author': 'Your Company',
    'depends': ['mrp'],
    'data': [
        'views/mrp_production_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}