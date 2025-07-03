from odoo import models, fields, api
from odoo.exceptions import UserError


class ProductCategoryCapacityWizard(models.TransientModel):
    _name = 'product.category.capacity.wizard'
    _description = 'Bulk Capacity Setup Wizard'

    setup_type = fields.Selection([
        ('year', 'Full Year Setup'),
        ('month', 'Single Month Setup'),
        ('range', 'Month Range Setup')
    ], string='Setup Type', required=True, default='month')
    
    category_ids = fields.Many2many(
        'product.category',
        string='Product Categories',
        required=True,
        help='Select categories to set up capacity for'
    )
    
    year = fields.Integer(
        string='Year',
        required=True,
        default=lambda self: fields.Date.today().year
    )
    
    month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='Month')
    
    month_from = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='From Month')
    
    month_to = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='To Month')
    
    default_capacity = fields.Float(
        string='Default Monthly Capacity',
        required=True,
        default=1000.0,
        help='Default capacity value to apply to all selected categories'
    )
    
    capacity_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
        default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
    )
    
    overwrite_existing = fields.Boolean(
        string='Overwrite Existing Records',
        default=False,
        help='If checked, existing capacity records will be overwritten'
    )
    
    line_ids = fields.One2many(
        'product.category.capacity.wizard.line',
        'wizard_id',
        string='Capacity Lines'
    )
    
    @api.onchange('setup_type')
    def _onchange_setup_type(self):
        if self.setup_type == 'month':
            self.month_from = False
            self.month_to = False
        elif self.setup_type == 'year':
            self.month = False
            self.month_from = False
            self.month_to = False
        elif self.setup_type == 'range':
            self.month = False
    
    @api.onchange('category_ids', 'setup_type', 'year', 'month', 'month_from', 'month_to', 'default_capacity')
    def _onchange_generate_lines(self):
        self.line_ids = [(5, 0, 0)]
        
        if not self.category_ids:
            return
        
        months = self._get_months_to_create()
        lines = []
        
        for category in self.category_ids:
            for month in months:
                lines.append((0, 0, {
                    'category_id': category.id,
                    'month': month,
                    'year': self.year,
                    'monthly_capacity': self.default_capacity,
                    'capacity_uom_id': self.capacity_uom_id.id
                }))
        
        self.line_ids = lines
    
    def _get_months_to_create(self):
        if self.setup_type == 'year':
            return [str(i).zfill(2) for i in range(1, 13)]
        elif self.setup_type == 'month':
            return [self.month] if self.month else []
        elif self.setup_type == 'range':
            if not self.month_from or not self.month_to:
                return []
            
            start = int(self.month_from)
            end = int(self.month_to)
            
            if start <= end:
                return [str(i).zfill(2) for i in range(start, end + 1)]
            else:
                return [str(i).zfill(2) for i in range(start, 13)] + [str(i).zfill(2) for i in range(1, end + 1)]
        
        return []
    
    def action_create_capacity_records(self):
        if not self.line_ids:
            raise UserError("No capacity lines to create. Please configure your selection.")
        
        Capacity = self.env['product.category.capacity']
        created_records = Capacity.browse()
        updated_records = Capacity.browse()
        
        for line in self.line_ids:
            existing = Capacity.search([
                ('category_id', '=', line.category_id.id),
                ('month', '=', line.month),
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
    
    month = fields.Selection([
        ('01', 'January'), ('02', 'February'), ('03', 'March'),
        ('04', 'April'), ('05', 'May'), ('06', 'June'),
        ('07', 'July'), ('08', 'August'), ('09', 'September'),
        ('10', 'October'), ('11', 'November'), ('12', 'December'),
    ], string='Month', required=True)
    
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
        help='Indicates if a record already exists for this category/month/year'
    )
    
    @api.depends('category_id', 'month', 'year')
    def _compute_existing_record(self):
        for line in self:
            if line.category_id and line.month and line.year:
                existing = self.env['product.category.capacity'].search([
                    ('category_id', '=', line.category_id.id),
                    ('month', '=', line.month),
                    ('year', '=', line.year)
                ])
                line.existing_record = bool(existing)
            else:
                line.existing_record = False