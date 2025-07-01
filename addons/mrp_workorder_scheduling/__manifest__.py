{
    'name': 'MRP Work Order Scheduling',
    'version': '1.0',
    'category': 'Manufacturing',
    'summary': 'Add scheduling dates and views to work orders',
    'description': """
        Work Order Scheduling
        ==========================
        
        This module provides basic work order scheduling functionality using MO start dates:
        
        Features:
        * Calendar view showing work orders based on MO start dates
        * Pivot analysis view for workload analysis grouped by work centers
        * Work orders automatically use their MO's start date for scheduling
        * No additional date fields - uses existing MO date_start
        
        Views:
        * Calendar view for visual scheduling (grouped by work centers)
        * Pivot view for workload analysis (work centers vs time periods)
        * Uses standard Odoo work order fields with MO date_start
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