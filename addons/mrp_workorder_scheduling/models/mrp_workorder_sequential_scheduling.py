# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta
import pytz
from pytz import timezone
import logging

_logger = logging.getLogger(__name__)

def to_utc_naive(dt):
    melbourne_tz = timezone('Australia/Melbourne')
    
    if dt is None:
        return None
        
    if dt.tzinfo is None:
        # Assume naive datetime is Melbourne time, convert to UTC
        dt_melbourne_aware = melbourne_tz.localize(dt)
        dt_utc = dt_melbourne_aware.astimezone(pytz.UTC)
        return dt_utc.replace(tzinfo=None)
    else:
        # Already timezone-aware, convert to UTC naive
        dt_utc = dt.astimezone(pytz.UTC)
        return dt_utc.replace(tzinfo=None)

def from_utc_to_melbourne_naive(dt):
    melbourne_tz = timezone('Australia/Melbourne')
    
    if dt is None:
        return None
        
    if dt.tzinfo is None:
        # Assume stored datetime is UTC naive, convert to Melbourne naive
        dt_utc_aware = pytz.UTC.localize(dt)
        dt_melbourne = dt_utc_aware.astimezone(melbourne_tz)
        return dt_melbourne.replace(tzinfo=None)
    else:
        # Already timezone-aware, convert to Melbourne naive
        dt_melbourne = dt.astimezone(melbourne_tz)
        return dt_melbourne.replace(tzinfo=None)

def melbourne_now():
    melbourne_tz = timezone('Australia/Melbourne')
    now_melbourne = datetime.now(melbourne_tz)
    return now_melbourne.replace(tzinfo=None)

def melbourne_localize(dt):
    if dt is None:
        return None
    melbourne_tz = timezone('Australia/Melbourne')
    if dt.tzinfo is None:
        return melbourne_tz.localize(dt)
    else:
        return dt.astimezone(melbourne_tz)

