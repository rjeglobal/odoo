from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'
    
    # Add project number field if it doesn't exist
    project_number = fields.Char(
        string='Project Number',
        copy=True,
        tracking=True,
        help='Project number for this manufacturing order'
    )
    
    @api.model
    def create(self, vals):
        """Override to ensure project number is propagated"""
        production = super(MrpProduction, self).create(vals)
        # If work orders already exist, update their project numbers
        if production.workorder_ids and production.project_number:
            production.workorder_ids.invalidate_recordset(['project_number'])
        return production
    
    def write(self, vals):
        """Override to update work order project numbers when MO project changes"""
        res = super(MrpProduction, self).write(vals)
        if 'project_number' in vals:
            for production in self:
                if production.workorder_ids:
                    # Trigger recomputation of related field
                    production.workorder_ids.invalidate_recordset(['project_number'])
        return res