from odoo import models, fields, api
from datetime import timedelta

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'
    
    # Add planned date fields if they don't exist
    date_planned_start = fields.Datetime(
        string='Planned Start Date',
        help='Planned start date for this work order'
    )
    
    date_planned_finished = fields.Datetime(
        string='Planned End Date',
        compute='_compute_date_planned_finished',
        store=True,
        help='Planned end date for this work order'
    )
    
    @api.depends('date_planned_start', 'duration_expected')
    def _compute_date_planned_finished(self):
        """Compute planned end date based on start date and duration"""
        for workorder in self:
            if workorder.date_planned_start and workorder.duration_expected:
                workorder.date_planned_finished = workorder.date_planned_start + timedelta(minutes=workorder.duration_expected)
            else:
                workorder.date_planned_finished = workorder.date_planned_start
    
    @api.model
    def create(self, vals):
        """Set default planned start date from production order if not provided"""
        if 'date_planned_start' not in vals and vals.get('production_id'):
            production = self.env['mrp.production'].browse(vals['production_id'])
            if production.date_start:
                vals['date_planned_start'] = production.date_start
        return super(MrpWorkorder, self).create(vals)