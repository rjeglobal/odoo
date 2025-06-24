# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'
    
    date_planned_start = fields.Datetime(
        string='Planned Start Date',
        help='Planned start date for this work order - set by scheduling system or manually'
    )
    
    date_planned_finished = fields.Datetime(
        string='Planned End Date',
        help='Planned end date for this work order - set by scheduling system or manually'
    )
    
    # @api.model
    # def create(self, vals):
        
    #     workorder = super(MrpWorkorder, self).create(vals)
        
    #     _logger.info(f"Created work order {workorder.name} - planned dates controlled by scheduling system or manual entry")
        
    #     return workorder

    @api.model
    def create(self, vals):
        
        workorder = super(MrpWorkorder, self).create(vals)
        workorder.button_schedule_sequential()
        
        return workorder