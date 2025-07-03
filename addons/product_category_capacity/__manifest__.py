# -*- coding: utf-8 -*-
{
    'name': 'Product Category Capacity Management',
    'version': '1.0.0',
    'category': 'Manufacturing',
    'summary': 'Monthly capacity management for product categories',
    'description': """
        This module allows you to define and manage monthly production capacity
        for different product categories. Features include:
        
        - Monthly capacity input per product category
        - Bulk capacity setup wizard
        - Calendar view for capacity planning
        - Analytics and reporting views
        - Integration with manufacturing orders
    """,
    'author': 'Your Company',
    'website': 'https://www.yourcompany.com',
    'depends': ['base', 'product', 'mrp', 'uom'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_category_capacity_views.xml',
        # 'views/capacity_wizard_views.xml',
        # 'views/product_category_views.xml',
    ],
    'demo': [],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}