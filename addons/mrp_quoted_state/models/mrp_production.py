from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta

class MrpProduction(models.Model):
    _inherit = 'mrp.production'
    
    # Override the state field completely to control the order
    state = fields.Selection([
        ('draft', 'Draft'),
        ('quoted', 'Quoted'),  
        ('confirmed', 'Confirmed'),
        ('progress', 'In Progress'),
        ('to_close', 'To Close'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')
    ], string='State', copy=False, default='draft', tracking=True,
    help="* Draft: The MO is not confirmed yet.\n"
         "* Quoted: The MO is quoted for capacity planning.\n"
         "* Confirmed: The MO is confirmed.\n"
         "* In Progress: The production has started.\n"
         "* To Close: The production is done but still needs to be closed.\n"
         "* Done: The production is done.\n"
         "* Cancelled: The MO has been cancelled.")
    
    # Add field to track if this is a quoted sub-MO
    is_quoted_child = fields.Boolean(
        string='Is Quoted Child MO',
        copy=False,
        help='Indicates if this MO was created as a quoted sub-MO'
    )
    
    # Add field to track parent MO (renamed to be more generic)
    parent_production_id = fields.Many2one(
        'mrp.production',
        string='Parent Manufacturing Order',
        copy=False,
        help='The parent MO that created this sub-MO'
    )
    
    # Add field to track child MOs (renamed to be more generic)
    child_production_ids = fields.One2many(
        'mrp.production',
        'parent_production_id',
        string='Sub Manufacturing Orders',
        copy=False
    )
    
    def action_quote(self):
        """
        Move MO from Draft to Quoted state and create quoted sub-MOs
        """
        if self.filtered(lambda mo: mo.state not in ['draft']):
            raise UserError(_('Only draft manufacturing orders can be quoted.'))
        
        for production in self:
            # Set to quoted state
            production.state = 'quoted'
            
            # Generate work orders for this MO if it has operations
            if production.bom_id and production.bom_id.operation_ids:
                production._generate_work_orders()
            
            # Create sub-MOs in quoted state
            production._create_quoted_sub_mos()
            
            # Log the action
            production.message_post(
                body=_('Manufacturing Order has been quoted.')
            )
        
        return True
    
    def update_child_project_numbers(self):
        """
        Update project numbers on all child MOs that don't have one
        This can be called manually or via server action
        """
        for production in self:
            if production.project_number:
                # Find all child MOs without project number
                child_mos = self.search([
                    '|',
                    ('parent_production_id', '=', production.id),
                    ('origin', '=', production.name),
                    ('project_number', '=', False)
                ])
                
                if child_mos:
                    child_mos.write({'project_number': production.project_number})
                    production.message_post(
                        body=_('Updated project number on %d child MO(s)') % len(child_mos)
                    )
        
        return True
    
    def write(self, vals):
        """
        Override write to propagate project number changes to children
        """
        res = super(MrpProduction, self).write(vals)
        
        # If project number is updated, update all child MOs
        if 'project_number' in vals:
            for production in self:
                if production.project_number:
                    # Update direct children
                    if production.child_production_ids:
                        production.child_production_ids.write({
                            'project_number': production.project_number
                        })
                    
                    # Update children found by origin
                    origin_children = self.search([
                        ('origin', '=', production.name),
                        ('id', '!=', production.id)
                    ])
                    if origin_children:
                        origin_children.write({
                            'project_number': production.project_number
                        })
        
        return res
    
    def reschedule_work_orders(self):
        """
        Reschedule work orders based on current MO state
        Can be called manually via server action
        """
        for production in self:
            if production.workorder_ids and production.bom_id:
                # Delete existing work orders
                production.workorder_ids.unlink()
                
                # Regenerate based on state
                production._generate_work_orders()
                
                production.message_post(
                    body=_('Work orders rescheduled using %s scheduling') % 
                    ('simple' if production.state == 'quoted' else 'sequential')
                )
        
        return True
    
    def _create_quoted_sub_mos(self):
        """
        Create sub-MOs for manufactured components in quoted state
        """
        self.ensure_one()
        
        if not self.bom_id:
            return
            
        # Get all BOM lines that are manufactured products
        for line in self.bom_id.bom_line_ids:
            if line.product_id.bom_ids and line.product_id.type in ['product', 'consu']:
                # Calculate required quantity
                qty_to_produce = (line.product_qty / self.bom_id.product_qty) * self.product_qty
                
                # Find the BOM for this component
                bom = self.env['mrp.bom']._bom_find(
                    line.product_id,
                    bom_type='normal',
                    company_id=self.company_id.id
                )[line.product_id]
                
                if bom:
                    # Create the sub-MO
                    sub_mo_vals = {
                        'product_id': line.product_id.id,
                        'product_qty': qty_to_produce,
                        'product_uom_id': line.product_uom_id.id,
                        'bom_id': bom.id,
                        'date_start': self.date_start,
                        'date_deadline': self.date_start,
                        'origin': self.name,
                        'state': 'quoted',
                        'is_quoted_child': True,
                        'parent_production_id': self.id,  # Link to parent
                        'company_id': self.company_id.id,
                        'project_number': self.project_number,  # Copy project number from parent
                    }
                    
                    sub_mo = self.create(sub_mo_vals)
                    
                    # Generate work orders for the sub-MO if it has operations
                    if sub_mo.bom_id.operation_ids:
                        sub_mo._generate_work_orders()
                    
                    # Recursively create quoted sub-MOs for the sub-MO
                    sub_mo._create_quoted_sub_mos()
    
    def _generate_work_orders(self):
        """
        Generate work orders for MOs based on BOM operations
        - For quoted MOs: Simple scheduling (all start at same time)
        - For confirmed MOs: Sequential scheduling
        """
        self.ensure_one()
        
        if not self.bom_id or not self.bom_id.operation_ids:
            return
        
        # Determine scheduling method based on MO state
        if self.state == 'quoted':
            self._generate_work_orders_simple()
        else:
            self._generate_work_orders_sequential()
    
    def _generate_work_orders_simple(self):
        """
        Generate work orders with simple scheduling (all start at same time)
        Used for quoted MOs for capacity planning
        """
        self.ensure_one()
        
        # Use MO's start date for all work orders
        wo_date_start = self.date_start or fields.Datetime.now()
        
        # Create work orders for each operation in the BOM
        for operation in self.bom_id.operation_ids:
            # Calculate duration based on quantity
            duration_expected = operation.time_cycle * self.product_qty
            
            wo_vals = {
                'name': operation.name,
                'production_id': self.id,
                'product_id': self.product_id.id,
                'product_uom_id': self.product_uom_id.id,
                'operation_id': operation.id,
                'workcenter_id': operation.workcenter_id.id,
                'duration_expected': duration_expected,
                # 'date_planned_start': wo_date_start,
                # 'date_planned_finished': wo_date_start + timedelta(minutes=duration_expected),
                'state': 'pending',
                'company_id': self.company_id.id,
            }
            
            self.env['mrp.workorder'].create(wo_vals)
    
    def _generate_work_orders_sequential(self):
        """
        Generate work orders with sequential scheduling
        Each operation starts after the previous one finishes
        """
        self.ensure_one()
        
        # Start scheduling from MO's start date
        current_date = self.date_start or fields.Datetime.now()
        
        # Create work orders for each operation in sequence
        for sequence, operation in enumerate(self.bom_id.operation_ids.sorted('sequence')):
            # Calculate duration for this operation
            duration_expected = operation.time_cycle * self.product_qty
            
            # Calculate end date for this work order
            date_finished = current_date + timedelta(minutes=duration_expected)
            
            wo_vals = {
                'name': operation.name,
                'production_id': self.id,
                'product_id': self.product_id.id,
                'product_uom_id': self.product_uom_id.id,
                'operation_id': operation.id,
                'workcenter_id': operation.workcenter_id.id,
                'duration_expected': duration_expected,
                # 'date_planned_start': current_date,
                # 'date_planned_finished': date_finished,
                'state': 'pending',
                'company_id': self.company_id.id,
            }
            
            self.env['mrp.workorder'].create(wo_vals)
            
            # Next operation starts when this one ends
            current_date = date_finished
        
        # Update MO's deadline based on last work order
        if self.workorder_ids and hasattr(self, 'date_deadline'):
            self.date_deadline = date_finished
    
    def action_confirm(self):
        """
        Override to handle both draft->confirmed and quoted->confirmed transitions
        """
        # Filter records by their current state
        draft_orders = self.filtered(lambda mo: mo.state == 'draft')
        quoted_orders = self.filtered(lambda mo: mo.state == 'quoted')
        
        # For draft orders going directly to confirmed, use standard behavior
        if draft_orders:
            # Ensure project number is propagated to child MOs created during confirmation
            for order in draft_orders:
                if order.project_number:
                    # Store project number to propagate after confirmation
                    order = order.with_context(parent_project_number=order.project_number)
            super(MrpProduction, draft_orders).action_confirm()
        
        # For quoted orders, we need special handling
        if quoted_orders:
            for production in quoted_orders:
                # Delete existing work orders (they were created with simple scheduling)
                if production.workorder_ids:
                    production.workorder_ids.unlink()
                
                # Confirm all child quoted MOs first
                if production.child_production_ids:
                    production.child_production_ids.filtered(
                        lambda mo: mo.state == 'quoted'
                    ).action_confirm()
            
            # Then confirm the quoted orders using standard behavior
            # But first temporarily set them to draft so the standard method works
            quoted_orders.write({'state': 'draft'})
            result = super(MrpProduction, quoted_orders).action_confirm()
            
            # Regenerate work orders with sequential scheduling
            for production in quoted_orders:
                if production.bom_id and production.bom_id.operation_ids:
                    production._generate_work_orders_sequential()
            
            return result
        
        return True
    
    def action_cancel(self):
        """
        Override to handle cancellation of MOs and ALL their children (regardless of how they were created)
        """
        # Cancel all child MOs first
        for production in self:
            # Method 1: Check using the parent-child relationship
            child_mos = production.child_production_ids.filtered(
                lambda mo: mo.state not in ['done', 'cancel']
            )
            
            # Method 2: Search for MOs where origin contains this MO's name
            # This catches MOs created through standard MRP processes
            origin_child_mos = self.search([
                '|',
                ('origin', '=', production.name),
                ('origin', 'ilike', production.name + ','),  # For multiple origins
                ('state', 'not in', ['done', 'cancel']),
                ('id', '!=', production.id)  # Exclude self
            ])
            
            # Combine both sets of child MOs
            all_child_mos = child_mos | origin_child_mos
            
            # Cancel all found child MOs recursively
            if all_child_mos:
                all_child_mos.action_cancel()
        
        return super(MrpProduction, self).action_cancel()
    
    @api.model
    def create(self, vals):
        """
        Override create to ensure proper parent-child linking for all sub-MOs
        """
        # If this MO has an origin that looks like another MO, try to link it
        if vals.get('origin') and 'parent_production_id' not in vals:
            # Extract the first MO name from origin (in case of multiple origins)
            origin_parts = vals['origin'].split(',')
            first_origin = origin_parts[0].strip()
            
            parent_mo = self.search([
                ('name', '=', first_origin),
                ('company_id', '=', vals.get('company_id', self.env.company.id))
            ], limit=1)
            
            if parent_mo:
                vals['parent_production_id'] = parent_mo.id
                # Copy project number from parent if not already set
                if not vals.get('project_number') and parent_mo.project_number:
                    vals['project_number'] = parent_mo.project_number
        
        return super(MrpProduction, self).create(vals)
    
    def force_cancel_mo_and_children(self):
        """
        Force cancel MO and all its children, bypassing all restrictions
        """
        # Get all MOs to cancel
        all_mos = self.env['mrp.production']
        
        # Find all children recursively
        def find_all_children(parent_mos):
            children = self.env['mrp.production']
            for parent in parent_mos:
                # Direct children
                direct = self.search([
                    ('parent_production_id', '=', parent.id),
                    ('state', 'not in', ['done', 'cancel'])
                ])
                # Origin-based children
                origin = self.search([
                    ('origin', 'ilike', parent.name),
                    ('state', 'not in', ['done', 'cancel']),
                    ('id', '!=', parent.id)
                ])
                found = direct | origin
                if found:
                    children |= found
                    children |= find_all_children(found)  # Recursive
            return children
        
        # Get all children
        all_children = find_all_children(self)
        all_mos = all_children | self
        
        # Cancel in reverse order (children first)
        for mo in sorted(all_mos, key=lambda x: x.id, reverse=True):
            if mo.state not in ['done', 'cancel']:
                # Cancel any work orders first
                if mo.workorder_ids:
                    mo.workorder_ids.filtered(
                        lambda wo: wo.state not in ['done', 'cancel']
                    ).write({'state': 'cancel'})
                
                # Cancel any stock moves
                if mo.move_raw_ids:
                    mo.move_raw_ids.filtered(
                        lambda m: m.state not in ['done', 'cancel']
                    )._action_cancel()
                
                if mo.move_finished_ids:
                    mo.move_finished_ids.filtered(
                        lambda m: m.state not in ['done', 'cancel']
                    )._action_cancel()
                
                # Force state change
                mo.write({'state': 'cancel'})
                mo.message_post(body=_('Force cancelled'))
        
        return True