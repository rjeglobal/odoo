# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)

class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    mo_date_start = fields.Datetime(
        string='MO Start Date',
        related='production_id.date_start',
        store=True,
        help='Start date from the related Manufacturing Order'
    )

    def action_reschedule_from_mo(self):
        """Action for manual rescheduling (mainly for UI purposes)"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'info',
                'message': 'Work orders use MO start date for scheduling.',
                'sticky': False,
            }
        }