class MrpWorkorderSequentialScheduling(models.Model):
    _inherit = 'mrp.workorder'

    scheduling_status = fields.Selection([
        ('unscheduled', 'Unscheduled'),
        ('scheduled', 'Scheduled'),
        ('overdue', 'Overdue')
    ], string='Scheduling Status', compute='_compute_scheduling_status', store=True)

    @api.depends('date_planned_start', 'date_planned_finished')
    def _compute_scheduling_status(self):
        melbourne_now_time = melbourne_now()
        for record in self:
            if not record.date_planned_start:
                record.scheduling_status = 'unscheduled'
            elif record.date_planned_start > melbourne_now_time:
                record.scheduling_status = 'scheduled'
            else:
                record.scheduling_status = 'overdue'

    def _get_scheduling_status_color(self):
        for record in self:
            if record.scheduling_status == 'unscheduled':
                return 'grey'
            elif record.scheduling_status == 'scheduled':
                return 'green'
            elif record.scheduling_status == 'overdue':
                return 'red'
        return 'black'

    def button_schedule_sequential(self):
        """Schedule work orders sequentially based on MO date_start"""
        for workorder in self:
            if not workorder.production_id:
                _logger.warning(f"Work order {workorder.name} has no production order")
                continue
                
            if not workorder.workcenter_id:
                _logger.warning(f"Work order {workorder.name} has no work center assigned")
                continue
                
            # Get MO scheduled start date as base
            mo = workorder.production_id
            if not mo.date_start:
                _logger.warning(f"Manufacturing Order {mo.name} has no scheduled start date")
                continue
            
            # Schedule this work order and all related work orders sequentially
            workorder._schedule_mo_workorders()

    def _schedule_mo_workorders(self):
        """Schedule all work orders for this MO sequentially based on MO date_start"""
        mo = self.production_id
        
        # Get all work orders for this MO, sorted by sequence
        workorders = mo.workorder_ids.sorted('sequence')
        
        if not workorders:
            return
            
        # Use MO date_start as base for scheduling
        if not mo.date_start:
            _logger.warning(f"No date_start found for MO {mo.name}")
            return
            
        # Convert MO date_start to Melbourne time for scheduling
        base_start_date = from_utc_to_melbourne_naive(mo.date_start)
        current_start_date = base_start_date
        
        _logger.info(f"Scheduling {len(workorders)} work orders for MO {mo.name} starting from {base_start_date}")
        
        for workorder in workorders:
            # Find next available slot for this work order considering work center capacity
            planned_start = workorder._find_next_available_slot(current_start_date)
            planned_end = workorder._calculate_planned_end_date(planned_start)
            
            # Update planned dates (convert back to UTC for storage)
            workorder.write({
                'date_planned_start': to_utc_naive(planned_start),
                'date_planned_finished': to_utc_naive(planned_end)
            })
            
            _logger.info(f"Scheduled work order {workorder.name}: {planned_start} - {planned_end}")
            
            # Next work order starts after this one finishes (minimum)
            # But may start later if work center is busy
            current_start_date = planned_end

    def _calculate_planned_end_date(self, start_date):
        """Calculate planned end date based on expected duration and work center calendar"""
        if not self.duration_expected:
            # Default to 1 hour if no duration specified
            duration_hours = 1.0
        else:
            duration_hours = self.duration_expected / 60.0
        
        # Check if work center has a calendar (try different possible field names)
        calendar = None
        if self.workcenter_id:
            # Try common calendar field names
            if hasattr(self.workcenter_id, 'calendar_id') and self.workcenter_id.calendar_id:
                calendar = self.workcenter_id.calendar_id
            elif hasattr(self.workcenter_id, 'resource_calendar_id') and self.workcenter_id.resource_calendar_id:
                calendar = self.workcenter_id.resource_calendar_id
            elif hasattr(self.workcenter_id, 'working_time_id') and self.workcenter_id.working_time_id:
                calendar = self.workcenter_id.working_time_id
        
        if calendar:
            # Use work center calendar for accurate scheduling
            # Convert to UTC for calendar calculation
            start_utc = to_utc_naive(start_date)
            
            try:
                # Plan hours using calendar
                end_utc = calendar.plan_hours(
                    duration_hours,
                    start_utc,
                    compute_leaves=True
                )
                
                # Convert back to Melbourne time
                return from_utc_to_melbourne_naive(end_utc)
            except Exception as e:
                _logger.warning(f"Calendar calculation failed for work order {self.name}: {e}")
                # Fallback to simple duration addition
                return start_date + timedelta(hours=duration_hours)
        else:
            # Fallback: simple duration addition
            _logger.info(f"No calendar found for work center {self.workcenter_id.name if self.workcenter_id else 'None'}, using simple duration calculation")
            return start_date + timedelta(hours=duration_hours)

    def _find_next_available_slot(self, earliest_start):
        """Find the next available time slot for this work order considering work center capacity"""
        if not self.workcenter_id:
            _logger.warning(f"No work center assigned to work order {self.name}")
            return earliest_start
        
        # Calculate duration needed
        if not self.duration_expected:
            duration_hours = 1.0
        else:
            duration_hours = self.duration_expected / 60.0
        
        # Start checking from the earliest possible start time
        check_start = earliest_start
        max_iterations = 100  # Prevent infinite loops
        iteration = 0
        
        while iteration < max_iterations:
            check_end = self._calculate_planned_end_date(check_start)
            
            # Check if this time slot is available
            if self._is_time_slot_available(check_start, check_end):
                return check_start
            
            # Find the next conflict and move past it
            next_available = self._find_next_gap_after_conflicts(check_start, check_end)
            check_start = next_available
            
            iteration += 1
        
        _logger.warning(f"Could not find available slot for work order {self.name} after {max_iterations} iterations")
        return earliest_start

    def _is_time_slot_available(self, start_time, end_time):
        """Check if the time slot is available on the work center"""
        if not self.workcenter_id:
            return True
        
        # Convert to UTC for database queries
        start_utc = to_utc_naive(start_time)
        end_utc = to_utc_naive(end_time)
        
        # Check for conflicting work orders on the same work center
        conflicts = self.env['mrp.workorder'].search([
            ('workcenter_id', '=', self.workcenter_id.id),
            ('id', '!=', self.id),  # Exclude current work order
            ('date_planned_start', '!=', False),
            ('date_planned_finished', '!=', False),
            ('state', 'not in', ['done', 'cancel']),  # Only active work orders
            # Check for time overlap
            '|',
            # Conflict case 1: Existing work order starts during our slot
            '&', ('date_planned_start', '>=', start_utc), ('date_planned_start', '<', end_utc),
            '|',
            # Conflict case 2: Existing work order ends during our slot  
            '&', ('date_planned_finished', '>', start_utc), ('date_planned_finished', '<=', end_utc),
            '|',
            # Conflict case 3: Existing work order completely contains our slot
            '&', ('date_planned_start', '<=', start_utc), ('date_planned_finished', '>=', end_utc),
            # Conflict case 4: Our slot completely contains existing work order
            '&', ('date_planned_start', '>=', start_utc), ('date_planned_finished', '<=', end_utc)
        ])
        
        if conflicts:
            conflict_names = ', '.join(conflicts.mapped('name'))
            _logger.info(f"Time slot {start_time} - {end_time} conflicts with work orders: {conflict_names}")
            return False
        
        return True

    def _find_next_gap_after_conflicts(self, start_time, end_time):
        """Find the next available gap after current conflicts"""
        if not self.workcenter_id:
            return end_time
        
        # Convert to UTC for database queries
        start_utc = to_utc_naive(start_time)
        end_utc = to_utc_naive(end_time)
        
        # Get all conflicting work orders sorted by end time
        conflicts = self.env['mrp.workorder'].search([
            ('workcenter_id', '=', self.workcenter_id.id),
            ('id', '!=', self.id),
            ('date_planned_start', '!=', False),
            ('date_planned_finished', '!=', False),
            ('state', 'not in', ['done', 'cancel']),
            ('date_planned_start', '<', end_utc),  # Starts before our end
            ('date_planned_finished', '>', start_utc),  # Ends after our start
        ], order='date_planned_finished desc')
        
        if not conflicts:
            return start_time
        
        # Find the latest ending conflict
        latest_end = conflicts[0].date_planned_finished
        
        # Convert back to Melbourne time and add small buffer
        next_available = from_utc_to_melbourne_naive(latest_end)
        
        # Add a small buffer to avoid scheduling conflicts due to rounding
        next_available += timedelta(minutes=5)
        
        _logger.info(f"Next available slot for work center {self.workcenter_id.name}: {next_available}")
        return next_available

    def _get_workcenter_utilization(self, start_date, end_date):
        """Get work center utilization for a given period"""
        if not self.workcenter_id:
            return 0.0
        
        start_utc = to_utc_naive(start_date)
        end_utc = to_utc_naive(end_date)
        
        scheduled_workorders = self.env['mrp.workorder'].search([
            ('workcenter_id', '=', self.workcenter_id.id),
            ('date_planned_start', '!=', False),
            ('date_planned_finished', '!=', False),
            ('state', 'not in', ['done', 'cancel']),
            ('date_planned_start', '<', end_utc),
            ('date_planned_finished', '>', start_utc),
        ])
        
        total_scheduled_minutes = sum(wo.duration_expected or 60 for wo in scheduled_workorders)
        period_minutes = (end_date - start_date).total_seconds() / 60
        
        if period_minutes > 0:
            utilization = min(100.0, (total_scheduled_minutes / period_minutes) * 100)
        else:
            utilization = 0.0
        
        return utilization

    def action_reschedule_from_mo(self):
        """Action to reschedule all work orders based on current MO date_start"""
        for workorder in self:
            workorder._schedule_mo_workorders()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': f'Work orders rescheduled successfully based on MO start date.',
                'sticky': False,
            }
        }

    # Remove duplicate method since it's now in base file

    def action_check_workcenter_conflicts(self):
        """Check for scheduling conflicts on work centers"""
        conflicts = []
        
        for workorder in self:
            if not workorder.date_planned_start or not workorder.date_planned_finished:
                continue
                
            # Check if current scheduling has conflicts
            if not workorder._is_time_slot_available(
                from_utc_to_melbourne_naive(workorder.date_planned_start),
                from_utc_to_melbourne_naive(workorder.date_planned_finished)
            ):
                conflicts.append(workorder)
        
        if conflicts:
            conflict_names = ', '.join(conflicts.mapped('name'))
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': f'Scheduling conflicts found for work orders: {conflict_names}',
                    'sticky': True,
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'message': 'No scheduling conflicts detected.',
                    'sticky': False,
                }
            }

    def action_resolve_conflicts(self):
        """Automatically resolve scheduling conflicts by rescheduling"""
        for workorder in self:
            if not workorder.date_planned_start or not workorder.date_planned_finished:
                continue
                
            current_start = from_utc_to_melbourne_naive(workorder.date_planned_start)
            current_end = from_utc_to_melbourne_naive(workorder.date_planned_finished)
            
            # Check if there's a conflict
            if not workorder._is_time_slot_available(current_start, current_end):
                # Find next available slot
                new_start = workorder._find_next_available_slot(current_start)
                new_end = workorder._calculate_planned_end_date(new_start)
                
                # Update the work order
                workorder.write({
                    'date_planned_start': to_utc_naive(new_start),
                    'date_planned_finished': to_utc_naive(new_end)
                })
                
                _logger.info(f"Resolved conflict for work order {workorder.name}: moved to {new_start} - {new_end}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': 'Scheduling conflicts resolved.',
                'sticky': False,
            }
        }

    def action_manual_reschedule(self):
        """Open wizard for manual rescheduling"""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Reschedule Work Order',
            'res_model': 'mrp.workorder.reschedule.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_workorder_id': self.id}
        }


