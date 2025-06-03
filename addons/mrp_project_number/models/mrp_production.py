from odoo import models, fields

class MrpProduction(models.Model):
    _inherit = 'mrp.production'
    
    project_number = fields.Char(
        string='Project Number',
        help='Enter the project number associated with this manufacturing order',
        copy=False,
        tracking=True,
    )