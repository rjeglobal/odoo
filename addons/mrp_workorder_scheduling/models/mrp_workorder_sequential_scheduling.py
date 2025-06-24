# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import datetime, timedelta
import pytz
from pytz import timezone
import logging

_logger = logging.getLogger(__name__)

def to_utc_naive(dt):
    """Convert Melbourne datetime to UTC naive for proper Odoo storage"""
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
    """Convert UTC naive datetime to Melbourne naive for calculations"""
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
    """Get current time in Melbourne timezone as naive datetime"""
    melbourne_tz = timezone('Australia/Melbourne')
    now_melbourne = datetime.now(melbourne_tz)
    return now_melbourne.replace(tzinfo=None)

def melbourne_localize(dt):
    """Convert naive datetime to Melbourne timezone-aware datetime"""
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
        """Compute scheduling status using Melbourne time"""
        melbourne_now_time = melbourne_now()
        for record in self:
            if not record.date_planned_start:
                record.scheduling_status = 'unscheduled'
            elif record.date_planned_start > melbourne_now_time:
                record.scheduling_status = 'scheduled'
            else:
                record.scheduling_status = 'overdue'

    def button_schedule_sequential(self):
        """Schedule this work order using Melbourne time"""
        if not self.workcenter_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': f'Work order {self.name} has no work center assigned',
                    'sticky': False,
                }
            }

        if not self.workcenter_id.resource_calendar_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': f'Work center {self.workcenter_id.name} has no calendar defined',
                    'sticky': False,
                }
            }

        next_available_time = self._find_next_available_slot(self.workcenter_id)
        if not next_available_time:
            next_available_time = melbourne_localize(melbourne_now())

        duration_minutes = self.duration_expected or 60.0
        start_time, end_time = self._get_next_working_time(
            self.workcenter_id, next_available_time, duration_minutes
        )

        if not start_time or not end_time:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': f'Could not find suitable working time for {self.name}',
                    'sticky': False,
                }
            }

        # Store as UTC naive (Odoo standard) - start_time and end_time are Melbourne naive
        self.date_planned_start = to_utc_naive(start_time)
        self.date_planned_finished = to_utc_naive(end_time)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': f'Work order {self.name} scheduled at {start_time.strftime("%Y-%m-%d %H:%M")} Melbourne time',
                'sticky': False,
            }
        }

    def button_reschedule_dependent(self):
        """Reschedule dependent work orders using Melbourne time"""
        if not self.workcenter_id or not self.date_planned_finished:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': 'Cannot reschedule: missing work center or end date',
                    'sticky': False,
                }
            }

        dependent_workorders = self.search([
            ('workcenter_id', '=', self.workcenter_id.id),
            ('date_planned_start', '>=', self.date_planned_start),
            ('id', '!=', self.id),
            ('state', 'not in', ['done', 'cancel'])
        ], order='date_planned_start asc')

        count = 0
        # Convert to Melbourne timezone-aware for calculations
        current_end_time = melbourne_localize(self.date_planned_finished) + timedelta(minutes=15)
        
        for workorder in dependent_workorders:
            planned_start = melbourne_localize(workorder.date_planned_start)
                
            if planned_start < current_end_time:
                duration_minutes = workorder.duration_expected or 60.0
                
                # Find next working time slot
                new_start, new_end = workorder._get_next_working_time(
                    workorder.workcenter_id, current_end_time, duration_minutes
                )
                
                if new_start and new_end:
                    workorder.date_planned_start = to_utc_naive(new_start)
                    workorder.date_planned_finished = to_utc_naive(new_end)
                    count += 1
                    current_end_time = new_end + timedelta(minutes=15)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': f'Rescheduled {count} dependent work orders',
                'sticky': False,
            }
        }

    def _get_next_working_time(self, workcenter, start_datetime, duration_minutes):
        """Find working time using Melbourne naive timezone throughout"""
        calendar = workcenter.resource_calendar_id
        melbourne_tz = pytz.timezone('Australia/Melbourne')

        if not calendar:
            _logger.error(f"No calendar found for {workcenter.name}")
            return None, None

        _logger.info(f"Searching for {duration_minutes} minute slot for {workcenter.name} starting from {start_datetime}")

        # Convert everything to Melbourne naive time
        if isinstance(start_datetime, str):
            start_dt = fields.Datetime.from_string(start_datetime)
        else:
            start_dt = start_datetime
            
        # If timezone-aware, convert to Melbourne naive
        if start_dt.tzinfo is not None:
            start_dt = start_dt.astimezone(melbourne_tz).replace(tzinfo=None)

        # Never schedule in the past (Melbourne naive time)
        now_melbourne_naive = melbourne_now()
        if start_dt < now_melbourne_naive:
            start_dt = now_melbourne_naive
            _logger.info(f"Adjusted start time to Melbourne now: {start_dt}")

        # Convert back to timezone-aware for calendar API
        start_dt_aware = melbourne_localize(start_dt)

        search_weeks = 1
        while search_weeks <= 52:  # Maximum 1 year search
            search_end_aware = start_dt_aware + timedelta(weeks=search_weeks)
            
            try:
                # Get working intervals (calendar API needs timezone-aware)
                intervals = calendar._work_intervals_batch(start_dt_aware, search_end_aware)[False]
                _logger.info(f"Found {len(intervals)} working intervals for {workcenter.name} in {search_weeks} weeks")
                
                # Try to find a single interval that can fit the entire job
                for interval_start, interval_end, _attendances in intervals:
                    # Convert calendar intervals to Melbourne naive
                    interval_start_naive = interval_start.astimezone(melbourne_tz).replace(tzinfo=None)
                    interval_end_naive = interval_end.astimezone(melbourne_tz).replace(tzinfo=None)
                    
                    # Skip past intervals
                    if interval_end_naive <= now_melbourne_naive:
                        continue
                    
                    # Ensure we don't start in the past
                    actual_start_naive = max(interval_start_naive, start_dt, now_melbourne_naive)
                    
                    if actual_start_naive >= interval_end_naive:
                        continue

                    # Check if the entire job fits in this interval
                    job_end_time_naive = actual_start_naive + timedelta(minutes=duration_minutes)
                    if job_end_time_naive <= interval_end_naive:
                        # Check for overlapping work orders (all times stored as Melbourne naive)
                        overlapping_wos = self.env['mrp.workorder'].search([
                            ('workcenter_id', '=', workcenter.id),
                            ('date_planned_start', '<', job_end_time_naive),
                            ('date_planned_finished', '>', actual_start_naive),
                            ('date_planned_finished', '>', now_melbourne_naive),
                            ('id', '!=', self.id),
                            ('state', 'not in', ['done', 'cancel'])
                        ])

                        if not overlapping_wos:
                            _logger.info(f"SUCCESS: Scheduled {workcenter.name} in single interval: {actual_start_naive} to {job_end_time_naive}")
                            return actual_start_naive, job_end_time_naive

                # If single interval doesn't work, try spanning intervals
                job_start_time_naive = None
                current_time_naive = start_dt
                accumulated_minutes = 0

                for interval_start, interval_end, _attendances in intervals:
                    # Convert calendar intervals to Melbourne naive
                    interval_start_naive = interval_start.astimezone(melbourne_tz).replace(tzinfo=None)
                    interval_end_naive = interval_end.astimezone(melbourne_tz).replace(tzinfo=None)
                    
                    # Skip past intervals
                    if interval_end_naive <= now_melbourne_naive:
                        continue
                    
                    # Ensure we don't start in the past
                    actual_start_naive = max(interval_start_naive, current_time_naive, now_melbourne_naive)
                    
                    if actual_start_naive >= interval_end_naive:
                        continue

                    # Check for overlapping work orders (all times stored as Melbourne naive)
                    overlapping_wos = self.env['mrp.workorder'].search([
                        ('workcenter_id', '=', workcenter.id),
                        ('date_planned_start', '<', interval_end_naive),
                        ('date_planned_finished', '>', actual_start_naive),
                        ('date_planned_finished', '>', now_melbourne_naive),
                        ('id', '!=', self.id),
                        ('state', 'not in', ['done', 'cancel'])
                    ])

                    if overlapping_wos:
                        # Find gaps between work orders
                        sorted_wos = overlapping_wos.sorted('date_planned_start')
                        gap_start_naive = actual_start_naive
                        
                        for wo in sorted_wos:
                            # Work order dates are stored as Melbourne naive (GMT+10)
                            wo_start_naive = wo.date_planned_start
                            wo_end_naive = wo.date_planned_finished
                            
                            # Skip past work orders
                            if wo_end_naive <= now_melbourne_naive:
                                continue
                            
                            # Check gap before this work order
                            if gap_start_naive < wo_start_naive:
                                gap_end_naive = min(wo_start_naive, interval_end_naive)
                                gap_minutes = (gap_end_naive - gap_start_naive).total_seconds() / 60.0
                                
                                if gap_minutes > 0:
                                    if job_start_time_naive is None:
                                        job_start_time_naive = gap_start_naive
                                    
                                    accumulated_minutes += gap_minutes
                                    
                                    if accumulated_minutes >= duration_minutes:
                                        job_end_time_naive = job_start_time_naive + timedelta(minutes=duration_minutes)
                                        _logger.info(f"SUCCESS: Scheduled {workcenter.name} spanning intervals: {job_start_time_naive} to {job_end_time_naive}")
                                        return job_start_time_naive, job_end_time_naive
                            
                            gap_start_naive = max(wo_end_naive + timedelta(minutes=15), now_melbourne_naive)
                        
                        # Check gap after all work orders
                        if gap_start_naive < interval_end_naive:
                            gap_minutes = (interval_end_naive - gap_start_naive).total_seconds() / 60.0
                            if gap_minutes > 0:
                                if job_start_time_naive is None:
                                    job_start_time_naive = gap_start_naive
                                
                                accumulated_minutes += gap_minutes
                                
                                if accumulated_minutes >= duration_minutes:
                                    job_end_time_naive = job_start_time_naive + timedelta(minutes=duration_minutes)
                                    _logger.info(f"SUCCESS: Scheduled {workcenter.name} spanning intervals: {job_start_time_naive} to {job_end_time_naive}")
                                    return job_start_time_naive, job_end_time_naive
                    else:
                        # No overlapping work orders
                        available_minutes = (interval_end_naive - actual_start_naive).total_seconds() / 60.0
                        
                        if available_minutes > 0:
                            if job_start_time_naive is None:
                                job_start_time_naive = actual_start_naive
                            
                            accumulated_minutes += available_minutes
                            
                            if accumulated_minutes >= duration_minutes:
                                job_end_time_naive = job_start_time_naive + timedelta(minutes=duration_minutes)
                                _logger.info(f"SUCCESS: Scheduled {workcenter.name} spanning intervals: {job_start_time_naive} to {job_end_time_naive}")
                                return job_start_time_naive, job_end_time_naive
                    
                    current_time_naive = max(interval_end_naive + timedelta(minutes=1), now_melbourne_naive)

                # Expand search if needed
                search_weeks *= 2
                _logger.info(f"Need {duration_minutes} minutes, found {accumulated_minutes:.1f} minutes for {workcenter.name}, expanding search to {search_weeks} weeks")

            except Exception as e:
                _logger.error(f"Calendar scheduling failed for {workcenter.name}: {e}")
                import traceback
                _logger.error(traceback.format_exc())
                break

        _logger.error(f"FAILED: Could not find {duration_minutes} minutes of working time for {workcenter.name}")
        return None, None

    def _find_next_available_slot(self, workcenter, after_datetime=None):
        """Find next available slot in Melbourne time"""
        melbourne_tz = timezone('Australia/Melbourne')
        now_melbourne = datetime.now(melbourne_tz)
        
        if not after_datetime:
            after_datetime = now_melbourne
        else:
            if isinstance(after_datetime, str):
                after_datetime = fields.Datetime.from_string(after_datetime)
            if after_datetime.tzinfo is None:
                after_datetime = melbourne_localize(after_datetime)
        
        # Never search in the past
        after_datetime = max(after_datetime, now_melbourne)
        
        calendar = workcenter.resource_calendar_id
        if not calendar:
            return None

        # Get future work orders only (all stored as Melbourne naive)
        context_ids = self._context.get('active_ids', [])
        scheduled_workorders = self.search([
            ('workcenter_id', '=', workcenter.id),
            ('date_planned_start', '!=', False),
            ('date_planned_finished', '!=', False),
            ('date_planned_finished', '>', melbourne_now()),  # Only future work orders
            ('state', 'not in', ['done', 'cancel']),
            ('id', 'not in', context_ids)
        ], order='date_planned_finished desc', limit=1)

        if scheduled_workorders:
            # Work orders are stored as Melbourne naive, convert to timezone-aware for calculation
            latest_end = melbourne_localize(scheduled_workorders[0].date_planned_finished)
            next_slot = max(latest_end + timedelta(minutes=15), now_melbourne)
        else:
            next_slot = now_melbourne

        # Convert next_slot to naive for comparison
        next_slot_naive = next_slot.replace(tzinfo=None)
        
        search_weeks = 1
        while search_weeks <= 52:  # Maximum 1 year search
            search_end = next_slot + timedelta(weeks=search_weeks)

            try:
                intervals = calendar._work_intervals_batch(next_slot, search_end)[False]

                for interval_start, interval_end, _attendances in intervals:
                    # Convert calendar intervals to Melbourne naive
                    interval_start_naive = interval_start.astimezone(melbourne_tz).replace(tzinfo=None)
                    interval_end_naive = interval_end.astimezone(melbourne_tz).replace(tzinfo=None)
                    
                    # Skip past intervals
                    if interval_end_naive <= now_melbourne_naive:
                        continue
                    
                    effective_start_naive = max(interval_start_naive, next_slot_naive, now_melbourne_naive)
                    
                    if effective_start_naive >= interval_end_naive:
                        continue
                    
                    if effective_start_naive >= next_slot_naive:
                        # Check for overlaps (all times stored as Melbourne naive GMT+10)
                        overlapping_wos = self.env['mrp.workorder'].search([
                            ('workcenter_id', '=', workcenter.id),
                            ('date_planned_start', '<', interval_end_naive),
                            ('date_planned_finished', '>', effective_start_naive),
                            ('date_planned_finished', '>', melbourne_now()),
                            ('state', 'not in', ['done', 'cancel'])
                        ])
                        
                        if not overlapping_wos:
                            _logger.info(f"Next available slot for {workcenter.name}: {effective_start_naive}")
                            return effective_start_naive

                # Expand search
                search_weeks *= 2
                _logger.info(f"Expanding slot search for {workcenter.name} to {search_weeks} weeks")

            except Exception as e:
                _logger.error(f"Calendar slot finding failed for {workcenter.name}: {e}")
                break

        _logger.warning(f"No working time slots available for {workcenter.name} in {search_weeks} weeks")
        return None

    @api.model
    def action_schedule_selected_workorders(self):
        """Schedule selected work orders using Melbourne time"""
        if not self._context.get('active_ids'):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'message': 'Please select work orders to schedule',
                    'sticky': False,
                }
            }

        workorders = self.browse(self._context['active_ids'])
        to_schedule = workorders.filtered(lambda w: w.state not in ['done', 'cancel'])

        if not to_schedule:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'info',
                    'message': 'No schedulable work orders found',
                    'sticky': False,
                }
            }

        scheduled_count = 0
        failed_count = 0
        workcenters = to_schedule.mapped('workcenter_id').filtered(lambda wc: wc)

        _logger.info(f"Starting to schedule {len(to_schedule)} work orders across {len(workcenters)} work centers")

        for workcenter in workcenters:
            _logger.info(f"Processing work center: {workcenter.name}")
            
            if not workcenter.resource_calendar_id:
                failed_wo_count = len(to_schedule.filtered(lambda w: w.workcenter_id == workcenter))
                failed_count += failed_wo_count
                _logger.warning(f"Skipping {failed_wo_count} work orders at {workcenter.name} - no calendar")
                continue

            wc_workorders = to_schedule.filtered(lambda w: w.workcenter_id == workcenter)
            
            # Clear existing schedules
            _logger.info(f"Clearing and rescheduling {len(wc_workorders)} work orders at {workcenter.name}")
            wc_workorders.write({
                'date_planned_start': False,
                'date_planned_finished': False,
            })
            
            # Sort by MO number
            wc_workorders_sorted = []
            for wo in wc_workorders:
                mo_name = wo.production_id.name if wo.production_id else wo.name
                wc_workorders_sorted.append((mo_name, wo))
            wc_workorders_sorted.sort(key=lambda x: x[0])
            sorted_workorders = [item[1] for item in wc_workorders_sorted]

            # Start from Melbourne current time (naive)
            current_slot_time = melbourne_now()
            _logger.info(f"Starting scheduling from: {current_slot_time} Melbourne time")

            for workorder in sorted_workorders:
                duration_minutes = workorder.duration_expected or 60.0
                _logger.info(f"Scheduling {workorder.name} (duration: {duration_minutes} minutes)")
                
                start_time, end_time = workorder._get_next_working_time(
                    workcenter, current_slot_time, duration_minutes
                )
                
                if start_time and end_time:
                    # Store as UTC naive (Odoo standard) - start_time and end_time are Melbourne naive
                    workorder.date_planned_start = to_utc_naive(start_time)
                    workorder.date_planned_finished = to_utc_naive(end_time)
                    
                    current_slot_time = end_time + timedelta(minutes=15)
                    scheduled_count += 1
                    
                    _logger.info(f"SUCCESS: Scheduled {workorder.name} (MO: {workorder.production_id.name if workorder.production_id else 'N/A'}) "
                               f"at {workcenter.name} from {start_time} to {end_time} Melbourne time")
                else:
                    failed_count += 1
                    _logger.error(f"FAILED: Could not schedule {workorder.name} - no working time available")

        _logger.info(f"Scheduling complete: {scheduled_count} scheduled, {failed_count} failed")

        message_parts = []
        if scheduled_count > 0:
            message_parts.append(f"Scheduled {scheduled_count} work orders")
        if failed_count > 0:
            message_parts.append(f"Failed to schedule {failed_count} work orders")

        if message_parts:
            message = " and ".join(message_parts) + f" across {len(workcenters)} work centers (Melbourne time)"
        else:
            message = "No work orders were processed"

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if failed_count == 0 else 'warning',
                'message': message,
                'sticky': False,
            }
        }