from odoo import models, fields, api
from odoo.exceptions import UserError


class ProductCategoryCapacityWizard(models.TransientModel):
    _name = 'product.category.capacity.wizard'
    _description = 'Bulk Capacity Setup Wizard'

    # Category selection
    category_ids = fields.Many2many(
        'product.category',
        string='Product Categories',
        required=True,
        help='Select categories to set up capacity for'
    )
    
    # Time period fields
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year
    )
    
    # Capacity settings
    default_capacity = fields.Float(
        string='Monthly Capacity',
        required=True,
        default=1000.0,
        help='Monthly capacity value to apply to all selected categories'
    )
    
    capacity_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
        default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
    )
    
    # Options
    overwrite_existing = fields.Boolean(
        string='Overwrite Existing Records',
        default=False,
        help='If checked, existing capacity records will be overwritten'
    )
    
    # Summary fields
    line_ids = fields.One2many(
        'product.category.capacity.wizard.line',
        'wizard_id',
        string='Capacity Lines'
    )
    
    @api.onchange('category_ids', 'year', 'default_capacity')
    def _onchange_generate_lines(self):
        """Generate preview lines based on selection"""
        self.line_ids = [(5, 0, 0)]  # Clear existing lines
        
        if not self.category_ids:
            return
        
        lines = []
        for category in self.category_ids:
            lines.append((0, 0, {
                'category_id': category.id,
                'month': 'Month',
                'year': self.year,
                'monthly_capacity': self.default_capacity,
                'capacity_uom_id': self.capacity_uom_id.id
            }))
        
        self.line_ids = lines
    
    def action_create_capacity_records(self):
        """Create capacity records based on wizard configuration"""
        if not self.line_ids:
            raise UserError("No capacity lines to create. Please configure your selection.")
        
        Capacity = self.env['product.category.capacity']
        created_records = Capacity.browse()
        updated_records = Capacity.browse()
        
        for line in self.line_ids:
            # Check if record already exists
            existing = Capacity.search([
                ('category_id', '=', line.category_id.id),
                ('year', '=', line.year)
            ])
            
            vals = {
                'category_id': line.category_id.id,
                'month': line.month,
                'year': line.year,
                'monthly_capacity': line.monthly_capacity,
                'capacity_uom_id': line.capacity_uom_id.id
            }
            
            if existing:
                if self.overwrite_existing:
                    existing.write(vals)
                    updated_records |= existing
            else:
                record = Capacity.create(vals)
                created_records |= record
        
        # Show summary message
        message = []
        if created_records:
            message.append(f"Created {len(created_records)} new capacity records")
        if updated_records:
            message.append(f"Updated {len(updated_records)} existing capacity records")
        
        if not message:
            message = ["No records were created or updated"]
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Capacity Setup Complete',
                'message': '. '.join(message),
                'type': 'success',
                'sticky': False,
            }
        }


class ProductCategoryCapacityWizardLine(models.TransientModel):
    _name = 'product.category.capacity.wizard.line'
    _description = 'Capacity Wizard Line'
    
    wizard_id = fields.Many2one(
        'product.category.capacity.wizard',
        string='Wizard',
        required=True,
        ondelete='cascade'
    )
    
    category_id = fields.Many2one(
        'product.category',
        string='Category',
        required=True
    )
    
    month = fields.Char(
        string='Month',
        required=True,
        default='Month'
    )
    
    year = fields.Integer(
        string='Year',
        required=True
    )
    
    monthly_capacity = fields.Float(
        string='Monthly Capacity',
        required=True
    )
    
    capacity_uom_id = fields.Many2one(
        'uom.uom',
        string='UoM',
        required=True
    )
    
    existing_record = fields.Boolean(
        string='Exists',
        compute='_compute_existing_record',
        help='Indicates if a record already exists for this category/year'
    )
    
    @api.depends('category_id', 'year')
    def _compute_existing_record(self):
        for line in self:
            if line.category_id and line.year:
                existing = self.env['product.category.capacity'].search([
                    ('category_id', '=', line.category_id.id),
                    ('year', '=', line.year)
                ])
                line.existing_record = bool(existing)
            else:
                line.existing_record = False