class MrpProduction(models.Model):
    _inherit = 'mrp.production'
    
    def write(self, vals):
        """Re-schedule work orders when MO date_start changes"""
        result = super(MrpProduction, self).write(vals)
        
        if 'date_start' in vals:
            for production in self:
                if production.workorder_ids:
                    # Reschedule all work orders when MO start date changes
                    production.workorder_ids[0]._schedule_mo_workorders()
                    _logger.info(f"Rescheduled work orders for MO {production.name} due to date_start change")
        
        return result

    def action_reschedule_all_workorders(self):
        """Action to reschedule all work orders for this MO"""
        if self.workorder_ids:
            self.workorder_ids[0]._schedule_mo_workorders()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': f'All work orders rescheduled for MO {self.name}.',
                'sticky': False,
            }
        }


class MrpWorkorderRescheduleWizard(models.TransientModel):
    _name = 'mrp.workorder.reschedule.wizard'
    _description = 'Work Order Reschedule Wizard'
    
    workorder_id = fields.Many2one('mrp.workorder', string='Work Order', required=True)
    new_start_date = fields.Datetime(string='New Start Date', required=True)
    reschedule_mode = fields.Selection([
        ('this_only', 'This Work Order Only'),
        ('this_and_following', 'This and Following Work Orders'),
        ('all_mo_workorders', 'All Work Orders in MO')
    ], string='Reschedule Mode', default='this_and_following', required=True)
    
    def action_reschedule(self):
        """Execute the rescheduling based on selected mode"""
        workorder = self.workorder_id
        new_start = from_utc_to_melbourne_naive(self.new_start_date)
        
        if self.reschedule_mode == 'this_only':
            # Reschedule only this work order
            planned_end = workorder._calculate_planned_end_date(new_start)
            workorder.write({
                'date_planned_start': to_utc_naive(new_start),
                'date_planned_finished': to_utc_naive(planned_end)
            })
            
        elif self.reschedule_mode == 'this_and_following':
            # Reschedule this and following work orders
            mo = workorder.production_id
            workorders = mo.workorder_ids.sorted('sequence')
            
            # Find current work order position
            current_index = list(workorders).index(workorder)
            following_workorders = workorders[current_index:]
            
            current_start_date = new_start
            for wo in following_workorders:
                planned_end = wo._calculate_planned_end_date(current_start_date)
                wo.write({
                    'date_planned_start': to_utc_naive(current_start_date),
                    'date_planned_finished': to_utc_naive(planned_end)
                })
                current_start_date = planned_end
                
        elif self.reschedule_mode == 'all_mo_workorders':
            # Update MO start date and reschedule all work orders
            workorder.production_id.write({
                'date_start': self.new_start_date
            })
            # The write method on MrpProduction will trigger rescheduling
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': 'Work orders rescheduled successfully.',
                'sticky': False,
            }
        }