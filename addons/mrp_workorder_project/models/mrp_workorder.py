from odoo import models, fields, api

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'
    
    # Add project number field from parent MO
    project_number = fields.Char(
        string='Project Number',
        related='production_id.project_number',
        store=True,
        readonly=True,
        help='Project number from the parent Manufacturing Order'
    )
    
    # Add MO status field
    mo_state = fields.Selection(
        string='MO Status',
        related='production_id.state',
        store=True,
        readonly=True,
        help='Current status of the parent Manufacturing Order'
    )
    
    # User-friendly display of MO status
    mo_state_display = fields.Char(
        string='MO Status Display',
        compute='_compute_mo_state_display',
        store=True
    )
    
    @api.depends('mo_state')
    def _compute_mo_state_display(self):
        """Compute user-friendly MO status display"""
        state_dict = {
            'draft': 'Draft',
            'quoted': 'Quoted',
            'confirmed': 'Confirmed', 
            'progress': 'In Progress',
            'to_close': 'To Close',
            'done': 'Done',
            'cancel': 'Cancelled'
        }
        for workorder in self:
            workorder.mo_state_display = state_dict.get(workorder.mo_state, workorder.mo_state or '')